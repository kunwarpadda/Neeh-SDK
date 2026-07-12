"""Policy evaluation scoring and dry-run coverage."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from neeh.rendering.png import render_page_png


MODULE_PATH = Path(__file__).parents[1] / "examples" / "evaluate_perception_policies.py"
SPEC = importlib.util.spec_from_file_location("evaluate_perception_policies", MODULE_PATH)
assert SPEC and SPEC.loader
eval_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = eval_module
SPEC.loader.exec_module(eval_module)


def test_score_result_checks_tool_target_validation_and_telemetry():
    case = eval_module.built_in_cases()[0]
    result = {
        "perception_policy": "active-index",
        "actions": [{
            "tool": case.expected_tool,
            "input": {"stroke_ids": list(case.expected_stroke_ids)},
            "output": {},
        }],
        "validation": {"passed": True, "repair_attempted": False},
        "perception_telemetry": {"estimated_tokens": 123, "perception_actions": 1},
    }

    scored = eval_module.score_result(case, result)

    assert scored["success"] is True
    assert scored["target_correct"] is True
    assert scored["perception"]["estimated_tokens"] == 123


def test_evaluate_case_clones_canvas_and_restores_policy():
    case = eval_module.built_in_cases()[1]
    previous = eval_module.assistant.PERCEPTION_MODE

    def runner(canvas, instruction):
        assert instruction == case.instruction
        return {
            "perception_policy": "index-only",
            "actions": [{
                "tool": case.expected_tool,
                "input": {"stroke_ids": list(case.expected_stroke_ids)},
                "output": {},
            }],
            "validation": {"passed": True},
        }

    row = eval_module.evaluate_case(case, "index-only", runner)

    assert row["success"] is True
    assert eval_module.assistant.PERCEPTION_MODE == previous


def test_read_case_scores_the_answer_text_not_only_the_tool():
    case = eval_module.built_in_cases()[2]
    wrong = {
        "perception_policy": "active-index",
        "actions": [{
            "tool": "write_text",
            "input": {"text": "42"},
            "output": {},
        }],
        "validation": {"passed": True},
    }
    right = {
        **wrong,
        "actions": [{
            "tool": "write_text",
            "input": {"text": "43"},
            "output": {},
        }],
    }

    assert eval_module.score_result(case, wrong)["success"] is False
    assert eval_module.score_result(case, right)["success"] is True


def test_all_policy_dry_runs_are_distinct_and_model_free():
    case = eval_module.built_in_cases()[0]
    rows = {
        policy: eval_module.dry_run_case(case, policy)
        for policy in eval_module.PERCEPTION_POLICIES
    }

    assert rows["raster-always"]["raster_attached"] is True
    assert rows["raster-only"]["raster_attached"] is True
    assert rows["raster-only"]["capabilities"] == []
    assert rows["index-only"]["raster_bytes"] == 0
    assert rows["active-index"]["raster_bytes"] == 0
    assert rows["active-index"]["capabilities"]
    assert rows["marked-index"]["bootstrap_chars"] > rows["active-index"]["bootstrap_chars"]


def test_temporal_direction_pair_has_identical_raster_but_opposite_answers():
    right, left = eval_module.built_in_cases()[-2:]

    assert right.pair_id == left.pair_id == "direction_pair_1"
    assert right.expected_text_contains == "right"
    assert left.expected_text_contains == "left"
    assert render_page_png(right.canvas.page) == render_page_png(left.canvas.page)


def test_controlled_pair_summary_exposes_systematic_ambiguity():
    rows = [
        {"pair_id": "p", "policy": "raster-only", "success": True, "actual_text": "right"},
        {"pair_id": "p", "policy": "raster-only", "success": False, "actual_text": "right"},
        {"pair_id": "p", "policy": "active-index", "success": True, "actual_text": "right"},
        {"pair_id": "p", "policy": "active-index", "success": True, "actual_text": "left"},
    ]

    summary = eval_module.summarize_controlled_pairs(rows)["p"]
    assert summary["raster-only"] == {
        "cases": 2, "successes": 1, "answers": ["right", "right"],
    }
    assert summary["active-index"]["successes"] == 2
