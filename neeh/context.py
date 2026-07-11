"""Reference builder for the model-facing Ink Context Format.

Ink Context Format (ICF) snapshots are deliberately separate from document
persistence.  They combine a descriptor for an externally transported raster
with compact, attributable vector ink and optional recognizer semantics.  No
image bytes are embedded in the returned mapping.
"""
from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Optional, Union

from neeh.canvas.canvas import Canvas
from neeh.document.document import Document
from neeh.document.layer import Layer
from neeh.document.page import Page
from neeh.ink.geometry import BoundingBox, Point
from neeh.ink.stroke import Author, Stroke
from neeh.protocol import INK_CONTEXT_V1_DRAFT_VERSION, INK_CONTEXT_VERSION

DEFAULT_MAX_STROKES = 80
DEFAULT_MAX_POINTS_PER_STROKE = 12
DEFAULT_GRID_LONG_EDGE = 256  # v1 draft: grid resolution across the longer page edge
DEFAULT_RESAMPLE_GRID_STEP = 4.0  # v1 draft: arc-length step between path points, grid units
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\Z")

PageSelector = Union[int, str, Page]
ContextSource = Union[Document, Page, Canvas]
RegionLike = Union[BoundingBox, Sequence[float]]


class InkContextError(ValueError):
    """Raised when an ICF snapshot cannot be built without ambiguity."""


def _non_empty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InkContextError(f"{field} must be a non-empty string")
    return value


