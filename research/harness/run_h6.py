"""H6 delta-context experiment: per-turn deltas vs full resend (T7).

Pre-registered in research/delta-context-design.md; scheduled in
research/icf-v2-transport-design.md. Each episode is a scripted 3-turn
session over a changing shape page:

  turn 1  three single-stroke shapes; warm-up count question
  turn 2  a fourth shape is drawn; combined-state count question
  turn 3  one original stroke is erased; count + erased-id questions

Turns run sequentially against a one-shot backend with the transcript
replayed each call — the replayed prompt IS the accumulated context window,
so full-resend arms pay O(page x turns) and the delta arm O(page + change).

Arms:
  D0   full PNG of the current state each turn (raster baseline; only the
       latest image can attach, so D0 cost is a lower bound)
  D1   full v1 compact SVG + bboxes re-sent each turn
  D2   v1 context at turn 1; turns 2+ send {"added_svg", "erased"} deltas
  D2n  D2 with ids stripped from deltas (identity ablation)

Run:  python -m research.harness.run_h6 --backend codex --episodes 4
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import time
from typing import Any, Optional

from neeh.document import Document, Layer, Page
from neeh.rendering.png import render_page_png

from research.harness.backends import (
    Backend,
    BackendError,
    ClaudeCliBackend,
    CodexCliBackend,
    MockBackend,
)
from research.harness.corpus_s0 import (
    QUADRANTS,
    SHAPE_KINDS,
    _QUADRANT_CENTERS,
    _shape_polylines,
    _StrokeFactory,
)
from research.harness.encoders import _compact_svg
from research.harness.ledger import DEFAULT_LEDGER, Ledger, row_key
from research.harness.scorers import score

ARMS = ("D0", "D1", "D2", "D2n")
VERSION = "T7/0.1.0"
_SINGLE_STROKE_KINDS = ["circle", "square", "triangle", "star"]

PREAMBLE = """\
You are in a multi-turn session over one page of digital ink. Page size:
1000 x 1414 page units; (0,0) top-left. The transcript below shows every
turn so far: page context and updates arrive in CONTEXT blocks, questions
in Q blocks, and your prior answers in A blocks. Vector geometry (when
present) is compact SVG: one <path> per stroke, id attribute = stable
stroke id, integer coordinates on the viewBox grid; per-stroke bboxes are
page units. Delta updates list only what changed since the previous turn;
everything not mentioned is unchanged. Answer ONLY the final question, in
the exact format it asks for — no explanation.
"""


def _strokes_svg(page_like: Any) -> str:
    return _compact_svg(page_like, with_bboxes=True)


def _subset_view(width: float, height: float, strokes: list[Any]) -> Any:
    """A page-shaped view over a stroke subset (keeps the grid identical)."""
    layer = type("L", (), {"visible": True, "strokes": strokes})()
    return type("V", (), {"width": width, "height": height, "layers": [layer]})()


def _strip_ids(svg: str) -> str:
    import re

    return re.sub(r' id="[^"]*"', "", svg)


class Episode:
    """Deterministic 3-state shape scene with ground truth."""

    def __init__(self, index: int, seed: int) -> None:
        rng = random.Random(f"{seed}:t7:{index}")
        tag = f"t7s{seed}_{index:02d}"
        self.page_id = f"pg_{tag}"
        factory = _StrokeFactory(tag, random.Random(f"{seed}:t7:{index}:j"), 0.0)

        # 10 base shapes + 1 added on a 3x4 cell grid: the base context
        # dominates episode cost the way a real page would, deltas stay tiny.
        cells = [(200.0 + cx * 300.0, 190.0 + cy * 345.0)
                 for cy in range(4) for cx in range(3)]
        picked = rng.sample(cells, 11)
        self.shapes: list[dict[str, Any]] = []
        for kind, (qx, qy) in zip(rng.choices(_SINGLE_STROKE_KINDS, k=11), picked):
            (polyline,) = _shape_polylines(
                kind, qx + rng.uniform(-30, 30), qy + rng.uniform(-30, 30),
                rng.uniform(60, 95),
            )
            stroke = factory.make(polyline)
            self.shapes.append({"kind": kind, "stroke": stroke})

        base = [s["stroke"] for s in self.shapes[:10]]
        added = self.shapes[10]["stroke"]
        self.erased = self.shapes[rng.randrange(10)]["stroke"]
        self.n_base = 10
        self.states = [
            base,
            base + [added],
            [s for s in base + [added] if s.id != self.erased.id],
        ]
        self.added = added

    def page_at(self, turn: int) -> Page:
        layer = Layer(name="ink", id=f"ly_{self.page_id}", strokes=list(self.states[turn]))
        page = Page(id=self.page_id, layers=[layer])
        Document(id=f"doc_{self.page_id}", created_at_ms=1_700_000_000_000, pages=[page])
        return page

    def questions(self) -> list[dict[str, Any]]:
        return [
            {"turn": 0, "tag": "count1",
             "q": "How many shapes are on the page? Reply with only the integer.",
             "truth": "10", "scorer": "exact"},
            {"turn": 1, "tag": "count2",
             "q": "How many shapes are on the page now? Reply with only the integer.",
             "truth": "11", "scorer": "exact"},
            {"turn": 2, "tag": "count3",
             "q": "How many shapes are on the page now? Reply with only the integer.",
             "truth": "10", "scorer": "exact"},
            {"turn": 2, "tag": "erased_id",
             "q": "One stroke was erased during this session. Reply with only its stroke id.",
             "truth": self.erased.id, "scorer": "exact"},
        ]


def _context_block(ep: Episode, arm: str, turn: int) -> tuple[str, Optional[bytes]]:
    """The CONTEXT block a given arm emits at a given turn, plus any image."""
    page = ep.page_at(turn)
    if arm == "D0":
        note = ("(page snapshot attached as an image; it shows the CURRENT "
                "state — earlier snapshots are superseded)")
        return note, render_page_png(page)
    if arm == "D1" or turn == 0:
        return _strokes_svg(page), None
    if turn == 1:
        view = _subset_view(page.width, page.height, [ep.added])
        added_svg = _strokes_svg(view) if arm == "D2" else _strip_ids(_strokes_svg(view))
        return json.dumps({"delta": {"added_svg": added_svg}}), None
    if arm == "D2":
        return json.dumps({"delta": {"erased": [ep.erased.id]}}), None
    b = ep.erased.bbox
    near = [round((b.min_x + b.max_x) / 2), round((b.min_y + b.max_y) / 2)]
    return json.dumps({"delta": {"erased_near": near}}), None


def run_episode(backend: Backend, ep: Episode, arm: str, ledger: Ledger,
                seed: int) -> None:
    transcript: list[str] = []
    image: Optional[bytes] = None
    last_turn = -1
    for task in ep.questions():
        key = row_key(backend.model, arm, VERSION,
                      f"{task['tag']}_{ep.page_id}", 0)
        if key in ledger.existing_keys():
            return  # episodes are atomic: partial replays would skew answers
        if task["turn"] != last_turn:
            block, image_now = _context_block(ep, arm, task["turn"])
            transcript.append(f"=== CONTEXT (turn {task['turn'] + 1}) ===\n{block}")
            if image_now is not None:
                image = image_now  # single-image transport: latest wins
            last_turn = task["turn"]
        transcript.append(f"=== Q (turn {task['turn'] + 1}) ===\n{task['q']}")
        prompt = PREAMBLE + "\n" + "\n\n".join(transcript)

        started = time.monotonic()
        failure, answer, tokens_in, tokens_out = None, None, None, None
        try:
            if isinstance(backend, MockBackend):
                backend.pending_truth = task["truth"]
            reply = backend.complete(prompt, image if arm == "D0" else None)
            answer = reply.text
            tokens_in, tokens_out = reply.input_tokens, reply.output_tokens
        except BackendError as exc:
            failure = str(exc)

        transcript.append(f"=== A (turn {task['turn'] + 1}) ===\n"
                          f"{answer if answer is not None else '(no reply)'}")
        value = None if answer is None else score(task["scorer"], answer, task["truth"])
        ledger.append(
            key=key, model=backend.model, backend=backend.name, arm=arm,
            encoder_version=VERSION, task_id=f"{task['tag']}_{ep.page_id}",
            family="T7", page_id=ep.page_id, repeat=0, seed=seed,
            prompt_sha1=hashlib.sha1(prompt.encode()).hexdigest()[:12],
            context_chars=len(prompt),
            image_bytes=len(image or b"") if arm == "D0" else 0,
            score=value, scorer=task["scorer"],
            answer=None if answer is None else answer[:2000],
            truth=task["truth"], input_tokens=tokens_in,
            output_tokens=tokens_out,
            latency_s=round(time.monotonic() - started, 3), failure=failure,
            extra={"turn": task["turn"] + 1},
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=["codex", "claude", "mock"], default="mock")
    parser.add_argument("--model", default=None)
    parser.add_argument("--model-label", default=None)
    parser.add_argument("--episodes", type=int, default=4)
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
    for i in range(args.episodes):
        ep = Episode(i, seed=args.seed)
        for arm in args.arms:
            run_episode(backend, ep, arm, ledger, args.seed)
            n += 1
            print(f"[{n}] {arm} {ep.page_id} episode done")
    print("episodes complete")


if __name__ == "__main__":
    main()
