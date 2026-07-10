"""ink-context/v1-draft builder: golden output, envelope invariants, and
byte-identity with the evaluated harness arm E7v/0.1.0."""
import pytest

from neeh import (
    Document,
    InkContextError,
    Page,
    build_ink_context_v1,
    build_ink_paths,
)
from neeh.document import Layer
from neeh.ink import Point, Stroke


def _page_with(strokes: list[Stroke], page_id: str = "pg_v1") -> Page:
    layer = Layer(name="ink", id="ly_v1", strokes=strokes)
    page = Page(id=page_id, layers=[layer])
    Document(id="doc_v1", created_at_ms=1_700_000_000_000, pages=[page])
    return page


def _stroke(stroke_id: str, points: list[tuple[float, float]], t0: int = 0) -> Stroke:
    return Stroke(
        id=stroke_id,
        points=tuple(Point(x, y, t0 + i * 10) for i, (x, y) in enumerate(points)),
        created_at_ms=1_700_000_000_000 + t0,
    )


def test_paths_golden():
    page = _page_with([_stroke("st_v1_0001", [(100, 100), (300, 100), (300, 300)])])
    svg = build_ink_paths(page)
    lines = svg.splitlines()
    assert lines[0] == '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 181 256">'
    assert lines[1].startswith('<path id="st_v1_0001" d="M18 18l')
    assert lines[-1] == "</svg>"
    # Offsets land on the same grid endpoint as the geometry: (300,300) -> (54,54).
    d = lines[1].split(' d="')[1].split('"')[0]
    deltas = [int(v) for v in d.partition("l")[2].split()]
    assert 18 + sum(deltas[0::2]) == 54
    assert 18 + sum(deltas[1::2]) == 54


def test_envelope_invariants_and_defaults():
    page = _page_with([
        _stroke("st_a", [(0, 0), (50, 50)]),
        _stroke("st_b", [(500, 500), (600, 600)], t0=100),
    ])
    payload = build_ink_context_v1(page)
    assert payload["schema"] == "ink-context/v1-draft"
    assert payload["raster"]["transport"] == "none"  # structure tier by default
    ink = payload["ink"]
    assert ink["encoding"] == "svg-paths/grid"
    assert ink["grid"] == [181, 256]
    assert ink["drawn_order"] is True
    assert ink["stroke_count"] == ink["included_stroke_count"] == 2
    assert ink["truncated"] is False
    assert ink["svg"].count("<path ") == 2
    assert 'id="st_a"' in ink["svg"] and 'id="st_b"' in ink["svg"]
    # Drawn order is the listing order.
    assert ink["svg"].index("st_a") < ink["svg"].index("st_b")


def test_truncation_keeps_newest_tail_with_accurate_counts():
    strokes = [_stroke(f"st_{i:02d}", [(10 * i, 10), (10 * i + 5, 15)], t0=i)
               for i in range(5)]
    payload = build_ink_context_v1(_page_with(strokes), max_strokes=2)
    ink = payload["ink"]
    assert ink["stroke_count"] == 5
    assert ink["included_stroke_count"] == 2
    assert ink["omitted_older_stroke_count"] == 3
    assert ink["truncated"] is True
    assert 'id="st_03"' in ink["svg"] and 'id="st_04"' in ink["svg"]
    assert 'id="st_00"' not in ink["svg"]


def test_region_selects_by_bbox_intersection():
    inside = _stroke("st_in", [(100, 100), (150, 150)])
    outside = _stroke("st_out", [(800, 1200), (900, 1300)], t0=50)
    payload = build_ink_context_v1(_page_with([inside, outside]),
                                   region=[0, 0, 400, 400])
    assert payload["ink"]["included_stroke_count"] == 1
    assert 'id="st_in"' in payload["ink"]["svg"]
    assert payload["ink"]["region"] == payload["raster"]["region"] == [0, 0, 400, 400]


def test_semantics_must_reference_included_strokes():
    page = _page_with([_stroke("st_x", [(10, 10), (20, 20)])])
    payload = build_ink_context_v1(
        page, semantics=[{"id": "rg_1", "kind": "word", "stroke_ids": ["st_x"]}]
    )
    assert payload["semantics"][0]["stroke_ids"] == ["st_x"]
    with pytest.raises(InkContextError):
        build_ink_context_v1(
            page, semantics=[{"id": "rg_1", "kind": "word", "stroke_ids": ["st_missing"]}]
        )


def test_raster_tier_and_validation():
    page = _page_with([_stroke("st_x", [(10, 10), (20, 20)])])
    perception = build_ink_context_v1(page, raster="attached_image")
    assert perception["raster"]["transport"] == "attached_image"
    with pytest.raises(InkContextError):
        build_ink_context_v1(page, raster="inline_base64")
    with pytest.raises(InkContextError):
        build_ink_paths(page, resample_grid_step=0)


def test_svg_matches_evaluated_harness_arm_byte_for_byte():
    """The SDK builder IS the evaluated encoding (E7v/0.1.0) — keep them locked."""
    harness = pytest.importorskip("research.harness.encoders")
    corpus = pytest.importorskip("research.harness.corpus_s0")
    for maker in (corpus.make_text_page, corpus.make_shape_page):
        page = maker(0, seed=7).page
        assert build_ink_paths(page) == harness.encode_e7v(page).text
