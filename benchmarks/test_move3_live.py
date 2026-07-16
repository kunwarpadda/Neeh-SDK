"""Move 3 live arm: reply parsing, scoring, ledger resume, and instruction assembly."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

live = pytest.importorskip(
    "benchmarks.move3_live", reason="Move 3 needs Pillow (neeh[png])",
)
m = pytest.importorskip("benchmarks.move3_grounding")


def test_parse_qa_reply_tolerates_prose_and_plain_text():
    assert live.parse_qa_reply('{"answer": "upper", "evidence": "timeline"}') == (
        "upper", "timeline",
    )
    answer, evidence = live.parse_qa_reply(
        'Sure — here is my answer: {"answer": "st_1", "evidence": "the event log"} done'
    )
    assert (answer, evidence) == ("st_1", "the event log")
    assert live.parse_qa_reply("lower") == ("lower", "")


def test_answers_match_is_case_and_order_insensitive():
    assert live.answers_match("Upper", "upper")
    assert live.answers_match("st_a,st_b,st_c", "st_c, st_a, st_b")
    assert not live.answers_match("st_a,st_b", "st_a")


def test_score_qa_separates_correct_abstained_and_false_explanation():
    task = m.build_tasks(["latest_mark"], per_kind=1, seed=0)[0]
    right = {"reply": json.dumps({"answer": task.answer, "evidence": "timeline"})}
    wrong_cited = {"reply": json.dumps({"answer": "st_nope", "evidence": "I saw it"})}
    wrong_silent = {"reply": json.dumps({"answer": "st_nope", "evidence": ""})}
    abstain = {"reply": json.dumps({"answer": live.ABSTAIN, "evidence": "no history"})}
    assert live.score_qa(task, right)["correct"] is True
    cited = live.score_qa(task, wrong_cited)
    assert cited["correct"] is False and cited["false_explanation"] is True
    assert live.score_qa(task, wrong_silent)["false_explanation"] is False
    scored = live.score_qa(task, abstain)
    assert scored["abstained"] is True and scored["false_explanation"] is False


def test_score_action_checks_tool_targets_validation_and_repair():
    task = m.Task(
        task_id="a0", kind="k", signal="history", canvas=m.Canvas(),
        question="q", answer="st_t", category="action",
        expected_tool="annotate", expected_target_ids=("st_t",),
    )
    good = {
        "actions": [{"tool": "annotate", "input": {"stroke_ids": ["st_t"]}}],
        "validation": {"passed": True, "repair_attempted": True},
    }
    scored = live.score_action(task, good)
    assert scored["correct"] and scored["target_correct"] and scored["repair_success"]
    miss = {
        "actions": [{"tool": "annotate", "input": {"stroke_ids": ["st_x"]}}],
        "validation": {"passed": True, "repair_attempted": False},
    }
    assert live.score_action(task, miss)["correct"] is False


def test_build_instruction_appends_measured_arm_evidence():
    task = m.build_tasks(["latest_mark"], per_kind=1, seed=1)[0]
    canvas = m.Canvas.from_session(task.canvas.session_snapshot())
    plain, extra, pre = live.build_instruction(task, "index-only", canvas)
    assert extra == 0 and pre is False and live.ABSTAIN in plain
    geo, extra_geo, _ = live.build_instruction(task, "raster+geometry", canvas)
    assert extra_geo > 0 and "Vector paths" in geo
    first, extra_first, pre_first = live.build_instruction(task, "analyzer-first", canvas)
    assert pre_first is True and extra_first > 0
    # A pointer to the workspace's precomputed analysis, never a payload copy
    # (duplicating it re-enters the perception budget and overflows).
    assert "already precomputed" in first and "{" not in first.split("\n\n")[-1]


@pytest.mark.skipif(
    not m.MATHWRITING_ROOT.is_dir(), reason="MathWriting excerpt not downloaded",
)
def test_analyzer_first_precompute_survives_dense_real_ink():
    # Regression: a ~14-stroke real expression once blew the workspace budget
    # (max_bootstrap_chars) because the precompute built a full workspace
    # instead of routing straight to the reducer.
    for task in m.build_tasks(["mw_erased_rewrite", "mw_grouping"], per_kind=2, seed=0):
        canvas = m.Canvas.from_session(task.canvas.session_snapshot())
        _, extra, precomputed = live.build_instruction(task, "analyzer-first", canvas)
        assert precomputed is True and extra > 0


@pytest.mark.skipif(
    not m.MATHWRITING_ROOT.is_dir(), reason="MathWriting excerpt not downloaded",
)
def test_analyzer_first_instruction_fits_the_perception_budget():
    # Regression: the assistant echoes the instruction into the observation
    # workspace, whose task text and analysis are untrimmable — an uncompacted
    # reducer dump in the instruction blew max_bootstrap_chars on the denser
    # erased-rewrite expressions (sweep errors on mw_erased_2..5).
    from neeh.agents.iai import build_observation_workspace

    for task in m.build_tasks(["mw_erased_rewrite"], per_kind=6, seed=0):
        canvas = m.Canvas.from_session(task.canvas.session_snapshot())
        instruction, extra, precomputed = live.build_instruction(
            task, "analyzer-first", canvas
        )
        assert precomputed is True
        workspace = build_observation_workspace(
            canvas, instruction, policy="active-index"
        )
        assert workspace["bootstrap_chars"] <= 6000


@pytest.mark.skipif(
    not m.MATHWRITING_ROOT.is_dir(), reason="MathWriting excerpt not downloaded",
)
def test_erased_rewrite_answer_surfaces_in_precomputed_analysis():
    import json as _json

    from neeh.agents.iai import _task_analysis

    for task in m.build_tasks(["mw_erased_rewrite"], per_kind=6, seed=0):
        canvas = m.Canvas.from_session(task.canvas.session_snapshot())
        analysis = _task_analysis(canvas, task.question)
        assert analysis is not None
        assert task.answer in _json.dumps(analysis)


@pytest.mark.skipif(
    not m.MATHWRITING_ROOT.is_dir(), reason="MathWriting excerpt not downloaded",
)
def test_pixel_free_arms_never_attach_a_bootstrap_raster(monkeypatch):
    # Arm identity: real-ink questions say "handwritten"/"symbol", which trips
    # the assistant's semantic-raster heuristic and silently turned the
    # pixel-free arms into raster-carrying ones during the first live sweep.
    from neeh.agents.assistant import _bootstrap_raster_required

    task = m.build_tasks(["mw_latest_symbol"], per_kind=1, seed=0)[0]
    canvas = m.Canvas.from_session(task.canvas.session_snapshot())
    instruction, _, _ = live.build_instruction(task, "active-index", canvas)
    monkeypatch.setenv("NEEH_PERCEPTION_MODE", "active-index")
    monkeypatch.setattr("neeh.agents.assistant.PERCEPTION_MODE", "active-index")
    monkeypatch.setenv("NEEH_BOOTSTRAP_RASTER", "auto")
    assert _bootstrap_raster_required(canvas, instruction) is True
    monkeypatch.setenv("NEEH_BOOTSTRAP_RASTER", "never")
    assert _bootstrap_raster_required(canvas, instruction) is False


def test_mock_sweep_writes_ledger_and_resumes(tmp_path: Path):
    ledger = tmp_path / "ledger.jsonl"
    kwargs = dict(
        agent="mock", kinds=["latest_mark", "recent_change"], per_kind=1,
        arms=["index-only", "analyzer-first"], seed=0, workers=2,
        ledger_path=ledger,
    )
    first = live.run_live(**kwargs)
    assert first["calls_made"] == 4 and first["rows_scored"] == 4
    summary = first["summary"]
    assert summary["index-only"]["abstention_rate"] == 1.0
    assert summary["index-only"]["accuracy"] == 0.0
    # Second run: everything already in the ledger, nothing re-called.
    second = live.run_live(**kwargs)
    assert second["calls_made"] == 0 and second["rows_scored"] == 4
    rows = [json.loads(line) for line in ledger.read_text().splitlines()]
    assert len(rows) == 4 and all(r["status"] == "ok" for r in rows)
