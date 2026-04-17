# encoding: utf-8
"""Pure helpers: URL, TLS, API payload, messages request (no Glyphs / UI)."""

import json
import ssl
import urllib.request

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant for type design and Glyphs.app. "
    "Answer clearly and concisely."
)

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = "2048"

# Anthropic Messages API; used for prompt caching and request compatibility.
ANTHROPIC_VERSION = "2023-06-01"

# Prompt caching: 1h TTL (see Anthropic prompt caching docs).
DEFAULT_CACHE_CONTROL = {"type": "ephemeral", "ttl": "1h"}

_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _messages_endpoint(base_url):
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    return base + "/v1/messages"


def extract_assistant_text(payload):
    """Parse Anthropic-style message response JSON."""
    if not isinstance(payload, dict):
        return str(payload)
    if payload.get("type") == "error":
        inner = payload.get("error")
        if isinstance(inner, dict):
            msg = inner.get("message") or inner.get("type") or json.dumps(inner)
        else:
            msg = str(inner)
        return "[error] %s" % msg
    err = payload.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("type") or json.dumps(err)
        return "[error] %s" % msg
    if isinstance(err, str):
        return "[error] %s" % err
    blocks = payload.get("content")
    if isinstance(blocks, list):
        parts = []
        for block in blocks:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text":
                parts.append(block.get("text") or "")
            elif block.get("type") == "tool_use":
                parts.append("[tool_use] %s" % block.get("name", ""))
        return "\n".join(parts).strip() or "(empty assistant content)"
    return json.dumps(payload, ensure_ascii=False)[:4000]


def ssl_context():
    # TODO: Use a proper CA bundle (cacert.pem next to this file, SSL_CERT_FILE, or certifi)
    # instead of disabling TLS verification. Glyphs' embedded Python often has no CA store.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def parse_max_tokens(raw, default_str=DEFAULT_MAX_TOKENS):
    s = (raw or "").strip() or default_str
    try:
        return max(1, min(200000, int(s)))
    except ValueError:
        return int(default_str)


def normalize_usage(usage):
    """Return Anthropic ``usage`` dict with known integer keys defaulting to 0."""
    out = {k: 0 for k in _USAGE_KEYS}
    if not isinstance(usage, dict):
        return out
    for k in _USAGE_KEYS:
        v = usage.get(k)
        if v is None:
            continue
        try:
            out[k] = max(0, int(v))
        except (TypeError, ValueError):
            continue
    return out


def format_usage_caption(last_usage, session_totals):
    """
    One-line English caption for the token usage TextBox.
    ``session_totals`` is a dict of summed normalize_usage keys (same as _USAGE_KEYS).
    """
    z = {k: 0 for k in _USAGE_KEYS}
    if isinstance(session_totals, dict):
        for k in _USAGE_KEYS:
            try:
                z[k] = max(0, int(session_totals.get(k, 0)))
            except (TypeError, ValueError):
                z[k] = 0

    def fmt(n):
        n = int(n)
        if n >= 10000:
            return "%.1fk" % (n / 1000.0)
        return str(n)

    sess_in = z["input_tokens"] + z["cache_read_input_tokens"] + z["cache_creation_input_tokens"]
    sess_out = z["output_tokens"]
    session_part = "session: %s in + %s out" % (fmt(sess_in), fmt(sess_out))

    if last_usage is None:
        return "Tokens — last: — · %s" % session_part

    lu = normalize_usage(last_usage)
    last_in = lu["input_tokens"] + lu["cache_read_input_tokens"] + lu["cache_creation_input_tokens"]
    last_out = lu["output_tokens"]
    last_part = "last: %s in + %s out" % (fmt(last_in), fmt(last_out))
    return "Tokens — %s · %s" % (last_part, session_part)


def build_messages_request_body(model, max_tokens, messages, system_text, cache_control=None):
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": list(messages),
    }
    if system_text:
        body["system"] = system_text
    if cache_control:
        body["cache_control"] = cache_control
    return body


def assistant_reply_or_error(payload):
    """
    Interpret API JSON payload after a successful HTTP response.
    Returns (reply_text, None) or (None, err_text) matching plugin behaviour.
    """
    text = extract_assistant_text(payload)
    if isinstance(payload, dict) and payload.get("type") == "error":
        return None, text
    if text.startswith("[error]"):
        return None, text
    return text, None


def post_messages_request(body, url, auth_value):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("anthropic-version", ANTHROPIC_VERSION)
    req.add_header("Authorization", "OAuth %s" % auth_value.strip())
    with urllib.request.urlopen(req, timeout=600, context=ssl_context()) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else {}