def _finite_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InkContextError(f"{field} must be a finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise InkContextError(f"{field} must be a finite number") from exc
    if not math.isfinite(result):
        raise InkContextError(f"{field} must be a finite number")
    return result


def _integer(value: Any, field: str, *, minimum: Optional[int] = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InkContextError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise InkContextError(f"{field} must be at least {minimum}, got {value}")
    return value


def _json_float(value: float) -> float:
    """Preserve validated precision while normalizing negative zero."""

    return 0.0 if value == 0 else value


def _box(value: RegionLike, field: str) -> BoundingBox:
    if isinstance(value, BoundingBox):
        values: Sequence[Any] = value.to_list()
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = value
    else:
        raise InkContextError(
            f"{field} must be a BoundingBox or [min_x, min_y, max_x, max_y]"
        )
    if len(values) != 4:
        raise InkContextError(f"{field} must contain exactly four coordinates")
    coordinates = [_finite_number(item, f"{field}[{index}]") for index, item in enumerate(values)]
    try:
        return BoundingBox(*coordinates)
    except ValueError as exc:
        raise InkContextError(f"{field} is inverted: {list(values)!r}") from exc


def _box_list(value: BoundingBox) -> list[float]:
    return [_json_float(float(number)) for number in value.to_list()]


def _strings(value: Any, field: str, *, unique: bool) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(value, Iterable):
        raise InkContextError(f"{field} must be an iterable of non-empty strings")
    result = tuple(_non_empty_string(item, f"{field}[{index}]") for index, item in enumerate(value))
    if unique and len(set(result)) != len(result):
        raise InkContextError(f"{field} must not contain duplicate ids")
    return result


@dataclass(frozen=True)
class SemanticItem:
    """A validated semantic claim anchored to page-space ink.

    An item must have a stable id and kind, and must be anchored by a region,
    one or more stroke ids, or both.  Optional text, confidence, and source
    fields cover the v0 recognizer-result shape without admitting arbitrary
    non-serializable payloads.
    """

    id: str
    kind: str
    region: Optional[RegionLike] = None
    stroke_ids: Sequence[str] = ()
    text: Optional[str] = None
    confidence: Optional[float] = None
    source: Optional[str] = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _non_empty_string(self.id, "semantic id"))
        object.__setattr__(self, "kind", _non_empty_string(self.kind, "semantic kind"))

        normalized_region = None if self.region is None else _box(self.region, "semantic region")
        normalized_ids = _strings(self.stroke_ids, "semantic stroke_ids", unique=True)
        if normalized_region is None and not normalized_ids:
            raise InkContextError("a semantic item needs a region, stroke_ids, or both")
        object.__setattr__(self, "region", normalized_region)
        object.__setattr__(self, "stroke_ids", normalized_ids)

        if self.text is not None:
            object.__setattr__(self, "text", _non_empty_string(self.text, "semantic text"))
        if self.confidence is not None:
            confidence = _finite_number(self.confidence, "semantic confidence")
            if not 0.0 <= confidence <= 1.0:
                raise InkContextError(
                    f"semantic confidence must be between 0 and 1, got {self.confidence}"
                )
            object.__setattr__(self, "confidence", confidence)
        if self.source is not None:
            object.__setattr__(self, "source", _non_empty_string(self.source, "semantic source"))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "SemanticItem":
        """Validate and normalize a mapping into a :class:`SemanticItem`."""

        if not isinstance(value, Mapping):
            raise InkContextError("semantic item must be a mapping")
        supported = {"id", "kind", "region", "stroke_ids", "text", "confidence", "source"}
        unknown = sorted(set(value) - supported, key=str)
        if unknown:
            raise InkContextError(
                "semantic item has unsupported field(s): " + ", ".join(str(key) for key in unknown)
            )
        missing = [field for field in ("id", "kind") if field not in value]
        if missing:
            raise InkContextError(
                "semantic item is missing required field(s): " + ", ".join(missing)
            )
        return cls(
            id=value["id"],
            kind=value["kind"],
            region=value.get("region"),
            stroke_ids=value.get("stroke_ids", ()),
            text=value.get("text"),
            confidence=value.get("confidence"),
            source=value.get("source"),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the canonical JSON-compatible v0 item shape."""

        result: dict[str, Any] = {"id": self.id, "kind": self.kind}
        if self.region is not None:
            result["region"] = _box_list(self.region)
        if self.stroke_ids:
            result["stroke_ids"] = list(self.stroke_ids)
        if self.text is not None:
            result["text"] = self.text
        if self.confidence is not None:
            result["confidence"] = self.confidence
        if self.source is not None:
            result["source"] = self.source
        return result


def _resolve_page(source: ContextSource, selector: Optional[PageSelector]) -> Page:
    if isinstance(source, Page):
        if selector is not None and selector is not source and selector != source.id:
            raise InkContextError("page selector cannot select a different page from a Page source")
        return source

    if isinstance(source, Canvas):
        if selector is None:
            if not source.document.pages:
                raise InkContextError("source canvas document has no pages")
            return source.page
        document = source.document
    elif isinstance(source, Document):
        document = source
    else:
        raise InkContextError("source must be a Document, Page, or Canvas")

    if isinstance(selector, Page):
        for candidate in document.pages:
            if candidate is selector or candidate.id == selector.id:
                return candidate
        raise InkContextError(f"page {selector.id!r} does not belong to the source document")

    if selector is None:
        if not document.pages:
            raise InkContextError("source document has no pages")
        return document.pages[0]

    if isinstance(selector, bool) or not isinstance(selector, (int, str)):
        raise InkContextError("page selector must be a page index, page id, or Page")
    selected = document.page(selector)
    if selected is None:
        raise InkContextError(f"page selector {selector!r} did not match a page")
    return selected


def _point_list(point: Point, field: str) -> list[Union[float, int]]:
    x = _finite_number(point.x, f"{field}.x")
    y = _finite_number(point.y, f"{field}.y")
    t_ms = _integer(point.t_ms, f"{field}.t_ms", minimum=0)
    pressure = _finite_number(point.pressure, f"{field}.pressure")
    tilt_x = _finite_number(point.tilt_x, f"{field}.tilt_x")
    tilt_y = _finite_number(point.tilt_y, f"{field}.tilt_y")
    if not 0.0 <= pressure <= 1.0:
        raise InkContextError(f"{field}.pressure must be between 0 and 1, got {point.pressure}")
    if not -90.0 <= tilt_x <= 90.0:
        raise InkContextError(f"{field}.tilt_x must be between -90 and 90, got {point.tilt_x}")
    if not -90.0 <= tilt_y <= 90.0:
        raise InkContextError(f"{field}.tilt_y must be between -90 and 90, got {point.tilt_y}")
    return [
        _json_float(x),
        _json_float(y),
        t_ms,
        _json_float(pressure),
        _json_float(tilt_x),
        _json_float(tilt_y),
    ]


def _validated_points(stroke: Stroke) -> list[list[Union[float, int]]]:
    if not stroke.points:
        raise InkContextError(f"stroke {stroke.id!r} must contain at least one point")
    points: list[list[Union[float, int]]] = []
    previous_t_ms: Optional[int] = None
    for index, point in enumerate(stroke.points):
        serialized = _point_list(point, f"stroke {stroke.id!r} point[{index}]")
        t_ms = serialized[2]
        assert isinstance(t_ms, int)  # established by _point_list
        if previous_t_ms is not None and t_ms < previous_t_ms:
            raise InkContextError(
                f"stroke {stroke.id!r} point[{index}].t_ms must be nondecreasing"
            )
        previous_t_ms = t_ms
        points.append(serialized)
    return points


def _sample_points(
    points: list[list[Union[float, int]]], limit: Optional[int]
) -> list[list[Union[float, int]]]:
    if limit is None or len(points) <= limit:
        indexes = range(len(points))
    else:
        # Equal-distance index sampling matches the Phase 0 spike.  The first
        # and last samples are exact endpoints; intermediate choices depend
        # only on point count and limit, so repeated builds are identical.
        indexes = [round(index * (len(points) - 1) / (limit - 1)) for index in range(limit)]
    return [points[index] for index in indexes]


def _stroke_record(layer: Layer, stroke: Stroke, point_limit: Optional[int]) -> dict[str, Any]:
    stroke_id = _non_empty_string(stroke.id, "stroke id")
    layer_id = _non_empty_string(layer.id, f"stroke {stroke_id!r} layer id")
    layer_name = _non_empty_string(layer.name, f"stroke {stroke_id!r} layer name")
    created_at_ms = _integer(stroke.created_at_ms, f"stroke {stroke_id!r} created_at_ms", minimum=0)
    points = _validated_points(stroke)
    duration_ms = _integer(stroke.duration_ms, f"stroke {stroke_id!r} duration_ms")
    if duration_ms < 0:
        raise InkContextError(f"stroke {stroke_id!r} duration_ms must not be negative")

    author = stroke.author.value if isinstance(stroke.author, Author) else stroke.author
    if author not in (Author.USER.value, Author.AGENT.value):
        raise InkContextError(f"stroke {stroke_id!r} author must be 'user' or 'agent'")

    style = stroke.style
    style_width = _finite_number(style.width, f"stroke {stroke_id!r} style.width")
    style_opacity = _finite_number(style.opacity, f"stroke {stroke_id!r} style.opacity")
    style_color = _non_empty_string(style.color, f"stroke {stroke_id!r} style.color")
    if not _HEX_COLOR.fullmatch(style_color):
        raise InkContextError(
            f"stroke {stroke_id!r} style.color must be a #rgb or #rrggbb hex color"
        )
    if style_width <= 0:
        raise InkContextError(f"stroke {stroke_id!r} style.width must be positive")
    if not 0.0 < style_opacity <= 1.0:
        raise InkContextError(f"stroke {stroke_id!r} style.opacity must be in (0, 1]")
    brush = style.brush.value if hasattr(style.brush, "value") else style.brush
    brush = _non_empty_string(brush, f"stroke {stroke_id!r} style.brush")
    if brush not in ("pen", "marker", "highlighter"):
        raise InkContextError(
            f"stroke {stroke_id!r} style.brush must be pen, marker, or highlighter"
        )

    return {
        "id": stroke_id,
        "layer_id": layer_id,
        "layer_name": layer_name,
        "author": author,
        "created_at_ms": created_at_ms,
        "duration_ms": duration_ms,
        "bbox": _box_list(stroke.bbox),
        "style": {
            "color": style_color,
            "width": _json_float(style_width),
            "opacity": _json_float(style_opacity),
            "brush": brush,
        },
        "point_count": len(stroke.points),
        "points_sample": _sample_points(points, point_limit),
    }


def _semantic_items(
    values: Optional[Iterable[Union[SemanticItem, Mapping[str, Any]]]],
    emitted_stroke_ids: set[str],
) -> list[dict[str, Any]]:
    if values is None:
        return []
    if isinstance(values, (str, bytes, bytearray, Mapping)) or not isinstance(values, Iterable):
        raise InkContextError("semantics must be an iterable of SemanticItem objects or mappings")

    result: list[dict[str, Any]] = []
    semantic_ids: set[str] = set()
    for index, value in enumerate(values):
        try:
            if isinstance(value, SemanticItem):
                item = value
            elif isinstance(value, Mapping):
                item = SemanticItem.from_mapping(value)
            else:
                raise InkContextError("item must be a SemanticItem or mapping")
        except InkContextError as exc:
            raise InkContextError(f"semantics[{index}]: {exc}") from exc

        if item.id in semantic_ids:
            raise InkContextError(f"semantics[{index}]: duplicate semantic id {item.id!r}")
        semantic_ids.add(item.id)
        missing = [
            stroke_id for stroke_id in item.stroke_ids if stroke_id not in emitted_stroke_ids
        ]
        if missing:
            raise InkContextError(
                f"semantics[{index}]: stroke_ids reference stroke(s) missing from vector.strokes: "
                + ", ".join(repr(stroke_id) for stroke_id in missing)
            )
        result.append(item.to_dict())
    return result


def build_ink_context(
    source: ContextSource,
    *,
    page: Optional[PageSelector] = None,
    region: Optional[RegionLike] = None,
    stroke_ids: Optional[Iterable[str]] = None,
    author: Optional[Union[Author, str]] = None,
    since_ms: Optional[int] = None,
    visible_only: bool = True,
    max_strokes: Optional[int] = DEFAULT_MAX_STROKES,
    max_points_per_stroke: Optional[int] = DEFAULT_MAX_POINTS_PER_STROKE,
    semantics: Optional[Iterable[Union[SemanticItem, Mapping[str, Any]]]] = None,
) -> dict[str, Any]:
    """Build a deterministic, JSON-compatible ``ink-context/v0`` snapshot.

    ``source`` may be a document, a page, or a canvas.  Raster bytes remain an
    external transport concern; the ``raster`` member only describes the PNG
    input block that should accompany this mapping.

    Matching strokes retain document/layer order.  When ``max_strokes`` is
    exceeded, the newest tail is retained in that same order, matching the
    established Phase 0 prompt behavior.  Point compaction is deterministic
    and always retains both endpoints.
    """

    selected_page = _resolve_page(source, page)
    selected_region = None if region is None else _box(region, "region")

    if not isinstance(visible_only, bool):
        raise InkContextError("visible_only must be a boolean")
    if max_strokes is not None:
        max_strokes = _integer(max_strokes, "max_strokes", minimum=0)
    if max_points_per_stroke is not None:
        max_points_per_stroke = _integer(
            max_points_per_stroke, "max_points_per_stroke", minimum=2
        )
    if since_ms is not None:
        since_ms = _integer(since_ms, "since_ms", minimum=0)

    id_filter: Optional[set[str]] = None
    if stroke_ids is not None:
        id_filter = set(_strings(stroke_ids, "stroke_ids", unique=False))

    author_filter: Optional[str] = None
    if author is not None:
        author_filter = author.value if isinstance(author, Author) else author
        if author_filter not in (Author.USER.value, Author.AGENT.value):
            raise InkContextError("author must be 'user', 'agent', or None")

    page_id = _non_empty_string(selected_page.id, "page.id")
    page_width = _finite_number(selected_page.width, "page.width")
    page_height = _finite_number(selected_page.height, "page.height")
    if page_width <= 0 or page_height <= 0:
        raise InkContextError("page.width and page.height must be positive")
    page_background = _non_empty_string(selected_page.background, "page.background")
    if not _HEX_COLOR.fullmatch(page_background):
        raise InkContextError("page.background must be a #rgb or #rrggbb hex color")

    matches: list[tuple[Layer, Stroke]] = []
    for layer in selected_page.layers:
        if visible_only and not layer.visible:
            continue
        for stroke in layer.strokes:
            if id_filter is not None and stroke.id not in id_filter:
                continue
            if selected_region is not None and not selected_region.intersects(stroke.bbox):
                continue
            stroke_author = (
                stroke.author.value if isinstance(stroke.author, Author) else stroke.author
            )
            if author_filter is not None and stroke_author != author_filter:
                continue
            if since_ms is not None and stroke.created_at_ms < since_ms:
                continue
            matches.append((layer, stroke))

    stroke_count = len(matches)
    if max_strokes is None or stroke_count <= max_strokes:
        included = matches
        omitted_count = 0
    elif max_strokes == 0:
        included = []
        omitted_count = stroke_count
    else:
        omitted_count = stroke_count - max_strokes
        included = matches[omitted_count:]

    region_list = None if selected_region is None else _box_list(selected_region)
    records = [
        _stroke_record(layer, stroke, max_points_per_stroke) for layer, stroke in included
    ]
    emitted_stroke_ids = {record["id"] for record in records}
    if len(emitted_stroke_ids) != len(records):
        raise InkContextError("vector.strokes contains duplicate stroke ids")

    vector = {
        "page_id": page_id,
        "width": page_width,
        "height": page_height,
        "region": region_list,
        "stroke_count": stroke_count,
        "included_stroke_count": len(included),
        "omitted_older_stroke_count": omitted_count,
        "truncated": omitted_count > 0,
        "points_policy": (
            "all points included"
            if max_points_per_stroke is None
            else f"sampled up to {max_points_per_stroke} points per stroke"
        ),
        "strokes": records,
    }
    return {
        "schema": INK_CONTEXT_VERSION,
        "page": {
            "id": page_id,
            "width": page_width,
            "height": page_height,
            "background": page_background,
        },
        "raster": {
            "format": "png",
            "transport": "attached_image",
            "coordinate_space": "page",
            "region": region_list,
        },
        "vector": vector,
        "semantics": _semantic_items(semantics, emitted_stroke_ids),
    }


# -- ink-context/v1-draft (research/icf-v1-draft.md) --------------------------
#
# The v1 draft replaces JSON point arrays with grid-quantized SVG paths — the
# encoding that won the M1/E7 evaluation (harness arm E7v/0.1.0). The builder
# below must stay byte-identical to that arm's `svg` output for the same page;
# a cross-check test enforces it.


def _resample_polyline(
    points: list[tuple[float, float]], step: float
) -> list[tuple[float, float]]:
    """Arc-length resampling; always keeps first and last points."""
    if len(points) < 2 or step <= 0:
        return list(points)
    out = [points[0]]
    carried = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        segment = math.hypot(x1 - x0, y1 - y0)
        if segment == 0:
            continue
        position = carried
        while position + step <= segment:
            position += step
            t = position / segment
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        carried = position - segment  # negative remainder toward the next segment
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def _select_strokes_v1(
    page: Page,
    region: Optional[BoundingBox],
    visible_only: bool,
    max_strokes: Optional[int],
) -> tuple[list[Stroke], int]:
    """Eligible strokes in drawn (layer, then stroke) order, newest-tail capped."""
    matches: list[Stroke] = []
    for layer in page.layers:
        if visible_only and not layer.visible:
            continue
        for stroke in layer.strokes:
            if region is not None and not region.intersects(stroke.bbox):
                continue
            matches.append(stroke)
    stroke_count = len(matches)
    if max_strokes is not None and stroke_count > max_strokes:
        matches = matches[stroke_count - max_strokes:]
    return matches, stroke_count


def _rdp_polyline(
    points: list[tuple[float, float]], eps: float
) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker: drop points within `eps` of the chord.

    Simplification measurably *improves* model comprehension of the paths in
    addition to shrinking them (research/results/real-ink-findings.md, E7vS).
    """
    if len(points) < 3:
        return list(points)
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy)
    dmax, idx = 0.0, 0
    for i in range(1, len(points) - 1):
        px, py = points[i]
        if norm:
            d = abs(dy * (px - x0) - dx * (py - y0)) / norm
        else:
            d = math.hypot(px - x0, py - y0)
        if d > dmax:
            dmax, idx = d, i
    if dmax <= eps:
        return [points[0], points[-1]]
    left = _rdp_polyline(points[: idx + 1], eps)
    return left[:-1] + _rdp_polyline(points[idx:], eps)


def _paths_svg(
    page: Page,
    strokes: list[Stroke],
    grid_long_edge: int,
    resample_grid_step: float,
    simplify_eps_grid: Optional[float] = None,
) -> tuple[str, int, int]:
    scale = grid_long_edge / max(page.width, page.height)
    grid_w = round(page.width * scale)
    grid_h = round(page.height * scale)
    step_page = resample_grid_step / scale
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {grid_w} {grid_h}">']
    for stroke in strokes:
        stroke_id = _non_empty_string(stroke.id, "stroke id")
        if not stroke.points:
            raise InkContextError(f"stroke {stroke_id!r} must contain at least one point")
        resampled = _resample_polyline(
            [(p.x, p.y) for p in stroke.points], step_page
        )
        if simplify_eps_grid is not None:
            resampled = _rdp_polyline(resampled, simplify_eps_grid / scale)
        gx = [round(x * scale) for x, _ in resampled]
        gy = [round(y * scale) for _, y in resampled]
        d = f"M{gx[0]} {gy[0]}"
        if len(gx) > 1:
            d += "l" + " ".join(
                f"{gx[i] - gx[i - 1]} {gy[i] - gy[i - 1]}" for i in range(1, len(gx))
            )
        parts.append(f'<path id="{stroke_id}" d="{d}"/>')
    parts.append("</svg>")
    return "\n".join(parts), grid_w, grid_h


def build_ink_paths(
    source: ContextSource,
    *,
    page: Optional[PageSelector] = None,
    region: Optional[RegionLike] = None,
    visible_only: bool = True,
    max_strokes: Optional[int] = None,
    grid_long_edge: int = DEFAULT_GRID_LONG_EDGE,
    resample_grid_step: float = DEFAULT_RESAMPLE_GRID_STEP,
) -> str:
    """Return the bare compact-SVG ink block of the ``ink-context/v1-draft``.

    One ``<path id=…>`` per stroke in drawn order; coordinates on an integer
    grid whose long edge is ``grid_long_edge``. This is the model-facing text
    without the JSON envelope — use :func:`build_ink_context_v1` for the full
    payload.
    """
    selected_page = _resolve_page(source, page)
    selected_region = None if region is None else _box(region, "region")
    if not isinstance(visible_only, bool):
        raise InkContextError("visible_only must be a boolean")
    if max_strokes is not None:
        max_strokes = _integer(max_strokes, "max_strokes", minimum=0)
    grid_long_edge = _integer(grid_long_edge, "grid_long_edge", minimum=16)
    resample_grid_step = _finite_number(resample_grid_step, "resample_grid_step")
    if resample_grid_step <= 0:
        raise InkContextError("resample_grid_step must be positive")
    strokes, _ = _select_strokes_v1(
        selected_page, selected_region, visible_only, max_strokes
    )
    svg, _, _ = _paths_svg(selected_page, strokes, grid_long_edge, resample_grid_step)
    return svg


def build_ink_context_v1(
    source: ContextSource,
    *,
    page: Optional[PageSelector] = None,
    region: Optional[RegionLike] = None,
    visible_only: bool = True,
    max_strokes: Optional[int] = None,
    grid_long_edge: int = DEFAULT_GRID_LONG_EDGE,
    resample_grid_step: float = DEFAULT_RESAMPLE_GRID_STEP,
    raster: str = "none",
    stroke_bboxes: bool = False,
    simplify_eps_grid: Optional[float] = None,
    char_budget: Optional[int] = None,
    semantics: Optional[Iterable[Union[SemanticItem, Mapping[str, Any]]]] = None,
) -> dict[str, Any]:
    """Build a deterministic ``ink-context/v1-draft`` snapshot.

    Geometry rides as grid-quantized SVG paths (``ink.svg``) instead of v0's
    JSON point arrays; strokes appear in drawn order, which carries the
    temporal signal. ``raster`` is ``"none"`` (structure tier, default) or
    ``"attached_image"`` (perception tier — the transport must then attach one
    page PNG beside the JSON, exactly as in v0).

    ``stroke_bboxes`` adds ``ink.bboxes`` (stroke id → page-unit box) — the
    segmentation cue that recovers full-ICF reading accuracy at compact cost
    (research/results/real-ink-findings.md). Bboxes are page units, never grid
    units: coordinates a consumer might echo into tool calls must not need a
    frame conversion.

    ``simplify_eps_grid`` runs RDP simplification (tolerance in grid units)
    on each path — measured to *improve* structure-task comprehension while
    cutting characters (E7vS result). ``char_budget`` enables rate control:
    the builder walks a fidelity ladder (finer grids first) and returns the
    highest-fidelity payload whose serialized JSON fits the budget; the
    chosen operating point is recorded in ``ink.rate_point``. Explicit
    ``grid_long_edge``/``simplify_eps_grid`` are ignored in budget mode.
    """
    if raster not in ("none", "attached_image"):
        raise InkContextError("raster must be 'none' or 'attached_image'")
    if char_budget is not None:
        char_budget = _integer(char_budget, "char_budget", minimum=1)
        common = dict(
            page=page, region=region, visible_only=visible_only,
            max_strokes=max_strokes, resample_grid_step=resample_grid_step,
            raster=raster, stroke_bboxes=stroke_bboxes, semantics=semantics,
        )
        # Fidelity ladder, best first (grid, simplify_eps_grid); measured
        # rate-distortion points — see results/embedded-coding-exhibit.md.
        ladder = [(512, None), (256, None), (256, 1.0), (128, 1.0), (128, 2.0)]
        chosen = None
        for grid, eps in ladder:
            candidate = build_ink_context_v1(
                source, grid_long_edge=grid, simplify_eps_grid=eps, **common
            )
            candidate["ink"]["rate_point"] = {
                "grid_long_edge": grid, "simplify_eps_grid": eps,
                "char_budget": char_budget,
            }
            chosen = candidate
            if len(json.dumps(candidate, separators=(",", ":"))) <= char_budget:
                return candidate
        return chosen  # budget unreachable: coarsest point, honestly labeled

    selected_page = _resolve_page(source, page)
    selected_region = None if region is None else _box(region, "region")
    if not isinstance(visible_only, bool):
        raise InkContextError("visible_only must be a boolean")
    if max_strokes is not None:
        max_strokes = _integer(max_strokes, "max_strokes", minimum=0)
    grid_long_edge = _integer(grid_long_edge, "grid_long_edge", minimum=16)
    resample_grid_step = _finite_number(resample_grid_step, "resample_grid_step")
    if resample_grid_step <= 0:
        raise InkContextError("resample_grid_step must be positive")

    page_id = _non_empty_string(selected_page.id, "page.id")
    page_width = _finite_number(selected_page.width, "page.width")
    page_height = _finite_number(selected_page.height, "page.height")
    if page_width <= 0 or page_height <= 0:
        raise InkContextError("page.width and page.height must be positive")
    page_background = _non_empty_string(selected_page.background, "page.background")
    if not _HEX_COLOR.fullmatch(page_background):
        raise InkContextError("page.background must be a #rgb or #rrggbb hex color")

    included, stroke_count = _select_strokes_v1(
        selected_page, selected_region, visible_only, max_strokes
    )
    if simplify_eps_grid is not None:
        simplify_eps_grid = _finite_number(simplify_eps_grid, "simplify_eps_grid")
        if simplify_eps_grid <= 0:
            raise InkContextError("simplify_eps_grid must be positive")
    svg, grid_w, grid_h = _paths_svg(
        selected_page, included, grid_long_edge, resample_grid_step,
        simplify_eps_grid,
    )
    included_ids = {stroke.id for stroke in included}
    if len(included_ids) != len(included):
        raise InkContextError("ink.svg contains duplicate stroke ids")

    region_list = None if selected_region is None else _box_list(selected_region)
    omitted = stroke_count - len(included)
    ink: dict[str, Any] = {
        "encoding": "svg-paths/grid",
        "grid": [grid_w, grid_h],
        "drawn_order": True,
        "region": region_list,
        "stroke_count": stroke_count,
        "included_stroke_count": len(included),
        "omitted_older_stroke_count": omitted,
        "truncated": omitted > 0,
        "svg": svg,
    }
    if stroke_bboxes:
        ink["bboxes"] = {stroke.id: _box_list(stroke.bbox) for stroke in included}
    return {
        "schema": INK_CONTEXT_V1_DRAFT_VERSION,
        "page": {
            "id": page_id,
            "width": page_width,
            "height": page_height,
            "background": page_background,
        },
        "raster": {
            "format": "png",
            "transport": raster,
            "coordinate_space": "page",
            "region": region_list,
        },
        "ink": ink,
        "semantics": _semantic_items(semantics, included_ids),
    }


@dataclass(frozen=True)
class ParsedInkPath:
    """One decoded ``svg-paths/grid`` stroke: grid cells, optionally page units."""

    id: str
    grid_points: tuple[tuple[int, int], ...]
    page_points: Optional[tuple[tuple[float, float], ...]] = None


_VIEWBOX = re.compile(r'viewBox="0 0 (\d+) (\d+)"')
_PATH = re.compile(r'<path id="([^"]+)" d="([^"]*)"\s*/>')


def parse_ink_paths(
    svg: str,
    *,
    page_width: Optional[float] = None,
    page_height: Optional[float] = None,
) -> tuple[tuple[int, int], list[ParsedInkPath]]:
    """Decode an ``ink.svg`` block back into per-stroke polylines.

    Returns ``((grid_w, grid_h), paths)`` in listing (drawn) order. When both
    page dimensions are given, each path also carries ``page_points`` mapped
    back to page units — the consumer-side inverse of :func:`build_ink_paths`
    (lossy: quantization is not undone).
    """
    box = _VIEWBOX.search(svg)
    if not box:
        raise InkContextError("ink svg has no integer viewBox")
    grid_w, grid_h = int(box.group(1)), int(box.group(2))
    if grid_w < 1 or grid_h < 1:
        raise InkContextError("ink svg viewBox must be at least 1x1")

    scale = None
    if page_width is not None or page_height is not None:
        if page_width is None or page_height is None:
            raise InkContextError("page_width and page_height must be given together")
        page_width = _finite_number(page_width, "page_width")
        page_height = _finite_number(page_height, "page_height")
        if page_width <= 0 or page_height <= 0:
            raise InkContextError("page dimensions must be positive")
        scale = max(page_width, page_height) / max(grid_w, grid_h)

    paths: list[ParsedInkPath] = []
    seen: set[str] = set()
    for stroke_id, d in _PATH.findall(svg):
        if stroke_id in seen:
            raise InkContextError(f"ink svg repeats stroke id {stroke_id!r}")
        seen.add(stroke_id)
        head, _, rest = d.partition("l")
        if not head.startswith("M"):
            raise InkContextError(f"path {stroke_id!r} must start with an absolute M")
        try:
            x, y = (int(v) for v in head[1:].split())
            offsets = [int(v) for v in rest.split()] if rest else []
        except ValueError as exc:
            raise InkContextError(f"path {stroke_id!r} has non-integer coordinates") from exc
        if len(offsets) % 2:
            raise InkContextError(f"path {stroke_id!r} has an odd offset count")
        points = [(x, y)]
        for i in range(0, len(offsets), 2):
            x += offsets[i]
            y += offsets[i + 1]
            points.append((x, y))
        page_points = None
        if scale is not None:
            page_points = tuple((px * scale, py * scale) for px, py in points)
        paths.append(ParsedInkPath(stroke_id, tuple(points), page_points))
    return (grid_w, grid_h), paths


__all__ = [
    "DEFAULT_GRID_LONG_EDGE",
    "DEFAULT_MAX_POINTS_PER_STROKE",
    "DEFAULT_MAX_STROKES",
    "DEFAULT_RESAMPLE_GRID_STEP",
    "InkContextError",
    "ParsedInkPath",
    "SemanticItem",
    "build_ink_context",
    "build_ink_context_v1",
    "build_ink_paths",
    "parse_ink_paths",
]
