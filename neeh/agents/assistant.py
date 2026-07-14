"""Reusable agent loop: user ink -> model perception -> tool calls -> answer ink.

The page is exposed either as a structured ink index with an on-demand raster,
or as the legacy raster plus Ink Context payload. The model answers by writing
ink through the same tool surface a human app would use.

`run_codex_cli` uses the user's Codex CLI login. `run_claude` uses the Claude
CLI login. `run_mock` exercises the identical Neeh tool path with canned calls
for keyless demos and tests.

This module lives in the SDK so applications can reuse the verified
model/context/tool orchestration without importing demo server code.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from neeh.canvas import Canvas
from neeh.document import Document
from neeh.agents.iai import (
    IAI_TOOL_SCHEMAS,
    PERCEPTION_POLICIES,
    build_observation_workspace,
)
from neeh.ink import Author, BoundingBox
from neeh.context import build_ink_context, build_ink_context_v1
from neeh.semantics import build_semantics
from neeh.tools import call_tool, tool_schemas

AGENT_INK = "#1d4ed8"  # agent ink is blue; user ink defaults to near-black
MAX_TURNS = 12
MAX_AGENT_NUDGE = 40.0
MAX_PLANNED_ACTIONS = 6
MAX_CONTEXT_STROKES = int(os.getenv("NEEH_CONTEXT_MAX_STROKES", "80"))
MAX_CONTEXT_POINTS = int(os.getenv("NEEH_CONTEXT_MAX_POINTS", "12"))
# "v1" sends compact SVG geometry. "pull" keeps geometry in the harness's
# on-demand detail source. "v0" is retained for compatibility.
CONTEXT_VERSION = os.getenv("NEEH_CONTEXT_VERSION", "v1")
PERCEPTION_MODE = os.getenv("NEEH_PERCEPTION_MODE", "active-index")
PERCEPTION_MODE_ALIASES = {"index": "active-index", "raster": "raster-always"}
PERCEPTION_MODES = ("index", "raster", *PERCEPTION_POLICIES)
PROMPT_PREVIEW_CHARS = int(os.getenv("NEEH_PROMPT_PREVIEW_CHARS", "5000"))
CODEX_MODEL = "gpt-5.5"
CODEX_REASONING_EFFORT = "high"

SYSTEM = """\
You are Neeh, an ink assistant who lives on a shared handwriting page. The user
writes or sketches a question in ink; you answer IN INK on the same page.

Each message describes how you perceive the page — as an image, a structured
index of the ink, a text rendering, or a mix. Coordinates are page units, (0,0)
at the top-left, x growing right and y growing down. The message states the page
size and, when a raster is attached, the region it covers; the rest of the page
is blank and available for your answer.

How to answer:
- Read the user's handwriting or drawing from the perception the message gives you.
- Make the SMALLEST edit that answers. When correcting something the user
  wrote, mark it up in place like a teacher would instead of rewriting it:
  use insert_text to add just the missing characters next to the user's own
  ink, and mark to strike/circle/underline/check it. Both take stroke ids
  from the context and compute the geometry for you — no coordinates needed.
  Example: missing quotes -> insert_text " before and after the word's
  strokes; do not transcribe their code again.
- For every correction request, edit the existing ink in place. NEVER use
  write_text to reproduce a corrected copy of a line already on the page,
  even when there are several fixes. Teacher-style markup is preferred over
  duplicating the user's work.
- Use write_text only for genuinely new answer content, such as an explanation
  or result that is not already written on the page. Use the handwritten style,
  put that new content in an empty region near the question, and leave a little
  margin.
- insert_text owns placement: it measures the new ink and automatically shifts
  the smallest same-line group needed to open a gap. Do not call move merely
  to make room for inserted text.
- To comment on part of the drawing, use annotate: give it your note text and
  the target's stroke ids and it writes the note beside that ink AND draws an
  arrow from the note to it, in one step. This keeps every label bound to the
  ink it describes — prefer it over a separate write_text plus connect, which
  can drift or cross when there are several notes.
- For a bare arrow with no note, use connect: it aims an arrow at the strokes
  you name by id (starting from other named ink when you give
  source_stroke_ids), computing the geometry for you. Never aim a freehand
  add_stroke arrow at existing ink — estimated coordinates miss.
- Pick the right stroke ids from the ink index/hints in the context: each id is
  labeled with the stroke's shape and position (e.g. "loop, lower-left"), so
  match the ink to its id there rather than guessing.
- Use add_stroke only for new freestanding shapes and diagrams; use highlight
  to emphasize part of the user's ink. Write in {agent_ink} so your ink is visibly yours.
- Keep written answers short: a sentence or two, or one worked step. This is a
  notebook page, not a chat window. Every stroke you add is re-sent on every
  future turn — sparse answers keep the page cheap.
- You plan all actions at once; you do not see the result before it is applied.
  So place answers in empty page area identified by the current perception, and prefer the
  anchored tools (mark, insert_text, connect) that compute geometry from stroke
  ids over hand-placed write_text/add_stroke — they cannot drift onto other ink.

