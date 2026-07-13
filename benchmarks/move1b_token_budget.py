"""Move 1b: the token-budget stress test — where per-point ink serialization breaks.

Move 1 showed that on sparse pages a plain coordinate serialization recovers the
ink-only signal at ~1/3 the tokens of PNG+structure. This experiment tests what
happens on **dense pages**, where serializing every point scales linearly. The
live result showed that a compact index still stays accurate; the decisive
comparison is now against a deterministic task reducer whose output is bounded.

The task is temporal and needs the whole page: N marks are each drawn at a
distinct time; the model must locate the mark drawn LAST and report whether it
sits in the upper or lower half. A PNG has no timestamps (floor). Two structured
representations carry the answer with very different scaling:

    png            dense raster only                     -> floor (no timing)
    coords-full    every mark's (x,y,t,pressure) stream  -> grows ~linearly with N
    index-compact  every mark as {i, created_at_ms, center} -> grows linearly
    analyzer-reduced exact latest-mark reducer              -> bounded O(1) evidence

The token-vs-N crossover is deterministic, so ``--dry-run`` produces the headline
(where coords-full crosses a budget line and index-compact does not) with no model
calls. A live sweep additionally measures whether accuracy degrades as the
relevant timestamp gets buried among N distractors.

    python research/move1b_token_budget.py --dry-run
    python research/move1b_token_budget.py --agent codex --sizes 4 16 48 128 \
        --trials-per-size 6 --output research/tmp/move1b.json

Codex runs pin model=gpt-5.5 at reasoning_effort=high (see move1 module).
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Allow `python research/move1b_token_budget.py` to import the sibling research
# module by putting the repo root (not research/) on the path.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.move1_render_identical_pairs import (
    CODEX_EFFORT,
    CODEX_MODEL,
    ModelUnavailableError,
    _content_crop,
    _sample_points,
    run_codex,
)
from neeh.agents import analyze_ink
from neeh.canvas import Canvas
from neeh.document import Document, Layer, Page
from neeh.ink import Author, Point, Stroke, StrokeStyle
from neeh.rendering.png import render_page_png

CONDITIONS = ("png", "coords-full", "index-compact", "analyzer-reduced")
# A representative small-context budget line, in tokens, for the crossover plot.
DEFAULT_BUDGET_TOKENS = 8000
_INK = StrokeStyle(color="#101010", width=3.0)
_PAGE_W, _PAGE_H = 1000.0, 1414.0
_HALF = _PAGE_H / 2


@dataclass(frozen=True)
class Scene:
    scene_id: str
    n: int
    page: Page
    question: str
    options: tuple[str, str]
    answer: str  # half containing the last-drawn mark


def _mark(cx: float, cy: float, rng: random.Random, created_at_ms: int) -> Stroke:
    """A small multi-point squiggle centred near (cx, cy)."""
    pts = []
    for i in range(4):
        x = cx + rng.uniform(-18, 18)
        y = cy + rng.uniform(-14, 14)
        pts.append(Point(x=round(x, 1), y=round(y, 1), t_ms=i * 30, pressure=1.0))
    return Stroke(points=tuple(pts), style=_INK, author=Author.USER, created_at_ms=created_at_ms)


def build_scene(rng: random.Random, n: int, index: int, last_upper: bool) -> Scene:
    """N marks, each drawn at a distinct time. The last-drawn mark is forced into
    the chosen half so the dataset stays balanced (png must be at chance)."""
    base, step = 1_000_000, 100
    draw_rank = list(range(n))
    rng.shuffle(draw_rank)  # draw_rank[k] = when mark k was drawn (0..n-1)
    last_k = draw_rank.index(n - 1)
    strokes: list[Stroke] = []
    for k in range(n):
        if k == last_k:
            cy = rng.uniform(60, _HALF - 60) if last_upper else rng.uniform(_HALF + 60, _PAGE_H - 60)
        else:
            cy = rng.uniform(60, _PAGE_H - 60)
        cx = rng.uniform(60, _PAGE_W - 60)
        strokes.append(_mark(cx, cy, rng, created_at_ms=base + draw_rank[k] * step))
    page = Page(layers=[Layer(name="ink", strokes=strokes)])
    q = (f"The page has {n} pen marks, each drawn at a different time. Consider the "
         "mark drawn LAST (the most recent one). Is that mark in the upper half or "
         f"the lower half of the page? The page is {_PAGE_H:g} units tall, so a mark "
         f"whose centre y is below {_HALF:g} is in the upper half.")
    return Scene(f"n{n}-{index}", n, page, q, ("upper", "lower"),
                 "upper" if last_upper else "lower")


def build_scenes(sizes: list[int], trials_per_size: int, seed: int) -> list[Scene]:
    rng = random.Random(seed)
    scenes: list[Scene] = []
    for n in sizes:
        for i in range(trials_per_size):
            scenes.append(build_scene(rng, n, i, last_upper=(i % 2 == 0)))
    return scenes


# --------------------------------------------------------------------------- #
# Perception channels
# --------------------------------------------------------------------------- #
def _coords_full(page: Page, cap: int) -> str:
    lines = []
    for k, s in enumerate(page.all_strokes()):
        pts = " ".join(f"({x:g},{y:g},{t},{p:g})" for x, y, t, p in _sample_points(s, cap))
        lines.append(f"mark{k} created_at_ms={s.created_at_ms}: {pts}")
    return "\n".join(lines)


def _index_compact(page: Page) -> str:
    records = []
    for k, s in enumerate(page.all_strokes()):
        cx, cy = s.bbox.center
        records.append({"i": k, "created_at_ms": s.created_at_ms,
                        "center": [round(cx, 1), round(cy, 1)]})
    return json.dumps(records, separators=(",", ":"))


def _analyzer_reduced(page: Page) -> str:
    """Use Neeh's product reducer; page size does not change output cardinality."""
    canvas = Canvas(Document(pages=[page]))
    return json.dumps(analyze_ink(canvas, "latest_mark"), separators=(",", ":"))


