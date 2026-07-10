"""Pages: a fixed-size ink surface holding an ordered stack of layers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from neeh.document.layer import Layer
from neeh.ids import new_id
from neeh.ink import Author, BoundingBox, Stroke

# Abstract page units, root-2 aspect (A-series paper). Renderers map to pixels.
DEFAULT_PAGE_WIDTH = 1000.0
DEFAULT_PAGE_HEIGHT = 1414.0


@dataclass
class Page:
    width: float = DEFAULT_PAGE_WIDTH
    height: float = DEFAULT_PAGE_HEIGHT
    background: str = "#ffffff"
    id: str = field(default_factory=lambda: new_id("pg"))
    layers: list[Layer] = field(default_factory=lambda: [Layer(name="ink")])

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