When you are done, reply with one sentence summarizing what you wrote.
""".format(agent_ink=AGENT_INK)

OnAction = Callable[[str, dict[str, Any]], None]

_CODEX_CLI_TOOL_NAMES = {
    "add_stroke", "annotate", "connect", "highlight", "insert_text", "mark",
    "move", "write_text",
}
_ANNOTATE_SIDES = ("auto", "left", "right", "above", "below")
_CODEX_CLI_ACTION_INPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "points": {
            "type": ["array", "null"],
            "items": {"type": "array", "items": {"type": "number"}},
        },
        "region": {"type": ["array", "null"], "items": {"type": "number"}},
        "text": {"type": ["string", "null"]},
        "color": {"type": ["string", "null"]},
        "width": {"type": ["number", "null"]},
        "brush": {"type": ["string", "null"], "enum": ["pen", "marker", "highlighter", None]},
        "style": {"type": ["string", "null"], "enum": ["handwritten", None]},
        "size": {"type": ["number", "null"]},
        "stroke_ids": {"type": ["array", "null"], "items": {"type": "string"}},
        "source_stroke_ids": {"type": ["array", "null"], "items": {"type": "string"}},
        "kind": {"type": ["string", "null"],
                 "enum": ["strike", "circle", "underline", "check", None]},
        "position": {"type": ["string", "null"],
                     "enum": ["before", "after", "above", "below", None]},
        "side": {"type": ["string", "null"],
                 "enum": [*_ANNOTATE_SIDES, None]},
        "dx": {"type": ["number", "null"],
               "minimum": -MAX_AGENT_NUDGE, "maximum": MAX_AGENT_NUDGE},
        "dy": {"type": ["number", "null"],
               "minimum": -MAX_AGENT_NUDGE, "maximum": MAX_AGENT_NUDGE},
    },
    "required": ["points", "region", "text", "color", "width", "brush", "style",
                 "size", "stroke_ids", "source_stroke_ids", "kind", "position",
                 "side", "dx", "dy"],
}
_CODEX_CLI_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reply": {"type": "string"},
        "actions": {
            "type": "array",
            "maxItems": MAX_PLANNED_ACTIONS,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "tool": {"type": "string", "enum": sorted(_CODEX_CLI_TOOL_NAMES)},
                    "input": _CODEX_CLI_ACTION_INPUT_SCHEMA,
                },
                "required": ["tool", "input"],
            },
        },
    },
    "required": ["reply", "actions"],
}


class ModelUnavailableError(RuntimeError):
    """Raised when an external model backend is not configured or reachable."""


def _finite_agent_nudge(value: Any, axis: str) -> float:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError(f"agent move {axis} must be a finite number")
    result = float(value)
    if abs(result) > MAX_AGENT_NUDGE:
        raise ValueError(
            f"agent move {axis} must be between {-MAX_AGENT_NUDGE:g} "
            f"and {MAX_AGENT_NUDGE:g} page units"
        )
    return result


def _tool_result_content(result: dict[str, Any]) -> Any:
    """Views return base64 PNGs — hand those back as image blocks so the
    model actually sees them; everything else goes back as JSON text."""
    if result.get("format") == "png":
        meta = {k: v for k, v in result.items() if k != "data"}
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": result["data"]}},
            {"type": "text", "text": json.dumps(meta)},
        ]
    return json.dumps(result)


def _ink_crop(canvas: Canvas) -> Optional[BoundingBox]:
    """The inked part of the page, padded — or None for a blank page.

    Cropping blank page area reduces image size. All strokes intersect their
    own union box, and the crop is declared in both ``ink.region`` and
    ``raster.region`` so coordinates remain in page space.
    """
    boxes = [s.bbox for layer in canvas.page.layers if layer.visible
             for s in layer.strokes]
    if not boxes:
        return None
    b = BoundingBox.union_all(boxes)
    pad = max(24.0, 0.05 * max(b.max_x - b.min_x, b.max_y - b.min_y))
    return BoundingBox(
        max(0.0, b.min_x - pad), max(0.0, b.min_y - pad),
        min(canvas.page.width, b.max_x + pad),
        min(canvas.page.height, b.max_y + pad),
    )


def _page_raster(canvas: Canvas) -> bytes:
    # Imported lazily so `import neeh.agents` works without Pillow; the
    # dependency is only needed when a raster is actually requested.
    from neeh.rendering.png import render_page_png

    return render_page_png(canvas.page, region=_ink_crop(canvas))


def _perception_mode() -> str:
    if PERCEPTION_MODE not in PERCEPTION_MODES:
        choices = ", ".join(PERCEPTION_MODES)
        raise ValueError(f"unknown perception mode {PERCEPTION_MODE!r}; choose {choices}")
    return PERCEPTION_MODE


def _perception_policy() -> str:
    return PERCEPTION_MODE_ALIASES.get(_perception_mode(), _perception_mode())


def _structured_primary() -> bool:
    return _perception_policy() not in {"raster-only", "raster-always"}


def _raster_perception() -> bool:
    return _perception_policy() in {"raster-only", "raster-always"}


def _active_perception() -> bool:
    return _perception_policy() in {"active-index", "marked-index"}


def _bootstrap_raster_required(
    canvas: Canvas,
    instruction: Optional[str],
) -> bool:
    """Attach pixels up front when the task requires reading ink semantics.

    The structured map can answer temporal and geometric questions exactly,
    but stroke shapes and bboxes cannot reveal the words on the page. The host
    can identify that evidence need before model invocation, avoiding a brittle
    dependency on the model deciding to request a raster itself.
    """
    if not _active_perception():
        return False
    user_ink = any(
        stroke.author is Author.USER
        for layer in canvas.page.layers if layer.visible
        for stroke in layer.strokes
    )
    if not user_ink:
        return False
    task = " ".join((instruction or "").casefold().split())
    if not task:
        return True
    semantic_visual_phrases = (
        "handwritten",
        "handwriting",
        "question",
        "sentence",
        "read",
        "text",
        "word",
        "symbol",
        "equation",
        "solve",
        "fix",
        "correct",
        "grammar",
        "spelling",
        "translate",
        "what does",
        "what is written",
        "this page",
        "this diagram",
        "this sketch",
        "explain this",
    )
    return any(phrase in task for phrase in semantic_visual_phrases)


def _recognized_semantics(canvas: Canvas) -> list[dict[str, Any]]:
    """Geometric recognizer output, filtered to strokes the payload keeps and
    trimmed to its highest-value signal.

    The v1 builder truncates to the newest MAX_CONTEXT_STROKES strokes and
    rejects semantics that reference dropped ink, so items are filtered against
    the same newest-tail rule. Of those, only *links* (an arrow relating one
    group to another — structure the image shows poorly) and the clusters those
    links reference are sent; standalone grouping clusters are dropped, since
    the raster and the scoped ink.hints already convey grouping far more cheaply
    than enumerating every stroke id in a handwritten word."""
    strokes = [s for layer in canvas.page.layers if layer.visible
               for s in layer.strokes]
    kept = {s.id for s in strokes[-MAX_CONTEXT_STROKES:]}
    items = [item for item in build_semantics(canvas.page)
             if all(sid in kept for sid in item["stroke_ids"])]
    by_id = {item["id"]: item for item in items}
    links = [item for item in items
             if item.get("kind") == "link"
             and all(t in by_id for t in (item.get("edges") or {}).values())]
    referenced = {t for link in links for t in link["edges"].values()}
    clusters = [item for item in items
                if item.get("kind") == "cluster" and item["id"] in referenced]
    # Preserve document order (clusters precede the links that bind them).
    return [item for item in items if item in clusters or item in links]


def _ink_context(canvas: Canvas) -> dict[str, Any]:
    if CONTEXT_VERSION == "v0":
        return build_ink_context(
            canvas,
            max_strokes=MAX_CONTEXT_STROKES,
            max_points_per_stroke=MAX_CONTEXT_POINTS,
        )
    payload = build_ink_context_v1(
        canvas,
        max_strokes=MAX_CONTEXT_STROKES,
        raster="attached_image",
        region=_ink_crop(canvas),
        stroke_bboxes=(CONTEXT_VERSION == "pull"),
        stroke_hints=True,
        semantics=_recognized_semantics(canvas),
    )
    if CONTEXT_VERSION == "pull":
        # Keep geometry out of the primary payload. The CLI prompt points to a
        # separate detailed context file for on-demand inspection.
        payload["ink"]["svg"] = (
            "(geometry omitted from the primary payload — read the on-demand "
            "detail source described by the agent harness when needed)"
        )
    return payload


def _raster_only_context(canvas: Canvas) -> dict[str, Any]:
    crop = _ink_crop(canvas) or canvas.page.rect
    return {
        "schema": "ink-raster/v1",
        "page": {
            "id": canvas.page.id,
            "width": canvas.page.width,
            "height": canvas.page.height,
        },
        "raster": {
            "region": crop.to_list(),
            "temporal_evidence": False,
            "geometry_evidence": False,
        },
    }


def _perception(
    canvas: Canvas,
    instruction: Optional[str] = None,
) -> dict[str, Any]:
    """Build the primary model channel for the selected perception mode."""
    if _perception_policy() == "raster-only":
        return _raster_only_context(canvas)
    if _structured_primary():
        return build_observation_workspace(
            canvas,
            instruction,
            policy=_perception_policy(),
        )
    return _ink_context(canvas)


def _detailed_ink_context(canvas: Canvas) -> dict[str, Any]:
    """High-fidelity fallback materialized outside the initial prompt."""
    return build_ink_context_v1(
        canvas,
        max_strokes=MAX_CONTEXT_STROKES,
        raster="none",
        region=_ink_crop(canvas),
        stroke_bboxes=True,
        stroke_hints=True,
        semantics=_recognized_semantics(canvas),
    )


def _perception_telemetry(
    canvas: Canvas,
    instruction: Optional[str],
    telemetry_path: Optional[Path] = None,
    bootstrap_raster: bool = False,
) -> dict[str, Any]:
    bootstrap = _perception(canvas, instruction)
    telemetry: dict[str, Any] = {
        "policy": _perception_policy(),
        "bootstrap_chars": len(json.dumps(bootstrap, separators=(",", ":"))),
        "perception_actions": 0,
        "action_types": [],
        "observation_chars": 0,
        "raster_pixels": 0,
        "moment_queries": 0,
        "analyzer_queries": 0,
        "replay_steps": 0,
    }
    if _raster_perception() or bootstrap_raster:
        crop = _ink_crop(canvas)
        if crop is not None:
            telemetry["raster_pixels"] = round(crop.width * crop.height)
    if telemetry_path is not None and telemetry_path.exists():
        try:
            records = [
                json.loads(line)
                for line in telemetry_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            for record in records:
                telemetry["bootstrap_chars"] = max(
                    telemetry["bootstrap_chars"], record.get("bootstrap_chars", 0)
                )
                telemetry["perception_actions"] += record.get("perception_actions", 0)
                telemetry["action_types"].extend(record.get("action_types") or [])
                telemetry["observation_chars"] += record.get("observation_chars", 0)
                telemetry["raster_pixels"] += record.get("raster_pixels", 0)
                telemetry["moment_queries"] += record.get("moment_queries", 0)
                telemetry["analyzer_queries"] += record.get("analyzer_queries", 0)
                telemetry["replay_steps"] += record.get("replay_steps", 0)
                if "budget" in record:
                    telemetry["budget"] = record["budget"]
        except (OSError, ValueError, TypeError):
            pass
    telemetry["estimated_tokens"] = round(
        (telemetry["bootstrap_chars"] + telemetry["observation_chars"]) / 4
        + telemetry["raster_pixels"] / 750
    )
    return telemetry


def _context_note(context: dict[str, Any]) -> str:
    """v1 path data uses a grid; tool calls must stay in page units."""
    if "ink" not in context:
        return ""
    grid_w, grid_h = context["ink"]["grid"]
    scale = context["page"]["width"] / grid_w
    return (
        f"\nCoordinate note: ink.svg path coordinates are on a {grid_w}x{grid_h} "
        f"grid; multiply by {scale:.3f} to convert to page units. Every tool-call "
        f"coordinate (regions, points) MUST be in page units, never grid units."
    )


def _perception_note(
    page_path: Optional[Path] = None,
    detail_path: Optional[Path] = None,
) -> str:
    policy = _perception_policy()
    if policy == "raster-only":
        return (
            "Primary perception: cropped page raster only. This control has no "
            "stroke geometry, ordering, timing, ids, or perception tools."
            + (f" The raster is at {page_path}." if page_path is not None else "")
        )
    if policy == "index-only":
        return (
            "Primary perception: structured ink index only. This is a strict "
            "ablation: no raster, detailed geometry, or perception tools are "
            "available. Ground actions only in the bootstrap page map."
        )
    if _structured_primary():
        raster_fallback = (
            f" A cropped page raster is attached from {page_path}. Inspect it before "
            "planning any action that depends on handwritten words, symbols, or "
            "visual meaning. Never infer page text from stroke shapes or positions."
            if page_path is not None else
            " A cropped page raster will be available to the model on demand, but "
            "is not attached to the initial request. Never infer handwritten words "
            "from stroke shapes or positions; request a raster when the task depends "
            "on page text or visual meaning."
        )
        detail_fallback = (
            f" Detailed ink geometry and handwriting stroke ids are available at "
            f"{detail_path}; read that file only when an anchored edit needs ids "
            "that the index intentionally summarized."
            if detail_path is not None else
            " Detailed ink geometry and handwriting stroke ids will "
            "also be available to the model on demand for anchored edits."
        )
        marked = (
            " The bootstrap also includes an ASCII Set-of-Marks view; its legend "
            "binds each overlay label to a stable stroke id."
            if policy == "marked-index" else ""
        )
        return (
            f"Primary perception policy: {policy}. Treat page_map marks and their "
            "stable ids/bboxes as authoritative for grounding. Use the typed IAI "
            "perception actions (find_marks, analyze_ink, reduce_ink, "
            "find_ink_moments, inspect_ink_moment, view_region, get_ink, "
            "expand_relations) only when the bootstrap is insufficient."
            + marked
            + raster_fallback
            + detail_fallback
        )
    detail_fallback = (
        f" Detailed ink geometry is available at {detail_path} when the compact "
        "primary payload omits it."
        if detail_path is not None else ""
    )
    return (
        "Primary perception: cropped page raster plus compact ink geometry."
        + detail_fallback
    )


def _focus_note(canvas: Canvas) -> str:
    """Tell the model which ink is NEW since its own last reply.

    Provider prompt caching dedupes cost, not behavior: the model still
    attends to the whole page and will re-answer old questions. The turn
    boundary is computable from ink itself — agent strokes are
    author=AGENT with timestamps — so we state it instead of hoping."""
    strokes = [s for layer in canvas.page.layers if layer.visible
               for s in layer.strokes]
    agent_ts = [s.created_at_ms for s in strokes if s.author is Author.AGENT]
    if not agent_ts:
        return ""
    last = max(agent_ts)
    new = [s.id for s in strokes
           if s.author is not Author.AGENT and s.created_at_ms > last]
    if new:
        return (
            "\nFocus note: you have already answered on this page (your ink is "
            f"author=agent, drawn in {AGENT_INK}). New user ink since your last "
            f"reply: {json.dumps(new)}. Respond ONLY to that new ink; treat all "
            "older ink as answered context — do not answer it again or rewrite "
            "prior answers."
        )
    return (
        "\nFocus note: you have already answered on this page and there is no "
        "new user ink. Do not repeat prior answers; act only on what the "
        "instruction explicitly asks."
    )


def _situation_note(context: dict[str, Any]) -> str:
    """A short, factual summary of what is on the page. It conditions which
    system guidance applies this turn (correcting handwriting vs. pointing at
    marks) without restating those rules in full — the system prompt already
    carries them once."""
    page_map = context.get("page_map", {})
    ink = context.get("ink", {})
    hints = ink.get("hints") or {}
    marks = page_map.get("marks") or context.get("marks") or []
    included = page_map.get(
        "included_stroke_count",
        context.get("included_stroke_count", ink.get("included_stroke_count", 0)),
    ) or 0
    handwriting = page_map.get(
        "handwriting_stroke_count",
        context.get("handwriting_stroke_count", included - len(hints)),
    ) or 0
    parts = []
    target_count = len(marks) if marks else len(hints)
    if target_count:
        source = "marks" if marks else "ink.hints"
        parts.append(f"{target_count} labeled mark(s) you can target by id ({source})")
    if handwriting >= 3:
        if marks:
            parts.append("handwriting summarized by the index (use on-demand detail to read or edit it)")
        else:
            parts.append("handwriting you can mark up in place")
    if not parts:
        return ""
    return "\nOn this page: " + "; ".join(parts) + "."


def _planner_rules(canvas: Canvas) -> str:
    """Planner mechanics only. The behavioral guidance (smallest edit, correct
    in place, annotate/connect, hints) lives once in SYSTEM; repeating it here
    every turn is pure duplication, so this block stays lean."""
    page = canvas.page
    return (
        "Rules:\n"
        "- Return only JSON matching the schema; do not edit files, run commands, "
        "mention implementation details, or ask a follow-up question.\n"
        f"- Use at most {MAX_PLANNED_ACTIONS} actions; the shared input object means "
        f"unused fields are null. Agent ink is {AGENT_INK}, handwritten style.\n"
        f"- Coordinates are page units; the page is {page.width:g} x {page.height:g}. "
        "Follow the tool and editing guidance in the system instructions above."
    )


def _ink_context_text(canvas: Canvas) -> str:
    context = _ink_context(canvas)
    label = "v0" if context["schema"] == "ink-context/v0" else "v1"
    if CONTEXT_VERSION == "pull":
        label = "v1 (pull mode — geometry via the harness detail source)"
    return (
        f"Current Ink Context Format {label} payload:\n"
        + json.dumps(context, separators=(",", ":"))
        + _context_note(context)
        + _focus_note(canvas)
    )


def _codex_cli_tool_contract() -> list[dict[str, Any]]:
    return [
        {
            "name": "write_text",
            "purpose": "write genuinely new answer content in blank space; NEVER use "
                       "this to reproduce or correct a line already on the page",
            "required": {"text": "string", "region": "[min_x,min_y,max_x,max_y]"},
            "optional": {"color": f"hex, prefer {AGENT_INK}",
                         "style": "handwritten (applied by default)", "size": "number"},
        },
        {
            "name": "highlight",
            "purpose": "draw a translucent band over an existing area",
            "required": {"region": "[min_x,min_y,max_x,max_y]"},
            "optional": {"color": "hex"},
        },
        {
            "name": "add_stroke",
            "purpose": "draw arrows, marks, or simple diagram strokes",
            "required": {"points": "[[x,y,t_ms,pressure,tilt_x,tilt_y],...]"},
            "optional": {"color": "hex", "width": "number", "brush": "pen|marker|highlighter"},
        },
        {
            "name": "mark",
            "purpose": "annotate existing ink by stroke id; geometry is computed "
                       "for you (strike = cross out, underline, circle, check)",
            "required": {"stroke_ids": "ids from the context", "kind": "strike|circle|underline|check"},
            "optional": {"color": f"hex, prefer {AGENT_INK}"},
        },
        {
            "name": "annotate",
            "purpose": "write a note about part of the drawing AND point an arrow "
                       "from the note to it, in one action; the note is placed "
                       "beside the target and the arrow is bound to it, so the "
                       "label and its target never cross or get mispaired — use "
                       "this for every 'point at X and explain' answer",
            "required": {"text": "string", "stroke_ids": "ids of the ink the note is about"},
            "optional": {"side": f"one of {list(_ANNOTATE_SIDES)} (default auto)",
                         "color": f"hex, prefer {AGENT_INK}", "size": "number"},
        },
        {
            "name": "connect",
            "purpose": "draw a bare arrow (no note) that points at ink you name by "
                       "stroke id; geometry is computed for you — the precise way "
                       "to point at or link existing ink, never estimate arrow "
                       "coordinates with add_stroke. If the arrow needs a caption, "
                       "use annotate instead",
            "required": {"stroke_ids": "ids of the ink the arrow points AT"},
            "optional": {"source_stroke_ids": "ids the arrow starts from",
                         "color": f"hex, prefer {AGENT_INK}"},
        },
        {
            "name": "insert_text",
            "purpose": "write text placed relative to existing ink, auto-sized to "
                       "match it, with collision-free space created automatically; "
                       "the precise way to insert a missing character or word next "
                       "to what the user wrote — no coordinates or move needed",
            "required": {"text": "string", "stroke_ids": "anchor ids from the context",
                         "position": "before|after|above|below"},
            "optional": {"color": f"hex, prefer {AGENT_INK}", "size": "number"},
        },
        {
            "name": "move",
            "purpose": "rearrange named strokes only when the user explicitly asks "
                       "to move content; insert_text already handles spacing",
            "required": {"stroke_ids": "ids from the context", "dx": "page-unit offset",
                         "dy": "page-unit offset"},
            "limits": {"dx": [-MAX_AGENT_NUDGE, MAX_AGENT_NUDGE],
                       "dy": [-MAX_AGENT_NUDGE, MAX_AGENT_NUDGE]},
        },
    ]


def _prompt_preview(prompt: str) -> dict[str, Any]:
    truncated = len(prompt) > PROMPT_PREVIEW_CHARS
    text = prompt[:PROMPT_PREVIEW_CHARS]
    if truncated:
        text += f"\n\n... truncated; append ?full=1 to /agent-input for all {len(prompt)} chars ..."
    return {"text": text, "chars": len(prompt), "truncated": truncated}


def _codex_cli_tool_schemas() -> list[dict[str, Any]]:
    return [schema for schema in tool_schemas() if schema["name"] in _CODEX_CLI_TOOL_NAMES]


def agent_input_preview(
    canvas: Canvas,
    instruction: Optional[str] = None,
    *,
    full: bool = False,
) -> dict[str, Any]:
    context = _perception(canvas, instruction)
    prompt = _codex_cli_prompt(canvas, instruction, context=context)
    context_json = json.dumps(context, separators=(",", ":"))
    attached = _raster_perception() or _bootstrap_raster_required(canvas, instruction)
    available = _active_perception() or attached
    raster = _page_raster(canvas) if attached else b""
    preview = {
        "mode": "codex-cli",
        "perception_mode": _perception_mode(),
        "perception_policy": _perception_policy(),
        "image": {
            "format": "png",
            "transport": (
                "codex exec --image" if attached
                else "IAI view_region" if available
                else "unavailable"
            ),
            "available": available,
            "attached": attached,
            "bytes": len(raster),
        },
        "context": context,
        "context_chars": len(context_json),
        "prompt_chars": len(prompt),
        "prompt_preview": _prompt_preview(prompt),
        "perception_tools": IAI_TOOL_SCHEMAS if _active_perception() else [],
        "tools": _codex_cli_tool_contract(),
        "output_schema": f"JSON object with reply plus up to {MAX_PLANNED_ACTIONS} Neeh tool actions",
        "raw_prompt_available": True,
    }
    if full:
        preview["prompt"] = prompt
        preview["tool_schemas"] = _codex_cli_tool_schemas()
    return preview


def _json_object_from_text(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(text[start:end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output was not a JSON object")
    return data


def _cli_result_payload(raw: str) -> dict[str, Any]:
    payload = _json_object_from_text(raw)

    structured = payload.get("structured_output")
    if isinstance(structured, dict):
        return structured
    if isinstance(structured, str):
        try:
            return _json_object_from_text(structured)
        except Exception:
            pass

    result = payload.get("result")
    if isinstance(result, dict):
        return result
    if isinstance(result, str):
        try:
            return _json_object_from_text(result)
        except Exception:
            pass

    return payload


def _codex_cli_prompt(
    canvas: Canvas,
    instruction: Optional[str],
    *,
    context: Optional[dict[str, Any]] = None,
    page_path: Optional[Path] = None,
    detail_path: Optional[Path] = None,
) -> str:
    ask = instruction or "Answer the question written on this page, in ink."
    context = context or _perception(canvas, instruction)
    if _perception_policy() == "index-only":
        channel_instruction = (
            "Use only the structured page map below; this ablation provides no "
            "perception tools or raster fallback."
        )
    elif _active_perception() and page_path is not None:
        channel_instruction = (
            "The task requires reading the user's ink, so inspect the attached "
            "cropped page image first. Use the structured page map and typed "
            "neeh_iai perception tools to ground any targeted edits in stable ids."
        )
    elif _active_perception():
        channel_instruction = (
            "Use the structured page map below first. If it is insufficient, use "
            "the typed neeh_iai perception tools to retrieve only the needed detail."
        )
    else:
        channel_instruction = (
            "Inspect the attached page image and use the compact ink context below "
            "to bind visible ink to stable stroke ids."
        )
    return f"""\
{SYSTEM}

