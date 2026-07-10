"""Encoding arms E0/E1a/E1b/E2/E4 (protocol §3).

Each encoder is a deterministic, versioned pure function of a Page. The legend
is part of the arm (in-context teaching is part of the encoding, per
SketchAgent); everything outside the legend + context block is byte-identical
across arms and lives in the runner.

E2 and E4 share one arc-length resampling step so they differ only in syntax —
that isolates the "models have seen SVG" variable from the compression
variable.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Callable, Optional

from neeh.context import build_ink_context
from neeh.document import Page

GRID_LONG_EDGE = 256  # E2 grid resolution across the longer page edge
RESAMPLE_GRID_STEP = 4.0  # target arc-length step, in grid units


@dataclass(frozen=True)
class EncodedContext:
    arm: str
    version: str
    legend: str
    text: Optional[str]  # context block placed in the prompt, or None
    image_png: Optional[bytes]  # attached page raster, or None


def _resample(points: list[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    """Arc-length resampling; always keeps first and last points."""
    if len(points) < 2 or step <= 0:
        return list(points)
    out = [points[0]]
    carried = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        segment = math.hypot(x1 - x0, y1 - y0)
        if segment == 0:
            continue
        position = carried
        while position + step <= segment:
            position += step
            t = position / segment
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
        carried = position - segment  # negative remainder toward the next segment
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def _page_strokes(page: Page):
    for layer in page.layers:
        if not layer.visible:
            continue
        yield from layer.strokes


# -- E0: raster control ------------------------------------------------------

E0_LEGEND = "The page is attached as an image."


def encode_e0(page: Page) -> EncodedContext:
    from neeh.rendering.png import render_page_png

    return EncodedContext(
        arm="E0", version="E0/0.1.0", legend=E0_LEGEND,
        text=None, image_png=render_page_png(page),
    )


# -- E1a / E1b: ICF v0 as shipped -------------------------------------------

E1A_LEGEND = (
    "The page is attached as an image, followed by its Ink Context Format v0 "
    "JSON snapshot (vector stroke records with stable stroke ids)."
)
E1B_LEGEND = (
    "The page is provided as an Ink Context Format v0 JSON snapshot: vector "
    "stroke records with stable stroke ids, bounding boxes as "
    "[min_x, min_y, max_x, max_y], and per-stroke sampled points as "
    "[x, y, t_ms, pressure, tilt_x, tilt_y]. Coordinates have (0,0) at the "
    "page's top-left, x right, y down. There is no image."
)


def _icf_json(page: Page) -> str:
    return json.dumps(build_ink_context(page), separators=(",", ":"))


def encode_e1a(page: Page) -> EncodedContext:
    from neeh.rendering.png import render_page_png

    return EncodedContext(
        arm="E1a", version="E1a/0.1.0", legend=E1A_LEGEND,
        text=_icf_json(page), image_png=render_page_png(page),
    )


def encode_e1b(page: Page) -> EncodedContext:
    return EncodedContext(
        arm="E1b", version="E1b/0.1.0", legend=E1B_LEGEND,
        text=_icf_json(page), image_png=None,
    )


# -- E2: quantized relative polyline (QRP) -----------------------------------

E2_LEGEND = """\
The page is described as quantized ink strokes on an integer grid, one stroke
per line. Header line: `page <grid_w> <grid_h>` — the grid covers the whole
page, (0,0) at the top-left, x right, y down. Each stroke line is:

  <stroke_id> <author> <brush> : <x0> <y0> <dx1> <dy1> <dx2> <dy2> ...

