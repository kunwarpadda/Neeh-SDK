"""Text as ink: lay out a string as single-stroke polylines.

This is the "print" style behind the `write_text` tool — a legible,
dependency-free stroke font (Hershey Simplex) so agents can answer in ink.
The user-font style (handwriting cloned from the user's own strokes) stays
reserved for the Neeh app's text-layout extraction.
"""
from __future__ import annotations

from typing import Optional

from neeh.ink.geometry import BoundingBox
from neeh.ink.hershey_simplex import BASELINE, CAP_HEIGHT, GLYPHS

LINE_HEIGHT = 1.6  # baseline-to-baseline distance, in multiples of size
MIN_SIZE = 4.0  # page units; below this text is unreadable anyway

Polyline = list[tuple[float, float]]


def _glyph(ch: str):
    return GLYPHS.get(ch) or GLYPHS["?"]


def _word_advance(word: str) -> float:
    """Advance width of a word in font units."""
    return sum(_glyph(ch)[0] for ch in word)


def _wrap(text: str, size: float, max_width: float) -> list[list[str]]:
    """Greedy word wrap; explicit newlines are respected."""
    scale = size / CAP_HEIGHT
    space = GLYPHS[" "][0] * scale
    lines: list[list[str]] = []
    for raw_line in text.split("\n"):
        current: list[str] = []
        used = 0.0
        for word in raw_line.split():
            w = _word_advance(word) * scale
            needed = w if not current else space + w
            if current and used + needed > max_width:
                lines.append(current)
                current, used = [word], w
            else:
                current.append(word)
                used += needed
        lines.append(current)  # may be empty: a blank line
    return lines


def _fits(lines: list[list[str]], size: float, region: BoundingBox) -> bool:
    scale = size / CAP_HEIGHT
    if size + (len(lines) - 1) * size * LINE_HEIGHT > region.height:
        return False
    space = GLYPHS[" "][0] * scale
    for line in lines:
        width = sum(_word_advance(w) * scale for w in line) + max(len(line) - 1, 0) * space
        if width > region.width:
            return False
    return True


def measure_text(text: str, size: float) -> tuple[float, float]:
    """Width and height in page units of `text` at cap height `size`,
    honoring explicit newlines but never word-wrapping. Uses the same glyph
    metrics as layout_text, so a region sized from this always fits."""
    scale = size / CAP_HEIGHT
    space = GLYPHS[" "][0] * scale
    lines = text.split("\n")
    width = 0.0
    for raw in lines:
        words = raw.split()
        w = sum(_word_advance(word) * scale for word in words)
        w += max(len(words) - 1, 0) * space
        width = max(width, w)
    return width, size + (len(lines) - 1) * size * LINE_HEIGHT


def layout_text(
    text: str, region: BoundingBox, size: Optional[float] = None
) -> tuple[list[Polyline], float]:
    """Lay `text` out inside `region`, top-left aligned.

    `size` is the cap height in page units; when omitted, the largest size
    that fits the region (wrapping at word boundaries) is chosen, floored at
    MIN_SIZE — long text degrades to small ink, never to an exception.
    Alignment is by cap height: a few tall glyphs (parentheses, 't', '?')
    and descenders may overshoot the region by up to 4/21 of the size.
    Returns (polylines in page coordinates, size used).
    """
    if size is None:
        size = max(region.height / (LINE_HEIGHT * 2), MIN_SIZE)  # generous start
        while size > MIN_SIZE and not _fits(_wrap(text, size, region.width), size, region):
            size *= 0.9
        size = max(size, MIN_SIZE)

    scale = size / CAP_HEIGHT
    space = GLYPHS[" "][0] * scale
    polylines: list[Polyline] = []
    baseline = region.min_y + size  # first baseline: cap top touches the region top
    for line in _wrap(text, size, region.width):
        x = region.min_x
        for i, word in enumerate(line):
            if i:
                x += space
            for ch in word:
                advance, strokes = _glyph(ch)
                for stroke in strokes:
                    polylines.append(
                        [(x + gx * scale, baseline + (gy - BASELINE) * scale) for gx, gy in stroke]
                    )
                x += advance * scale
        baseline += size * LINE_HEIGHT
    return polylines, size
