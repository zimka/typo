# encoding: utf-8
"""
Agent tools for Typo Chat (Phase 2).

Eight tools are exposed to the model via Anthropic ``tools`` parameter:

Read-only:
- ``list_masters``       — enumerate masters of the current font.
- ``list_glyphs``        — list glyph names (optional substring filter).
- ``get_glyph``          — dump a glyph's paths/nodes/anchors/metrics as text.
- ``render_specimen``    — rasterize a text using the current font state (returns PNG).

Edit:
- ``move_nodes_where``   — move nodes in ``glyph@master`` whose coordinates match a predicate.

Snapshot / diff:
- ``save_snapshot``      — capture geometry of the listed glyphs (one slot, overwrites).
- ``reset_snapshot``     — restore the saved geometry (revert edits).
- ``diff_pre_post``      — render pre (from snapshot), post (live), and R/G overlay.

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
            "the single edit primitive: one call should do one atomic geometric change. "
            "Call save_snapshot FIRST before any move_nodes_where so the user can undo."
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
    {
        "name": "save_snapshot",
        "description": (
            "Capture the current geometry (node positions, anchors, widths across all masters) "
            "of the listed glyphs. One slot only — a second call overwrites. You MUST call "
            "this BEFORE the first move_nodes_where in a fix so the user (or you) can revert "
            "via reset_snapshot and so diff_pre_post can render the before/after comparison."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "glyph_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Glyph names you plan to edit. Must be non-empty.",
                }
            },
            "required": ["glyph_names"],
        },
    },
    {
        "name": "reset_snapshot",
        "description": (
            "Restore the geometry saved by save_snapshot. Use when your edits went the wrong "
            "way and you want to revise the plan, or to undo an exploratory attempt. The "
            "snapshot itself is kept (a reset can be applied multiple times)."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "diff_pre_post",
        "description": (
            "Render the specimen three times into one reply: pre (from the active snapshot), "
            "post (from the live current font), and an R/G overlay (red = pre, green = post, "
            "yellow = both) on a black background. Requires an active snapshot — call "
            "save_snapshot first."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Specimen text (same as was used for render_specimen)."},
                "master": {"type": "string", "description": "Master name or id. Defaults to the first master."},
                "size": {"type": "integer", "description": "Em size in pixels. Default 160."},
            },
            "required": ["text"],
        },
    },
]


class ToolContext:
    """Plugin-level state passed to every tool call."""

    def __init__(self, font_provider, render_contract=None, snapshot_store=None):
        self._font_provider = font_provider
        self.render_contract = dict(render_contract or DEFAULT_RENDER_CONTRACT)
        self.snapshot_store = snapshot_store if snapshot_store is not None else SnapshotStore()

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


def _handle_save_snapshot(args, ctx, font):
    names_raw = args.get("glyph_names")
    if isinstance(names_raw, str):
        names_raw = [names_raw]
    if not isinstance(names_raw, list) or not names_raw:
        return "[error] 'glyph_names' must be a non-empty list of glyph names."
    names = [str(n).strip() for n in names_raw if str(n).strip()]
    if not names:
        return "[error] 'glyph_names' must contain non-empty strings."
    missing = [n for n in names if _resolve_glyph(font, n) is None]
    if missing:
        return "[error] Glyph not found: %s" % ", ".join(missing)

    had_prev = ctx.snapshot_store.has_snapshot()
    info = ctx.snapshot_store.save(font, names)
    prefix = "Overwrote previous snapshot. " if had_prev else ""
    return "%sSnapshot saved for %d glyph(s) across %d layer(s): %s" % (
        prefix,
        len(info["glyph_names"]),
        info["layers"],
        ", ".join(info["glyph_names"]),
    )


def _handle_reset_snapshot(args, ctx, font):
    if not ctx.snapshot_store.has_snapshot():
        return "[error] No active snapshot — call save_snapshot first."
    info = ctx.snapshot_store.reset(font)
    return "Snapshot restored: %d glyph(s) reverted (%s). Snapshot is still active." % (
        len(info["glyph_names"]),
        ", ".join(info["glyph_names"]),
    )


def _handle_diff_pre_post(args, ctx, font):
    text = str(args.get("text") or "")
    if not text:
        return "[error] 'text' is required."
    master = _resolve_master(font, args.get("master"))
    if master is None:
        return "[error] Master not found: %s" % args.get("master")
    if not ctx.snapshot_store.has_snapshot():
        return "[error] No active snapshot — call save_snapshot([...]) before diff_pre_post."

    contract = dict(ctx.render_contract)
    size = args.get("size")
    if size is not None:
        try:
            contract["em_px"] = float(size)
        except (TypeError, ValueError):
            return "[error] 'size' must be a number."

    store = ctx.snapshot_store
    pre_png = store.render_pre(font, master, text, contract)
    post_png = _render_layer_run(font, master, text, contract)
    overlay_png = _render_overlay_run(font, master, text, contract, store)
    header = "diff_pre_post master=%s text=%r snapshot_glyphs=%s" % (
        master.name,
        text,
        list(store._glyph_names),
    )
    return [
        header,
        "pre (snapshot):",
        pre_png,
        "post (live):",
        post_png,
        "overlay (red=pre, green=post, yellow=overlap):",
        overlay_png,
    ]


_HANDLERS = {
    "list_masters": _handle_list_masters,
    "list_glyphs": _handle_list_glyphs,
    "get_glyph": _handle_get_glyph,
    "render_specimen": _handle_render_specimen,
    "move_nodes_where": _handle_move_nodes_where,
    "save_snapshot": _handle_save_snapshot,
    "reset_snapshot": _handle_reset_snapshot,
    "diff_pre_post": _handle_diff_pre_post,
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


# ---------------------------------------------------------------------------
# Snapshot store: one slot of per-glyph-per-master geometry (node positions,
# anchors, widths). Sufficient to undo any move_nodes_where sequence because
# that tool only changes positions, not topology. Stored as plain dicts so we
# don't keep references to Objective-C objects and the snapshot survives any
# subsequent Glyphs-internal mutations.
# ---------------------------------------------------------------------------


def _snapshot_layer_data(layer):
    paths = []
    for path in (layer.paths or []):
        nodes = []
        for node in (path.nodes or []):
            nodes.append(
                {"x": float(node.position.x), "y": float(node.position.y)}
            )
        paths.append({"nodes": nodes})
    anchors = []
    for anchor in (getattr(layer, "anchors", None) or []):
        try:
            nm = anchor.name
        except Exception:
            nm = None
        if not nm:
            continue
        anchors.append(
            {"name": nm, "x": float(anchor.position.x), "y": float(anchor.position.y)}
        )
    width = None
    try:
        width = float(layer.width)
    except Exception:
        pass
    return {"paths": paths, "anchors": anchors, "width": width}


def _apply_layer_data(layer, data):
    live_paths = list(layer.paths or [])
    snap_paths = data.get("paths") or []
    for pi, path in enumerate(live_paths):
        if pi >= len(snap_paths):
            break
        snap_nodes = snap_paths[pi].get("nodes") or []
        live_nodes = list(path.nodes or [])
        for ni, node in enumerate(live_nodes):
            if ni >= len(snap_nodes):
                break
            sn = snap_nodes[ni]
            node.position = _point(sn["x"], sn["y"])
    w = data.get("width")
    if w is not None:
        try:
            layer.width = w
        except Exception:
            pass
    snap_anchors_by_name = {
        a["name"]: a for a in (data.get("anchors") or []) if a.get("name")
    }
    for anchor in (getattr(layer, "anchors", None) or []):
        try:
            nm = anchor.name
        except Exception:
            nm = None
        if not nm:
            continue
        sa = snap_anchors_by_name.get(nm)
        if sa is None:
            continue
        anchor.position = _point(sa["x"], sa["y"])


def _snapshot_glyphs(font, glyph_names):
    """Return ``{glyph_name: {master_id: layer_data}}`` for the requested glyphs."""
    out = {}
    for name in glyph_names:
        glyph = _resolve_glyph(font, name)
        if glyph is None:
            continue
        layers = {}
        for master in font.masters:
            try:
                layer = glyph.layers[master.id]
            except Exception:
                layer = None
            if layer is None:
                continue
            layers[master.id] = _snapshot_layer_data(layer)
        out[name] = layers
    return out


def _apply_snapshot(font, snapshot):
    """Apply a snapshot back into the font's live layers."""
    if not snapshot:
        return
    for name, layers in snapshot.items():
        glyph = _resolve_glyph(font, name)
        if glyph is None:
            continue
        for master_id, data in layers.items():
            try:
                layer = glyph.layers[master_id]
            except Exception:
                layer = None
            if layer is None:
                continue
            _apply_layer_data(layer, data)


