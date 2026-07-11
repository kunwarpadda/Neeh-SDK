"""The demo agent loop: user ink -> page PNG -> model -> tool calls -> answer ink.

This is the whole thesis in one file: the page is rendered so a multimodal
model can SEE it, the Neeh tool manifest (`tool_schemas()`) is passed to the
model API, and the model answers by writing ink through the same
tool surface a human app would use.

`run_codex_cli` uses the user's Codex CLI login. `run_codex_api` uses the
OpenAI Responses API with OPENAI_API_KEY. `run_claude` uses the Claude API
with ANTHROPIC_API_KEY or an `ant auth login` profile. `run_mock` exercises
the identical Neeh tool path with canned calls for keyless demos and tests.
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from neeh.canvas import Canvas
from neeh.context import build_ink_context, build_ink_context_v1
from neeh.rendering.png import render_page_png
from neeh.tools import call_tool, tool_schemas

CLAUDE_MODEL = "claude-opus-4-8"
OPENAI_CODEX_MODEL = "gpt-5.3-codex"
AGENT_INK = "#1d4ed8"  # agent ink is blue; user ink defaults to near-black
MAX_TURNS = 12
MAX_CONTEXT_STROKES = int(os.getenv("NEEH_CONTEXT_MAX_STROKES", "80"))
MAX_CONTEXT_POINTS = int(os.getenv("NEEH_CONTEXT_MAX_POINTS", "12"))
# "v1" = ink-context/v1 (compact SVG geometry, ~9x fewer context chars — see
# research/results/m1-findings.md); "pull" = v1 gist only (bboxes, no
# geometry) plus the fetch_ink_region tool for on-demand detail (the H7
# foveated protocol — needs a tool-loop agent, i.e. --agent claude or
# codex-api); "v0" = the original Phase 0 payload.
CONTEXT_VERSION = os.getenv("NEEH_CONTEXT_VERSION", "v1")
PROMPT_PREVIEW_CHARS = int(os.getenv("NEEH_PROMPT_PREVIEW_CHARS", "5000"))

SYSTEM = """\
You are Neeh, an ink assistant who lives on a shared handwriting page. The user
writes or sketches a question in ink; you answer IN INK on the same page.

You see the page as an image. Coordinates are page units, (0,0) at the top-left,
x growing right and y growing down. The first message states the page size.

How to answer:
- Read the user's handwriting or drawing from the image.
- Write your answer with write_text in an empty region near the question
  (usually below it). Choose region [min_x, min_y, max_x, max_y] so it does not
  overlap existing ink; leave a little margin.
- Use add_stroke for arrows, shapes, and diagrams; use highlight to emphasize
  part of the user's ink. Write in {agent_ink} so your ink is visibly yours.
- Keep written answers short: a sentence or two, or one worked step. This is a
  notebook page, not a chat window.
- After writing, call view_page with format "png" to check placement and
  legibility. If your ink overlaps something, undo and place it again.

