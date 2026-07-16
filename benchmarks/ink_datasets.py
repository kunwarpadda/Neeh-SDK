"""Real-ink ingestion for the Move 3 grounding study.

MathWriting (Gervais et al., 2024) ships online handwriting as InkML whose
traces carry per-point millisecond timing::

    <trace id="0">901.72 479.26 0.0, 900.52 482.87 12.0, ...</trace>

That timing is exactly the signal the grounding study is about, so ingestion
preserves it: each trace becomes one neeh stroke whose ``created_at_ms`` is the
trace's first sample time (rebased onto a caller-supplied epoch) and whose
points carry integer ``t_ms`` offsets from that instant. Geometry is scale-fit
into a caller-supplied page region, preserving aspect ratio, so task builders
can place one sample per page or compose several into a dense page.

The archives themselves are not vendored. Download either one::

    https://storage.googleapis.com/mathwriting_data/mathwriting-2024-excerpt.tgz
    https://storage.googleapis.com/mathwriting_data/mathwriting-2024.tgz

and point ``iter_mathwriting`` at the extracted root.
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from neeh import Canvas  # noqa: E402
from neeh.ink import Author, Stroke, StrokeStyle  # noqa: E402

_INKML_NS = "{http://www.w3.org/2003/InkML}"

# One raw ink sample: strokes of (x, y, t_ms) in the source coordinate frame,
# times session-global as recorded on the device.
RawStroke = tuple[tuple[float, float, float], ...]


class InkDatasetError(ValueError):
    """A dataset file could not be parsed into timed strokes."""


@dataclass(frozen=True)
class InkSample:
    sample_id: str
    label: str
    normalized_label: str
    creation_method: str          # "human" | "synthetic" | "" when unannotated
    strokes: tuple[RawStroke, ...]
    source: str

    @property
    def is_human(self) -> bool:
        return self.creation_method == "human"


def parse_mathwriting_inkml(path: Path) -> InkSample:
    """Parse one MathWriting InkML file, keeping per-point timing."""
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise InkDatasetError(f"{path}: not parseable InkML: {exc}") from exc

    annotations = {
        node.get("type", ""): (node.text or "").strip()
        for node in root.findall(f"{_INKML_NS}annotation")
    }
    strokes: list[RawStroke] = []
    for trace in root.findall(f"{_INKML_NS}trace"):
        points: list[tuple[float, float, float]] = []
        for token in (trace.text or "").split(","):
            fields = token.split()
            if not fields:
                continue
            if len(fields) != 3:
                raise InkDatasetError(
                    f"{path}: trace sample {token!r} is not 'x y t'"
                )
            x, y, t = (float(v) for v in fields)
            points.append((x, y, t))
        if points:
            strokes.append(tuple(points))
    if not strokes:
        raise InkDatasetError(f"{path}: no non-empty traces")
    return InkSample(
        sample_id=annotations.get("sampleId", path.stem),
        label=annotations.get("label", ""),
        normalized_label=annotations.get("normalizedLabel", ""),
        creation_method=annotations.get("inkCreationMethod", ""),
        strokes=tuple(strokes),
        source=str(path),
    )


def iter_mathwriting(
    root: Path,
    split: str = "train",
    *,
    human_only: bool = True,
    limit: Optional[int] = None,
) -> Iterator[InkSample]:
    """Yield samples from an extracted MathWriting root, deterministically.

    Files are visited in sorted name order so a (root, split, limit) triple
    always names the same sample set; ``human_only`` drops the synthetic split's
    machine-generated inks, which have no claim to real pen dynamics.
    """
    split_dir = root / split
    if not split_dir.is_dir():
        raise InkDatasetError(f"no such split directory: {split_dir}")
    yielded = 0
    for path in sorted(split_dir.glob("*.inkml")):
        if limit is not None and yielded >= limit:
            return
        sample = parse_mathwriting_inkml(path)
        if human_only and not sample.is_human:
            continue
        yield sample
        yielded += 1


def fit_strokes(
    strokes: Sequence[RawStroke],
    box: tuple[float, float, float, float],
) -> list[list[list[float]]]:
    """Scale-fit raw strokes into ``box`` (min_x, min_y, max_x, max_y).

    Aspect ratio is preserved and the ink is centered; times are rebased so the
    sample's first recorded instant is 0 and converted to integer milliseconds.
    Returns point lists shaped for ``Point.from_list`` ([x, y, t_ms]).
    """
    min_x0, min_y0, max_x0, max_y0 = box
    if not (max_x0 > min_x0 and max_y0 > min_y0):
        raise ValueError(f"degenerate target box {box!r}")
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    ts = [p[2] for s in strokes for p in s]
    if not xs:
        raise ValueError("no points to fit")
    ink_w = max(xs) - min(xs)
    ink_h = max(ys) - min(ys)
    t0 = min(ts)
    # A dot or a perfectly straight horizontal/vertical sample still has to
    # land inside the box, so degenerate extents scale as points.
    scale = min(
        (max_x0 - min_x0) / ink_w if ink_w > 0 else float("inf"),
        (max_y0 - min_y0) / ink_h if ink_h > 0 else float("inf"),
    )
    if scale == float("inf"):
        scale = 1.0
    off_x = min_x0 + ((max_x0 - min_x0) - ink_w * scale) / 2 - min(xs) * scale
    off_y = min_y0 + ((max_y0 - min_y0) - ink_h * scale) / 2 - min(ys) * scale
    fitted: list[list[list[float]]] = []
    for stroke in strokes:
        fitted.append(
            [
                [
                    round(x * scale + off_x, 2),
                    round(y * scale + off_y, 2),
                    max(0, int(round(t - t0))),
                ]
                for x, y, t in stroke
            ]
        )
    return fitted


def write_sample(
    canvas: Canvas,
    sample: InkSample,
    box: tuple[float, float, float, float],
    *,
    time_base_ms: int = 1_000_000,
    style: Optional[StrokeStyle] = None,
    author: Author = Author.USER,
) -> list[Stroke]:
    """Draw ``sample`` onto ``canvas`` inside ``box`` with real timing.

    Each trace becomes one stroke: ``created_at_ms`` is the trace's first
    sample instant rebased onto ``time_base_ms``, and every point's ``t_ms``
    is its offset from that instant — so temporal analyzers see the writer's
    actual pen-down order and pacing, not ingestion order.
    """
    fitted = fit_strokes(sample.strokes, box)
    strokes: list[Stroke] = []
    for points in fitted:
        stroke_t0 = points[0][2]
        rebased = [[x, y, max(0, t - stroke_t0)] for x, y, t in points]
        strokes.append(
            canvas.add_stroke(
                rebased,
                style=style,
                author=author,
                created_at_ms=time_base_ms + stroke_t0,
            )
        )
    return strokes
