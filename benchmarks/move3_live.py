"""Live accuracy/abstention arm for the Move 3 grounding study.

Where ``move3_grounding.py --dry-run`` scores what each perception arm *could*
ground, this runner measures what a real model *does* with each arm's evidence:
exact answer accuracy, abstention, false explanations (a wrong answer asserted
with cited evidence), retrieval calls, context and pixel cost, latency, and —
for action tasks — target accuracy and repair success.

Model calls go through the local ``codex`` / ``claude`` CLI logins (owner rule:
never raw APIs). The codex arm pins the roadmap model (gpt-5.5, high reasoning);
set ``NEEH_CODEX_HOME`` to a harness-owned codex home and it is forwarded as
``CODEX_HOME``. Every completed row is appended to a JSONL ledger keyed by
(task, arm, agent, model, seed); re-running skips keys whose latest row is ok,
so a quota-gated sweep resumes with ``--retry-failed``.

    python benchmarks/move3_live.py --agent codex --smoke        # ~18 calls
    python benchmarks/move3_live.py --agent codex --workers 4    # full sweep
    python benchmarks/move3_live.py --agent claude               # second model
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.move3_grounding import (  # noqa: E402
    ARMS,
    _ANALYZER_ARMS,
    _ARM_POLICY,
    _BUILDERS,
    _REAL_INK_KINDS,
    Task,
    _geometry_text,
    adversarial_controls,
    available_kinds,
    build_tasks,
)
from neeh import Canvas  # noqa: E402
from neeh.agents import assistant  # noqa: E402
from neeh.agents.iai import _task_analysis  # noqa: E402

DEFAULT_LEDGER = Path(__file__).resolve().parent / "results" / "move3_ledger.jsonl"
ABSTAIN = "cannot-determine"
SMOKE_ARMS = ("raster-only", "index-only", "analyzer-first")
# Arms whose definition includes pixels; every other arm runs pixel-free, so
# the assistant's bootstrap-raster heuristic is pinned off for them.
_RASTER_ARMS_LIVE = {"raster-only", "raster+geometry", "marked-index"}

_LEDGER_LOCK = threading.Lock()


def _forward_codex_home() -> None:
    home = os.getenv("NEEH_CODEX_HOME")
    if home and not os.getenv("CODEX_HOME"):
        os.environ["CODEX_HOME"] = home


def row_key(task: Task, arm: str, agent: str, model: str, seed: int) -> str:
    return f"{task.task_id}|{arm}|{agent}|{model}|seed{seed}"


# --------------------------------------------------------------------------- #
# Instruction assembly per arm.
# --------------------------------------------------------------------------- #
_QA_CONTRACT = (
    "Answer using only the evidence available to you. Set your reply to exactly "
    'this JSON: {"answer": "<answer>", "evidence": "<one short sentence naming '
    'the evidence you used>"}. Stroke-id answers are bare ids, comma-separated '
    "if several. If the evidence cannot determine the answer, use exactly "
    f'"{ABSTAIN}" as the answer and say what was missing. '
    "Do not draw anything: return an empty actions list."
)


def build_instruction(task: Task, arm: str, canvas: Canvas) -> tuple[str, int, bool]:
    """The model-facing instruction for one (task, arm): (text, extra_chars,
    analysis_precomputed). Constructed arms append their extra evidence here so
    its cost is measured explicitly."""
    parts = [task.question]
    if task.category == "qa":
        parts.append(_QA_CONTRACT)
        if task.options:
            parts.append("The answer must be one of: " + ", ".join(task.options) + ".")
    extra_chars = 0
    precomputed = False
    if arm == "raster+geometry":
        geometry = "Vector paths (stroke id: sampled points): " + _geometry_text(canvas)
        extra_chars = len(geometry)
        parts.append(geometry)
    elif arm == "analyzer-first":
        # The active-index workspace already precomputes the routed reducer
        # (shipped intent routing), so the arm is a pointer, not a payload:
        # duplicating the analysis into the instruction re-enters the same
        # perception budget and overflows on dense real-ink pages.
        if _task_analysis(canvas, task.question) is not None:
            text = (
                "The exact deterministic analysis for this question is already "
                "precomputed in your observation workspace's 'analysis' field. "
                "Treat it as authoritative evidence and answer from it."
            )
            extra_chars = len(text)
            precomputed = True
            parts.append(text)
    return "\n\n".join(parts), extra_chars, precomputed


# --------------------------------------------------------------------------- #
# Scoring.
# --------------------------------------------------------------------------- #
def parse_qa_reply(reply: str) -> tuple[str, str]:
    """Extract (answer, evidence) from a reply, tolerating prose around JSON."""
    text = (reply or "").strip()
    start = text.find("{")
    if start != -1:
        for end in range(len(text), start, -1):
            try:
                payload = json.loads(text[start:end])
            except (json.JSONDecodeError, ValueError):
                continue
            if isinstance(payload, dict):
                return (
                    str(payload.get("answer", "")).strip(),
                    str(payload.get("evidence", "")).strip(),
                )
            break
    return text, ""


def _normalize(answer: str) -> str:
    return " ".join(answer.casefold().replace(",", " ").split())


def answers_match(expected: str, actual: str) -> bool:
    if _normalize(expected) == _normalize(actual):
        return True
    # Comma-joined id sets compare order-insensitively.
    return set(_normalize(expected).split()) == set(_normalize(actual).split())


def is_abstention(answer: str) -> bool:
    return _normalize(answer) in {ABSTAIN, "cannot determine"}


def score_qa(task: Task, result: dict[str, Any]) -> dict[str, Any]:
    answer, evidence = parse_qa_reply(str(result.get("reply") or ""))
    abstained = is_abstention(answer)
    correct = not abstained and answers_match(task.answer, answer)
    return {
        "answer": answer,
        "evidence": evidence,
        "correct": correct,
        "abstained": abstained,
        # The roadmap's "unsupported claims": wrong, not abstained, and asserted
        # with an evidence citation.
        "false_explanation": (not correct and not abstained and bool(evidence)),
    }


def score_action(task: Task, result: dict[str, Any]) -> dict[str, Any]:
    actions = result.get("actions") or []
    match = next(
        (
            a for a in actions
            if a.get("tool") == task.expected_tool and "error" not in a
        ),
        None,
    )
    target_ids = set((match.get("input") or {}).get("stroke_ids") or []) if match else set()
    validation = result.get("validation") or {}
    tool_correct = match is not None
    target_correct = tool_correct and target_ids == set(task.expected_target_ids)
    repair_attempted = bool(validation.get("repair_attempted"))
    return {
        "answer": ",".join(sorted(target_ids)),
        "evidence": "",
        "correct": target_correct and bool(validation.get("passed", True)),
        "abstained": False,
        "false_explanation": False,
        "tool_correct": tool_correct,
        "target_correct": target_correct,
        "validation_passed": bool(validation.get("passed", True)),
        "repair_attempted": repair_attempted,
        "repair_success": repair_attempted and bool(validation.get("passed", False)),
    }


# --------------------------------------------------------------------------- #
# One (task, arm) row through a runner.
# --------------------------------------------------------------------------- #
Runner = Callable[[Canvas, str], dict[str, Any]]


def run_row(task: Task, arm: str, runner: Runner, agent: str, seed: int) -> dict[str, Any]:
    canvas = Canvas.from_session(task.canvas.session_snapshot())
    instruction, extra_chars, precomputed = build_instruction(task, arm, canvas)
    row: dict[str, Any] = {
        "task": task.task_id,
        "kind": task.kind,
        "signal": task.signal,
        "category": task.category,
        "arm": arm,
        "policy": _ARM_POLICY[arm],
        "agent": agent,
        "seed": seed,
        "extra_instruction_chars": extra_chars,
        "analysis_precomputed": precomputed,
        "ts": round(time.time(), 3),
    }
    started = time.monotonic()
    try:
        result = runner(canvas, instruction)
    except Exception as exc:  # ModelUnavailableError, timeouts, parse failures
        row.update({
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
            "latency_s": round(time.monotonic() - started, 2),
            "model": assistant.CODEX_MODEL if agent == "codex" else agent,
        })
        return row
    telemetry = result.get("perception_telemetry") or {}
    scores = score_qa(task, result) if task.category == "qa" else score_action(task, result)
    row.update(scores)
    row.update({
        "status": "ok",
        "latency_s": round(time.monotonic() - started, 2),
        "model": result.get("model"),
        "reasoning_effort": result.get("reasoning_effort"),
        "retrieval_calls": telemetry.get("perception_actions", 0),
        "analyzer_queries": telemetry.get("analyzer_queries", 0),
        "bootstrap_chars": telemetry.get("bootstrap_chars", 0),
        "observation_chars": telemetry.get("observation_chars", 0),
        "estimated_tokens": telemetry.get("estimated_tokens", 0),
        "raster_pixels": telemetry.get("raster_pixels", 0),
        "reply": str(result.get("reply") or "")[:2000],
    })
    return row


# --------------------------------------------------------------------------- #
# Ledger.
# --------------------------------------------------------------------------- #
def load_ledger(path: Path) -> dict[str, dict[str, Any]]:
    """Latest row per key is authoritative."""
    rows: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        record = json.loads(line)
        if "key" in record:
            rows[record["key"]] = record
    return rows


def append_ledger(path: Path, record: dict[str, Any]) -> None:
    with _LEDGER_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")


# --------------------------------------------------------------------------- #
# Summary.
# --------------------------------------------------------------------------- #
def _rate(part: int, whole: int) -> Optional[float]:
    return round(part / whole, 3) if whole else None


def summarize_live(rows: list[dict[str, Any]]) -> dict[str, Any]:
    arms = sorted({r["arm"] for r in rows}, key=list(ARMS).index)
    out: dict[str, Any] = {}
    for arm in arms:
        cell = [r for r in rows if r["arm"] == arm and r.get("status") == "ok"]
        errors = sum(r["arm"] == arm and r.get("status") == "error" for r in rows)
        qa = [r for r in cell if r["category"] == "qa"]
        action = [r for r in cell if r["category"] == "action"]
        entry: dict[str, Any] = {
            "n_ok": len(cell),
            "n_error": errors,
            "accuracy": _rate(sum(r["correct"] for r in qa), len(qa)),
            "abstention_rate": _rate(sum(r["abstained"] for r in qa), len(qa)),
            "false_explanation_rate": _rate(
                sum(r["false_explanation"] for r in qa), len(qa)
            ),
            "mean_estimated_tokens": round(
                sum(r.get("estimated_tokens", 0) for r in cell) / len(cell)
            ) if cell else None,
            "mean_retrieval_calls": round(
                sum(r.get("retrieval_calls", 0) for r in cell) / len(cell), 2
            ) if cell else None,
            "mean_raster_pixels": round(
                sum(r.get("raster_pixels", 0) for r in cell) / len(cell)
            ) if cell else None,
            "mean_latency_s": round(
                sum(r.get("latency_s", 0) for r in cell) / len(cell), 2
            ) if cell else None,
        }
        if action:
            entry["action"] = {
                "n": len(action),
                "target_accuracy": _rate(
                    sum(r.get("target_correct", False) for r in action), len(action)
                ),
                "repair_attempted": sum(r.get("repair_attempted", False) for r in action),
                "repair_success": sum(r.get("repair_success", False) for r in action),
            }
        by_kind = {}
        for kind in sorted({r["kind"] for r in qa}):
            kind_rows = [r for r in qa if r["kind"] == kind]
            by_kind[kind] = _rate(sum(r["correct"] for r in kind_rows), len(kind_rows))
        entry["accuracy_by_kind"] = by_kind
        out[arm] = entry
    return out


# --------------------------------------------------------------------------- #
# Sweep driver.
# --------------------------------------------------------------------------- #
def _mock_runner(canvas: Canvas, instruction: str) -> dict[str, Any]:
    """Deterministic offline runner exercising every scoring path."""
    reply = json.dumps({"answer": ABSTAIN, "evidence": "mock run"})
    return {
        "reply": reply,
        "actions": [],
        "model": "mock",
        "reasoning_effort": None,
        "validation": {"passed": True, "repair_attempted": False},
        "perception_telemetry": {
            "bootstrap_chars": len(instruction),
            "perception_actions": 0,
            "estimated_tokens": len(instruction) // 4,
            "raster_pixels": 0,
        },
    }


_RUNNERS: dict[str, Runner] = {
    "codex": assistant.run_codex_cli,
    "claude": assistant.run_claude,
    "mock": _mock_runner,
}


def run_live(
    *,
    agent: str,
    kinds: list[str],
    per_kind: int,
    arms: list[str],
    seed: int,
    workers: int,
    ledger_path: Path,
    output: Optional[Path] = None,
    retry_failed: bool = False,
) -> dict[str, Any]:
    _forward_codex_home()
    runner = _RUNNERS[agent]
    model = assistant.CODEX_MODEL if agent == "codex" else (
        os.getenv("NEEH_CLAUDE_CLI_MODEL", "default-profile") if agent == "claude" else "mock"
    )
    tasks = build_tasks(kinds, per_kind, seed)
    controls = adversarial_controls(tasks)
    if not controls["leak_free"] or not controls["labels_disjoint_from_answers"]:
        raise SystemExit(f"adversarial controls failed: {controls}")

    ledger = load_ledger(ledger_path)
    planned: list[tuple[Task, str, str]] = []
    skipped = 0
    for task in tasks:
        for arm in arms:
            key = row_key(task, arm, agent, model, seed)
            existing = ledger.get(key)
            if existing is not None and (
                existing.get("status") == "ok"
                or (existing.get("status") == "error" and not retry_failed)
            ):
                skipped += 1
                continue
            planned.append((task, arm, key))

    print(
        f"live sweep: {len(planned)} calls planned, {skipped} already in ledger "
        f"({agent}/{model}, arms={arms})",
        file=sys.stderr,
    )
    completed: list[dict[str, Any]] = []
    # assistant.PERCEPTION_MODE is a module global, so parallelism stays within
    # one arm at a time: every in-flight call shares the same policy.
    for arm in arms:
        batch = [(t, k) for t, a, k in planned if a == arm]
        if not batch:
            continue
        previous = assistant.PERCEPTION_MODE
        assistant.PERCEPTION_MODE = _ARM_POLICY[arm]
        # Arm identity: the pixel-free arms must stay pixel-free, so the
        # assistant's bootstrap-raster heuristic (which fires on words like
        # "handwritten"/"symbol" in real-ink questions) is pinned off for them.
        previous_raster = os.environ.get("NEEH_BOOTSTRAP_RASTER")
        os.environ["NEEH_BOOTSTRAP_RASTER"] = (
            "never" if arm not in _RASTER_ARMS_LIVE else "auto"
        )
        try:
            with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
                futures = {
                    pool.submit(run_row, task, arm, runner, agent, seed): key
                    for task, key in batch
                }
                for future, key in futures.items():
                    record = future.result()
                    record["key"] = key
                    append_ledger(ledger_path, record)
                    completed.append(record)
                    status = record["status"]
                    flag = "" if status == "ok" else f" ({record.get('error', '')[:80]})"
                    print(f"  {key}: {status}{flag}", file=sys.stderr)
        finally:
            assistant.PERCEPTION_MODE = previous
            if previous_raster is None:
                os.environ.pop("NEEH_BOOTSTRAP_RASTER", None)
            else:
                os.environ["NEEH_BOOTSTRAP_RASTER"] = previous_raster

    # Score over the authoritative ledger view of this sweep's keys.
    ledger = load_ledger(ledger_path)
    sweep_rows = [
        ledger[row_key(task, arm, agent, model, seed)]
        for task in tasks
        for arm in arms
        if row_key(task, arm, agent, model, seed) in ledger
    ]
    report = {
        "agent": agent,
        "model": model,
        "seed": seed,
        "kinds": kinds,
        "per_kind": per_kind,
        "arms": arms,
        "calls_made": len(completed),
        "rows_scored": len(sweep_rows),
        "adversarial": controls,
        "summary": summarize_live(sweep_rows),
    }
    if agent == "codex":
        report["reasoning_effort"] = assistant.CODEX_REASONING_EFFORT
    elif agent == "claude":
        report["reasoning_effort"] = os.getenv("NEEH_CLAUDE_CLI_EFFORT", "default")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--agent", choices=sorted(_RUNNERS), default="mock")
    parser.add_argument(
        "--kinds", nargs="+", choices=list(_BUILDERS), default=available_kinds()
    )
    parser.add_argument("--per-kind", type=int, default=6)
    parser.add_argument("--arms", nargs="+", choices=list(ARMS), default=list(ARMS))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="one task per real-ink kind over three arms (~18 calls)",
    )
    args = parser.parse_args()

    kinds, per_kind, arms = args.kinds, args.per_kind, args.arms
    if args.smoke:
        kinds = [k for k in _REAL_INK_KINDS if k in _BUILDERS]
        per_kind = 1
        arms = [a for a in SMOKE_ARMS]

    report = run_live(
        agent=args.agent,
        kinds=kinds,
        per_kind=per_kind,
        arms=arms,
        seed=args.seed,
        workers=args.workers,
        ledger_path=args.ledger,
        output=args.output,
        retry_failed=args.retry_failed,
    )
    print(json.dumps({"summary": report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
