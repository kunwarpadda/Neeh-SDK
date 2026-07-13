"""Move 1 harness: render-identity is the load-bearing invariant."""
from __future__ import annotations

import pytest

move1 = pytest.importorskip(
    "benchmarks.move1_render_identical_pairs",
    reason="Move 1 harness needs Pillow (neeh[png])",
)


def _rows_by(rows, **match):
    return [r for r in rows if all(r[k] == v for k, v in match.items())]


def test_every_pair_is_pixel_identical():
    trials = move1.build_trials(list(move1.AXES), n_per_axis=4, seed=7)
    certified = move1.certify_identical(trials)
    pairs = {k: v for k, v in certified.items() if isinstance(k, tuple)}
    assert pairs, "expected certified pairs"
    assert all(pairs.values()), f"a generator leaked signal into pixels: {pairs}"


def test_twins_carry_opposite_answers():
    trials = move1.build_trials(list(move1.AXES), n_per_axis=3, seed=1)
    by_id = {t.trial_id: t for t in trials}
    for t in trials:
        twin = by_id[t.twin_id]
        assert t.answer != twin.answer
        assert set((t.answer, twin.answer)) == set(t.options)


def test_mock_oracle_recovers_signal_from_history_not_pixels():
    trials = move1.build_trials(list(move1.AXES), n_per_axis=5, seed=2)
    rows = []
    for trial in trials:
        for condition in move1.CONDITIONS:
            prompt = move1.build_prompt(trial, condition, cap=24)
            out = move1.run_mock(trial, condition, prompt, image_png=None)
            rows.append(move1.score(trial, condition, out, cap=24))
    summary = move1.summarize(rows)
    for axis in move1.AXES:
        # png condition has no history: the oracle sits exactly at chance
        assert summary[axis]["png"]["accuracy"] == 0.5
        # structured + coordinate conditions expose the hidden axis exactly
        assert summary[axis]["png+struct"]["accuracy"] == 1.0
        assert summary[axis]["coords"]["accuracy"] == 1.0


def test_structured_conditions_do_not_leak_order_by_list_position():
    # For the order axis, both twins must serialize their strokes in the same
    # positional order, so only created_at_ms distinguishes them.
    trials = move1.build_trials(["order"], n_per_axis=1, seed=0)
    a, b = trials
    rec_a = move1._ink_record(a.page, cap=24)
    rec_b = move1._ink_record(b.page, cap=24)
    assert [s["shape"] for s in rec_a] == [s["shape"] for s in rec_b]
    # the answer only flips because the created_at_ms ordering flips
    assert (rec_a[0]["created_at_ms"] < rec_a[1]["created_at_ms"]) != (
        rec_b[0]["created_at_ms"] < rec_b[1]["created_at_ms"]
    )


def test_direction_serialization_keeps_endpoints():
    trials = move1.build_trials(["direction"], n_per_axis=1, seed=0)
    for trial in trials:
        pts = move1._sample_points(trial.page.all_strokes()[0], cap=6)
        first_x, last_x = pts[0][0], pts[-1][0]
        expected_ltr = first_x <= last_x
        assert (trial.answer == "left-to-right") == expected_ltr


def test_codex_model_and_effort_are_not_configurable():
    assert move1.CODEX_MODEL == "gpt-5.5"
    assert move1.CODEX_EFFORT == "high"
