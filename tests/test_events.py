"""The append-only event log keeps erased and replaced ink recoverable."""
from __future__ import annotations

import pytest

from neeh import Canvas
from neeh.ink import Author


def _canvas_with_stroke():
    canvas = Canvas()
    stroke = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    return canvas, stroke


def test_every_mutation_is_appended_in_order():
    canvas, stroke = _canvas_with_stroke()
    canvas.erase([stroke.id])
    canvas.undo()
    canvas.redo()

    kinds = [event.kind for event in canvas.events.events]
    assert kinds == ["add", "erase", "undo", "redo"]
    # Sequence numbers are monotonic and never reused.
    assert [event.seq for event in canvas.events.events] == [0, 1, 2, 3]


def test_undo_does_not_pop_the_log():
    canvas, stroke = _canvas_with_stroke()
    canvas.erase([stroke.id])
    before = len(canvas.events)
    canvas.undo()
    # Undo adds an event rather than removing the erase event.
    assert len(canvas.events) == before + 1


def test_replay_reconstructs_past_state_including_erased_ink():
    canvas, stroke = _canvas_with_stroke()
    canvas.erase([stroke.id])

    # After the erase the stroke is gone from the live document...
    assert canvas.events.replay().get(stroke.id) is None
    # ...but replaying to the add event still shows it.
    assert stroke.id in canvas.events.replay(to_seq=0)


def test_recover_returns_the_erased_stroke_snapshot():
    canvas, stroke = _canvas_with_stroke()
    canvas.erase([stroke.id])

    recovered = canvas.events.recover(stroke.id)
    assert recovered is not None
    assert recovered.id == stroke.id
    # A live stroke is not "recoverable" — it is simply present.
    live, live_stroke = _canvas_with_stroke()
    assert live.events.recover(live_stroke.id) is None


def test_diff_reports_added_removed_and_changed():
    canvas = Canvas()
    a = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    b = canvas.add_stroke([(30, 30), (40, 40)], author=Author.USER)
    canvas.erase([a.id])
    canvas.move(5, 5, stroke_ids=[b.id])

    diff = canvas.events.diff(from_seq=1)  # from just after b was added
    assert a.id in diff["removed_ids"]
    assert b.id in diff["changed_ids"]  # moved -> same id, different geometry


def test_snapshot_returns_stroke_state_at_a_point():
    canvas = Canvas()
    b = canvas.add_stroke([(30, 30), (40, 40)], author=Author.USER)
    canvas.move(100, 0, stroke_ids=[b.id])

    original = canvas.events.snapshot(b.id, at_seq=0)
    moved = canvas.events.snapshot(b.id)  # latest
    assert original.bbox.min_x == 30.0
    assert moved.bbox.min_x == 130.0


def test_event_log_serializes_to_dict():
    canvas, stroke = _canvas_with_stroke()
    payload = canvas.events.to_dict()
    assert payload["schema"] == "ink-eventlog/v1"
    assert payload["event_count"] == 1
    assert payload["events"][0]["kind"] == "add"
    assert stroke.id in payload["events"][0]["added_ids"]


def test_timeline_from_log_is_complete_and_keeps_erased_ink():
    from neeh.agents.timeline import build_ink_timeline

    canvas = Canvas()
    kept = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    gone = canvas.add_stroke([(30, 30), (40, 40)], author=Author.USER)
    canvas.erase([gone.id])

    # Without the log: only the surviving stroke, history incomplete.
    snapshot = build_ink_timeline(canvas.page)
    assert snapshot["history_complete"] is False
    ids_snapshot = {sid for moment in snapshot["moments"] for sid in moment["stroke_ids"]}
    assert ids_snapshot == {kept.id}

    # With the log: erased stroke reappears, tagged, and history is complete.
    complete = build_ink_timeline(canvas.page, event_log=canvas.events)
    assert complete["history_complete"] is True
    ids_complete = {sid for moment in complete["moments"] for sid in moment["stroke_ids"]}
    assert ids_complete == {kept.id, gone.id}
    erased = {sid for moment in complete["moments"] for sid in moment["erased_ids"]}
    assert erased == {gone.id}


