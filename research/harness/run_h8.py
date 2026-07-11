"""H8 progressive-refinement experiment: multiresolution as transport.

Pre-registered in research/icf-v2-transport-design.md. The embedded-coding
exhibit rejected progressive codes in the one-shot regime (refinements
re-emit their prefix); in a session a refinement is an append, so H8 asks
whether coarse-base + on-demand refinement beats any static fidelity on a
mixed question batch.

Arms (all with page-unit bboxes; sessions via codex exec resume):
  R64   static push, 64-grid SVG, 1 turn   (cost floor / accuracy floor)
  R128  static push, 128-grid SVG, 1 turn
  R512  static push, 512-grid SVG, 1 turn  (accuracy ceiling / cost ceiling)
  RP    64-grid base, model may request {"refine": {"stroke_ids": [...]}}
        once; turn 2 appends 512-grid paths for ONLY those strokes

Questions per dense page: one reading question (fine detail pays) and one
layout question (coarse suffices) — RP should fetch for the first and skip
or fetch small for the second.

Run:  python -m research.harness.run_h8 --backend codex --pages 4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from typing import Any, Optional

from research.harness.backends import (
    BackendError,
    CodexCliSession,
    MockSession,
    ModelReply,
)
from research.harness.corpus_s0 import CorpusPage, make_dense_text_page
from research.harness.encoders import _compact_svg
from research.harness.ledger import DEFAULT_LEDGER, Ledger, row_key
from research.harness.scorers import score

ARMS = ("R64", "R128", "R512", "RP")
VERSION = "T8p/0.1.0"
BASE_GRID, FINE_GRID = 64, 512
MAX_REFINE_IDS = 60

STATIC_PROMPT = """\
You are working with a page of digital ink. Page size: 1000 x 1414 page
units; (0,0) top-left. The ink is compact SVG: one <path> per stroke, id
attribute = stable stroke id, integer coordinates on the viewBox grid,
data-bbox = per-stroke bounding box in page units. Reply with only the
answer in the exact format the question asks for — no explanation.

=== INK ===
{svg}
=== QUESTION ===
{question}"""

RP_PROMPT_1 = """\
You are working with a page of digital ink. Page size: 1000 x 1414 page
units; (0,0) top-left. Below is a COARSE rendering: compact SVG on a small
{base}-cell grid (id = stable stroke id, data-bbox = page-unit bbox). Shapes
and layout are reliable; fine letterforms may not be legible at this
resolution.

If you can answer the question from the coarse ink alone, reply with ONLY
the answer in the exact format the question asks for. If you need finer
geometry, reply with ONLY {{"refine": {{"stroke_ids": [...]}}}} listing the
stroke ids (at most {max_ids}) you need at high resolution; you will
receive them and can then answer.

=== COARSE INK ===
{svg}
=== QUESTION ===
{question}"""

RP_PROMPT_2 = """\
High-resolution geometry for the requested strokes ({fine}-cell grid, same
conventions):

=== REFINED INK ===
{svg}

