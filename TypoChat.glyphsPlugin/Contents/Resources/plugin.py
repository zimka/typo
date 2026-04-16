# encoding: utf-8
"""Typo Chat — Messages API (Claude-compatible) with configurable base URL and OAuth key."""

import threading

import objc
from AppKit import NSAlert, NSMenuItem
from Foundation import NSOperationQueue
from GlyphsApp import Glyphs, WINDOW_MENU
from GlyphsApp.plugins import GeneralPlugin
from vanilla import Button, EditText, TextBox, TextEditor, Window

from state import ChatState, migration_default_strings

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


def _show_alert(title, text):
    """Modal dialog; ``Glyphs.showMessage`` is not available on all Glyphs builds."""
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(text)
    alert.runModal()


def _load_persistent_settings(state):
    """Load settings from JSON blob, or migrate from legacy flat keys if blob is absent."""
    blob = _get_default("settingsJson", "")
    assert blob and str(blob).strip()
    state.set_settings_json(str(blob))


class TypoChatPlugin(GeneralPlugin):
    windowName = "com.typo.TypoChat.main"
    _frame_autosave_set = False

    @objc.python_method
    def _transcript_text_from_messages(self):
        parts = []
        for m in self._state.messages:
            role = m.get("role")
            c = m.get("content") or ""
            if role == "user":
                parts.append("You: %s\n" % c)
            elif role == "assistant":
                parts.append("Assistant: %s\n\n" % c)
        return "".join(parts)

    @objc.python_method
    def _build_window(self):
        """Create or replace ``self.w``. Vanilla forbids ``open()`` after close; rebuild when ``_window`` is None."""
        self._frame_autosave_set = False
        s = self._state.settings
        self.w = Window((600, 760), self.name, minSize=(560, 680))

        y = 12
        self.w.baseUrlLabel = TextBox((12, y, 300, 14), "Base URL (POST → …/v1/messages)")
        y += 18
        self.w.baseUrl = EditText(
            (12, y, -12, 22),
            s["baseUrl"],
            placeholder="https://your-provider.example.com",
            continuous=False,
        )
        y += 30

        self.w.apiKeyLabel = TextBox((12, y, 300, 14), "OAuth / API key (Authorization: OAuth …)")
        y += 18
        self.w.apiKey = EditText(
            (12, y, -12, 22),
            s["apiKey"],
            placeholder="Paste token",
            continuous=False,
        )
        y += 30

        self.w.modelLabel = TextBox((12, y, 120, 14), "Model")
        y += 18
        self.w.model = EditText(
            (12, y, -12, 22),
            s["model"],
            continuous=False,
        )
        y += 30

        self.w.maxTokensLabel = TextBox((12, y, 200, 14), "Max tokens")
        y += 18
        self.w.maxTokens = EditText(
            (12, y, 120, 22),
            s["maxTokens"],
            continuous=False,
        )
        y += 30

        self.w.systemLabel = TextBox((12, y, 200, 14), "System prompt")
        y += 18
        self.w.systemPrompt = TextEditor(
            (12, y, -12, 72),
            text=s["systemPrompt"],
            checksSpelling=True,
        )
        y += 80

        self.w.transcriptLabel = TextBox((12, y, 200, 14), "Transcript")
        y += 18
        self.w.transcript = TextEditor(
            (12, y, -12, 200),
            text=self._transcript_text_from_messages(),
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
    def settings(self):
        self.name = Glyphs.localize(
            {
                "en": "Typo Chat",
                "de": "Typo Chat",
                "fr": "Typo Chat",
                "es": "Typo Chat",
            }
        )
        self._state = ChatState()
        _load_persistent_settings(self._state)
        self._build_window()

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
        if getattr(self.w, "_window", None) is None:
            self._build_window()
        self.w.open()
        ns_win = self.w.getNSWindow()
        if ns_win is not None:
            if not self._frame_autosave_set:
                ns_win.setFrameAutosaveName_(self.windowName)
                self._frame_autosave_set = True
            ns_win.makeKeyAndOrderFront_(self)

    @objc.python_method
    def _save_settings_from_ui(self):
        self._state.update_settings_from_ui_fields(
            (self.w.baseUrl.get() or "").strip(),
            (self.w.apiKey.get() or "").strip(),
            (self.w.model.get() or "").strip(),
            (self.w.maxTokens.get() or "").strip(),
            self.w.systemPrompt.get() or "",
        )
        _set_default("settingsJson", self._state.get_settings_json())

    @objc.python_method
    def _append_transcript(self, block):
        prev = self.w.transcript.get() or ""
        self.w.transcript.set((prev + block) if prev else block)

    @objc.python_method
    def _run_on_main(self, fn):
        NSOperationQueue.mainQueue().addOperationWithBlock_(fn)

    @objc.python_method
    def _on_send_(self, sender):
        text = (self.w.inputField.get() or "").strip()
        if not text:
            return

        self._save_settings_from_ui()
        err = self._state.validate_setting_errors()
        if err:
            _show_alert("Typo Chat", err)
            return

        self._state.append_user(text)
        self._append_transcript("You: %s\n" % text)
        self.w.inputField.set("")
        self.w.sendButton.enable(False)

        def worker():
            reply_text, err_out = self._state.send_messages_request_and_append_assistant()

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
        self._state.clear()
        self.w.transcript.set("")
        self._state.reset_system_prompt_to_default()
        self.w.systemPrompt.set(self._state.settings["systemPrompt"])
        self.w.inputField.set("")
        self._save_settings_from_ui()

    @objc.python_method
    def __file__(self):
        return __file__
