"""Ink assistant demo server — draw a question, ask, watch the answer appear.

Stdlib-only HTTP server around one shared Canvas:

    GET  /           the drawing page
    GET  /page.svg   current page render
    GET  /status     active backend and perception policy
    POST /stroke     {"points": [[x, y, t_ms, pressure], ...]} -> user ink
    POST /scenario   load a deterministic example page
    POST /analyze    run a deterministic ink reducer
    POST /ask        {"instruction": "..."} -> runs the agent, returns actions
    POST /undo       undo the last edit
    POST /clear      fresh page

Run:  python examples/assistant/server.py [--port 8787] [--lan]
                                             [--agent codex|claude|mock|auto]
                                             [--perception active-index|raster-only|raster-always|index-only|marked-index]
The default uses the local Codex CLI login. Missing CLIs or credentials fall
back to the canned mock agent.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from neeh.canvas import Canvas
from neeh.ink import Author, Point, Stroke
from neeh.rendering import render_page_svg

from neeh.agents import assistant as agent
from neeh.agents import (
    ModelUnavailableError,
    analyze_ink,
    agent_input_preview,
    run_claude,
    run_codex_cli,
    run_mock,
)

HERE = Path(__file__).parent

state_lock = threading.Lock()
canvas = Canvas()
agent_mode = "codex"


def _local_ipv4_addresses() -> list[str]:
    """Return usable IPv4 addresses for opening this server from another device."""
    candidates: set[str] = set()
    try:
        candidates.update(
            info[4][0]
            for info in socket.getaddrinfo(
                socket.gethostname(), None, socket.AF_INET, socket.SOCK_STREAM
            )
        )
    except OSError:
        pass

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 80))
            candidates.add(probe.getsockname()[0])
    except OSError:
        pass

    addresses = []
    for candidate in candidates:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
        ):
            addresses.append(candidate)
    return sorted(set(addresses))


def _server_urls(
    bind_host: str,
    port: int,
    lan_addresses: list[str] | None = None,
) -> list[str]:
    if bind_host == "0.0.0.0":
        addresses = _local_ipv4_addresses() if lan_addresses is None else lan_addresses
        hosts = ["127.0.0.1", *addresses]
    else:
        hosts = [bind_host]
    return [f"http://{host}:{port}" for host in dict.fromkeys(hosts)]


SCENARIOS = {
    "latest": {
        "title": "Latest mark",
        "question": "Where is the most recently drawn mark?",
        "analysis": {"operation": "latest_mark"},
    },
    "direction": {
        "title": "Drawing direction",
        "question": "Which direction was the long horizontal stroke drawn?",
        "analysis": {
            "operation": "stroke_dynamics",
            "stroke_ids": ["st_direction"],
        },
    },
    "crossout": {
        "title": "Cross-out evidence",
        "question": "Which earlier mark has evidence of being crossed out?",
        "analysis": {"operation": "cross_out_candidates"},
    },
}


def _stroke(
    stroke_id: str,
    xy: list[tuple[float, float]],
    created_at_ms: int,
    duration_ms: int = 400,
) -> Stroke:
    points = tuple(
        Point(
            x,
            y,
            t_ms=round(index * duration_ms / max(len(xy) - 1, 1)),
            pressure=min(0.45 + index * 0.08, 0.9),
        )
        for index, (x, y) in enumerate(xy)
    )
    return Stroke(points=points, id=stroke_id, created_at_ms=created_at_ms)


def make_scenario(name: str) -> tuple[Canvas, dict]:
    """Build a deterministic demo page and return its public metadata."""
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}")

    scene = Canvas()
    layer = scene.page.layers[0]
    if name == "latest":
        layer.add(_stroke(
            "st_circle",
            [(220, 330), (260, 285), (325, 285), (365, 330), (325, 375),
             (260, 375), (220, 330)],
            1_000,
            700,
        ))
        layer.add(_stroke("st_underline", [(420, 360), (700, 360)], 2_000))
        layer.add(_stroke(
            "st_check",
            [(650, 620), (700, 675), (810, 535)],
            3_000,
            550,
        ))
    elif name == "direction":
        layer.add(_stroke(
            "st_direction",
            [(800, 470), (680, 470), (560, 470), (440, 470), (320, 470), (200, 470)],
            1_000,
            1_200,
        ))
    else:
        layer.add(_stroke(
            "st_original",
            [(280, 420), (370, 405), (470, 430), (570, 410), (680, 420)],
            1_000,
            850,
        ))
        layer.add(_stroke("st_cross", [(240, 330), (720, 520)], 5_000, 650))

    return scene, {"name": name, **SCENARIOS[name]}


def _recoverable_model_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return isinstance(exc, (ModuleNotFoundError, ModelUnavailableError)) or any(
        clue in text
        for clue in ("auth", "api_key", "api key", "credential", "401", "unauthorized")
    )


def ask(instruction: str | None) -> dict:
    runners = {
        "codex": [("codex-cli", run_codex_cli)],
        "claude": [("claude-cli", run_claude)],
        "mock": [("mock", run_mock)],
        "auto": [("codex-cli", run_codex_cli), ("claude-cli", run_claude)],
    }[agent_mode]

    fallback_reason = None
    for mode, runner in runners:
        try:
            return {"mode": mode, **runner(canvas, instruction)}
        except Exception as exc:
            if mode == "mock" or not _recoverable_model_error(exc):
                raise
            if agent_mode != "auto":
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
        elif self.path.startswith("/status"):
            with state_lock:
                stroke_count = sum(
                    len(layer.strokes) for layer in canvas.page.layers
                )
            self._json({
                "agent": agent_mode,
                "perception_mode": agent.PERCEPTION_MODE,
                "perception_policy": agent.PERCEPTION_MODE_ALIASES.get(
                    agent.PERCEPTION_MODE, agent.PERCEPTION_MODE
                ),
                "context_version": agent.CONTEXT_VERSION,
                "stroke_count": stroke_count,
                "scenarios": [
                    {"name": name, "title": item["title"]}
                    for name, item in SCENARIOS.items()
                ],
            })
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
            elif self.path == "/analyze":
                with state_lock:
                    result = analyze_ink(
                        canvas,
                        body["operation"],
                        stroke_ids=body.get("stroke_ids"),
                        region=body.get("region"),
                        limit=body.get("limit", 16),
                    )
                self._json(result)
            elif self.path == "/scenario":
                scene, metadata = make_scenario(body["name"])
                with state_lock:
                    canvas = scene
                self._json(metadata)
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
    network = parser.add_mutually_exclusive_group()
    network.add_argument(
        "--host",
        default="127.0.0.1",
        help="interface to bind (default: 127.0.0.1)",
    )
    network.add_argument(
        "--lan",
        action="store_true",
        help="listen on all interfaces and print URLs for nearby devices",
    )
    parser.add_argument(
        "--agent",
        choices=["codex", "claude", "mock", "auto"],
        default="codex",
        help="model backend to use for /ask",
    )
    parser.add_argument("--mock", action="store_true", help="shortcut for --agent mock")
    parser.add_argument(
        "--perception",
        choices=agent.PERCEPTION_MODES,
        default=agent.PERCEPTION_MODE,
        help="model perception policy: active index with typed retrieval (default), "
             "raster control, strict index ablation, or marked index",
    )
    parser.add_argument(
        "--context",
        choices=["v1", "pull", "v0"],
        default=agent.CONTEXT_VERSION,
        help="ink context payload: v1 (compact SVG, default), pull (v1 gist "
             "+ geometry in the on-demand detail file), "
             "or the original v0 JSON",
    )
    args = parser.parse_args()
    agent_mode = "mock" if args.mock else args.agent
    agent.PERCEPTION_MODE = args.perception
    agent.CONTEXT_VERSION = args.context

    bind_host = "0.0.0.0" if args.lan else args.host
    server = ThreadingHTTPServer((bind_host, args.port), Handler)
    label = "codex-cli" if agent_mode == "codex" else "claude-cli" if agent_mode == "claude" else agent_mode
    if agent_mode == "auto":
        mode = f"{label} (codex-cli, claude-cli, then mock fallback)"
    else:
        mode = label
    print(
        "Neeh ink assistant "
        f"[agent: {mode}] [perception: {args.perception}] [context: {args.context}]"
    )
    for url in _server_urls(bind_host, args.port):
        suffix = (
            "  (tablet)"
            if args.lan and not url.startswith("http://127.0.0.1:")
            else ""
        )
        print(f"  {url}{suffix}")
    if args.lan:
        print("LAN mode has no authentication; use it only on a trusted network.")
    server.serve_forever()


if __name__ == "__main__":
    main()
