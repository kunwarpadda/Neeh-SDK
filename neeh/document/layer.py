"""Layers: ordered stroke containers with visibility, locking, and authorship."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from neeh.ids import new_id
from neeh.ink import Author, BoundingBox, Stroke


@dataclass
class Layer:
    name: str = "ink"
    author: Author = Author.USER
    id: str = field(default_factory=lambda: new_id("ly"))
    visible: bool = True
    locked: bool = False
    strokes: list[Stroke] = field(default_factory=list)

    def add(self, stroke: Stroke) -> Stroke:
        if self.locked:
            raise ValueError(f"layer '{self.name}' is locked")
        self.strokes.append(stroke)
        return stroke

    def remove(self, stroke_id: str) -> Optional[Stroke]:
        if self.locked:
            raise ValueError(f"layer '{self.name}' is locked")
        for i, stroke in enumerate(self.strokes):
            if stroke.id == stroke_id:
                return self.strokes.pop(i)
        return None

    def get(self, stroke_id: str) -> Optional[Stroke]:
        for stroke in self.strokes:
            if stroke.id == stroke_id:
                return stroke
        return None

    def strokes_in(self, region: BoundingBox) -> list[Stroke]:
        return [s for s in self.strokes if region.intersects(s.bbox)]

    @property
    def bbox(self) -> Optional[BoundingBox]:
        return BoundingBox.union_all(s.bbox for s in self.strokes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "author": self.author.value,
            "visible": self.visible,
            "locked": self.locked,
            "strokes": [s.to_dict() for s in self.strokes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Layer":
        return cls(
            id=data["id"],
            name=data.get("name", "ink"),
            author=Author(data.get("author", "user")),
            visible=data.get("visible", True),
            locked=data.get("locked", False),
            strokes=[Stroke.from_dict(s) for s in data.get("strokes", [])],
        )
