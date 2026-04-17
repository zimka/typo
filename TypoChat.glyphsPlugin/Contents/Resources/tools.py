# encoding: utf-8
"""
Agent tools for Typo Chat (Phase 1).

Five tools are exposed to the model via Anthropic ``tools`` parameter:

- ``list_masters``       — enumerate masters of the current font.
- ``list_glyphs``        — list glyph names (optional substring filter).
- ``get_glyph``          — dump a glyph's paths/nodes/anchors/metrics as text.
- ``render_specimen``    — rasterize a text using the current font state (returns PNG).
- ``move_nodes_where``   — move nodes in ``glyph@master`` whose coordinates match a predicate.

The rendering and Glyphs-SDK code paths import ``AppKit`` / ``GlyphsApp`` lazily so this
module can still be imported from non-Glyphs unit tests.
"""

import json

DEFAULT_RENDER_CONTRACT = {
    "canvas_w": 900,
    "canvas_h": 260,
    "margin_x": 24,
    "em_px": 160.0,
    "baseline_y": 56.0,
    "unknown_advance_upm": 250.0,
}


TOOL_SCHEMAS = [
    {
        "name": "list_masters",
        "description": (
            "List all masters (weight/width/custom axes) of the currently open font. "
            "Returns master name, id and axis values."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_glyphs",
        "description": (
            "List glyph names in the current font. Optionally filter by a case-insensitive "
            "substring match against glyph name or unicode value."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "string",
                    "description": "Optional substring, e.g. 'cy', 'Dje', '0402'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max entries to return. Default 200.",
                },
            },
        },
    },
    {
        "name": "get_glyph",
        "description": (
            "Return paths, nodes, anchors, components and metrics of a single glyph at a "
            "specific master, as structured text. Use this to reason about geometry."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Glyph name (e.g. 'Dje-cy') or a single character.",
                },
                "master": {
                    "type": "string",
                    "description": "Master name or id. Defaults to the first master.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "render_specimen",
        "description": (
            "Render a short text using the CURRENT state of the open font and return a PNG "
            "image. Use the SAME text and master before and after a fix so renders are "
            "comparable by eye."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Specimen text (short; 1-20 characters is typical).",
                },
                "master": {
                    "type": "string",
                    "description": "Master name or id. Defaults to the first master.",
                },
                "size": {
                    "type": "integer",
                    "description": "Em size in pixels. Default 160.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "move_nodes_where",
        "description": (
            "Move nodes of a glyph at a specific master whose coordinates match 'predicate' "
            "by 'delta'. Only integer coordinates are matched (no tolerance). Use this as "
            "the single edit primitive: one call should do one atomic geometric change."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "glyph": {"type": "string", "description": "Glyph name."},
                "master": {"type": "string", "description": "Master name or id."},
                "predicate": {
                    "type": "object",
                    "description": "Match any subset of {x, y} with integer values.",
                    "properties": {
                        "x": {"type": "integer"},
                        "y": {"type": "integer"},
                    },
                },
                "delta": {
                    "type": "object",
                    "description": "Integer offsets. Keys: dx, dy.",
                    "properties": {
                        "dx": {"type": "integer"},
                        "dy": {"type": "integer"},
                    },
                },
            },
            "required": ["glyph", "master", "predicate", "delta"],
        },
    },
]


class ToolContext:
    """Plugin-level state passed to every tool call."""

    def __init__(self, font_provider, render_contract=None):
        self._font_provider = font_provider
        self.render_contract = dict(render_contract or DEFAULT_RENDER_CONTRACT)

    @property
    def font(self):
        return self._font_provider()


def execute_tool(name, args, ctx):
    """Dispatch a tool call. Returns content accepted by ``normalize_tool_result_content``."""
    font = ctx.font
    if font is None:
        return "[error] No font is open in Glyphs."
    handler = _HANDLERS.get(name)
    if handler is None:
        return "[error] Unknown tool: %s" % name
    return handler(args or {}, ctx, font)


