"""Move 1: the controlled render-identical experiment.

Isolates the *unique* value of raw ink from general model quality. Each trial is
a pair of ink samples that rasterize to **byte-identical pixels** but differ on
exactly one hidden axis of the ink history — stroke direction, object creation
order, or pen pressure. A question is posed whose answer lives only in that
hidden history, so a PNG-only model is provably at chance while the answer is
recoverable from structured or serialized ink.

Three input conditions run through the *same* model:

    png         cropped page raster only            -> theoretical floor (info absent)
    png+struct  raster + structured ink record      -> the Track-1 ("recognizer index") ceiling
    coords      coordinate/point serialization only -> Fadeeva-style, no image

The gap between ``png`` and the structured arms measures whether the hidden
information is recoverable at all. This benchmark does not test or justify a
learned native encoder; the follow-up Move 1b result instead motivates bounded,
deterministic analysis over Neeh's existing ink records.

    # certify the trials and price the prompts without spending model calls
    python examples/move1_render_identical_pairs.py --dry-run

    # live sweep through Codex CLI (GPT-5.5 at high reasoning effort)
    python examples/move1_render_identical_pairs.py --agent codex --n-per-axis 8 \
        --output tmp/move1.json

Codex runs are hard-pinned to model=gpt-5.5 at reasoning_effort=high. Sweeps go
through the Codex CLI login, never a raw API.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from neeh.agents.assistant import _cli_result_payload  # robust CLI-envelope parsing
from neeh.document import Layer, Page
from neeh.ink import Author, BoundingBox, Point, Stroke, StrokeStyle
from neeh.rendering.png import render_page_png

AXES = ("direction", "order", "pressure")
CONDITIONS = ("png", "png+struct", "coords")

CODEX_MODEL = "gpt-5.5"
CODEX_EFFORT = "high"

_INK = StrokeStyle(color="#101010", width=3.0)


# --------------------------------------------------------------------------- #
# Trial construction
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Trial:
    """One render-identical pair member: a page, a question, and the ground
    truth that is only recoverable from the hidden ink history.

    ``page`` carries the honest ink history used for the structured/coordinate
    channels. ``image_page`` is what the model actually *sees* as a raster; it
    defaults to ``page`` but is set to a shared canonical page for axes whose
    answer is not in the pixels at all (direction). This sidesteps sub-pixel
    rasterizer asymmetry while keeping the claim exact: the image is byte-for-
    byte identical across twins, so a PNG-only model must be at chance.
    """

    trial_id: str
    axis: str
    page: Page
    question: str
    options: tuple[str, str]
    answer: str
    twin_id: str  # the sibling trial with identical pixels and the other answer
    image_page: Optional[Page] = None


def _raster_page(trial: Trial) -> Page:
    return trial.image_page or trial.page


def _stroke(
    xy: list[tuple[float, float]],
    *,
    created_at_ms: int,
    pressure: float = 1.0,
    duration_ms: int = 400,
    reverse: bool = False,
) -> Stroke:
    """Build a stroke with an explicit draw order and per-point timing.

    ``reverse`` draws the identical polyline in the opposite direction: the
    point sequence and t_ms flip, the pixels do not.
    """
    path = list(reversed(xy)) if reverse else list(xy)
    n = len(path)
    points = tuple(
        Point(
            x=x,
            y=y,
            t_ms=round(duration_ms * i / max(n - 1, 1)),
            pressure=pressure,
        )
        for i, (x, y) in enumerate(path)
    )
    return Stroke(points=points, style=_INK, author=Author.USER, created_at_ms=created_at_ms)


def _page(strokes: list[Stroke]) -> Page:
    return Page(layers=[Layer(name="ink", strokes=list(strokes))])


def _polyline(rng: random.Random, x0: float, y: float, x1: float, jitter: float) -> list[tuple[float, float]]:
    """A roughly horizontal wobble from x0 to x1 — enough points that draw
    order is legible, deterministic under a seed."""
    steps = 9
    pts = []
    for i in range(steps):
        t = i / (steps - 1)
        x = x0 + (x1 - x0) * t
        yy = y + rng.uniform(-jitter, jitter)
        pts.append((round(x, 1), round(yy, 1)))
    return pts


def _rectangle(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]


def _arrow(x0: float, y0: float, x1: float, y1: float) -> list[tuple[float, float]]:
    # shaft then a small V head, one polyline
    return [(x0, y0), (x1, y1), (x1 - 14, y1 - 8), (x1, y1), (x1 - 8, y1 + 12)]


def gen_direction(rng: random.Random, i: int) -> list[Trial]:
    y = rng.uniform(200, 900)
    x0, x1 = 160.0, rng.uniform(620, 840)
    path = _polyline(rng, x0, y, x1, jitter=18.0)
    base = f"direction-{i}"
    forward = _stroke(path, created_at_ms=1_000_000)
    backward = _stroke(path, created_at_ms=1_000_000, reverse=True)
    canonical = _page([forward])  # both twins are rendered from this exact raster
    q = ("A single pen stroke is on the page. In which direction was it drawn — "
         "from its left end to its right end, or from its right end to its left end?")
    opts = ("left-to-right", "right-to-left")
    return [
        Trial(f"{base}a", "direction", canonical, q, opts, "left-to-right", f"{base}b",
              image_page=canonical),
        Trial(f"{base}b", "direction", _page([backward]), q, opts, "right-to-left", f"{base}a",
              image_page=canonical),
    ]


def gen_order(rng: random.Random, i: int) -> list[Trial]:
    bx = rng.uniform(120, 300)
    by = rng.uniform(200, 500)
    box_pts = _rectangle(bx, by, bx + 180, by + 130)
    ax = rng.uniform(560, 720)
    ay = rng.uniform(600, 900)
    arrow_pts = _arrow(ax, ay, ax + 150, ay + 90)
    base = f"order-{i}"

    def page(box_first: bool) -> Page:
        t_box = 1_000_000 if box_first else 1_000_800
        t_arrow = 1_000_800 if box_first else 1_000_000
        box = _stroke(box_pts, created_at_ms=t_box)
        arrow = _stroke(arrow_pts, created_at_ms=t_arrow)
        # store in a fixed spatial order (box then arrow) so list position never
        # leaks the answer; only created_at_ms distinguishes the twins.
        return _page([box, arrow])

    q = ("The page has a rectangle and an arrow. Which one was drawn first — "
         "the rectangle or the arrow?")
    opts = ("rectangle", "arrow")
    return [
        Trial(f"{base}a", "order", page(True), q, opts, "rectangle", f"{base}b"),
        Trial(f"{base}b", "order", page(False), q, opts, "arrow", f"{base}a"),
    ]


def gen_pressure(rng: random.Random, i: int) -> list[Trial]:
    y = rng.uniform(220, 880)
    x0, x1 = 180.0, rng.uniform(600, 820)
    path = _polyline(rng, x0, y, x1, jitter=10.0)
    base = f"pressure-{i}"
    light = _stroke(path, created_at_ms=1_000_000, pressure=0.18)
    heavy = _stroke(path, created_at_ms=1_000_000, pressure=0.95)
    q = ("A single pen stroke is on the page. Was it drawn with light pen "
         "pressure or heavy pen pressure?")
    opts = ("light", "heavy")
    return [
        Trial(f"{base}a", "pressure", _page([light]), q, opts, "light", f"{base}b"),
        Trial(f"{base}b", "pressure", _page([heavy]), q, opts, "heavy", f"{base}a"),
    ]


_GENERATORS: dict[str, Callable[[random.Random, int], list[Trial]]] = {
    "direction": gen_direction,
    "order": gen_order,
    "pressure": gen_pressure,
}


def build_trials(axes: list[str], n_per_axis: int, seed: int) -> list[Trial]:
    rng = random.Random(seed)
    trials: list[Trial] = []
    for axis in axes:
        for i in range(n_per_axis):
            trials.extend(_GENERATORS[axis](rng, i))
    return trials


# --------------------------------------------------------------------------- #
# Render-identity guard + perception channels
# --------------------------------------------------------------------------- #
def _content_crop(page: Page, pad: float = 28.0) -> Optional[BoundingBox]:
    box = page.content_bbox
    if box is None:
        return None
    return BoundingBox(
        max(0.0, box.min_x - pad), max(0.0, box.min_y - pad),
        min(page.width, box.max_x + pad), min(page.height, box.max_y + pad),
    )


def _pixels(page: Page) -> bytes:
    """Decoded RGB pixels of the cropped page — the object rasterization maps to.
    Comparing pixels (not PNG container bytes) is the strict R(I) equality test."""
    from PIL import Image

    png = render_page_png(page, region=_content_crop(page))
    return Image.open(io.BytesIO(png)).convert("RGB").tobytes()


def certify_identical(trials: list[Trial]) -> dict[str, bool]:
    """Every trial must rasterize identically to its twin. Returns per-pair
    certification; a False means a generator leaked signal into the pixels."""
    by_id = {t.trial_id: t for t in trials}
    result: dict[str, bool] = {}
    for t in trials:
        twin = by_id.get(t.twin_id)
        if twin is None:
            result[t.trial_id] = False
            continue
        pair = tuple(sorted((t.trial_id, t.twin_id)))
        if pair in result:
            continue
        result[pair] = _pixels(_raster_page(t)) == _pixels(_raster_page(twin))
    return result


def _sample_points(stroke: Stroke, cap: int) -> list[list[float]]:
    """Subsample a stroke's points to <= cap, always keeping first and last so
    draw direction survives the compression."""
    pts = stroke.points
    if len(pts) <= cap:
        keep = list(range(len(pts)))
    else:
        keep = sorted({round(i * (len(pts) - 1) / (cap - 1)) for i in range(cap)})
    return [[p.x, p.y, p.t_ms, round(p.pressure, 3)] for i, p in enumerate(pts) if i in keep]


def _shape_label(stroke: Stroke) -> str:
    """A cheap geometric label — the kind a Neeh recognizer index would carry.
    Providing it is representative of Track 1, not an answer leak: it never
    encodes order/direction/pressure."""
    pts = stroke.points
    closed = abs(pts[0].x - pts[-1].x) < 6 and abs(pts[0].y - pts[-1].y) < 6
    if closed and len(pts) >= 5:
        return "rectangle"
    if len(pts) >= 5 and not closed:
        return "arrow"
    return "stroke"


def _ink_record(page: Page, cap: int) -> list[dict[str, Any]]:
    """Structured per-stroke record: shape label, absolute creation time, and
    the (x, y, t_ms, pressure) point stream. Strokes appear in stored order,
    which is spatial — never sorted by time — so nothing but the fields leak."""
    strokes = page.all_strokes()
    return [
        {
            "shape": _shape_label(s),
            "created_at_ms": s.created_at_ms,
            "points": _sample_points(s, cap),
            "points_note": "[x, y, t_ms, pressure]; t_ms is offset from created_at_ms; points are in draw order",
        }
        for s in strokes
    ]


def _coord_text(page: Page, cap: int) -> str:
    lines = []
    for k, s in enumerate(page.all_strokes()):
        pts = " ".join(f"({x:g},{y:g},{t},{p:g})" for x, y, t, p in _sample_points(s, cap))
        lines.append(f"stroke{k} created_at_ms={s.created_at_ms} shape={_shape_label(s)}: {pts}")
    return "\n".join(lines)


_PREAMBLE = (
    "You are analyzing digital ink on a notebook page. Answer the question with "
    "exactly one of the allowed options. Coordinates are page units, (0,0) at "
    "top-left, x right, y down. Points within a stroke are listed in the order "
    "the pen drew them; t_ms is the milliseconds offset from the stroke's "
    "created_at_ms; pressure is 0..1."
)


def build_prompt(trial: Trial, condition: str, cap: int) -> str:
    ask = (
        f"Question: {trial.question}\n"
        f"Allowed options: {trial.options[0]!r} or {trial.options[1]!r}.\n"
        "Respond with JSON: {\"answer\": <one option>, \"why\": <one sentence>}."
    )
    if condition == "png":
        body = ("Perception: a cropped image of the page is attached. No ink "
                "history is provided.")
    elif condition == "png+struct":
        body = ("Perception: a cropped image is attached, plus this structured "
                "ink record:\n"
                + json.dumps(_ink_record(trial.page, cap), separators=(",", ":")))
    elif condition == "coords":
        body = ("Perception: no image. The ink is serialized as coordinate "
                "streams:\n" + _coord_text(trial.page, cap))
    else:
        raise ValueError(f"unknown condition {condition!r}")
    return f"{_PREAMBLE}\n\n{body}\n\n{ask}\n"


def _needs_image(condition: str) -> bool:
    return condition in ("png", "png+struct")


def estimate_tokens(trial: Trial, condition: str, cap: int) -> int:
    """Match the harness's telemetry estimate: chars/4 plus image pixels/750."""
    prompt = build_prompt(trial, condition, cap)
    tokens = len(prompt) / 4
    if _needs_image(condition):
        crop = _content_crop(_raster_page(trial))
        if crop is not None:
            tokens += (crop.width * crop.height) / 750
    return round(tokens)