When you are done, reply with one sentence summarizing what you wrote.
""".format(agent_ink=AGENT_INK)

OnAction = Callable[[str, dict[str, Any]], None]

_CODEX_CLI_TOOL_NAMES = {"add_stroke", "highlight", "write_text"}
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
        "style": {"type": ["string", "null"], "enum": ["print", "user_font", None]},
        "size": {"type": ["number", "null"]},
    },
    "required": ["points", "region", "text", "color", "width", "brush", "style", "size"],
}
_CODEX_CLI_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "reply": {"type": "string"},
        "actions": {
            "type": "array",
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


def _page_png_data_url(canvas: Canvas) -> str:
    return "data:image/png;base64," + base64.b64encode(render_page_png(canvas.page)).decode("ascii")


def _page_image_block(canvas: Canvas) -> dict[str, Any]:
    png = render_page_png(canvas.page)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(png).decode("ascii"),
        },
    }


def _tool_result_content(result: dict[str, Any]) -> Any:
    """Views return base64 PNGs — hand those back as image blocks so the
    model actually sees them; everything else goes back as JSON text."""
    if result.get("format") == "png":
        meta = {k: v for k, v in result.items() if k != "data"}
        return [
            {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                         "data": result["data"]}},
            {"type": "text", "text": json.dumps(meta)},
        ]
    return json.dumps(result)


def _ink_context(canvas: Canvas) -> dict[str, Any]:
    if CONTEXT_VERSION == "v0":
        return build_ink_context(
            canvas,
            max_strokes=MAX_CONTEXT_STROKES,
            max_points_per_stroke=MAX_CONTEXT_POINTS,
        )
    payload = build_ink_context_v1(
        canvas, max_strokes=MAX_CONTEXT_STROKES, raster="attached_image",
        stroke_bboxes=(CONTEXT_VERSION == "pull"),
    )
    if CONTEXT_VERSION == "pull":
        # H7 foveated protocol: ship the index (page-unit bboxes), let the
        # agent pull geometry through the fetch_ink_region tool.
        payload["ink"]["svg"] = (
            "(geometry omitted — call fetch_ink_region with a page-unit "
            "region to get compact SVG paths with stable stroke ids)"
        )
    return payload


def _context_note(context: dict[str, Any]) -> str:
    """v1 payloads carry grid coordinates; tool calls must stay in page units.

    Stated explicitly because the M2 sweep showed models answering regions in
    grid units when a raster is attached (results/m2-findings.md)."""
    if "ink" not in context:
        return ""
    grid_w, grid_h = context["ink"]["grid"]
    scale = context["page"]["width"] / grid_w
    return (
        f"\nCoordinate note: ink.svg path coordinates are on a {grid_w}x{grid_h} "
        f"grid; multiply by {scale:.3f} to convert to page units. Every tool-call "
        f"coordinate (regions, points) MUST be in page units, never grid units."
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
    )


def _codex_cli_tool_contract() -> list[dict[str, Any]]:
    return [
        {
            "name": "write_text",
            "purpose": "write short answer text as agent ink",
            "required": {"text": "string", "region": "[min_x,min_y,max_x,max_y]"},
            "optional": {"color": f"hex, prefer {AGENT_INK}", "style": "print|user_font", "size": "number"},
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
    ]


def _prompt_preview(prompt: str) -> dict[str, Any]:
    truncated = len(prompt) > PROMPT_PREVIEW_CHARS
    text = prompt[:PROMPT_PREVIEW_CHARS]
    if truncated:
        text += f"\n\n... truncated; append ?full=1 to /agent-input for all {len(prompt)} chars ..."
    return {"text": text, "chars": len(prompt), "truncated": truncated}


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
            "bytes": len(render_page_png(canvas.page)),
        },
        "context": context,
        "context_chars": len(context_json),
        "prompt_chars": len(prompt),
        "prompt_preview": _prompt_preview(prompt),
        "tools": _codex_cli_tool_contract(),
        "output_schema": "JSON object with reply plus up to three write_text/highlight/add_stroke actions",
        "raw_prompt_available": True,
    }
    if full:
        preview["prompt"] = prompt
        preview["tool_schemas"] = _codex_cli_tool_schemas()
    return preview


def _openai_tool_schemas() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": schema["name"],
            "description": schema["description"],
            "parameters": schema["input_schema"],
            "strict": False,
        }
        for schema in tool_schemas()
    ]


def _codex_cli_tool_schemas() -> list[dict[str, Any]]:
    return [schema for schema in tool_schemas() if schema["name"] in _CODEX_CLI_TOOL_NAMES]


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
{json.dumps(context, separators=(",", ":"))}{_context_note(context)}

Available Neeh action tools:
{json.dumps(_codex_cli_tool_contract(), separators=(",", ":"))}

Rules:
- Use at most three actions.
- The output schema uses one shared input object; set unrelated fields to null.
- Prefer write_text for the answer, in color {AGENT_INK}.
- Put the answer in an empty region near the user's ink, usually below it.
- Use highlight only when it helps connect your answer to existing ink.
- Use add_stroke for arrows, marks, or simple diagram strokes.
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
    for item in planned[:3]:
        if not isinstance(item, dict):
            continue
        name = item.get("tool")
        arguments = item.get("input") or {}
        if name not in _CODEX_CLI_TOOL_NAMES or not isinstance(arguments, dict):
            continue
        arguments = {key: value for key, value in arguments.items() if value is not None}
        try:
            call_tool(canvas, name, arguments)
        except Exception as exc:
            actions.append({"tool": name, "input": arguments, "error": str(exc)})
            continue
        actions.append({"tool": name, "input": arguments})
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
        image_path.write_bytes(render_page_png(canvas.page))
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
        payload = _json_object_from_text(raw)

    planned = payload.get("actions") or []
    if not isinstance(planned, list):
        planned = []
    return {
        "reply": str(payload.get("reply") or "Codex planned an ink response."),
        "actions": _apply_planned_actions(canvas, planned, on_action),
        "model": os.getenv("NEEH_CODEX_CLI_MODEL", "default-profile"),
    }


def _openai_tool_result_content(result: dict[str, Any]) -> str:
    if result.get("format") == "png":
        meta = {k: v for k, v in result.items() if k != "data"}
        meta["image"] = "attached as input_image in the next message"
        return json.dumps(meta)
    return json.dumps(result)


def _openai_image_followup(result: dict[str, Any]) -> Optional[dict[str, Any]]:
    if result.get("format") != "png":
        return None
    return {
        "role": "user",
        "content": [
            {"type": "input_text", "text": "Rendered page image returned by the last view tool call."},
            {"type": "input_image", "image_url": f"data:image/png;base64,{result['data']}", "detail": "high"},
        ],
    }


def run_codex_api(
    canvas: Canvas,
    instruction: Optional[str] = None,
    on_action: Optional[OnAction] = None,
) -> dict[str, Any]:
    """Run one ask-the-page turn against OpenAI's Codex model.

    Returns {"reply": str, "actions": [{"tool", "input"}...], "model": str}.
    """
    from openai import OpenAI

    client = OpenAI()
    model = os.getenv("NEEH_OPENAI_MODEL", OPENAI_CODEX_MODEL)
    page = canvas.page
    ask = instruction or "Answer the question written on this page, in ink."
    input_list: list[Any] = [
        {
            "role": "user",
            "content": [
                {"type": "input_text", "text": (
                    f"This is the current page ({page.width:g} x {page.height:g} "
                    f"page units). {ask}\n\n{_ink_context_text(canvas)}"
                )},
                {"type": "input_image", "image_url": _page_png_data_url(canvas), "detail": "high"},
            ],
        }
    ]

    actions: list[dict[str, Any]] = []
    reply = ""
    tools = _openai_tool_schemas()
    request: dict[str, Any] = {
        "model": model,
        "instructions": SYSTEM,
        "tools": tools,
    }
    if effort := os.getenv("NEEH_OPENAI_REASONING_EFFORT"):
        request["reasoning"] = {"effort": effort}

    for _ in range(MAX_TURNS):
        response = client.responses.create(input=input_list, **request)
        reply = getattr(response, "output_text", "") or reply
        input_list += response.output

        tool_uses = [item for item in response.output if getattr(item, "type", None) == "function_call"]
        if not tool_uses:
            break

        image_followups: list[dict[str, Any]] = []
        for item in tool_uses:
            arguments = json.loads(item.arguments or "{}")
            try:
                result = call_tool(canvas, item.name, arguments)
            except Exception as exc:
                input_list.append({
                    "type": "function_call_output",
                    "call_id": item.call_id,
                    "output": json.dumps({"error": str(exc)}),
                })
                continue

            actions.append({"tool": item.name, "input": arguments})
            if on_action:
                on_action(item.name, arguments)
            input_list.append({
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": _openai_tool_result_content(result),
            })
            if followup := _openai_image_followup(result):
                image_followups.append(followup)
        input_list += image_followups

    return {"reply": reply, "actions": actions, "model": model}


def run_claude(
    canvas: Canvas,
    instruction: Optional[str] = None,
    on_action: Optional[OnAction] = None,
) -> dict[str, Any]:
    """Run one ask-the-page turn against the Claude API.

    Returns {"reply": str, "actions": [{"tool", "input"}...]}.
    """
    import anthropic

    client = anthropic.Anthropic()
    page = canvas.page
    ask = instruction or "Answer the question written on this page, in ink."
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                _page_image_block(canvas),
                {
                    "type": "text",
                    "text": f"This is the current page ({page.width:g} x {page.height:g} "
                    f"page units). {ask}\n\n{_ink_context_text(canvas)}",
                },
            ],
        }
    ]

    actions: list[dict[str, Any]] = []
    reply = ""
    for _ in range(MAX_TURNS):
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=16000,
            thinking={"type": "adaptive"},
            system=SYSTEM,
            tools=tool_schemas(),
            messages=messages,
        )
        if response.stop_reason == "refusal":
            return {"reply": "The model declined this request.", "actions": actions}

        reply = "".join(b.text for b in response.content if b.type == "text") or reply
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            break

        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in tool_uses:
            arguments = dict(block.input or {})
            try:
                result = call_tool(canvas, block.name, arguments)
            except Exception as exc:
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": f"Error: {exc}",
                    "is_error": True,
                })
                continue
            actions.append({"tool": block.name, "input": arguments})
            if on_action:
                on_action(block.name, arguments)
            results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": _tool_result_content(result),
            })
        messages.append({"role": "user", "content": results})

    return {"reply": reply, "actions": actions}


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
    })
    return {"reply": "Mock reply: highlighted your ink and wrote a note below it.",
            "actions": actions}
