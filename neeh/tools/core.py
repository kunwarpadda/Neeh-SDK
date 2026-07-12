"""The v1 tool surface.

Conventions:
- Tools are the AGENT's hands and eyes — all ink they create is
  author=AGENT on the page's agent layer, never on user layers.
- Regions are [min_x, min_y, max_x, max_y] in page coordinates.
- Points are [x, y] or [x, y, t_ms, pressure, tilt_x, tilt_y].
- Every tool returns a JSON-serializable dict.
"""
from __future__ import annotations

import base64
import math
from typing import Any, Optional, Sequence

from neeh.canvas import Canvas
from neeh.document import Page
from neeh.ink import Author, BoundingBox, Stroke, StrokeStyle
from neeh.rendering import render_page_svg
from neeh.tools.registry import tool

_FORMAT_SCHEMA = {
    "type": "string",
    "enum": ["svg", "png"],
    "description": "svg returns markup; png returns base64 (needs the Pillow extra)",
}


def _render(page: Page, region: Optional[BoundingBox], fmt: str) -> dict[str, Any]:
    if fmt == "png":
        from neeh.rendering.png import render_page_png  # optional extra, import lazily

        return {"format": "png", "data": base64.b64encode(
            render_page_png(page, region=region)).decode("ascii")}
    return {"format": "svg", "data": render_page_svg(page, region=region)}

_REGION_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 4,
    "maxItems": 4,
    "description": "[min_x, min_y, max_x, max_y] in page coordinates",
}
_POINTS_SCHEMA = {
    "type": "array",
    "minItems": 1,
    "items": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 6},
    "description": "Points as [x, y] or [x, y, t_ms, pressure, tilt_x, tilt_y]",
}
_IDS_SCHEMA = {"type": "array", "items": {"type": "string"}}
_AUTHOR_SCHEMA = {"type": "string", "enum": ["user", "agent"]}


def _finite_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


