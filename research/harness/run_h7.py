"""H7 foveated-context experiment: pull vs push on dense pages (T8).

Pre-registered in research/foveated-context-design.md. Two-phase episodes on
one-shot CLI backends: phase 1 shows a cheap gist (word-cluster bboxes,
no text) and asks the model to request regions; phase 2 supplies the fetched
detail and asks the question. Cost = both phases' input tokens.

Arms:
  F0  static push baseline — full compact SVG + bboxes of the whole page
  F1  gist + vector fetch (compact SVG of requested regions, with ids)
  F2  gist + raster fetch (PNG crop of requested regions) — H7c ablation
  F3  gist only, no fetch — the floor

Run:  python -m research.harness.run_h7 --backend codex --pages 4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from statistics import mean
from typing import Any, Optional

from neeh.document import Page
from neeh.ink import BoundingBox

from research.harness.backends import (
    Backend,
    BackendError,
    ClaudeCliBackend,
    CodexCliBackend,
    CodexCliSession,
    MockBackend,
    MockSession,
    ModelReply,
)
from research.harness.corpus_s0 import CorpusPage, make_dense_text_page
from research.harness.encoders import _compact_svg
from research.harness.ledger import DEFAULT_LEDGER, Ledger, row_key
from research.harness.scorers import score

ARMS = ("F0", "F1", "F2", "F3")
VERSION = "T8/0.1.0"
MAX_REGIONS = 2

PHASE1_PREAMBLE = """\
You are working with a page of digital ink. Page size: 1000 x 1414 page
units; (0,0) top-left, x right, y down. You have only a cheap index of the
page below: one entry per ink cluster (id, bounding box in page units,
stroke count) — the ink itself is not included.

To answer the question you may fetch detail for up to {max_regions} regions.
Reply with ONLY a JSON object: {{"regions": [[min_x,min_y,max_x,max_y], ...]}}
(page units, at most {max_regions} regions, no other text).

=== PAGE INDEX ===
{gist}
=== QUESTION (you will answer it in the next step) ===
{question}"""

PHASE2_PREAMBLE = """\
You are working with a page of digital ink. Page size: 1000 x 1414 page
units; (0,0) top-left, x right, y down. You previously saw an index of ink
clusters and requested detail for regions; the fetched detail is below.
{legend}

Answer using only this material. Reply with only the answer in the exact
format the question asks for — no explanation.

=== PAGE INDEX ===
{gist}
=== FETCHED DETAIL ===
{detail}
=== QUESTION ===
{question}"""

F1_LEGEND = (
    "The detail is a compact SVG: one <path> per stroke, id attribute is the "
    "stable stroke id, integer coordinates on the viewBox grid covering the "
    "whole page (drawn order preserved)."
)
F2_LEGEND = "The detail is attached as an image crop of the requested region."
F3_LEGEND = "No detail was fetched; only the index is available."


def _gist(cpage: CorpusPage) -> str:
    lines = []
    for i, word in enumerate(cpage.words):
        box = [round(v) for v in word["bbox"]]
        lines.append(
            json.dumps({"cluster": f"c{i:02d}", "bbox": box,
                        "strokes": len(word["stroke_ids"])},
                       separators=(",", ":"))
        )
    return "\n".join(lines)


def _episode_tasks(cpage: CorpusPage, rng_index: int) -> list[dict[str, Any]]:
    """Two questions per page: locate-and-read, locate-and-address."""
    words = list(cpage.words)
    # Deterministic picks: reading target = word whose bbox center is nearest
    # the page center; addressing target = last word in reading order.
    cx, cy = 500.0, 707.0
    def center_dist(w):
        b = w["bbox"]
        return ((b[0] + b[2]) / 2 - cx) ** 2 + ((b[1] + b[3]) / 2 - cy) ** 2
    read_target = min(words, key=center_dist)
    addr_target = words[-1]
    return [
        {
            "task_id": f"T8r_{cpage.page.id}",
            "question": ("One word on this page is closest to the page center "
                         "(500, 707). Reply with that word, lowercase."),
            "truth": read_target["word"],
            "scorer": "cer",
        },
        {
            "task_id": f"T8a_{cpage.page.id}",
            "question": (f"Reply with the stroke ids of the word written inside "
                         f"the region {[round(v) for v in addr_target['bbox']]} "
                         f"as a JSON array of strings."),
            "truth": addr_target["stroke_ids"],
            "scorer": "set_f1",
        },
    ]


def _parse_regions(text: str) -> list[BoundingBox]:
    try:
        start, end = text.find("{"), text.rfind("}")
        data = json.loads(text[start:end + 1])
        regions = data.get("regions", [])[:MAX_REGIONS]
        return [BoundingBox(*[float(v) for v in r]) for r in regions
                if isinstance(r, (list, tuple)) and len(r) == 4]
    except Exception:
        return []


def _strokes_in(page: Page, regions: list[BoundingBox]):
    for layer in page.layers:
        for stroke in layer.strokes:
            b = stroke.bbox
            for r in regions:
                if not (b.max_x < r.min_x or b.min_x > r.max_x
                        or b.max_y < r.min_y or b.min_y > r.max_y):
                    yield stroke
                    break


def _region_svg(page: Page, regions: list[BoundingBox]) -> str:
    wanted = {s.id for s in _strokes_in(page, regions)}

    class _View:
        width, height = page.width, page.height
        layers = [type("L", (), {
            "visible": True,
            "strokes": [s for layer in page.layers for s in layer.strokes
                        if s.id in wanted],
        })()]

    return _compact_svg(_View(), with_bboxes=True)


def _region_png(page: Page, regions: list[BoundingBox]) -> Optional[bytes]:
    from neeh.rendering.png import render_page_png

    if not regions:
        return None
    box = BoundingBox(
        min(r.min_x for r in regions), min(r.min_y for r in regions),
        max(r.max_x for r in regions), max(r.max_y for r in regions),
    )
    return render_page_png(page, region=box)


STATEFUL_VERSION = "T8/0.2.0-stateful"

PHASE2_FOLLOWUP = """\
Fetched detail for your requested regions is below.
{legend}

