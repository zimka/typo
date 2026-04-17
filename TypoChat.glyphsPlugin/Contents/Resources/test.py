# encoding: utf-8
"""
Level-3 smoke test: run inside Glyphs. Imports the ``utils`` module
(without the plugin class) so ``plugin`` is not loaded twice—otherwise PyObjC
reports "overriding existing Objective-C class".

How to run in Glyphs
--------------------
1. Open the Macro Panel: **Window → Macro Panel** (or **⌥⌘M**).
2. Paste the code below, substituting the **absolute path** to
   ``TypoChat.glyphsPlugin/Contents/Resources`` (your repo clone or a copy of
   the plugin in the Glyphs plugins folder), and run it.

Example for a clone (macOS; replace ``YOUR_NAME`` and the path if needed)::

    import sys
    sys.path.insert(0, "/Users/YOUR_NAME/my/grammafont_plugin/TypoChat.glyphsPlugin/Contents/Resources")
    import test
    test.run_smoke()

If the plugin was installed via the plugin manager, the path is usually::

    ~/Library/Application Support/Glyphs 3/Plugins/TypoChat.glyphsPlugin/Contents/Resources

(For Glyphs 2 the folder may be named ``Glyphs 2``). In the macro, use an
expanded path, e.g. via ``os.path.expanduser``.

After a successful run, the bottom of the panel shows a success line; if
expectations do not match, an ``AssertionError`` with a traceback is raised.
"""


def run_smoke():
    """Single entry point: smoke-test helpers from ``utils`` (no Glyphs)."""
    from utils import (
        DEFAULT_CACHE_CONTROL,
        _messages_endpoint,
        build_messages_request_body,
        format_usage_caption,
        normalize_usage,
    )

    assert _messages_endpoint("") == ""
    assert _messages_endpoint("   ") == ""
    assert _messages_endpoint("https://api.example.com") == "https://api.example.com/v1/messages"
    assert _messages_endpoint("https://api.example.com/") == "https://api.example.com/v1/messages"
    assert _messages_endpoint(None) == ""

    z = normalize_usage(None)
    assert z["input_tokens"] == 0 and z["output_tokens"] == 0
    assert normalize_usage({"input_tokens": 100, "output_tokens": 50})["output_tokens"] == 50
    assert normalize_usage({"input_tokens": "12", "bad": "x"})["input_tokens"] == 12

    body = build_messages_request_body(
        "claude-sonnet-4-6",
        1024,
        [{"role": "user", "content": "hi"}],
        "You are helpful.",
        cache_control=DEFAULT_CACHE_CONTROL,
    )
    assert body["cache_control"]["type"] == "ephemeral"
    assert body["cache_control"]["ttl"] == "1h"
    assert "cache_control" not in build_messages_request_body(
        "m", 100, [], "", cache_control=None
    )

    cap = format_usage_caption(
        {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    )
    assert "last:" in cap and "session:" in cap

    print("Typo Chat Resources/test.py: run_smoke() OK")
