"""Real-capture-shaped M3 integration across Neeh's public analysis layers."""
from __future__ import annotations

from pathlib import Path

from neeh.adapters.device_capture import load_device_capture
from neeh.agents.analyzers import analyze_ink
from neeh.agents.iai import InkAgentInterface, build_observation_workspace
from neeh.agents.reducers import reduce_ink
from neeh.agents.timeline import build_ink_timeline
from neeh.context import build_ink_context_v1, build_ink_index


FIXTURE = (
    Path(__file__).parents[1]
    / "spec"
    / "fixtures"
    / "neeh-device-capture-v1.session.json"
)


def test_device_capture_runs_through_the_analyzer_first_m3_path():
    imported = load_device_capture(FIXTURE)
    canvas = imported.canvas
    truth = imported.capture["ground_truth"]
    visible_ids = {
        stroke.id
        for page in imported.document.pages
        for stroke in page.all_strokes(visible_only=True)
    }

    assert imported.capture["app"]["name"] == "Device Recorder"
    assert visible_ids == set(truth["visible_stroke_ids"])
    assert not (set(truth["erased_stroke_ids"]) & visible_ids)
    assert len(imported.document.pages) == 2

    # Both pages remain usable by the stable context/index/timeline layers.
    for page_index, page in enumerate(imported.document.pages):
        canvas.goto_page(page_index)
        context = build_ink_context_v1(
            canvas, stroke_bboxes=True, stroke_hints=True
        )
        index = build_ink_index(canvas)
        timeline = build_ink_timeline(page, event_log=imported.event_log)

        assert context["schema"] == "ink-context/v1"
        assert context["ink"]["included_stroke_count"] == len(page.all_strokes())
        assert index["schema"] == "ink-index/v1"
        assert index["included_stroke_count"] == len(page.all_strokes())
        assert timeline["schema"] == "ink-timeline/v1"
        assert timeline["history_complete"] is True

    canvas.goto_page(0)
    timeline = build_ink_timeline(canvas.page, event_log=imported.event_log)
    erased_in_timeline = {
        stroke_id
        for moment in timeline["moments"]
        for stroke_id in moment["erased_ids"]
    }
    cross_out_targets = {
        stroke_id
        for moment in timeline["moments"]
        if "cross_out_candidate" in moment["event_types"]
        for stroke_id in moment["affected_prior_ids"]
    }
    assert erased_in_timeline == set(truth["erased_stroke_ids"])
    assert set(truth["cross_out_target_ids"]) <= cross_out_targets

    latest = analyze_ink(canvas, "latest_mark")
    revisions = reduce_ink(canvas, "revisions")
    assert latest["schema"] == "ink-analysis/v1"
    assert latest["deterministic"] is True
    assert latest["latest"]["id"] in truth["cross_out_mark_ids"]
    assert revisions["task"] == "revisions"
    assert revisions["history_complete"] is True
    assert any(
        revision["kind"] == "cross_out"
        and set(truth["cross_out_target_ids"]) <= set(revision["target_ids"])
        and revision["provenance"]
        for revision in revisions["revisions"]
    )

    task = "Which ink was revised or replaced?"
    workspace = build_observation_workspace(canvas, task, policy="active-index")
    interface = InkAgentInterface(canvas, task, policy="active-index")
    assert workspace["analysis"]["task"] == "revisions"
    assert workspace["analysis"]["deterministic"] is True
    assert interface.workspace()["analysis"]["task"] == "revisions"

    interface_latest = interface.call("analyze_ink", {"operation": "latest_mark"})
    detail = interface.call(
        "get_ink",
        {"detail": "bboxes", "stroke_ids": [interface_latest["latest"]["id"]]},
    )
    telemetry = interface.telemetry()
    assert detail["strokes"][0]["id"] == interface_latest["latest"]["id"]
    assert telemetry["perception_actions"] == 2
    assert telemetry["action_types"] == ["analyze_ink", "get_ink"]
    assert telemetry["analyzer_queries"] == 1

    erased_id = truth["erased_stroke_ids"][0]
    restored_id = truth["restored_stroke_ids"][0]
    assert imported.event_log.recover(erased_id).id == erased_id
    assert canvas.page.find(restored_id) is not None
    assert any(restored_id in event.removed_ids for event in imported.event_log.events)
    assert any(restored_id in event.added_ids for event in imported.event_log.events)
