"""Minimal stdio MCP server exposing the read-only Ink Agent Interface."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from neeh.agents.iai import IAI_TOOL_SCHEMAS, InkAgentInterface, PerceptionBudget
from neeh.canvas import Canvas
from neeh.document import Document

# Any legitimate perception request is small; this bounds memory use per line
# regardless of how much a misbehaving writer sends, by capping each
# `readline()` call rather than buffering an unbounded line before checking it.
_MAX_LINE_BYTES = 1_000_000


def _response(request_id: Any, result: Any = None, error: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    return payload


def _content(result: dict[str, Any]) -> list[dict[str, Any]]:
    if result.get("format") == "png" and "data" in result:
        metadata = {key: value for key, value in result.items() if key != "data"}
        return [
            {"type": "image", "data": result["data"], "mimeType": "image/png"},
            {"type": "text", "text": json.dumps(metadata, separators=(",", ":"))},
        ]
    return [{"type": "text", "text": json.dumps(result, separators=(",", ":"))}]


def _read_bounded_line(stream) -> tuple[Optional[str], bool]:
    """Read one line capped at _MAX_LINE_BYTES. Returns (line, oversized);
    `line` is None at EOF. An oversized line is drained in bounded chunks
    rather than accumulated, so memory use never scales with input size."""
    chunk = stream.readline(_MAX_LINE_BYTES)
    if chunk == "":
        return None, False
    if not chunk.endswith("\n") and len(chunk) >= _MAX_LINE_BYTES:
        while True:
            more = stream.readline(_MAX_LINE_BYTES)
            if more == "" or more.endswith("\n"):
                break
        return chunk, True
    return chunk, False


def serve(interface: InkAgentInterface) -> None:
    while True:
        line, oversized = _read_bounded_line(sys.stdin)
        if line is None:
            return
        if oversized:
            print(json.dumps(_response(None, error={
                "code": -32600,
                "message": f"request exceeds {_MAX_LINE_BYTES} byte limit",
            })), flush=True)
            continue
        try:
            message = json.loads(line)
            method = message.get("method")
            request_id = message.get("id")
            if method == "initialize":
                result = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "neeh-iai", "version": "0.1.0"},
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": IAI_TOOL_SCHEMAS}
            elif method == "tools/call":
                params = message.get("params") or {}
                try:
                    output = interface.call(params.get("name"), params.get("arguments") or {})
                    result = {"content": _content(output), "isError": False}
                    if output.get("format") != "png":
                        result["structuredContent"] = output
                except Exception as exc:
                    result = {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    }
            elif method and method.startswith("notifications/"):
                continue
            else:
                print(json.dumps(_response(request_id, error={"code": -32601, "message": "method not found"})), flush=True)
                continue
            if request_id is not None:
                print(json.dumps(_response(request_id, result=result)), flush=True)
        except Exception as exc:
            print(json.dumps(_response(None, error={"code": -32603, "message": str(exc)})), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--task-file", type=Path)
    parser.add_argument("--policy", default="active-index")
    parser.add_argument("--max-actions", type=int, default=4)
    parser.add_argument("--telemetry", type=Path)
    args = parser.parse_args()
    canvas = Canvas(Document.load(args.state))
    task = args.task_file.read_text(encoding="utf-8") if args.task_file else None
    interface = InkAgentInterface(
        canvas,
        task,
        policy=args.policy,
        budget=PerceptionBudget(max_actions=args.max_actions),
    )
    try:
        serve(interface)
    finally:
        if args.telemetry:
            with args.telemetry.open("a", encoding="utf-8") as output:
                output.write(json.dumps(interface.telemetry(), separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
