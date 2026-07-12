"""Reusable agent loop: user ink -> page PNG -> model -> tool calls -> answer ink.

The page is rendered so a multimodal
model can SEE it, the Neeh tool manifest (`tool_schemas()`) is passed to the
model API, and the model answers by writing ink through the same
tool surface a human app would use.

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
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from neeh.canvas import Canvas
from neeh.ink import Author, BoundingBox
from neeh.context import build_ink_context, build_ink_context_v1
from neeh.rendering.png import render_page_png
from neeh.semantics import build_semantics
from neeh.tools import call_tool, tool_schemas

AGENT_INK = "#1d4ed8"  # agent ink is blue; user ink defaults to near-black
MAX_TURNS = 12
MAX_AGENT_NUDGE = 40.0
MAX_PLANNED_ACTIONS = 6
MAX_CONTEXT_STROKES = int(os.getenv("NEEH_CONTEXT_MAX_STROKES", "80"))
MAX_CONTEXT_POINTS = int(os.getenv("NEEH_CONTEXT_MAX_POINTS", "12"))
# "v1" sends compact SVG geometry. "pull" sends bounding boxes and exposes
# fetch_ink_region for on-demand detail. "v0" is retained for compatibility.
CONTEXT_VERSION = os.getenv("NEEH_CONTEXT_VERSION", "v1")
PROMPT_PREVIEW_CHARS = int(os.getenv("NEEH_PROMPT_PREVIEW_CHARS", "5000"))

SYSTEM = """\
You are Neeh, an ink assistant who lives on a shared handwriting page. The user
writes or sketches a question in ink; you answer IN INK on the same page.

You see the page as an image. Coordinates are page units, (0,0) at the top-left,
x growing right and y growing down. The first message states the page size.
To save cost the image may show only the inked part of the page — when the
context declares a raster region [min_x, min_y, max_x, max_y], the image covers
exactly that region of the page; the rest of the page is blank and available
for your answer.

How to answer:
- Read the user's handwriting or drawing from the image.
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
- To point at or link ink already on the page, use connect: it aims an arrow
  at the strokes you name by id (and starts it from other named ink when you
  give source_stroke_ids), computing the geometry for you. Never aim a
  freehand add_stroke arrow at existing ink — estimated coordinates miss.
- Use add_stroke only for new freestanding shapes and diagrams; use highlight
  to emphasize part of the user's ink. Write in {agent_ink} so your ink is visibly yours.
- Keep written answers short: a sentence or two, or one worked step. This is a
  notebook page, not a chat window. Every stroke you add is re-sent on every
  future turn — sparse answers keep the page cheap.
- After writing, call view_page with format "png" to check placement and
  legibility. If your ink overlaps something, undo and place it again.

When you are done, reply with one sentence summarizing what you wrote.
""".format(agent_ink=AGENT_INK)

OnAction = Callable[[str, dict[str, Any]], None]

_CODEX_CLI_TOOL_NAMES = {
    "add_stroke", "connect", "highlight", "insert_text", "mark", "move", "write_text",
}
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
        "dx": {"type": ["number", "null"],
               "minimum": -MAX_AGENT_NUDGE, "maximum": MAX_AGENT_NUDGE},
        "dy": {"type": ["number", "null"],
               "minimum": -MAX_AGENT_NUDGE, "maximum": MAX_AGENT_NUDGE},
    },
    "required": ["points", "region", "text", "color", "width", "brush", "style",
                 "size", "stroke_ids", "source_stroke_ids", "kind", "position",
                 "dx", "dy"],
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
    return render_page_png(canvas.page, region=_ink_crop(canvas))


def _recognized_semantics(canvas: Canvas) -> list[dict[str, Any]]:
    """Geometric recognizer output, filtered to strokes the payload keeps.

    The v1 builder truncates to the newest MAX_CONTEXT_STROKES strokes and
    rejects semantics that reference dropped ink, so items (and links whose
    endpoints vanished) are filtered against the same newest-tail rule."""
    strokes = [s for layer in canvas.page.layers if layer.visible
               for s in layer.strokes]
    kept = {s.id for s in strokes[-MAX_CONTEXT_STROKES:]}
    items = [item for item in build_semantics(canvas.page)
             if all(sid in kept for sid in item["stroke_ids"])]
    ids = {item["id"] for item in items}
    return [item for item in items
            if all(t in ids for t in (item.get("edges") or {}).values())]


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
        semantics=_recognized_semantics(canvas),
    )
    if CONTEXT_VERSION == "pull":
        # Send the page-space index and retrieve detailed geometry on demand.
        payload["ink"]["svg"] = (
            "(geometry omitted — call fetch_ink_region with a page-unit "
            "region to get compact SVG paths with stable stroke ids)"
        )
    return payload


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


def _ink_context_text(canvas: Canvas) -> str:
    context = _ink_context(canvas)
    label = "v0" if context["schema"] == "ink-context/v0" else "v1"
    if CONTEXT_VERSION == "pull":
        label = "v1 (pull mode — geometry via fetch_ink_region)"
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
            "name": "connect",
            "purpose": "draw an arrow that points at ink you name by stroke id; "
                       "geometry is computed for you — the precise way to point at "
                       "or link existing ink, never estimate arrow coordinates "
                       "with add_stroke",
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
    context = _ink_context(canvas)
    prompt = _codex_cli_prompt(canvas, instruction, context=context)
    context_json = json.dumps(context, separators=(",", ":"))
    preview = {
        "mode": "codex-cli",
        "image": {
            "format": "png",
            "transport": "codex exec --image",
            "bytes": len(_page_raster(canvas)),
        },
        "context": context,
        "context_chars": len(context_json),
        "prompt_chars": len(prompt),
        "prompt_preview": _prompt_preview(prompt),
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
) -> str:
    page = canvas.page
    ask = instruction or "Answer the question written on this page, in ink."
    context = context or _ink_context(canvas)
    return f"""\
{SYSTEM}

