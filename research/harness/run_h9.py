"""H9 hierarchical-graph experiment: graph edges vs flat clusters (T9).

Pre-registered in research/icf-v2-transport-design.md; design approved
2026-07-10. Argument pages carry two claim words and six evidence words
whose support arrows deliberately CROSS the column layout, so proximity
misleads. Both arms see the identical compact SVG (words + arrows as plain
strokes with bboxes). The only variable is the semantics block:

  G0  flat clusters: one item per word (kind=cluster, stroke_ids, bbox);
      arrows are unlabeled ink — support must be traced geometrically
  G1  oracle graph: claim/statement kinds, supports edges, arrow ids,
      confidence + source (stroke -> word -> statement -> claim)

Questions force level-crossing: stroke->claim attribution, tool-executed
evidence erasure (set-F1 on stroke ids), and support counting.

Run:  python -m research.harness.run_h9 --backend codex --pages 4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from typing import Any

from research.harness.backends import (
    Backend,
    BackendError,
    ClaudeCliBackend,
    CodexCliBackend,
    MockBackend,
)
from research.harness.corpus_s0 import CorpusPage, make_argument_page
from research.harness.encoders import _compact_svg
from research.harness.ledger import DEFAULT_LEDGER, Ledger, row_key
from research.harness.scorers import score

ARMS = ("G0", "G1")
VERSION = "T9/0.1.0"

PROMPT = """\
You are working with a page of digital ink. Page size: 1000 x 1414 page
units; (0,0) top-left. The ink is compact SVG: one <path> per stroke, id
attribute = stable stroke id, integer coordinates on the viewBox grid,
data-bbox = per-stroke bounding box in page units. A SEMANTICS block lists
recognized structure; anything not listed there is still present as ink.
Reply with only the answer in the exact format the question asks for — no
explanation.

=== INK ===
{svg}
=== SEMANTICS ===
{semantics}
=== QUESTION ===
{question}"""


def _semantics(cpage: CorpusPage, arm: str) -> str:
    arg = cpage.argument
    items: list[dict[str, Any]] = []
    if arm == "G0":
        for entry in arg["claims"] + arg["statements"]:
            items.append({"id": entry["id"], "kind": "cluster",
                          "stroke_ids": entry["stroke_ids"],
                          "bbox": [round(v) for v in entry["bbox"]]})
    else:
        for c in arg["claims"]:
            items.append({"id": c["id"], "kind": "claim", "text": c["word"],
                          "stroke_ids": c["stroke_ids"],
                          "bbox": [round(v) for v in c["bbox"]],
                          "confidence": 0.99, "source": "recognizer"})
        for s in arg["statements"]:
            items.append({"id": s["id"], "kind": "statement", "text": s["word"],
                          "stroke_ids": s["stroke_ids"],
                          "bbox": [round(v) for v in s["bbox"]],
                          "supports": s["supports"],
                          "arrow_stroke_ids": s["arrow_stroke_ids"],
                          "confidence": 0.99, "source": "recognizer"})
    return "\n".join(json.dumps(i, separators=(",", ":")) for i in items)


def _tasks(cpage: CorpusPage) -> list[dict[str, Any]]:
    arg = cpage.argument
    claims = {c["id"]: c for c in arg["claims"]}
    statements = arg["statements"]
    # Hardest instance for Q1: a statement whose arrow crosses columns.
    crossing = next(s for s in statements if s["crosses"])
    probe_stroke = crossing["stroke_ids"][0]
    big_id = max(claims, key=lambda cid: sum(1 for s in statements
                                             if s["supports"] == cid))
    big = claims[big_id]
    big_support = [s for s in statements if s["supports"] == big_id]
    erase_truth = [sid for s in big_support for sid in s["stroke_ids"]]
    pid = cpage.page.id
    return [
        {"task_id": f"T9a_{pid}", "kind": "attribute",
         "question": (f"Stroke {probe_stroke} belongs to an evidence word. "
                      f"Which claim word does that evidence support? Reply "
                      f"with the claim word, lowercase."),
         "truth": claims[crossing["supports"]]["word"], "scorer": "exact"},
        {"task_id": f"T9e_{pid}", "kind": "erase",
         "question": (f"Erase all ink of the evidence words that support the "
                      f"claim '{big['word']}' — evidence word strokes only, "
                      f"not arrows, not the claim itself. Reply with exactly "
                      f'{{"tool":"erase","input":{{"stroke_ids":[...]}}}}.'),
         "truth": erase_truth, "scorer": "set_f1"},
        {"task_id": f"T9c_{pid}", "kind": "count",
         "question": (f"How many evidence words support the claim "
                      f"'{big['word']}'? Reply with only the integer."),
         "truth": str(len(big_support)), "scorer": "exact"},
    ]


def run_cell(backend: Backend, cpage: CorpusPage, arm: str,
             task: dict[str, Any], ledger: Ledger, seed: int) -> None:
    key = row_key(backend.model, arm, VERSION, task["task_id"], 0)
    if key in ledger.existing_keys():
        return
    svg = _compact_svg(cpage.page, with_bboxes=True)
    semantics = _semantics(cpage, arm)
    prompt = PROMPT.format(svg=svg, semantics=semantics,
                           question=task["question"])
    started = time.monotonic()
    failure = answer = tokens_in = tokens_out = None
    try:
        if isinstance(backend, MockBackend):
            backend.pending_truth = (
                json.dumps({"tool": "erase",
                            "input": {"stroke_ids": task["truth"]}})
                if task["scorer"] == "set_f1" else task["truth"])
        reply = backend.complete(prompt, None)
        answer = reply.text
        tokens_in, tokens_out = reply.input_tokens, reply.output_tokens
    except BackendError as exc:
        failure = str(exc)
    value = None if answer is None else score(task["scorer"], answer, task["truth"])
    ledger.append(
        key=key, model=backend.model, backend=backend.name, arm=arm,
        encoder_version=VERSION, task_id=task["task_id"], family="T9",
        page_id=cpage.page.id, repeat=0, seed=seed,
        prompt_sha1=hashlib.sha1(prompt.encode()).hexdigest()[:12],
        context_chars=len(prompt), image_bytes=0,
        score=value, scorer=task["scorer"],
        answer=None if answer is None else answer[:2000],
        truth=task["truth"], input_tokens=tokens_in, output_tokens=tokens_out,
        latency_s=round(time.monotonic() - started, 3), failure=failure,
        extra={"kind": task["kind"]},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["codex", "claude", "mock"], default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--arms", nargs="+", default=list(ARMS))
    args = parser.parse_args()

    if args.backend == "codex":
        backend: Backend = CodexCliBackend(model=args.model or "default",
                                           label=args.model_label)
    elif args.backend == "claude":
        backend = ClaudeCliBackend(model=args.model or "claude-haiku-4-5-20251001")
    else:
        backend = MockBackend()

    ledger = Ledger(DEFAULT_LEDGER.parent / "ledger-mock.jsonl") \
        if args.backend == "mock" else Ledger()
    n = 0
    for i in range(args.pages):
        cpage = make_argument_page(i, seed=args.seed)
        for task in _tasks(cpage):
            for arm in args.arms:
                run_cell(backend, cpage, arm, task, ledger, args.seed)
                n += 1
                print(f"[{n}] {arm} {task['task_id']} done")
    print("cells complete")


if __name__ == "__main__":
    main()