def _handle_list_masters(args, ctx, font):
    lines = []
    for i, m in enumerate(font.masters):
        axes = _master_axes_text(font, m)
        lines.append("[%d] id=%s name=%s%s" % (i, m.id, m.name, (" " + axes) if axes else ""))
    if not lines:
        return "(no masters)"
    return "masters:\n" + "\n".join(lines)


def _handle_list_glyphs(args, ctx, font):
    flt = str(args.get("filter") or "").strip().lower()
    try:
        limit = int(args.get("limit") or 200)
    except (TypeError, ValueError):
        limit = 200
    limit = max(1, min(2000, limit))

    out = []
    for g in font.glyphs:
        name = g.name or ""
        uni = (g.unicode or "") if hasattr(g, "unicode") else ""
        if flt:
            if flt not in name.lower() and flt not in str(uni).lower():
                continue
        out.append("%s%s" % (name, (" U+" + uni) if uni else ""))
        if len(out) >= limit:
            break
    if not out:
        return "(no glyphs matched filter=%r)" % flt
    header = "glyphs (%d shown%s):" % (len(out), ", filter=%r" % flt if flt else "")
    return header + "\n" + "\n".join(out)


def _handle_get_glyph(args, ctx, font):
    name = str(args.get("name") or "").strip()
    if not name:
        return "[error] 'name' is required."
    glyph = _resolve_glyph(font, name)
    if glyph is None:
        return "[error] Glyph not found: %s" % name
    master = _resolve_master(font, args.get("master"))
    if master is None:
        return "[error] Master not found: %s" % args.get("master")
    layer = glyph.layers[master.id]
    if layer is None:
        return "[error] Glyph %s has no layer for master %s." % (name, master.name)
    return _dump_layer(glyph, master, layer)


