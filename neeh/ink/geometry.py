"""Geometric primitives: the coordinate-level substrate of ink."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence


def _finite(value: object, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{field} must be a finite number, got {value!r}")


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

    def __post_init__(self) -> None:
        _finite(self.x, "point x")
        _finite(self.y, "point y")
        if (
            isinstance(self.t_ms, bool)
            or not isinstance(self.t_ms, int)
            or not 0 <= self.t_ms <= 2**63 - 1
        ):
            raise ValueError(
                f"point t_ms must be a non-negative signed 64-bit integer, got {self.t_ms!r}"
            )
        _finite(self.pressure, "point pressure")
        if not 0.0 <= self.pressure <= 1.0:
            raise ValueError(f"point pressure must be in [0, 1], got {self.pressure!r}")
        for field, value in (("tilt_x", self.tilt_x), ("tilt_y", self.tilt_y)):
            _finite(value, f"point {field}")
            if not -90.0 <= value <= 90.0:
                raise ValueError(f"point {field} must be in [-90, 90], got {value!r}")

    def translated(self, dx: float, dy: float) -> "Point":
        return Point(self.x + dx, self.y + dy, self.t_ms, self.pressure, self.tilt_x, self.tilt_y)

    def to_list(self) -> list[float]:
        return [self.x, self.y, self.t_ms, self.pressure, self.tilt_x, self.tilt_y]

    @classmethod
    def from_list(cls, data: Sequence[float]) -> "Point":
        if isinstance(data, (str, bytes, bytearray)):
            raise ValueError("a point must be a numeric sequence")
        if not 2 <= len(data) <= 6:
            raise ValueError(f"a point needs 2 to 6 values, got {len(data)}")
        x, y, *rest = data
        return cls(
            x=float(x),
            y=float(y),
            t_ms=rest[0] if len(rest) > 0 else 0,
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
        for field, value in (
            ("min_x", self.min_x),
            ("min_y", self.min_y),
            ("max_x", self.max_x),
            ("max_y", self.max_y),
        ):
            _finite(value, f"bounding box {field}")
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
        if isinstance(data, (str, bytes, bytearray)):
            raise ValueError("a bounding box must be a numeric sequence")
        if len(data) != 4:
            raise ValueError(f"a bounding box needs exactly 4 values, got {len(data)}")
        return cls(*(float(v) for v in data))