def _stroke_ids(values: Optional[Sequence[str]], name: str = "stroke_ids") -> Optional[list[str]]:
    if values is None:
        return None
    if isinstance(values, (str, bytes, bytearray)):
        raise ValueError(f"{name} must be an array of non-empty strings")
    result = list(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError(f"{name} must contain only non-empty strings")
    return list(dict.fromkeys(result))


def _region(data: Sequence[float]) -> BoundingBox:
    return BoundingBox.from_list(data)


def _stroke_record(layer_id: str, layer_name: str, stroke, include_points: bool) -> dict[str, Any]:
    record = {
        "id": stroke.id,
        "layer_id": layer_id,
        "layer_name": layer_name,
        "author": stroke.author.value,
        "created_at_ms": stroke.created_at_ms,
        "duration_ms": stroke.duration_ms,
        "bbox": stroke.bbox.to_list(),
        "style": stroke.style.to_dict(),
        "point_count": len(stroke.points),
    }
    if include_points:
        record["points"] = [point.to_list() for point in stroke.points]
    return record


@tool(
    "view_page",
    "Render the current page so you can see it, as SVG markup or a base64 PNG.",
    {"type": "object", "properties": {"format": _FORMAT_SCHEMA}, "required": []},
)
def view_page(canvas: Canvas, format: str = "svg") -> dict[str, Any]:
    if format not in ("svg", "png"):
        raise ValueError("format must be 'svg' or 'png'")
    page = canvas.page
    return {
        "page_id": page.id,
        "width": page.width,
        "height": page.height,
        **_render(page, None, format),
    }


@tool(
    "view_region",
    "Render a rectangular region of the current page at higher detail.",
    {
        "type": "object",
        "properties": {"region": _REGION_SCHEMA, "format": _FORMAT_SCHEMA},
        "required": ["region"],
    },
)
def view_region(canvas: Canvas, region: Sequence[float], format: str = "svg") -> dict[str, Any]:
    if format not in ("svg", "png"):
        raise ValueError("format must be 'svg' or 'png'")
    box = _region(region)
    return {
        "page_id": canvas.page.id,
        "region": box.to_list(),
        **_render(canvas.page, box, format),
    }


@tool(
    "fetch_ink_region",
    "Fetch compact vector ink for a region: one SVG <path> per stroke on an "
    "integer grid (the id attribute is the stable stroke id, drawn order "
    "preserved) plus per-stroke bounding boxes in page units. The cheapest "
    "way to read exact, addressable geometry for part of the page.",
    {
        "type": "object",
        "properties": {"region": _REGION_SCHEMA},
        "required": ["region"],
    },
)
def fetch_ink_region(canvas: Canvas, region: Sequence[float]) -> dict[str, Any]:
    from neeh.context import build_ink_context_v1

    box = _region(region)
    payload = build_ink_context_v1(canvas, region=box, stroke_bboxes=True)
    ink = payload["ink"]
    return {
        "page_id": canvas.page.id,
        "region": box.to_list(),
        "grid": ink["grid"],
        "svg": ink["svg"],
        "bboxes": ink.get("bboxes", {}),
        "stroke_count": ink["included_stroke_count"],
    }


@tool(
    "get_strokes",
    "Return vector ink records by region, ids, author, or time. Use this with view_page for "
    "precise coordinates, timestamps, authorship, and stable stroke ids.",
    {
        "type": "object",
        "properties": {
            "region": _REGION_SCHEMA,
            "stroke_ids": _IDS_SCHEMA,
            "author": _AUTHOR_SCHEMA,
            "since_ms": {
                "type": "integer",
                "description": "Only return strokes with created_at_ms >= this epoch ms",
            },
            "visible_only": {"type": "boolean"},
            "include_points": {"type": "boolean"},
        },
        "required": [],
    },
)
def get_strokes(
    canvas: Canvas,
    region: Optional[Sequence[float]] = None,
    stroke_ids: Optional[Sequence[str]] = None,
    author: Optional[str] = None,
    since_ms: Optional[int] = None,
    visible_only: bool = True,
    include_points: bool = True,
) -> dict[str, Any]:
    if author is not None and author not in (Author.USER.value, Author.AGENT.value):
        raise ValueError("author must be 'user' or 'agent'")
    if since_ms is not None and (
        isinstance(since_ms, bool) or not isinstance(since_ms, int) or since_ms < 0
    ):
        raise ValueError("since_ms must be a non-negative integer")
    if not isinstance(visible_only, bool):
        raise ValueError("visible_only must be a boolean")
    if not isinstance(include_points, bool):
        raise ValueError("include_points must be a boolean")
    page = canvas.page
    box = _region(region) if region is not None else None
    validated_ids = _stroke_ids(stroke_ids)
    id_filter = None if validated_ids is None else set(validated_ids)
    strokes = []
    for layer in page.layers:
        if visible_only and not layer.visible:
            continue
        for stroke in layer.strokes:
            if id_filter is not None and stroke.id not in id_filter:
                continue
            if box is not None and not box.intersects(stroke.bbox):
                continue
            if author is not None and stroke.author.value != author:
                continue
            if since_ms is not None and stroke.created_at_ms < since_ms:
                continue
            strokes.append(_stroke_record(layer.id, layer.name, stroke, include_points))
    return {
        "page_id": page.id,
        "width": page.width,
        "height": page.height,
        "region": box.to_list() if box else None,
        "stroke_count": len(strokes),
        "strokes": strokes,
    }


@tool(
    "add_stroke",
    "Draw a stroke on the agent layer of the current page.",
    {
        "type": "object",
        "properties": {
            "points": _POINTS_SCHEMA,
            "color": {"type": "string", "description": "Hex color, e.g. #1a1a1a"},
            "width": {"type": "number", "exclusiveMinimum": 0},
            "brush": {"type": "string", "enum": ["pen", "marker", "highlighter"]},
        },
        "required": ["points"],
    },
)
def add_stroke(
    canvas: Canvas,
    points: Sequence[Sequence[float]],
    color: Optional[str] = None,
    width: Optional[float] = None,
    brush: Optional[str] = None,
) -> dict[str, Any]:
    base = StrokeStyle()
    style = StrokeStyle(
        color=base.color if color is None else color,
        width=base.width if width is None else width,
        brush=base.brush if brush is None else brush,
    )
    stroke = canvas.add_stroke(points, style=style, author=Author.AGENT)
    return {"stroke_id": stroke.id, "bbox": stroke.bbox.to_list()}


@tool(
    "erase",
    "Erase strokes by id or by region. Locked layers are never touched.",
    {
        "type": "object",
        "properties": {"stroke_ids": _IDS_SCHEMA, "region": _REGION_SCHEMA},
        "required": [],
    },
)
def erase(
    canvas: Canvas,
    stroke_ids: Optional[Sequence[str]] = None,
    region: Optional[Sequence[float]] = None,
) -> dict[str, Any]:
    if (stroke_ids is None) == (region is None):
        raise ValueError("erase needs exactly one of stroke_ids or region")
    validated_ids = _stroke_ids(stroke_ids)
    erased = canvas.erase(
        stroke_ids=validated_ids,
        region=_region(region) if region is not None else None,
    )
    return {"erased": erased}


@tool(
    "select",
    "Select strokes by region or explicit ids; returns the selected ids and their bounds.",
    {
        "type": "object",
        "properties": {"region": _REGION_SCHEMA, "stroke_ids": _IDS_SCHEMA},
        "required": [],
    },
)
def select(
    canvas: Canvas,
    region: Optional[Sequence[float]] = None,
    stroke_ids: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    if stroke_ids is not None and region is not None:
        raise ValueError("select accepts at most one of stroke_ids or region")
    validated_ids = _stroke_ids(stroke_ids)
    selection = canvas.select(
        region=_region(region) if region is not None else None,
        stroke_ids=validated_ids,
    )
    bounds = selection.bounds(canvas.page)
    return {
        "selected": sorted(selection.stroke_ids),
        "bounds": bounds.to_list() if bounds else None,
    }


@tool(
    "move",
    "Translate strokes by (dx, dy). Defaults to the current selection; stroke ids are preserved.",
    {
        "type": "object",
        "properties": {
            "dx": {"type": "number"},
            "dy": {"type": "number"},
            "stroke_ids": _IDS_SCHEMA,
        },
        "required": ["dx", "dy"],
    },
)
def move(
    canvas: Canvas,
    dx: float,
    dy: float,
    stroke_ids: Optional[Sequence[str]] = None,
) -> dict[str, Any]:
    validated_ids = _stroke_ids(stroke_ids)
    return {
        "moved": canvas.move(
            _finite_number(dx, "dx"),
            _finite_number(dy, "dy"),
            stroke_ids=validated_ids,
        )
    }


@tool(
    "highlight",
    "Draw a translucent highlighter band across a region, on the agent layer (non-destructive).",
    {
        "type": "object",
        "properties": {"region": _REGION_SCHEMA, "color": {"type": "string"}},
        "required": ["region"],
    },
)
def highlight(canvas: Canvas, region: Sequence[float], color: str = "#ffe066") -> dict[str, Any]:
    box = _region(region)
    cy = box.center[1]
    style = StrokeStyle.highlighter(color=color, width=max(box.height, 1.0))
    stroke = canvas.add_stroke(
        [(box.min_x, cy), (box.max_x, cy)],
        style=style,
        author=Author.AGENT,
    )
    return {"stroke_id": stroke.id, "region": box.to_list()}


@tool(
    "write_text",
    "Write text into a region as ink strokes on the agent layer. The text is laid out "
    "top-left in the region, word-wrapped, auto-sized to fit (largest readable size). "
    "Style 'print' is a clean single-stroke font; 'handwritten' uses the "
    "calligraphic Hershey Script Complex face. 'user_font' is reserved.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "region": _REGION_SCHEMA,
            "style": {
                "type": "string",
                "enum": ["print", "handwritten"],
                "default": "handwritten",
            },
            "color": {"type": "string", "description": "Hex color, e.g. #1d4ed8"},
            "size": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Cap height in page units; omit to auto-fit the region",
            },
        },
        "required": ["text", "region"],
    },
)
def write_text(
    canvas: Canvas,
    text: str,
    region: Sequence[float],
    style: str = "handwritten",
    color: Optional[str] = None,
    size: Optional[float] = None,
) -> dict[str, Any]:
    if style == "user_font":
        raise NotImplementedError(
            "user_font requires a host-provided handwriting model; use "
            "style='handwritten' or style='print'"
        )
    from neeh.ink.textink import TEXT_STYLES, layout_text

    if style not in TEXT_STYLES:
        raise ValueError(f"style must be one of {TEXT_STYLES}")

    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if size is not None:
        size = _finite_number(size, "size")
        if size <= 0:
            raise ValueError("size must be positive")
    box = _region(region)
    polylines, used_size = layout_text(text, box, size=size, style=style)
    stroke_style = StrokeStyle(color=color or "#1a1a1a", width=max(used_size / 12.0, 0.8))
    strokes = canvas.add_strokes(polylines, style=stroke_style, author=Author.AGENT)
    return {
        "stroke_ids": [s.id for s in strokes],
        "size": used_size,
        "region": box.to_list(),
        "style": style,
    }


