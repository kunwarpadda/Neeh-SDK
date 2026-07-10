"""M1 sweep entry point.

Examples (from the repo root):

    python -m research.harness.run_m1 --backend mock
    python -m research.harness.run_m1 --backend claude --model claude-haiku-4-5-20251001 --smoke
    python -m research.harness.run_m1 --backend claude --model claude-opus-4-8
    python -m research.harness.run_m1 --backend codex
    python -m research.harness.run_m1 --report
"""
from __future__ import annotations

import argparse

from research.harness.backends import ClaudeCliBackend, CodexCliBackend, MockBackend
from research.harness.corpus_s0 import generate_corpus
from research.harness.encoders import ALL_ARMS, M1_ARMS
from research.harness.ledger import Ledger
from research.harness.runner import SweepConfig, run_sweep
from research.harness.tasks import ALL_FAMILIES, generate_tasks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the M1 ink-context sweep")
    parser.add_argument("--backend", choices=["claude", "codex", "mock"], default="mock")
    parser.add_argument("--model", default=None,
                        help="model id (claude backend) or codex --model value")
    parser.add_argument("--arms", nargs="*", default=M1_ARMS,
                        help=f"encoding arms; M1 default. All: {ALL_ARMS}")
    parser.add_argument("--families", nargs="*", default=["T1", "T3", "T4"],
                        help=f"task families; M1 default. All: {list(ALL_FAMILIES)}")
    parser.add_argument("--corpus", choices=["s0", "s1", "s2"], default="s0",
                        help="s0 = synthetic; s1 = Quick, Draw!; s2 = MathWriting "
                             "(fetch the real-ink corpora first)")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--jitter", type=float, default=0.0)
    parser.add_argument("--text-pages", type=int, default=6)
    parser.add_argument("--shape-pages", type=int, default=6)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1,
                        help="parallel CLI calls (try 4-6; mock always runs serially)")
    parser.add_argument("--retry-failed", action="store_true",
                        help="re-run cells whose latest ledger row failed "
                             "(e.g. after a quota outage)")
    parser.add_argument("--smoke", action="store_true",
                        help="tiny slice: 1 text + 1 shape page, arms E0+E2 only")
    parser.add_argument("--report", action="store_true",
                        help="only regenerate results/summary.md from the ledger")
    parser.add_argument("--sizes", action="store_true",
                        help="only write the offline context-size exhibit")
    args = parser.parse_args()

    if args.report:
        from research.harness.report import write_summary

        print(f"wrote {write_summary()}")
        return
    if args.sizes:
        from research.harness.sizes import write_sizes

        print(f"wrote {write_sizes()}")
        return

    if args.smoke:
        args.text_pages, args.shape_pages = 1, 1
        args.arms = ["E0", "E2"]

    if args.backend == "claude":
        backend = ClaudeCliBackend(model=args.model or "claude-haiku-4-5-20251001")
    elif args.backend == "codex":
        backend = CodexCliBackend(model=args.model or "default")
    else:
        backend = MockBackend()

    if args.corpus == "s1":
        from research.harness.quickdraw import generate_s1_corpus

        pages = generate_s1_corpus(seed=args.seed, n_pages=args.shape_pages)
    elif args.corpus == "s2":
        from research.harness.mathwriting import generate_s2_corpus

        pages = generate_s2_corpus(n_pages=args.text_pages)
    else:
        pages = generate_corpus(
            seed=args.seed, n_text_pages=args.text_pages,
            n_shape_pages=args.shape_pages, jitter=args.jitter,
        )
    tasks = generate_tasks(pages, families=tuple(args.families))
    if args.backend == "mock":  # mock rows must never share the real ledger
        from research.harness.ledger import DEFAULT_LEDGER

        ledger = Ledger(DEFAULT_LEDGER.parent / "ledger-mock.jsonl")
    else:
        ledger = Ledger()
    config = SweepConfig(arms=list(args.arms), repeats=args.repeats,
                         seed=args.seed, workers=args.workers,
                         retry_failed=args.retry_failed, ledger=ledger)
    print(f"backend={backend.name} model={backend.model} pages={len(pages)} "
          f"tasks={len(tasks)} arms={config.arms}+CTRL repeats={config.repeats} "
          f"workers={config.workers}")
    counts = run_sweep(backend, pages, tasks, config)
    print(f"done: {counts}")


if __name__ == "__main__":
    main()
