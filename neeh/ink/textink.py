"""Text as ink: lay out a string as single-stroke polylines.

Print uses Hershey Roman Simplex. Handwritten text uses Hershey Script Complex,
a true cursive stroke face with calligraphic weight and connected letterforms.
"""
from __future__ import annotations

import math
from typing import Optional

from neeh.ink.geometry import BoundingBox
from neeh.ink.hershey_script_complex import GLYPHS as SCRIPT_GLYPHS
from neeh.ink.hershey_simplex import BASELINE, CAP_HEIGHT, GLYPHS as PRINT_GLYPHS

LINE_HEIGHT = 1.6  # baseline-to-baseline distance, in multiples of size
MIN_SIZE = 4.0  # page units; below this text is unreadable anyway

Polyline = list[tuple[float, float]]
TEXT_STYLES = ("print", "handwritten")


def _validate_style(style: str) -> None:
    if style not in TEXT_STYLES:
        raise ValueError(f"style must be one of {TEXT_STYLES}")


def _font(style: str):
    return SCRIPT_GLYPHS if style == "handwritten" else PRINT_GLYPHS


def _glyph(ch: str, font):
    return font.get(ch) or font["?"]


def _line_bounds(text: str, font) -> tuple[float, float, float, float]:
    """Font-unit bounds including cursive side bearings and flourishes."""
    cursor = 0.0
    min_x = 0.0
    max_x = 0.0
    min_y = -12.0
    max_y = 9.0
    for ch in text:
        advance, strokes = _glyph(ch, font)
        for stroke in strokes:
            for gx, gy in stroke:
                min_x = min(min_x, cursor + gx)
                max_x = max(max_x, cursor + gx)
                min_y = min(min_y, gy)
                max_y = max(max_y, gy)
        cursor += advance
        max_x = max(max_x, cursor)
    return min_x, max_x, min_y, max_y


def _line_width(words: list[str], font) -> float:
    min_x, max_x, _, _ = _line_bounds(" ".join(words), font)
    return max_x - min_x


def _line_height(style: str) -> float:
    return 1.85 if style == "handwritten" else LINE_HEIGHT


def _wrap(text: str, size: float, max_width: float, style: str) -> list[list[str]]:
    """Greedy word wrap; explicit newlines are respected."""
    scale = size / CAP_HEIGHT
    font = _font(style)
    lines: list[list[str]] = []
    for raw_line in text.split("\n"):
        current: list[str] = []
        for word in raw_line.split():
            candidate = [*current, word]
            if current and _line_width(candidate, font) * scale > max_width:
                lines.append(current)
                current = [word]
            else:
                current = candidate
        lines.append(current)  # may be empty: a blank line
    return lines


def _block_height(lines: list[list[str]], size: float, style: str) -> float:
    if not lines:
        return 0.0
    font = _font(style)
    _, _, first_min_y, _ = _line_bounds(" ".join(lines[0]), font)
    _, _, _, last_max_y = _line_bounds(" ".join(lines[-1]), font)
    scale = size / CAP_HEIGHT
    return ((len(lines) - 1) * size * _line_height(style)
            + (last_max_y - first_min_y) * scale)


def _fits(lines: list[list[str]], size: float, region: BoundingBox, style: str) -> bool:
    scale = size / CAP_HEIGHT
    if _block_height(lines, size, style) > region.height:
        return False
    font = _font(style)
    for line in lines:
        if _line_width(line, font) * scale > region.width:
            return False
    return True


def measure_text(text: str, size: float, style: str = "print") -> tuple[float, float]:
    """Width and height in page units of `text` at cap height `size`,
    honoring explicit newlines but never word-wrapping. Uses the same glyph
    metrics as layout_text, so a region sized from this always fits."""
    _validate_style(style)
    scale = size / CAP_HEIGHT
    font = _font(style)
    lines = [raw.split() for raw in text.split("\n")]
    width = 0.0
    for words in lines:
        width = max(width, _line_width(words, font) * scale)
    return width, _block_height(lines, size, style)


def layout_text(
    text: str,
    region: BoundingBox,
    size: Optional[float] = None,
    style: str = "print",
    angle_deg: float = 0.0,
) -> tuple[list[Polyline], float]:
    """Lay `text` out inside `region`, top-left aligned.

    `size` is the cap height in page units; when omitted, the largest size
    that fits the region (wrapping at word boundaries) is chosen, floored at
    MIN_SIZE — long text degrades to small ink, never to an exception.
    Cursive side bearings, ascenders, descenders, and flourishes are included
    in measurement and kept inside the region.

    `angle_deg` rotates the finished layout about the region's top-left
    corner, in degrees counterclockwise as seen on screen (page y grows
    down). `region` is always the text's own unrotated frame — wrapping and
    auto-sizing happen before rotation — so rotated ink can leave the region
    and must still land on the page when added to a canvas.
    Returns (polylines in page coordinates, size used).
    """
    _validate_style(style)
    if (
        isinstance(angle_deg, bool)
        or not isinstance(angle_deg, (int, float))
        or not math.isfinite(angle_deg)
    ):
        raise ValueError(f"angle_deg must be a finite number, got {angle_deg!r}")
    if size is None:
        size = max(region.height / (LINE_HEIGHT * 2), MIN_SIZE)  # generous start
        while size > MIN_SIZE and not _fits(
            _wrap(text, size, region.width, style), size, region, style
        ):
            size *= 0.9
        size = max(size, MIN_SIZE)

    scale = size / CAP_HEIGHT
    font = _font(style)
    space = font[" "][0] * scale
    polylines: list[Polyline] = []
    lines = _wrap(text, size, region.width, style)
    _, _, first_min_y, _ = _line_bounds(" ".join(lines[0]) if lines else "", font)
    baseline = region.min_y + (BASELINE - first_min_y) * scale
    for line in lines:
        min_x, _, _, _ = _line_bounds(" ".join(line), font)
        x = region.min_x - min_x * scale
        for i, word in enumerate(line):
            if i:
                x += space
            for ch in word:
                advance, strokes = _glyph(ch, font)
                for stroke in strokes:
                    polylines.append([
                        (x + gx * scale, baseline + (gy - BASELINE) * scale)
                        for gx, gy in stroke
                    ])
                x += advance * scale
        baseline += size * _line_height(style)
    if angle_deg % 360.0:
        # Visual-CCW rotation in page coordinates (y down): the y-flip folds
        # into the sign of the sine terms.
        theta = math.radians(angle_deg % 360.0)
        cos_t, sin_t = math.cos(theta), math.sin(theta)
        pivot_x, pivot_y = region.min_x, region.min_y
        polylines = [
            [
                (
                    pivot_x + (x - pivot_x) * cos_t + (y - pivot_y) * sin_t,
                    pivot_y - (x - pivot_x) * sin_t + (y - pivot_y) * cos_t,
                )
                for x, y in line
            ]
            for line in polylines
        ]
    return polylines, size
