"""Model backends: local `claude` and `codex` CLIs, plus a mock (protocol §6).

The sweep runs through the user's existing CLI logins — no raw API keys.
Consequences, recorded in the protocol changelog:
- Determinism knobs (temperature) are not exposed; repeats measure variance.
- Reported token usage includes each CLI's own scaffolding, so per-arm cost
  is computed as a delta against the CTRL (empty-context) arm.

`claude -p` receives image arms via --input-format stream-json (an image
content block beside the text), which avoids tool round-trips. `codex exec`
receives images via --image, mirroring examples/assistant/agent.py.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Protocol


class BackendError(RuntimeError):
    """The backend failed to produce an answer for this call."""


@dataclass(frozen=True)
class ModelReply:
    text: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    meta: dict[str, Any]


class Backend(Protocol):
    name: str
    model: str

    def complete(self, prompt: str, image_png: Optional[bytes]) -> ModelReply: ...


def _which(binary: str, env_var: str) -> str:
    path = shutil.which(os.getenv(env_var, binary))
    if not path:
        raise BackendError(f"{binary} CLI was not found on PATH")
    return path


class ClaudeCliBackend:
    """One-shot `claude -p` calls with a pinned model."""

    name = "claude-cli"

    def __init__(self, model: str, timeout_s: float = 240.0) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self._bin = _which("claude", "NEEH_CLAUDE_CLI_BIN")

    def complete(self, prompt: str, image_png: Optional[bytes]) -> ModelReply:
        content: list[dict[str, Any]] = []
        if image_png is not None:
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.b64encode(image_png).decode("ascii"),
                },
            })
        content.append({"type": "text", "text": prompt})
        stdin_payload = json.dumps({
            "type": "user",
            "message": {"role": "user", "content": content},
        })

        with tempfile.TemporaryDirectory(prefix="neeh-claude-") as tmp:
            command = [
                self._bin, "-p",
                "--model", self.model,
                "--input-format", "stream-json",
                "--output-format", "stream-json",
                "--verbose",  # required by -p with stream-json output
                "--strict-mcp-config",
                "--disallowedTools", "*",
                "--max-turns", "1",
            ]
            try:
                completed = subprocess.run(
                    command, input=stdin_payload, text=True, capture_output=True,
                    timeout=self.timeout_s, check=False, cwd=tmp,
                )
            except subprocess.TimeoutExpired as exc:
                raise BackendError(f"claude -p timed out after {self.timeout_s:g}s") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:500]
            raise BackendError(f"claude -p exited {completed.returncode}: {detail}")
        return _parse_claude_stream(completed.stdout)


def _parse_claude_stream(stdout: str) -> ModelReply:
    result_event: Optional[dict[str, Any]] = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result_event = event
    if result_event is None:
        raise BackendError("claude -p produced no result event")
    if result_event.get("is_error"):
        raise BackendError(f"claude -p error result: {str(result_event)[:500]}")
    usage = result_event.get("usage") or {}
    input_tokens = usage.get("input_tokens")
    for cached in ("cache_read_input_tokens", "cache_creation_input_tokens"):
        if isinstance(usage.get(cached), int) and isinstance(input_tokens, int):
            input_tokens += usage[cached]
    return ModelReply(
        text=str(result_event.get("result", "")),
        input_tokens=input_tokens,
        output_tokens=usage.get("output_tokens"),
        meta={"cost_usd": result_event.get("total_cost_usd")},
    )


class CodexCliBackend:
    """One-shot `codex exec` calls through the user's Codex login."""

    name = "codex-cli"

    def __init__(self, model: str = "default", timeout_s: float = 240.0) -> None:
        self.model = model
        self.timeout_s = timeout_s
        self._bin = _which("codex", "NEEH_CODEX_CLI_BIN")

    def complete(self, prompt: str, image_png: Optional[bytes]) -> ModelReply:
        env = None
        if os.getenv("NEEH_CODEX_HOME"):  # harness-owned home (auth copy + valid config)
            env = dict(os.environ, CODEX_HOME=os.environ["NEEH_CODEX_HOME"])
        with tempfile.TemporaryDirectory(prefix="neeh-codex-") as tmp_dir:
            tmp = Path(tmp_dir)
            output_path = tmp / "last-message.txt"
            command = [
                self._bin, "exec",
                "--ephemeral", "--skip-git-repo-check",
                "-C", str(tmp),
                "--sandbox", "read-only",
                "--json",
                "--output-last-message", str(output_path),
            ]
            if image_png is not None:
                image_path = tmp / "page.png"
                image_path.write_bytes(image_png)
                command.extend(["--image", str(image_path)])
            if self.model != "default":
                command.extend(["--model", self.model])
            command.append("-")
            try:
                completed = subprocess.run(
                    command, input=prompt, text=True, capture_output=True,
                    timeout=self.timeout_s, check=False, env=env,
                )
            except subprocess.TimeoutExpired as exc:
                raise BackendError(f"codex exec timed out after {self.timeout_s:g}s") from exc
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()[:500]
                raise BackendError(f"codex exec exited {completed.returncode}: {detail}")
            answer = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        input_tokens, output_tokens = _parse_codex_usage(completed.stdout)
        if not answer:
            raise BackendError("codex exec produced no final message")
        return ModelReply(text=answer, input_tokens=input_tokens,
                          output_tokens=output_tokens, meta={})


def _parse_codex_usage(stdout: str) -> tuple[Optional[int], Optional[int]]:
    """Best-effort extraction of token usage from `codex exec --json` events."""
    input_tokens = output_tokens = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for container in (event, event.get("msg") or {}):
            usage = container.get("usage") or (container.get("info") or {}).get("total_token_usage")
            if isinstance(usage, dict):
                input_tokens = usage.get("input_tokens", input_tokens)
                output_tokens = usage.get("output_tokens", output_tokens)
    return input_tokens, output_tokens


class MockBackend:
    """Oracle/noise backend for pipeline validation — never for science.

    The runner injects each task's truth before calling `complete`; the mock
    answers from it (optionally corrupted), which exercises prompt assembly,
    scorers, and the ledger end to end without any model.
    """

    name = "mock"

    def __init__(self, model: str = "oracle", noise: float = 0.0, seed: int = 0) -> None:
        import random

        self.model = model
        self._noise = noise
        self._rng = random.Random(seed)
        self.pending_truth: Any = None

    def complete(self, prompt: str, image_png: Optional[bytes]) -> ModelReply:
        truth = self.pending_truth
        if isinstance(truth, dict):  # T5 action spec -> the correct tool call
            if truth["type"] == "erase":
                answer = json.dumps(
                    {"tool": "erase", "input": {"stroke_ids": truth["stroke_ids"]}}
                )
            else:
                answer = json.dumps(
                    {"tool": "highlight", "input": {"region": truth["target_bbox"]}}
                )
        elif isinstance(truth, list):
            answer = " ".join(truth)
        else:
            answer = str(truth)
        if self._noise > 0 and self._rng.random() < self._noise:
            answer = "unknown"
        tokens = len(prompt) // 4 + (1836 if image_png is not None else 0)
        return ModelReply(text=answer, input_tokens=tokens, output_tokens=len(answer) // 4,
                          meta={"mock": True})
