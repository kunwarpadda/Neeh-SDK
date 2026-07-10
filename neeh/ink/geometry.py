"""Geometric primitives: the coordinate-level substrate of ink."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


@dataclass(frozen=True)
class Point:
    """One ink sample in page space.

    `t_ms` is milliseconds since the owning stroke started; pair it with
    `Stroke.created_at_ms` for absolute time. Tilt follows the W3C
    pointer-event convention (degrees, -90..90).
    """

    x: float
    y: float
    t_ms: int = 0
    pressure: float = 1.0
    tilt_x: float = 0.0
    tilt_y: float = 0.0

    def translated(self, dx: float, dy: float) -> "Point":
        return Point(self.x + dx, self.y + dy, self.t_ms, self.pressure, self.tilt_x, self.tilt_y)

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.t_ms, self.pressure, self.tilt_x, self.tilt_y]

    @classmethod
    def from_list(cls, data: Sequence[float]) -> "Point":
        x, y, *rest = data
        return cls(
            x=float(x),
            y=float(y),
            t_ms=int(rest[0]) if len(rest) > 0 else 0,
            pressure=float(rest[1]) if len(rest) > 1 else 1.0,
            tilt_x=float(rest[2]) if len(rest) > 2 else 0.0,
            tilt_y=float(rest[3]) if len(rest) > 3 else 0.0,
        )


@dataclass(frozen=True)
class BoundingBox:
    """Axis-aligned box in page coordinates. Zero-size boxes are valid."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float

    def __post_init__(self) -> None:
        if self.max_x < self.min_x or self.max_y < self.min_y:
            raise ValueError(f"inverted bounding box: {self}")

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center(self) -> tuple[float, float]:
        return ((self.min_x + self.max_x) / 2, (self.min_y + self.max_y) / 2)

    def contains(self, x: float, y: float) -> bool:
        return self.min_x <= x <= self.max_x and self.min_y <= y <= self.max_y

    def contains_box(self, other: "BoundingBox") -> bool:
        return (
            other.min_x >= self.min_x
            and other.max_x <= self.max_x
            and other.min_y >= self.min_y
            and other.max_y <= self.max_y
        )

    def intersects(self, other: "BoundingBox") -> bool:
        return not (
            other.min_x > self.max_x
            or other.max_x < self.min_x
            or other.min_y > self.max_y
            or other.max_y < self.min_y
        )

    def union(self, other: "BoundingBox") -> "BoundingBox":
        return BoundingBox(
            min(self.min_x, other.min_x),
            min(self.min_y, other.min_y),
            max(self.max_x, other.max_x),
            max(self.max_y, other.max_y),
        )

    def expanded(self, margin: float) -> "BoundingBox":
        return BoundingBox(
            self.min_x - margin, self.min_y - margin, self.max_x + margin, self.max_y + margin
        )

    @classmethod
    def from_points(cls, points: Iterable[Point]) -> "BoundingBox":
        pts = list(points)
        if not pts:
            raise ValueError("cannot compute bounding box of zero points")
        return cls(
            min(p.x for p in pts),
            min(p.y for p in pts),
            max(p.x for p in pts),
            max(p.y for p in pts),
        )

    @staticmethod
    def union_all(boxes: Iterable["BoundingBox"]) -> Optional["BoundingBox"]:
        result: Optional[BoundingBox] = None
        for box in boxes:
            result = box if result is None else result.union(box)
        return result

    def to_list(self) -> list[float]:
        return [self.min_x, self.min_y, self.max_x, self.max_y]

    @classmethod
    def from_list(cls, data: Sequence[float]) -> "BoundingBox":
        return cls(*(float(v) for v in data))
