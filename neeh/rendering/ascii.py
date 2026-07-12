"""ASCII rasterizer — a token-cheap "gestalt" view of a page for model context.

Maps strokes onto a monospace character grid with direction glyphs
(``-`` ``|`` ``/`` ``\\``) and optionally overlays single-character
Set-of-Marks labels. Unlike the PNG backend this costs no image tokens and
needs no vision model: it is a *text* rendering of spatial layout, meant as
the cheap perceptual tier beside the structured ink index.

It conveys arrangement, not fine detail — dense handwriting degrades to
texture, by design. Use it for layout and pointing; use the raster only when
a task must actually read the ink.
"""
from __future__ import annotations

import math
from typing import Mapping, Optional

from neeh.document import Page
from neeh.ink import BoundingBox

# A monospace character cell is roughly twice as tall as it is wide; rows are
# scaled down by this so the rendered aspect ratio matches the page.
_CELL_ASPECT = 2.0


def _glyph(dx: float, dy: float) -> str:
    """A line-drawing character for a segment's direction (y grows downward)."""
    angle = math.degrees(math.atan2(-dy, dx)) % 180.0
    if angle < 22.5 or angle >= 157.5:
        return "-"
    if angle < 67.5:
        return "/"
    if angle < 112.5:
        return "|"
    return "\\"


def render_page_ascii(
    page: Page,
    *,
    region: Optional[BoundingBox] = None,
    cols: int = 54,
    rows: Optional[int] = None,
    marks: Optional[Mapping[str, tuple[float, float]]] = None,
    strip: bool = True,
) -> str:
    """Render a page (or a region of it) as a monospace character grid.

    ``cols`` sets the width; ``rows`` defaults to an aspect-correct height.
    ``marks`` overlays single-character labels at page-space points, on top of
    the ink — the Set-of-Marks layer that lets a model name a region by id.
    Returns the grid as newline-joined text (trailing spaces stripped unless
    ``strip`` is False); a page with no ink renders as an empty string.
    """
    region = region or page.content_bbox
    if region is None:  # a page with no ink has nothing to render
        return ""
    cols = max(int(cols), 1)
    if rows is None:
        ratio = max(region.height, 1e-6) / max(region.width, 1e-6)
        rows = max(1, round(cols * ratio / _CELL_ASPECT))
    rows = max(int(rows), 1)
    sx = (cols - 1) / max(region.width, 1e-6)
    sy = (rows - 1) / max(region.height, 1e-6)

    def cell(x: float, y: float) -> tuple[int, int]:
        col = min(max(int(round((x - region.min_x) * sx)), 0), cols - 1)
        row = min(max(int(round((y - region.min_y) * sy)), 0), rows - 1)
        return row, col

    grid: dict[tuple[int, int], str] = {}
    for layer in page.layers:
        if not layer.visible:
            continue
        for stroke in layer.strokes:
            pts = stroke.points
            if len(pts) == 1:
                grid[cell(pts[0].x, pts[0].y)] = "o"
                continue
            for i in range(len(pts) - 1):
                x0, y0 = pts[i].x, pts[i].y
                x1, y1 = pts[i + 1].x, pts[i + 1].y
                mark = _glyph(x1 - x0, y1 - y0)
                steps = max(1, int(math.hypot((x1 - x0) * sx, (y1 - y0) * sy)))
                for k in range(steps + 1):
                    t = k / steps
                    grid[cell(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)] = mark

    if marks:
        for label, (x, y) in marks.items():
            if label:
                grid[cell(x, y)] = label[0]

    lines = ["".join(grid.get((r, c), " ") for c in range(cols)) for r in range(rows)]
    if strip:
        lines = [line.rstrip() for line in lines]
    return "\n".join(lines)
