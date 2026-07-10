"""S1 corpus: Quick, Draw! sketches composed onto Neeh pages (protocol §5).

Quick, Draw! is CC BY 4.0 (Google), distributed as ndjson — one sketch per
line, strokes as parallel coordinate arrays. Both distributions are handled:
`simplified` (RDP-reduced, normalized to a 0-255 box, no timing) and `raw`
(device coordinates plus per-point time).

Composed pages reuse the S0 shapes truth schema — {kind, quadrant, center,
stroke_ids, bbox} with kind = the sketch's category — so every existing task
generator (T1 classification, T2, T3, T4, T5 highlight, T6) runs on real
human ink unchanged. Contamination note (protocol §10.2): models may know
Quick, Draw! categories; report S0-vs-S1 deltas, not S1 absolutes.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

from neeh.document import Document, Layer, Page
from neeh.ink import Author, BoundingBox, Point, Stroke, StrokeStyle

from research.harness.corpus_s0 import (
    BASE_EPOCH_MS,
    PAGE_H,
    PAGE_W,
    POINT_DT_MS,
    QUADRANTS,
    STROKE_GAP_MS,
    _QUADRANT_CENTERS,
    CorpusPage,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "quickdraw"
SKETCH_HALF_EXTENT = 130.0  # sketches are fitted into a 260x260 quadrant box


@dataclass(frozen=True)
class QuickDrawSketch:
    """One sketch: polylines in the source coordinate space."""

    category: str
    key_id: str
    recognized: bool
    polylines: tuple[tuple[tuple[float, float], ...], ...]


def parse_ndjson_line(line: str) -> QuickDrawSketch:
    record = json.loads(line)
    polylines = []
    for stroke in record["drawing"]:
        xs, ys = stroke[0], stroke[1]  # raw format has a third array (time)
        polylines.append(tuple((float(x), float(y)) for x, y in zip(xs, ys)))
    return QuickDrawSketch(
        category=str(record["word"]),
        key_id=str(record.get("key_id", "")),
        recognized=bool(record.get("recognized", True)),
        polylines=tuple(polylines),
    )


def load_category(
    path: Path,
    limit: int = 50,
    recognized_only: bool = True,
    max_strokes: int = 20,
) -> list[QuickDrawSketch]:
    """Read up to `limit` usable sketches from one category ndjson file."""
    sketches: list[QuickDrawSketch] = []
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            sketch = parse_ndjson_line(line)
            if recognized_only and not sketch.recognized:
                continue
            if not sketch.polylines or len(sketch.polylines) > max_strokes:
                continue
            sketches.append(sketch)
            if len(sketches) >= limit:
                break
    return sketches


def _fit_polylines(
    sketch: QuickDrawSketch, cx: float, cy: float, half_extent: float
) -> list[list[tuple[float, float]]]:
    """Scale the sketch uniformly into a box centered at (cx, cy)."""
    points = [p for polyline in sketch.polylines for p in polyline]
    min_x = min(p[0] for p in points)
    max_x = max(p[0] for p in points)
    min_y = min(p[1] for p in points)
    max_y = max(p[1] for p in points)
    span = max(max_x - min_x, max_y - min_y, 1e-6)
    scale = (2 * half_extent) / span
    off_x = cx - (min_x + max_x) / 2 * scale
    off_y = cy - (min_y + max_y) / 2 * scale
    return [
        [(x * scale + off_x, y * scale + off_y) for x, y in polyline]
        for polyline in sketch.polylines
    ]


def compose_sketch_page(
    index: int,
    seed: int,
    sketches_by_category: dict[str, list[QuickDrawSketch]],
) -> CorpusPage:
    """Place 3-4 sketches of distinct categories into distinct quadrants."""
    rng = random.Random(f"{seed}:quickdraw:{index}")
    categories = [c for c, pool in sketches_by_category.items() if pool]
    n_sketches = min(rng.randint(3, 4), len(categories))
    if n_sketches < 2:
        raise ValueError("need at least two categories with sketches")
    chosen = rng.sample(sorted(categories), n_sketches)
    quadrants = rng.sample(QUADRANTS, n_sketches)

    tag = f"qd{seed}_{index:02d}"
    layer = Layer(name="ink", id=f"ly_{tag}")
    page = Page(width=PAGE_W, height=PAGE_H, id=f"pg_{tag}", layers=[layer])
    document = Document(
        title=f"s1-{tag}", id=f"doc_{tag}", created_at_ms=BASE_EPOCH_MS, pages=[page]
    )

    style = StrokeStyle(width=3.0)
    stroke_count = 0
    truth: list[dict[str, Any]] = []
    for category, quadrant in zip(chosen, quadrants):
        sketch = rng.choice(sketches_by_category[category])
        qx, qy = _QUADRANT_CENTERS[quadrant]
        cx = qx + rng.uniform(-40.0, 40.0)
        cy = qy + rng.uniform(-40.0, 40.0)
        stroke_ids = []
        for polyline in _fit_polylines(sketch, cx, cy, SKETCH_HALF_EXTENT):
            points = tuple(
                Point(round(min(max(x, 0.0), PAGE_W), 2),
                      round(min(max(y, 0.0), PAGE_H), 2),
                      t_ms=i * POINT_DT_MS)
                for i, (x, y) in enumerate(polyline)
            )
            stroke = layer.add(Stroke(
                points=points, style=style, id=f"st_{tag}_{stroke_count:04d}",
                author=Author.USER,
                created_at_ms=BASE_EPOCH_MS + stroke_count * STROKE_GAP_MS,
            ))
            stroke_ids.append(stroke.id)
            stroke_count += 1
        bbox = BoundingBox.union_all(layer.get(sid).bbox for sid in stroke_ids)
        truth.append({
            "kind": category,
            "quadrant": quadrant,
            "center": [round(cx, 2), round(cy, 2)],
            "stroke_ids": stroke_ids,
            "bbox": bbox.to_list(),
            "source": f"quickdraw:{sketch.key_id}",
        })
    return CorpusPage(
        document=document, page=page, kind="shapes", seed=seed, jitter=0.0,
        shapes=tuple(truth),
    )


def generate_s1_corpus(
    seed: int = 0,
    n_pages: int = 6,
    data_dir: Path = DATA_DIR,
    categories: Optional[Iterable[str]] = None,
    sketches_per_category: int = 50,
) -> list[CorpusPage]:
    """Compose pages from downloaded category files (see fetch_quickdraw.py)."""
    files = sorted(Path(data_dir).glob("*.ndjson"))
    if categories is not None:
        wanted = set(categories)
        files = [f for f in files if f.stem in wanted]
    if len(files) < 2:
        raise FileNotFoundError(
            f"need at least two category files in {data_dir} — run "
            "`python -m research.harness.fetch_quickdraw` first"
        )
    pools = {f.stem: load_category(f, limit=sketches_per_category) for f in files}
    return [compose_sketch_page(i, seed, pools) for i in range(n_pages)]


def iter_fixture_lines() -> Iterator[str]:  # pragma: no cover - test helper
    """Two tiny synthetic ndjson lines in the simplified shape, for tests."""
    yield json.dumps({
        "word": "zigzag", "key_id": "fx1", "recognized": True,
        "drawing": [[[0, 60, 120, 180, 240], [120, 0, 120, 0, 120]]],
    })
    yield json.dumps({
        "word": "box", "key_id": "fx2", "recognized": True,
        "drawing": [[[0, 250, 250, 0, 0], [0, 0, 250, 250, 0]]],
    })
