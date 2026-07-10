"""Visual properties of a stroke."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?\Z")


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
        if not isinstance(self.color, str) or _HEX_COLOR.fullmatch(self.color) is None:
            raise ValueError(f"stroke color must be #rgb or #rrggbb, got {self.color!r}")
        if (
            isinstance(self.width, bool)
            or not isinstance(self.width, (int, float))
            or not math.isfinite(self.width)
            or self.width <= 0
        ):
            raise ValueError(f"stroke width must be positive, got {self.width}")
        if (
            isinstance(self.opacity, bool)
            or not isinstance(self.opacity, (int, float))
            or not math.isfinite(self.opacity)
            or not 0.0 < self.opacity <= 1.0
        ):
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
