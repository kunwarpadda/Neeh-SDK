"""T5 action-grounding execution and scoring (protocol §4).

The model's answer must be a JSON tool call. It is executed through the real
`neeh-tools/v1` surface on a copy of the document, then scored on what
actually happened:

- erase     — set F1 between the ids the tool actually erased and the truth.
- highlight — 1.0 if the requested region overlaps the target (IoU >= 0.5)
              and touches no foreign element's bbox, else 0.0.

A reply that fails to parse or execute scores 0.0 — an agent that cannot form
a valid call has not grounded the action.
"""
from __future__ import annotations

import json
import re
from typing import Any

from neeh.canvas import Canvas
from neeh.document import Document, Page
from neeh.ink import BoundingBox
from neeh.tools import call_tool

from research.harness.scorers import score_set_f1

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _parse_call(answer: str) -> tuple[str, dict[str, Any]]:
    match = _JSON_OBJECT.search(answer)
    if not match:
        raise ValueError("no JSON object in answer")
    payload = json.loads(match.group(0))
    tool = payload.get("tool")
    tool_input = payload.get("input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        raise ValueError("answer JSON must have 'tool' and 'input'")
    return tool, tool_input


def _fresh_canvas(page: Page) -> Canvas:
    document = Document(
        title="t5-exec", id="doc_t5exec", created_at_ms=1_700_000_000_000,
        pages=[Page.from_dict(page.to_dict())],
    )
    return Canvas(document)


def _iou(a: BoundingBox, b: BoundingBox) -> float:
    if not a.intersects(b):
        return 0.0
    inter_w = min(a.max_x, b.max_x) - max(a.min_x, b.min_x)
    inter_h = min(a.max_y, b.max_y) - max(a.min_y, b.min_y)
    intersection = inter_w * inter_h
    union = a.width * a.height + b.width * b.height - intersection
    return intersection / union if union > 0 else 0.0


def score_action(answer: str, truth: dict[str, Any], page: Page) -> float:
    try:
        tool, tool_input = _parse_call(answer)
    except (ValueError, json.JSONDecodeError):
        return 0.0

    if truth["type"] == "erase":
        if tool != "erase":
            return 0.0
        try:
            result = call_tool(_fresh_canvas(page), "erase", tool_input)
        except Exception:
            return 0.0
        return score_set_f1(" ".join(result.get("erased", [])), truth["stroke_ids"])

    if truth["type"] == "highlight":
        if tool != "highlight":
            return 0.0
        try:
            region = BoundingBox.from_list(tool_input["region"])
            call_tool(_fresh_canvas(page), "highlight", tool_input)
        except Exception:
            return 0.0
        if _iou(region, BoundingBox.from_list(truth["target_bbox"])) < 0.5:
            return 0.0
        for foreign in truth["foreign_bboxes"]:
            if region.intersects(BoundingBox.from_list(foreign)):
                return 0.0
        return 1.0

    raise ValueError(f"unknown action type {truth['type']!r}")
