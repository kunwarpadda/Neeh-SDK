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
from neeh.ink import Author, BoundingBox, StrokeStyle
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
    "Style 'print' is a clean single-stroke font; 'user_font' is reserved.",
    {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "region": _REGION_SCHEMA,
            # Do not advertise reserved implementations to agents.  The
            # function still rejects user_font explicitly for callers that
            # send it, but generated tool calls must only choose a style that
            # can actually be executed.
            "style": {"type": "string", "enum": ["print"]},
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
    style: str = "print",
    color: Optional[str] = None,
    size: Optional[float] = None,
) -> dict[str, Any]:
    if style not in ("print", "user_font"):
        raise ValueError("style must be 'print' or 'user_font'")
    if style == "user_font":
        raise NotImplementedError(
            "the user_font style ships with the handwriting extraction from the Neeh app "
            "(NEEH_SDK_PLAN §3); use style='print' for now"
        )
    from neeh.ink.textink import layout_text

    if not isinstance(text, str):
        raise ValueError("text must be a string")
    if size is not None:
        size = _finite_number(size, "size")
        if size <= 0:
            raise ValueError("size must be positive")
    box = _region(region)
    polylines, used_size = layout_text(text, box, size=size)
    stroke_style = StrokeStyle(color=color or "#1a1a1a", width=max(used_size / 12.0, 0.8))
    strokes = canvas.add_strokes(polylines, style=stroke_style, author=Author.AGENT)
    return {
        "stroke_ids": [s.id for s in strokes],
        "size": used_size,
        "region": box.to_list(),
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
