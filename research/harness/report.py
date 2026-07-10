"""Summaries and Pareto data from the ledger — and nothing but the ledger."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Optional

from research.harness.ledger import DEFAULT_LEDGER, Ledger

SUMMARY_PATH = DEFAULT_LEDGER.parent / "summary.md"


def _cell_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scored = [r for r in rows if r.get("score") is not None]
    tokens = [r["input_tokens"] for r in rows if r.get("input_tokens") is not None]
    return {
        "n": len(rows),
        "score": mean(r["score"] for r in scored) if scored else None,
        "input_tokens": mean(tokens) if tokens else None,
        "context_chars": mean(r["context_chars"] for r in rows) if rows else None,
        "failure_rate": sum(1 for r in rows if r.get("failure")) / len(rows) if rows else 0.0,
    }


def build_summary(ledger: Optional[Ledger] = None) -> str:
    ledger = ledger or Ledger()
    rows = list(ledger.rows())
    if not rows:
        return "# M1 summary\n\nLedger is empty.\n"

    by_cell: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_cell[(row["model"], row["arm"], row["family"])].append(row)

    ctrl_tokens: dict[str, float] = {}
    for (model, arm, _family), cell_rows in by_cell.items():
        if arm == "CTRL":
            tokens = [r["input_tokens"] for r in cell_rows if r.get("input_tokens") is not None]
            if tokens:
                existing = ctrl_tokens.get(model)
                ctrl_tokens[model] = mean(tokens) if existing is None else min(existing, mean(tokens))

    lines = [
        "# M1 summary",
        "",
        f"Ledger rows: {len(rows)}. Context token cost = model-reported input tokens minus the",
        "model's CTRL (empty-context) arm mean, which removes CLI scaffolding overhead.",
        "",
        "| model | arm | family | n | score | input tok | Δctx tok | ctx chars | fail |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    def fmt(value, spec: str) -> str:
        return format(value, spec) if value is not None else "—"

    for (model, arm, family) in sorted(by_cell):
        stats = _cell_stats(by_cell[(model, arm, family)])
        delta = None
        if stats["input_tokens"] is not None and model in ctrl_tokens:
            delta = stats["input_tokens"] - ctrl_tokens[model]
        lines.append(
            f"| {model} | {arm} | {family} | {stats['n']} | {fmt(stats['score'], '.3f')} "
            f"| {fmt(stats['input_tokens'], '.0f')} | {fmt(delta, '+.0f')} "
            f"| {fmt(stats['context_chars'], '.0f')} | {stats['failure_rate']:.0%} |"
        )

    lines += ["", "## Pareto view (score vs Δ context tokens, per model × family)", ""]
    by_family: dict[tuple[str, str], list[tuple[str, float, Optional[float]]]] = defaultdict(list)
    for (model, arm, family), cell_rows in by_cell.items():
        if arm == "CTRL":
            continue
        stats = _cell_stats(cell_rows)
        if stats["score"] is None:
            continue
        delta = None
        if stats["input_tokens"] is not None and model in ctrl_tokens:
            delta = stats["input_tokens"] - ctrl_tokens[model]
        by_family[(model, family)].append((arm, stats["score"], delta))
    for (model, family) in sorted(by_family):
        lines.append(f"**{model} — {family}**")
        entries = sorted(by_family[(model, family)], key=lambda e: (e[2] is None, e[2] or 0))
        best = -1.0
        for arm, score_value, delta in entries:
            marker = ""
            if score_value > best:
                best = score_value
                marker = "  ← frontier"
            delta_text = f"{delta:+.0f} tok" if delta is not None else "tok n/a"
            lines.append(f"- {arm}: score {score_value:.3f} at {delta_text}{marker}")
        lines.append("")
    return "\n".join(lines) + "\n"


def write_summary(path: Path = SUMMARY_PATH, ledger: Optional[Ledger] = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_summary(ledger), encoding="utf-8")
    return path


if __name__ == "__main__":
    print(write_summary())