Answer using the index and this detail. Reply with only the answer in the
exact format the question asks for — no explanation.

=== FETCHED DETAIL ===
{detail}
=== QUESTION (repeated) ===
{question}"""


def run_episode_stateful(make_session, cpage: CorpusPage, arm: str,
                         task: dict[str, Any], ledger: Ledger, seed: int) -> None:
    """H7-S: one real session per episode; phase 2 pays only the increment.

    F0 is one turn (push). F1/F3 are two turns where the second sends only
    the fetched detail (or nothing) — the gist and question are already in
    the thread. F2 is excluded: codex resume cannot attach images.
    """
    session = make_session()
    key = row_key(session.model, arm, STATEFUL_VERSION, task["task_id"], 0)
    if key in ledger.existing_keys():
        return
    gist = _gist(cpage)
    question = task["question"]
    started = time.monotonic()
    failure = answer = None
    turns: list[ModelReply] = []
    try:
        if arm == "F0":
            detail = _compact_svg(cpage.page, with_bboxes=True)
            prompt = PHASE2_PREAMBLE.format(
                legend=F1_LEGEND, gist="(index omitted — full page below)",
                detail=detail, question=question,
            )
            if isinstance(session, MockSession):
                session.pending_truth = task["truth"]
            turns.append(session.send(prompt))
        else:
            p1 = PHASE1_PREAMBLE.format(
                max_regions=MAX_REGIONS, gist=gist, question=question,
            )
            if isinstance(session, MockSession):
                session.pending_truth = json.dumps({"regions": [[0, 0, 1000, 1414]]})
            r1 = session.send(p1)
            turns.append(r1)
            regions = _parse_regions(r1.text)
            if arm == "F1":
                detail, legend = _region_svg(cpage.page, regions), F1_LEGEND
            else:  # F3: no fetch, answer from the index alone
                detail, legend = "(no detail available)", F3_LEGEND
            if isinstance(session, MockSession):
                session.pending_truth = task["truth"]
            turns.append(session.send(
                PHASE2_FOLLOWUP.format(legend=legend, detail=detail,
                                       question=question)))
        answer = turns[-1].text
    except BackendError as exc:
        failure = str(exc)

    tokens_in = sum(t.input_tokens or 0 for t in turns) or None
    cached = sum(t.meta.get("cached_input_tokens") or 0 for t in turns)
    tokens_out = sum(t.output_tokens or 0 for t in turns) or None
    value = None if answer is None else score(task["scorer"], answer, task["truth"])
    ledger.append(
        key=key, model=session.model, backend=session.name, arm=arm,
        encoder_version=STATEFUL_VERSION, task_id=task["task_id"], family="T8",
        page_id=cpage.page.id, repeat=0, seed=seed,
        prompt_sha1=hashlib.sha1(question.encode()).hexdigest()[:12],
        context_chars=len(gist), image_bytes=0,
        score=value, scorer=task["scorer"],
        answer=None if answer is None else answer[:2000],
        truth=task["truth"], input_tokens=tokens_in, output_tokens=tokens_out,
        latency_s=round(time.monotonic() - started, 3), failure=failure,
        extra={"cached_input_tokens": cached, "turns": len(turns),
               "uncached_input_tokens": (tokens_in - cached) if tokens_in else None,
               "thread_id": getattr(session, "thread_id", None)},
    )


def run_episode(backend: Backend, cpage: CorpusPage, arm: str,
                task: dict[str, Any], ledger: Ledger, seed: int) -> None:
    key = row_key(backend.model, arm, VERSION, task["task_id"], 0)
    if key in ledger.existing_keys():
        return
    gist = _gist(cpage)
    question = task["question"]
    started = time.monotonic()
    failure = None
    answer = None
    tokens_in = 0
    tokens_out = 0
    image = None
    try:
        if arm == "F0":
            detail = _compact_svg(cpage.page, with_bboxes=True)
            prompt = PHASE2_PREAMBLE.format(
                legend=F1_LEGEND, gist="(index omitted — full page below)",
                detail=detail, question=question,
            )
            if isinstance(backend, MockBackend):
                backend.pending_truth = task["truth"]
            reply = backend.complete(prompt, None)
            tokens_in = reply.input_tokens or 0
            tokens_out = reply.output_tokens or 0
            answer = reply.text
        else:
            regions: list[BoundingBox] = []
            if arm in ("F1", "F2"):
                p1 = PHASE1_PREAMBLE.format(
                    max_regions=MAX_REGIONS, gist=gist, question=question,
                )
                if isinstance(backend, MockBackend):
                    backend.pending_truth = json.dumps(
                        {"regions": [[0, 0, 1000, 1414]]})
                r1 = backend.complete(p1, None)
                tokens_in += r1.input_tokens or 0
                tokens_out += r1.output_tokens or 0
                regions = _parse_regions(r1.text)
            if arm == "F1":
                detail, legend = _region_svg(cpage.page, regions), F1_LEGEND
            elif arm == "F2":
                image = _region_png(cpage.page, regions)
                detail, legend = "(see attached image crop)", F2_LEGEND
            else:
                detail, legend = "(none)", F3_LEGEND
            p2 = PHASE2_PREAMBLE.format(
                legend=legend, gist=gist, detail=detail, question=question,
            )
            if isinstance(backend, MockBackend):
                backend.pending_truth = task["truth"]
            r2 = backend.complete(p2, image)
            tokens_in += r2.input_tokens or 0
            tokens_out += r2.output_tokens or 0
            answer = r2.text
    except BackendError as exc:
        failure = str(exc)

    value = None if answer is None else score(task["scorer"], answer, task["truth"])
    ledger.append(
        key=key, model=backend.model, backend=backend.name, arm=arm,
        encoder_version=VERSION, task_id=task["task_id"], family="T8",
        page_id=cpage.page.id, repeat=0, seed=seed,
        prompt_sha1=hashlib.sha1(question.encode()).hexdigest()[:12],
        context_chars=len(gist), image_bytes=len(image or b""),
        score=value, scorer=task["scorer"],
        answer=None if answer is None else answer[:2000],
        truth=task["truth"], input_tokens=tokens_in or None,
        output_tokens=tokens_out or None,
        latency_s=round(time.monotonic() - started, 3), failure=failure,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["codex", "claude", "mock"], default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--pages", type=int, default=4)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--arms", nargs="+", default=None)
    parser.add_argument("--stateful", action="store_true",
                        help="H7-S: real sessions via codex exec resume; "
                             "phase 2 pays only incremental input (F2 excluded)")
    args = parser.parse_args()

    if args.backend == "codex":
        backend: Backend = CodexCliBackend(model=args.model or "default",
                                           label=args.model_label)
    elif args.backend == "claude":
        backend = ClaudeCliBackend(model=args.model or "claude-haiku-4-5-20251001")
    else:
        backend = MockBackend()

    if args.stateful:
        if args.backend == "claude":
            raise SystemExit("--stateful currently supports codex and mock only")
        def make_session():
            if args.backend == "mock":
                return MockSession()
            return CodexCliSession(model=args.model or "default",
                                   label=args.model_label)
        arms = args.arms or ["F0", "F1", "F3"]
    else:
        arms = args.arms or list(ARMS)

    # Mock runs stay off the real ledger, same as run_m1.
    ledger = Ledger(DEFAULT_LEDGER.parent / "ledger-mock.jsonl") \
        if args.backend == "mock" else Ledger()
    pages = [make_dense_text_page(i, seed=args.seed) for i in range(args.pages)]
    n = 0
    for cpage in pages:
        for task in _episode_tasks(cpage, args.seed):
            for arm in arms:
                if args.stateful:
                    run_episode_stateful(make_session, cpage, arm, task,
                                         ledger, args.seed)
                else:
                    run_episode(backend, cpage, arm, task, ledger, args.seed)
                n += 1
                print(f"[{n}] {arm} {task['task_id']} done")
    print("episodes complete")


if __name__ == "__main__":
    main()
