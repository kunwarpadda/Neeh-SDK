"""Deterministic ink reducers stay exact and bounded as pages grow."""
from __future__ import annotations

import json

from neeh import Canvas
from neeh.agents import InkAgentInterface, analyze_ink, build_observation_workspace
from neeh.document import Document, Page
from neeh.ink import Point, Stroke


def _stroke(stroke_id: str, x: float, y: float, created_at_ms: int) -> Stroke:
    return Stroke(
        id=stroke_id,
        created_at_ms=created_at_ms,
        points=(Point(x, y, 0, 0.4), Point(x + 12, y + 4, 100, 0.8)),
    )


def _seg(stroke_id: str, x1: float, y1: float, x2: float, y2: float, t: int = 1_000) -> Stroke:
    return Stroke(
        id=stroke_id,
        created_at_ms=t,
        points=(Point(x1, y1, 0, 0.6), Point(x2, y2, 100, 0.6)),
    )


def test_latest_mark_reduces_320_strokes_to_one_constant_size_record():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    for index in range(320):
        layer.add(_stroke(f"st_{index}", index % 900, 100 + index, 10_000 + index))

    result = analyze_ink(canvas, "latest_mark")

    assert result["source_stroke_count"] == 320
    assert result["latest"]["id"] == "st_319"
    assert result["latest"]["vertical_half"] == "upper"
    assert len(json.dumps(result, separators=(",", ":"))) < 500


def test_creation_order_and_dynamics_use_only_requested_ids():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_stroke("st_late", 300, 800, 2_000))
    layer.add(_stroke("st_early", 100, 100, 1_000))

    order = analyze_ink(
        canvas, "creation_order", stroke_ids=["st_late", "st_early"]
    )
    dynamics = analyze_ink(canvas, "stroke_dynamics", stroke_ids=["st_late"])

    assert [item["id"] for item in order["order"]] == ["st_early", "st_late"]
    assert dynamics["strokes"][0]["id"] == "st_late"
    assert dynamics["strokes"][0]["direction"] == "right"


def test_iai_analyzer_is_budgeted_and_telemetried():
    canvas = Canvas()
    canvas.page.layers[0].add(_stroke("st_latest", 100, 900, 1_000))
    interface = InkAgentInterface(canvas)

    result = interface.call("analyze_ink", {"operation": "latest_mark"})

    assert result["latest"]["id"] == "st_latest"
    assert interface.telemetry()["analyzer_queries"] == 1


def test_latest_mark_intent_is_reduced_before_the_model_sees_the_workspace():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    for index in range(320):
        layer.add(_stroke(f"st_{index}", index % 900, 100 + index, 10_000 + index))

    workspace = build_observation_workspace(
        canvas,
        "Is the most recent mark in the upper or lower half?",
    )

    assert workspace["analysis"]["operation"] == "latest_mark"
    assert workspace["analysis"]["latest"]["id"] == "st_319"
    assert workspace["bootstrap_chars"] <= workspace["budget"]["max_bootstrap_chars"]


def test_measurements_and_inferences_are_tagged_distinctly():
    canvas = Canvas()
    canvas.page.layers[0].add(_stroke("st_1", 100, 100, 1_000))

    measurement = analyze_ink(canvas, "latest_mark")
    inference = analyze_ink(canvas, "cross_out_candidates")

    assert measurement["claim_type"] == "measurement"
    assert inference["claim_type"] == "inference"


def test_endpoints_returns_exact_start_and_end_coordinates():
    canvas = Canvas()
    canvas.page.layers[0].add(_seg("st_arrow", 100, 100, 260, 300))

    result = analyze_ink(canvas, "endpoints", stroke_ids=["st_arrow"])

    stroke = result["strokes"][0]
    assert stroke["start"] == [100.0, 100.0]
    assert stroke["end"] == [260.0, 300.0]
    assert stroke["start_half"] == {"vertical": "upper", "horizontal": "left"}
    assert stroke["displacement"] == round((160**2 + 200**2) ** 0.5, 2)