def _anchor_bbox(
    canvas: Canvas, stroke_ids: Sequence[str], name: str = "stroke_ids"
) -> BoundingBox:
    """Union bbox of the named strokes; unknown ids are an error."""
    ids = _stroke_ids(stroke_ids, name)
    if not ids:
        raise ValueError(f"{name} must name at least one stroke")
    wanted = set(ids)
    boxes = [s.bbox for layer in canvas.page.layers if layer.visible
             for s in layer.strokes if s.id in wanted]
    if len(boxes) < len(wanted):
        found = {s.id for layer in canvas.page.layers if layer.visible
                 for s in layer.strokes if s.id in wanted}
        missing = sorted(wanted - found)
        where = "" if name == "stroke_ids" else f" ({name})"
        raise ValueError(f"unknown stroke ids{where}: {missing}")
    return BoundingBox.union_all(boxes)


_MARK_KINDS = ("strike", "circle", "underline", "check")


@tool(
    "mark",
    "Annotate existing ink by stroke id — the geometry is computed for you "
    "from the strokes' bounding box. Kinds: 'strike' crosses the ink out, "
    "'underline' underlines it, 'circle' rings it, 'check' draws a check "
    "mark beside it. Prefer this over add_stroke for corrections: no "
    "coordinates needed.",
    {
        "type": "object",
        "properties": {
            "stroke_ids": _IDS_SCHEMA,
            "kind": {"type": "string", "enum": list(_MARK_KINDS)},
            "color": {"type": "string", "description": "Hex color, e.g. #1d4ed8"},
        },
        "required": ["stroke_ids", "kind"],
    },
)
def mark(
    canvas: Canvas,
    stroke_ids: Sequence[str],
    kind: str,
    color: Optional[str] = None,
) -> dict[str, Any]:
    if kind not in _MARK_KINDS:
        raise ValueError(f"kind must be one of {_MARK_KINDS}")
    box = _anchor_bbox(canvas, stroke_ids)
    cx, cy = box.center
    pad = max(box.height * 0.15, 3.0)
    if kind == "strike":
        points = [(box.min_x - pad, cy), (box.max_x + pad, cy)]
    elif kind == "underline":
        y = box.max_y + pad
        points = [(box.min_x, y), (box.max_x, y)]
    elif kind == "circle":
        rx = box.width / 2 + pad * 1.5
        ry = box.height / 2 + pad * 1.5
        points = [
            (cx + rx * math.cos(2 * math.pi * i / 24),
             cy + ry * math.sin(2 * math.pi * i / 24))
            for i in range(25)
        ]
    else:  # check
        h = max(box.height * 0.8, 8.0)
        x0 = box.max_x + pad * 2
        points = [(x0, cy), (x0 + h * 0.3, cy + h * 0.4), (x0 + h * 0.9, cy - h * 0.5)]
    style = StrokeStyle(
        color=color or StrokeStyle().color,
        width=max(box.height * 0.06, 1.2),
    )
    stroke = canvas.add_stroke(points, style=style, author=Author.AGENT)
    return {"stroke_id": stroke.id, "kind": kind, "anchor_bbox": box.to_list()}


