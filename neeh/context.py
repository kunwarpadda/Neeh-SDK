"""Reference builder for the model-facing Ink Context Format.

Ink Context Format (ICF) snapshots are deliberately separate from document
persistence.  They combine a descriptor for an externally transported raster
with compact, attributable vector ink and optional recognizer semantics.  No
image bytes are embedded in the returned mapping.
"""
from __future__ import annotations

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
from neeh.protocol import INK_CONTEXT_VERSION

DEFAULT_MAX_STROKES = 80
DEFAULT_MAX_POINTS_PER_STROKE = 12
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


__all__ = [
    "DEFAULT_MAX_POINTS_PER_STROKE",
    "DEFAULT_MAX_STROKES",
    "InkContextError",
    "SemanticItem",
    "build_ink_context",
]
