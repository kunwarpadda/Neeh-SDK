"""Task generators for families T1, T3, T4 (protocol §4).

Every instance carries its ground truth and scorer id. Generation is
deterministic in the corpus (which is deterministic in its seed), so task ids
are stable across runs — that is what makes the ledger resumable.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from research.harness.corpus_s0 import CorpusPage


@dataclass(frozen=True)
class TaskInstance:
    task_id: str
    family: str  # "T1" | "T3" | "T4"
    page_id: str
    prompt: str
    truth: Any
    scorer: str  # "cer" | "exact" | "set_f1"


def t1_tasks(page: CorpusPage) -> list[TaskInstance]:
    """Transcription: read all words in reading order."""
    if page.kind != "text":
        return []
    truth = " ".join(w["word"] for w in sorted(page.words, key=lambda w: w["order"]))
    return [TaskInstance(
        task_id=f"T1_{page.page.id}",
        family="T1",
        page_id=page.page.id,
        prompt=(
            "Transcribe every handwritten word on the page in reading order "
            "(left to right, then top to bottom). Reply with only the words, "
            "lowercase, separated by single spaces."
        ),
        truth=truth,
        scorer="cer",
    )]


def t3_tasks(page: CorpusPage) -> list[TaskInstance]:
    """Global layout: quadrant occupancy and left-of relations."""
    if page.kind != "shapes":
        return []
    rng = random.Random(f"t3:{page.page.id}")
    tasks: list[TaskInstance] = []

    quadrant_shape = rng.choice(page.shapes)
    tasks.append(TaskInstance(
        task_id=f"T3q_{page.page.id}",
        family="T3",
        page_id=page.page.id,
        prompt=(
            f"The page is divided into four equal quadrants. In which quadrant "
            f"is the {quadrant_shape['kind']}? Reply with exactly one of: "
            f"top-left, top-right, bottom-left, bottom-right."
        ),
        truth=quadrant_shape["quadrant"],
        scorer="exact",
    ))

    # A left-of question with an unambiguous answer: pick the pair with the
    # largest horizontal center separation.
    pairs = [
        (a, b)
        for i, a in enumerate(page.shapes)
        for b in page.shapes[i + 1:]
    ]
    a, b = max(pairs, key=lambda p: abs(p[0]["center"][0] - p[1]["center"][0]))
    if rng.random() < 0.5:
        a, b = b, a
    tasks.append(TaskInstance(
        task_id=f"T3r_{page.page.id}",
        family="T3",
        page_id=page.page.id,
        prompt=(
            f"Is the {a['kind']} to the left of the {b['kind']}? "
            f"Reply with exactly one word: yes or no."
        ),
        truth="yes" if a["center"][0] < b["center"][0] else "no",
        scorer="exact",
    ))
    return tasks


def t2_tasks(page: CorpusPage) -> list[TaskInstance]:
    """Object comprehension: count the distinct shapes."""
    if page.kind != "shapes":
        return []
    return [TaskInstance(
        task_id=f"T2_{page.page.id}",
        family="T2",
        page_id=page.page.id,
        prompt=(
            "How many distinct shapes are drawn on the page? "
            "Reply with a single integer."
        ),
        truth=str(len(page.shapes)),
        scorer="exact",
    )]


def t4_tasks(page: CorpusPage) -> list[TaskInstance]:
    """Addressing: which stroke ids form a named word or shape."""
    rng = random.Random(f"t4:{page.page.id}")
    tasks: list[TaskInstance] = []
    if page.kind == "text":
        for target in rng.sample(list(page.words), 2):
            tasks.append(TaskInstance(
                task_id=f"T4_{page.page.id}_{target['word']}",
                family="T4",
                page_id=page.page.id,
                prompt=(
                    f"Which strokes make up the handwritten word '{target['word']}'? "
                    f"Reply with only the stroke ids, separated by single spaces."
                ),
                truth=list(target["stroke_ids"]),
                scorer="set_f1",
            ))
    elif page.kind == "shapes":
        target = rng.choice(page.shapes)
        tasks.append(TaskInstance(
            task_id=f"T4_{page.page.id}_{target['kind']}",
            family="T4",
            page_id=page.page.id,
            prompt=(
                f"Which strokes make up the {target['kind']}? "
                f"Reply with only the stroke ids, separated by single spaces."
            ),
            truth=list(target["stroke_ids"]),
            scorer="set_f1",
        ))
    return tasks


def t5_tasks(page: CorpusPage) -> list[TaskInstance]:
    """Action grounding: the model must reply with an executable tool call.

    Truth carries an action spec; the runner executes the call through
    neeh-tools/v1 on a copy of the document and scores geometrically
    (see actions.py). Raster arms have no stroke ids and are expected
    near floor on erase — that gap is the measurement.
    """
    rng = random.Random(f"t5:{page.page.id}")
    tasks: list[TaskInstance] = []
    if page.kind == "text":
        target = rng.choice(list(page.words))
        tasks.append(TaskInstance(
            task_id=f"T5e_{page.page.id}_{target['word']}",
            family="T5",
            page_id=page.page.id,
            prompt=(
                f"Erase the handwritten word '{target['word']}'. Reply with only a "
                f'JSON object of this exact shape: {{"tool": "erase", '
                f'"input": {{"stroke_ids": ["st_...", "st_..."]}}}}'
            ),
            truth={"type": "erase", "stroke_ids": list(target["stroke_ids"])},
            scorer="action",
        ))
        target = rng.choice(list(page.words))
        others = [w["bbox"] for w in page.words if w["word"] != target["word"]]
        tasks.append(TaskInstance(
            task_id=f"T5h_{page.page.id}_{target['word']}",
            family="T5",
            page_id=page.page.id,
            prompt=(
                f"Highlight the handwritten word '{target['word']}'. Reply with only a "
                f'JSON object of this exact shape: {{"tool": "highlight", '
                f'"input": {{"region": [min_x, min_y, max_x, max_y]}}}}'
            ),
            truth={"type": "highlight", "target_bbox": list(target["bbox"]),
                   "foreign_bboxes": others},
            scorer="action",
        ))
    elif page.kind == "shapes":
        target = rng.choice(page.shapes)
        others = [s["bbox"] for s in page.shapes if s["kind"] != target["kind"]]
        tasks.append(TaskInstance(
            task_id=f"T5h_{page.page.id}_{target['kind']}",
            family="T5",
            page_id=page.page.id,
            prompt=(
                f"Highlight the {target['kind']}. Reply with only a "
                f'JSON object of this exact shape: {{"tool": "highlight", '
                f'"input": {{"region": [min_x, min_y, max_x, max_y]}}}}'
            ),
            truth={"type": "highlight", "target_bbox": list(target["bbox"]),
                   "foreign_bboxes": others},
            scorer="action",
        ))
    return tasks


def t6_tasks(page: CorpusPage) -> list[TaskInstance]:
    """Temporal: drawing order. Static raster arms are at chance by design."""
    rng = random.Random(f"t6:{page.page.id}")
    tasks: list[TaskInstance] = []
    if page.kind == "text":
        last = max(page.words, key=lambda w: w["order"])
        tasks.append(TaskInstance(
            task_id=f"T6_{page.page.id}",
            family="T6",
            page_id=page.page.id,
            prompt=(
                "The words on this page were written one after another. "
                "Which word was written last? Reply with only that word, lowercase."
            ),
            truth=last["word"],
            scorer="exact",
        ))
    elif page.kind == "shapes":
        a, b = rng.sample(list(page.shapes), 2)
        # Strokes were created in truth order, so list position is time order.
        first_kind = a["kind"] if page.shapes.index(a) < page.shapes.index(b) else b["kind"]
        tasks.append(TaskInstance(
            task_id=f"T6_{page.page.id}",
            family="T6",
            page_id=page.page.id,
            prompt=(
                f"The shapes on this page were drawn one after another. Which was "
                f"drawn first: the {a['kind']} or the {b['kind']}? "
                f"Reply with only the shape name."
            ),
            truth=first_kind,
            scorer="exact",
        ))
    return tasks


ALL_FAMILIES = ("T1", "T2", "T3", "T4", "T5", "T6")


def generate_tasks(pages: list[CorpusPage], families: tuple[str, ...] = ("T1", "T3", "T4")) -> list[TaskInstance]:
    generators = {"T1": t1_tasks, "T2": t2_tasks, "T3": t3_tasks,
                  "T4": t4_tasks, "T5": t5_tasks, "T6": t6_tasks}
    tasks: list[TaskInstance] = []
    for family in families:
        for page in pages:
            tasks.extend(generators[family](page))
    return tasks
