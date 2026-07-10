"""Viewport: the pan/zoom window mapping page space to view space."""
from __future__ import annotations

from dataclasses import dataclass

from neeh.ink import BoundingBox

MIN_ZOOM = 0.05
MAX_ZOOM = 32.0


@dataclass
class Viewport:
    """`(x, y)` is the page coordinate at the view origin; `width`/`height`
    are the view size in pixels; `zoom` is view px per page unit."""

    width: float = 1280.0
    height: float = 800.0
    x: float = 0.0
    y: float = 0.0
    zoom: float = 1.0

    @property
    def visible_bounds(self) -> BoundingBox:
        return BoundingBox(self.x, self.y, self.x + self.width / self.zoom, self.y + self.height / self.zoom)

    def to_view(self, px: float, py: float) -> tuple[float, float]:
        return ((px - self.x) * self.zoom, (py - self.y) * self.zoom)

    def to_page(self, vx: float, vy: float) -> tuple[float, float]:
        return (self.x + vx / self.zoom, self.y + vy / self.zoom)

    def pan(self, dvx: float, dvy: float) -> None:
        """Pan by a view-space delta (e.g. a drag gesture in pixels)."""
        self.x += dvx / self.zoom
        self.y += dvy / self.zoom

    def zoom_at(self, factor: float, vx: float, vy: float) -> None:
        """Zoom, keeping the page point under view point (vx, vy) fixed."""
        px, py = self.to_page(vx, vy)
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, self.zoom * factor))
        self.x = px - vx / self.zoom
        self.y = py - vy / self.zoom

    def fit(self, bounds: BoundingBox, padding: float = 40.0) -> None:
        """Fit and center `bounds` in the view with `padding` view px around it."""
        usable_w = max(self.width - 2 * padding, 1.0)
        usable_h = max(self.height - 2 * padding, 1.0)
        zoom = min(usable_w / max(bounds.width, 1e-6), usable_h / max(bounds.height, 1e-6))
        self.zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        cx, cy = bounds.center
        self.x = cx - self.width / self.zoom / 2
        self.y = cy - self.height / self.zoom / 2