# --------------------------------------------------------------------------- #
# Model backends
# --------------------------------------------------------------------------- #
class ModelUnavailableError(RuntimeError):
    pass


def _answer_schema(options: tuple[str, str]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "answer": {"type": "string", "enum": list(options)},
            "why": {"type": "string"},
        },
        "required": ["answer", "why"],
    }


def run_codex(trial: Trial, condition: str, prompt: str, image_png: Optional[bytes]) -> dict[str, Any]:
    codex = shutil.which(os.getenv("NEEH_CODEX_CLI_BIN", "codex"))
    if not codex:
        raise ModelUnavailableError("codex CLI was not found on PATH")
    timeout = float(os.getenv("NEEH_MOVE1_TIMEOUT", "180"))
    with tempfile.TemporaryDirectory(prefix="neeh-move1-") as tmp_dir:
        tmp = Path(tmp_dir)
        schema_path = tmp / "answer.schema.json"
        output_path = tmp / "answer.json"
        schema_path.write_text(json.dumps(_answer_schema(trial.options)), encoding="utf-8")
        cmd = [
            codex, "exec", "--ephemeral", "--ignore-user-config",
            "--disable", "shell_tool", "--disable", "unified_exec",
            "--skip-git-repo-check", "-C", str(tmp), "--sandbox", "read-only",
            "--output-schema", str(schema_path), "--output-last-message", str(output_path),
            "--model", CODEX_MODEL, "-c", f"model_reasoning_effort={CODEX_EFFORT}",
        ]
        if image_png is not None:
            image_path = tmp / "page.png"
            image_path.write_bytes(image_png)
            cmd.extend(["--image", str(image_path)])
        cmd.append("-")
        try:
            completed = subprocess.run(
                cmd, input=prompt, text=True, capture_output=True,
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ModelUnavailableError(f"codex exec timed out after {timeout:g}s") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[-800:]
            raise ModelUnavailableError(detail or f"codex exec exited {completed.returncode}")
        raw = output_path.read_text(encoding="utf-8") if output_path.exists() else completed.stdout
    payload = _cli_result_payload(raw)
    return {"answer": payload.get("answer"), "why": payload.get("why"), "raw": raw}


def run_mock(trial: Trial, condition: str, prompt: str, image_png: Optional[bytes]) -> dict[str, Any]:
    """Keyless oracle for pipeline validation. It reads the hidden history from
    the prompt exactly when that history is present — chance on png, correct on
    the channels that carry the signal — so the harness's own scoring is
    exercised without a model. Not a substitute for a real sweep."""
    if condition == "png":
        # No history in the pixels: always guess the first option. Twins are
        # balanced (opposite answers), so this is exactly chance by construction.
        return {"answer": trial.options[0], "why": "mock: no history", "raw": ""}
    strokes = trial.page.all_strokes()
    if trial.axis == "direction":
        s = strokes[0]
        ans = "left-to-right" if s.points[0].x <= s.points[-1].x else "right-to-left"
    elif trial.axis == "order":
        first = min(strokes, key=lambda s: s.created_at_ms)
        ans = _shape_label(first)
    else:  # pressure
        ans = "light" if strokes[0].points[0].pressure < 0.5 else "heavy"
    return {"answer": ans, "why": "mock: read from history", "raw": ""}


_BACKENDS = {"codex": run_codex, "mock": run_mock}


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def score(trial: Trial, condition: str, out: dict[str, Any], cap: int) -> dict[str, Any]:
    given = str(out.get("answer") or "").strip().casefold()
    correct = given == trial.answer.casefold()
    return {
        "trial": trial.trial_id,
        "axis": trial.axis,
        "condition": condition,
        "answer": trial.answer,
        "model_answer": out.get("answer"),
        "correct": correct,
        "estimated_tokens": estimate_tokens(trial, condition, cap),
        "why": out.get("why"),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for axis in sorted({r["axis"] for r in rows}):
        summary[axis] = {}
        for condition in CONDITIONS:
            cell = [r for r in rows if r["axis"] == axis and r["condition"] == condition]
            if not cell:
                continue
            n = len(cell)
            hits = sum(r["correct"] for r in cell)
            summary[axis][condition] = {
                "n": n,
                "correct": hits,
                "accuracy": round(hits / n, 3),
                "chance": 0.5,
                "mean_tokens": round(sum(r["estimated_tokens"] for r in cell) / n),
            }
    return summary


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--agent", choices=list(_BACKENDS), default="codex")
    parser.add_argument("--axes", nargs="+", choices=AXES, default=list(AXES))
    parser.add_argument("--conditions", nargs="+", choices=CONDITIONS, default=list(CONDITIONS))
    parser.add_argument("--n-per-axis", type=int, default=6, help="pairs per axis (2 trials each)")
    parser.add_argument("--sample-points", type=int, default=24, help="max points per stroke in serializations")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true", help="certify pixel-identity + price prompts; no model calls")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    trials = build_trials(args.axes, args.n_per_axis, args.seed)
    certified = certify_identical(trials)
    pair_results = {k: v for k, v in certified.items() if isinstance(k, tuple)}
    all_identical = all(pair_results.values())
    cert = {
        "pairs": len(pair_results),
        "identical": sum(pair_results.values()),
        "all_render_identical": all_identical,
    }
    if not all_identical:
        cert["leaking_pairs"] = [list(k) for k, v in pair_results.items() if not v]

    backend = _BACKENDS[args.agent]
    rows: list[dict[str, Any]] = []

    if args.dry_run:
        for trial in trials:
            for condition in args.conditions:
                rows.append({
                    "trial": trial.trial_id,
                    "axis": trial.axis,
                    "condition": condition,
                    "prompt_chars": len(build_prompt(trial, condition, args.sample_points)),
                    "estimated_tokens": estimate_tokens(trial, condition, args.sample_points),
                    "has_image": _needs_image(condition),
                })
        token_by_condition = {
            c: round(sum(r["estimated_tokens"] for r in rows if r["condition"] == c)
                     / max(sum(r["condition"] == c for r in rows), 1))
            for c in args.conditions
        }
        report = {
            "mode": "dry-run", "trials": len(trials), "certification": cert,
            "mean_tokens_by_condition": token_by_condition, "rows": rows,
        }
        print(json.dumps({"certification": cert, "mean_tokens_by_condition": token_by_condition}, indent=2))
    else:
        for trial in trials:
            for condition in args.conditions:
                prompt = build_prompt(trial, condition, args.sample_points)
                raster = _raster_page(trial)
                image = render_page_png(raster, region=_content_crop(raster)) if _needs_image(condition) else None
                try:
                    out = backend(trial, condition, prompt, image)
                except ModelUnavailableError as exc:
                    out = {"answer": None, "why": f"error: {exc}", "raw": ""}
                row = score(trial, condition, out, args.sample_points)
                rows.append(row)
                print(json.dumps(row, separators=(",", ":")))
        summary = summarize(rows)
        report = {
            "mode": "live", "agent": args.agent,
            "model": CODEX_MODEL if args.agent == "codex" else args.agent,
            "reasoning_effort": CODEX_EFFORT if args.agent == "codex" else None,
            "certification": cert, "summary": summary, "rows": rows,
        }
        print(json.dumps({"certification": cert, "summary": summary}, indent=2))

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
