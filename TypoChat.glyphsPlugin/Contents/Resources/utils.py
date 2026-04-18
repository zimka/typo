# encoding: utf-8
"""Pure helpers: URL, TLS, API payload, messages request, response parsing (no Glyphs / UI)."""

import json
import ssl
import urllib.request

DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = "2048"

ANTHROPIC_VERSION = "2023-06-01"

MARKER_ISSUE_RECOGNIZED = "ISSUE RECOGNIZED"
MARKER_ISSUE_NOT_RECOGNIZED = "ISSUE NOT RECOGNIZED"
MARKER_PLAN_APPROVAL = "PLAN APPROVAL REQUIRED"
MARKER_DOD_PASSED = "DOD PASSED"
MARKER_DOD_FAILED = "DOD FAILED"

MAX_AGENT_ITERATIONS = 10

DEFAULT_SYSTEM_PROMPT = (
    "You are a type design assistant embedded in Glyphs.app. The user has a font open; "
    "you help them fix and refine glyphs via a small set of tools.\n\n"
    "Available tools:\n"
    "- list_masters(): list all masters of the currently open font.\n"
    "- list_glyphs(filter): list glyph names, optionally filtered by a substring.\n"
    "- get_glyph(name, master): return paths, nodes, anchors, metrics as structured text.\n"
    "- render_specimen(text, master, size): render the specimen text using the current state of "
    "the font and return a PNG. Call this to SEE the font.\n"
    "- move_nodes_where(glyph, master, predicate, delta): move nodes in glyph@master whose "
    "coordinates match `predicate` (keys among x, y with integer values) by `delta` "
    "(keys among dx, dy). Other nodes are untouched. This is the only edit tool.\n"
    "- save_snapshot(glyph_names): capture the current geometry of the listed glyphs. One "
    "slot only — a second call overwrites. You MUST call this BEFORE the first "
    "move_nodes_where so the user can revert and so diff_pre_post has a 'before' image.\n"
    "- reset_snapshot(): restore the geometry saved by save_snapshot. Use it if an edit "
    "attempt went the wrong way.\n"
    "- diff_pre_post(text, master): return three images — pre (from snapshot), post (from "
    "live font), and a red/green overlay (red=pre, green=post, yellow=overlap). Requires "
    "an active snapshot.\n\n"
    "Intent gating:\n"
    "Before entering the fix workflow, decide whether the user actually described a concrete "
    "font problem that can be verified visually. Do NOT call tools until then.\n\n"
    "Examples that DO trigger the fix workflow:\n"
    "  - 'The kerning between A and V looks too tight at 200.'\n"
    "  - 'Node at (520, 420) on glyph x should be at (520, 400).'\n\n"
    "Examples that do NOT trigger the workflow — reply in prose and, if helpful, ask 1-2 "
    "targeted questions about what they want to fix:\n"
    "  - 'Hello', 'Hi there', 'What can you do?'\n"
    "  - 'Test text hello', 'render something', 'show me a glyph' (no specific issue).\n"
    "  - 'Help me with my font' (too vague).\n\n"
    "Fix workflow (only when triggered):\n"
    "1. Produce a one-line Definition of Done and a primary_specimen text that directly "
    "triggers the issue.\n"
    "2. Call render_specimen once with the primary_specimen to see current state. If the issue "
    "is visible, emit:\n"
    "   ISSUE RECOGNIZED\n"
    "   If it is not, emit:\n"
    "   ISSUE NOT RECOGNIZED\n"
    "   and ask 2-4 clarifying questions, then stop.\n"
    "3. Read affected glyphs with get_glyph. Formulate a minimal fix plan: which exact nodes "
    "move, which do not. Then emit:\n"
    "   PLAN APPROVAL REQUIRED\n"
    "   and stop. Do not edit anything yet.\n"
    "4. After the user replies with 'approve', call save_snapshot(glyph_names=[...the glyphs "
    "you are about to edit...]) to capture the pre-fix state.\n"
    "5. Apply the fix with move_nodes_where. You may issue several calls if the plan has "
    "multiple atomic moves.\n"
    "6. Call diff_pre_post(text, master) with the SAME primary_specimen and master. It returns "
    "three images: pre (from snapshot), post (live), and the red/green overlay.\n"
    "7. Compare in your reply. If the fix matches the Definition of Done, emit:\n"
    "   DOD PASSED\n"
    "   Otherwise emit:\n"
    "   DOD FAILED\n"
    "   and briefly propose next step. If you want to retry, call reset_snapshot() to revert "
    "the font, revise the plan, then loop back to step 5 (the snapshot is kept, so the next "
    "diff_pre_post still compares against the original pre-fix state).\n\n"
    "Constraints:\n"
    "- Tools are for real font work. For greetings, capability questions, or ambiguous "
    "messages, reply in prose first — do not preemptively call tools to 'explore' or 'warm up'.\n"
    "- Never mutate the font before the user approves the plan.\n"
    "- Always save_snapshot BEFORE the first move_nodes_where in a run.\n"
    "- Always diff_pre_post ONCE after edits so the user sees the visual before/after.\n"
    "- Hard limit: 10 tool-use iterations. If DoD is still not closed by then, stop and report "
    "what was tried.\n"
    "- Keep responses concise. Long exploration dumps are not useful."
)


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
    """One-line English caption for the token usage TextBox."""
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