_MIN_ARROW_RUN = 12.0


def _ray_box_exit(box: BoundingBox, ux: float, uy: float) -> float:
    """Distance from the box center along the unit ray (ux, uy) to its boundary."""
    tx = (box.width / 2) / abs(ux) if ux else math.inf
    ty = (box.height / 2) / abs(uy) if uy else math.inf
    return min(tx, ty)


def _arrow_standoff(box: BoundingBox) -> float:
    """How far outside a box an arrow endpoint sits, so it never touches the ink."""
    return min(max(4.0, 0.15 * max(box.width, box.height)), 14.0)


def _arrow_geometry(
    page: Page, target: BoundingBox, source: Optional[BoundingBox] = None,
) -> tuple[list[list[tuple[float, float]]], float, tuple[float, float], tuple[float, float]]:
    """Shaft + arrowhead polylines for an arrow whose tip stands just outside
    ``target``. With a ``source`` box the tail stands off it; otherwise the
    tail is placed toward the page interior at a default shaft length, clamped
    on-page. Returns (polylines, width, tail, tip)."""
    tcx, tcy = target.center
    if source is not None:
        scx, scy = source.center
    else:
        scx, scy = page.width / 2, page.height / 2
    dx, dy = tcx - scx, tcy - scy
    length = math.hypot(dx, dy)
    if length < 1e-6:
        if source is not None:
            raise ValueError("source and target ink coincide; nothing to point between")
        dx, dy, length = 1.0, 1.0, math.sqrt(2.0)  # target at page center: point down-right
    ux, uy = dx / length, dy / length

    # The tip approaches the target along the ray and stops on its near side.
    tip_t = _ray_box_exit(target, ux, uy) + _arrow_standoff(target)
    tip = (tcx - ux * tip_t, tcy - uy * tip_t)
    if source is not None:
        tail_t = _ray_box_exit(source, ux, uy) + _arrow_standoff(source)
        tail = (scx + ux * tail_t, scy + uy * tail_t)
    else:
        shaft = min(max(1.5 * max(target.width, target.height), 48.0), 160.0)
        tail = (
            min(max(tip[0] - ux * shaft, 4.0), page.width - 4.0),
            min(max(tip[1] - uy * shaft, 4.0), page.height - 4.0),
        )

    # Guard the SIGNED length along the intended direction: standoffs around
    # near-touching boxes can push the tail past the tip, flipping the arrow.
    if (tip[0] - tail[0]) * ux + (tip[1] - tail[1]) * uy < _MIN_ARROW_RUN:
        raise ValueError("source and target ink are too close to connect with an arrow")
    run = math.hypot(tip[0] - tail[0], tip[1] - tail[1])
    # Head barbs follow the drawn shaft, which page clamping may have re-aimed.
    hx, hy = (tip[0] - tail[0]) / run, (tip[1] - tail[1]) / run
    head = min(max(6.0, 0.22 * run), 16.0)
    back = (tip[0] - hx * head, tip[1] - hy * head)
    left = (back[0] - hy * head * 0.55, back[1] + hx * head * 0.55)
    right = (back[0] + hy * head * 0.55, back[1] - hx * head * 0.55)
    width = min(max(run / 60.0, 1.4), 3.0)
    return [[tail, tip], [left, tip, right]], width, tail, tip


