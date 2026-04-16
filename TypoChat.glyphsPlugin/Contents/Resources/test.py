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
    """Single entry point: smoke-test ``_messages_endpoint`` from ``utils``."""
    from utils import _messages_endpoint

    assert _messages_endpoint("") == ""
    assert _messages_endpoint("   ") == ""
    assert _messages_endpoint("https://api.example.com") == "https://api.example.com/v1/messages"
    assert _messages_endpoint("https://api.example.com/") == "https://api.example.com/v1/messages"
    assert _messages_endpoint(None) == ""

    print("Typo Chat Resources/test.py: run_smoke() OK")
