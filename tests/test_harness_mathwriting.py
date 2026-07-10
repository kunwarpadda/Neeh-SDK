"""S2 MathWriting adapter: InkML parsing, page fitting, task wiring, raw CER."""
import pytest

from research.harness.mathwriting import (
    FIXTURE_INKML,
    parse_inkml,
    sample_to_page,
)
from research.harness.scorers import score_cer_raw
from research.harness.tasks import generate_tasks


def test_parse_inkml_prefers_normalized_label():
    sample = parse_inkml(FIXTURE_INKML, "fx")
    assert sample.label == "1+2"  # normalizedLabel wins over label
    assert len(sample.polylines) == 4
    assert sample.polylines[0][0] == (10.0, 40.0)  # t coordinate dropped


def test_parse_inkml_requires_label_and_ink():
    with pytest.raises(ValueError):
        parse_inkml('<ink xmlns="http://www.w3.org/2003/InkML"><trace>1 2 0</trace></ink>')
    with pytest.raises(ValueError):
        parse_inkml(
            '<ink xmlns="http://www.w3.org/2003/InkML">'
            '<annotation type="label">x</annotation></ink>'
        )


def test_sample_to_page_fits_and_preserves_order():
    page = sample_to_page(parse_inkml(FIXTURE_INKML, "fx"), 0)
    assert page.kind == "math"
    assert page.expression == "1+2"
    strokes = page.page.layers[0].strokes
    assert [s.id for s in strokes] == [f"st_s2mw_000_{i:04d}" for i in range(4)]
    xs = [p.x for s in strokes for p in s.points]
    ys = [p.y for s in strokes for p in s.points]
    assert 0 <= min(xs) and max(xs) <= 1000
    assert 0 <= min(ys) and max(ys) <= 1414
    # Drawn order carries time (T6-compatible).
    assert strokes[0].created_at_ms < strokes[-1].created_at_ms
    # Deterministic rebuild.
    again = sample_to_page(parse_inkml(FIXTURE_INKML, "fx"), 0)
    assert again.document.to_dict() == page.document.to_dict()


def test_math_pages_generate_latex_transcription_tasks():
    page = sample_to_page(parse_inkml(FIXTURE_INKML, "fx"), 3)
    tasks = generate_tasks([page], families=("T1",))
    assert len(tasks) == 1
    task = tasks[0]
    assert task.scorer == "cer_raw"
    assert task.truth == "1+2"
    assert "LaTeX" in task.prompt


def test_cer_raw_preserves_latex_and_strips_fences():
    truth = "\\frac{a}{b}+C_1"
    assert score_cer_raw("\\frac{a}{b}+C_1", truth) == 1.0
    assert score_cer_raw("$\\frac{a}{b}+C_1$", truth) == 1.0
    assert score_cer_raw("\\(\\frac{a}{b}+C_1\\)", truth) == 1.0
    assert score_cer_raw("\\frac{a}{b} + C_1", truth) < 1.0  # spacing matters
    assert score_cer_raw("\\frac{A}{B}+c_1", truth) < 1.0  # case matters
    assert score_cer_raw("", truth) == 0.0