You are running through Codex CLI as a JSON planner for the Neeh demo. You
cannot call tools directly. Inspect the attached page image, choose the Neeh
tool actions that should be applied, and return only JSON matching the provided
output schema.

Current ink context:
{json.dumps(context, separators=(",", ":"))}{_context_note(context)}{_focus_note(canvas)}

Available Neeh action tools:
{json.dumps(_codex_cli_tool_contract(), separators=(",", ":"))}

Rules:
- Use at most {MAX_PLANNED_ACTIONS} actions.
- The output schema uses one shared input object; set unrelated fields to null.
- Use write_text only for genuinely new answer content, in color {AGENT_INK}.
- Agent text uses the "handwritten" style so it looks written rather than typeset.
- Make the SMALLEST edit that answers. When correcting the user's writing,
  mark it up in place instead of rewriting it: insert_text adds missing
  characters next to ink you name by stroke id, mark strikes/circles/
  underlines/checks it — both compute geometry for you, no coordinates
  needed. E.g. missing quotes -> insert_text " with position "before" and
  "after" on the word's stroke ids; never transcribe their text again.
- For ANY correction of existing writing, NEVER use write_text to reproduce a
  corrected copy elsewhere. Use in-place insert_text and mark actions, even if
  the markup is imperfect. insert_text automatically makes collision-free room;
  do not call move for insertion spacing.
- Use highlight only when it helps connect your answer to existing ink.
- To point at existing ink, use connect with the target's stroke ids (add
  source_stroke_ids to start the arrow from other ink). Use add_stroke only
  for new freestanding shapes that reference nothing on the page.
- Coordinates are page units. The page is {page.width:g} x {page.height:g}.
- Do not edit files, run commands, mention implementation details, or ask a
  follow-up question.

User instruction: {ask}
"""


def _codex_cli_command(codex: str, tmp: Path, schema_path: Path, output_path: Path, image_path: Path) -> list[str]:
    cmd = [
        codex,
        "exec",
        "--ephemeral",
        "--skip-git-repo-check",
        "-C",
        str(tmp),
        "--sandbox",
        "read-only",
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(output_path),
        "--image",
        str(image_path),
    ]
    if model := os.getenv("NEEH_CODEX_CLI_MODEL"):
        cmd.extend(["--model", model])
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
        schema_path = tmp / "response.schema.json"
        output_path = tmp / "response.json"
        image_path.write_bytes(_page_raster(canvas))
        schema_path.write_text(json.dumps(_CODEX_CLI_RESPONSE_SCHEMA), encoding="utf-8")

        try:
            completed = subprocess.run(
                _codex_cli_command(codex, tmp, schema_path, output_path, image_path),
                input=_codex_cli_prompt(canvas, instruction),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ModelUnavailableError(f"codex exec timed out after {timeout:g}s") from exc

        if completed.returncode != 0:
            raise ModelUnavailableError(_codex_cli_error(completed))
        raw = output_path.read_text(encoding="utf-8") if output_path.exists() else completed.stdout
        payload = _cli_result_payload(raw)

    planned = payload.get("actions") or []
    if not isinstance(planned, list):
        planned = []
    actions = _apply_planned_actions(canvas, planned, on_action)
    failures = [action for action in actions if "error" in action]
    successful = [action for action in actions if "error" not in action]
    if failures and not successful:
        reply = "I could not write the planned answer on the page."
    else:
        reply = str(payload.get("reply") or "Codex planned an ink response.")
    return {
        "reply": reply,
        "actions": actions,
        "model": os.getenv("NEEH_CODEX_CLI_MODEL", "default-profile"),
        "raw_model_output": raw,
    }


def _claude_cli_prompt(canvas: Canvas, instruction: Optional[str], *, page_path: Path) -> str:
    page = canvas.page
    ask = instruction or "Answer the question written on this page, in ink."
    context = _ink_context(canvas)
    return f"""\
{SYSTEM}

