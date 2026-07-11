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
    encode_e7,
    encode_e7v,
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


def test_e7_golden_matches_e2_quantization():
    """E7's SVG paths live on E2's grid: same start cell, same endpoint."""
    encoded = encode_e7v(_tiny_page())
    assert encoded.version == "E7v/0.1.0"
    lines = encoded.text.splitlines()
    assert lines[0] == '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 181 256">'
    path = lines[1]
    assert path.startswith('<path id="st_gold_0001" d="M18 18l')
    d = path.split(' d="')[1].split('"')[0]
    deltas = [int(v) for v in d.partition("l")[2].split()]
    assert 18 + sum(deltas[0::2]) == 54  # same endpoint as the E2 golden test
    assert 18 + sum(deltas[1::2]) == 54
    assert encoded.image_png is None


def test_e7_hybrid_carries_raster_and_same_svg():
    pytest.importorskip("PIL")
    hybrid = encode_e7(_tiny_page())
    vector_only = encode_e7v(_tiny_page())
    assert hybrid.image_png[:8] == b"\x89PNG\r\n\x1a\n"
    assert hybrid.text == vector_only.text
    assert "attached as an image" in hybrid.legend
    assert "no image" in vector_only.legend


def test_e7_svg_is_smaller_than_e4():
    page = make_text_page(0, seed=3).page
    assert len(encode_e7v(page).text) < 0.6 * len(encode_e4(page).text)


def test_e7b_adds_page_unit_bboxes_beside_raster():
    pytest.importorskip("PIL")
    from research.harness.encoders import encode_e7b

    encoded = encode_e7b(_tiny_page())
    assert encoded.version == "E7b/0.2.0"
    assert encoded.image_png[:8] == b"\x89PNG\r\n\x1a\n"
    line = encoded.text.splitlines()[1]
    # Frame rule: geometry on the grid, echoable bboxes in page units.
    assert 'data-bbox="100 100 300 300"' in line
    assert 'd="M18 18l' in line
    assert "PAGE units" in encoded.legend


def test_rdp_keeps_corners_drops_straight_runs():
    from research.harness.encoders import _rdp

    # An L shape sampled densely: only the three defining points survive.
    leg1 = [(float(x), 0.0) for x in range(0, 101, 10)]
    leg2 = [(100.0, float(y)) for y in range(10, 101, 10)]
    out = _rdp(leg1 + leg2, 1.0)
    assert out == [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)]


def test_e8_family_shrinks_raster_and_text():
    pytest.importorskip("PIL")
    from research.harness.encoders import encode_e7b, encode_e7v, encode_e7vs, encode_e8, encode_e8q, encode_e8s

    page = make_text_page(0, seed=3).page
    full = encode_e7b(page)
    half, quarter, cheap = encode_e8(page), encode_e8q(page), encode_e8s(page)
    # Raster shrinks monotonically; the SVG side is unchanged until E8s.
    assert len(quarter.image_png) < len(half.image_png) < len(full.image_png)
    assert half.text == full.text and quarter.text == full.text
    assert len(cheap.text) < len(quarter.text)
    assert "reduced-resolution" in half.legend
    # E7vS: same strokes as E7v, fewer characters, endpoints intact.
    plain, simplified = encode_e7v(page), encode_e7vs(page)
    assert simplified.text.count("<path ") == plain.text.count("<path ")
    assert len(simplified.text) < len(plain.text)


def test_embedded_coding_sections_and_monotone_error():
    from research.harness.embedded import build_embedded, rate_distortion_curve
    from research.harness.encoders import _page_strokes

    page = make_shape_page(0, seed=3).page
    embedded = build_embedded(page)
    assert len(embedded.coarse) == sum(1 for _ in _page_strokes(page))
    assert embedded.text_at(0).startswith("<svg ")
    curve = rate_distortion_curve(page)
    chars = [c for c, _ in curve]
    errs = [e for _, e in curve]
    assert chars == sorted(chars)  # more sections, more characters
    assert all(a >= b - 1e-9 for a, b in zip(errs, errs[1:]))  # error never rises


def test_e7vb_differs_only_in_legend():
    from research.harness.encoders import encode_e7v, encode_e7vb

    page = make_shape_page(0, seed=3).page
    a, b = encode_e7v(page), encode_e7vb(page)
    assert a.text == b.text and b.image_png is None
    assert a.legend != b.legend
    assert b.version == "E7vB/0.1.0"


def test_e7v_grid_resolution_arms():
    from research.harness.encoders import encode_e7v128, encode_e7v512

    page = make_text_page(0, seed=3).page
    low, mid, high = (encode_e7v128(page), encode_e7v(page), encode_e7v512(page))
    assert 'viewBox="0 0 91 128"' in low.text
    assert 'viewBox="0 0 362 512"' in high.text
    # Higher resolution costs more characters; ids survive at every level.
    assert len(low.text) < len(mid.text) < len(high.text)
    assert low.text.count("<path ") == mid.text.count("<path ") == high.text.count("<path ")


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