You are running through Codex CLI as a JSON planner for the Neeh demo. You
cannot call Neeh action tools directly. {channel_instruction} Choose the Neeh
tool actions that should be applied, and return only JSON matching the provided
output schema.

{_perception_note(page_path, detail_path)}

Current perception payload:
{json.dumps(context, separators=(",", ":"))}{_context_note(context)}{_focus_note(canvas)}{_situation_note(context)}

Available Neeh action tools:
{json.dumps(_codex_cli_tool_contract(), separators=(",", ":"))}

{_planner_rules(canvas)}

User instruction: {ask}
"""


def _codex_cli_command(
    codex: str,
    tmp: Path,
    schema_path: Path,
    output_path: Path,
    image_path: Optional[Path] = None,
    state_path: Optional[Path] = None,
    task_path: Optional[Path] = None,
    telemetry_path: Optional[Path] = None,
) -> list[str]:
    cmd = [
        codex,
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--model",
        CODEX_MODEL,
        "-c",
        f'model_reasoning_effort={json.dumps(CODEX_REASONING_EFFORT)}',
        "--disable",
        "shell_tool",
        "--disable",
        "unified_exec",
        "--skip-git-repo-check",
        "-C",
        str(tmp),
        "--sandbox",
        "read-only",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
    ]
    if image_path is not None:
        cmd.extend(["--image", str(image_path)])
    if state_path is not None and task_path is not None:
        server_args = [
            "-m", "neeh.agents.iai_mcp",
            "--state", str(state_path),
            "--task-file", str(task_path),
            "--policy", _perception_policy(),
        ]
        if telemetry_path is not None:
            server_args.extend(["--telemetry", str(telemetry_path)])
        cmd.extend([
            "-c", f"mcp_servers.neeh_iai.command={json.dumps(sys.executable)}",
            "-c", f"mcp_servers.neeh_iai.args={json.dumps(server_args)}",
        ])
    cmd.append("-")
    return cmd


def _codex_cli_error(completed: subprocess.CompletedProcess[str]) -> str:
    detail = (completed.stderr or completed.stdout or "").strip()
    if not detail:
        detail = f"codex exec exited {completed.returncode}"
    return detail[-1200:]


def _apply_planned_actions(
    canvas: Canvas,
    planned: list[Any],
    on_action: Optional[OnAction],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    for item in planned[:MAX_PLANNED_ACTIONS]:
        if not isinstance(item, dict):
            continue
        name = item.get("tool")
        arguments = item.get("input") or {}
        if name not in _CODEX_CLI_TOOL_NAMES or not isinstance(arguments, dict):
            continue
        arguments = {key: value for key, value in arguments.items() if value is not None}
        # Model-written answer text always uses the distinct agent hand,
        # regardless of stale planner output or an omitted style.
        if name == "write_text":
            arguments["style"] = "handwritten"
        try:
            if name == "move":
                if not arguments.get("stroke_ids"):
                    raise ValueError("agent move requires explicit stroke_ids")
                missing = [
                    stroke_id for stroke_id in arguments["stroke_ids"]
                    if canvas.page.find(stroke_id) is None
                ]
                if missing:
                    raise ValueError(f"agent move references unknown stroke ids: {missing}")
                locked = [
                    stroke_id for stroke_id in arguments["stroke_ids"]
                    if canvas.page.find(stroke_id)[0].locked
                ]
                if locked:
                    raise ValueError(f"agent move references locked stroke ids: {locked}")
                for axis in ("dx", "dy"):
                    value = _finite_agent_nudge(arguments.get(axis), axis)
                    arguments[axis] = value
            output = call_tool(canvas, name, arguments)
        except Exception as exc:
            actions.append({"tool": name, "input": arguments, "error": str(exc)})
            continue
        actions.append({"tool": name, "input": arguments, "output": output})
        if on_action:
            on_action(name, arguments)
    return actions


def _validate_planned_actions(
    canvas: Canvas,
    planned: list[Any],
) -> list[dict[str, Any]]:
    """Dry-run a full batch on a document clone before mutating live ink."""
    clone = Canvas(Document.from_dict(canvas.document.to_dict()))
    return _apply_planned_actions(clone, planned, None)


def _validation_failures(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [action for action in actions if "error" in action]


def _rejected_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Make clear that successful dry-run siblings were not applied either."""
    return [
        action if "error" in action else {
            "tool": action["tool"],
            "input": action["input"],
            "error": "plan not applied because another action failed validation",
        }
        for action in actions
    ]


