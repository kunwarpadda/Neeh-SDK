"""Ink assistant demo server — draw a question, ask, watch the answer appear.

Stdlib-only HTTP server around one shared Canvas:

    GET  /           the drawing page
    GET  /page.svg   current page render
    POST /stroke     {"points": [[x, y, t_ms, pressure], ...]} -> user ink
    POST /ask        {"instruction": "..."} -> runs the agent, returns actions
    POST /undo       undo the last edit
    POST /clear      fresh page

Run:  python examples/assistant/server.py [--port 8787] [--agent codex|codex-api|claude|mock|auto]
The default uses the local Codex CLI login. Missing CLIs, SDKs, or credentials
fall back to the canned mock agent.
"""
from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from neeh.canvas import Canvas
from neeh.ink import Author
from neeh.rendering import render_page_svg

from agent import (
    ModelUnavailableError,
    agent_input_preview,
    run_claude,
    run_codex_api,
    run_codex_cli,
    run_mock,
)

HERE = Path(__file__).parent

state_lock = threading.Lock()
canvas = Canvas()
agent_mode = "codex"


def _recoverable_model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return isinstance(exc, (ModuleNotFoundError, ModelUnavailableError)) or any(
        clue in text
        for clue in ("auth", "api_key", "api key", "credential", "401", "unauthorized")
    )


def ask(instruction: str | None) -> dict:
    runners = {
        "codex": [("codex-cli", run_codex_cli)],
        "codex-api": [("codex-api", run_codex_api)],
        "claude": [("claude", run_claude)],
        "mock": [("mock", run_mock)],
        "auto": [("codex-cli", run_codex_cli), ("codex-api", run_codex_api), ("claude", run_claude)],
    }[agent_mode]

    fallback_reason = None
    for mode, runner in runners:
        try:
            return {"mode": mode, **runner(canvas, instruction)}
        except Exception as exc:
            if mode == "mock" or not _recoverable_model_error(exc):
                raise
            fallback_reason = f"{mode}: {exc}"

    result = run_mock(canvas, instruction)
    return {"mode": "mock", "fallback_reason": fallback_reason, **result}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quieter default logging
        print(f"[server] {fmt % args}")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, status: int = 200) -> None:
        self._send(status, json.dumps(payload).encode(), "application/json")

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length))

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/index"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif self.path.startswith("/page.svg"):
            with state_lock:
                svg = render_page_svg(canvas.page)
            self._send(200, svg.encode(), "image/svg+xml")
        elif self.path.startswith("/agent-input"):
            instruction = None
            full = False
            if "?" in self.path:
                from urllib.parse import parse_qs, urlsplit

                query = parse_qs(urlsplit(self.path).query)
                instruction = query.get("instruction", [None])[0]
                full = query.get("full", ["0"])[0] in {"1", "true", "yes"}
            with state_lock:
                preview = agent_input_preview(canvas, instruction, full=full)
            self._json(preview)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self) -> None:
        global canvas
        try:
            body = self._body()
            if self.path == "/stroke":
                points = body["points"]
                with state_lock:
                    stroke = canvas.add_stroke(points, author=Author.USER)
                self._json({"stroke_id": stroke.id})
            elif self.path == "/ask":
                with state_lock:
                    result = ask(body.get("instruction") or None)
                self._json(result)
            elif self.path == "/undo":
                with state_lock:
                    undone = canvas.undo()
                self._json({"undone": undone})
            elif self.path == "/clear":
                with state_lock:
                    canvas = Canvas()
                self._json({"ok": True})
            else:
                self._json({"error": "not found"}, 404)
        except Exception as exc:
            self._json({"error": str(exc)}, 500)


def main() -> None:
    global agent_mode
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument(
        "--agent",
        choices=["codex", "codex-api", "claude", "mock", "auto"],
        default="codex",
        help="model backend to use for /ask",
    )
    parser.add_argument("--mock", action="store_true", help="shortcut for --agent mock")
    args = parser.parse_args()
    agent_mode = "mock" if args.mock else args.agent

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    label = "codex-cli" if agent_mode == "codex" else agent_mode
    mode = label if agent_mode == "mock" else f"{label} (mock fallback)"
    print(f"Neeh ink assistant on http://127.0.0.1:{args.port}  [agent: {mode}]")
    server.serve_forever()


if __name__ == "__main__":
    main()