def test_containment_splits_fully_inside_from_partial():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_seg("st_inside", 50, 50, 60, 60))
    layer.add(_seg("st_straddle", 190, 190, 260, 260))

    result = analyze_ink(canvas, "containment", region=[0, 0, 200, 200])

    assert [item["id"] for item in result["contained"]] == ["st_inside"]
    assert [item["id"] for item in result["partial"]] == ["st_straddle"]


def test_spatial_collision_reports_bbox_overlap_pairs():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_seg("st_a", 100, 100, 150, 150))
    layer.add(_seg("st_b", 140, 140, 200, 200))
    layer.add(_seg("st_far", 500, 500, 510, 510))

    result = analyze_ink(canvas, "spatial_collision")

    assert result["pair_count"] == 1
    pair = result["collisions"][0]
    assert {pair["a"], pair["b"]} == {"st_a", "st_b"}
    assert pair["overlap"] == [140.0, 140.0, 150.0, 150.0]


def test_intersection_is_exact_and_stricter_than_bbox_collision():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    # An X: these two segments truly cross at (150, 150).
    layer.add(_seg("st_x1", 100, 100, 200, 200))
    layer.add(_seg("st_x2", 100, 200, 200, 100))
    # Parallel diagonals: bboxes overlap but the paths never cross.
    layer.add(_seg("st_p1", 100, 400, 150, 450))
    layer.add(_seg("st_p2", 120, 400, 170, 450))

    crossings = analyze_ink(canvas, "intersection")
    collisions = analyze_ink(canvas, "spatial_collision")

    crossing_pairs = {frozenset((c["a"], c["b"])) for c in crossings["intersections"]}
    collision_pairs = {frozenset((c["a"], c["b"])) for c in collisions["collisions"]}

    assert frozenset(("st_x1", "st_x2")) in crossing_pairs
    assert crossings["intersections"][0]["at"] == [150.0, 150.0]
    # The parallel pair collides by bbox but does not truly intersect.
    assert frozenset(("st_p1", "st_p2")) in collision_pairs
    assert frozenset(("st_p1", "st_p2")) not in crossing_pairs


def test_connector_candidate_links_two_distinct_objects_with_confidence():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_seg("obj_left", 100, 100, 120, 120))
    layer.add(_seg("obj_right", 300, 100, 320, 120))
    layer.add(_seg("st_link", 121, 110, 299, 110))

    result = analyze_ink(canvas, "connector_candidates")

    assert result["claim_type"] == "inference"
    ids = {item["id"] for item in result["candidates"]}
    assert "st_link" in ids
    link = next(item for item in result["candidates"] if item["id"] == "st_link")
    assert {link["from_id"], link["to_id"]} == {"obj_left", "obj_right"}
    assert 0.0 < link["confidence"] <= 1.0
    assert "start_gap" in link["provenance"] and "margin" in link["provenance"]


def test_grouping_candidates_find_separate_spatial_clusters():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    for i in range(3):
        layer.add(_seg(f"near_{i}", 100 + 10 * i, 100 + 5 * i, 108 + 10 * i, 106 + 5 * i))
    for i in range(2):
        layer.add(_seg(f"far_{i}", 600 + 10 * i, 700 + 5 * i, 608 + 10 * i, 706 + 5 * i))

    result = analyze_ink(canvas, "grouping_candidates")

    assert result["group_count"] == 2
    sizes = sorted(group["size"] for group in result["groups"])
    assert sizes == [2, 3]
    for group in result["groups"]:
        assert 0.0 <= group["confidence"] <= 1.0
        assert group["provenance"]["measured_from"] == "bbox proximity"


def _line(stroke_id, x1, y1, x2, y2, t):
    return Stroke(
        id=stroke_id,
        created_at_ms=t,
        points=(Point(x1, y1, 0, 0.6), Point(x2, y2, 100, 0.6)),
    )


