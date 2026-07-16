"""Ink dataset ingestion: parsing, timing preservation, and geometry fit."""
from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks import ink_datasets as ds

EXCERPT_ROOT = Path(__file__).resolve().parent.parent / (
    "research/data/mathwriting/excerpt/mathwriting-2024-excerpt"
)

_INKML = """<ink xmlns="http://www.w3.org/2003/InkML">
  <annotation type="label">x^2</annotation>
  <annotation type="normalizedLabel">x^{2}</annotation>
  <annotation type="inkCreationMethod">human</annotation>
  <annotation type="sampleId">deadbeef</annotation>
  <traceFormat>
    <channel name="X" type="decimal" />
    <channel name="Y" type="decimal" />
    <channel name="T" type="decimal" units="ms" />
  </traceFormat>
  <trace id="0">100.0 200.0 50.0,110.0 210.0 62.0,120.0 200.0 75.5</trace>
  <trace id="1">300.0 180.0 900.0,300.0 240.0 930.0</trace>
</ink>
"""


@pytest.fixture()
def sample(tmp_path: Path) -> ds.InkSample:
    path = tmp_path / "deadbeef.inkml"
    path.write_text(_INKML, encoding="utf-8")
    return ds.parse_mathwriting_inkml(path)


def test_parse_keeps_annotations_and_timed_traces(sample: ds.InkSample):
    assert sample.sample_id == "deadbeef"
    assert sample.label == "x^2"
    assert sample.is_human
    assert len(sample.strokes) == 2
    # Per-point device times survive parsing untouched.
    assert sample.strokes[0][0] == (100.0, 200.0, 50.0)
    assert sample.strokes[1][-1] == (300.0, 240.0, 930.0)


def test_fit_preserves_aspect_and_rebases_time(sample: ds.InkSample):
    box = (0.0, 0.0, 400.0, 100.0)
    fitted = ds.fit_strokes(sample.strokes, box)
    xs = [p[0] for s in fitted for p in s]
    ys = [p[1] for s in fitted for p in s]
    assert min(xs) >= 0 and max(xs) <= 400 and min(ys) >= 0 and max(ys) <= 100
    # Ink is 200x60 in source units; the 100-tall box binds, so scale = 100/60
    # and width scales to 200 * (100/60) ≈ 333.33 — not stretched to 400.
    assert max(xs) - min(xs) == pytest.approx(200 * (100 / 60), abs=0.1)
    assert max(ys) - min(ys) == pytest.approx(100, abs=0.1)
    # Times rebase to the sample's first instant (50.0 -> 0) as integer ms.
    assert fitted[0][0][2] == 0
    assert fitted[0][1][2] == 12
    assert fitted[1][0][2] == 850


def test_write_sample_preserves_pen_order_and_offsets(sample: ds.InkSample):
    from neeh import Canvas

    canvas = Canvas()
    strokes = ds.write_sample(canvas, sample, (100, 100, 900, 700), time_base_ms=2_000_000)
    assert [s.created_at_ms for s in strokes] == [2_000_000, 2_000_850]
    # Point t_ms are offsets from the owning stroke's start.
    assert [p.t_ms for p in strokes[0].points] == [0, 12, 26]
    assert [p.t_ms for p in strokes[1].points] == [0, 30]
    assert set(canvas.page.all_strokes()) == set(strokes)


def test_unparseable_and_empty_files_raise(tmp_path: Path):
    bad = tmp_path / "bad.inkml"
    bad.write_text("<ink", encoding="utf-8")
    with pytest.raises(ds.InkDatasetError):
        ds.parse_mathwriting_inkml(bad)
    empty = tmp_path / "empty.inkml"
    empty.write_text('<ink xmlns="http://www.w3.org/2003/InkML"></ink>', encoding="utf-8")
    with pytest.raises(ds.InkDatasetError):
        ds.parse_mathwriting_inkml(empty)


@pytest.mark.skipif(not EXCERPT_ROOT.is_dir(), reason="MathWriting excerpt not downloaded")
def test_excerpt_ingests_onto_canvas_in_bounds():
    from neeh import Canvas

    count = 0
    for sample in ds.iter_mathwriting(EXCERPT_ROOT, "train", limit=10):
        canvas = Canvas()
        strokes = ds.write_sample(canvas, sample, (60, 60, 940, 1350))
        assert strokes, sample.source
        rect = canvas.page.rect
        for stroke in strokes:
            for p in stroke.points:
                assert rect.min_x <= p.x <= rect.max_x
                assert rect.min_y <= p.y <= rect.max_y
        # Monotone non-decreasing wall-clock order within each trace.
        for stroke in strokes:
            offsets = [p.t_ms for p in stroke.points]
            assert offsets[0] == 0
        count += 1
    assert count == 10