`<x0> <y0>` is the absolute grid position of the pen-down point; every
following pair is the offset from the previous point. Strokes are listed in
the order they were drawn. Example: `st_x user pen : 10 20 3 0 3 1` is a
stroke from (10,20) through (13,20) to (16,21) — a short, nearly horizontal
line drawn left to right."""


def encode_e2(page: Page) -> EncodedContext:
    scale = GRID_LONG_EDGE / max(page.width, page.height)
    grid_w = round(page.width * scale)
    grid_h = round(page.height * scale)
    step_page = RESAMPLE_GRID_STEP / scale
    lines = [f"page {grid_w} {grid_h}"]
    for stroke in _page_strokes(page):
        resampled = _resample([(p.x, p.y) for p in stroke.points], step_page)
        gx = [round(x * scale) for x, _ in resampled]
        gy = [round(y * scale) for _, y in resampled]
        body = [str(gx[0]), str(gy[0])]
        for i in range(1, len(gx)):
            body.append(str(gx[i] - gx[i - 1]))
            body.append(str(gy[i] - gy[i - 1]))
        lines.append(
            f"{stroke.id} {stroke.author.value} {stroke.style.brush.value} : "
            + " ".join(body)
        )
    return EncodedContext(
        arm="E2", version="E2/0.1.0", legend=E2_LEGEND,
        text="\n".join(lines), image_png=None,
    )


# -- E4: SVG path text --------------------------------------------------------

E4_LEGEND = (
    "The page is described as an SVG document. Each ink stroke is one <path> "
    "whose id attribute is its stable stroke id; coordinates are page units "
    "with (0,0) at the top-left, x right, y down. Paths are listed in the "
    "order they were drawn. There is no image."
)


def encode_e4(page: Page) -> EncodedContext:
    scale = GRID_LONG_EDGE / max(page.width, page.height)
    step_page = RESAMPLE_GRID_STEP / scale  # same resampling as E2 (see module doc)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '
        f'{round(page.width)} {round(page.height)}">'
    ]
    for stroke in _page_strokes(page):
        resampled = _resample([(p.x, p.y) for p in stroke.points], step_page)
        d = f"M {round(resampled[0][0])} {round(resampled[0][1])}"
        for x, y in resampled[1:]:
            d += f" L {round(x)} {round(y)}"
        style = stroke.style
        parts.append(
            f'<path id="{stroke.id}" data-author="{stroke.author.value}" fill="none" '
            f'stroke="{style.color}" stroke-width="{style.width:g}" d="{d}"/>'
        )
    parts.append("</svg>")
    return EncodedContext(
        arm="E4", version="E4/0.1.0", legend=E4_LEGEND,
        text="\n".join(parts), image_png=None,
    )


# -- E7 / E7v: hybrid composed from M1 evidence (m1-findings.md) --------------
#
# M1 measured: raster is unbeaten on transcription (E0 1.000 at +1.8k tok),
# SVG-with-ids is unbeaten on addressing (E4 1.000 at a quarter of ICF's
# cost), and E2's grid quantization is the cheapest geometry that still
# solves layout. E7 composes exactly those winners: the E0 PNG plus a
# compact SVG whose path data is E2-grade (resampled, integer grid,
# relative offsets). E7v is the same SVG alone, probing whether a pure-text
# arm can hold the frontier without pixels.

_E7_SVG_LEGEND = (
    "a compact SVG of the page: each ink stroke is one <path> whose id "
    "attribute is its stable stroke id. Coordinates are on an integer grid "
    "covering the whole page (the viewBox gives the grid size), (0,0) at the "
    "top-left, x right, y down. Each path starts with an absolute `M x y` "
    "and continues with relative `l dx dy dx dy ...` offsets. Paths are "
    "listed in the order they were drawn."
)
E7_LEGEND = "The page is attached as an image, followed by " + _E7_SVG_LEGEND
E7V_LEGEND = "The page is provided as " + _E7_SVG_LEGEND + " There is no image."


def _compact_svg(page: Page, grid_long_edge: int = GRID_LONG_EDGE,
                 with_bboxes: bool = False) -> str:
    """SVG paths with E2's resampling/quantization: same grid, same step.

    ``with_bboxes`` adds a data-bbox attribute (grid units) per stroke — the
    segmentation cue E1a carries that E7 lacks; see real-ink-findings.md."""
    scale = grid_long_edge / max(page.width, page.height)
    grid_w = round(page.width * scale)
    grid_h = round(page.height * scale)
    step_page = RESAMPLE_GRID_STEP / scale
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {grid_w} {grid_h}">']
    for stroke in _page_strokes(page):
        resampled = _resample([(p.x, p.y) for p in stroke.points], step_page)
        gx = [round(x * scale) for x, _ in resampled]
        gy = [round(y * scale) for _, y in resampled]
        d = f"M{gx[0]} {gy[0]}"
        if len(gx) > 1:
            d += "l" + " ".join(
                f"{gx[i] - gx[i - 1]} {gy[i] - gy[i - 1]}" for i in range(1, len(gx))
            )
        bbox = ""
        if with_bboxes:
            box = stroke.bbox  # page units per the v1 frame rule (echoable coords)
            bbox = (f' data-bbox="{round(box.min_x)} {round(box.min_y)} '
                    f'{round(box.max_x)} {round(box.max_y)}"')
        parts.append(f'<path id="{stroke.id}"{bbox} d="{d}"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def encode_e7(page: Page) -> EncodedContext:
    from neeh.rendering.png import render_page_png

    return EncodedContext(
        arm="E7", version="E7/0.1.0", legend=E7_LEGEND,
        text=_compact_svg(page), image_png=render_page_png(page),
    )


def encode_e7v(page: Page) -> EncodedContext:
    return EncodedContext(
        arm="E7v", version="E7v/0.1.0", legend=E7V_LEGEND,
        text=_compact_svg(page), image_png=None,
    )


# Grid-resolution sweep arms for the ICF v1 draft's open question #3: 256 was
# inherited from Google's ink-tokenization recipe and never swept. The 4-grid-
# unit resampling step is kept, so resolution coherently changes both
# quantization and sampling density.


# E7b: the E1b-addendum experiment (real-ink-findings.md) — does E1a's
# reading gain over raster survive when the vector side is the compact SVG
# plus per-stroke bboxes instead of full point JSON? (Answer: yes, 0.672 vs
# 0.664 at 30% of the cost.)
#
# 0.1.0 emitted bboxes in grid units and models copied them into region tool
# calls unconverted (T5 collapsed to 0.167). 0.2.0 applies the v1 frame rule:
# path geometry stays grid-quantized, but bboxes — coordinates a model might
# echo back — are PAGE units, and the legend says so.

E7B_LEGEND = (
    E7_LEGEND[:-1] + "; each path also carries data-bbox=\"min_x min_y max_x "
    "max_y\", the stroke's bounding box in PAGE units (not grid units). Any "
    "coordinates you output (regions, points) must be page units."
)


def encode_e7b(page: Page) -> EncodedContext:
    from neeh.rendering.png import render_page_png

    return EncodedContext(
        arm="E7b", version="E7b/0.2.0", legend=E7B_LEGEND,
        text=_compact_svg(page, with_bboxes=True), image_png=render_page_png(page),
    )


# Legend-variant arm (protocol §5 risk 1: prompt sensitivity). Identical
# geometry text to E7v; only the legend differs, isolating the wording effect
# on the winning arm.

E7VB_LEGEND = (
    "SVG of the page. One <path> per pen stroke, in drawing order; the id "
    "attribute is the stroke's id. Integer coordinates on the viewBox grid, "
    "origin top-left, x right, y down; `M` is absolute, `l` offsets are "
    "relative. No image."
)


def encode_e7vb(page: Page) -> EncodedContext:
    return EncodedContext(
        arm="E7vB", version="E7vB/0.1.0", legend=E7VB_LEGEND,
        text=_compact_svg(page), image_png=None,
    )


def encode_e7v128(page: Page) -> EncodedContext:
    return EncodedContext(
        arm="E7v128", version="E7v128/0.1.0", legend=E7V_LEGEND,
        text=_compact_svg(page, grid_long_edge=128), image_png=None,
    )


def encode_e7v512(page: Page) -> EncodedContext:
    return EncodedContext(
        arm="E7v512", version="E7v512/0.1.0", legend=E7V_LEGEND,
        text=_compact_svg(page, grid_long_edge=512), image_png=None,
    )


# -- Control arm: no page context at all -------------------------------------

CTRL_LEGEND = "No page context is provided for this question."


def encode_ctrl(page: Page) -> EncodedContext:  # noqa: ARG001 - deliberate
    """Scaffolding-cost baseline: identical prompt shape, empty context.

    CLI backends wrap every call in their own system prompt; per-arm token
    cost is computed as a delta against this arm (protocol changelog v0.2).
    """
    return EncodedContext(
        arm="CTRL", version="CTRL/0.1.0", legend=CTRL_LEGEND, text=None, image_png=None,
    )


ENCODERS: dict[str, Callable[[Page], EncodedContext]] = {
    "E0": encode_e0,
    "E1a": encode_e1a,
    "E1b": encode_e1b,
    "E2": encode_e2,
    "E4": encode_e4,
    "E7": encode_e7,
    "E7b": encode_e7b,
    "E7v": encode_e7v,
    "E7vB": encode_e7vb,
    "E7v128": encode_e7v128,
    "E7v512": encode_e7v512,
    "CTRL": encode_ctrl,
}

M1_ARMS = ["E0", "E1a", "E1b", "E2", "E4"]


# M2 arms live in encoders_m2.py, which registers itself into ENCODERS on
# import. Importing it here fills the registry for everyone who imports this
# module; the ImportError guard covers the encoders_m2-imported-first cycle,
# where its own bottom-of-module registration completes the job instead.
try:
    from research.harness import encoders_m2  # noqa: F401  (registration side effect)
except ImportError:  # pragma: no cover - partial-initialization cycle
    pass

ALL_ARMS = M1_ARMS + ["E3", "E5", "E6", "E7", "E7v"]
