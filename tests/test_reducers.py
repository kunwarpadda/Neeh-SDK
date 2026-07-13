"""Task-specific reducers compose primitive analyzers into task-shaped answers."""
from __future__ import annotations

import pytest

from neeh import Canvas
from neeh.agents import reduce_ink
from neeh.ink import Point, Stroke


def _seg(stroke_id: str, x1: float, y1: float, x2: float, y2: float, t: int) -> Stroke:
    return Stroke(
        id=stroke_id,
        created_at_ms=t,
        points=(Point(x1, y1, 0, 0.6), Point(x2, y2, 100, 0.6)),
    )


def test_unknown_task_is_rejected():
    with pytest.raises(ValueError):
        reduce_ink(Canvas(), "not_a_task")


def test_recent_changes_orders_by_end_time_and_is_bounded():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_seg("old", 100, 100, 110, 110, 1_000))
    layer.add(_seg("mid", 200, 200, 210, 210, 5_000))
    layer.add(_seg("new", 300, 300, 310, 310, 9_000))

    result = reduce_ink(canvas, "recent_changes", limit=2)

    assert result["claim_type"] == "measurement"
    assert [c["id"] for c in result["changes"]] == ["new", "mid"]
    assert result["changes"][0]["ms_since_latest"] == 0
    assert result["truncated"] is True


def test_recent_changes_since_ms_filters_older_ink():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_seg("old", 100, 100, 110, 110, 1_000))
    layer.add(_seg("new", 300, 300, 310, 310, 9_000))

    result = reduce_ink(canvas, "recent_changes", since_ms=5_000)

    assert [c["id"] for c in result["changes"]] == ["new"]


def test_overwritten_ink_flags_later_stroke_over_earlier():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_seg("first", 100, 100, 160, 160, 1_000))
    layer.add(_seg("correction", 110, 110, 150, 150, 5_000))  # later, overlapping

    result = reduce_ink(canvas, "overwritten_ink")

    assert result["claim_type"] == "inference"
    assert result["candidate_count"] >= 1
    top = result["candidates"][0]
    assert top["later_id"] == "correction"
    assert top["earlier_id"] == "first"
    assert 0.0 < top["confidence"] <= 0.95
    assert top["provenance"]["time_gap_ms"] == 4_000


def test_revisions_merges_overwrite_and_crossout_evidence():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    layer.add(_seg("first", 100, 100, 160, 160, 1_000))
    layer.add(_seg("correction", 110, 110, 150, 150, 5_000))

    result = reduce_ink(canvas, "revisions")

    kinds = {rev["kind"] for rev in result["revisions"]}
    assert "overwrite" in kinds
    assert all("confidence" in rev and "provenance" in rev for rev in result["revisions"])
    assert "history_complete" in result


def test_page_summary_reports_exact_aggregates_and_groups():
    canvas = Canvas()
    layer = canvas.page.layers[0]
    for i in range(3):
        layer.add(_seg(f"near_{i}", 100 + 10 * i, 100 + 5 * i, 108 + 10 * i, 106 + 5 * i, 1_000 + i))
    for i in range(2):
        layer.add(_seg(f"far_{i}", 600 + 10 * i, 700 + 5 * i, 608 + 10 * i, 706 + 5 * i, 2_000 + i))

    result = reduce_ink(canvas, "page_summary")

    assert result["claim_type"] == "measurement"
    assert result["stroke_count"] == 5
    assert result["time_span_ms"] == (2_001 + 100) - 1_000
    assert result["group_count"] == 2
    assert result["page_bbox"][0] == 100.0


def test_page_summary_handles_empty_page():
    result = reduce_ink(Canvas(), "page_summary")
    assert result["stroke_count"] == 0
    assert result["time_span_ms"] is None
