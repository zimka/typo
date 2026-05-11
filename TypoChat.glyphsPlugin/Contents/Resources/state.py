# encoding: utf-8
"""Conversation state and agent loop for Typo Chat (no UI / Glyphs dependencies)."""

import json
import urllib.error

from utils import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    MARKER_PLAN_APPROVAL,
    MAX_AGENT_ITERATIONS,
    _chat_endpoint,
    format_usage_caption,
    normalize_tool_result_content,
    normalize_usage,
    parse_max_tokens,
)
from provider import (
    build_request_body,
    post_request,
    parse_response,
)

_SETTINGS_KEYS = frozenset(
    {"baseUrl", "apiKey", "model", "maxTokens", "systemPrompt"}
)

# Keys loaded from persisted defaults. ``systemPrompt`` is intentionally excluded during
# active development so that edits to ``DEFAULT_SYSTEM_PROMPT`` always take effect after a
# Glyphs restart, without being shadowed by a stale value cached in ``Glyphs.defaults``.
_PERSISTED_LOAD_KEYS = frozenset({"baseUrl", "apiKey", "model", "maxTokens"})

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
    """
    Holds chat messages, persisted UI settings and the agent loop.

    ``messages`` entries have the shape ``{"role": "user"|"assistant", "content": str | list}``;
    content is a list of Anthropic content blocks for tool-use / tool-result turns.
    """

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

    def append_assistant_blocks(self, blocks):
        self._messages.append({"role": "assistant", "content": list(blocks)})

    def update_settings_from_ui_fields(
        self, base_url, api_key, model, max_tokens, system_prompt
    ):
        self.settings["baseUrl"] = base_url
        self.settings["apiKey"] = api_key
        self.settings["model"] = model
        self.settings["maxTokens"] = max_tokens
        self.settings["systemPrompt"] = system_prompt
        self._normalize_settings()

    def reset_system_prompt_to_default(self):
        self.settings["systemPrompt"] = DEFAULT_SYSTEM_PROMPT

    def validate_setting_errors(self):
        base = (self.settings.get("baseUrl") or "").strip()
        if not _chat_endpoint(base):
            return "Set Base URL first."
        auth = (self.settings.get("apiKey") or "").strip()
        if not auth:
            return "Set API key first."
        return ""

    def run_agent_turn(
        self,
        user_text,
        tool_executor,
        tool_schemas,
        on_event,
        cancel_event=None,
    ):
        """
        Run one "Send" cycle: append ``user_text``, then loop with Anthropic tool-use until the
        model stops with ``end_turn`` / ``max_tokens`` / ``stop_sequence`` or the iteration cap
        is reached.

        ``tool_executor(name, input_dict) -> content`` is expected to run on main thread and
        return a value accepted by :func:`normalize_tool_result_content`. Exceptions raised by
        the executor are caught and forwarded to the model as a ``tool_result`` with
        ``is_error: true``.

        ``on_event(dict)`` is called for every significant step. Event kinds:
          - ``user``:                {"kind", "text"}
          - ``assistant_text``:      {"kind", "text"}
          - ``tool_use``:            {"kind", "id", "name", "input"}
          - ``tool_result``:         {"kind", "id", "name", "content", "is_error"}
          - ``approval_required``:   {"kind", "text"}
          - ``done``:                {"kind", "text", "stop_reason"}
          - ``iteration_limit``:     {"kind"}
          - ``cancelled``:           {"kind"}
          - ``error``:               {"kind", "text"}
          - ``usage_updated``:       {"kind", "last", "session"}
        """
        if user_text is not None:
            self.append_user(user_text)
            on_event({"kind": "user", "text": user_text})

        s = self.settings
        model = (s.get("model") or "").strip() or DEFAULT_MODEL
        max_tokens = parse_max_tokens(s.get("maxTokens") or "")
        system_text = (s.get("systemPrompt") or "").strip()
        base = (s.get("baseUrl") or "").strip()
        url = _chat_endpoint(base)
        auth = s.get("apiKey") or ""

        iteration = 0
        while iteration < MAX_AGENT_ITERATIONS:
            if cancel_event is not None and cancel_event.is_set():
                on_event({"kind": "cancelled"})
                return

            try:
                body = build_request_body(
                    model, max_tokens, self._messages, system_text, tools=tool_schemas
                )
                payload = post_request(body, url, auth)
            except urllib.error.HTTPError as e:
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = str(e)
                on_event({"kind": "error", "text": "[HTTP %s] %s" % (e.code, err_body[:4000])})
                return
            except Exception as e:
                on_event({"kind": "error", "text": str(e)})
                return

            parsed = parse_response(payload)
            if parsed["error"]:
                on_event({"kind": "error", "text": parsed["error"]})
                return

            usage = parsed["usage"]
            self._last_usage = usage
            for k in _USAGE_SUM_KEYS:
                self._usage_session[k] += usage.get(k, 0)
            on_event(
                {
                    "kind": "usage_updated",
                    "last": usage,
                    "session": dict(self._usage_session),
                }
            )

            self.append_assistant_blocks(parsed["content_blocks"])

            if parsed["text"]:
                on_event({"kind": "assistant_text", "text": parsed["text"]})

            tool_uses = parsed["tool_uses"]
            for tu in tool_uses:
                on_event(
                    {
                        "kind": "tool_use",
                        "id": tu["id"],
                        "name": tu["name"],
                        "input": tu["input"],
                    }
                )

            stop_reason = parsed["stop_reason"]
            if not tool_uses or stop_reason != "tool_use":
                if MARKER_PLAN_APPROVAL in (parsed["text"] or ""):
                    on_event({"kind": "approval_required", "text": parsed["text"]})
                else:
                    on_event({"kind": "done", "text": parsed["text"], "stop_reason": stop_reason})
                return

            tool_result_blocks = []
            for tu in tool_uses:
                if cancel_event is not None and cancel_event.is_set():
                    on_event({"kind": "cancelled"})
                    return
                try:
                    raw_result = tool_executor(tu["name"], tu["input"] or {})
                    is_error = False
                except Exception as e:
                    raw_result = "[tool error] %s" % e
                    is_error = True
                content_blocks = normalize_tool_result_content(raw_result)
                block = {
                    "type": "tool_result",
                    "tool_call_id": tu["id"],
                    "content": content_blocks,
                }
                if is_error:
                    block["is_error"] = True
                tool_result_blocks.append(block)
                on_event(
                    {
                        "kind": "tool_result",
                        "id": tu["id"],
                        "name": tu["name"],
                        "content": content_blocks,
                        "is_error": is_error,
                    }
                )

            self.append_user(tool_result_blocks)
            iteration += 1

        on_event({"kind": "iteration_limit"})

    def usage_caption(self):
        return format_usage_caption(self._last_usage, self._usage_session)

    def clear(self):
        self._messages = []
        self._last_usage = None
        self._usage_session = {k: 0 for k in _USAGE_SUM_KEYS}

    def get_settings_json(self):
        return json.dumps(self.settings, ensure_ascii=False, sort_keys=True)

    def set_settings_json(self, raw):
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
        systemPrompt=None,
    ):
        """Load from pre-JSON flat ``Glyphs.defaults`` keys. ``systemPrompt`` is ignored."""
        del systemPrompt
        if baseUrl:
            self.settings["baseUrl"] = str(baseUrl)
        if apiKey:
            self.settings["apiKey"] = str(apiKey)
        if model is not None and str(model).strip():
            self.settings["model"] = str(model).strip()
        if maxTokens is not None and str(maxTokens).strip():
            self.settings["maxTokens"] = str(maxTokens).strip()
        self._normalize_settings()

    def _merge_settings_dict(self, obj):
        s = self.settings
        for k in _PERSISTED_LOAD_KEYS:
            if k in obj and obj[k] is not None:
                s[k] = str(obj[k])
        self._normalize_settings()

    def _normalize_settings(self):
        s = self.settings
        s["model"] = (s.get("model") or "").strip() or DEFAULT_MODEL
        s["maxTokens"] = (s.get("maxTokens") or "").strip() or DEFAULT_MAX_TOKENS
        s["systemPrompt"] = s.get("systemPrompt") or ""
