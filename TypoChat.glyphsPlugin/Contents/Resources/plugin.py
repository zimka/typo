# encoding: utf-8
"""Typo Chat — Messages API (Claude-compatible) with configurable base URL and OAuth key."""

import json
import ssl
import threading
import urllib.error
import urllib.request

import objc
from AppKit import NSMenuItem
from Foundation import NSOperationQueue
from GlyphsApp import Glyphs, WINDOW_MENU
from GlyphsApp.plugins import GeneralPlugin
from vanilla import Button, EditText, TextBox, TextEditor, Window

_DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful assistant for type design and Glyphs.app. "
    "Answer clearly and concisely."
)

_DEFAULT_MODEL = "claude-sonnet-4-6"
_DEFAULT_MAX_TOKENS = "2048"

_DEFAULTS_PREFIX = "com.typo."


def _defaults_key(name):
    return _DEFAULTS_PREFIX + name


def _get_default(name, fallback=""):
    try:
        d = Glyphs.defaults
        if d is None:
            return fallback
        v = d[_defaults_key(name)]
        if v is None:
            return fallback
        return str(v)
    except Exception:
        return fallback


def _set_default(name, value):
    try:
        Glyphs.defaults[_defaults_key(name)] = value
    except Exception:
        pass


def _ssl_context():
    # TODO: Use a proper CA bundle (cacert.pem next to this file, SSL_CERT_FILE, or certifi)
    # instead of disabling TLS verification. Glyphs' embedded Python often has no CA store.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _messages_endpoint(base_url):
    base = (base_url or "").strip().rstrip("/")
    if not base:
        return ""
    return base + "/v1/messages"


def _extract_assistant_text(payload):
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