def test_orientation_reads_horizontal_writing_left_to_right():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    # Five short marks in a horizontal row, drawn left to right over time.
    for i in range(5):
        layer.add(_line(f"h_{i}", 100 + 40 * i, 300, 128 + 40 * i, 302, 1_000 + i))

    result = analyze_ink(canvas, "orientation", stroke_ids=[s.id for s in layer.strokes])

    assert result["claim_type"] == "measurement"
    o = result["orientation"]
    assert abs(o["angle_deg"]) < 5 or abs(o["angle_deg"] - 180) < 5
    assert o["axis"] == "horizontal"
    assert o["reading_direction"] == "right"
    assert o["axis_ratio"] > 3  # clearly line-like


def test_orientation_reads_vertical_writing_top_to_bottom():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    # Marks stacked top to bottom (y grows down), drawn over time downward.
    for i in range(5):
        layer.add(_line(f"v_{i}", 400, 100 + 40 * i, 402, 128 + 40 * i, 1_000 + i))

    result = analyze_ink(canvas, "orientation", stroke_ids=[s.id for s in layer.strokes])
    o = result["orientation"]

    assert abs(o["angle_deg"] - 90) < 5
    assert o["axis"] == "vertical"
    assert o["reading_direction"] == "down"


def test_orientation_distinguishes_rising_from_falling_diagonals():
    # Rising on screen: x grows, y shrinks (up-right).
    rising = Canvas()
    for i in range(5):
        rising.page.layers[0].add(
            _line(f"r_{i}", 100 + 40 * i, 500 - 40 * i, 128 + 40 * i, 472 - 40 * i, 1_000 + i)
        )
    ro = analyze_ink(rising, "orientation",
                     stroke_ids=[s.id for s in rising.page.layers[0].strokes])["orientation"]
    assert abs(ro["angle_deg"] - 45) < 8
    assert ro["axis"] == "diagonal-rising"
    assert ro["reading_direction"] == "up-right"

    # Falling on screen: x grows, y grows (down-right).
    falling = Canvas()
    for i in range(5):
        falling.page.layers[0].add(
            _line(f"f_{i}", 100 + 40 * i, 100 + 40 * i, 128 + 40 * i, 128 + 40 * i, 1_000 + i)
        )
    fo = analyze_ink(falling, "orientation",
                     stroke_ids=[s.id for s in falling.page.layers[0].strokes])["orientation"]
    assert abs(fo["angle_deg"] - 135) < 8
    assert fo["axis"] == "diagonal-falling"
    assert fo["reading_direction"] == "down-right"


def test_orientation_of_a_dot_has_no_angle():
    canvas = Canvas()
    canvas.page.layers[0].add(
        Stroke(id="dot", created_at_ms=1, points=(Point(200, 200, 0, 0.5),))
    )
    result = analyze_ink(canvas, "orientation", stroke_ids=["dot"])
    assert result["orientation"]["angle_deg"] is None
    assert result["orientation"]["axis"] is None


def test_orientation_is_bounded_and_per_stroke_capped():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    for i in range(40):
        layer.add(_line(f"s_{i}", 100 + 5 * i, 300, 128 + 5 * i, 302, 1_000 + i))
    result = analyze_ink(canvas, "orientation",
                         stroke_ids=[s.id for s in layer.strokes], limit=8)
    assert len(result["strokes"]) == 8
    assert result["truncated"] is True
    assert result["orientation"]["stroke_count"] == 40  # aggregate sees all


def _box(prefix: str, cx: float, cy: float, half: float = 15, t: int = 1_000):
    """A hand-drawn box as four touching (not overlapping) edge strokes --
    real strokes are rarely one continuous outline."""
    x0, y0, x1, y1 = cx - half, cy - half, cx + half, cy + half
    return [
        _seg(f"{prefix}_top", x0, y0, x1, y0, t),
        _seg(f"{prefix}_right", x1, y0, x1, y1, t),
        _seg(f"{prefix}_bottom", x1, y1, x0, y1, t),
        _seg(f"{prefix}_left", x0, y1, x0, y0, t),
    ]