def _handle_render_specimen(args, ctx, font):
    text = str(args.get("text") or "")
    if not text:
        return "[error] 'text' is required."
    master = _resolve_master(font, args.get("master"))
    if master is None:
        return "[error] Master not found: %s" % args.get("master")
    contract = dict(ctx.render_contract)
    try:
        size = int(args.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    if size > 0:
        contract["em_px"] = float(size)
        contract["canvas_h"] = int(max(contract["canvas_h"], size * 1.6))
    png_bytes = _render_layer_run(font, master, text, contract)
    header = (
        "render_specimen master=%s size=%s text=%r canvas=%dx%d"
        % (master.name, int(contract.get("em_px", 0)), text,
           contract.get("canvas_w"), contract.get("canvas_h"))
    )
    return [header, png_bytes]


def _handle_move_nodes_where(args, ctx, font):
    name = str(args.get("glyph") or "").strip()
    if not name:
        return "[error] 'glyph' is required."
    glyph = _resolve_glyph(font, name)
    if glyph is None:
        return "[error] Glyph not found: %s" % name
    master = _resolve_master(font, args.get("master"))
    if master is None:
        return "[error] Master not found: %s" % args.get("master")
    layer = glyph.layers[master.id]
    if layer is None:
        return "[error] Glyph %s has no layer for master %s." % (name, master.name)

    pred = args.get("predicate") or {}
    delta = args.get("delta") or {}
    if not isinstance(pred, dict) or not isinstance(delta, dict):
        return "[error] 'predicate' and 'delta' must be objects."
    if not pred:
        return "[error] 'predicate' is empty — refuse to move ALL nodes as a safety guard."

    px = _int_or_none(pred.get("x"))
    py = _int_or_none(pred.get("y"))
    dx = _int_or_none(delta.get("dx")) or 0
    dy = _int_or_none(delta.get("dy")) or 0
    if dx == 0 and dy == 0:
        return "[error] 'delta' is zero — no-op."

    moved = []
    for pi, path in enumerate(layer.paths or []):
        for ni, node in enumerate(path.nodes or []):
            nx = int(round(node.position.x))
            ny = int(round(node.position.y))
            if px is not None and nx != px:
                continue
            if py is not None and ny != py:
                continue
            new_x = nx + dx
            new_y = ny + dy
            node.position = _point(new_x, new_y)
            moved.append((pi, ni, nx, ny, new_x, new_y))

    if not moved:
        return (
            "No nodes matched predicate %s in %s@%s. Nothing changed."
            % (json.dumps(pred), name, master.name)
        )

    lines = [
        "Moved %d node(s) in %s@%s by dx=%d, dy=%d:"
        % (len(moved), name, master.name, dx, dy)
    ]
    for pi, ni, ox, oy, nx, ny in moved[:30]:
        lines.append("  path[%d].node[%d] (%d,%d) -> (%d,%d)" % (pi, ni, ox, oy, nx, ny))
    if len(moved) > 30:
        lines.append("  ... %d more" % (len(moved) - 30))
    return "\n".join(lines)


_HANDLERS = {
    "list_masters": _handle_list_masters,
    "list_glyphs": _handle_list_glyphs,
    "get_glyph": _handle_get_glyph,
    "render_specimen": _handle_render_specimen,
    "move_nodes_where": _handle_move_nodes_where,
}


def _resolve_master(font, key):
    """Resolve a master by id or name, or return the first master if ``key`` is empty."""
    if key is None or str(key).strip() == "":
        masters = list(font.masters)
        return masters[0] if masters else None
    key_s = str(key).strip()
    for m in font.masters:
        if getattr(m, "id", None) == key_s:
            return m
    for m in font.masters:
        if getattr(m, "name", None) == key_s:
            return m
    key_low = key_s.lower()
    for m in font.masters:
        mname = (m.name or "").lower()
        if key_low in mname:
            return m
    return None


def _resolve_glyph(font, name):
    """Look up a glyph by name, or by single-character unicode."""
    if not name:
        return None
    g = font.glyphs[name]
    if g is not None:
        return g
    if len(name) == 1:
        try:
            return font.glyphForCharacter_(ord(name))
        except Exception:
            return None
    return None


def _master_axes_text(font, master):
    try:
        values = list(master.axes or [])
    except Exception:
        values = []
    if not values:
        return ""
    try:
        axes = list(getattr(font, "axes", []) or [])
        names = [getattr(a, "name", "?") for a in axes]
    except Exception:
        names = []
    parts = []
    for i, v in enumerate(values):
        label = names[i] if i < len(names) else ("axis%d" % i)
        parts.append("%s=%s" % (label, v))
    return "(" + ", ".join(parts) + ")"


def _int_or_none(v):
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(round(float(v)))
        except (TypeError, ValueError):
            return None


class _PyPoint:
    """Fallback point type when Foundation is unavailable (unit tests outside Glyphs)."""

    __slots__ = ("x", "y")

    def __init__(self, x, y):
        self.x = x
        self.y = y


def _point(x, y):
    """Build a point value that ``GSNode.position`` accepts."""
    try:
        from Foundation import NSMakePoint

        return NSMakePoint(x, y)
    except Exception:
        return _PyPoint(x, y)


def _dump_layer(glyph, master, layer):
    uni = (glyph.unicode or "") if hasattr(glyph, "unicode") else ""
    header = "glyph: %s%s" % (glyph.name, (" U+" + uni) if uni else "")
    lines = [
        header,
        "master: %s (id=%s)" % (master.name, master.id),
        "width: %s" % _fmt_num(layer.width),
    ]
    paths = list(layer.paths or [])
    lines.append("paths: %d" % len(paths))
    for pi, path in enumerate(paths):
        closed = getattr(path, "closed", True)
        nodes = list(path.nodes or [])
        lines.append("  path[%d] closed=%s nodes=%d" % (pi, bool(closed), len(nodes)))
        for ni, node in enumerate(nodes):
            t = getattr(node, "type", "") or ""
            x = _fmt_num(node.position.x)
            y = _fmt_num(node.position.y)
            smooth = " smooth" if getattr(node, "smooth", False) else ""
            lines.append("    node[%d] %s (x=%s, y=%s)%s" % (ni, t, x, y, smooth))
    anchors = list(getattr(layer, "anchors", []) or [])
    lines.append("anchors: %d" % len(anchors))
    for a in anchors:
        lines.append(
            "  %s (x=%s, y=%s)"
            % (a.name, _fmt_num(a.position.x), _fmt_num(a.position.y))
        )
    comps = list(getattr(layer, "components", []) or [])
    lines.append("components: %d" % len(comps))
    for c in comps:
        cname = getattr(c, "componentName", "?")
        try:
            px, py = c.position.x, c.position.y
            pos = " at (%s, %s)" % (_fmt_num(px), _fmt_num(py))
        except Exception:
            pos = ""
        lines.append("  %s%s" % (cname, pos))
    return "\n".join(lines)


def _fmt_num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if f == int(f):
        return str(int(f))
    return "%.3f" % f


def _render_layer_run(font, master, text, contract):
    """Rasterize ``text`` using the current outlines at ``master``. Returns PNG bytes."""
    from AppKit import (
        NSAffineTransform,
        NSBezierPath,
        NSBitmapImageRep,
        NSColor,
        NSDeviceRGBColorSpace,
        NSGraphicsContext,
    )

    canvas_w = int(contract.get("canvas_w", 900))
    canvas_h = int(contract.get("canvas_h", 260))
    margin_x = int(contract.get("margin_x", 24))
    em_px = float(contract.get("em_px", 160.0))
    baseline_y = float(contract.get("baseline_y", 56.0))
    unknown_advance_upm = float(contract.get("unknown_advance_upm", 250.0))

    upm_raw = getattr(font, "upm", 1000) or 1000
    try:
        upm = float(upm_raw)
    except (TypeError, ValueError):
        upm = 1000.0
    scale = em_px / upm

    rep = (
        NSBitmapImageRep.alloc()
        .initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
            None,
            canvas_w,
            canvas_h,
            8,
            4,
            True,
            False,
            NSDeviceRGBColorSpace,
            0,
            32,
        )
    )
    if rep is None:
        raise RuntimeError("failed to allocate NSBitmapImageRep")

    gc = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(gc)
    try:
        NSColor.whiteColor().set()
        NSBezierPath.bezierPathWithRect_(((0, 0), (canvas_w, canvas_h))).fill()
        NSColor.blackColor().set()

        x = float(margin_x)
        right_limit = float(canvas_w - margin_x)
        for ch in text:
            glyph = _lookup_char(font, ch)
            layer = None
            if glyph is not None:
                try:
                    layer = glyph.layers[master.id]
                except Exception:
                    layer = None

            if layer is not None:
                try:
                    path = layer.completeBezierPath
                except Exception:
                    path = None
                if path is not None:
                    tr = NSAffineTransform.alloc().init()
                    tr.translateXBy_yBy_(x, baseline_y)
                    tr.scaleXBy_yBy_(scale, scale)
                    transformed = tr.transformBezierPath_(path)
                    transformed.fill()
                try:
                    adv = float(layer.width)
                except Exception:
                    adv = unknown_advance_upm
                x += adv * scale
            else:
                x += unknown_advance_upm * scale

            if x > right_limit:
                break
    finally:
        NSGraphicsContext.restoreGraphicsState()

    png_type = 4
    png_data = rep.representationUsingType_properties_(png_type, {})
    if png_data is None:
        raise RuntimeError("failed to encode PNG")
    return bytes(png_data)


def _lookup_char(font, ch):
    if not ch:
        return None
    try:
        return font.glyphForCharacter_(ord(ch))
    except Exception:
        return None