@tool(
    "connect",
    "Point at existing ink with an arrow — the geometry is computed for you "
    "from the strokes' bounding boxes. The tip lands just outside the ink "
    "named by stroke_ids; give source_stroke_ids to start the arrow from "
    "other ink instead of blank space. Prefer this over add_stroke whenever "
    "an arrow should reference ink already on the page: no coordinates "
    "needed. To attach a written note to a target, prefer annotate.",
    {
        "type": "object",
        "properties": {
            "stroke_ids": _IDS_SCHEMA,
            "source_stroke_ids": _IDS_SCHEMA,
            "color": {"type": "string", "description": "Hex color, e.g. #1d4ed8"},
        },
        "required": ["stroke_ids"],
    },
)
def connect(
    canvas: Canvas,
    stroke_ids: Sequence[str],
    source_stroke_ids: Optional[Sequence[str]] = None,
    color: Optional[str] = None,
) -> dict[str, Any]:
    target = _anchor_bbox(canvas, stroke_ids)
    source: Optional[BoundingBox] = None
    if source_stroke_ids is not None:
        source = _anchor_bbox(canvas, source_stroke_ids, name="source_stroke_ids")
    polylines, width, tail, tip = _arrow_geometry(canvas.page, target, source)
    style = StrokeStyle(color=color or StrokeStyle().color, width=width)
    strokes = canvas.add_strokes(polylines, style=style, author=Author.AGENT)
    return {
        "stroke_ids": [s.id for s in strokes],
        "from": [tail[0], tail[1]],
        "to": [tip[0], tip[1]],
        "target_bbox": target.to_list(),
        "source_bbox": source.to_list() if source is not None else None,
    }


_ANNOTATE_SIDES = ("auto", "left", "right", "above", "below")
_ANNOTATE_DEFAULT_SIZE = 24.0
_ANNOTATE_GAP = 44.0  # clear span from target to note; must exceed both standoffs


_HORIZONTAL_SIDES = ("left", "right")
_NOTE_MARGIN = 6.0
_NOTE_OBSTACLE_PAD = 4.0


def _side_room(page: Page, target: BoundingBox, side: str) -> float:
    """Blank page span beyond the target's edge on ``side``."""
    if side == "right":
        return page.width - target.max_x
    if side == "left":
        return target.min_x
    if side == "above":
        return target.min_y
    return page.height - target.max_y  # below


def _ordered_sides(side: str, page: Page, target: BoundingBox) -> list[str]:
    """Sides to try in order. A note reads best beside its target, so horizontal
    sides lead (roomier one first) with vertical sides as fallback. An explicit
    choice leads, then the same ranking for collision fallback."""
    room = lambda s: _side_room(page, target, s)  # noqa: E731
    ranked = (sorted(_HORIZONTAL_SIDES, key=room, reverse=True)
              + sorted(("below", "above"), key=room, reverse=True))
    if side == "auto":
        return ranked
    return [side] + [s for s in ranked if s != side]


def _place_on_side(
    page: Page, target: BoundingBox, w: float, h: float,
    side: str, gap: float, offset: float,
) -> BoundingBox:
    """A w×h box `gap` off the target's ``side``, slid by ``offset`` along the
    perpendicular axis, then shifted (never shrunk) to stay on-page."""
    tcx, tcy = target.center
    if side == "right":
        x0, y0 = target.max_x + gap, tcy - h / 2 + offset
    elif side == "left":
        x0, y0 = target.min_x - gap - w, tcy - h / 2 + offset
    elif side == "above":
        x0, y0 = tcx - w / 2 + offset, target.min_y - gap - h
    else:  # below
        x0, y0 = tcx - w / 2 + offset, target.max_y + gap
    m = _NOTE_MARGIN
    x0 = min(max(x0, m), max(m, page.width - m - w))
    y0 = min(max(y0, m), max(m, page.height - m - h))
    return BoundingBox(x0, y0, x0 + w, y0 + h)


