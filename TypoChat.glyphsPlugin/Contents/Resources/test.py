# encoding: utf-8
"""
Level-3 smoke tests. Safe to run inside Glyphs (Macro Panel) and — for the
Glyphs-agnostic parts — also as a plain Python script.

How to run in Glyphs
--------------------
1. Open the Macro Panel: **Window → Macro Panel** (or **⌥⌘M**).
2. Paste, substituting the absolute path to the plugin's ``Resources`` folder:

    import sys
    sys.path.insert(0, "/Users/YOUR_NAME/my/grammafont_plugin/TypoChat.glyphsPlugin/Contents/Resources")
    import test
    test.run_smoke()

A success line prints at the bottom; on failure an ``AssertionError`` with a
traceback is raised.
"""


def _test_utils_basics():
    from utils import (
        _messages_endpoint,
        build_messages_request_body,
        format_usage_caption,
        normalize_tool_result_content,
        normalize_usage,
        parse_assistant_response,
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
        tools=[{"name": "t", "description": "", "input_schema": {"type": "object"}}],
    )
    assert body["model"] == "claude-sonnet-4-6"
    assert body["tools"][0]["name"] == "t"
    assert body["system"] == "You are helpful."

    cap = format_usage_caption(
        {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
    )
    assert "last:" in cap and "session:" in cap

    blocks = normalize_tool_result_content("hello")
    assert blocks == [{"type": "text", "text": "hello"}]
    blocks = normalize_tool_result_content(b"\x89PNG\r\n\x1a\n")
    assert blocks[0]["type"] == "image"
    assert blocks[0]["source"]["media_type"] == "image/png"
    blocks = normalize_tool_result_content(["hdr", b"\x89PNG\r\n\x1a\n"])
    assert blocks[0]["type"] == "text" and blocks[1]["type"] == "image"


def _test_parse_assistant_response():
    from utils import parse_assistant_response

    tool_payload = {
        "id": "msg_01",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-6",
        "content": [
            {"type": "text", "text": "let me look"},
            {
                "type": "tool_use",
                "id": "toolu_abc",
                "name": "list_masters",
                "input": {},
            },
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 42, "output_tokens": 11},
    }
    p = parse_assistant_response(tool_payload)
    assert p["error"] is None
    assert p["stop_reason"] == "tool_use"
    assert p["text"] == "let me look"
    assert len(p["tool_uses"]) == 1
    assert p["tool_uses"][0]["name"] == "list_masters"
    assert p["tool_uses"][0]["id"] == "toolu_abc"
    assert p["usage"]["input_tokens"] == 42

    end_payload = {
        "content": [{"type": "text", "text": "DOD PASSED"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 1, "output_tokens": 2},
    }
    p = parse_assistant_response(end_payload)
    assert p["error"] is None
    assert p["text"] == "DOD PASSED"
    assert p["tool_uses"] == []
    assert p["stop_reason"] == "end_turn"

    err_payload = {"type": "error", "error": {"type": "invalid_request_error", "message": "boom"}}
    p = parse_assistant_response(err_payload)
    assert p["error"] and "boom" in p["error"]


class _FakeAxis:
    def __init__(self, name):
        self.name = name


class _FakeMaster:
    def __init__(self, mid, name, axes=None):
        self.id = mid
        self.name = name
        self.axes = list(axes or [])


class _FakePosition:
    def __init__(self, x, y):
        self.x = x
        self.y = y


class _FakeNode:
    def __init__(self, x, y, t="line", smooth=False):
        self.position = _FakePosition(x, y)
        self.type = t
        self.smooth = smooth


class _FakePath:
    def __init__(self, nodes, closed=True):
        self.nodes = list(nodes)
        self.closed = closed


class _FakeLayer:
    def __init__(self, width, paths, anchors=None, components=None):
        self.width = width
        self.paths = list(paths)
        self.anchors = list(anchors or [])
        self.components = list(components or [])
        self.completeBezierPath = None


class _LayerMap:
    def __init__(self, by_id):
        self._by_id = dict(by_id)

    def __getitem__(self, key):
        return self._by_id.get(key)


class _FakeGlyph:
    def __init__(self, name, unicode_hex, layers_by_id):
        self.name = name
        self.unicode = unicode_hex
        self.layers = _LayerMap(layers_by_id)


class _FakeGlyphsList:
    def __init__(self, glyphs):
        self._glyphs = list(glyphs)
        self._by_name = {g.name: g for g in self._glyphs}

    def __iter__(self):
        return iter(self._glyphs)

    def __getitem__(self, key):
        return self._by_name.get(key)


class _FakeFont:
    def __init__(self, upm=1000):
        self.upm = upm
        self.axes = [_FakeAxis("Weight")]
        self.masters = []
        self.glyphs = _FakeGlyphsList([])

    def glyphForCharacter_(self, code):
        for g in self.glyphs:
            if g.unicode and int(g.unicode, 16) == code:
                return g
        return None


def _build_fake_font():
    m_regular = _FakeMaster("M_REG", "Regular", axes=[400])
    m_bold = _FakeMaster("M_BOLD", "Bold", axes=[700])
    font = _FakeFont(upm=1000)
    font.masters = [m_regular, m_bold]

    nodes_bold_dje = [
        _FakeNode(100, 1230),
        _FakeNode(800, 1230),
        _FakeNode(800, 1420),
        _FakeNode(100, 1420),
    ]
    layer_bold = _FakeLayer(width=1200, paths=[_FakePath(nodes_bold_dje)])
    layer_regular = _FakeLayer(
        width=1200,
        paths=[_FakePath([_FakeNode(100, 1158), _FakeNode(800, 1158)])],
    )
    dje = _FakeGlyph(
        "Dje-cy",
        "0402",
        {m_regular.id: layer_regular, m_bold.id: layer_bold},
    )
    font.glyphs = _FakeGlyphsList([dje])
    return font


def _test_tool_handlers_pure():
    import tools

    font = _build_fake_font()
    ctx = tools.ToolContext(font_provider=lambda: font)

    out = tools.execute_tool("list_masters", {}, ctx)
    assert "Regular" in out and "Bold" in out and "M_BOLD" in out

    out = tools.execute_tool("list_glyphs", {"filter": "dje"}, ctx)
    assert "Dje-cy" in out and "U+0402" in out

    out = tools.execute_tool(
        "get_glyph", {"name": "Dje-cy", "master": "Bold"}, ctx
    )
    assert "glyph: Dje-cy" in out
    assert "master: Bold" in out
    assert "paths: 1" in out
    assert "(x=100, y=1230)" in out
    assert "(x=100, y=1420)" in out

    out = tools.execute_tool(
        "move_nodes_where",
        {
            "glyph": "Dje-cy",
            "master": "Bold",
            "predicate": {"y": 1230},
            "delta": {"dy": -72},
        },
        ctx,
    )
    assert "Moved 2 node(s)" in out
    layer = font.glyphs["Dje-cy"].layers["M_BOLD"]
    ys = sorted(int(n.position.y) for n in layer.paths[0].nodes)
    assert ys == [1158, 1158, 1420, 1420], ys

    out = tools.execute_tool(
        "move_nodes_where",
        {
            "glyph": "Dje-cy",
            "master": "Bold",
            "predicate": {},
            "delta": {"dy": 1},
        },
        ctx,
    )
    assert "refuse" in out.lower()

    out = tools.execute_tool(
        "move_nodes_where",
        {
            "glyph": "Dje-cy",
            "master": "Bold",
            "predicate": {"y": 9999},
            "delta": {"dy": -10},
        },
        ctx,
    )
    assert "No nodes matched" in out

    out = tools.execute_tool("get_glyph", {"name": "Missing"}, ctx)
    assert out.startswith("[error]")

    out = tools.execute_tool("unknown_tool", {}, ctx)
    assert out.startswith("[error] Unknown tool")


def _test_agent_loop_fake():
    from state import ChatState

    script = [
        {
            "content": [
                {"type": "text", "text": "Looking at masters."},
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "list_masters",
                    "input": {},
                },
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 1, "output_tokens": 2},
        },
        {
            "content": [{"type": "text", "text": "DOD PASSED"}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 3, "output_tokens": 4},
        },
    ]

    import state as state_mod

    original_post = state_mod.post_messages_request
    calls = {"n": 0}

    def fake_post(body, url, auth_value):
        i = calls["n"]
        calls["n"] += 1
        return script[i]

    state_mod.post_messages_request = fake_post
    try:
        s = ChatState()
        s.update_settings_from_ui_fields(
            "https://fake.example",
            "token",
            "m",
            "1024",
            "sys",
        )
        events = []

        def executor(name, args):
            assert name == "list_masters"
            return "masters: [0] id=A name=Regular"

        s.run_agent_turn(
            user_text="Fix it",
            tool_executor=executor,
            tool_schemas=[{"name": "list_masters", "input_schema": {"type": "object"}}],
            on_event=events.append,
        )
    finally:
        state_mod.post_messages_request = original_post

    kinds = [e.get("kind") for e in events]
    assert kinds[0] == "user"
    assert "tool_use" in kinds
    assert "tool_result" in kinds
    assert kinds[-1] == "done", kinds
    assert s.messages[-1]["role"] == "assistant"
    assert s.messages[-2]["role"] == "user"


def run_smoke():
    """Single entry point: run all smoke tests that do not require a live Glyphs font."""
    _test_utils_basics()
    _test_parse_assistant_response()
    _test_tool_handlers_pure()
    _test_agent_loop_fake()
    print("Typo Chat Resources/test.py: run_smoke() OK")


if __name__ == "__main__":
    run_smoke()
