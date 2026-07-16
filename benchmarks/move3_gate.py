"""M3 exit-gate check over the Move 3 live ledger.

The roadmap gate: analyzer-first active IAI matches or beats raster grounding
while materially reducing average model context and unsupported claims. This
script turns the ledger into that verdict:

    python benchmarks/move3_gate.py                      # gate over full ledger
    python benchmarks/move3_gate.py --agent codex --seed 0 --kinds mw_...

The raster baseline is the better-scoring of the pixel-bearing perception arms
(raster-only, raster+geometry); marked-index carries pixels too but belongs to
the IAI family, so it is reported alongside rather than folded into the
baseline. "Materially" is an explicit, printed threshold, not an adjective:
context must drop by at least --context-reduction (default 25%).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.move3_live import DEFAULT_LEDGER, load_ledger, summarize_live  # noqa: E402

RASTER_BASELINE_ARMS = ("raster-only", "raster+geometry")
IAI_ARMS = ("active-index", "marked-index", "analyzer-first")


def evaluate_exit_gate(
    summary: dict[str, Any],
    *,
    candidate: str = "analyzer-first",
    context_reduction: float = 0.25,
) -> dict[str, Any]:
    """Score one IAI arm against the raster baseline per the M3 exit gate."""
    baselines = {
        arm: cell for arm, cell in summary.items()
        if arm in RASTER_BASELINE_ARMS and cell.get("accuracy") is not None
    }
    cell = summary.get(candidate)
    if not baselines or not cell or cell.get("accuracy") is None:
        return {"decidable": False, "reason": "missing arms or no scored QA rows"}
    baseline_arm = max(baselines, key=lambda a: baselines[a]["accuracy"])
    base = baselines[baseline_arm]
    tokens_base = base.get("mean_estimated_tokens") or 0
    tokens_cand = cell.get("mean_estimated_tokens") or 0
    reduction = 1 - tokens_cand / tokens_base if tokens_base else None
    matches_accuracy = cell["accuracy"] >= base["accuracy"]
    reduces_context = reduction is not None and reduction >= context_reduction
    fe_base = base.get("false_explanation_rate")
    fe_cand = cell.get("false_explanation_rate")
    reduces_unsupported = (
        fe_base is not None and fe_cand is not None and fe_cand <= fe_base
    )
    return {
        "decidable": True,
        "candidate": candidate,
        "raster_baseline": baseline_arm,
        "accuracy": {"candidate": cell["accuracy"], "baseline": base["accuracy"]},
        "matches_or_beats_accuracy": matches_accuracy,
        "mean_estimated_tokens": {"candidate": tokens_cand, "baseline": tokens_base},
        "context_reduction": round(reduction, 3) if reduction is not None else None,
        "context_reduction_threshold": context_reduction,
        "materially_reduces_context": reduces_context,
        "false_explanation_rate": {"candidate": fe_cand, "baseline": fe_base},
        "reduces_unsupported_claims": reduces_unsupported,
        "raster_pixels": {
            "candidate": cell.get("mean_raster_pixels"),
            "baseline": base.get("mean_raster_pixels"),
        },
        "gate_passed": matches_accuracy and reduces_context and reduces_unsupported,
    }


def _select_rows(
    ledger: dict[str, dict[str, Any]],
    *,
    agent: Optional[str],
    model: Optional[str],
    seed: Optional[int],
    kinds: Optional[list[str]],
) -> list[dict[str, Any]]:
    rows = list(ledger.values())
    if agent is not None:
        rows = [r for r in rows if r.get("agent") == agent]
    if model is not None:
        rows = [r for r in rows if r.get("model") == model]
    if seed is not None:
        rows = [r for r in rows if r.get("seed") == seed]
    if kinds:
        rows = [r for r in rows if r.get("kind") in set(kinds)]
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    parser.add_argument("--agent", default="codex")
    parser.add_argument("--model", default=None, help="e.g. gpt-5.6-luna")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--kinds", nargs="+", default=None)
    parser.add_argument("--context-reduction", type=float, default=0.25)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    rows = _select_rows(
        load_ledger(args.ledger),
        agent=args.agent,
        model=args.model,
        seed=args.seed,
        kinds=args.kinds,
    )
    if not rows:
        raise SystemExit(f"no matching ledger rows in {args.ledger}")
    summary = summarize_live(rows)
    report = {
        "rows": len(rows),
        "agent": args.agent,
        "kinds": sorted({r.get("kind", "?") for r in rows}),
        "summary": summary,
        "exit_gate": {
            arm: evaluate_exit_gate(
                summary, candidate=arm, context_reduction=args.context_reduction
            )
            for arm in IAI_ARMS
            if arm in summary
        },
    }
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