def test_grouping_merges_touching_multi_stroke_marks_before_clustering():
    # A box drawn as four separate touching edges, plus a two-stroke label
    # just beside it (near but not touching) -- both belong to the same
    # semantic object and should end up in one group. A distant, unrelated
    # mark must stay out of it.
    canvas = Canvas()
    layer = canvas.page.layers[0]
    for stroke in _box("box", 200, 200):
        layer.add(stroke)
    layer.add(_seg("label_a", 240, 195, 260, 195))
    layer.add(_seg("label_b", 240, 205, 258, 205))
    layer.add(_seg("far_mark", 900, 900, 920, 920))

    result = analyze_ink(canvas, "grouping_candidates")

    assert result["group_count"] == 1
    group = result["groups"][0]
    assert group["size"] == 6
    assert set(group["member_ids"]) == {
        "box_top", "box_right", "box_bottom", "box_left", "label_a", "label_b",
    }


def test_grouping_margin_scales_with_content_not_raw_page_size():
    # Real device pages are often just the tablet's full screen resolution
    # (e.g. 3122x4413), unrelated to how much of it the ink occupies. Two
    # boxes separated by a gap that is small relative to a big page but large
    # relative to their own content must still end up in separate groups.
    canvas = Canvas(Document(pages=[Page(width=3200, height=4400)]))
    layer = canvas.page.layers[0]
    for stroke in _box("left", 200, 200, half=15):
        layer.add(stroke)
    layer.add(_seg("left_label", 216, 195, 236, 195))
    for stroke in _box("right", 500, 200, half=15):
        layer.add(stroke)
    layer.add(_seg("right_label", 516, 195, 536, 195))

    result = analyze_ink(canvas, "grouping_candidates")

    assert result["group_count"] == 2
    sizes = sorted(group["size"] for group in result["groups"])
    assert sizes == [5, 5]


def test_connector_margin_is_not_starved_by_elongated_content():
    # A long, thin connector scene (two small boxes joined by a wide, flat
    # link) has a small minimum content dimension; the margin must scale off
    # the content's overall size, not its narrowest side, or a real link can
    # fall outside its own proximity margin.
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_seg("obj_left", 100, 100, 120, 120))
    layer.add(_seg("obj_right", 300, 100, 320, 120))
    layer.add(_seg("st_link", 121, 110, 299, 110))

    result = analyze_ink(canvas, "connector_candidates")

    ids = {item["id"] for item in result["candidates"]}
    assert "st_link" in ids


def test_recorded_groups_report_exact_membership_from_the_log():
    canvas = Canvas()
    a = canvas.add_stroke([(100, 100), (140, 100)])
    b = canvas.add_stroke([(600, 900), (640, 900)])  # far apart on purpose
    canvas.add_stroke([(300, 500), (340, 500)])
    group_id = canvas.group([a.id, b.id], label="scattered")

    result = analyze_ink(canvas, "recorded_groups")

    assert result["claim_type"] == "measurement"
    assert result["group_count"] == 1
    group = result["groups"][0]
    assert group["group_id"] == group_id
    # Exact membership even though the members are spatially far apart --
    # this is log truth, not a proximity guess.
    assert group["member_ids"] == [a.id, b.id]
    assert group["label"] == "scattered"
    assert result["matched_stroke_count"] == 2


def test_recorded_groups_empty_without_group_events():
    canvas = Canvas()
    canvas.add_stroke([(100, 100), (140, 100)])
    result = analyze_ink(canvas, "recorded_groups")
    assert result["group_count"] == 0
    assert result["groups"] == []


def test_recorded_groups_never_silently_truncate_membership():
    canvas = Canvas()
    members = [
        canvas.add_stroke([(50 + 30 * i, 100), (70 + 30 * i, 100)]).id
        for i in range(30)
    ]
    canvas.group(members, label="big")

    result = analyze_ink(canvas, "recorded_groups", limit=6)

    group = result["groups"][0]
    # `limit` bounds groups, not members: even at limit=6 the member list is
    # cut only at the 24-id cap, and the cut is declared, never silent.
    assert len(group["member_ids"]) == 24
    assert group["member_ids_truncated"] is True
    assert group["size"] == 30
