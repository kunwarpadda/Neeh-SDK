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

from benchmarks.move1_render_identical_pairs import _content_crop  # noqa: E402
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
    kind: str            # latest_mark | crossed_out | ... | mw_erased_rewrite
    signal: str          # temporal | history | grouping
    canvas: Canvas
    question: str
    answer: str          # ground-truth answer string (label or stroke id(s))
    options: tuple[str, ...] = ()
    category: str = "qa"                       # qa | action
    expected_tool: str = ""                    # action tasks: required tool
    expected_target_ids: tuple[str, ...] = ()  # action tasks: required targets
    source_labels: tuple[str, ...] = ()        # dataset labels used to build the scene


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


# --------------------------------------------------------------------------- #
# Real ink (M3): MathWriting samples with scripted, event-logged histories.
#
# The geometry, per-point timing, and pen-down order are a real writer's; the
# *history* (a later strike, an erase-and-rewrite, a grouping, a move) is
# scripted on top so ground truth stays exactly checkable off the document and
# event log. Questions never ask for transcription, so memorizing MathWriting
# labels cannot produce an answer (see adversarial_controls).
# --------------------------------------------------------------------------- #
MATHWRITING_ROOT = Path(
    os.getenv(
        "NEEH_MATHWRITING_ROOT",
        str(
            Path(__file__).resolve().parent.parent
            / "research/data/mathwriting/excerpt/mathwriting-2024-excerpt"
        ),
    )
)
_POOLS: dict[str, list] = {}


def _mathwriting_pool(which: str) -> list:
    """Deterministic, cached sample pools (sorted file order, human ink only)."""
    if which in _POOLS:
        return _POOLS[which]
    if not MATHWRITING_ROOT.is_dir():
        raise SystemExit(
            f"MathWriting data not found at {MATHWRITING_ROOT}. Download and extract "
            "the excerpt (see benchmarks/ink_datasets.py) or set NEEH_MATHWRITING_ROOT."
        )
    from benchmarks.ink_datasets import iter_mathwriting

    if which == "symbol":
        pool = [
            s for s in iter_mathwriting(MATHWRITING_ROOT, "symbols")
            if len(s.strokes) == 1
        ]
    elif which == "expression":
        pool = [
            s for s in iter_mathwriting(MATHWRITING_ROOT, "train")
            if 5 <= len(s.strokes) <= 25
        ]
    else:
        raise ValueError(f"unknown pool {which!r}")
    if len(pool) < 8:
        raise SystemExit(f"MathWriting pool {which!r} too small ({len(pool)} samples)")
    _POOLS[which] = pool
    return pool


def _scatter(rng: random.Random, n: int, half: Optional[str] = None) -> list[tuple[float, float]]:
    """n well-separated symbol centers; the LAST one confined to `half` if given."""
    centers: list[tuple[float, float]] = []
    for i in range(n):
        confined = half if i == n - 1 else None
        for _ in range(200):
            cx = rng.uniform(150, _PAGE_W - 150)
            if confined == "upper":
                cy = rng.uniform(140, _HALF - 110)
            elif confined == "lower":
                cy = rng.uniform(_HALF + 110, _PAGE_H - 140)
            else:
                cy = rng.uniform(140, _PAGE_H - 140)
            if all((cx - x) ** 2 + (cy - y) ** 2 >= 190**2 for x, y in centers):
                break
        centers.append((cx, cy))
    return centers


def _place_symbols(
    canvas: Canvas,
    rng: random.Random,
    samples: list,
    centers: list[tuple[float, float]],
    order: list[int],
) -> list:
    """Write one single-stroke symbol per center; creation order per `order`."""
    from benchmarks.ink_datasets import write_sample

    strokes = []
    for i, (sample, (cx, cy)) in enumerate(zip(samples, centers)):
        box = (cx - 75, cy - 60, cx + 75, cy + 60)
        added = write_sample(
            canvas, sample, box, time_base_ms=1_000_000 + order[i] * 20_000
        )
        strokes.append(added[0])
    return strokes