def _overlap_area(box: BoundingBox, obstacles: Sequence[BoundingBox], pad: float) -> float:
    """Total area `box` overlaps any obstacle, each grown by ``pad``."""
    total = 0.0
    for ob in obstacles:
        ix = min(box.max_x, ob.max_x + pad) - max(box.min_x, ob.min_x - pad)
        iy = min(box.max_y, ob.max_y + pad) - max(box.min_y, ob.min_y - pad)
        if ix > 0 and iy > 0:
            total += ix * iy
    return total


def _note_box(
    page: Page, target: BoundingBox, w: float, h: float, side: str, gap: float,
    obstacles: Sequence[BoundingBox],
) -> tuple[BoundingBox, str]:
    """Place a w×h note beside ``target`` clear of existing ink.

    Tries each side (the explicit choice or, for 'auto', roomiest first),
    sliding along the perpendicular axis to dodge obstacles. Returns the first
    fully-clear spot; if the page is too crowded for any, returns the
    least-overlapping candidate so annotate still produces a note."""
    best: Optional[tuple[float, BoundingBox, str]] = None
    for candidate_side in _ordered_sides(side, page, target):
        extent = h if candidate_side in _HORIZONTAL_SIDES else w
        step = 0.6 * extent
        offsets = [0.0] + [sign * k * step for k in (1, 2, 3) for sign in (1, -1)]
        for offset in offsets:
            box = _place_on_side(page, target, w, h, candidate_side, gap, offset)
            # Score other ink with a small pad, but require the full gap of
            # clearance from the target itself: a side without room clamps the
            # note back toward the target, which looks wrong and leaves the
            # bound arrow too little run to draw.
            overlap = (_overlap_area(box, obstacles, _NOTE_OBSTACLE_PAD)
                       + _overlap_area(box, [target], gap))
            if overlap == 0.0:
                return box, candidate_side
            if best is None or overlap < best[0]:
                best = (overlap, box, candidate_side)
    assert best is not None  # _ordered_sides is never empty
    return best[1], best[2]


@tool(
    "annotate",
    "Attach a written note to existing ink and point an arrow from the note to "
    "it — one atomic action. The note is placed in blank space beside the ink "
    "named by stroke_ids and an arrow is drawn from the note to that ink, with "
    "all geometry computed for you. This is the reliable way to caption or "
    "explain part of a drawing: it keeps each note bound to the ink it "
    "describes, so labels and arrows never cross or get mispaired. 'side' "
    "chooses which side of the target the note sits on (default 'auto').",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "stroke_ids": _IDS_SCHEMA,
            "side": {"type": "string", "enum": list(_ANNOTATE_SIDES), "default": "auto"},
            "color": {"type": "string", "description": "Hex color, e.g. #1d4ed8"},
            "size": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Cap height in page units; omit for a default size",
            },
        },
        "required": ["text", "stroke_ids"],
    },
)
def annotate(
    canvas: Canvas,
    text: str,
    stroke_ids: Sequence[str],
    side: str = "auto",
    color: Optional[str] = None,
    size: Optional[float] = None,
) -> dict[str, Any]:
    from neeh.ink.textink import layout_text, measure_text  # optional font tables

    if not isinstance(text, str) or not text.strip():
        raise ValueError("annotate text must be a non-empty string")
    if side not in _ANNOTATE_SIDES:
        raise ValueError(f"side must be one of {_ANNOTATE_SIDES}")
    if size is not None:
        size = _finite_number(size, "size")
        if size <= 0:
            raise ValueError("size must be positive")
    target = _anchor_bbox(canvas, stroke_ids)
    style_name = "handwritten"
    cap = size or _ANNOTATE_DEFAULT_SIZE
    w, h = measure_text(text, cap, style_name)
    target_ids = set(_stroke_ids(stroke_ids) or [])
    obstacles = [
        stroke.bbox
        for layer in canvas.page.layers if layer.visible
        for stroke in layer.strokes if stroke.id not in target_ids
    ]
    box, side = _note_box(canvas.page, target, w, h, side, _ANNOTATE_GAP, obstacles)
    polylines, used = layout_text(text, box, size=cap, style=style_name)
    if not polylines:
        raise ValueError("annotate text produced no ink")

    xs = [x for line in polylines for x, _ in line]
    ys = [y for line in polylines for _, y in line]
    note_box = BoundingBox(min(xs), min(ys), max(xs), max(ys))
    arrow_lines, arrow_width, tail, tip = _arrow_geometry(canvas.page, target, note_box)

    ink_color = color or StrokeStyle().color
    text_style = StrokeStyle(color=ink_color, width=max(used / 12.0, 0.8))
    arrow_style = StrokeStyle(color=ink_color, width=arrow_width)
    groups = [(line, text_style) for line in polylines]
    groups += [(line, arrow_style) for line in arrow_lines]
    strokes = canvas.add_styled_strokes(groups, author=Author.AGENT, label="annotate")

    text_ids = [s.id for s in strokes[:len(polylines)]]
    arrow_ids = [s.id for s in strokes[len(polylines):]]
    return {
        "text_stroke_ids": text_ids,
        "arrow_stroke_ids": arrow_ids,
        "note_bbox": note_box.to_list(),
        "target_bbox": target.to_list(),
        "side": side,
        "size": used,
        "from": [tail[0], tail[1]],
        "to": [tip[0], tip[1]],
    }


