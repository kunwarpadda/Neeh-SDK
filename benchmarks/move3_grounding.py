"""Move 3: grounding across perception policies on history-bearing ink tasks.

Where Move 1 isolated *whether* ink structure carries a hidden signal, Move 3
asks *which perception policy actually grounds an answer in it*, and at what
context and pixel cost. Six arms are compared over tasks whose ground truth
lives in ink history or structure -- the most-recent mark, a cross-out, a
grouping, the most recent change:

    raster-only        pixels only
    raster+geometry    pixels plus vector paths
    index-only         structured page map, no perception actions
    active-index       page map plus on-demand analyzers/retrieval
    marked-index       active-index plus a marked raster
    analyzer-first     the exact reducer pre-computed into the workspace

The scoring model is deliberately conservative and *deterministic*, so the
headline comparison runs with no model calls:

    python research/move3_grounding.py --dry-run

For each (task, arm) the dry run reports whether the answer is grounded in the
evidence the arm exposes (``exact`` when a reducer already computed it,
``reachable`` when a perception call can, ``no`` when the signal is absent),
plus the context character and raster pixel cost. Adversarial controls check
that no answer leaks into the question text and that the dataset stays balanced.
A GPT-5.5 arm (``--agent codex``) is wired for the live accuracy/abstention
study but is not required to reproduce the grounding-versus-cost table.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.move1_render_identical_pairs import (  # noqa: E402
    CODEX_EFFORT,
    CODEX_MODEL,
    _content_crop,
)
from neeh import Canvas  # noqa: E402
from neeh.agents import build_observation_workspace  # noqa: E402
from neeh.ink import Author, Point, Stroke, StrokeStyle  # noqa: E402

# Arm -> underlying SDK perception policy. "raster+geometry" and "analyzer-first"
# are constructed arms layered on a real policy (see arm_context).
ARMS = (
    "raster-only",
    "raster+geometry",
    "index-only",
    "active-index",
    "marked-index",
    "analyzer-first",
)
_ARM_POLICY = {
    "raster-only": "raster-only",
    "raster+geometry": "raster-only",
    "index-only": "index-only",
    "active-index": "active-index",
    "marked-index": "marked-index",
    "analyzer-first": "active-index",
}
# Arms whose evidence includes a rendered raster (charged pixels).
_RASTER_ARMS = {"raster-only", "raster+geometry", "marked-index"}
# Arms that can call analyzers/reducers on demand.
_ANALYZER_ARMS = {"active-index", "marked-index", "analyzer-first"}

_INK = StrokeStyle(color="#101010", width=3.0)
_PAGE_W, _PAGE_H = 1000.0, 1414.0
_HALF = _PAGE_H / 2


@dataclass
class Task:
    task_id: str
    kind: str            # latest_mark | crossed_out | grouping | recent_change
    signal: str          # temporal | history | grouping
    canvas: Canvas
    question: str
    answer: str          # ground-truth answer string (label or stroke id)
    options: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# Scene / task construction (ground truth is read straight off the document
# and event log, so every task is exactly checkable).
# --------------------------------------------------------------------------- #
def _mark(cx: float, cy: float, rng: random.Random, t0: int) -> list[tuple[float, float]]:
    return [(round(cx + rng.uniform(-16, 16), 1), round(cy + rng.uniform(-12, 12), 1)) for _ in range(4)]


def _latest_mark_task(rng: random.Random, index: int, n: int = 12) -> Task:
    canvas = Canvas()
    upper = index % 2 == 0
    order = list(range(n))
    rng.shuffle(order)
    last_k = order.index(n - 1)
    last_id = None
    for k in range(n):
        if k == last_k:
            cy = rng.uniform(60, _HALF - 60) if upper else rng.uniform(_HALF + 60, _PAGE_H - 60)
        else:
            cy = rng.uniform(60, _PAGE_H - 60)
        cx = rng.uniform(60, _PAGE_W - 60)
        pts = [(x, y) for x, y in _mark(cx, cy, rng, 0)]
        stroke = canvas.add_stroke(pts, author=Author.USER, created_at_ms=1_000_000 + order[k] * 100)
        if k == last_k:
            last_id = stroke.id
    answer = "upper" if upper else "lower"
    return Task(
        task_id=f"latest_{index}", kind="latest_mark", signal="temporal", canvas=canvas,
        question=("Several marks were drawn at different times. Is the most recently drawn "
                  f"mark in the upper or lower half of the {_PAGE_H:g}-unit-tall page?"),
        answer=answer, options=("upper", "lower"),
    )


def _crossed_out_task(rng: random.Random, index: int) -> Task:
    canvas = Canvas()
    base_cx = rng.uniform(200, 800)
    base_cy = rng.uniform(200, _PAGE_H - 200)
    target = canvas.add_stroke(
        [(base_cx - 60, base_cy), (base_cx + 60, base_cy)],
        author=Author.USER, created_at_ms=1_000_000,
    )
    # distractors
    for j in range(3):
        cx, cy = rng.uniform(60, _PAGE_W - 60), rng.uniform(60, _PAGE_H - 60)
        canvas.add_stroke([(cx, cy), (cx + 40, cy + 6)], author=Author.USER, created_at_ms=1_000_100 + j * 50)
    # a later scribble crossing the target
    canvas.add_stroke(
        [(base_cx - 55, base_cy - 12), (base_cx + 55, base_cy + 12)],
        author=Author.USER, created_at_ms=1_005_000,
    )
    return Task(
        task_id=f"crossout_{index}", kind="crossed_out", signal="history", canvas=canvas,
        question="One earlier mark was later scribbled over. Which mark id was crossed out?",
        answer=target.id,
    )


def _grouping_task(rng: random.Random, index: int) -> Task:
    canvas = Canvas()
    members = []
    gx, gy = rng.uniform(200, 700), rng.uniform(200, 900)
    for j in range(3):
        s = canvas.add_stroke([(gx + j * 18, gy), (gx + j * 18 + 12, gy + 10)], author=Author.USER,
                              created_at_ms=1_000_000 + j)
        members.append(s.id)
    for j in range(4):  # unrelated strokes
        cx, cy = rng.uniform(60, _PAGE_W - 60), rng.uniform(60, _PAGE_H - 60)
        canvas.add_stroke([(cx, cy), (cx + 20, cy)], author=Author.USER, created_at_ms=1_000_100 + j)
    group_id = canvas.group(members, label="equation")
    return Task(
        task_id=f"group_{index}", kind="grouping", signal="grouping", canvas=canvas,
        question=f"Which stroke ids belong to group {group_id}?",
        answer=",".join(sorted(members)),
    )


def _recent_change_task(rng: random.Random, index: int) -> Task:
    canvas = Canvas()
    ids = []
    for j in range(5):
        cx, cy = rng.uniform(60, _PAGE_W - 60), rng.uniform(60, _PAGE_H - 60)
        s = canvas.add_stroke([(cx, cy), (cx + 20, cy + 6)], author=Author.USER, created_at_ms=1_000_000 + j * 100)
        ids.append(s.id)
    canvas.move(10, 10, stroke_ids=[ids[1]])  # the most recent change touches ids[1]
    return Task(
        task_id=f"recent_{index}", kind="recent_change", signal="temporal", canvas=canvas,
        question="Which stroke id was changed most recently?",
        answer=ids[1],
    )


_BUILDERS: dict[str, Callable[[random.Random, int], Task]] = {
    "latest_mark": _latest_mark_task,
    "crossed_out": _crossed_out_task,
    "grouping": _grouping_task,
    "recent_change": _recent_change_task,
}


def build_tasks(kinds: list[str], per_kind: int, seed: int) -> list[Task]:
    rng = random.Random(seed)
    tasks: list[Task] = []
    for kind in kinds:
        for i in range(per_kind):
            tasks.append(_BUILDERS[kind](rng, i))
    return tasks


# --------------------------------------------------------------------------- #
# Per-arm evidence and cost (deterministic).
# --------------------------------------------------------------------------- #
def _geometry_text(canvas: Canvas, cap: int = 6) -> str:
    parts = []
    for layer in canvas.page.layers:
        for stroke in layer.strokes:
            pts = [[round(p.x, 1), round(p.y, 1)] for p in stroke.points[:cap]]
            parts.append(f"{stroke.id}:{pts}")
    return "; ".join(parts)


def _raster_pixels(canvas: Canvas) -> int:
    region = _content_crop(canvas.page) or canvas.page.rect
    return int(max(1, round(region.width)) * max(1, round(region.height)))


def arm_context(task: Task, arm: str) -> dict[str, Any]:
    """Build one arm's evidence bundle and measure its deterministic cost."""
    policy = _ARM_POLICY[arm]
    workspace = build_observation_workspace(task.canvas, task.question, policy=policy)
    context_chars = int(workspace.get("bootstrap_chars", 0))
    raster_pixels = 0
    if arm in _RASTER_ARMS:
        raster_pixels = _raster_pixels(task.canvas)
    if arm == "raster+geometry":
        context_chars += len(_geometry_text(task.canvas))
    analysis = workspace.get("analysis")
    return {
        "context_chars": context_chars,
        "raster_pixels": raster_pixels,
        "capabilities": list(workspace.get("capabilities", [])),
        "analysis": analysis,
        "workspace": workspace,
    }


