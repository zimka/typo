# encoding: utf-8
"""Conversation state for Typo Chat (no UI / Glyphs)."""

import json
import urllib.error

from utils import (
    DEFAULT_CACHE_CONTROL,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    _messages_endpoint,
    assistant_reply_or_error,
    build_messages_request_body,
    format_usage_caption,
    normalize_usage,
    parse_max_tokens,
    post_messages_request,
)

_SETTINGS_KEYS = frozenset(
    {"baseUrl", "apiKey", "model", "maxTokens", "systemPrompt"}
)

_USAGE_SUM_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def migration_default_strings():
    """Fallbacks for reading legacy flat Glyphs.defaults keys (model / maxTokens / systemPrompt)."""
    return DEFAULT_MODEL, DEFAULT_MAX_TOKENS, DEFAULT_SYSTEM_PROMPT


class ChatState:
    """Holds chat messages and persisted UI settings (stored as JSON in Glyphs.defaults by the plugin)."""

    def __init__(self):
        self._messages = []
        self._last_usage = None
        self._usage_session = {k: 0 for k in _USAGE_SUM_KEYS}
        self.settings = {
            "baseUrl": "",
            "apiKey": "",
            "model": DEFAULT_MODEL,
            "maxTokens": DEFAULT_MAX_TOKENS,
            "systemPrompt": DEFAULT_SYSTEM_PROMPT,
        }

    @property
    def messages(self):
        return self._messages

    def append_user(self, content):
        self._messages.append({"role": "user", "content": content})

    def append_assistant(self, content):
        self._messages.append({"role": "assistant", "content": content})

    def update_settings_from_ui_fields(
        self, base_url, api_key, model, max_tokens, system_prompt
    ):
        """Assign widget values and apply the same normalization as :meth:`_normalize_settings`."""
        self.settings["baseUrl"] = base_url
        self.settings["apiKey"] = api_key
        self.settings["model"] = model
        self.settings["maxTokens"] = max_tokens
        self.settings["systemPrompt"] = system_prompt
        self._normalize_settings()

    def reset_system_prompt_to_default(self):
        """Set system prompt in ``settings`` to the factory default (e.g. New chat)."""
        self.settings["systemPrompt"] = DEFAULT_SYSTEM_PROMPT

    def validate_setting_errors(self):
        """
        Return a non-empty user-facing message if ``settings`` are invalid for sending;
        otherwise return ``""``.
        """
        base = (self.settings.get("baseUrl") or "").strip()
        if not _messages_endpoint(base):
            return "Set Base URL first."
        auth = (self.settings.get("apiKey") or "").strip()
        if not auth:
            return "Set OAuth / API key first."
        return ""

    def send_messages_request_and_append_assistant(self):
        """
        POST the current ``messages`` using ``settings``, then append the assistant turn on success.

        ``messages`` must already include the latest user message. Call
        :meth:`validate_setting_errors` before invoking. Returns
        ``(reply_text, None, usage_norm)`` on success (``reply_text`` may be empty string), or
        ``(None, err_text, None)`` on failure (HTTP, transport, or API-level error payload).
        """
        s = self.settings
        model = (s.get("model") or "").strip() or DEFAULT_MODEL
        max_tokens = parse_max_tokens(s.get("maxTokens") or "")
        system_text = (s.get("systemPrompt") or "").strip()
        base = (s.get("baseUrl") or "").strip()
        url = _messages_endpoint(base)
        auth = s.get("apiKey") or ""

        err_out = None
        reply_text = None
        usage_norm = None
        try:
            body = build_messages_request_body(
                model,
                max_tokens,
                self._messages,
                system_text,
                cache_control=DEFAULT_CACHE_CONTROL,
            )
            payload = post_messages_request(body, url, auth)
            got_reply, got_err = assistant_reply_or_error(payload)
            if got_err is not None:
                err_out = got_err
            else:
                reply_text = got_reply
                self.append_assistant(reply_text)
                raw_usage = payload.get("usage") if isinstance(payload, dict) else None
                usage_norm = normalize_usage(raw_usage)
                self._last_usage = usage_norm
                for k in _USAGE_SUM_KEYS:
                    self._usage_session[k] += usage_norm[k]
        except urllib.error.HTTPError as e:
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = str(e)
            err_out = "[HTTP %s] %s" % (e.code, err_body[:4000])
        except Exception as e:
            err_out = str(e)
        return reply_text, err_out, usage_norm

    def usage_caption(self):
        """English one-line string for token usage UI (last turn + session totals)."""
        return format_usage_caption(self._last_usage, self._usage_session)

    def clear(self):
        self._messages = []
        self._last_usage = None
        self._usage_session = {k: 0 for k in _USAGE_SUM_KEYS}

    def get_settings_json(self):
        """Serialize ``settings`` to a JSON string for Glyphs.defaults."""
        return json.dumps(self.settings, ensure_ascii=False, sort_keys=True)

    def set_settings_json(self, raw):
        """
        Deserialize JSON into ``settings``. Unknown keys are ignored.
        Empty or invalid input leaves defaults unchanged.
        """
        if raw is None:
            return
        text = str(raw).strip()
        if not text:
            return
        try:
            obj = json.loads(text)
        except (TypeError, ValueError):
            return
        if not isinstance(obj, dict):
            return
        self._merge_settings_dict(obj)

    def migrate_from_legacy_flat(
        self,
        baseUrl="",
        apiKey="",
        model="",
        maxTokens="",
        systemPrompt="",
    ):
        """Fill settings from pre-JSON flat Glyphs.defaults keys (one-time migration)."""
        if baseUrl:
            self.settings["baseUrl"] = str(baseUrl)
        if apiKey:
            self.settings["apiKey"] = str(apiKey)
        if model is not None and str(model).strip():
            self.settings["model"] = str(model).strip()
        if maxTokens is not None and str(maxTokens).strip():
            self.settings["maxTokens"] = str(maxTokens).strip()
        if systemPrompt is not None:
            self.settings["systemPrompt"] = str(systemPrompt)
        self._normalize_settings()

    def _merge_settings_dict(self, obj):
        s = self.settings
        for k in _SETTINGS_KEYS:
            if k in obj and obj[k] is not None:
                s[k] = str(obj[k])
        self._normalize_settings()

    def _normalize_settings(self):
        s = self.settings
        s["model"] = (s.get("model") or "").strip() or DEFAULT_MODEL
        s["maxTokens"] = (s.get("maxTokens") or "").strip() or DEFAULT_MAX_TOKENS
        s["systemPrompt"] = s.get("systemPrompt") or ""