class SnapshotStore:
    """One-slot geometry snapshot for a subset of glyphs.

    - ``save(font, glyph_names)``: capture node positions / anchors / widths for all
      masters of the listed glyphs. Overwrites any previous snapshot.
    - ``reset(font)``: write the snapshot back into the live font. The snapshot is
      kept — resetting twice is allowed.
    - ``render_pre(font, master, text, contract)``: temporarily install the snapshot
      into the live font, render, then restore the live state. Used by ``diff_pre_post``.
    - ``has_snapshot()`` / ``clear()``: lifecycle helpers.
    """

    def __init__(self):
        self._slot = None
        self._glyph_names = []

    def has_snapshot(self):
        return self._slot is not None

    def clear(self):
        self._slot = None
        self._glyph_names = []

    def save(self, font, glyph_names):
        names = [str(n).strip() for n in (glyph_names or []) if str(n).strip()]
        if not names:
            raise ValueError("glyph_names must be a non-empty list")
        self._slot = _snapshot_glyphs(font, names)
        self._glyph_names = names
        layers_count = sum(len(v) for v in self._slot.values())
        return {"glyph_names": list(names), "layers": layers_count}

    def reset(self, font):
        if not self.has_snapshot():
            raise ValueError("no active snapshot")
        _apply_snapshot(font, self._slot)
        return {"glyph_names": list(self._glyph_names)}

    def render_pre(self, font, master, text, contract):
        """Render ``text`` as if the snapshot were the current font state.

        Strategy: snapshot current geometry for the same glyphs, apply the stored
        snapshot, render, then restore the current geometry. This is synchronous on
        the main thread, so no intermediate UI frame is observable.
        """
        if not self.has_snapshot():
            raise ValueError("no active snapshot")
        current = _snapshot_glyphs(font, self._glyph_names)
        _apply_snapshot(font, self._slot)
        try:
            return _render_layer_run(font, master, text, contract)
        finally:
            _apply_snapshot(font, current)


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