_INSERT_POSITIONS = ("before", "after", "above", "below")
_MAX_INSERT_REFLOW = 64.0


def _translated_box(box: BoundingBox, dx: float, dy: float) -> BoundingBox:
    return BoundingBox(
        box.min_x + dx,
        box.min_y + dy,
        box.max_x + dx,
        box.max_y + dy,
    )


def _same_line_strokes(
    canvas: Canvas,
    anchor: BoundingBox,
    size: float,
) -> list[tuple[Stroke, bool]]:
    """Visible line ink paired with whether automatic reflow may move it."""
    vertical_pad = max(size * 0.35, 4.0)
    min_y = anchor.min_y - vertical_pad
    max_y = anchor.max_y + vertical_pad
    max_stroke_height = max(size * 2.5, anchor.height * 2.5, 12.0)
    return [
        (stroke, not layer.locked and stroke.author is Author.USER)
        for layer in canvas.page.layers
        if layer.visible
        for stroke in layer.strokes
        if stroke.bbox.max_y >= min_y
        and stroke.bbox.min_y <= max_y
        and stroke.bbox.height <= max_stroke_height
    ]


def _horizontal_insert_reflow(
    canvas: Canvas,
    anchor_ids: Sequence[str],
    anchor: BoundingBox,
    position: str,
    text_width: float,
    gap: float,
    size: float,
) -> tuple[BoundingBox, list[str], float]:
    """Open a bounded gap for before/after insertion by shifting trailing ink."""
    if position not in ("before", "after"):
        return anchor, [], 0.0

    anchor_set = set(anchor_ids)
    line_entries = _same_line_strokes(canvas, anchor, size)
    line = [stroke for stroke, _ in line_entries]
    movable = {stroke.id for stroke, can_move in line_entries if can_move}
    others = [stroke for stroke in line if stroke.id not in anchor_set]
    epsilon = 1e-6

    if position == "before":
        left = [stroke for stroke in others if stroke.bbox.max_x <= anchor.min_x + epsilon]
        if not left:
            return anchor, [], 0.0
        nearest_edge = max(stroke.bbox.max_x for stroke in left)
        desired_min_x = anchor.min_x - gap - text_width
        shift = max(0.0, nearest_edge + gap - desired_min_x)
        moved = [
            stroke for stroke in line
            if stroke.id in anchor_set or stroke.bbox.center[0] >= anchor.min_x - epsilon
        ]
    else:
        right = [stroke for stroke in others if stroke.bbox.min_x >= anchor.max_x - epsilon]
        if not right:
            return anchor, [], 0.0
        nearest_edge = min(stroke.bbox.min_x for stroke in right)
        desired_max_x = anchor.max_x + gap + text_width
        shift = max(0.0, desired_max_x + gap - nearest_edge)
        moved = [
            stroke for stroke in line
            if stroke.id not in anchor_set and stroke.bbox.min_x >= nearest_edge - epsilon
        ]

    if shift <= epsilon or not moved:
        return anchor, [], 0.0
    blocked = [stroke.id for stroke in moved if stroke.id not in movable]
    if blocked:
        raise ValueError(
            "insertion needs to move locked or non-user ink: " + ", ".join(blocked)
        )
    if shift > _MAX_INSERT_REFLOW:
        raise ValueError(
            f"insertion needs a {shift:g}-unit reflow, above the "
            f"{_MAX_INSERT_REFLOW:g}-unit safety limit"
        )
    if max(stroke.bbox.max_x for stroke in moved) + shift > canvas.page.width:
        raise ValueError("insertion reflow would move ink beyond the page")

    moved_ids = [stroke.id for stroke in moved]
    if position == "before":
        anchor = _translated_box(anchor, shift, 0.0)
    return anchor, moved_ids, shift


