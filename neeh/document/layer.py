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

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("layer name must be a non-empty string")
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("layer id must be a non-empty string")
        if not isinstance(self.author, Author):
            self.author = Author(self.author)
        if not isinstance(self.visible, bool) or not isinstance(self.locked, bool):
            raise ValueError("layer visible and locked flags must be booleans")
        if not isinstance(self.strokes, list) or any(
            not isinstance(stroke, Stroke) for stroke in self.strokes
        ):
            raise ValueError("layer strokes must be a list of Stroke instances")
        ids = [stroke.id for stroke in self.strokes]
        if len(ids) != len(set(ids)):
            raise ValueError("layer contains duplicate stroke ids")

    def add(self, stroke: Stroke) -> Stroke:
        if self.locked:
            raise ValueError(f"layer '{self.name}' is locked")
        if not isinstance(stroke, Stroke):
            raise ValueError("layer can only contain Stroke instances")
        if self.get(stroke.id) is not None:
            raise ValueError(f"duplicate stroke id {stroke.id!r} in layer")
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
