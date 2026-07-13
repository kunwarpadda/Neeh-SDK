"""Move 3: ground truth, the grounding-versus-policy model, and controls."""
from __future__ import annotations

import pytest

m = pytest.importorskip(
    "benchmarks.move3_grounding", reason="Move 3 needs Pillow (neeh[png])",
)


def test_latest_mark_ground_truth_matches_newest_stroke():
    tasks = m.build_tasks(["latest_mark"], per_kind=6, seed=3)
    for t in tasks:
        newest = max(t.canvas.page.all_strokes(), key=lambda s: s.created_at_ms)
        expected = "upper" if newest.bbox.center[1] < m._HALF else "lower"
        assert t.answer == expected


def test_crossed_out_and_grouping_ground_truth_is_exact():
    cross = m.build_tasks(["crossed_out"], per_kind=4, seed=1)
    for t in cross:
        # The crossed-out mark is the earliest stroke on the page.
        earliest = min(t.canvas.page.all_strokes(), key=lambda s: s.created_at_ms)
        assert t.answer == earliest.id
    groups = m.build_tasks(["grouping"], per_kind=4, seed=1)
    for t in groups:
        # Answer is exactly the group's membership per the event log.
        members = next(iter(t.canvas.groups().values()))["member_ids"]
        assert t.answer == ",".join(sorted(members))


def test_dataset_is_balanced_for_binary_tasks():
    tasks = m.build_tasks(["latest_mark"], per_kind=6, seed=0)
    uppers = sum(t.answer == "upper" for t in tasks)
    assert uppers == len(tasks) // 2


def test_raster_and_static_index_do_not_ground_history_tasks():
    tasks = m.build_tasks(list(m._BUILDERS), per_kind=3, seed=2)
    rows = m.evaluate_dry(tasks, list(m.ARMS))
    summary = m.summarize(rows)
    # Pixels and a static map cannot recover time/history/grouping signals.
    assert summary["raster-only"]["grounded_rate"] == 0.0
    assert summary["raster+geometry"]["grounded_rate"] == 0.0
    assert summary["index-only"]["grounded_rate"] == 0.0
    # Analyzer-bearing arms can.
    assert summary["active-index"]["grounded_rate"] == 1.0
    assert summary["marked-index"]["grounded_rate"] == 1.0
    assert summary["analyzer-first"]["grounded_rate"] == 1.0


def test_analyzer_first_is_exact_and_cheaper_than_raster_in_pixels():
    tasks = m.build_tasks(list(m._BUILDERS), per_kind=3, seed=5)
    rows = m.evaluate_dry(tasks, list(m.ARMS))
    summary = m.summarize(rows)
    # analyzer-first grounds every task with a pre-computed reducer, no pixels.
    assert summary["analyzer-first"]["exact"] == summary["analyzer-first"]["n_tasks"]
    assert summary["analyzer-first"]["mean_raster_pixels"] == 0
    assert summary["raster-only"]["mean_raster_pixels"] > 0


def test_adversarial_controls_are_leak_free_and_balanced():
    tasks = m.build_tasks(list(m._BUILDERS), per_kind=4, seed=7)
    controls = m.adversarial_controls(tasks)
    assert controls["leak_free"] is True
    for kind, cell in controls["balance"].items():
        assert cell["balanced"] is True