def _make_bitmap_rep(canvas_w, canvas_h):
    from AppKit import NSBitmapImageRep, NSDeviceRGBColorSpace

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
    return rep


def _encode_png(rep):
    png_type = 4  # NSBitmapImageFileTypePNG
    png_data = rep.representationUsingType_properties_(png_type, {})
    if png_data is None:
        raise RuntimeError("failed to encode PNG")
    return bytes(png_data)


def _draw_glyphs_run(font, master, text, contract):
    """Draw the specimen glyph outlines onto the current NSGraphicsContext, filled with
    the currently set color. Factored out so both plain rendering and the R/G overlay
    can reuse the exact same layout and glyph-lookup logic."""
    from AppKit import NSAffineTransform

    canvas_w = int(contract.get("canvas_w", 900))
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


def _render_layer_run(font, master, text, contract):
    """Rasterize ``text`` using the current outlines at ``master``. Returns PNG bytes."""
    from AppKit import NSBezierPath, NSColor, NSGraphicsContext

    canvas_w = int(contract.get("canvas_w", 900))
    canvas_h = int(contract.get("canvas_h", 260))

    rep = _make_bitmap_rep(canvas_w, canvas_h)
    gc = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(gc)
    try:
        NSColor.whiteColor().set()
        NSBezierPath.bezierPathWithRect_(((0, 0), (canvas_w, canvas_h))).fill()
        NSColor.blackColor().set()
        _draw_glyphs_run(font, master, text, contract)
    finally:
        NSGraphicsContext.restoreGraphicsState()

    return _encode_png(rep)


def _render_white_on_black_rep(font, master, text, contract):
    """Rasterize glyph fills as white on an opaque black background (single mask pass)."""
    from AppKit import (
        NSBezierPath,
        NSColor,
        NSCompositingOperationSourceOver,
        NSGraphicsContext,
    )

    canvas_w = int(contract.get("canvas_w", 900))
    canvas_h = int(contract.get("canvas_h", 260))
    rep = _make_bitmap_rep(canvas_w, canvas_h)
    gc = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(gc)
    try:
        NSColor.blackColor().set()
        NSBezierPath.bezierPathWithRect_(((0, 0), (canvas_w, canvas_h))).fill()
        NSGraphicsContext.currentContext().setCompositingOperation_(
            NSCompositingOperationSourceOver
        )
        NSColor.whiteColor().set()
        _draw_glyphs_run(font, master, text, contract)
    finally:
        NSGraphicsContext.restoreGraphicsState()
    return rep


