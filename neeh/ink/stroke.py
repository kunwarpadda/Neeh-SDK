"""The stroke: the atomic unit of ink."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from enum import Enum
from functools import cached_property
from typing import Any, Iterable

from neeh.ids import new_id
from neeh.ink.geometry import BoundingBox, Point
from neeh.ink.style import StrokeStyle


class Author(str, Enum):
    """Who made a mark. Agent ink is always attributable, filterable, and
    undoable — user ink is never silently mutated."""

    USER = "user"
    AGENT = "agent"


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class Stroke:
    """An immutable timestamped sequence of points.

    Edits produce new Stroke instances; the id is stable across geometric
    transforms (move, style change) so agent references survive edits.
    Point `t_ms` values are offsets from `created_at_ms` (epoch ms), keeping
    time a first-class, queryable axis.
    """

    points: tuple[Point, ...]
    style: StrokeStyle = field(default_factory=StrokeStyle)
    id: str = field(default_factory=lambda: new_id("st"))
    author: Author = Author.USER
    created_at_ms: int = field(default_factory=_now_ms)

    def __post_init__(self) -> None:
        if not isinstance(self.points, tuple):
            object.__setattr__(self, "points", tuple(self.points))
        if not self.points:
            raise ValueError("a stroke needs at least one point")
        if not isinstance(self.author, Author):
            object.__setattr__(self, "author", Author(self.author))

    @cached_property
    def bbox(self) -> BoundingBox:
        return BoundingBox.from_points(self.points)

    @property
    def duration_ms(self) -> int:
        return self.points[-1].t_ms - self.points[0].t_ms

    def translated(self, dx: float, dy: float) -> "Stroke":
        return replace(self, points=tuple(p.translated(dx, dy) for p in self.points))

    def with_style(self, style: StrokeStyle) -> "Stroke":
        return replace(self, style=style)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "author": self.author.value,
            "created_at_ms": self.created_at_ms,
            "style": self.style.to_dict(),
            "points": [p.to_list() for p in self.points],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Stroke":
        return cls(
            points=tuple(Point.from_list(p) for p in data["points"]),
            style=StrokeStyle.from_dict(data.get("style", {})),
            id=data["id"],
            author=Author(data.get("author", "user")),
            created_at_ms=data.get("created_at_ms", 0),
        )

    @classmethod
    def from_xy(
        cls,
        xy: Iterable[tuple[float, float]],
        style: StrokeStyle | None = None,
        author: Author = Author.USER,
    ) -> "Stroke":
        """Convenience for tests and synthetic ink: points from bare (x, y) pairs."""
        pts = tuple(Point(x, y) for x, y in xy)
        return cls(points=pts, style=style or StrokeStyle(), author=author)
