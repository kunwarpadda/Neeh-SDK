"""S1 Quick, Draw! adapter: parsing, fitting, composition, task reuse."""
import pytest

from research.harness.quickdraw import (
    QuickDrawSketch,
    compose_sketch_page,
    iter_fixture_lines,
    parse_ndjson_line,
)
from research.harness.tasks import ALL_FAMILIES, generate_tasks


@pytest.fixture()
def pools():
    sketches = [parse_ndjson_line(line) for line in iter_fixture_lines()]
    # Composition needs at least three categories with a pool each.
    third = QuickDrawSketch(
        category="loop", key_id="fx3", recognized=True,
        polylines=((tuple((float(x), float(y)) for x, y in
                    [(0, 100), (100, 0), (200, 100), (100, 200), (0, 100)])),),
    )
    return {s.category: [s] for s in sketches + [third]}


def test_parse_simplified_and_raw_shapes():
    simplified = parse_ndjson_line(next(iter_fixture_lines()))
    assert simplified.category == "zigzag"
    assert simplified.polylines[0][0] == (0.0, 120.0)
    raw = parse_ndjson_line(
        '{"word":"line","key_id":"r1","recognized":true,'
        '"drawing":[[[10,20],[30,40],[0,16]]]}'
    )  # raw format carries a third per-stroke array (time); it is ignored
    assert raw.polylines == (((10.0, 30.0), (20.0, 40.0)),)


def test_compose_page_is_deterministic_and_truthful(pools):
    a = compose_sketch_page(0, seed=9, sketches_by_category=pools)
    b = compose_sketch_page(0, seed=9, sketches_by_category=pools)
    assert a.document.to_dict() == b.document.to_dict()
    assert a.kind == "shapes"

    on_page = {s.id for layer in a.page.layers for s in layer.strokes}
    quadrants = [s["quadrant"] for s in a.shapes]
    assert len(set(quadrants)) == len(quadrants)
    for shape in a.shapes:
        assert set(shape["stroke_ids"]) <= on_page
        assert shape["source"].startswith("quickdraw:")
        min_x, min_y, max_x, max_y = shape["bbox"]
        assert 0 <= min_x <= max_x <= 1000
        assert 0 <= min_y <= max_y <= 1414
        # Fitted uniformly into a 260-unit box.
        assert max(max_x - min_x, max_y - min_y) <= 261


def test_sketch_pages_drive_existing_task_families(pools):
    page = compose_sketch_page(1, seed=9, sketches_by_category=pools)
    tasks = generate_tasks([page], families=ALL_FAMILIES)
    families = {t.family for t in tasks}
    assert families == {"T1", "T2", "T3", "T4", "T5", "T6"}
    t1 = next(t for t in tasks if t.family == "T1")
    assert t1.truth in pools  # classification truth is the category name
