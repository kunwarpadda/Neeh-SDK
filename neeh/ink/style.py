"""Visual properties of a stroke."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class Brush(str, Enum):
    PEN = "pen"
    MARKER = "marker"
    HIGHLIGHTER = "highlighter"


@dataclass(frozen=True)
class StrokeStyle:
    """Immutable stroke appearance. `width` is the base width in page units;
    per-point pressure modulates it at render time."""

    color: str = "#1a1a1a"
    width: float = 2.0
    brush: Brush = Brush.PEN
    opacity: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.brush, Brush):
            object.__setattr__(self, "brush", Brush(self.brush))
        if self.width <= 0:
            raise ValueError(f"stroke width must be positive, got {self.width}")
        if not 0.0 < self.opacity <= 1.0:
            raise ValueError(f"opacity must be in (0, 1], got {self.opacity}")

    @classmethod
    def highlighter(cls, color: str = "#ffe066", width: float = 18.0) -> "StrokeStyle":
        return cls(color=color, width=width, brush=Brush.HIGHLIGHTER, opacity=0.35)

    def to_dict(self) -> dict[str, Any]:
        return {
            "color": self.color,
            "width": self.width,
            "brush": self.brush.value,
            "opacity": self.opacity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StrokeStyle":
        return cls(
            color=data.get("color", "#1a1a1a"),
            width=data.get("width", 2.0),
            brush=Brush(data.get("brush", "pen")),
            opacity=data.get("opacity", 1.0),
        )
