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
        _chat_endpoint,
        format_usage_caption,
        normalize_tool_result_content,
        normalize_usage,
    )

    assert _chat_endpoint("") == ""
    assert _chat_endpoint("   ") == ""
    assert _chat_endpoint("https://api.example.com") == "https://api.example.com/v1/chat/completions"
    assert _chat_endpoint("https://api.example.com/") == "https://api.example.com/v1/chat/completions"
    assert _chat_endpoint(None) == ""

    z = normalize_usage(None)
    assert z["input_tokens"] == 0 and z["output_tokens"] == 0
    assert normalize_usage({"input_tokens": 100, "output_tokens": 50})["output_tokens"] == 50
    assert normalize_usage({"input_tokens": "12", "bad": "x"})["input_tokens"] == 12

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


def _test_parse_provider_response():
    from provider import parse_response

    # Tool use turn (OpenAI format)
    tool_payload = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "let me look",
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "list_masters",
                            "arguments": "{}",
                        }
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 42, "completion_tokens": 11, "total_tokens": 53},
    }
    p = parse_response(tool_payload)
    assert p["error"] is None
    assert p["stop_reason"] == "tool_use"
    assert p["text"] == "let me look"
    assert len(p["tool_uses"]) == 1
    assert p["tool_uses"][0]["name"] == "list_masters"
    assert p["tool_uses"][0]["id"] == "call_abc"
    assert p["usage"]["input_tokens"] == 42
    assert p["usage"]["output_tokens"] == 11

    # End turn (OpenAI format)
    end_payload = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "DOD PASSED",
                "tool_calls": None,
            },
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
    }
    p = parse_response(end_payload)
    assert p["error"] is None
    assert p["text"] == "DOD PASSED"
    assert p["tool_uses"] == []
    assert p["stop_reason"] == "end_turn"

    # Error response
    err_payload = {"error": {"type": "invalid_request_error", "message": "boom"}}
    p = parse_response(err_payload)
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

    # OpenAI-format responses
    script = [
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "Looking at masters.",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "list_masters",
                                "arguments": "{}",
                            }
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        },
        {
            "choices": [{
                "message": {
                    "role": "assistant",
                    "content": "DOD PASSED",
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
        },
    ]

    import provider as provider_mod

    original_post = provider_mod.post_request
    calls = {"n": 0}

    def fake_post(body, url, auth_value):
        i = calls["n"]
        calls["n"] += 1
        return script[i]

    provider_mod.post_request = fake_post
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
        provider_mod.post_request = original_post

    kinds = [e.get("kind") for e in events]
    assert kinds[0] == "user"
    assert "tool_use" in kinds
    assert "tool_result" in kinds
    assert kinds[-1] == "done", kinds
    assert s.messages[-1]["role"] == "assistant"
    assert s.messages[-2]["role"] == "user"


def _test_snapshot_store_pure():
    import tools

    font = _build_fake_font()
    store = tools.SnapshotStore()
    ctx = tools.ToolContext(font_provider=lambda: font, snapshot_store=store)

    assert not store.has_snapshot()

    out = tools.execute_tool("reset_snapshot", {}, ctx)
    assert out.startswith("[error]"), out
    out = tools.execute_tool("diff_pre_post", {"text": "Ђ"}, ctx)
    assert out.startswith("[error]") and "snapshot" in out.lower(), out

    out = tools.execute_tool("save_snapshot", {"glyph_names": []}, ctx)
    assert out.startswith("[error]"), out
    out = tools.execute_tool("save_snapshot", {"glyph_names": ["NoSuch"]}, ctx)
    assert out.startswith("[error]") and "NoSuch" in out, out

    out = tools.execute_tool("save_snapshot", {"glyph_names": ["Dje-cy"]}, ctx)
    assert "Snapshot saved" in out, out
    assert store.has_snapshot()
    assert store._glyph_names == ["Dje-cy"]
    assert set(store._slot["Dje-cy"].keys()) == {"M_REG", "M_BOLD"}
    bold_pre = store._slot["Dje-cy"]["M_BOLD"]
    assert bold_pre["width"] == 1200.0
    ys_pre = sorted(int(n["y"]) for n in bold_pre["paths"][0]["nodes"])
    assert ys_pre == [1230, 1230, 1420, 1420]

    tools.execute_tool(
        "move_nodes_where",
        {
            "glyph": "Dje-cy",
            "master": "Bold",
            "predicate": {"y": 1230},
            "delta": {"dy": -72},
        },
        ctx,
    )
    layer = font.glyphs["Dje-cy"].layers["M_BOLD"]
    ys_mid = sorted(int(n.position.y) for n in layer.paths[0].nodes)
    assert ys_mid == [1158, 1158, 1420, 1420], ys_mid

    out = tools.execute_tool("reset_snapshot", {}, ctx)
    assert "Snapshot restored" in out, out
    ys_post = sorted(int(n.position.y) for n in layer.paths[0].nodes)
    assert ys_post == [1230, 1230, 1420, 1420], ys_post
    assert store.has_snapshot(), "snapshot should persist after reset"

    out = tools.execute_tool("save_snapshot", {"glyph_names": ["Dje-cy"]}, ctx)
    assert "Overwrote previous snapshot" in out, out

    store.clear()
    assert not store.has_snapshot()
    out = tools.execute_tool("reset_snapshot", {}, ctx)
    assert out.startswith("[error]"), out


def run_smoke():
    """Single entry point: run all smoke tests that do not require a live Glyphs font."""
    _test_utils_basics()
    _test_parse_provider_response()
    _test_tool_handlers_pure()
    _test_agent_loop_fake()
    _test_snapshot_store_pure()
    print("Typo Chat Resources/test.py: run_smoke() OK")


if __name__ == "__main__":
    run_smoke()