@tool(
    "insert_text",
    "Write text placed relative to existing ink named by stroke id — sized "
    "to match that ink, region computed for you, and nearby same-line ink "
    "shifted minimally when space is tight. The precise way to insert "
    "a missing character, word, or short correction next to what the user "
    "wrote (e.g. a quote mark right before a word). Prefer this over "
    "write_text when the placement is relative to existing ink.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "stroke_ids": {**_IDS_SCHEMA,
                           "description": "Anchor strokes the text is placed relative to"},
            "position": {"type": "string", "enum": list(_INSERT_POSITIONS)},
            "color": {"type": "string", "description": "Hex color, e.g. #1d4ed8"},
            "size": {
                "type": "number",
                "exclusiveMinimum": 0,
                "description": "Cap height in page units; omit to match the anchor ink",
            },
        },
        "required": ["text", "stroke_ids", "position"],
    },
)
def insert_text(
    canvas: Canvas,
    text: str,
    stroke_ids: Sequence[str],
    position: str,
    color: Optional[str] = None,
    size: Optional[float] = None,
) -> dict[str, Any]:
    from neeh.ink.textink import MIN_SIZE, layout_text, measure_text

    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    if position not in _INSERT_POSITIONS:
        raise ValueError(f"position must be one of {_INSERT_POSITIONS}")
    validated_ids = _stroke_ids(stroke_ids)
    if not validated_ids:
        raise ValueError("stroke_ids must name at least one stroke")
    original_box = _anchor_bbox(canvas, validated_ids)
    box = original_box
    if size is not None:
        size = _finite_number(size, "size")
        if size <= 0:
            raise ValueError("size must be positive")
    else:
        # Horizontal punctuation (for example a hyphen being replaced by an
        # underscore) has a zero-height bbox. Use its width as the font-scale
        # hint in that case, capped so long rules do not create giant text.
        extent = box.height if box.height >= MIN_SIZE else min(box.width, 48.0)
        size = max(extent * 0.9, MIN_SIZE)
    text_style = "handwritten"
    w, h = measure_text(text, size, style=text_style)
    w += 0.5  # epsilon so layout_text's wrap check never triggers
    gap = max(size * 0.25, 2.0)
    page = canvas.page
    box, moved_ids, shift = _horizontal_insert_reflow(
        canvas, validated_ids, box, position, w, gap, size
    )
    if position == "before":
        region = BoundingBox(box.min_x - gap - w, box.min_y,
                             box.min_x - gap, box.min_y + h)
    elif position == "after":
        region = BoundingBox(box.max_x + gap, box.min_y,
                             box.max_x + gap + w, box.min_y + h)
    elif position == "above":
        region = BoundingBox(box.min_x, box.min_y - gap - h,
                             box.min_x + w, box.min_y - gap)
    else:  # below
        region = BoundingBox(box.min_x, box.max_y + gap,
                             box.min_x + w, box.max_y + gap + h)
    if (region.min_x < 0 or region.min_y < 0
            or region.max_x > page.width or region.max_y > page.height):
        raise ValueError(
            f"no room {position!r} the anchor at size {size:g}; "
            f"try another position or a smaller size"
        )
    polylines, used_size = layout_text(text, region, size=size, style=text_style)
    style = StrokeStyle(color=color or "#1a1a1a", width=max(used_size / 12.0, 0.8))
    strokes, moved_ids = canvas.move_and_add_strokes(
        polylines,
        move_stroke_ids=moved_ids,
        dx=shift,
        dy=0.0,
        style=style,
        author=Author.AGENT,
        label="insert_text",
    )
    return {
        "stroke_ids": [s.id for s in strokes],
        "size": used_size,
        "region": region.to_list(),
        "anchor_bbox": box.to_list(),
        "original_anchor_bbox": original_box.to_list(),
        "reflow": {"moved_stroke_ids": moved_ids, "dx": shift, "dy": 0.0},
        "style": text_style,
    }


@tool(
    "undo",
    "Undo the most recent edit on this canvas.",
    {"type": "object", "properties": {}, "required": []},
)
def undo(canvas: Canvas) -> dict[str, Any]:
    return {"undone": canvas.undo()}


@tool(
    "redo",
    "Redo the most recently undone edit on this canvas.",
    {"type": "object", "properties": {}, "required": []},
)
def redo(canvas: Canvas) -> dict[str, Any]:
    return {"redone": canvas.redo()}
