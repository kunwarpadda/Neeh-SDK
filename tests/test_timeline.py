"""Ink Moment Retrieval timeline, ranking, inspection, and promotion tests."""
from __future__ import annotations

from neeh import Canvas
import pytest

from neeh.agents import (
    InkAgentInterface,
    PerceptionBudget,
    build_ink_timeline,
    find_ink_moments,
    inspect_ink_moment,
)
from neeh.ink import Point, Stroke


def _stroke(stroke_id: str, xy, created_at_ms: int, duration_ms: int = 200) -> Stroke:
    points = tuple(
        Point(x, y, t_ms=round(index * duration_ms / max(len(xy) - 1, 1)), pressure=0.6 + index * 0.1)
        for index, (x, y) in enumerate(xy)
    )
    return Stroke(points=points, id=stroke_id, created_at_ms=created_at_ms)


def _timeline_scene() -> Canvas:
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_stroke("st_box", [(100, 100), (260, 100), (260, 240), (100, 240), (100, 100)], 1_000, 500))
    layer.add(_stroke("st_label", [(130, 160), (220, 160)], 1_800))
    layer.add(_stroke("st_cross", [(80, 80), (280, 260)], 5_000))
    return canvas


def test_timeline_groups_spatially_temporal_strokes_and_preserves_features():
    timeline = build_ink_timeline(_timeline_scene().page)

    assert timeline["schema"] == "ink-timeline/v1"
    assert timeline["history_complete"] is False
    assert timeline["moment_count"] == 2
    first, correction = timeline["moments"]
    assert first["stroke_ids"] == ["st_box", "st_label"]
    assert first["strokes"][1]["pause_before_ms"] == 300
    assert correction["event_types"] == ["creation", "overlay", "cross_out_candidate"]
    assert correction["affected_prior_ids"] == ["st_box"]
    assert correction["strokes"][0]["direction"] == "down-right"


def test_query_ranking_finds_cross_out_evidence_and_inspection_replays_it():
    canvas = _timeline_scene()
    timeline = build_ink_timeline(canvas.page)
    ranked = find_ink_moments(timeline, "what was crossed out?", limit=1)

    assert ranked[0]["stroke_ids"] == ["st_cross"]
    assert "cross-out-evidence" in ranked[0]["reasons"]
    moment_id = ranked[0]["id"]
    diff = inspect_ink_moment(canvas.page, timeline, moment_id, view="diff")
    replay = inspect_ink_moment(canvas.page, timeline, moment_id, view="replay")
    assert diff["affected_prior_ids"] == ["st_box"]
    assert replay["steps"][0]["direction"] == "down-right"

    both = find_ink_moments(timeline, "show the creation order", limit=2)
    assert len(both) == 2


def test_iai_moment_tools_promote_a_bounded_working_set_and_report_telemetry():
    interface = InkAgentInterface(_timeline_scene(), "what was crossed out?")

    found = interface.call("find_ink_moments", {"query": "crossed out", "limit": 1})
    moment_id = found["moments"][0]["id"]
    replay = interface.call("inspect_ink_moment", {"moment_id": moment_id, "view": "replay"})
    telemetry = interface.telemetry()

    assert replay["steps"]
    assert interface.workspace()["working_set"]["moment_ids"] == [moment_id]
    assert "st_cross" in interface.workspace()["working_set"]["stroke_ids"]
    assert telemetry["moment_queries"] == 1
    assert telemetry["replay_steps"] == 1


def test_replay_budget_is_cumulative_across_moment_inspections():
    canvas = _timeline_scene()
    interface = InkAgentInterface(
        canvas,
        budget=PerceptionBudget(max_actions=3, max_replay_steps=1),
    )
    moment_id = interface.call(
        "find_ink_moments", {"query": "cross out", "limit": 1}
    )["moments"][0]["id"]
    interface.call("inspect_ink_moment", {"moment_id": moment_id, "view": "replay"})

    with pytest.raises(ValueError, match="replay-step budget"):
        interface.call("inspect_ink_moment", {"moment_id": moment_id, "view": "replay"})
