"""Pages: a fixed-size ink surface holding an ordered stack of layers."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from neeh.document.layer import Layer
from neeh.ids import new_id
from neeh.ink import Author, BoundingBox, Stroke

# Abstract page units, root-2 aspect (A-series paper). Renderers map to pixels.
DEFAULT_PAGE_WIDTH = 1000.0
DEFAULT_PAGE_HEIGHT = 1414.0
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\Z")


@dataclass
class Page:
    width: float = DEFAULT_PAGE_WIDTH
    height: float = DEFAULT_PAGE_HEIGHT
    background: str = "#ffffff"
    id: str = field(default_factory=lambda: new_id("pg"))
    layers: list[Layer] = field(default_factory=lambda: [Layer(name="ink")])

    def __post_init__(self) -> None:
        for field_name, value in (("width", self.width), ("height", self.height)):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"page {field_name} must be a finite positive number")
        if not isinstance(self.background, str) or _HEX_COLOR.fullmatch(self.background) is None:
            raise ValueError("page background must be #rgb or #rrggbb")
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("page id must be a non-empty string")
        if not isinstance(self.layers, list) or any(
            not isinstance(layer, Layer) for layer in self.layers
        ):
            raise ValueError("page layers must be a list of Layer instances")
        layer_ids = [layer.id for layer in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("page contains duplicate layer ids")
        stroke_ids = [stroke.id for layer in self.layers for stroke in layer.strokes]
        if len(stroke_ids) != len(set(stroke_ids)):
            raise ValueError("page contains duplicate stroke ids")

    @property
    def rect(self) -> BoundingBox:
        return BoundingBox(0.0, 0.0, self.width, self.height)

    def layer(self, key: str) -> Optional[Layer]:
        """Look up a layer by id, falling back to the first name match."""
        for layer in self.layers:
            if layer.id == key:
                return layer
        for layer in self.layers:
            if layer.name == key:
                return layer
        return None

    def add_layer(self, name: str, author: Author = Author.USER) -> Layer:
        layer = Layer(name=name, author=author)
        self.layers.append(layer)
        return layer

    def agent_layer(self) -> Layer:
        """Get or create the layer agent ink goes on. Agent output never lands
        on user layers — it stays attributable and filterable."""
        for layer in self.layers:
            if layer.author is Author.AGENT and not layer.locked:
                return layer
        return self.add_layer("agent", author=Author.AGENT)

    def all_strokes(self, visible_only: bool = False) -> list[Stroke]:
        return [
            s
            for layer in self.layers
            if layer.visible or not visible_only
            for s in layer.strokes
        ]

    def find(self, stroke_id: str) -> Optional[tuple[Layer, Stroke]]:
        for layer in self.layers:
            stroke = layer.get(stroke_id)
            if stroke is not None:
                return layer, stroke
        return None

    def strokes_in(self, region: BoundingBox, visible_only: bool = False) -> list[Stroke]:
        return [
            s
            for layer in self.layers
            if layer.visible or not visible_only
            for s in layer.strokes_in(region)
        ]

    def strokes_since(self, epoch_ms: int) -> list[Stroke]:
        """Temporal query — 'what was written in the last 30 seconds'. Time is
        a first-class axis; no screenshot pipeline can answer this."""
        if (
            isinstance(epoch_ms, bool)
            or not isinstance(epoch_ms, int)
            or not 0 <= epoch_ms <= 2**63 - 1
        ):
            raise ValueError("epoch_ms must be a non-negative signed 64-bit integer")
        return [s for s in self.all_strokes() if s.created_at_ms >= epoch_ms]

    @property
    def content_bbox(self) -> Optional[BoundingBox]:
        return BoundingBox.union_all(
            layer.bbox for layer in self.layers if layer.bbox is not None
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "width": self.width,
            "height": self.height,
            "background": self.background,
            "layers": [layer.to_dict() for layer in self.layers],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Page":
        return cls(
            id=data["id"],
            width=data.get("width", DEFAULT_PAGE_WIDTH),
            height=data.get("height", DEFAULT_PAGE_HEIGHT),
            background=data.get("background", "#ffffff"),
            layers=[Layer.from_dict(l) for l in data.get("layers", [])],
        )
