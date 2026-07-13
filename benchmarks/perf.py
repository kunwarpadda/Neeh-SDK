"""Latency and memory on realistic notebook pages.

Times the operations an embedding application actually pays for — analyzers,
task reducers, observation-workspace builds, event-log replay, and rendering —
on deterministic synthetic pages from light (100 strokes) to heavy (5000
strokes, well past a dense notebook page). Peak memory is measured with
tracemalloc on the heaviest page.

    python benchmarks/perf.py            # human-readable table
    python benchmarks/perf.py --json     # machine-readable report

No model, no network, no credentials; results are hardware-dependent but the
scaling shape is not.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import time
import tracemalloc
from typing import Any, Callable

from neeh import Canvas, render_page_ascii, render_page_svg
from neeh.agents import analyze_ink, build_observation_workspace, reduce_ink
from neeh.ink import Author

PAGE_SIZES = (100, 1000, 5000)
REPEATS = 5


def build_page(n: int, seed: int = 7) -> Canvas:
    rng = random.Random(seed)
    canvas = Canvas()
    for i in range(n):
        x = rng.uniform(40, 960)
        y = rng.uniform(40, 1374)
        pts = [(x + dx, y + rng.uniform(-3, 3)) for dx in range(0, 24, 6)]
        canvas.add_stroke(pts, author=Author.USER, created_at_ms=1_000_000 + i * 20)
    return canvas


def timed(fn: Callable[[], Any]) -> float:
    """Median wall time of REPEATS runs, in milliseconds."""
    samples = []
    for _ in range(REPEATS):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000.0)
    return round(statistics.median(samples), 3)


def measure(canvas: Canvas) -> dict[str, float]:
    ids = [s.id for layer in canvas.page.layers for s in layer.strokes][:16]
    out = {
        "analyze_latest_mark_ms": timed(lambda: analyze_ink(canvas, "latest_mark")),
        "analyze_spatial_collision_ms": timed(
            lambda: analyze_ink(canvas, "spatial_collision", limit=16)
        ),
        "analyze_stroke_dynamics_ms": timed(
            lambda: analyze_ink(canvas, "stroke_dynamics", stroke_ids=ids)
        ),
        "reduce_page_summary_ms": timed(lambda: reduce_ink(canvas, "page_summary")),
        "reduce_recent_changes_ms": timed(lambda: reduce_ink(canvas, "recent_changes")),
        "workspace_build_ms": timed(
            lambda: build_observation_workspace(canvas, "what changed most recently?")
        ),
        "eventlog_replay_ms": timed(lambda: canvas.events.replay()),
        "render_svg_ms": timed(lambda: render_page_svg(canvas.page)),
        "render_ascii_ms": timed(lambda: render_page_ascii(canvas.page)),
    }
    try:
        from neeh.rendering.png import render_page_png

        out["render_png_ms"] = timed(lambda: render_page_png(canvas.page))
    except ImportError:
        pass  # Pillow extra not installed; PNG timing simply omitted
    return out


def peak_memory_mb(n: int) -> float:
    tracemalloc.start()
    canvas = build_page(n)
    build_observation_workspace(canvas, "summary?")
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return round(peak / (1024 * 1024), 2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sizes", nargs="+", type=int, default=list(PAGE_SIZES))
    args = parser.parse_args()

    report: dict[str, Any] = {"repeats": REPEATS, "pages": {}}
    for n in args.sizes:
        canvas = build_page(n)
        report["pages"][str(n)] = measure(canvas)
    report["peak_memory_mb_at_max"] = peak_memory_mb(max(args.sizes))

    if args.json:
        print(json.dumps(report, indent=2))
        return
    for n, metrics in report["pages"].items():
        print(f"\n== {n} strokes ==")
        for name, ms in metrics.items():
            print(f"  {name:32} {ms:>10.3f} ms")
    print(f"\npeak memory @ {max(args.sizes)} strokes: {report['peak_memory_mb_at_max']} MB")


if __name__ == "__main__":
    main()
