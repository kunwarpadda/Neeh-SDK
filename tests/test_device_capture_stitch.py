"""Stitching sequential device-capture research bundles of one notebook."""
from __future__ import annotations

from typing import Any

import pytest

from neeh.adapters.device_capture import (
    DeviceCaptureError,
    import_device_capture,
    stitch_device_captures,
    validate_device_capture,
)

_PAGE = "page-1"


def _stroke_triple(
    seq: int, tag: str, t_ms: int, stroke_id: str, points: list[tuple[float, float, int]],
    *, tool: str = "pen",
) -> tuple[list[dict[str, Any]], int]:
    events = [{
        "seq": seq, "event_id": f"{tag}-ev{seq}", "kind": "stroke_begin", "t_ms": t_ms,
        "page_id": _PAGE, "stroke_id": stroke_id, "layer_id": "ink", "author": "user",
        "tool": tool, "style": {"width": 3.0, "color": "#101010"},
        "created_at_ms": 1_000_000 + t_ms,
    }]
    seq += 1
    for x, y, pt_ms in points:
        events.append({
            "seq": seq, "event_id": f"{tag}-ev{seq}", "kind": "stroke_sample", "t_ms": t_ms,
            "page_id": _PAGE, "stroke_id": stroke_id, "point": {"x": x, "y": y, "t_ms": pt_ms},
        })
        seq += 1
    events.append({
        "seq": seq, "event_id": f"{tag}-ev{seq}", "kind": "stroke_end", "t_ms": t_ms,
        "page_id": _PAGE, "stroke_id": stroke_id,
    })
    return events, seq + 1


def _erase(seq: int, tag: str, t_ms: int, stroke_id: str, removed_snapshot: dict) -> tuple[dict, int]:
    return {
        "seq": seq, "event_id": f"{tag}-ev{seq}", "kind": "stroke_delete", "t_ms": t_ms,
        "page_id": _PAGE, "reason": "eraser",
        "removed": [removed_snapshot], "added": [],
    }, seq + 1


def _base(session_id: str, started_at_ms: int, events: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "schema": "neeh-device-capture/v1",
        "session": {"id": session_id, "started_at_ms": started_at_ms,
                     "ended_at_ms": started_at_ms + 100_000, "name": session_id},
        "device": {"manufacturer": "samsung", "model": "SM-X620", "android_version": "16",
                   "sdk_int": 36, "pressure_available": False, "tilt_available": False,
                   "orientation_available": False},
        "app": {"name": "Device Recorder", "package_name": "com.device.recorder", "version_name": "0.1.0-m0"},
        "coordinate_space": {"unit": "px", "origin": "top-left"},
        "pages": [{"id": _PAGE, "index": 0, "width": 1000.0, "height": 1400.0}],
        "events": events,
    }


def _snapshot_of(stroke_id: str, points: list[tuple[float, float, int]]) -> dict:
    return {
        "stroke_id": stroke_id, "layer_id": "ink", "author": "user", "tool": "pen",
        "style": {"width": 3.0, "color": "#101010"}, "created_at_ms": 1_000_000,
        "points": [{"x": x, "y": y, "t_ms": t} for x, y, t in points],
    }


def _bundle1() -> dict[str, Any]:
    """Two strokes: st_a (kept) and st_b (later erased in bundle 2)."""
    events: list[dict[str, Any]] = []
    seq = 0
    e, seq = _stroke_triple(seq, "b1", 0, "stroke-1", [(100, 100, 0), (140, 100, 50)])
    events += e
    e, seq = _stroke_triple(seq, "b1", 200, "stroke-2", [(100, 300, 0), (140, 300, 50)])
    events += e
    return _base("session-1", 1_000_000, events)


def _preexisting_seed(seq: int, tag: str, entries: list[tuple[str, list[tuple[float, float, int]]]]) -> tuple[list[dict], int]:
    events: list[dict[str, Any]] = []
    for stroke_id, points in entries:
        e, seq = _stroke_triple(seq, tag, 0, stroke_id, points, tool="preexisting")
        events += e
    return events, seq


