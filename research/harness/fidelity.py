"""Offline geometry-fidelity exhibit for the ICF v1 draft (open question #3).

Measures what the svg-paths/grid encoding loses *geometrically* — no model
calls. For every S0 corpus stroke we encode at a grid resolution, decode with
the SDK's consumer-side parser, map back to page units, and measure each
original point's distance to the decoded polyline. That bounds the combined
resampling + quantization error the model context carries.

The model-side half of the question (does coarser geometry hurt task scores?)
needs the live E7v128/E7v512 sweep; this exhibit is the physical half.
"""
from __future__ import annotations

import math
from pathlib import Path
from statistics import mean

from neeh.context import parse_ink_paths
from neeh.document import Page

from research.harness.corpus_s0 import generate_corpus
from research.harness.encoders import _compact_svg
from research.harness.ledger import DEFAULT_LEDGER

FIDELITY_PATH = DEFAULT_LEDGER.parent / "geometry-fidelity.md"
GRID_EDGES = (128, 256, 512)


def _point_to_segment(px, py, x0, y0, x1, y1) -> float:
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - x0, py - y0)
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length_sq))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


def _point_to_polyline(px, py, polyline) -> float:
    if len(polyline) == 1:
        return math.hypot(px - polyline[0][0], py - polyline[0][1])
    return min(
        _point_to_segment(px, py, x0, y0, x1, y1)
        for (x0, y0), (x1, y1) in zip(polyline, polyline[1:])
    )


def page_errors(page: Page, grid_long_edge: int) -> tuple[list[float], int]:
    """Per-original-point deviations (page units) and encoded size in chars."""
    svg = _compact_svg(page, grid_long_edge=grid_long_edge)
    _, decoded = parse_ink_paths(svg, page_width=page.width, page_height=page.height)
    by_id = {path.id: path.page_points for path in decoded}
    errors: list[float] = []
    for layer in page.layers:
        if not layer.visible:
            continue
        for stroke in layer.strokes:
            polyline = by_id[stroke.id]
            errors.extend(
                _point_to_polyline(point.x, point.y, polyline)
                for point in stroke.points
            )
    return errors, len(svg)


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[index]


def fidelity_table() -> str:
    pages = generate_corpus()
    lines = [
        "# Geometry fidelity of svg-paths/grid (offline, exact)",
        "",
        f"S0 corpus, {len(pages)} pages. Every original ink point's distance to the",
        "decoded (encode -> parse_ink_paths -> page units) polyline, in page units",
        "(page is 1000 x 1414). This is the physical half of icf-v1-draft open",
        "question #3; the live E7v128/E7v512 sweep supplies the task-score half.",
        "",
        "| grid | page kind | mean err | p95 err | max err | mean chars |",
        "|---|---|---|---|---|---|",
    ]
    for grid in GRID_EDGES:
        for kind in ("text", "shapes"):
            errors: list[float] = []
            sizes: list[int] = []
            for corpus_page in pages:
                if corpus_page.kind != kind:
                    continue
                page_errs, chars = page_errors(corpus_page.page, grid)
                errors.extend(page_errs)
                sizes.append(chars)
            lines.append(
                f"| {grid} | {kind} | {mean(errors):.2f} | {_percentile(errors, 0.95):.2f} "
                f"| {max(errors):.2f} | {mean(sizes):,.0f} |"
            )
    lines += [
        "",
        "Reading: error scales inversely with grid resolution while characters grow",
        "sub-linearly (offsets stay small). For scale, a pen stroke is ~2-3 page",
        "units wide; errors below that are invisible at readback.",
    ]
    return "\n".join(lines) + "\n"


def write_fidelity(path: Path = FIDELITY_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fidelity_table(), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_fidelity())