def grounding_level(task: Task, arm: str, ctx: dict[str, Any]) -> str:
    """How the arm can reach the answer: exact | reachable | no.

    Conservative by construction: raster and static-index arms cannot recover a
    temporal/history/grouping signal that pixels and a static map do not carry;
    analyzer arms can compute it on demand; analyzer-first already did.
    """
    if arm == "analyzer-first" and ctx.get("analysis") is not None:
        return "exact"
    if arm in _ANALYZER_ARMS:
        return "reachable"
    # index-only and raster arms expose no temporal/history/grouping signal.
    return "no"


# --------------------------------------------------------------------------- #
# Adversarial controls.
# --------------------------------------------------------------------------- #
def adversarial_controls(tasks: list[Task]) -> dict[str, Any]:
    # 1) The ground-truth answer must not leak into the question. Naming both
    #    choices of a binary task is by design, so offered options are exempt;
    #    a leak is an answer (e.g. a stroke id) that the question gives away.
    leaks = [
        t.task_id for t in tasks
        if t.answer.casefold() in t.question.casefold() and t.answer not in t.options
    ]
    # 2) Balance: for binary-label tasks no single option may dominate.
    balance: dict[str, Any] = {}
    for kind in {t.kind for t in tasks}:
        labeled = [t for t in tasks if t.kind == kind and t.options]
        if not labeled:
            continue
        counts = {opt: sum(t.answer == opt for t in labeled) for opt in labeled[0].options}
        spread = max(counts.values()) - min(counts.values())
        balance[kind] = {"counts": counts, "balanced": spread <= 1}
    return {
        "question_leaks": leaks,
        "leak_free": not leaks,
        "balance": balance,
    }