class TypoChatPlugin(GeneralPlugin):
    windowName = "com.typo.TypoChat.main"
    _frame_autosave_set = False

    @objc.python_method
    def settings(self):
        self.name = Glyphs.localize(
            {
                "en": "Typo Chat",
                "de": "Typo Chat",
                "fr": "Typo Chat",
                "es": "Typo Chat",
            }
        )
        self._messages = []

        self.w = Window((600, 760), self.name, minSize=(560, 680))

        y = 12
        self.w.baseUrlLabel = TextBox((12, y, 300, 14), "Base URL (POST → …/v1/messages)")
        y += 18
        self.w.baseUrl = EditText(
            (12, y, -12, 22),
            _get_default("baseUrl", ""),
            placeholder="https://your-provider.example.com",
            continuous=False,
        )
        y += 30

        self.w.apiKeyLabel = TextBox((12, y, 300, 14), "OAuth / API key (Authorization: OAuth …)")
        y += 18
        self.w.apiKey = EditText(
            (12, y, -12, 22),
            _get_default("apiKey", ""),
            placeholder="Paste token",
            continuous=False,
        )
        y += 30

        self.w.modelLabel = TextBox((12, y, 120, 14), "Model")
        y += 18
        self.w.model = EditText(
            (12, y, -12, 22),
            _get_default("model", _DEFAULT_MODEL),
            continuous=False,
        )
        y += 30

        self.w.maxTokensLabel = TextBox((12, y, 200, 14), "Max tokens")
        y += 18
        self.w.maxTokens = EditText(
            (12, y, 120, 22),
            _get_default("maxTokens", _DEFAULT_MAX_TOKENS),
            continuous=False,
        )
        y += 30

        self.w.systemLabel = TextBox((12, y, 200, 14), "System prompt")
        y += 18
        self.w.systemPrompt = TextEditor(
            (12, y, -12, 72),
            text=_get_default("systemPrompt", _DEFAULT_SYSTEM_PROMPT),
            checksSpelling=True,
        )
        y += 80

        self.w.transcriptLabel = TextBox((12, y, 200, 14), "Transcript")
        y += 18
        self.w.transcript = TextEditor(
            (12, y, -12, 200),
            text="",
            readOnly=True,
            checksSpelling=False,
        )
        y += 208

        self.w.inputLabel = TextBox((12, y, 200, 14), "Message")
        y += 18
        self.w.inputField = EditText(
            (12, y, -12, 22),
            "",
            placeholder="Type a message…",
            continuous=False,
        )
        y += 30

        self.w.sendButton = Button(
            (12, y, 120, 22),
            "Send",
            callback=self._on_send_,
        )
        self.w.newChatButton = Button(
            (140, y, 120, 22),
            "New chat",
            callback=self._on_new_chat_,
        )

    @objc.python_method
    def start(self):
        if Glyphs.buildNumber >= 3320:
            from GlyphsApp.UI import MenuItem

            new_menu_item = MenuItem(self.name, action=self.showWindow_, target=self)
        else:
            new_menu_item = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                self.name, self.showWindow_, ""
            )
            new_menu_item.setTarget_(self)
        Glyphs.menu[WINDOW_MENU].append(new_menu_item)

    def showWindow_(self, sender):
        self.w.open()
        ns_win = self.w.getNSWindow()
        if ns_win is not None:
            if not self._frame_autosave_set:
                ns_win.setFrameAutosaveName_(self.windowName)
                self._frame_autosave_set = True
            ns_win.makeKeyAndOrderFront_(self)

    @objc.python_method
    def _save_settings_from_ui(self):
        _set_default("baseUrl", (self.w.baseUrl.get() or "").strip())
        _set_default("apiKey", (self.w.apiKey.get() or "").strip())
        _set_default("model", (self.w.model.get() or "").strip() or _DEFAULT_MODEL)
        _set_default("maxTokens", (self.w.maxTokens.get() or "").strip() or _DEFAULT_MAX_TOKENS)
        _set_default("systemPrompt", self.w.systemPrompt.get() or "")

    @objc.python_method
    def _parse_max_tokens(self):
        raw = (self.w.maxTokens.get() or "").strip() or _DEFAULT_MAX_TOKENS
        try:
            return max(1, min(200000, int(raw)))
        except ValueError:
            return int(_DEFAULT_MAX_TOKENS)

    @objc.python_method
    def _append_transcript(self, block):
        prev = self.w.transcript.get() or ""
        self.w.transcript.set((prev + block) if prev else block)

    @objc.python_method
    def _run_on_main(self, fn):
        NSOperationQueue.mainQueue().addOperationWithBlock_(fn)

    @objc.python_method
    def _post_messages_request(self, body, url, auth_value):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", "OAuth %s" % auth_value.strip())
        with urllib.request.urlopen(req, timeout=600, context=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}

    @objc.python_method
    def _on_send_(self, sender):
        text = (self.w.inputField.get() or "").strip()
        if not text:
            return

        base_url = (self.w.baseUrl.get() or "").strip()
        auth = (self.w.apiKey.get() or "").strip()
        url = _messages_endpoint(base_url)
        if not url:
            Glyphs.showMessage("Typo Chat", "Set Base URL first.")
            return
        if not auth:
            Glyphs.showMessage("Typo Chat", "Set OAuth / API key first.")
            return

        self._save_settings_from_ui()
        model = (self.w.model.get() or "").strip() or _DEFAULT_MODEL
        max_tokens = self._parse_max_tokens()
        system_text = (self.w.systemPrompt.get() or "").strip()

        self._messages.append({"role": "user", "content": text})
        self._append_transcript("You: %s\n" % text)
        self.w.inputField.set("")
        self.w.sendButton.enable(False)

        def worker():
            err_out = None
            reply_text = None
            try:
                body = {
                    "model": model,
                    "max_tokens": max_tokens,
                    "messages": list(self._messages),
                }
                if system_text:
                    body["system"] = system_text
                payload = self._post_messages_request(body, url, auth)
                text = _extract_assistant_text(payload)
                if isinstance(payload, dict) and payload.get("type") == "error":
                    err_out = text
                elif text.startswith("[error]"):
                    err_out = text
                else:
                    reply_text = text
                    self._messages.append(
                        {"role": "assistant", "content": reply_text}
                    )
            except urllib.error.HTTPError as e:
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = str(e)
                err_out = "[HTTP %s] %s" % (e.code, err_body[:4000])
            except Exception as e:
                err_out = str(e)

            def finish():
                self.w.sendButton.enable(True)
                if err_out:
                    self._append_transcript("%s\n\n" % err_out)
                elif reply_text is not None:
                    self._append_transcript("Assistant: %s\n\n" % reply_text)

            self._run_on_main(finish)

        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def _on_new_chat_(self, sender):
        self._messages = []
        self.w.transcript.set("")
        self.w.systemPrompt.set(_DEFAULT_SYSTEM_PROMPT)
        self.w.inputField.set("")
        self._save_settings_from_ui()

    @objc.python_method
    def __file__(self):
        return __file__