def _mw_latest_symbol_task(rng: random.Random, index: int, n: int = 8) -> Task:
    pool = _mathwriting_pool("symbol")
    samples = rng.sample(pool, n)
    half = "upper" if index % 2 == 0 else "lower"
    centers = _scatter(rng, n, half=half)
    order = list(range(n))
    rng.shuffle(order)
    # The symbol at the confined center (list position n-1) must be newest.
    newest_pos = order.index(n - 1)
    order[newest_pos], order[n - 1] = order[n - 1], order[newest_pos]
    canvas = Canvas()
    _place_symbols(canvas, rng, samples, centers, order)
    return Task(
        task_id=f"mw_latest_{index}", kind="mw_latest_symbol", signal="temporal",
        canvas=canvas,
        question=("Several handwritten symbols were drawn at different times. Is the "
                  f"most recently drawn symbol in the upper or lower half of the "
                  f"{_PAGE_H:g}-unit-tall page?"),
        answer=half, options=("upper", "lower"),
        source_labels=tuple(s.label for s in samples),
    )


def _mw_crossed_scene(rng: random.Random) -> tuple[Canvas, str, tuple[str, ...]]:
    pool = _mathwriting_pool("symbol")
    samples = rng.sample(pool, 4)
    centers = _scatter(rng, 4)
    canvas = Canvas()
    strokes = _place_symbols(canvas, rng, samples, centers, list(range(4)))
    target = strokes[rng.randrange(4)]
    box = target.bbox
    cy = (box.min_y + box.max_y) / 2
    canvas.add_stroke(
        [
            [box.min_x - 12, cy + rng.uniform(-8, 8), 0],
            [(box.min_x + box.max_x) / 2, cy + rng.uniform(-6, 6), 90],
            [box.max_x + 12, cy + rng.uniform(-8, 8), 200],
        ],
        author=Author.USER, created_at_ms=1_400_000,
    )
    return canvas, target.id, tuple(s.label for s in samples)


def _mw_crossed_out_task(rng: random.Random, index: int) -> Task:
    canvas, target_id, labels = _mw_crossed_scene(rng)
    return Task(
        task_id=f"mw_crossout_{index}", kind="mw_crossed_out", signal="history",
        canvas=canvas,
        question=("One handwritten symbol was later struck through. "
                  "Which stroke id was crossed out?"),
        answer=target_id, source_labels=labels,
    )


def _mw_erased_rewrite_task(rng: random.Random, index: int) -> Task:
    from benchmarks.ink_datasets import write_sample

    pool = _mathwriting_pool("expression")
    sample = pool[(index * 7 + rng.randrange(3)) % len(pool)]
    canvas = Canvas()
    strokes = write_sample(canvas, sample, (150, 450, 850, 950), time_base_ms=1_000_000)
    erased = strokes[rng.randrange(len(strokes))]
    canvas.erase([erased.id])
    replacement = canvas.add_stroke(
        [[p.x + 6, p.y + 4, p.t_ms] for p in erased.points],
        author=Author.USER, created_at_ms=1_600_000,
    )
    return Task(
        task_id=f"mw_erased_{index}", kind="mw_erased_rewrite", signal="history",
        canvas=canvas,
        question=("One stroke of this handwritten expression was erased and then "
                  "rewritten. Which stroke id is the rewritten replacement?"),
        answer=replacement.id, source_labels=(sample.label,),
    )


def _mw_grouping_task(rng: random.Random, index: int) -> Task:
    from benchmarks.ink_datasets import write_sample

    expr_pool = _mathwriting_pool("expression")
    sym_pool = _mathwriting_pool("symbol")
    sample = expr_pool[(index * 5 + rng.randrange(3)) % len(expr_pool)]
    canvas = Canvas()
    strokes = write_sample(canvas, sample, (200, 450, 800, 850), time_base_ms=1_000_000)
    for i, sym in enumerate(rng.sample(sym_pool, 2)):
        cy = 200 if i == 0 else 1150
        write_sample(canvas, sym, (400, cy - 60, 550, cy + 60),
                     time_base_ms=1_100_000 + i * 30_000)
    member_ids = [s.id for s in strokes]
    group_id = canvas.group(member_ids, label="expression")
    return Task(
        task_id=f"mw_group_{index}", kind="mw_grouping", signal="grouping",
        canvas=canvas,
        question=f"Which stroke ids belong to group {group_id}?",
        answer=",".join(sorted(member_ids)), source_labels=(sample.label,),
    )