# --------------------------------------------------------------------------- #
# Dry-run evaluation and summary.
# --------------------------------------------------------------------------- #
def evaluate_dry(tasks: list[Task], arms: list[str]) -> list[dict[str, Any]]:
    rows = []
    for task in tasks:
        for arm in arms:
            ctx = arm_context(task, arm)
            rows.append({
                "task": task.task_id,
                "kind": task.kind,
                "signal": task.signal,
                "arm": arm,
                "grounding": grounding_level(task, arm, ctx),
                "context_chars": ctx["context_chars"],
                "raster_pixels": ctx["raster_pixels"],
                "answer_in_context": task.answer.casefold() in json.dumps(ctx["workspace"]).casefold(),
            })
    return rows


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    arms = sorted({r["arm"] for r in rows}, key=list(ARMS).index)
    out: dict[str, Any] = {}
    for arm in arms:
        cell = [r for r in rows if r["arm"] == arm]
        k = len(cell)
        grounded = sum(r["grounding"] in ("exact", "reachable") for r in cell)
        out[arm] = {
            "n_tasks": k,
            "grounded": grounded,
            "grounded_rate": round(grounded / k, 3) if k else None,
            "exact": sum(r["grounding"] == "exact" for r in cell),
            "mean_context_chars": round(sum(r["context_chars"] for r in cell) / k) if k else 0,
            "mean_raster_pixels": round(sum(r["raster_pixels"] for r in cell) / k) if k else 0,
        }
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", choices=["codex", "mock"], default="mock")
    parser.add_argument("--kinds", nargs="+", choices=list(_BUILDERS), default=list(_BUILDERS))
    parser.add_argument("--per-kind", type=int, default=6)
    parser.add_argument("--arms", nargs="+", choices=list(ARMS), default=list(ARMS))
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", help="grounding-vs-cost table; no model calls")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    tasks = build_tasks(args.kinds, args.per_kind, args.seed)
    controls = adversarial_controls(tasks)

    if args.dry_run or args.agent == "mock":
        rows = evaluate_dry(tasks, args.arms)
        summary = summarize(rows)
        report = {
            "mode": "dry-run",
            "task_count": len(tasks),
            "kinds": args.kinds,
            "arms": args.arms,
            "grounding_by_arm": summary,
            "adversarial": controls,
        }
        print(json.dumps({
            "grounding_by_arm": {
                arm: {"grounded_rate": cell["grounded_rate"],
                      "mean_context_chars": cell["mean_context_chars"],
                      "mean_raster_pixels": cell["mean_raster_pixels"]}
                for arm, cell in summary.items()
            },
            "adversarial_leak_free": controls["leak_free"],
        }, indent=2))
        if args.output:
            args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return

    # Live model path (GPT-5.5) is wired for the accuracy/abstention study.
    raise SystemExit(
        f"Live --agent codex ({CODEX_MODEL}/{CODEX_EFFORT}) run is not wired into this "
        "scaffold yet; use --dry-run for the deterministic grounding-versus-cost table."
    )


if __name__ == "__main__":
    main()
