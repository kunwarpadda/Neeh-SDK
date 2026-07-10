"""S2 corpus adapter: Google MathWriting (real handwritten math, CC BY 4.0).

Parses InkML samples into corpus pages — one handwritten expression per page,
LaTeX label as the T1 transcription truth (scored with raw CER; case and
punctuation matter for LaTeX). This is the protocol's S2 gate: E7v's 0.910
synthetic transcription must hold on real handwriting before any ICF v1 claim.

Data: run ``python -m research.harness.fetch_mathwriting`` once to download
the official excerpt archive into ``research/data/mathwriting/`` (gitignored).

Dataset: https://github.com/google-research/google-research/tree/master/mathwriting
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from neeh.document import Document, Layer, Page
from neeh.ink import Author, Point, Stroke

from research.harness.corpus_s0 import BASE_EPOCH_MS, PAGE_H, PAGE_W, CorpusPage

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "mathwriting"
_INKML_NS = "{http://www.w3.org/2003/InkML}"

# Expressions are wider than tall; fit into a centered landscape content box.
_BOX_W, _BOX_H = 900.0, 500.0


@dataclass(frozen=True)
class MathWritingSample:
    sample_id: str
    label: str  # normalized LaTeX
    polylines: tuple[tuple[tuple[float, float], ...], ...]


def parse_inkml(text: str, sample_id: str = "sample") -> MathWritingSample:
    """Parse one InkML file: traces plus the (normalized, else plain) label."""
    root = ET.fromstring(text)
    label = None
    fallback = None
    for annotation in root.iter(f"{_INKML_NS}annotation"):
        kind = annotation.get("type")
        if kind == "normalizedLabel":
            label = (annotation.text or "").strip()
        elif kind == "label" and fallback is None:
            fallback = (annotation.text or "").strip()
    label = label or fallback
    if not label:
        raise ValueError(f"{sample_id}: InkML sample has no label annotation")

    polylines: list[tuple[tuple[float, float], ...]] = []
    for trace in root.iter(f"{_INKML_NS}trace"):
        points: list[tuple[float, float]] = []
        for token in (trace.text or "").split(","):
            parts = token.split()
            if len(parts) < 2:
                continue
            points.append((float(parts[0]), float(parts[1])))
        if points:
            polylines.append(tuple(points))
    if not polylines:
        raise ValueError(f"{sample_id}: InkML sample has no trace points")
    return MathWritingSample(sample_id, label, tuple(polylines))


def sample_to_page(sample: MathWritingSample, index: int) -> CorpusPage:
    """Fit one expression onto a standard page; strokes keep drawn order."""
    xs = [x for line in sample.polylines for x, _ in line]
    ys = [y for line in sample.polylines for _, y in line]
    min_x, max_x, min_y, max_y = min(xs), max(xs), min(ys), max(ys)
    scale = min(_BOX_W / max(max_x - min_x, 1e-9), _BOX_H / max(max_y - min_y, 1e-9))
    fitted_w = (max_x - min_x) * scale
    fitted_h = (max_y - min_y) * scale
    offset_x = (PAGE_W - fitted_w) / 2
    offset_y = (PAGE_H - fitted_h) / 2

    tag = f"s2mw_{index:03d}"
    strokes = []
    for stroke_index, line in enumerate(sample.polylines):
        points = tuple(
            Point(
                round(offset_x + (x - min_x) * scale, 2),
                round(offset_y + (y - min_y) * scale, 2),
                t_ms=i * 8,
            )
            for i, (x, y) in enumerate(line)
        )
        strokes.append(Stroke(
            points=points,
            id=f"st_{tag}_{stroke_index:04d}",
            author=Author.USER,
            created_at_ms=BASE_EPOCH_MS + stroke_index * 400,
        ))

    page = Page(id=f"pg_{tag}", layers=[Layer(name="ink", id=f"ly_{tag}", strokes=strokes)])
    document = Document(id=f"doc_{tag}", created_at_ms=BASE_EPOCH_MS, pages=[page])
    return CorpusPage(
        document=document, page=page, kind="math", seed=index, jitter=0.0,
        expression=sample.label,
    )


def load_samples(data_dir: Path = DATA_DIR, limit: int = 12) -> list[MathWritingSample]:
    """Deterministically load the first ``limit`` samples by sorted filename."""
    files = sorted(data_dir.rglob("*.inkml"))
    if not files:
        raise FileNotFoundError(
            f"no .inkml files under {data_dir} — run "
            "`python -m research.harness.fetch_mathwriting` first"
        )
    samples = []
    for path in files:
        try:
            samples.append(parse_inkml(path.read_text(encoding="utf-8"), path.stem))
        except ValueError:
            continue  # unlabeled samples exist in some splits; skip them
        if len(samples) >= limit:
            break
    return samples


def generate_s2_corpus(
    n_pages: int = 12, data_dir: Path = DATA_DIR
) -> list[CorpusPage]:
    samples = load_samples(data_dir, limit=n_pages)
    return [sample_to_page(sample, index) for index, sample in enumerate(samples)]


# A handcrafted fixture so tests never need the download: "1+2" in four
# traces — the "1", the "+" as two crossing lines, and the "2".
FIXTURE_INKML = """\
<ink xmlns="http://www.w3.org/2003/InkML">
  <annotation type="label">1 + 2</annotation>
  <annotation type="normalizedLabel">1+2</annotation>
  <trace>10 40 0, 12 10 50, 12 42 100</trace>
  <trace>30 25 0, 50 25 40</trace>
  <trace>40 15 0, 40 35 40</trace>
  <trace>70 12 0, 85 10 30, 88 25 60, 70 40 90, 90 42 120</trace>
</ink>
"""
