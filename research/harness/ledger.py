"""Append-only results ledger (protocol §7.6).

Every model call becomes exactly one JSONL row. A result that is not in the
ledger does not exist; summaries and Pareto plots are derived from it only.
Rows are keyed so an interrupted sweep resumes without re-running work.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Iterator, Optional

DEFAULT_LEDGER = Path(__file__).resolve().parent.parent / "results" / "ledger.jsonl"


def row_key(model: str, arm: str, encoder_version: str, task_id: str, repeat: int) -> str:
    material = "|".join((model, arm, encoder_version, task_id, str(repeat)))
    return hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]


class Ledger:
    def __init__(self, path: Path = DEFAULT_LEDGER) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def latest_rows(self) -> dict[str, dict[str, Any]]:
        """Last row per key — a retried cell's newest row supersedes older ones."""
        latest: dict[str, dict[str, Any]] = {}
        for row in self.rows():
            if "key" in row:
                latest[row["key"]] = row
        return latest

    def existing_keys(self) -> set[str]:
        return set(self.latest_rows())

    def failed_keys(self) -> set[str]:
        """Keys whose latest attempt failed (candidates for --retry-failed)."""
        return {key for key, row in self.latest_rows().items() if row.get("failure")}

    def rows(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def append(
        self,
        *,
        key: str,
        model: str,
        backend: str,
        arm: str,
        encoder_version: str,
        task_id: str,
        family: str,
        page_id: str,
        repeat: int,
        seed: int,
        prompt_sha1: str,
        context_chars: int,
        image_bytes: int,
        score: Optional[float],
        scorer: str,
        answer: Optional[str],
        truth: Any,
        input_tokens: Optional[int],
        output_tokens: Optional[int],
        latency_s: float,
        failure: Optional[str],
        extra: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        row = {
            "key": key,
            "ts": int(time.time()),
            "model": model,
            "backend": backend,
            "arm": arm,
            "encoder_version": encoder_version,
            "task_id": task_id,
            "family": family,
            "page_id": page_id,
            "repeat": repeat,
            "seed": seed,
            "prompt_sha1": prompt_sha1,
            "context_chars": context_chars,
            "image_bytes": image_bytes,
            "score": score,
            "scorer": scorer,
            "answer": answer,
            "truth": truth,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_s": round(latency_s, 3),
            "failure": failure,
        }
        if extra:
            row["extra"] = extra
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row
