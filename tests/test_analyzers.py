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
