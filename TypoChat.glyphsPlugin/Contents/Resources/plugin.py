# encoding: utf-8
"""Typo Chat — agentic Chat Completions API (OpenAI-compatible) with tool use and human-in-the-loop."""

import threading

import objc
from AppKit import (
    NSAlert,
    NSAttributedString,
    NSBlockOperation,
    NSColor,
    NSFont,
    NSImage,
    NSMenuItem,
    NSTextAttachment,
)
from Foundation import NSData, NSOperationQueue, NSSize
from GlyphsApp import Glyphs, WINDOW_MENU
from GlyphsApp.plugins import GeneralPlugin
from vanilla import Button, EditText, TextBox, TextEditor, Window

import tools
from state import ChatState, migration_default_strings

_DEFAULTS_PREFIX = "com.typo."

PLUGIN_VERSION = "0.3.4"

_TRANSCRIPT_IMAGE_MAX_W = 440
_TRANSCRIPT_IMAGE_MAX_H = 140


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
    alert = NSAlert.alloc().init()
    alert.setMessageText_(title)
    alert.setInformativeText_(text)
    alert.runModal()


def _load_persistent_settings(state):
    """Load baseUrl / apiKey / model / maxTokens from Glyphs.defaults.

    ``systemPrompt`` is intentionally NOT loaded during active development, so that updates
    to ``DEFAULT_SYSTEM_PROMPT`` in :mod:`utils` take effect on the next Glyphs launch.
    """
    blob = _get_default("settingsJson", "")
    if blob and str(blob).strip():
        state.set_settings_json(str(blob))
    else:
        dm, dmt, _dsp = migration_default_strings()
        state.migrate_from_legacy_flat(
            baseUrl=_get_default("baseUrl", ""),
            apiKey=_get_default("apiKey", ""),
            model=_get_default("model", dm),
            maxTokens=_get_default("maxTokens", dmt),
        )


def _run_on_main_sync(fn):
    """Execute ``fn()`` synchronously on the main thread and return its value.

    MUST be called from a background thread only — calling this from the main thread
    self-waits on ``addOperations_waitUntilFinished_`` and deadlocks the UI.
    """
    box = {}

    def wrapper():
        try:
            box["value"] = fn()
        except BaseException as e:
            box["error"] = e

    op = NSBlockOperation.blockOperationWithBlock_(wrapper)
    NSOperationQueue.mainQueue().addOperations_waitUntilFinished_([op], True)
    if "error" in box:
        raise box["error"]
    return box.get("value")


def _brief_json(value, limit=180):
    import json

    try:
        s = json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        s = str(value)
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