Answer the question now. Reply with only the answer in the exact format the
question asks for — no explanation.
=== QUESTION (repeated) ===
{question}"""


def _svg_for(cpage: CorpusPage, grid: int, only_ids: Optional[set] = None) -> str:
    page = cpage.page
    if only_ids is None:
        return _compact_svg(page, grid_long_edge=grid, with_bboxes=True)
    strokes = [s for layer in page.layers for s in layer.strokes
               if s.id in only_ids]
    layer = type("L", (), {"visible": True, "strokes": strokes})()
    view = type("V", (), {"width": page.width, "height": page.height,
                          "layers": [layer]})()
    return _compact_svg(view, grid_long_edge=grid, with_bboxes=True)


def _tasks(cpage: CorpusPage) -> list[dict[str, Any]]:
    words = list(cpage.words)
    cx, cy = 500.0, 707.0
    read_target = min(words, key=lambda w: ((w["bbox"][0] + w["bbox"][2]) / 2 - cx) ** 2
                      + ((w["bbox"][1] + w["bbox"][3]) / 2 - cy) ** 2)
    top_row = [w for w in words if w["bbox"][1] < 300]
    return [
        {"task_id": f"T8pr_{cpage.page.id}", "kind": "read",
         "question": ("One word on this page is closest to the page center "
                      "(500, 707). Reply with that word, lowercase."),
         "truth": read_target["word"], "scorer": "cer",
         "refine_ids": read_target["stroke_ids"]},
        {"task_id": f"T8pl_{cpage.page.id}", "kind": "layout",
         "question": ("How many separate words are written in the top row of "
                      "the page (bbox top edge above y=300)? Reply with only "
                      "the integer."),
         "truth": str(len(top_row)), "scorer": "exact",
         "refine_ids": []},
    ]


def _parse_refine(text: str) -> Optional[list[str]]:
    try:
        start, end = text.find("{"), text.rfind("}")
        if start < 0:
            return None
        data = json.loads(text[start:end + 1])
        ids = (data.get("refine") or {}).get("stroke_ids")
        if isinstance(ids, list):
            return [str(i) for i in ids][:MAX_REFINE_IDS]
    except Exception:
        pass
    return None


def run_episode(make_session, cpage: CorpusPage, arm: str,
                task: dict[str, Any], ledger: Ledger, seed: int) -> None:
    session = make_session()
    key = row_key(session.model, arm, VERSION, task["task_id"], 0)
    if key in ledger.existing_keys():
        return
    question = task["question"]
    started = time.monotonic()
    failure = answer = None
    turns: list[ModelReply] = []
    refined_n = 0
    try:
        if arm != "RP":
            grid = {"R64": 64, "R128": 128, "R512": 512}[arm]
            prompt = STATIC_PROMPT.format(svg=_svg_for(cpage, grid),
                                          question=question)
            if isinstance(session, MockSession):
                session.pending_truth = task["truth"]
            turns.append(session.send(prompt))
        else:
            p1 = RP_PROMPT_1.format(base=BASE_GRID, max_ids=MAX_REFINE_IDS,
                                    svg=_svg_for(cpage, BASE_GRID),
                                    question=question)
            if isinstance(session, MockSession):
                # Oracle policy: refine exactly when the task benefits.
                session.pending_truth = (
                    json.dumps({"refine": {"stroke_ids": task["refine_ids"]}})
                    if task["refine_ids"] else task["truth"])
            r1 = session.send(p1)
            turns.append(r1)
            wanted = _parse_refine(r1.text)
            if wanted is not None:
                refined_n = len(wanted)
                p2 = RP_PROMPT_2.format(
                    fine=FINE_GRID,
                    svg=_svg_for(cpage, FINE_GRID, only_ids=set(wanted)),
                    question=question)
                if isinstance(session, MockSession):
                    session.pending_truth = task["truth"]
                turns.append(session.send(p2))
        answer = turns[-1].text
    except BackendError as exc:
        failure = str(exc)

    tokens_in = sum(t.input_tokens or 0 for t in turns) or None
    cached = sum(t.meta.get("cached_input_tokens") or 0 for t in turns)
    value = None if answer is None else score(task["scorer"], answer, task["truth"])
    ledger.append(
        key=key, model=session.model, backend=session.name, arm=arm,
        encoder_version=VERSION, task_id=task["task_id"], family="T8p",
        page_id=cpage.page.id, repeat=0, seed=seed,
        prompt_sha1=hashlib.sha1(question.encode()).hexdigest()[:12],
        context_chars=0, image_bytes=0, score=value, scorer=task["scorer"],
        answer=None if answer is None else answer[:2000],
        truth=task["truth"], input_tokens=tokens_in,
        output_tokens=sum(t.output_tokens or 0 for t in turns) or None,
        latency_s=round(time.monotonic() - started, 3), failure=failure,
        extra={"cached_input_tokens": cached, "turns": len(turns),
               "uncached_input_tokens": (tokens_in - cached) if tokens_in else None,
               "refined_stroke_count": refined_n, "kind": task["kind"]},
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["codex", "mock"], default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--arms", nargs="+", default=list(ARMS))
    args = parser.parse_args()

    def make_session():
        if args.backend == "mock":
            return MockSession()
        return CodexCliSession(model=args.model or "default",
                               label=args.model_label)

    ledger = Ledger(DEFAULT_LEDGER.parent / "ledger-mock.jsonl") \
        if args.backend == "mock" else Ledger()
    pages = [make_dense_text_page(i, seed=args.seed) for i in range(args.pages)]
    n = 0
    for cpage in pages:
        for task in _tasks(cpage):
            for arm in args.arms:
                run_episode(make_session, cpage, arm, task, ledger, args.seed)
                n += 1
                print(f"[{n}] {arm} {task['task_id']} done")
    print("episodes complete")


if __name__ == "__main__":
    main()