def _bitmap_rep_row_bytes(rep):
    """Copy packed row bytes from a non-planar 32-bpp ``NSBitmapImageRep`` (includes row padding)."""
    bpr = int(rep.bytesPerRow())
    h = int(rep.pixelsHigh())
    n = bpr * h
    ptr = rep.bitmapData()
    if ptr is None:
        raise RuntimeError("NSBitmapImageRep.bitmapData() is None")
    try:
        return bytearray(memoryview(ptr).tobytes()[:n])
    except TypeError:
        from ctypes import string_at

        addr = int(ptr)
        return bytearray(string_at(addr, n))


def _merge_silhouettes_to_overlay_rg(pre_buf, post_buf, out_buf, bpr, h, w):
    """Combine two white-on-black masks into red/green overlay (yellow = overlap).

    Avoids ``NSCompositingOperationPlusLighter`` on bitmap contexts, which can drop
    interior pixels (premultiplied alpha / compositing quirks) so only edge fringes
    remain visible.
    """
    for y in range(h):
        row = y * bpr
        for x in range(w):
            i = row + x * 4
            lp = (pre_buf[i] + pre_buf[i + 1] + pre_buf[i + 2]) / (3.0 * 255.0)
            lq = (post_buf[i] + post_buf[i + 1] + post_buf[i + 2]) / (3.0 * 255.0)
            lp = max(0.0, min(1.0, lp))
            lq = max(0.0, min(1.0, lq))
            out_buf[i] = int(round(lp * 255.0))
            out_buf[i + 1] = int(round(lq * 255.0))
            out_buf[i + 2] = 0
            out_buf[i + 3] = 255


def _bitmap_rep_write_row_bytes(rep, buf):
    bpr = int(rep.bytesPerRow())
    h = int(rep.pixelsHigh())
    n = bpr * h
    if len(buf) != n:
        raise RuntimeError("buffer length does not match bitmap")
    ptr = rep.bitmapData()
    if ptr is None:
        raise RuntimeError("NSBitmapImageRep.bitmapData() is None")
    try:
        memoryview(ptr).cast("B")[:n] = buf
    except TypeError:
        from ctypes import addressof, c_char, memmove

        raw = (c_char * n).from_buffer(buf)
        memmove(int(ptr), addressof(raw), n)


def _render_overlay_run(font, master, text, contract, store):
    """Render the R/G overlay: red = pre (snapshot), green = post (live), yellow = overlap.

    Implementation: draw snapshot and live glyphs as white-on-black masks, then merge
    pixels so channels are independent (no additive compositing in the graphics state).
    Returns PNG bytes."""
    canvas_w = int(contract.get("canvas_w", 900))
    canvas_h = int(contract.get("canvas_h", 260))

    current_snap = _snapshot_glyphs(font, store._glyph_names)
    _apply_snapshot(font, store._slot)
    try:
        pre_rep = _render_white_on_black_rep(font, master, text, contract)
    finally:
        _apply_snapshot(font, current_snap)

    post_rep = _render_white_on_black_rep(font, master, text, contract)

    bpr = int(pre_rep.bytesPerRow())
    h = int(pre_rep.pixelsHigh())
    w = int(pre_rep.pixelsWide())
    if (
        bpr != int(post_rep.bytesPerRow())
        or h != int(post_rep.pixelsHigh())
        or w != int(post_rep.pixelsWide())
    ):
        raise RuntimeError("overlay silhouette bitmaps differ in layout")

    pre_buf = _bitmap_rep_row_bytes(pre_rep)
    post_buf = _bitmap_rep_row_bytes(post_rep)
    out_buf = bytearray(bpr * h)
    _merge_silhouettes_to_overlay_rg(pre_buf, post_buf, out_buf, bpr, h, w)

    out_rep = _make_bitmap_rep(canvas_w, canvas_h)
    _bitmap_rep_write_row_bytes(out_rep, out_buf)
    return _encode_png(out_rep)


def _lookup_char(font, ch):
    if not ch:
        return None
    try:
        return font.glyphForCharacter_(ord(ch))
    except Exception:
        return None