def _mw_recent_change_task(rng: random.Random, index: int) -> Task:
    from benchmarks.ink_datasets import write_sample

    expr_pool = _mathwriting_pool("expression")
    sym_pool = _mathwriting_pool("symbol")
    sample = expr_pool[(index * 3 + rng.randrange(3)) % len(expr_pool)]
    canvas = Canvas()
    write_sample(canvas, sample, (150, 500, 850, 900), time_base_ms=1_000_000)
    symbols = _place_symbols(
        canvas, rng, rng.sample(sym_pool, 2),
        [(rng.uniform(200, 800), 200), (rng.uniform(200, 800), 1180)],
        [1, 2],
    )
    moved = symbols[rng.randrange(2)]
    canvas.move(12, 8, stroke_ids=[moved.id])
    return Task(
        task_id=f"mw_recent_{index}", kind="mw_recent_change", signal="temporal",
        canvas=canvas,
        question="Which stroke id was changed most recently?",
        answer=moved.id, source_labels=(sample.label,),
    )


def _mw_annotate_crossed_task(rng: random.Random, index: int) -> Task:
    canvas, target_id, labels = _mw_crossed_scene(rng)
    return Task(
        task_id=f"mw_annotate_{index}", kind="mw_annotate_crossed", signal="history",
        canvas=canvas,
        question="Annotate the symbol that was crossed out with the note 'removed'.",
        answer=target_id, category="action",
        expected_tool="annotate", expected_target_ids=(target_id,),
        source_labels=labels,
    )


# --------------------------------------------------------------------------- #
# Real ink (M3): genuine device recordings.
#
# Unlike the MathWriting arms above, nothing here is scripted: the geometry,
# timing, AND history (an eraser stroke the writer actually made) are the
# writer's own. Ground truth is read straight off the imported event log, so
# it stays exactly checkable while carrying zero synthetic staging.
# --------------------------------------------------------------------------- #
DEVICE_CAPTURE_ROOT = Path(
    os.getenv(
        "NEEH_DEVICE_CAPTURE_ROOT",
        str(Path(__file__).resolve().parent.parent / "research/data/device/raw"),
    )
)
_DEVICE_CAPTURES: dict[str, Any] = {}


def _device_capture(session: str):
    """Load and cache one research/data/device/raw/<session> bundle."""
    if session in _DEVICE_CAPTURES:
        return _DEVICE_CAPTURES[session]
    session_dir = DEVICE_CAPTURE_ROOT / session
    bundles = sorted(session_dir.glob("*.neeh-capture.zip"))
    if not bundles:
        raise SystemExit(
            f"no device capture bundle for session {session!r} under {session_dir}"
        )
    from neeh.adapters.device_capture import load_device_capture

    imported = load_device_capture(bundles[0])
    _DEVICE_CAPTURES[session] = imported
    return imported


def _device_capture_available(session: str) -> bool:
    session_dir = DEVICE_CAPTURE_ROOT / session
    return session_dir.is_dir() and any(session_dir.glob("*.neeh-capture.zip"))


# RECORDING.md's six sessions, in script order. Later ones may not be
# recorded yet -- _available_device_capture_sessions() filters to what
# actually exists on disk, so task pools grow automatically as more land.
_DEVICE_CAPTURE_SESSIONS = (
    "s1_notes", "s2_math", "s3_diagram", "s4_dense", "s5_edit", "s6_crossouts",
)


def _available_device_capture_sessions() -> list[str]:
    return [s for s in _DEVICE_CAPTURE_SESSIONS if _device_capture_available(s)]


