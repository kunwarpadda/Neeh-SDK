"""S0 synthetic corpus (protocol §5).

Neeh-generated pages with perfect ground truth and zero licensing burden.
Everything is deterministic in the seed: stroke ids, geometry, timestamps,
word/shape placement, and jitter. Two page kinds for M1:

- text pages  — words placed in a row-major cell grid; ground truth maps each
  word to its stroke ids, bbox, and reading-order index (T1, T4).
- shape pages — one shape per page quadrant; ground truth maps each shape to
  its kind, quadrant, center, bbox, and stroke ids (T3, T4).

Known limitation (protocol §10.3): Hershey print is not human handwriting;
`jitter` adds seeded Gaussian point noise so legibility can be swept.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Optional

from neeh.document import Document, Layer, Page
from neeh.ink import Author, BoundingBox, Point, Stroke, StrokeStyle
from neeh.ink.textink import layout_text

PAGE_W, PAGE_H = 1000.0, 1414.0
BASE_EPOCH_MS = 1_700_000_000_000
POINT_DT_MS = 8
STROKE_GAP_MS = 400

WORDS = [
    "apple", "bridge", "cloud", "dragon", "ember", "forest", "garden", "harbor",
    "island", "jungle", "kettle", "lantern", "meadow", "night", "ocean", "piano",
    "quartz", "river", "stone", "temple", "under", "valley", "window", "xylem",
    "yellow", "zephyr", "candle", "mirror", "puzzle", "signal",
]

SHAPE_KINDS = ["circle", "square", "triangle", "arrow", "star"]
QUADRANTS = ["top-left", "top-right", "bottom-left", "bottom-right"]
_QUADRANT_CENTERS = {
    "top-left": (250.0, 353.5),
    "top-right": (750.0, 353.5),
    "bottom-left": (250.0, 1060.5),
    "bottom-right": (750.0, 1060.5),
}


@dataclass(frozen=True)
class CorpusPage:
    """One synthetic page plus its ground truth."""

    document: Document
    page: Page
    kind: str  # "text" | "shapes" | "math"
    seed: int
    jitter: float
    # text pages: [{"word", "order", "stroke_ids", "bbox"}]
    words: tuple[dict[str, Any], ...] = ()
    # shape pages: [{"kind", "quadrant", "center", "stroke_ids", "bbox"}]
    shapes: tuple[dict[str, Any], ...] = ()
    # math pages (S2): the LaTeX ground-truth transcription
    expression: str = ""


class _StrokeFactory:
    """Builds strokes with deterministic ids, timestamps, and optional jitter."""

    def __init__(self, page_tag: str, rng: random.Random, jitter: float) -> None:
        self._tag = page_tag
        self._rng = rng
        self._jitter = jitter
        self._count = 0

    def make(self, xy: list[tuple[float, float]], style: Optional[StrokeStyle] = None) -> Stroke:
        index = self._count
        self._count += 1
        points = []
        for i, (x, y) in enumerate(xy):
            if self._jitter > 0:
                x += self._rng.gauss(0.0, self._jitter)
                y += self._rng.gauss(0.0, self._jitter)
            x = min(max(x, 0.0), PAGE_W)
            y = min(max(y, 0.0), PAGE_H)
            points.append(Point(round(x, 2), round(y, 2), t_ms=i * POINT_DT_MS))
        return Stroke(
            points=tuple(points),
            style=style or StrokeStyle(),
            id=f"st_{self._tag}_{index:04d}",
            author=Author.USER,
            created_at_ms=BASE_EPOCH_MS + index * STROKE_GAP_MS,
        )


def _shape_polylines(kind: str, cx: float, cy: float, r: float) -> list[list[tuple[float, float]]]:
    if kind == "circle":
        pts = [
            (cx + r * math.cos(2 * math.pi * i / 24), cy + r * math.sin(2 * math.pi * i / 24))
            for i in range(25)
        ]
        return [pts]
    if kind == "square":
        return [[(cx - r, cy - r), (cx + r, cy - r), (cx + r, cy + r), (cx - r, cy + r),
                 (cx - r, cy - r)]]
    if kind == "triangle":
        return [[(cx, cy - r), (cx + r, cy + r * 0.8), (cx - r, cy + r * 0.8), (cx, cy - r)]]
    if kind == "arrow":  # horizontal shaft plus a separate 3-point head
        return [
            [(cx - r, cy), (cx + r, cy)],
            [(cx + r * 0.55, cy - r * 0.35), (cx + r, cy), (cx + r * 0.55, cy + r * 0.35)],
        ]
    if kind == "star":
        pts = []
        for i in range(11):
            radius = r if i % 2 == 0 else r * 0.45
            angle = -math.pi / 2 + i * math.pi / 5
            pts.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        return [pts]
    raise ValueError(f"unknown shape kind {kind!r}")


def _make_page(tag: str) -> tuple[Document, Page, Layer]:
    layer = Layer(name="ink", id=f"ly_{tag}")
    page = Page(width=PAGE_W, height=PAGE_H, id=f"pg_{tag}", layers=[layer])
    document = Document(
        title=f"s0-{tag}", id=f"doc_{tag}", created_at_ms=BASE_EPOCH_MS, pages=[page]
    )
    return document, page, layer


def make_text_page(index: int, seed: int, jitter: float = 0.0) -> CorpusPage:
    """4x2 grid of distinct words; row-major placement is the reading order."""
    tag = f"s0t{seed}_{index:02d}"
    # Structure (word choice, placement) must be invariant under the jitter
    # level, so a jitter sweep perturbs geometry only; noise gets its own RNG.
    rng = random.Random(f"{seed}:text:{index}")
    factory = _StrokeFactory(tag, random.Random(f"{seed}:text:{index}:jitter:{jitter}"), jitter)
    document, page, layer = _make_page(tag)

    n_words = rng.randint(6, 8)
    words = rng.sample(WORDS, n_words)
    truth: list[dict[str, Any]] = []
    cells = [(col, row) for row in range(4) for col in range(2)]  # row-major
    for order, word in enumerate(words):
        col, row = cells[order]
        x0 = 70.0 + col * 470.0
        y0 = 140.0 + row * 300.0
        box = BoundingBox(x0, y0, x0 + 420.0, y0 + 120.0)
        polylines, _ = layout_text(word, box, size=48.0)
        stroke_ids = []
        for polyline in polylines:
            stroke = layer.add(factory.make(polyline))
            stroke_ids.append(stroke.id)
        bbox = BoundingBox.union_all(layer.get(sid).bbox for sid in stroke_ids)
        truth.append({
            "word": word,
            "order": order,
            "stroke_ids": stroke_ids,
            "bbox": bbox.to_list(),
        })
    return CorpusPage(
        document=document, page=page, kind="text", seed=seed, jitter=jitter,
        words=tuple(truth),
    )


def make_dense_text_page(index: int, seed: int, jitter: float = 0.0) -> CorpusPage:
    """3x8 grid of words (~200+ strokes): the H7 foveated-context corpus (S0d).

    Dense enough that full static context is genuinely expensive, so the
    pull-vs-push comparison has something to save."""
    tag = f"s0d{seed}_{index:02d}"
    rng = random.Random(f"{seed}:dense:{index}")
    factory = _StrokeFactory(tag, random.Random(f"{seed}:dense:{index}:jitter:{jitter}"), jitter)
    document, page, layer = _make_page(tag)

    n_words = 24
    words = rng.sample(WORDS, min(n_words, len(WORDS)))
    truth: list[dict[str, Any]] = []
    cells = [(col, row) for row in range(8) for col in range(3)]  # row-major
    for order, word in enumerate(words):
        col, row = cells[order]
        x0 = 40.0 + col * 320.0
        y0 = 80.0 + row * 165.0
        box = BoundingBox(x0, y0, x0 + 290.0, y0 + 70.0)
        polylines, _ = layout_text(word, box, size=30.0)
        stroke_ids = []
        for polyline in polylines:
            stroke = layer.add(factory.make(polyline))
            stroke_ids.append(stroke.id)
        bbox = BoundingBox.union_all(layer.get(sid).bbox for sid in stroke_ids)
        truth.append({
            "word": word,
            "order": order,
            "stroke_ids": stroke_ids,
            "bbox": bbox.to_list(),
        })
    return CorpusPage(
        document=document, page=page, kind="text", seed=seed, jitter=jitter,
        words=tuple(truth),
    )


def make_shape_page(index: int, seed: int, jitter: float = 0.0) -> CorpusPage:
    """3-4 distinct shapes, each fully inside its own quadrant."""
    tag = f"s0s{seed}_{index:02d}"
    rng = random.Random(f"{seed}:shapes:{index}")
    factory = _StrokeFactory(tag, random.Random(f"{seed}:shapes:{index}:jitter:{jitter}"), jitter)
    document, page, layer = _make_page(tag)

    n_shapes = rng.randint(3, 4)
    kinds = rng.sample(SHAPE_KINDS, n_shapes)
    quadrants = rng.sample(QUADRANTS, n_shapes)
    style = StrokeStyle(width=3.0)
    truth: list[dict[str, Any]] = []
    for kind, quadrant in zip(kinds, quadrants):
        qx, qy = _QUADRANT_CENTERS[quadrant]
        r = rng.uniform(70.0, 120.0)
        cx = qx + rng.uniform(-60.0, 60.0)
        cy = qy + rng.uniform(-60.0, 60.0)
        stroke_ids = []
        for polyline in _shape_polylines(kind, cx, cy, r):
            stroke = layer.add(factory.make(polyline, style=style))
            stroke_ids.append(stroke.id)
        bbox = BoundingBox.union_all(layer.get(sid).bbox for sid in stroke_ids)
        truth.append({
            "kind": kind,
            "quadrant": quadrant,
            "center": [round(cx, 2), round(cy, 2)],
            "stroke_ids": stroke_ids,
            "bbox": bbox.to_list(),
        })
    return CorpusPage(
        document=document, page=page, kind="shapes", seed=seed, jitter=jitter,
        shapes=tuple(truth),
    )


def generate_corpus(
    seed: int = 0,
    n_text_pages: int = 6,
    n_shape_pages: int = 6,
    jitter: float = 0.0,
) -> list[CorpusPage]:
    pages = [make_text_page(i, seed, jitter) for i in range(n_text_pages)]
    pages += [make_shape_page(i, seed, jitter) for i in range(n_shape_pages)]
    return pages
