"""Embedded (anytime) ink coding — the SPIHT/JPEG2000 idea applied to context.

EE's embedded coders emit symbols in steepest rate-distortion-slope order so
the bitstream can be truncated anywhere and is near-optimal at every
truncation point. Applied to ink: one canonical context string — coarse paths
first, then per-stroke refinements ordered by how much geometric error each
one removes. Any token budget slices the same string; there are no tiers to
choose, only truncation points.

This module is the *offline geometry proof*: it builds the embedded string
and measures its rate-distortion curve (chars vs mean reconstruction error in
page units) against the fixed-grid encodings (E7v128/E7v/E7v512). A
model-facing arm only makes sense if the curve dominates here first.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean
from typing import Optional

from neeh.document import Page

from research.harness.encoders import (
    GRID_LONG_EDGE,
    RESAMPLE_GRID_STEP,
    _page_strokes,
    _rdp,
    _resample,
)
from research.harness.fidelity import _point_to_polyline

COARSE_EPS_GRID = 8.0  # aggressive first pass: corners only
REFINE_CHUNKS = 4  # refinement sections between coarse and full


@dataclass(frozen=True)
class EmbeddedInk:
    """Sections of one embedded context string, in emit order."""

    header: str  # svg open tag (grid declaration)
    coarse: list[str]  # one coarse <path> per stroke, drawn order
    refinements: list[list[str]]  # chunks of full-detail re-emissions
    footer: str

    def text_at(self, level: int) -> str:
        """The context string truncated after `level` refinement chunks."""
        parts = [self.header, *self.coarse]
        for chunk in self.refinements[:level]:
            parts.extend(chunk)
        parts.append(self.footer)
        return "\n".join(parts)


def _grid_polyline(points, scale, eps_grid: Optional[float]):
    """Resample -> optional RDP -> integer grid points (as page-unit floats)."""
    step_page = RESAMPLE_GRID_STEP / scale
    pts = _resample(points, step_page)
    if eps_grid is not None:
        pts = _rdp(pts, eps_grid / scale)
    grid = [(round(x * scale), round(y * scale)) for x, y in pts]
    return grid, [(gx / scale, gy / scale) for gx, gy in grid]


def _path_d(grid_points) -> str:
    d = f"M{grid_points[0][0]} {grid_points[0][1]}"
    if len(grid_points) > 1:
        d += "l" + " ".join(
            f"{grid_points[i][0] - grid_points[i - 1][0]} "
            f"{grid_points[i][1] - grid_points[i - 1][1]}"
            for i in range(1, len(grid_points))
        )
    return d


def build_embedded(page: Page, grid_long_edge: int = GRID_LONG_EDGE) -> EmbeddedInk:
    scale = grid_long_edge / max(page.width, page.height)
    grid_w, grid_h = round(page.width * scale), round(page.height * scale)

    coarse_lines: list[str] = []
    gains: list[tuple[float, str, str]] = []  # (error removed, id, fine path line)
    for stroke in _page_strokes(page):
        original = [(p.x, p.y) for p in stroke.points]
        coarse_grid, coarse_page = _grid_polyline(original, scale, COARSE_EPS_GRID)
        fine_grid, fine_page = _grid_polyline(original, scale, None)
        coarse_lines.append(f'<path id="{stroke.id}" d="{_path_d(coarse_grid)}"/>')
        err_coarse = mean(_point_to_polyline(x, y, coarse_page) for x, y in original)
        err_fine = mean(_point_to_polyline(x, y, fine_page) for x, y in original)
        gain = err_coarse - err_fine
        gains.append(
            (gain, stroke.id, f'<path id="{stroke.id}" d="{_path_d(fine_grid)}"/>')
        )

    # Steepest rate-distortion slope first: refine the strokes whose coarse
    # form is most wrong, in equal-count chunks.
    gains.sort(key=lambda g: -g[0])
    per_chunk = max(1, -(-len(gains) // REFINE_CHUNKS))
    refinements = [
        [line for _, _, line in gains[i : i + per_chunk]]
        for i in range(0, len(gains), per_chunk)
    ]
    return EmbeddedInk(
        header=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {grid_w} {grid_h}">',
        coarse=coarse_lines,
        refinements=refinements,
        footer="</svg>",
    )


def rate_distortion_curve(page: Page, grid_long_edge: int = GRID_LONG_EDGE):
    """(chars, mean error in page units) at every truncation point.

    A refined stroke's geometry supersedes its coarse form, mirroring how the
    legend instructs a model to read the refinement section.
    """
    scale = grid_long_edge / max(page.width, page.height)
    embedded = build_embedded(page, grid_long_edge)

    strokes = list(_page_strokes(page))
    originals = {s.id: [(p.x, p.y) for p in s.points] for s in strokes}
    coarse_page = {
        s.id: _grid_polyline(originals[s.id], scale, COARSE_EPS_GRID)[1] for s in strokes
    }
    fine_page = {
        s.id: _grid_polyline(originals[s.id], scale, None)[1] for s in strokes
    }
    order = [g[1] for g in sorted(
        ((mean(_point_to_polyline(x, y, coarse_page[s.id]) for x, y in originals[s.id])
          - mean(_point_to_polyline(x, y, fine_page[s.id]) for x, y in originals[s.id])),
         s.id)
        for s in strokes
    )][::-1]

    per_chunk = max(1, -(-len(order) // REFINE_CHUNKS))
    points = []
    for level in range(len(embedded.refinements) + 1):
        refined = set(order[: level * per_chunk])
        errors = [
            _point_to_polyline(x, y, fine_page[sid] if sid in refined else coarse_page[sid])
            for sid, pts in originals.items()
            for x, y in pts
        ]
        points.append((len(embedded.text_at(level)), mean(errors)))
    return points
