"""Ink Agent Interface: budgeted page map plus typed perception actions.

This is the ink equivalent of a coding agent's repository map and file-view
tools. The bootstrap observation stays compact; a model can then retrieve
region or stroke detail through a deliberately small read-only action surface.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from neeh.canvas import Canvas
from neeh.context import build_ink_index
from neeh.ink import Author, BoundingBox
from neeh.rendering import render_page_ascii
from neeh.semantics import build_semantics
from neeh.tools import call_tool
from neeh.agents.timeline import (
    build_ink_timeline,
    find_ink_moments,
    inspect_ink_moment,
)
from neeh.agents.analyzers import ANALYSIS_OPERATIONS, analyze_ink
from neeh.agents.reducers import REDUCER_TASKS, reduce_ink

IAI_VERSION = "ink-agent-interface/v1"
PERCEPTION_POLICIES = (
    "raster-only", "raster-always", "index-only", "active-index", "marked-index",
)


@dataclass(frozen=True)
class PerceptionBudget:
    """Hard limits for one perception workspace/trajectory."""

    max_marks: int = 24
    max_bootstrap_chars: int = 6000
    max_actions: int = 4
    max_observation_chars: int = 12000
    max_raster_pixels: int = 1_500_000
    max_recent_strokes: int = 16
    max_moments: int = 8
    max_replay_steps: int = 16

    def __post_init__(self) -> None:
        for name, value in self.__dict__.items():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer")

    def to_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


def _visible_strokes(canvas: Canvas):
    return [
        stroke
        for layer in canvas.page.layers
        if layer.visible
        for stroke in layer.strokes
    ]


def _compact_relations(canvas: Canvas) -> list[dict[str, Any]]:
    items = build_semantics(canvas.page)
    clusters = {
        item["id"]: {
            "region": item.get("region"),
            "stroke_count": len(item.get("stroke_ids") or []),
        }
        for item in items
        if item.get("kind") == "cluster"
    }
    return [
        {
            "id": item["id"],
            "from": item["edges"]["from"],
            "to": item["edges"]["to"],
            "region": item.get("region"),
            "confidence": item.get("confidence"),
            "from_summary": clusters.get(item["edges"]["from"]),
            "to_summary": clusters.get(item["edges"]["to"]),
        }
        for item in items
        if item.get("kind") == "link" and item.get("edges")
    ]


def _rank_marks(canvas: Canvas, task: str, marks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words = {word.strip(".,:;!?()[]{}\"'").lower() for word in task.split()}
    strokes = _visible_strokes(canvas)
    order = {stroke.id: i for i, stroke in enumerate(strokes)}
    author = {stroke.id: stroke.author for stroke in strokes}
    selected = set(canvas.selection.stroke_ids)
    semantics = build_semantics(canvas.page)
    clusters = {
        item["id"]: set(item.get("stroke_ids") or [])
        for item in semantics if item.get("kind") == "cluster"
    }
    related_strokes: set[str] = set()
    for item in semantics:
        if item.get("kind") != "link":
            continue
        related_strokes.update(item.get("stroke_ids") or [])
        for cluster_id in (item.get("edges") or {}).values():
            related_strokes.update(clusters.get(cluster_id, set()))
    denominator = max(len(strokes) - 1, 1)

    def score(mark: dict[str, Any]) -> tuple[float, int]:
        labels = {mark["shape"].lower(), *mark["position"].lower().split("-")}
        relevance = 8.0 * len(words & labels)
        relevance += 4.0 if mark["id"] in selected else 0.0
        relevance += 3.0 if mark["id"] in related_strokes else 0.0
        relevance += 2.0 * order.get(mark["id"], 0) / denominator
        relevance += 1.0 if author.get(mark["id"]) is Author.USER else -1.0
        return relevance, order.get(mark["id"], -1)

    ranked = sorted(marks, key=score, reverse=True)
    return [{**mark, "rank": i + 1} for i, mark in enumerate(ranked)]


def _recent_delta(canvas: Canvas, limit: int) -> dict[str, Any]:
    strokes = _visible_strokes(canvas)
    agent_times = [s.created_at_ms for s in strokes if s.author is Author.AGENT]
    cutoff = max(agent_times) if agent_times else None
    all_recent = [
        s for s in strokes
        if s.author is Author.USER and (cutoff is None or s.created_at_ms > cutoff)
    ]
    recent = all_recent[-limit:]
    return {
        "since_ms": cutoff,
        "stroke_count": len(recent),
        "truncated": len(all_recent) > len(recent),
        "strokes": [
            {
                "id": stroke.id,
                "bbox": stroke.bbox.to_list(),
                "created_at_ms": stroke.created_at_ms,
            }
            for stroke in recent
        ],
    }


def _task_analysis(canvas: Canvas, task: str) -> Optional[dict[str, Any]]:
    """Route a natural-language task to the exact analyzer/reducer that answers it.

    Explicit intent routing keeps mechanical questions off the model: the
    matching reducer is pre-computed into the workspace so the answer is already
    bounded evidence, not a search the model has to perform. Order matters ---
    more specific intents are checked before more general ones.
    """
    normalized = " ".join(task.casefold().split())

    def has(*phrases: str) -> bool:
        return any(phrase in normalized for phrase in phrases)

    if has("crossed out", "cross-out", "cross out", "struck through", "scratched out"):
        return analyze_ink(canvas, "cross_out_candidates", limit=4)
    # Change-flavored recency must outrank the bare "most recent" intent below:
    # "which stroke was changed most recently" asks about modification history
    # (moves, erases, restyles -- the event log), not drawing time, and
    # "changed most recently" contains the substring "most recent", so checking
    # latest_mark first silently rewrites the question into the wrong one.
    if has("changed", "change", "modified", "edited", "what changed",
           "new since", "just added"):
        return reduce_ink(canvas, "recent_changes", limit=6)
    if has("erased", "erase", "rubbed out"):
        return reduce_ink(canvas, "revisions", limit=6)
    if has("revis", "overwrit", "corrected", "replaced", "rewrote", "rewritten"):
        return reduce_ink(canvas, "revisions", limit=6)
    if has("most recent", "latest", "last drawn", "last mark", "newest"):
        return analyze_ink(canvas, "latest_mark")
    if has("recently", "recent change"):
        return reduce_ink(canvas, "recent_changes", limit=6)
    if has("summar", "overview", "what is on the page", "describe the page"):
        return reduce_ink(canvas, "page_summary")
    if has("orientation", "rotated", "tilted", "slanted", "sideways",
           "at an angle", "upside down", "which way"):
        return analyze_ink(canvas, "orientation")
    if has("connector", "connect", "arrow", "links to", "linking", "joins"):
        return analyze_ink(canvas, "connector_candidates", limit=6)
    if has("group", "cluster"):
        # Recorded membership is an exact fact; only guess spatially when the
        # log has no groups to report.
        if canvas.groups():
            return analyze_ink(canvas, "recorded_groups", limit=6)
        return analyze_ink(canvas, "grouping_candidates", limit=6)
    return None


def build_observation_workspace(
    canvas: Canvas,
    task: Optional[str] = None,
    *,
    policy: str = "active-index",
    budget: Optional[PerceptionBudget] = None,
) -> dict[str, Any]:
    """Build the budgeted, stable bootstrap observation for an ink agent."""
    if policy not in PERCEPTION_POLICIES:
        raise ValueError(f"unknown perception policy {policy!r}")
    budget = budget or PerceptionBudget()
    task_text = task or "Answer the question written on this page, in ink."
    index = build_ink_index(canvas)
    ranked = _rank_marks(canvas, task_text, index["marks"])
    relations = _compact_relations(canvas)
    # Recorded group membership is exact page state (folded from the event
    # log), so it rides in the static page map for every policy -- without it,
    # a recorded group is invisible in every evidence channel and a model can
    # only guess membership from spatial proximity.
    recorded_groups = [
        {
            "group_id": group_id,
            "label": group.get("label"),
            "member_ids": list(group.get("member_ids", []))[:24],
            "member_ids_truncated": len(group.get("member_ids", [])) > 24,
            "size": len(group.get("member_ids", [])),
        }
        for group_id, group in sorted(canvas.groups().items())
    ][:12]
    timeline = build_ink_timeline(canvas.page, event_log=canvas.events)
    task_analysis = (
        _task_analysis(canvas, task_text)
        if policy in {"active-index", "marked-index"}
        else None
    )
    keep = min(len(ranked), budget.max_marks)
    relation_keep = len(relations)
    moment_keep = min(timeline["moment_count"], budget.max_moments)

    def payload(mark_count: int, relation_count: int, moment_count: int) -> dict[str, Any]:
        marks = ranked[:mark_count]
        marked_view = None
        if policy == "marked-index" and marks:
            alphabet = "123456789abcdefghijklmnopqrstuvwxyz"
            legend: dict[str, str] = {}
            positions: dict[str, tuple[float, float]] = {}
            for label, mark in zip(alphabet, marks):
                x0, y0, x1, y1 = mark["bbox"]
                legend[label] = mark["id"]
                positions[label] = ((x0 + x1) / 2, (y0 + y1) / 2)
            marked_view = {
                "format": "ascii-set-of-marks",
                "data": render_page_ascii(canvas.page, marks=positions),
                "legend": legend,
            }
        timeline_map = None
        if policy in {"active-index", "marked-index"}:
            timeline_map = {
                key: value for key, value in timeline.items() if key != "moments"
            }
            timeline_map.update({
                "moments": [
                    {key: value for key, value in moment.items() if key != "strokes"}
                    for moment in timeline["moments"][-moment_count:]
                ] if moment_count else [],
                "included_moment_count": moment_count,
                "omitted_moment_count": timeline["moment_count"] - moment_count,
            })
        return {
            "schema": IAI_VERSION,
            "policy": policy,
            "task": task_text,
            "page_map": {
                **{key: value for key, value in index.items() if key != "marks"},
                "marks": marks,
                "included_mark_count": len(marks),
                "omitted_mark_count": len(ranked) - len(marks),
                "relations": relations[:relation_count],
                "included_relation_count": relation_count,
                "omitted_relation_count": len(relations) - relation_count,
                "groups": recorded_groups,
                "group_count": len(recorded_groups),
                "marked_view": marked_view,
            },
            "recent_delta": _recent_delta(canvas, budget.max_recent_strokes),
            "analysis": task_analysis,
            "timeline_map": timeline_map,
            "working_set": {"regions": [], "stroke_ids": [], "moment_ids": []},
            "budget": budget.to_dict(),
            "capabilities": [
                "find_marks", "analyze_ink", "reduce_ink", "find_ink_moments",
                "inspect_ink_moment", "view_region", "get_ink", "expand_relations",
            ] if policy in {"active-index", "marked-index"} else [],
            "bootstrap_chars": 0,
        }

    workspace = payload(keep, relation_keep, moment_keep)
    while True:
        # Two passes settle the small length change caused by writing the count.
        workspace["bootstrap_chars"] = len(json.dumps(workspace, separators=(",", ":")))
        workspace["bootstrap_chars"] = len(json.dumps(workspace, separators=(",", ":")))
        if workspace["bootstrap_chars"] <= budget.max_bootstrap_chars:
            break
        if moment_keep:
            moment_keep -= 1
        elif relation_keep:
            relation_keep -= 1
        elif keep:
            keep -= 1
        else:
            raise ValueError("minimal observation workspace exceeds max_bootstrap_chars")
        workspace = payload(keep, relation_keep, moment_keep)
    return workspace


IAI_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "find_marks",
        "description": "Search the ranked ink page map by id, shape, or position.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 24},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "analyze_ink",
        "description": "Run a deterministic bounded reducer before asking the model to search raw ink.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "operation": {"type": "string", "enum": list(ANALYSIS_OPERATIONS)},
                "stroke_ids": {"type": "array", "items": {"type": "string"}, "maxItems": 24},
                "region": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "limit": {"type": "integer", "minimum": 1, "maximum": 24},
            },
            "required": ["operation"],
            "additionalProperties": False,
        },
    },
    {
        "name": "reduce_ink",
        "description": "Compose analyzers into a task-shaped answer (recent changes, revisions, page summary).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "enum": list(REDUCER_TASKS)},
                "region": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "since_ms": {"type": "integer", "minimum": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 24},
            },
            "required": ["task"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_ink_moments",
        "description": "Find query-relevant creation episodes using temporal evidence, coverage, and novelty.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "region": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "object_ids": {"type": "array", "items": {"type": "string"}},
                "limit": {"type": "integer", "minimum": 1, "maximum": 24},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "inspect_ink_moment",
        "description": "Inspect one creation episode as before, after, current, diff, or ordered replay evidence.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "moment_id": {"type": "string"},
                "view": {"type": "string", "enum": ["before", "after", "current", "diff", "replay"]},
            },
            "required": ["moment_id", "view"],
            "additionalProperties": False,
        },
    },
    {
        "name": "view_region",
        "description": "Inspect one page-space region as raster or ASCII gestalt.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "region": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "modality": {"type": "string", "enum": ["raster", "ascii"]},
            },
            "required": ["region", "modality"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_ink",
        "description": "Retrieve addressable stroke bboxes or paths by ids or page-space region.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "stroke_ids": {"type": "array", "items": {"type": "string"}},
                "region": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
                "detail": {"type": "string", "enum": ["bboxes", "paths"]},
            },
            "required": ["detail"],
            "additionalProperties": False,
        },
    },
    {
        "name": "expand_relations",
        "description": "Return recognized clusters and links touching a stroke or semantic id.",
        "inputSchema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
            "additionalProperties": False,
        },
    },
]


class InkAgentInterface:
    """Stateful, budget-enforcing read-only perception surface."""

    def __init__(
        self,
        canvas: Canvas,
        task: Optional[str] = None,
        *,
        policy: str = "active-index",
        budget: Optional[PerceptionBudget] = None,
    ) -> None:
        self.canvas = canvas
        self.task = task or "Answer the question written on this page, in ink."
        self.policy = policy
        self.budget = budget or PerceptionBudget()
        self._workspace = build_observation_workspace(
            canvas, self.task, policy=policy, budget=self.budget
        )
        full_index = build_ink_index(canvas)
        self._all_marks = _rank_marks(canvas, self.task, full_index["marks"])
        self._timeline = build_ink_timeline(canvas.page, event_log=canvas.events)
        self._actions = 0
        self._observation_chars = 0
        self._raster_pixels = 0
        self._action_types: list[str] = []
        self._moment_queries = 0
        self._analyzer_queries = 0
        self._replay_steps = 0

    def workspace(self) -> dict[str, Any]:
        return self._workspace

    def telemetry(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "bootstrap_chars": self._workspace.get("bootstrap_chars", 0),
            "perception_actions": self._actions,
            "action_types": list(self._action_types),
            "observation_chars": self._observation_chars,
            "raster_pixels": self._raster_pixels,
            "moment_queries": self._moment_queries,
            "analyzer_queries": self._analyzer_queries,
            "replay_steps": self._replay_steps,
            "working_set": {
                "moment_count": len(self._workspace["working_set"]["moment_ids"]),
                "stroke_count": len(self._workspace["working_set"]["stroke_ids"]),
                "region_count": len(self._workspace["working_set"]["regions"]),
            },
            "budget": self.budget.to_dict(),
        }

    def _begin(self, name: str) -> None:
        if self.policy not in {"active-index", "marked-index"}:
            raise ValueError(f"policy {self.policy!r} does not allow perception actions")
        if self._actions >= self.budget.max_actions:
            raise ValueError("perception action budget exhausted")
        self._actions += 1
        self._action_types.append(name)

    def _finish(self, value: dict[str, Any], *, raster_pixels: int = 0) -> dict[str, Any]:
        text_value = (
            {key: val for key, val in value.items() if key != "data"}
            if value.get("format") == "png" else value
        )
        chars = len(json.dumps(text_value, separators=(",", ":")))
        if self._observation_chars + chars > self.budget.max_observation_chars:
            raise ValueError("perception observation character budget exceeded")
        if self._raster_pixels + raster_pixels > self.budget.max_raster_pixels:
            raise ValueError("perception raster pixel budget exceeded")
        self._observation_chars += chars
        self._raster_pixels += raster_pixels
        return value

    def call(self, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        arguments = arguments or {}
        if name not in {schema["name"] for schema in IAI_TOOL_SCHEMAS}:
            raise ValueError(f"unknown IAI perception action {name!r}")
        self._begin(name)
        return getattr(self, name)(**arguments)

    def find_marks(self, query: str, limit: int = 8) -> dict[str, Any]:
        if not isinstance(query, str):
            raise ValueError("query must be a string")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 24:
            raise ValueError("limit must be an integer between 1 and 24")
        terms = [term.lower() for term in query.split() if term]
        # Keep the strict lexical filter (only matching marks are returned), but
        # rank the matches by analyzer signals rather than page order: matches on
        # a mark's structured shape/position labels outrank incidental substring
        # hits, and the analyzer-derived page-map rank breaks ties.
        matched = [
            mark for mark in self._all_marks
            if all(term in json.dumps(mark).lower() for term in terms)
        ]

        def relevance(mark: dict[str, Any]) -> tuple[int, int, int]:
            labels = {mark["shape"].lower(), *mark["position"].lower().split("-")}
            label_hits = sum(1 for term in terms if any(term in label for label in labels))
            blob = json.dumps(mark).lower()
            blob_hits = sum(1 for term in terms if term in blob)
            return (label_hits, blob_hits, -mark["rank"])

        matched.sort(key=relevance, reverse=True)
        matched = matched[:limit]
        return self._finish({"query": query, "marks": matched, "match_count": len(matched)})

    def analyze_ink(
        self,
        operation: str,
        stroke_ids: Optional[Sequence[str]] = None,
        region: Optional[Sequence[float]] = None,
        limit: int = 16,
    ) -> dict[str, Any]:
        self._analyzer_queries += 1
        return self._finish(analyze_ink(
            self.canvas,
            operation,
            stroke_ids=stroke_ids,
            region=region,
            limit=limit,
        ))

    def reduce_ink(
        self,
        task: str,
        region: Optional[Sequence[float]] = None,
        since_ms: Optional[int] = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        self._analyzer_queries += 1
        return self._finish(reduce_ink(
            self.canvas,
            task,
            region=region,
            since_ms=since_ms,
            limit=limit,
        ))

    def _promote_moments(self, moments: Sequence[dict[str, Any]]) -> None:
        working = self._workspace["working_set"]
        for moment in moments:
            if (
                moment["id"] not in working["moment_ids"]
                and len(working["moment_ids"]) >= self.budget.max_moments
            ):
                continue
            if moment["id"] not in working["moment_ids"]:
                working["moment_ids"].append(moment["id"])
            for stroke_id in moment["stroke_ids"]:
                if stroke_id not in working["stroke_ids"]:
                    working["stroke_ids"].append(stroke_id)
            if moment["bbox"] not in working["regions"]:
                working["regions"].append(moment["bbox"])

    def find_ink_moments(
        self,
        query: str,
        region: Optional[Sequence[float]] = None,
        object_ids: Optional[Sequence[str]] = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        limit = min(limit, self.budget.max_moments)
        if limit < 1:
            raise ValueError("ink moment result budget exhausted")
        moments = find_ink_moments(
            self._timeline,
            query,
            region=region,
            object_ids=object_ids,
            limit=limit,
        )
        self._moment_queries += 1
        result = self._finish({"query": query, "moments": moments, "match_count": len(moments)})
        self._promote_moments(moments)
        return result

    def inspect_ink_moment(self, moment_id: str, view: str) -> dict[str, Any]:
        remaining_replay = self.budget.max_replay_steps - self._replay_steps
        if view == "replay" and remaining_replay < 1:
            raise ValueError("perception replay-step budget exhausted")
        result = inspect_ink_moment(
            self.canvas.page,
            self._timeline,
            moment_id,
            view=view,
            max_replay_steps=remaining_replay if view == "replay" else self.budget.max_replay_steps,
        )
        moment = next(item for item in self._timeline["moments"] if item["id"] == moment_id)
        finished = self._finish(result)
        if view == "replay":
            self._replay_steps += len(result.get("steps") or [])
        self._promote_moments([moment])
        return finished

    def view_region(self, region: Sequence[float], modality: str) -> dict[str, Any]:
        if modality == "raster":
            box = BoundingBox(*[float(value) for value in region])
            requested_pixels = round(box.width * box.height)
            # Check the budget BEFORE rendering: raster_pixels was previously
            # only checked on the already-rendered result, so an oversized
            # single request paid the full render cost before being rejected.
            if self._raster_pixels + requested_pixels > self.budget.max_raster_pixels:
                raise ValueError("perception raster pixel budget exceeded")
            result = call_tool(self.canvas, "view_region", {"region": region, "format": "png"})
            return self._finish(result, raster_pixels=requested_pixels)
        if modality == "ascii":
            if len(region) != 4:
                raise ValueError("region must contain four page-space numbers")
            box = BoundingBox(*[float(value) for value in region])
            result = {
                "format": "ascii",
                "page_id": self.canvas.page.id,
                "region": box.to_list(),
                "data": render_page_ascii(self.canvas.page, region=box),
            }
            return self._finish(result)
        raise ValueError("modality must be 'raster' or 'ascii'")

    def get_ink(
        self,
        detail: str,
        stroke_ids: Optional[Sequence[str]] = None,
        region: Optional[Sequence[float]] = None,
    ) -> dict[str, Any]:
        if (stroke_ids is None) == (region is None):
            raise ValueError("get_ink needs exactly one of stroke_ids or region")
        if detail not in {"bboxes", "paths"}:
            raise ValueError("detail must be 'bboxes' or 'paths'")
        if region is not None and detail == "paths":
            return self._finish(call_tool(self.canvas, "fetch_ink_region", {"region": region}))
        arguments: dict[str, Any] = {"include_points": detail == "paths"}
        if stroke_ids is not None:
            arguments["stroke_ids"] = list(stroke_ids)
        else:
            arguments["region"] = list(region or [])
        return self._finish(call_tool(self.canvas, "get_strokes", arguments))

    def expand_relations(self, id: str) -> dict[str, Any]:
        if not isinstance(id, str) or not id:
            raise ValueError("id must be a non-empty string")
        items = build_semantics(self.canvas.page)
        semantic_ids = {
            item["id"] for item in items
            if id == item["id"] or id in (item.get("stroke_ids") or [])
        }
        changed = True
        while changed:
            changed = False
            for item in items:
                edges = set((item.get("edges") or {}).values())
                if item["id"] in semantic_ids or edges & semantic_ids:
                    before = len(semantic_ids)
                    semantic_ids.add(item["id"])
                    semantic_ids.update(edges)
                    changed = changed or len(semantic_ids) != before
        related = [item for item in items if item["id"] in semantic_ids]
        return self._finish({"id": id, "relations": related, "relation_count": len(related)})


__all__ = [
    "IAI_TOOL_SCHEMAS",
    "IAI_VERSION",
    "PERCEPTION_POLICIES",
    "InkAgentInterface",
    "PerceptionBudget",
    "build_observation_workspace",
]
