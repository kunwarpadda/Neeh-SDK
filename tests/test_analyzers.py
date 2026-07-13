"""Deterministic ink reducers stay exact and bounded as pages grow."""
from __future__ import annotations

import json

from neeh import Canvas
from neeh.agents import InkAgentInterface, analyze_ink, build_observation_workspace
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
