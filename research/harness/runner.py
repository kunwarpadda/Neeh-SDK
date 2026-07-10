"""Sweep runner: model × arm × task, resumable through the ledger (§7.4).

Prompt assembly fairness rule (§3): PREAMBLE and the task prompt are
byte-identical across arms; only the legend and the context block vary, and
they are the encoding under test.

Cells are independent one-shot CLI calls, so `SweepConfig.workers > 1` runs
them through a thread pool; ledger appends and progress logging are
serialized behind a lock. The mock backend is always run serially — its
truth-injection handshake is not thread-safe.
"""
from __future__ import annotations

import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    workers: int = 1
    ledger: Ledger = field(default_factory=Ledger)


@dataclass(frozen=True)
class _Cell:
    arm: str
    task: TaskInstance
    repeat: int
    encoded: EncodedContext
    key: str


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

    # Encode each page once per arm, not once per task; collect pending cells.
    encoded_cache: dict[tuple[str, str], EncodedContext] = {}
    pending: list[_Cell] = []
    for arm in arms:
        encoder = ENCODERS[arm]
        for task in tasks:
            for repeat in range(config.repeats):
                cache_key = (arm, task.page_id)
                if cache_key not in encoded_cache:
                    encoded_cache[cache_key] = encoder(pages_by_id[task.page_id].page)
                encoded = encoded_cache[cache_key]
                key = row_key(backend.model, arm, encoded.version, task.task_id, repeat)
                if key in done:
                    counts["skipped"] += 1
                    continue
                pending.append(_Cell(arm, task, repeat, encoded, key))

    total = len(arms) * len(tasks) * config.repeats
    lock = threading.Lock()
    position = counts["skipped"]

    def run_cell(cell: _Cell) -> None:
        nonlocal position
        prompt = assemble_prompt(cell.encoded, cell.task)
        if isinstance(backend, MockBackend):
            backend.pending_truth = cell.task.truth

        reply = None
        failure: Optional[str] = None
        started = time.monotonic()
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                reply = backend.complete(prompt, cell.encoded.image_png)
                failure = None
                break
            except BackendError as exc:
                failure = str(exc)
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF_S * attempt)
        latency = time.monotonic() - started

        value = None
        if reply is not None:
            if cell.task.scorer == "action":
                from research.harness.actions import score_action

                value = score_action(
                    reply.text, cell.task.truth, pages_by_id[cell.task.page_id].page
                )
            else:
                value = score(cell.task.scorer, reply.text, cell.task.truth)

        with lock:
            position += 1
            config.ledger.append(
                key=cell.key,
                model=backend.model,
                backend=backend.name,
                arm=cell.arm,
                encoder_version=cell.encoded.version,
                task_id=cell.task.task_id,
                family=cell.task.family,
                page_id=cell.task.page_id,
                repeat=cell.repeat,
                seed=config.seed,
                prompt_sha1=hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12],
                context_chars=len(cell.encoded.text or ""),
                image_bytes=len(cell.encoded.image_png or b""),
                score=value,
                scorer=cell.task.scorer,
                answer=None if reply is None else reply.text[:2000],
                truth=cell.task.truth,
                input_tokens=None if reply is None else reply.input_tokens,
                output_tokens=None if reply is None else reply.output_tokens,
                latency_s=latency,
                failure=failure,
            )
            if failure is None:
                counts["run"] += 1
                log(f"[{position}/{total}] {backend.model} {cell.arm} "
                    f"{cell.task.task_id} r{cell.repeat} score={value:.2f} "
                    f"in={reply.input_tokens} ({latency:.1f}s)")
            else:
                counts["failed"] += 1
                log(f"[{position}/{total}] {backend.model} {cell.arm} "
                    f"{cell.task.task_id} r{cell.repeat} FAILED: {failure[:120]}")

    workers = max(1, config.workers)
    if isinstance(backend, MockBackend):
        workers = 1
    if workers == 1:
        for cell in pending:
            run_cell(cell)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(run_cell, cell) for cell in pending]
            try:
                for future in as_completed(futures):
                    future.result()
            except KeyboardInterrupt:
                # Drop queued cells; in-flight calls finish and are ledgered.
                pool.shutdown(cancel_futures=True)
                raise
    return counts
