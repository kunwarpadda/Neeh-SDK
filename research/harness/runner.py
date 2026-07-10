"""Sweep runner: model × arm × task, resumable through the ledger (§7.4).

Prompt assembly fairness rule (§3): PREAMBLE and the task prompt are
byte-identical across arms; only the legend and the context block vary, and
they are the encoding under test.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Optional

from research.harness.backends import Backend, BackendError, MockBackend
from research.harness.corpus_s0 import CorpusPage
from research.harness.encoders import ENCODERS, EncodedContext
from research.harness.ledger import Ledger, row_key
from research.harness.scorers import score
from research.harness.tasks import TaskInstance

PREAMBLE = """\
You are evaluating a page of digital ink (handwriting and drawings).
Page size: 1000 x 1414 page units; (0,0) is the top-left corner, x grows
right, y grows down.

Answer the question using only the page context provided below. Reply with
only the answer in the exact format the question asks for — no explanation,
no preamble, no punctuation beyond what the format requires.

=== PAGE CONTEXT ===
{legend}

{context}
=== QUESTION ===
{question}"""

MAX_ATTEMPTS = 3
RETRY_BACKOFF_S = 8.0


def assemble_prompt(encoded: EncodedContext, task: TaskInstance) -> str:
    return PREAMBLE.format(
        legend=encoded.legend,
        context=encoded.text or "(no further context)",
        question=task.prompt,
    )


@dataclass
class SweepConfig:
    arms: list[str]
    repeats: int = 1
    seed: int = 0
    include_ctrl: bool = True
    ledger: Ledger = field(default_factory=Ledger)


def run_sweep(
    backend: Backend,
    pages: list[CorpusPage],
    tasks: list[TaskInstance],
    config: SweepConfig,
    log=print,
) -> dict[str, int]:
    """Run every (arm × task × repeat) cell not already in the ledger."""
    pages_by_id = {page.page.id: page for page in pages}
    arms = list(config.arms) + (["CTRL"] if config.include_ctrl else [])
    done = config.ledger.existing_keys()
    counts = {"run": 0, "skipped": 0, "failed": 0}

    # Encode each page once per arm, not once per task.
    encoded_cache: dict[tuple[str, str], EncodedContext] = {}

    total = len(arms) * len(tasks) * config.repeats
    position = 0
    for arm in arms:
        encoder = ENCODERS[arm]
        for task in tasks:
            for repeat in range(config.repeats):
                position += 1
                cache_key = (arm, task.page_id)
                if cache_key not in encoded_cache:
                    encoded_cache[cache_key] = encoder(pages_by_id[task.page_id].page)
                encoded = encoded_cache[cache_key]

                key = row_key(backend.model, arm, encoded.version, task.task_id, repeat)
                if key in done:
                    counts["skipped"] += 1
                    continue

                prompt = assemble_prompt(encoded, task)
                if isinstance(backend, MockBackend):
                    backend.pending_truth = task.truth

                reply = None
                failure: Optional[str] = None
                started = time.monotonic()
                for attempt in range(1, MAX_ATTEMPTS + 1):
                    try:
                        reply = backend.complete(prompt, encoded.image_png)
                        failure = None
                        break
                    except BackendError as exc:
                        failure = str(exc)
                        if attempt < MAX_ATTEMPTS:
                            time.sleep(RETRY_BACKOFF_S * attempt)
                latency = time.monotonic() - started

                value = None
                if reply is not None:
                    if task.scorer == "action":
                        from research.harness.actions import score_action

                        value = score_action(
                            reply.text, task.truth, pages_by_id[task.page_id].page
                        )
                    else:
                        value = score(task.scorer, reply.text, task.truth)
                config.ledger.append(
                    key=key,
                    model=backend.model,
                    backend=backend.name,
                    arm=arm,
                    encoder_version=encoded.version,
                    task_id=task.task_id,
                    family=task.family,
                    page_id=task.page_id,
                    repeat=repeat,
                    seed=config.seed,
                    prompt_sha1=hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12],
                    context_chars=len(encoded.text or ""),
                    image_bytes=len(encoded.image_png or b""),
                    score=value,
                    scorer=task.scorer,
                    answer=None if reply is None else reply.text[:2000],
                    truth=task.truth,
                    input_tokens=None if reply is None else reply.input_tokens,
                    output_tokens=None if reply is None else reply.output_tokens,
                    latency_s=latency,
                    failure=failure,
                )
                if failure is None:
                    counts["run"] += 1
                    log(f"[{position}/{total}] {backend.model} {arm} {task.task_id} "
                        f"r{repeat} score={value:.2f} in={reply.input_tokens} "
                        f"({latency:.1f}s)")
                else:
                    counts["failed"] += 1
                    log(f"[{position}/{total}] {backend.model} {arm} {task.task_id} "
                        f"r{repeat} FAILED: {failure[:120]}")
    return counts