class TypoChatPlugin(GeneralPlugin):
    windowName = "com.typo.TypoChat.main"
    _frame_autosave_set = False

    @objc.python_method
    def _font_provider(self):
        return Glyphs.font

    @objc.python_method
    def _build_tool_context(self):
        return tools.ToolContext(
            font_provider=self._font_provider,
            render_contract=tools.DEFAULT_RENDER_CONTRACT,
            snapshot_store=tools.SnapshotStore(),
        )

    @objc.python_method
    def _build_window(self):
        self._frame_autosave_set = False
        s = self._state.settings
        self.w = Window((620, 880), self.name, minSize=(580, 760))

        y = 12
        self.w.baseUrlLabel = TextBox((12, y, 300, 14), "Base URL (POST → …/v1/chat/completions)")
        y += 18
        self.w.baseUrl = EditText(
            (12, y, -12, 22),
            s["baseUrl"],
            placeholder="https://your-provider.example.com",
            continuous=False,
        )
        y += 30

        self.w.apiKeyLabel = TextBox((12, y, 300, 14), "API key (Authorization: Bearer …)")
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
            (12, y, -12, 96),
            text=s["systemPrompt"],
            checksSpelling=True,
        )
        y += 104

        self.w.transcriptLabel = TextBox((12, y, 200, 14), "Transcript")
        y += 18
        self.w.transcript = TextEditor(
            (12, y, -12, 260),
            text="",
            readOnly=True,
            checksSpelling=False,
        )
        y += 268

        self.w.inputLabel = TextBox((12, y, 200, 14), "Message")
        y += 18
        self.w.inputField = EditText(
            (12, y, -12, 22),
            "",
            placeholder="Type a message…",
            continuous=False,
        )
        y += 26
        self.w.tokenUsageLabel = TextBox((12, y, -12, 28), self._state.usage_caption())
        y += 32

        self.w.sendButton = Button(
            (12, y, 100, 22),
            "Send",
            callback=self._on_send_,
        )
        self.w.approveButton = Button(
            (120, y, 90, 22),
            "Approve",
            callback=self._on_approve_,
        )
        self.w.approveButton.enable(False)
        self.w.rejectButton = Button(
            (218, y, 90, 22),
            "Reject",
            callback=self._on_reject_,
        )
        self.w.rejectButton.enable(False)
        self.w.cancelButton = Button(
            (316, y, 90, 22),
            "Cancel",
            callback=self._on_cancel_,
        )
        self.w.cancelButton.enable(False)
        self.w.newChatButton = Button(
            (-112, y, 100, 22),
            "New chat",
            callback=self._on_new_chat_,
        )
        y += 28
        self.w.resetSnapshotButton = Button(
            (12, y, 160, 22),
            "Reset snapshot",
            callback=self._on_reset_snapshot_,
        )
        self.w.resetSnapshotButton.enable(False)
        self.w.snapshotStatus = TextBox(
            (180, y + 3, -12, 16),
            "No snapshot saved.",
            sizeStyle="small",
        )

        self.w.versionLabel = TextBox(
            (12, -20, -12, 14),
            "TypoChat v%s" % PLUGIN_VERSION,
            sizeStyle="small",
            alignment="right",
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
        self._tool_ctx = self._build_tool_context()
        self._cancel_event = None
        self._worker_busy = False
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
        self._refresh_snapshot_ui()

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
    def _transcript_text_view(self):
        try:
            return self.w.transcript.getNSTextView()
        except Exception:
            return None

    @objc.python_method
    def _append_plain_text(self, text, color=None):
        tv = self._transcript_text_view()
        if tv is None:
            return
        attrs = {}
        # Default to the system adaptive text color so the transcript is readable in both
        # light and dark appearance (see debug log 2025-04-17: NSTextView.textColor is None
        # by default, so attributed strings without NSColor render as static black).
        attrs["NSColor"] = color if color is not None else NSColor.textColor()
        body_font = NSFont.userFontOfSize_(12.0)
        if body_font is not None:
            attrs["NSFont"] = body_font
        attr_str = NSAttributedString.alloc().initWithString_attributes_(text, attrs)
        tv.textStorage().appendAttributedString_(attr_str)

    @objc.python_method
    def _append_image(self, png_bytes):
        tv = self._transcript_text_view()
        if tv is None or not png_bytes:
            return
        data = NSData.dataWithBytes_length_(png_bytes, len(png_bytes))
        img = NSImage.alloc().initWithData_(data)
        if img is None:
            return
        sz = img.size()
        w, h = float(sz.width), float(sz.height)
        if w > 0 and h > 0:
            scale = min(_TRANSCRIPT_IMAGE_MAX_W / w, _TRANSCRIPT_IMAGE_MAX_H / h, 1.0)
            img.setSize_(NSSize(int(w * scale), int(h * scale)))
        attachment = NSTextAttachment.alloc().init()
        attachment.setImage_(img)
        attr = NSAttributedString.attributedStringWithAttachment_(attachment)
        tv.textStorage().appendAttributedString_(attr)
        self._append_plain_text("\n")

    @objc.python_method
    def _scroll_to_end(self):
        tv = self._transcript_text_view()
        if tv is None:
            return
        length = tv.textStorage().length()
        tv.scrollRangeToVisible_((length, 0))

    @objc.python_method
    def _set_busy(self, busy):
        self._worker_busy = busy
        self.w.sendButton.enable(not busy)
        self.w.cancelButton.enable(busy)
        if busy:
            self.w.approveButton.enable(False)
            self.w.rejectButton.enable(False)
        self._refresh_snapshot_ui()

    @objc.python_method
    def _refresh_snapshot_ui(self):
        store = getattr(self._tool_ctx, "snapshot_store", None)
        has = bool(store and store.has_snapshot())
        self.w.resetSnapshotButton.enable(has and not self._worker_busy)
        if has:
            names = list(getattr(store, "_glyph_names", []) or [])
            preview = ", ".join(names[:3])
            if len(names) > 3:
                preview += ", +%d" % (len(names) - 3)
            self.w.snapshotStatus.set("Snapshot: %s" % (preview or "(saved)"))
        else:
            self.w.snapshotStatus.set("No snapshot saved.")

    @objc.python_method
    def _on_event(self, event):
        """Dispatched on main thread. ``event`` is a dict (see ``ChatState.run_agent_turn``)."""
        kind = event.get("kind")

        if kind == "user":
            self._append_plain_text("You: %s\n" % event.get("text", ""))
        elif kind == "assistant_text":
            text = event.get("text") or ""
            if text:
                self._append_plain_text("Assistant: %s\n" % text)
        elif kind == "tool_use":
            line = "[tool_use] %s(%s)\n" % (
                event.get("name", "?"),
                _brief_json(event.get("input") or {}),
            )
            self._append_plain_text(line, color=NSColor.systemBlueColor())
        elif kind == "tool_result":
            blocks = event.get("content") or []
            is_error = bool(event.get("is_error"))
            prefix = "[tool_result%s] %s:\n" % (
                " error" if is_error else "",
                event.get("name", "?"),
            )
            self._append_plain_text(
                prefix,
                color=NSColor.systemRedColor() if is_error else NSColor.systemGrayColor(),
            )
            for b in blocks:
                btype = b.get("type")
                if btype == "text":
                    self._append_plain_text((b.get("text") or "") + "\n")
                elif btype == "image":
                    src = b.get("source") or {}
                    if src.get("type") == "base64":
                        import base64

                        try:
                            raw = base64.b64decode(src.get("data") or "")
                        except Exception:
                            raw = b""
                        if raw:
                            self._append_image(raw)
        elif kind == "approval_required":
            self._append_plain_text(
                "\n[waiting for Approve / Reject]\n",
                color=NSColor.systemOrangeColor(),
            )
            self.w.approveButton.enable(True)
            self.w.rejectButton.enable(True)
        elif kind == "usage_updated":
            self.w.tokenUsageLabel.set(self._state.usage_caption())
        elif kind == "done":
            reason = event.get("stop_reason") or "end_turn"
            self._append_plain_text("\n[turn finished: %s]\n\n" % reason)
        elif kind == "iteration_limit":
            self._append_plain_text(
                "\n[iteration limit reached]\n\n",
                color=NSColor.systemOrangeColor(),
            )
        elif kind == "cancelled":
            self._append_plain_text("\n[cancelled by user]\n\n", color=NSColor.systemOrangeColor())
        elif kind == "error":
            self._append_plain_text(
                "\n[error] %s\n\n" % (event.get("text") or ""),
                color=NSColor.systemRedColor(),
            )

        if kind in ("tool_result", "done", "cancelled", "iteration_limit"):
            self._refresh_snapshot_ui()
        self._scroll_to_end()

    @objc.python_method
    def _dispatch_event(self, event):
        NSOperationQueue.mainQueue().addOperationWithBlock_(lambda: self._on_event(event))

    @objc.python_method
    def _tool_executor(self, name, args):
        return _run_on_main_sync(lambda: tools.execute_tool(name, args, self._tool_ctx))

    @objc.python_method
    def _start_turn(self, user_text):
        if self._worker_busy:
            return
        self._save_settings_from_ui()
        err = self._state.validate_setting_errors()
        if err:
            _show_alert("Typo Chat", err)
            return
        self._cancel_event = threading.Event()
        self._set_busy(True)

        def worker():
            try:
                self._state.run_agent_turn(
                    user_text=user_text,
                    tool_executor=self._tool_executor,
                    tool_schemas=tools.TOOL_SCHEMAS,
                    on_event=self._dispatch_event,
                    cancel_event=self._cancel_event,
                )
            except Exception as e:
                self._dispatch_event({"kind": "error", "text": str(e)})
            finally:
                NSOperationQueue.mainQueue().addOperationWithBlock_(
                    lambda: self._set_busy(False)
                )

        threading.Thread(target=worker, daemon=True).start()

    @objc.python_method
    def _on_send_(self, sender):
        text = (self.w.inputField.get() or "").strip()
        if not text:
            return
        self.w.inputField.set("")
        self._start_turn(text)

    @objc.python_method
    def _on_approve_(self, sender):
        self.w.approveButton.enable(False)
        self.w.rejectButton.enable(False)
        self._start_turn("approve")

    @objc.python_method
    def _on_reject_(self, sender):
        self.w.approveButton.enable(False)
        self.w.rejectButton.enable(False)
        self._start_turn("reject — please revise the plan and propose another approach")

    @objc.python_method
    def _on_cancel_(self, sender):
        if self._cancel_event is not None:
            self._cancel_event.set()
        self.w.cancelButton.enable(False)

    @objc.python_method
    def _on_reset_snapshot_(self, sender):
        # AppKit calls this on the main thread; do the work directly here.
        # Do NOT route through ``_run_on_main_sync`` — that would self-wait on
        # NSOperationQueue.mainQueue and deadlock the UI.
        if self._worker_busy:
            return
        store = getattr(self._tool_ctx, "snapshot_store", None)
        if store is None or not store.has_snapshot():
            self._refresh_snapshot_ui()
            return
        font = self._font_provider()
        if font is None:
            _show_alert("Typo Chat", "No font is open — cannot reset snapshot.")
            return
        try:
            info = store.reset(font)
        except Exception as e:
            _show_alert("Typo Chat", "Reset failed: %s" % e)
            return
        names = ", ".join(info.get("glyph_names", []) or [])
        self._append_plain_text(
            "\n[manual reset_snapshot] reverted: %s\n\n" % names,
            color=NSColor.systemOrangeColor(),
        )
        self._refresh_snapshot_ui()
        self._scroll_to_end()

    @objc.python_method
    def _on_new_chat_(self, sender):
        if self._worker_busy and self._cancel_event is not None:
            self._cancel_event.set()
        self._state.clear()
        tv = self._transcript_text_view()
        if tv is not None:
            tv.textStorage().setAttributedString_(NSAttributedString.alloc().initWithString_(""))
        self._state.reset_system_prompt_to_default()
        self.w.systemPrompt.set(self._state.settings["systemPrompt"])
        self.w.inputField.set("")
        self.w.tokenUsageLabel.set(self._state.usage_caption())
        self.w.approveButton.enable(False)
        self.w.rejectButton.enable(False)
        store = getattr(self._tool_ctx, "snapshot_store", None)
        if store is not None:
            store.clear()
        self._refresh_snapshot_ui()
        self._save_settings_from_ui()

    @objc.python_method
    def __file__(self):
        return __file__
