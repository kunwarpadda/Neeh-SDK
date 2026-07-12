"""Run grounding policies P0-P4 through the real Codex or Claude CLI adapter.

The harness scores action choice, target stroke ids, validation, and perception
escalation. Use ``--dry-run`` to inspect bootstrap economics without model calls.

    python examples/evaluate_perception_policies.py --agent codex
    python examples/evaluate_perception_policies.py --agent claude --policies active-index marked-index
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from neeh import Canvas
from neeh.agents import assistant
from neeh.agents.iai import PERCEPTION_POLICIES, build_observation_workspace
from neeh.document import Document
from neeh.ink import Author, BoundingBox, Point, Stroke
from neeh.ink.textink import layout_text


@dataclass(frozen=True)
class EvalCase:
    name: str
    task_class: str
    canvas: Canvas
    instruction: str
    expected_tool: str
    expected_stroke_ids: tuple[str, ...] = ()
    expected_text_contains: str | None = None
    pair_id: str | None = None


Runner = Callable[[Canvas, str], dict[str, Any]]


def _two_marks() -> EvalCase:
    canvas = Canvas()
    loop = canvas.add_stroke(
        [(60, 80), (220, 80), (220, 240), (60, 240), (60, 80)],
        author=Author.USER,
    )
    canvas.add_stroke([(650, 100), (860, 100)], author=Author.USER)
    return EvalCase(
        "annotate_upper_left_loop",
        "annotate",
        canvas,
        "Annotate the upper-left loop with the note 'closed shape'.",
        "annotate",
        (loop.id,),
    )


def _point_lower_right() -> EvalCase:
    canvas = Canvas()
    canvas.add_stroke([(80, 100), (260, 100)], author=Author.USER)
    loop = canvas.add_stroke(
        [(650, 500), (820, 500), (820, 660), (650, 660), (650, 500)],
        author=Author.USER,
    )
    return EvalCase(
        "point_lower_right_loop",
        "point",
        canvas,
        "Draw one bare arrow pointing at the lower-right loop.",
        "connect",
        (loop.id,),
    )


def _read_question() -> EvalCase:
    canvas = Canvas()
    polylines, _ = layout_text(
        "17 + 26 = ?",
        BoundingBox(100, 180, 800, 320),
        size=64,
        style="handwritten",
    )
    canvas.add_strokes(polylines, author=Author.USER)
    return EvalCase(
        "read_handwritten_question",
        "read",
        canvas,
        "Answer the handwritten question with a short answer in empty space.",
        "write_text",
        expected_text_contains="43",
    )


def _direction_case(direction: str) -> EvalCase:
    canvas = Canvas()
    xy = [(120, 260), (720, 260)]
    if direction == "left":
        xy.reverse()
    stroke = Stroke(
        points=tuple(
            Point(x, y, t_ms=index * 300, pressure=0.65)
            for index, (x, y) in enumerate(xy)
        ),
        id=f"st_direction_{direction}",
        created_at_ms=10_000,
    )
    canvas.page.layers[0].add(stroke)
    return EvalCase(
        f"identical_raster_direction_{direction}",
        "temporal-direction",
        canvas,
        "In which direction was the horizontal line drawn? Write only 'right' or 'left' in empty space.",
        "write_text",
        expected_text_contains=direction,
        pair_id="direction_pair_1",
    )
def built_in_cases() -> list[EvalCase]:
    return [
        _two_marks(),
        _point_lower_right(),
        _read_question(),
        _direction_case("right"),
        _direction_case("left"),
    ]


def _target_ids(result: dict[str, Any], tool: str) -> set[str]:
    for action in result.get("actions") or []:
        if action.get("tool") == tool and "error" not in action:
            return set((action.get("input") or {}).get("stroke_ids") or [])
    return set()


def _action_text(result: dict[str, Any], tool: str) -> str:
    for action in result.get("actions") or []:
        if action.get("tool") == tool and "error" not in action:
            action_input = action.get("input") or {}
            return " ".join(
                str(action_input.get(key, ""))
                for key in ("text", "label", "note")
            )
    return ""


def score_result(case: EvalCase, result: dict[str, Any]) -> dict[str, Any]:
    successful_tools = [
        action.get("tool") for action in result.get("actions") or []
        if "error" not in action
    ]
    tool_correct = case.expected_tool in successful_tools
    expected_ids = set(case.expected_stroke_ids)
    actual_ids = _target_ids(result, case.expected_tool)
    target_correct = not expected_ids or actual_ids == expected_ids
    actual_text = _action_text(result, case.expected_tool)
    text_correct = (
        case.expected_text_contains is None
        or case.expected_text_contains.casefold() in actual_text.casefold()
    )
    validation_passed = bool((result.get("validation") or {}).get("passed", True))
    return {
        "case": case.name,
        "task_class": case.task_class,
        "pair_id": case.pair_id,
        "policy": result.get("perception_policy"),
        "tool_correct": tool_correct,
        "target_correct": target_correct,
        "text_correct": text_correct,
        "validation_passed": validation_passed,
        "success": tool_correct and target_correct and text_correct and validation_passed,
        "expected_tool": case.expected_tool,
        "expected_stroke_ids": sorted(expected_ids),
        "actual_stroke_ids": sorted(actual_ids),
        "expected_text_contains": case.expected_text_contains,
        "actual_text": actual_text,
        "perception": result.get("perception_telemetry") or {},
        "repair_attempted": bool((result.get("validation") or {}).get("repair_attempted")),
        "reply": result.get("reply"),
        "model": result.get("model"),
        "reasoning_effort": result.get("reasoning_effort"),
    }


def evaluate_case(case: EvalCase, policy: str, runner: Runner) -> dict[str, Any]:
    if policy not in PERCEPTION_POLICIES:
        raise ValueError(f"unknown policy {policy!r}")
    canvas = Canvas(Document.from_dict(case.canvas.document.to_dict()))
    previous = assistant.PERCEPTION_MODE
    assistant.PERCEPTION_MODE = policy
    try:
        result = runner(canvas, case.instruction)
    finally:
        assistant.PERCEPTION_MODE = previous
    return score_result(case, result)


def dry_run_case(case: EvalCase, policy: str) -> dict[str, Any]:
    previous = assistant.PERCEPTION_MODE
    assistant.PERCEPTION_MODE = policy
    try:
        preview = assistant.agent_input_preview(case.canvas, case.instruction)
    finally:
        assistant.PERCEPTION_MODE = previous
    return {
        "case": case.name,
        "task_class": case.task_class,
        "policy": policy,
        "bootstrap_chars": preview["context_chars"],
        "raster_attached": preview["image"]["attached"],
        "raster_bytes": preview["image"]["bytes"],
        "capabilities": preview["context"].get("capabilities", []),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    policies = sorted({row["policy"] for row in rows})
    return {
        policy: {
            "cases": sum(row["policy"] == policy for row in rows),
            "successes": sum(row["policy"] == policy and row.get("success") for row in rows),
            "mean_estimated_tokens": round(
                sum(
                    (row.get("perception") or {}).get("estimated_tokens", 0)
                    for row in rows if row["policy"] == policy
                ) / max(sum(row["policy"] == policy for row in rows), 1)
            ),
            "perception_actions": sum(
                (row.get("perception") or {}).get("perception_actions", 0)
                for row in rows if row["policy"] == policy
            ),
        }
        for policy in policies
    }


def summarize_controlled_pairs(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pair_ids = sorted({row["pair_id"] for row in rows if row.get("pair_id")})
    return {
        pair_id: {
            policy: {
                "cases": len(selected),
                "successes": sum(bool(row.get("success")) for row in selected),
                "answers": [row.get("actual_text", "").strip() for row in selected],
            }
            for policy in sorted({row["policy"] for row in rows if row.get("pair_id") == pair_id})
            if (selected := [
                row for row in rows
                if row.get("pair_id") == pair_id and row["policy"] == policy
            ])
        }
        for pair_id in pair_ids
    }


def main() -> None:
    cases = built_in_cases()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=["codex", "claude"], default="codex")
    parser.add_argument(
        "--policies",
        nargs="+",
        choices=PERCEPTION_POLICIES,
        default=list(PERCEPTION_POLICIES),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--cases",
        nargs="+",
        choices=[case.name for case in cases],
        default=[case.name for case in cases],
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    runner = assistant.run_codex_cli if args.agent == "codex" else assistant.run_claude
    rows: list[dict[str, Any]] = []
    for case in cases:
        if case.name not in args.cases:
            continue
        for policy in args.policies:
            row = dry_run_case(case, policy) if args.dry_run else evaluate_case(case, policy, runner)
            rows.append(row)
            print(json.dumps(row, separators=(",", ":")))
    report = {"agent": args.agent, "dry_run": args.dry_run, "rows": rows}
    if args.agent == "codex":
        report["codex_config"] = {
            "model": assistant.CODEX_MODEL,
            "reasoning_effort": assistant.CODEX_REASONING_EFFORT,
        }
    if not args.dry_run:
        report["summary"] = summarize(rows)
        report["controlled_pairs"] = summarize_controlled_pairs(rows)
        print(json.dumps({"summary": report["summary"]}, indent=2))
    if args.output:
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