def test_timeline_history_incomplete_when_ink_bypasses_the_log():
    from neeh.agents.timeline import build_ink_timeline

    canvas = Canvas()
    # Add straight to the layer, bypassing the logged Canvas API.
    canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    from neeh.ink import Point, Stroke
    canvas.page.layers[0].add(Stroke(id="bypass", created_at_ms=1, points=(Point(0, 0, 0), Point(5, 5, 10))))

    result = build_ink_timeline(canvas.page, event_log=canvas.events)
    # A visible stroke never passed through the log, so completeness is honest.
    assert result["history_complete"] is False


def test_event_log_snapshot_round_trip_preserves_replay_and_recover():
    from neeh.canvas import EventLog

    canvas, stroke = _canvas_with_stroke()
    canvas.erase([stroke.id])

    restored = EventLog.from_snapshot(canvas.events.to_snapshot())

    assert len(restored) == len(canvas.events)
    # The erased stroke's full geometry survives the round-trip.
    recovered = restored.recover(stroke.id)
    assert recovered is not None and recovered.id == stroke.id
    assert stroke.id in restored.replay(to_seq=0)
    assert restored.replay().get(stroke.id) is None


def test_canvas_session_bundle_round_trips_document_and_history(tmp_path):
    canvas = Canvas()
    kept = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    gone = canvas.add_stroke([(30, 30), (40, 40)], author=Author.USER)
    canvas.erase([gone.id])

    path = tmp_path / "session.json"
    canvas.save_session(path)
    restored = Canvas.load_session(path)

    # Live document preserved.
    live_ids = {s.id for layer in restored.page.layers for s in layer.strokes}
    assert live_ids == {kept.id}
    # Erased history preserved and still recoverable.
    assert restored.events.recover(gone.id) is not None
    assert len(restored.events) == len(canvas.events)


def test_uim_sidecar_persists_event_log(tmp_path):
    pytest.importorskip("uim")
    from neeh.adapters.uim import save_uim, load_uim, load_uim_events

    canvas = Canvas()
    kept = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    gone = canvas.add_stroke([(30, 30), (40, 40)], author=Author.USER)
    canvas.erase([gone.id])

    path = tmp_path / "doc.uim"
    save_uim(canvas.document, path, event_log=canvas.events)
    assert load_uim(path) is not None  # document body still valid UIM

    log = load_uim_events(path)
    assert log is not None
    assert log.recover(gone.id) is not None  # erased ink recovered from sidecar


def test_group_emits_event_and_membership_is_folded_from_log():
    canvas = Canvas()
    a = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    b = canvas.add_stroke([(30, 30), (40, 40)], author=Author.USER)

    group_id = canvas.group([a.id, b.id], label="equation")

    # A group event is appended (kind "group") with the membership as meta.
    group_events = [e for e in canvas.events.events if e.kind == "group"]
    assert len(group_events) == 1
    assert set(group_events[0].meta["member_ids"]) == {a.id, b.id}
    # Current membership is reconstructed from the log.
    groups = canvas.groups()
    assert group_id in groups
    assert groups[group_id]["label"] == "equation"


def test_ungroup_removes_membership_but_keeps_history():
    canvas = Canvas()
    a = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    b = canvas.add_stroke([(30, 30), (40, 40)], author=Author.USER)
    group_id = canvas.group([a.id, b.id])

    assert canvas.ungroup(group_id) is True
    assert group_id not in canvas.groups()  # no longer a current group
    # But the append-only log still records both the group and ungroup events.
    assert [e.kind for e in canvas.events.events if e.kind == "group"] == ["group", "group"]
    # Ungrouping a non-existent group is a no-op.
    assert canvas.ungroup("grp_missing") is False


def test_group_rejects_hidden_or_too_few_strokes():
    canvas = Canvas()
    a = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    with pytest.raises(ValueError):
        canvas.group([a.id])  # need at least two
    with pytest.raises(ValueError):
        canvas.group([a.id, "not_a_stroke"])  # unknown member


def test_group_events_survive_session_round_trip(tmp_path):
    canvas = Canvas()
    a = canvas.add_stroke([(10, 10), (20, 20)], author=Author.USER)
    b = canvas.add_stroke([(30, 30), (40, 40)], author=Author.USER)
    group_id = canvas.group([a.id, b.id], label="fig")

    path = tmp_path / "s.json"
    canvas.save_session(path)
    restored = Canvas.load_session(path)

    assert group_id in restored.groups()
    assert restored.groups()[group_id]["label"] == "fig"
