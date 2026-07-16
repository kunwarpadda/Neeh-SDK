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
    # Pixels cannot recover time/history/grouping signals at all.
    assert summary["raster-only"]["grounded_rate"] == 0.0
    assert summary["raster+geometry"]["grounded_rate"] == 0.0
    # The static map grounds exactly one signal class: recorded group
    # membership rides verbatim in the page map, nothing else does.
    index_rows = [r for r in rows if r["arm"] == "index-only"]
    for row in index_rows:
        if row["signal"] == "grouping":
            assert row["grounding"] == "exact"
        else:
            assert row["grounding"] == "no"
    # Analyzer-bearing arms ground everything.
    assert summary["active-index"]["grounded_rate"] == 1.0
    assert summary["marked-index"]["grounded_rate"] == 1.0
    assert summary["analyzer-first"]["grounded_rate"] == 1.0


def test_analyzer_first_is_exact_and_cheaper_than_raster_in_pixels():
    # Includes dc_erased_ink: since intent routing learned the erase intent
    # (event-log-backed revisions), every kind precomputes to exact evidence.
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


# ---- Real ink (MathWriting-backed) ---------------------------------------- #
real_ink = pytest.mark.skipif(
    not m.MATHWRITING_ROOT.is_dir(), reason="MathWriting excerpt not downloaded",
)


@real_ink
def test_mw_latest_symbol_half_matches_newest_stroke_and_is_balanced():
    tasks = m.build_tasks(["mw_latest_symbol"], per_kind=6, seed=11)
    for t in tasks:
        newest = max(t.canvas.page.all_strokes(), key=lambda s: s.created_at_ms)
        half = "upper" if newest.bbox.center[1] < m._HALF else "lower"
        assert t.answer == half
    assert sum(t.answer == "upper" for t in tasks) == 3


@real_ink
def test_mw_crossed_out_strike_overlaps_exactly_the_answer():
    for t in m.build_tasks(["mw_crossed_out"], per_kind=4, seed=13):
        strike = max(t.canvas.page.all_strokes(), key=lambda s: s.created_at_ms)
        answer = next(s for s in t.canvas.page.all_strokes() if s.id == t.answer)
        assert strike.id != t.answer
        # The strike spans the answer's horizontal extent and no other symbol's.
        others = [
            s for s in t.canvas.page.all_strokes()
            if s.id not in (t.answer, strike.id)
        ]
        assert strike.bbox.min_x < answer.bbox.min_x
        assert strike.bbox.max_x > answer.bbox.max_x
        for other in others:
            assert (
                strike.bbox.max_y < other.bbox.min_y
                or strike.bbox.min_y > other.bbox.max_y
                or strike.bbox.max_x < other.bbox.min_x
                or strike.bbox.min_x > other.bbox.max_x
            )


@real_ink
def test_mw_erased_rewrite_history_is_in_the_log_not_the_page():
    for t in m.build_tasks(["mw_erased_rewrite"], per_kind=4, seed=17):
        page_ids = {s.id for s in t.canvas.page.all_strokes()}
        assert t.answer in page_ids
        erase_events = [e for e in t.canvas.events.events if e.kind == "erase"]
        assert len(erase_events) == 1
        erased_ids = {s.id for _, s in erase_events[0].removed}
        # The erased original is gone from the page; only the log knows it.
        assert erased_ids.isdisjoint(page_ids)
        newest = max(t.canvas.page.all_strokes(), key=lambda s: s.created_at_ms)
        assert newest.id == t.answer


@real_ink
def test_mw_grouping_and_recent_change_ground_truth_is_exact():
    for t in m.build_tasks(["mw_grouping"], per_kind=3, seed=19):
        members = next(iter(t.canvas.groups().values()))["member_ids"]
        assert t.answer == ",".join(sorted(members))
    for t in m.build_tasks(["mw_recent_change"], per_kind=3, seed=19):
        last = t.canvas.events.events[-1]
        assert last.kind == "move"
        assert {s.id for _, s in last.added} == {t.answer}


@real_ink
def test_mw_annotate_is_an_action_task_targeting_the_crossed_symbol():
    for t in m.build_tasks(["mw_annotate_crossed"], per_kind=3, seed=23):
        assert t.category == "action"
        assert t.expected_tool == "annotate"
        assert t.expected_target_ids == (t.answer,)


@real_ink
def test_real_ink_controls_hold_and_answers_never_contain_labels():
    tasks = m.build_tasks(list(m._REAL_INK_KINDS), per_kind=4, seed=29)
    controls = m.adversarial_controls(tasks)
    assert controls["leak_free"] is True
    assert controls["labels_disjoint_from_answers"] is True
    for cell in controls["balance"].values():
        assert cell["balanced"] is True
    rows = m.evaluate_dry(tasks, list(m.ARMS))
    summary = m.summarize(rows)
    assert summary["raster-only"]["grounded_rate"] == 0.0
    # index-only grounds recorded group membership (it rides in the page map)
    # and nothing else among the real-ink kinds.
    for row in rows:
        if row["arm"] != "index-only":
            continue
        expected = "exact" if row["signal"] == "grouping" else "no"
        assert row["grounding"] == expected
    assert summary["analyzer-first"]["grounded_rate"] == 1.0
