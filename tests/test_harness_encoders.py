"""Encoding arms: determinism, structure, and golden behavior."""
import json

import pytest

from neeh.document import Document, Layer, Page
from neeh.ink import Point, Stroke
from research.harness.corpus_s0 import make_shape_page, make_text_page
from research.harness.encoders import (
    ENCODERS,
    M1_ARMS,
    _resample,
    encode_ctrl,
    encode_e1b,
    encode_e2,
    encode_e4,
)


def _tiny_page() -> Page:
    stroke = Stroke(
        points=(Point(100, 100, 0), Point(300, 100, 40), Point(300, 300, 80)),
        id="st_gold_0001",
        created_at_ms=1_700_000_000_000,
    )
    layer = Layer(name="ink", id="ly_gold", strokes=[stroke])
    page = Page(id="pg_gold", layers=[layer])
    Document(id="doc_gold", created_at_ms=1_700_000_000_000, pages=[page])
    return page


def test_resample_keeps_endpoints_and_spacing():
    points = [(0.0, 0.0), (100.0, 0.0)]
    out = _resample(points, 10.0)
    assert out[0] == (0.0, 0.0) and out[-1] == (100.0, 0.0)
    assert len(out) == 11  # 0, 10, ..., 100


def test_e2_golden():
    encoded = encode_e2(_tiny_page())
    assert encoded.version == "E2/0.1.0"
    lines = encoded.text.splitlines()
    assert lines[0] == "page 181 256"
    head, _, body = lines[1].partition(" : ")
    assert head == "st_gold_0001 user pen"
    values = [int(v) for v in body.split()]
    # Absolute start at grid (18, 18); offsets sum to the end point (54, 54).
    assert values[0] == 18 and values[1] == 18
    xs = values[0] + sum(values[2::2])
    ys = values[1] + sum(values[3::2])
    assert (xs, ys) == (54, 54)


def test_e4_golden():
    encoded = encode_e4(_tiny_page())
    assert encoded.text.startswith('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1414">')
    assert 'id="st_gold_0001"' in encoded.text
    assert 'd="M 100 100 L' in encoded.text
    assert encoded.text.rstrip().endswith("</svg>")
    assert encoded.image_png is None


def test_e1b_is_valid_icf_json_without_image():
    encoded = encode_e1b(_tiny_page())
    payload = json.loads(encoded.text)
    assert payload["schema"] == "ink-context/v0"
    assert payload["vector"]["strokes"][0]["id"] == "st_gold_0001"
    assert encoded.image_png is None


def test_raster_arms_produce_png():
    pytest.importorskip("PIL")
    for arm in ("E0", "E1a"):
        encoded = ENCODERS[arm](_tiny_page())
        assert encoded.image_png[:8] == b"\x89PNG\r\n\x1a\n"
    assert ENCODERS["E0"](_tiny_page()).text is None


def test_ctrl_arm_is_empty():
    encoded = encode_ctrl(_tiny_page())
    assert encoded.text is None and encoded.image_png is None


def test_encoders_are_deterministic_on_corpus_pages():
    pytest.importorskip("PIL")
    for page in (make_text_page(0, seed=3), make_shape_page(0, seed=3)):
        for arm in M1_ARMS:
            first = ENCODERS[arm](page.page)
            second = ENCODERS[arm](page.page)
            assert first.text == second.text
            assert first.image_png == second.image_png


def test_e2_and_e4_share_resampling_budget():
    """E2 vs E4 must differ only in syntax: same points after resampling."""
    page = make_shape_page(1, seed=3).page
    e2_points = sum(
        (len(line.partition(" : ")[2].split()) - 2) // 2 + 1
        for line in encode_e2(page).text.splitlines()[1:]
    )
    e4_points = sum(
        path.count(" L ") + 1
        for path in encode_e4(page).text.splitlines()
        if path.startswith("<path")
    )
    assert e2_points == e4_points