def _dc_erased_ink_task(rng: random.Random, index: int) -> Task:
    sessions = _available_device_capture_sessions()
    if not sessions:
        raise SystemExit("no device capture sessions available for dc_erased_ink")
    session = sessions[index % len(sessions)]
    imported = _device_capture(session)
    erased_ids = sorted({
        stroke_id
        for event in imported.event_log.events
        if event.kind == "erase"
        for stroke_id in event.removed_ids
    })
    if not erased_ids:
        raise SystemExit(f"{session} capture has no erase history to build dc_erased_ink from")
    target_id = erased_ids[(index // len(sessions)) % len(erased_ids)]
    return Task(
        task_id=f"dc_erased_{index}", kind="dc_erased_ink", signal="history",
        canvas=imported.canvas,
        question=(
            "This is a real handwritten notes page recorded on a tablet. One "
            "stroke on this page was erased with the eraser. Which stroke id "
            "was erased?"
        ),
        answer=target_id,
    )


def _dc_recent_change_task(rng: random.Random, index: int) -> Task:
    sessions = _available_device_capture_sessions()
    if not sessions:
        raise SystemExit("no device capture sessions available for dc_recent_change")
    session = sessions[index % len(sessions)]
    imported = _device_capture(session)
    events = [
        event for event in imported.event_log.events
        if event.kind in ("add", "erase") and (event.added_ids or event.removed_ids)
    ]
    if not events:
        raise SystemExit(f"{session} capture has no add/erase history for dc_recent_change")
    latest = events[-1]
    target_id = (latest.added_ids or latest.removed_ids)[0]
    return Task(
        task_id=f"dc_recent_{index}", kind="dc_recent_change", signal="temporal",
        canvas=imported.canvas,
        question=(
            "This is a real handwritten notes page recorded on a tablet. "
            "Which stroke id reflects the single most recent change (a new "
            "stroke or an erase) made to this page?"
        ),
        answer=target_id,
    )


_BUILDERS: dict[str, Callable[[random.Random, int], Task]] = {
    "latest_mark": _latest_mark_task,
    "crossed_out": _crossed_out_task,
    "grouping": _grouping_task,
    "recent_change": _recent_change_task,
    "mw_latest_symbol": _mw_latest_symbol_task,
    "mw_crossed_out": _mw_crossed_out_task,
    "mw_erased_rewrite": _mw_erased_rewrite_task,
    "mw_grouping": _mw_grouping_task,
    "mw_recent_change": _mw_recent_change_task,
    "mw_annotate_crossed": _mw_annotate_crossed_task,
    "dc_erased_ink": _dc_erased_ink_task,
    "dc_recent_change": _dc_recent_change_task,
}
_REAL_INK_KINDS = tuple(k for k in _BUILDERS if k.startswith("mw_"))
_DEVICE_CAPTURE_KINDS = tuple(k for k in _BUILDERS if k.startswith("dc_"))


def available_kinds() -> list[str]:
    """All kinds whose backing dataset is present on this machine."""
    kinds = [
        k for k in _BUILDERS
        if k not in _REAL_INK_KINDS and k not in _DEVICE_CAPTURE_KINDS
    ]
    if MATHWRITING_ROOT.is_dir():
        kinds += list(_REAL_INK_KINDS)
    if _available_device_capture_sessions():
        kinds += list(_DEVICE_CAPTURE_KINDS)
    return kinds


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

    Conservative by construction: raster and static-index arms cannot recover
    a temporal/history signal that pixels and a static map do not carry;
    analyzer arms can compute it on demand; analyzer-first already did. One
    exception is measured, not assumed: *recorded* group membership rides
    verbatim in the static page map, so a grouping question over recorded
    groups is grounded for every index-bearing arm, including index-only.
    """
    if arm == "analyzer-first" and ctx.get("analysis") is not None:
        return "exact"
    if arm in _ANALYZER_ARMS:
        return "reachable"
    if arm == "index-only" and task.signal == "grouping" and task.canvas.groups():
        return "exact"  # membership is already in the bootstrap page map
    # Remaining index/raster arms expose no temporal/history signal.
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
    # 3) Contamination: answers must be document addresses (ids, halves), never
    #    dataset transcriptions — so a model that memorized MathWriting labels
    #    gains nothing. A violation is an answer that IS a source label, or
    #    contains a non-trivial one (single-character symbol labels collide with
    #    random id characters and cannot constitute a transcription).
    def _contains_label(answer: str, label: str) -> bool:
        label = label.casefold().strip()
        if not label:
            return False
        return label == answer.casefold() or (
            len(label) >= 3 and label in answer.casefold()
        )

    contaminated = [
        t.task_id for t in tasks
        if any(_contains_label(t.answer, label) for label in t.source_labels)
    ]
    return {
        "question_leaks": leaks,
        "leak_free": not leaks,
        "balance": balance,
        "label_contamination": contaminated,
        "labels_disjoint_from_answers": not contaminated,
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
    parser.add_argument("--kinds", nargs="+", choices=list(_BUILDERS), default=available_kinds())
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

    # Live accuracy/abstention arm (gpt-5.5/high through the codex CLI login).
    from benchmarks.move3_live import DEFAULT_LEDGER, run_live

    report = run_live(
        agent=args.agent,
        kinds=args.kinds,
        per_kind=args.per_kind,
        arms=args.arms,
        seed=args.seed,
        workers=4,
        ledger_path=DEFAULT_LEDGER,
        output=args.output,
    )
    print(json.dumps({"summary": report["summary"]}, indent=2))


if __name__ == "__main__":
    main()