_PREAMBLE = (
    "You are analyzing digital ink on a notebook page. Answer with exactly one of "
    "the allowed options. Coordinates are page units, (0,0) at top-left, x right, "
    "y down. created_at_ms is the absolute time a mark was drawn."
)


def build_prompt(scene: Scene, condition: str, cap: int) -> str:
    ask = (f"Question: {scene.question}\nAllowed options: 'upper' or 'lower'.\n"
           "Respond with JSON: {\"answer\": <one option>, \"why\": <one sentence>}.")
    if condition == "png":
        body = "Perception: a rendered image of the page is attached. No timing is provided."
    elif condition == "coords-full":
        body = "Perception: no image. Every mark's coordinate stream:\n" + _coords_full(scene.page, cap)
    elif condition == "index-compact":
        body = ("Perception: no image. A compact index, one row per mark:\n"
                + _index_compact(scene.page))
    elif condition == "analyzer-reduced":
        body = ("Perception: no image. Neeh ran an exact deterministic latest-mark "
                "reducer before this request:\n" + _analyzer_reduced(scene.page))
    else:
        raise ValueError(f"unknown condition {condition!r}")
    return f"{_PREAMBLE}\n\n{body}\n\n{ask}\n"


def estimate_tokens(scene: Scene, condition: str, cap: int) -> int:
    tokens = len(build_prompt(scene, condition, cap)) / 4
    if condition == "png":
        crop = _content_crop(scene.page)
        if crop is not None:
            tokens += (crop.width * crop.height) / 750
    return round(tokens)


# --------------------------------------------------------------------------- #
# Backends + scoring
# --------------------------------------------------------------------------- #
def run_mock(scene: Scene, condition: str) -> dict[str, Any]:
    if condition == "png":
        return {"answer": "upper", "why": "mock: no timing", "raw": ""}
    last = max(scene.page.all_strokes(), key=lambda s: s.created_at_ms)
    ans = "upper" if last.bbox.center[1] < _HALF else "lower"
    return {"answer": ans, "why": "mock: read newest mark's centre", "raw": ""}


def score(scene: Scene, condition: str, out: dict[str, Any], cap: int) -> dict[str, Any]:
    given = str(out.get("answer") or "").strip().casefold()
    return {
        "scene": scene.scene_id, "n": scene.n, "condition": condition,
        "answer": scene.answer, "model_answer": out.get("answer"),
        "correct": given == scene.answer.casefold(),
        "estimated_tokens": estimate_tokens(scene, condition, cap),
        "why": out.get("why"),
    }


def summarize(rows: list[dict[str, Any]], budget: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for n in sorted({r["n"] for r in rows}):
        out[str(n)] = {}
        for c in CONDITIONS:
            cell = [r for r in rows if r["n"] == n and r["condition"] == c]
            if not cell:
                continue
            k = len(cell)
            mean_tokens = round(sum(r["estimated_tokens"] for r in cell) / k)
            out[str(n)][c] = {
                "n_trials": k,
                "accuracy": round(sum(r["correct"] for r in cell) / k, 3) if cell[0].get("model_answer") is not None else None,
                "mean_tokens": mean_tokens,
                "over_budget": mean_tokens > budget,
            }
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", choices=["codex", "mock"], default="codex")
    parser.add_argument("--sizes", nargs="+", type=int, default=[4, 16, 48, 128, 320])
    parser.add_argument("--trials-per-size", type=int, default=6)
    parser.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS))
    parser.add_argument("--sample-points", type=int, default=8)
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET_TOKENS)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", help="token-vs-N curves only; no model calls")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    scenes = build_scenes(args.sizes, args.trials_per_size, args.seed)

    if args.dry_run:
        rows = [
            {"scene": s.scene_id, "n": s.n, "condition": c, "model_answer": None,
             "correct": False, "estimated_tokens": estimate_tokens(s, c, args.sample_points),
             "answer": s.answer}
            for s in scenes for c in args.conditions
        ]
        summary = summarize(rows, args.budget)
        report = {"mode": "dry-run", "budget_tokens": args.budget,
                  "sizes": args.sizes, "summary": summary}
        print(json.dumps({"budget_tokens": args.budget, "token_scaling": {
            n: {c: cell["mean_tokens"] for c, cell in conds.items()}
            for n, conds in summary.items()
        }}, indent=2))
    else:
        rows = []
        for scene in scenes:
            for condition in args.conditions:
                prompt = build_prompt(scene, condition, args.sample_points)
                if args.agent == "mock":
                    out = run_mock(scene, condition)
                else:
                    image = (render_page_png(scene.page, region=_content_crop(scene.page))
                             if condition == "png" else None)
                    try:
                        out = run_codex(scene, condition, prompt, image)
                    except ModelUnavailableError as exc:
                        out = {"answer": None, "why": f"error: {exc}", "raw": ""}
                row = score(scene, condition, out, args.sample_points)
                rows.append(row)
                print(json.dumps(row, separators=(",", ":")))
        summary = summarize(rows, args.budget)
        report = {"mode": "live", "agent": args.agent,
                  "model": CODEX_MODEL if args.agent == "codex" else args.agent,
                  "reasoning_effort": CODEX_EFFORT if args.agent == "codex" else None,
                  "budget_tokens": args.budget, "summary": summary, "rows": rows}
        print(json.dumps({"summary": summary}, indent=2))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