def build_messages_request_body(model, max_tokens, messages, system_text, tools=None):
    """
    Build an Anthropic Messages API request body.

    ``messages`` items may carry string content or a list of content blocks
    (for tool_use / tool_result turns) — the API accepts both and we pass through.
    """
    body = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": list(messages),
    }
    if system_text:
        body["system"] = system_text
    if tools:
        body["tools"] = list(tools)
    return body


def parse_assistant_response(payload):
    """
    Parse a successful Anthropic Messages response.

    Returns a dict with:
      - ``content_blocks``: raw ``content`` list from the payload (list of block dicts).
      - ``text``: concatenated text from all ``text`` blocks.
      - ``tool_uses``: list of ``{"id", "name", "input"}`` for each ``tool_use`` block.
      - ``stop_reason``: string from payload (``end_turn``, ``tool_use``, ``max_tokens``, ...).
      - ``usage``: normalized usage dict.
      - ``error``: None on success, else a user-facing error string (and other fields are empty).
    """
    out = {
        "content_blocks": [],
        "text": "",
        "tool_uses": [],
        "stop_reason": None,
        "usage": normalize_usage(None),
        "error": None,
    }
    if not isinstance(payload, dict):
        out["error"] = "[error] unexpected response: %s" % str(payload)[:400]
        return out

    if payload.get("type") == "error":
        inner = payload.get("error")
        if isinstance(inner, dict):
            msg = inner.get("message") or inner.get("type") or json.dumps(inner)
        else:
            msg = str(inner)
        out["error"] = "[error] %s" % msg
        return out

    err = payload.get("error")
    if isinstance(err, dict):
        msg = err.get("message") or err.get("type") or json.dumps(err)
        out["error"] = "[error] %s" % msg
        return out
    if isinstance(err, str) and err:
        out["error"] = "[error] %s" % err
        return out

    blocks = payload.get("content") or []
    if not isinstance(blocks, list):
        out["error"] = "[error] response has no content list"
        return out
    out["content_blocks"] = blocks

    text_parts = []
    tool_uses = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            text_parts.append(b.get("text") or "")
        elif t == "tool_use":
            tool_uses.append(
                {
                    "id": b.get("id") or "",
                    "name": b.get("name") or "",
                    "input": b.get("input") if isinstance(b.get("input"), dict) else {},
                }
            )
    out["text"] = "\n".join(p for p in text_parts if p).strip()
    out["tool_uses"] = tool_uses
    out["stop_reason"] = payload.get("stop_reason")
    out["usage"] = normalize_usage(payload.get("usage"))
    return out


def normalize_tool_result_content(raw):
    """
    Normalize a tool executor's return value into a list of Anthropic ``tool_result`` content blocks.

    Accepts:
      - str            → ``[{"type":"text","text":raw}]``
      - bytes (PNG)    → ``[{"type":"image","source":{"type":"base64","media_type":"image/png","data":<b64>}}]``
      - dict (single block)  → ``[dict]``
      - list of dicts / strs → normalized elementwise
      - None           → ``[{"type":"text","text":"(no content)"}]``
    """
    import base64

    def _block_for_item(item):
        if isinstance(item, (bytes, bytearray)):
            b64 = base64.b64encode(bytes(item)).decode("ascii")
            return {
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            }
        if isinstance(item, str):
            return {"type": "text", "text": item}
        if isinstance(item, dict):
            if item.get("type") in ("text", "image"):
                return item
            return {"type": "text", "text": json.dumps(item, ensure_ascii=False)}
        return {"type": "text", "text": str(item)}

    if raw is None:
        return [{"type": "text", "text": "(no content)"}]
    if isinstance(raw, list):
        return [_block_for_item(x) for x in raw] or [{"type": "text", "text": "(empty)"}]
    return [_block_for_item(raw)]


def post_messages_request(body, url, auth_value):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("anthropic-version", ANTHROPIC_VERSION)
    req.add_header("Authorization", "OAuth %s" % auth_value.strip())
    with urllib.request.urlopen(req, timeout=600, context=ssl_context()) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw) if raw else {}