def _bundle2_continuing(*, drop_stroke_b: bool, mismatch: bool = False) -> dict[str, Any]:
    """Reseeds bundle 1's ink, optionally erases st_b's reseeded copy, adds st_c."""
    seed_points_a = [(100, 100, 0), (140, 101, 0)]  # resampled, not identical to bundle 1
    seed_points_b = [(100, 302, 0), (139, 300, 0)]
    if mismatch:
        seed_points_b = [(900, 900, 0), (950, 950, 0)]  # deliberately wrong location
    seed, seq = _preexisting_seed(0, "b2", [
        ("stroke-1", seed_points_a),  # local id for st_a's reseed
        ("stroke-2", seed_points_b),  # local id for st_b's reseed
    ])
    events = list(seed)
    if drop_stroke_b:
        snap = _snapshot_of("stroke-2", seed_points_b)
        ev, seq = _erase(seq, "b2", 300, "stroke-2", snap)
        events.append(ev)
    e, seq = _stroke_triple(seq, "b2", 400, "stroke-3", [(500, 500, 0), (540, 500, 50)])
    events += e
    return _base("session-2", 1_100_000, events)


def test_stitch_drops_redundant_preexisting_seed_and_appends_new_events() -> None:
    b1, b2 = _bundle1(), _bundle2_continuing(drop_stroke_b=False)
    stitched = stitch_device_captures([b1, b2])
    validate_device_capture(stitched)

    # Only bundle 1's own events plus bundle 2's genuinely new stroke survive;
    # bundle 2's reseed of st_a/st_b is fully dropped, not duplicated.
    kinds = [e["kind"] for e in stitched["events"]]
    assert kinds.count("stroke_begin") == 3  # stroke-1, stroke-2 (bundle 1) + the new one

    imported = import_device_capture(stitched)
    live_ids = {s.id for s in imported.document.pages[0].all_strokes()}
    assert live_ids == {"stroke-1", "stroke-2", f"b2:stroke-3"}


def test_stitch_erase_of_carried_over_stroke_targets_the_original_id() -> None:
    b1, b2 = _bundle1(), _bundle2_continuing(drop_stroke_b=True)
    stitched = stitch_device_captures([b1, b2])
    imported = import_device_capture(stitched)

    live_ids = {s.id for s in imported.document.pages[0].all_strokes()}
    assert live_ids == {"stroke-1", "b2:stroke-3"}  # stroke-2 was erased in bundle 2
    # The erase must be recorded against bundle 1's ORIGINAL id, not bundle 2's
    # local re-numbering, so history recovery still finds the true original.
    assert imported.event_log.recover("stroke-2") is not None
    assert imported.event_log.recover("stroke-2").id == "stroke-2"


def test_stitch_rejects_a_seed_that_does_not_match_prior_final_ink() -> None:
    b1 = _bundle1()
    b2 = _bundle2_continuing(drop_stroke_b=False, mismatch=True)
    with pytest.raises(DeviceCaptureError, match="does not match the prior bundle"):
        stitch_device_captures([b1, b2])


def test_stitch_rejects_out_of_order_bundles() -> None:
    b1, b2 = _bundle1(), _bundle2_continuing(drop_stroke_b=False)
    with pytest.raises(DeviceCaptureError, match="chronological order"):
        stitch_device_captures([b2, b1])


def test_stitch_single_bundle_is_a_no_op_copy() -> None:
    b1 = _bundle1()
    stitched = stitch_device_captures([b1])
    assert stitched == b1
    assert stitched is not b1  # a copy, not the same object


def test_stitch_three_bundles_keeps_canonical_ids_through_the_whole_chain() -> None:
    b1 = _bundle1()
    b2 = _bundle2_continuing(drop_stroke_b=False)

    # Bundle 3 reseeds bundle 2's final live ink: stroke-1, stroke-2 (from
    # bundle 1, carried through) plus b2:stroke-3 (bundle 2's own new stroke).
    seed, seq = _preexisting_seed(0, "b3", [
        ("stroke-1", [(100, 100, 0), (140, 101, 0)]),
        ("stroke-2", [(100, 302, 0), (139, 300, 0)]),
        ("stroke-3", [(500, 500, 0), (540, 501, 0)]),
    ])
    events = list(seed)
    e, seq = _stroke_triple(seq, "b3", 500, "stroke-4", [(700, 700, 0), (740, 700, 50)])
    events += e
    b3 = _base("session-3", 1_200_000, events)

    stitched = stitch_device_captures([b1, b2, b3])
    validate_device_capture(stitched)
    imported = import_device_capture(stitched)
    live_ids = {s.id for s in imported.document.pages[0].all_strokes()}
    # stroke-1/stroke-2 from bundle 1, b2:stroke-3 from bundle 2, and bundle
    # 3's own new stroke -- every reseed collapsed away, no id collisions.
    assert live_ids == {"stroke-1", "stroke-2", "b2:stroke-3", "b3:stroke-4"}