You are running through Claude CLI as a JSON planner for the Neeh demo. Keep
Claude's default coding-agent behavior, but when you inspect the page image use
Read on the file at {page_path}. Choose the Neeh tool actions that should be
applied, and return only JSON matching the provided output schema.

Current ink context:
{json.dumps(context, separators=(",", ":"))}{_context_note(context)}{_focus_note(canvas)}

Available Neeh action tools:
{json.dumps(_codex_cli_tool_contract(), separators=(",", ":"))}

Rules:
- Use at most {MAX_PLANNED_ACTIONS} actions.
- The output schema uses one shared input object; set unrelated fields to null.
- Use write_text only for genuinely new answer content, in color {AGENT_INK}.
- Agent text uses the "handwritten" style so it looks written rather than typeset.
- Make the SMALLEST edit that answers. When correcting the user's writing,
  mark it up in place instead of rewriting it: insert_text adds missing
  characters next to ink you name by stroke id, mark strikes/circles/
  underlines/checks it — both compute geometry for you, no coordinates
  needed. E.g. missing quotes -> insert_text " with position "before" and
  "after" on the word's stroke ids; never transcribe their text again.
- For ANY correction of existing writing, NEVER use write_text to reproduce a
  corrected copy elsewhere. Use in-place insert_text and mark actions, even if
  the markup is imperfect. insert_text automatically makes collision-free room;
  do not call move for insertion spacing.
- Use highlight only when it helps connect your answer to existing ink.
- To point at existing ink, use connect with the target's stroke ids (add
  source_stroke_ids to start the arrow from other ink). Use add_stroke only
  for new freestanding shapes that reference nothing on the page.
- Coordinates are page units. The page is {page.width:g} x {page.height:g}.
- The page PNG to inspect is at: {page_path}
- Do not edit files, run commands, mention implementation details, or ask a
  follow-up question.

User instruction: {ask}
"""


def _claude_cli_command(claude: str, tmp: Path, prompt: str) -> list[str]:
    cmd = [claude, "-p"]
    if model := os.getenv("NEEH_CLAUDE_CLI_MODEL"):
        cmd.extend(["--model", model])
    cmd.extend([
        prompt,
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(_CODEX_CLI_RESPONSE_SCHEMA),
        "--append-system-prompt",
        SYSTEM,
        "--tools",
        "Read",
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
        page_path.write_bytes(_page_raster(canvas))

        prompt = _claude_cli_prompt(canvas, instruction, page_path=page_path)

        try:
            completed = subprocess.run(
                _claude_cli_command(claude, tmp, prompt),
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ModelUnavailableError(f"claude -p timed out after {timeout:g}s") from exc

        if completed.returncode != 0:
            raise ModelUnavailableError(_claude_cli_error(completed))
        raw = completed.stdout
        payload = _cli_result_payload(raw)

    planned = payload.get("actions") or []
    if not isinstance(planned, list):
        planned = []
    return {
        "reply": str(payload.get("reply") or "Claude planned an ink response."),
        "actions": _apply_planned_actions(canvas, planned, on_action),
        "model": os.getenv("NEEH_CLAUDE_CLI_MODEL", "default-profile"),
        "raw_model_output": raw,
    }


def run_mock(
    canvas: Canvas,
    instruction: Optional[str] = None,
    on_action: Optional[OnAction] = None,
) -> dict[str, Any]:
    """Keyless stand-in: same tool surface, canned behavior. Highlights the
    user's ink and writes a placeholder answer below it."""
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
    return {"reply": "Mock reply: highlighted your ink and wrote a note below it.",
            "actions": actions}