def _repair_prompt(
    original_prompt: str,
    payload: dict[str, Any],
    validation: list[dict[str, Any]],
) -> str:
    feedback = [
        {
            "tool": action.get("tool"),
            "input": action.get("input"),
            "error": action.get("error"),
        }
        for action in validation
        if "error" in action
    ]
    return (
        original_prompt
        + "\n\nValidation rejected the previous batch atomically; nothing was applied.\n"
        + "Previous plan: "
        + json.dumps(payload, separators=(",", ":"))
        + "\nConcise validation feedback: "
        + json.dumps(feedback, separators=(",", ":"))
        + "\nReturn one corrected complete JSON plan. This is the only repair pass.\n"
    )


def run_codex_cli(
    canvas: Canvas,
    instruction: Optional[str] = None,
    on_action: Optional[OnAction] = None,
) -> dict[str, Any]:
    """Run one ask-the-page turn through the local Codex CLI login.

    Returns {"reply": str, "actions": [{"tool", "input"}...], "model": str}.
    """
    codex = shutil.which(os.getenv("NEEH_CODEX_CLI_BIN", "codex"))
    if not codex:
        raise ModelUnavailableError("codex CLI was not found on PATH")

    timeout = float(os.getenv("NEEH_CODEX_CLI_TIMEOUT", "180"))
    with tempfile.TemporaryDirectory(prefix="neeh-codex-") as tmp_dir:
        tmp = Path(tmp_dir)
        image_path = tmp / "page.png"
        detail_path = tmp / "ink-context.json"
        state_path = tmp / "page-state.json"
        task_path = tmp / "task.txt"
        telemetry_path = tmp / "iai-telemetry.json"
        schema_path = tmp / "response.schema.json"
        output_path = tmp / "response.json"
        page_available = (
            _raster_perception()
            or _bootstrap_raster_required(canvas, instruction)
        )
        if page_available:
            image_path.write_bytes(_page_raster(canvas))
        if _perception_policy() == "raster-always":
            detail_path.write_text(
                json.dumps(
                    _detailed_ink_context(canvas),
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        if _active_perception():
            canvas.document.save(state_path)
            task_path.write_text(
                instruction or "Answer the question written on this page, in ink.",
                encoding="utf-8",
            )
        schema_path.write_text(json.dumps(_CODEX_CLI_RESPONSE_SCHEMA), encoding="utf-8")
        attached_image = image_path if page_available else None
        mcp_state = state_path if _active_perception() else None
        mcp_task = task_path if _active_perception() else None

        command = _codex_cli_command(
            codex,
            tmp,
            schema_path,
            output_path,
            attached_image,
            mcp_state,
            mcp_task,
            telemetry_path if _active_perception() else None,
        )
        base_prompt = _codex_cli_prompt(
            canvas,
            instruction,
            page_path=image_path if page_available else None,
            detail_path=(
                detail_path if _perception_policy() == "raster-always" else None
            ),
        )

        def invoke(prompt: str) -> tuple[str, dict[str, Any]]:
            if output_path.exists():
                output_path.unlink()
            try:
                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ModelUnavailableError(f"codex exec timed out after {timeout:g}s") from exc
            if completed.returncode != 0:
                raise ModelUnavailableError(_codex_cli_error(completed))
            model_raw = (
                output_path.read_text(encoding="utf-8")
                if output_path.exists() else completed.stdout
            )
            return model_raw, _cli_result_payload(model_raw)

        raw, payload = invoke(base_prompt)
        planned = payload.get("actions") or []
        if not isinstance(planned, list):
            planned = []
        validation = _validate_planned_actions(canvas, planned)
        repair_attempted = bool(_validation_failures(validation))
        if repair_attempted:
            raw, payload = invoke(_repair_prompt(base_prompt, payload, validation))
            planned = payload.get("actions") or []
            if not isinstance(planned, list):
                planned = []
            validation = _validate_planned_actions(canvas, planned)
        perception_telemetry = _perception_telemetry(
            canvas,
            instruction,
            telemetry_path if _active_perception() else None,
            bootstrap_raster=(page_available and not _raster_perception()),
        )

    validation_failures = _validation_failures(validation)
    actions = (
        _rejected_actions(validation)
        if validation_failures
        else _apply_planned_actions(canvas, planned, on_action)
    )
    if validation_failures:
        reply = "I could not write the planned answer on the page."
    else:
        reply = str(payload.get("reply") or "Codex planned an ink response.")
    return {
        "reply": reply,
        "actions": actions,
        "model": CODEX_MODEL,
        "reasoning_effort": CODEX_REASONING_EFFORT,
        "perception_mode": _perception_mode(),
        "perception_policy": _perception_policy(),
        "validation": {
            "passed": not validation_failures,
            "repair_attempted": repair_attempted,
            "failure_count": len(validation_failures),
        },
        "perception_telemetry": perception_telemetry,
        "raw_model_output": raw,
    }


def _claude_cli_prompt(
    canvas: Canvas,
    instruction: Optional[str],
    *,
    page_path: Optional[Path],
    detail_path: Optional[Path] = None,
) -> str:
    ask = instruction or "Answer the question written on this page, in ink."
    context = _perception(canvas, instruction)
    if _perception_policy() == "index-only":
        channel_instruction = (
            "Use only the structured page map below; this ablation provides no "
            "perception tools or raster fallback."
        )
    elif _active_perception() and page_path is not None:
        channel_instruction = (
            "The task requires reading the user's ink, so inspect the cropped "
            "page image first. Use the structured page map and typed neeh_iai "
            "perception tools to ground any targeted edits in stable ids."
        )
    elif _active_perception():
        channel_instruction = (
            "Use the structured page map below first. If it is insufficient, use "
            "the typed neeh_iai perception tools to retrieve only the needed detail."
        )
    else:
        channel_instruction = (
            "Read the page image before planning, then bind visible ink to the "
            "compact context's stable stroke ids."
        )
    image_instruction = (
        f" When raw image detail is needed, Read can inspect {page_path}."
        if page_path is not None else ""
    )
    return f"""\
{SYSTEM}

You are running through Claude CLI as a JSON planner for the Neeh demo. Keep
Claude's default coding-agent behavior. {channel_instruction}{image_instruction}
Choose the Neeh tool actions that should be applied, and return only JSON
matching the provided output schema.

{_perception_note(page_path, detail_path)}

Current perception payload:
{json.dumps(context, separators=(",", ":"))}{_context_note(context)}{_focus_note(canvas)}{_situation_note(context)}

Available Neeh action tools:
{json.dumps(_codex_cli_tool_contract(), separators=(",", ":"))}

{_planner_rules(canvas)}

User instruction: {ask}
"""


def _claude_cli_command(
    claude: str,
    tmp: Path,
    prompt: str,
    *,
    state_path: Optional[Path] = None,
    task_path: Optional[Path] = None,
    telemetry_path: Optional[Path] = None,
    page_available: bool = False,
) -> list[str]:
    cmd = [claude, "-p"]
    if model := os.getenv("NEEH_CLAUDE_CLI_MODEL"):
        cmd.extend(["--model", model])
    tools = "Read" if page_available else ""
    if state_path is not None and task_path is not None:
        server_args = [
            "-m", "neeh.agents.iai_mcp",
            "--state", str(state_path),
            "--task-file", str(task_path),
            "--policy", _perception_policy(),
        ]
        if telemetry_path is not None:
            server_args.extend(["--telemetry", str(telemetry_path)])
        config = {
            "mcpServers": {
                "neeh_iai": {"command": sys.executable, "args": server_args},
            }
        }
        cmd.extend(["--mcp-config", json.dumps(config), "--strict-mcp-config"])
        perception_tools = (
            "mcp__neeh_iai__find_marks,mcp__neeh_iai__analyze_ink,"
            "mcp__neeh_iai__reduce_ink,"
            "mcp__neeh_iai__find_ink_moments,mcp__neeh_iai__inspect_ink_moment,"
            "mcp__neeh_iai__view_region,mcp__neeh_iai__get_ink,"
            "mcp__neeh_iai__expand_relations"
        )
        tools = f"Read,{perception_tools}" if page_available else perception_tools
    cmd.extend([
        prompt,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(_CODEX_CLI_RESPONSE_SCHEMA),
        "--append-system-prompt",
        SYSTEM,
        "--tools",
        tools,
        "--permission-mode",
        "bypassPermissions",
        "--add-dir",
        str(tmp),
        "--no-session-persistence",
    ])
    return cmd


def _claude_cli_error(completed: subprocess.CompletedProcess[str]) -> str:
    detail = (completed.stderr or completed.stdout or "").strip()
    if not detail:
        detail = f"claude -p exited {completed.returncode}"
    return detail[-1200:]


def run_claude(
    canvas: Canvas,
    instruction: Optional[str] = None,
    on_action: Optional[OnAction] = None,
) -> dict[str, Any]:
    """Run one ask-the-page turn through the local Claude CLI login.

    Returns {"reply": str, "actions": [{"tool", "input"}...], "model": str}.
    """
    claude = shutil.which(os.getenv("NEEH_CLAUDE_CLI_BIN", "claude"))
    if not claude:
        raise ModelUnavailableError("claude CLI was not found on PATH")

    timeout = float(os.getenv("NEEH_CLAUDE_CLI_TIMEOUT", "180"))
    with tempfile.TemporaryDirectory(prefix="neeh-claude-") as tmp_dir:
        tmp = Path(tmp_dir)
        page_path = tmp / "page.png"
        detail_path = tmp / "ink-context.json"
        state_path = tmp / "page-state.json"
        task_path = tmp / "task.txt"
        telemetry_path = tmp / "iai-telemetry.json"
        page_available = (
            _raster_perception()
            or _bootstrap_raster_required(canvas, instruction)
        )
        if page_available:
            page_path.write_bytes(_page_raster(canvas))
        if _perception_policy() == "raster-always":
            detail_path.write_text(
                json.dumps(
                    _detailed_ink_context(canvas),
                    separators=(",", ":"),
                ),
                encoding="utf-8",
            )
        if _active_perception():
            canvas.document.save(state_path)
            task_path.write_text(
                instruction or "Answer the question written on this page, in ink.",
                encoding="utf-8",
            )

        prompt = _claude_cli_prompt(
            canvas,
            instruction,
            page_path=page_path if page_available else None,
            detail_path=(
                detail_path if _perception_policy() == "raster-always" else None
            ),
        )

        def invoke(model_prompt: str) -> tuple[str, dict[str, Any]]:
            command = _claude_cli_command(
                claude,
                tmp,
                model_prompt,
                state_path=state_path if _active_perception() else None,
                task_path=task_path if _active_perception() else None,
                telemetry_path=telemetry_path if _active_perception() else None,
                page_available=page_available,
            )
            try:
                completed = subprocess.run(
                    command,
                    text=True,
                    capture_output=True,
                    timeout=timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise ModelUnavailableError(f"claude -p timed out after {timeout:g}s") from exc
            if completed.returncode != 0:
                raise ModelUnavailableError(_claude_cli_error(completed))
            return completed.stdout, _cli_result_payload(completed.stdout)

        raw, payload = invoke(prompt)
        planned = payload.get("actions") or []
        if not isinstance(planned, list):
            planned = []
        validation = _validate_planned_actions(canvas, planned)
        repair_attempted = bool(_validation_failures(validation))
        if repair_attempted:
            raw, payload = invoke(_repair_prompt(prompt, payload, validation))
            planned = payload.get("actions") or []
            if not isinstance(planned, list):
                planned = []
            validation = _validate_planned_actions(canvas, planned)
        perception_telemetry = _perception_telemetry(
            canvas,
            instruction,
            telemetry_path if _active_perception() else None,
            bootstrap_raster=(page_available and not _raster_perception()),
        )

    validation_failures = _validation_failures(validation)
    actions = (
        _rejected_actions(validation)
        if validation_failures
        else _apply_planned_actions(canvas, planned, on_action)
    )
    return {
        "reply": (
            "I could not write the planned answer on the page."
            if validation_failures
            else str(payload.get("reply") or "Claude planned an ink response.")
        ),
        "actions": actions,
        "model": os.getenv("NEEH_CLAUDE_CLI_MODEL", "default-profile"),
        "perception_mode": _perception_mode(),
        "perception_policy": _perception_policy(),
        "validation": {
            "passed": not validation_failures,
            "repair_attempted": repair_attempted,
            "failure_count": len(validation_failures),
        },
        "perception_telemetry": perception_telemetry,
        "raw_model_output": raw,
    }


def run_mock(
    canvas: Canvas,
    instruction: Optional[str] = None,
    on_action: Optional[OnAction] = None,
) -> dict[str, Any]:
    """Keyless stand-in: same tool surface, canned behavior. Highlights the
    user's ink and writes a mock answer below it."""
    page = canvas.page
    actions: list[dict[str, Any]] = []

    def act(tool: str, arguments: dict[str, Any]) -> None:
        call_tool(canvas, tool, arguments)
        actions.append({"tool": tool, "input": arguments})
        if on_action:
            on_action(tool, arguments)

    content = page.content_bbox
    if content is not None:
        pad = 12.0
        act("highlight", {"region": [
            max(content.min_x - pad, 0.0), max(content.min_y - pad, 0.0),
            min(content.max_x + pad, page.width), min(content.max_y + pad, page.height),
        ]})
        top = min(content.max_y + 40.0, page.height - 120.0)
    else:
        top = 80.0
    act("write_text", {
        "text": "Mock agent: I see your ink! Run codex login status if Codex CLI is unavailable.",
        "region": [60.0, top, page.width - 60.0, top + 110.0],
        "color": AGENT_INK,
        "style": "handwritten",
    })
    return {
        "reply": "Mock reply: highlighted your ink and wrote a note below it.",
        "actions": actions,
        "perception_mode": _perception_mode(),
        "perception_policy": _perception_policy(),
        "perception_telemetry": _perception_telemetry(canvas, instruction),
    }
