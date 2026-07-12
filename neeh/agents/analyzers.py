"""Deterministic, bounded reducers for common ink questions.

These analyzers keep mechanical work out of the language-model context. They
turn a large page into the exact evidence needed for common temporal and
geometric questions before IAI spends model tokens.
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from neeh.canvas import Canvas
from neeh.ink import BoundingBox
from neeh.agents.timeline import build_ink_timeline, stroke_analysis_record

ANALYSIS_VERSION = "ink-analysis/v1"
ANALYSIS_OPERATIONS = (
    "latest_mark",
    "creation_order",
    "stroke_dynamics",
    "cross_out_candidates",
)


def _records(canvas: Canvas) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    strokes = [
        stroke
        for layer in canvas.page.layers if layer.visible
        for stroke in layer.strokes
    ]
    records = {stroke.id: stroke_analysis_record(stroke) for stroke in strokes}
    page_order = {stroke.id: index for index, stroke in enumerate(strokes)}
    return records, page_order


def _center(record: dict[str, Any]) -> list[float]:
    x, y = BoundingBox.from_list(record["bbox"]).center
    return [round(x, 2), round(y, 2)]


def _compact(record: dict[str, Any], canvas: Canvas) -> dict[str, Any]:
    center = _center(record)
    return {
        "id": record["id"],
        "start_ms": record["start_ms"],
        "end_ms": record["end_ms"],
        "center": center,
        "bbox": record["bbox"],
        "vertical_half": "upper" if center[1] < canvas.page.height / 2 else "lower",
        "horizontal_half": "left" if center[0] < canvas.page.width / 2 else "right",
        "direction": record["direction"],
        "duration_ms": record["duration_ms"],
        "pressure": record["pressure"],
    }


def analyze_ink(
    canvas: Canvas,
    operation: str,
    *,
    stroke_ids: Optional[Sequence[str]] = None,
    region: Optional[Sequence[float]] = None,
    limit: int = 16,
) -> dict[str, Any]:
    """Run one exact reducer and return bounded, model-ready evidence."""
    if operation not in ANALYSIS_OPERATIONS:
        raise ValueError(f"unknown ink analysis operation {operation!r}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 24:
        raise ValueError("limit must be an integer between 1 and 24")
    query_box = BoundingBox.from_list(region) if region is not None else None
    records, page_order = _records(canvas)
    requested = list(dict.fromkeys(stroke_ids or []))
    unknown = [stroke_id for stroke_id in requested if stroke_id not in records]
    if unknown:
        raise ValueError(f"unknown visible stroke ids: {unknown}")
    candidates = list(records.values())
    if requested:
        wanted = set(requested)
        candidates = [record for record in candidates if record["id"] in wanted]
    if query_box is not None:
        candidates = [
            record for record in candidates
            if query_box.intersects(BoundingBox.from_list(record["bbox"]))
        ]
    envelope: dict[str, Any] = {
        "schema": ANALYSIS_VERSION,
        "operation": operation,
        "deterministic": True,
        "source_stroke_count": len(records),
        "matched_stroke_count": len(candidates),
    }

    if operation == "latest_mark":
        if not candidates:
            return {**envelope, "latest": None}
        latest = max(
            candidates,
            key=lambda record: (
                record["end_ms"],
                record["start_ms"],
                page_order.get(record["id"], -1),
            ),
        )
        return {**envelope, "latest": _compact(latest, canvas)}

    if operation == "creation_order":
        if not requested:
            raise ValueError("creation_order requires stroke_ids")
        ordered = sorted(
            candidates,
            key=lambda record: (
                record["start_ms"],
                record["end_ms"],
                page_order.get(record["id"], -1),
            ),
        )[:limit]
        return {
            **envelope,
            "order": [
                {
                    "rank": rank,
                    "id": record["id"],
                    "start_ms": record["start_ms"],
                    "end_ms": record["end_ms"],
                }
                for rank, record in enumerate(ordered, 1)
            ],
            "truncated": len(candidates) > len(ordered),
        }

    if operation == "stroke_dynamics":
        if not requested:
            raise ValueError("stroke_dynamics requires stroke_ids")
        selected = sorted(candidates, key=lambda record: page_order[record["id"]])[:limit]
        return {
            **envelope,
            "strokes": [_compact(record, canvas) for record in selected],
            "truncated": len(candidates) > len(selected),
        }

    timeline = build_ink_timeline(canvas.page)
    all_moments = [
        moment for moment in timeline["moments"]
        if "cross_out_candidate" in moment["event_types"]
        and (
            query_box is None
            or query_box.intersects(BoundingBox.from_list(moment["bbox"]))
        )
    ]
    moments = all_moments[:limit]
    return {
        **envelope,
        "candidates": [
            {
                "moment_id": moment["id"],
                "start_ms": moment["start_ms"],
                "bbox": moment["bbox"],
                "stroke_ids": moment["stroke_ids"],
                "affected_prior_ids": moment["affected_prior_ids"],
            }
            for moment in moments
        ],
        "truncated": len(all_moments) > len(moments),
        "history_complete": timeline["history_complete"],
    }


__all__ = ["ANALYSIS_OPERATIONS", "ANALYSIS_VERSION", "analyze_ink"]
