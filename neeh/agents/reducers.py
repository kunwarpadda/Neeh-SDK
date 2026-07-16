"""Task-specific ink reducers composed from the primitive analyzers.

Where :mod:`neeh.agents.analyzers` answers primitive geometric and temporal
questions, this module composes those primitives into the higher-level,
task-shaped answers an assistant actually asks for -- "what changed recently?",
"was anything revised?", "summarise this page". Each reducer returns bounded,
model-ready evidence and, like the analyzers, tags every result as an exact
``measurement`` or a recognizer ``inference`` (with confidence and provenance).
"""
from __future__ import annotations

from typing import Any, Optional, Sequence

from neeh.canvas import Canvas
from neeh.ink import BoundingBox
from neeh.agents.analyzers import (
    ANALYSIS_VERSION,
    _content_margin,
    _endpoints,
    _point_to_polyline_distance,
    _records,
    analyze_ink,
)

REDUCER_TASKS = (
    "recent_changes",
    "overwritten_ink",
    "revisions",
    "ambiguous_connectors",
    "page_summary",
)
_INFERENCE_TASKS = frozenset(
    {"overwritten_ink", "revisions", "ambiguous_connectors"}
)


def _box_area(box: BoundingBox) -> float:
    return box.width * box.height


def _filtered_records(
    canvas: Canvas, region: Optional[Sequence[float]]
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, Any]]:
    records, page_order, strokes_by_id = _records(canvas)
    query_box = BoundingBox.from_list(region) if region is not None else None
    values = list(records.values())
    if query_box is not None:
        values = [
            record for record in values
            if query_box.intersects(BoundingBox.from_list(record["bbox"]))
        ]
    return values, page_order, strokes_by_id


def reduce_ink(
    canvas: Canvas,
    task: str,
    *,
    region: Optional[Sequence[float]] = None,
    since_ms: Optional[int] = None,
    limit: int = 8,
) -> dict[str, Any]:
    """Run one task-specific reducer and return bounded, model-ready evidence."""
    if task not in REDUCER_TASKS:
        raise ValueError(f"unknown ink reducer task {task!r}")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 24:
        raise ValueError("limit must be an integer between 1 and 24")
    if since_ms is not None and (isinstance(since_ms, bool) or not isinstance(since_ms, int)):
        raise ValueError("since_ms must be an integer epoch or None")

    records, page_order, strokes_by_id = _filtered_records(canvas, region)
    envelope: dict[str, Any] = {
        "schema": ANALYSIS_VERSION,
        "task": task,
        "deterministic": True,
        "claim_type": "inference" if task in _INFERENCE_TASKS else "measurement",
        "source_stroke_count": len(strokes_by_id),
        "matched_stroke_count": len(records),
    }

    if task == "recent_changes":
        return _recent_changes(envelope, canvas, records, region, since_ms, limit)
    if task == "overwritten_ink":
        return _overwritten_ink(envelope, records, limit)
    if task == "revisions":
        return _revisions(envelope, canvas, records, region, limit)
    if task == "ambiguous_connectors":
        return _ambiguous_connectors(envelope, canvas, records, strokes_by_id, limit)
    return _page_summary(envelope, canvas, records, region)


# Event kinds that change a stroke's state. Group membership and page
# lifecycle are relations, not stroke changes, so they are excluded here.
_CHANGE_EVENT_KINDS = frozenset(("add", "erase", "move", "restyle", "undo", "redo", "agent"))


def _log_change_entries(
    canvas: Canvas, region: Optional[Sequence[float]]
) -> list[dict[str, Any]]:
    """The last event-log change per stroke on the current page, newest first.

    Reading the log (not stroke geometry) is what makes a *move* or an *erase*
    count as the most recent change: a moved stroke keeps its original
    created_at/point times, and an erased stroke is no longer on the page at
    all, so both are invisible to a created-at sort over live strokes.
    """
    page_id = canvas.page.id
    box = None if region is None else BoundingBox.from_list([float(v) for v in region])
    latest: dict[str, dict[str, Any]] = {}
    for event in canvas.events.events:
        if event.page_id != page_id or event.kind not in _CHANGE_EVENT_KINDS:
            continue
        for _layer_id, stroke in event.removed + event.added:
            if box is not None and not box.intersects(stroke.bbox):
                continue
            latest[stroke.id] = {
                "id": stroke.id,
                "changed_ms": event.at_ms,
                "change": event.kind,
                "seq": event.seq,
                "bbox": stroke.bbox,
            }
    if not latest:
        return []
    live = {s.id for layer in canvas.page.layers for s in layer.strokes}
    entries = sorted(latest.values(), key=lambda e: (e["changed_ms"], e["seq"]), reverse=True)
    for entry in entries:
        entry["visible"] = entry["id"] in live
    return entries


def _recent_changes(
    envelope: dict[str, Any],
    canvas: Canvas,
    records: list[dict[str, Any]],
    region: Optional[Sequence[float]],
    since_ms: Optional[int],
    limit: int,
) -> dict[str, Any]:
    entries = _log_change_entries(canvas, region)
    if entries:
        considered = (
            entries if since_ms is None
            else [e for e in entries if e["changed_ms"] >= since_ms]
        )
        latest_ms = considered[0]["changed_ms"] if considered else None
        top = considered[:limit]
        changes = []
        for entry in top:
            cx, cy = entry["bbox"].center
            changes.append({
                "id": entry["id"],
                "changed_ms": entry["changed_ms"],
                # The log's sequence number is the authoritative total order:
                # wall-clock changed_ms can tie (batch edits, ms resolution),
                # and without seq a consumer has no evidence that the first
                # entry really is the newest change rather than a tie.
                "seq": entry["seq"],
                "change": entry["change"],
                "visible": entry["visible"],
                "ms_since_latest": (
                    latest_ms - entry["changed_ms"] if latest_ms is not None else None
                ),
                "center": [round(cx, 2), round(cy, 2)],
                "bbox": [round(v, 2) for v in entry["bbox"].to_list()],
            })
        return {
            **envelope,
            "latest_ms": latest_ms,
            "since_ms": since_ms,
            "measured_from": "event log",
            "order": "newest change first, by event-log sequence (seq breaks changed_ms ties)",
            "changes": changes,
            "truncated": len(considered) > len(top),
        }

    # No event log (e.g. strokes added straight onto layers): fall back to the
    # geometric view -- most recently *ended* strokes, newest first.
    considered = records
    if since_ms is not None:
        considered = [record for record in records if record["end_ms"] >= since_ms]
    ordered = sorted(considered, key=lambda record: record["end_ms"], reverse=True)
    latest_ms = ordered[0]["end_ms"] if ordered else None
    top = ordered[:limit]
    changes = []
    for record in top:
        box = BoundingBox.from_list(record["bbox"])
        cx, cy = box.center
        changes.append({
            "id": record["id"],
            "end_ms": record["end_ms"],
            "ms_since_latest": latest_ms - record["end_ms"] if latest_ms is not None else None,
            "center": [round(cx, 2), round(cy, 2)],
            "bbox": record["bbox"],
            "direction": record["direction"],
        })
    return {
        **envelope,
        "latest_ms": latest_ms,
        "since_ms": since_ms,
        "measured_from": "stroke end times",
        "changes": changes,
        "truncated": len(considered) > len(top),
    }


def _overwrite_pairs(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Later strokes whose bbox overlaps an earlier stroke's bbox."""
    boxes = [(record, BoundingBox.from_list(record["bbox"])) for record in records]
    pairs = []
    for later_record, later_box in boxes:
        for earlier_record, earlier_box in boxes:
            if later_record["id"] == earlier_record["id"]:
                continue
            if earlier_record["end_ms"] >= later_record["end_ms"]:
                continue  # not strictly earlier
            if not later_box.intersects(earlier_box):
                continue
            overlap = BoundingBox(
                max(later_box.min_x, earlier_box.min_x),
                max(later_box.min_y, earlier_box.min_y),
                min(later_box.max_x, earlier_box.max_x),
                min(later_box.max_y, earlier_box.max_y),
            )
            denom = min(_box_area(later_box), _box_area(earlier_box))
            coverage = _box_area(overlap) / denom if denom > 0 else 1.0
            pairs.append({
                "later_id": later_record["id"],
                "earlier_id": earlier_record["id"],
                "overlap": [round(v, 2) for v in overlap.to_list()],
                "coverage": round(min(1.0, coverage), 3),
                "time_gap_ms": later_record["end_ms"] - earlier_record["end_ms"],
            })
    pairs.sort(key=lambda item: item["coverage"], reverse=True)
    return pairs


def _overwritten_ink(
    envelope: dict[str, Any], records: list[dict[str, Any]], limit: int
) -> dict[str, Any]:
    pairs = _overwrite_pairs(records)
    candidates = []
    for pair in pairs[:limit]:
        candidates.append({
            "later_id": pair["later_id"],
            "earlier_id": pair["earlier_id"],
            "confidence": round(min(0.95, 0.4 + 0.55 * pair["coverage"]), 3),
            "provenance": {
                "overlap": pair["overlap"],
                "coverage": pair["coverage"],
                "time_gap_ms": pair["time_gap_ms"],
                "measured_from": "later stroke bbox overlapping earlier stroke bbox",
            },
        })
    return {
        **envelope,
        "candidates": candidates,
        "candidate_count": len(pairs),
        "truncated": len(pairs) > limit,
    }


def _log_revisions(
    canvas: Canvas,
    records: list[dict[str, Any]],
    region: Optional[Sequence[float]],
) -> list[dict[str, Any]]:
    """Erase and erase-then-rewrite revisions read straight off the event log.

    These are exact history facts (confidence 1.0), so they rank above the
    geometric overwrite/cross-out inferences: an erase followed by fresh ink
    written near the erased stroke's location is the strongest revision
    evidence a page can carry, and it is exactly the case a final-page
    geometric view can never see -- the erased stroke is gone.
    """
    page_id = canvas.page.id
    box = None if region is None else BoundingBox.from_list([float(v) for v in region])
    events = list(canvas.events.events)
    live = {s.id for layer in canvas.page.layers for s in layer.strokes}
    margin = _content_margin(records, 0.04) if records else 0.0
    entries: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if event.page_id != page_id or event.kind != "erase":
            continue
        for _layer_id, erased in event.removed:
            if box is not None and not box.intersects(erased.bbox):
                continue
            search = erased.bbox.expanded(margin)
            rewrite_ids: list[str] = []
            rewrite_event_id = None
            for later in events[index + 1:]:
                if later.page_id != page_id or later.kind != "add":
                    continue
                near = [
                    stroke.id for _l, stroke in later.added
                    if stroke.id != erased.id and stroke.bbox.intersects(search)
                ]
                if near:
                    rewrite_ids = near
                    rewrite_event_id = later.event_id
                    break
            provenance = {
                "event_id": event.event_id,
                "at_ms": event.at_ms,
                "measured_from": "event log erase",
            }
            if rewrite_event_id is not None:
                provenance["rewrite_event_id"] = rewrite_event_id
            entries.append({
                "kind": "erase_rewrite" if rewrite_ids else "erase",
                "by_ids": rewrite_ids,
                "target_ids": [erased.id],
                "target_visible": erased.id in live,
                "confidence": 1.0,
                "provenance": provenance,
            })
    return entries


def _revisions(
    envelope: dict[str, Any],
    canvas: Canvas,
    records: list[dict[str, Any]],
    region: Optional[Sequence[float]],
    limit: int,
) -> dict[str, Any]:
    revisions: list[dict[str, Any]] = list(_log_revisions(canvas, records, region))
    for pair in _overwrite_pairs(records):
        revisions.append({
            "kind": "overwrite",
            "by_ids": [pair["later_id"]],
            "target_ids": [pair["earlier_id"]],
            "confidence": round(min(0.95, 0.4 + 0.55 * pair["coverage"]), 3),
            "provenance": {
                "coverage": pair["coverage"],
                "time_gap_ms": pair["time_gap_ms"],
                "measured_from": "bbox overwrite",
            },
        })
    cross = analyze_ink(canvas, "cross_out_candidates", region=region, limit=limit)
    for candidate in cross["candidates"]:
        revisions.append({
            "kind": "cross_out",
            "by_ids": candidate["stroke_ids"],
            "target_ids": candidate["affected_prior_ids"],
            "confidence": candidate["confidence"],
            "provenance": {
                "moment_id": candidate["moment_id"],
                "measured_from": candidate["provenance"]["measured_from"],
            },
        })
    revisions.sort(key=lambda item: item["confidence"], reverse=True)
    return {
        **envelope,
        "revisions": revisions[:limit],
        "revision_count": len(revisions),
        "history_complete": cross["history_complete"],
        "truncated": len(revisions) > limit,
    }


def _ambiguous_connectors(
    envelope: dict[str, Any],
    canvas: Canvas,
    records: list[dict[str, Any]],
    strokes_by_id: dict[str, Any],
    limit: int,
) -> dict[str, Any]:
    margin = _content_margin(records, 0.04)
    near_tie = margin * 0.25
    ids = [record["id"] for record in records]
    found = []
    for stroke_id in ids:
        stroke = strokes_by_id[stroke_id]
        start, end = _endpoints(stroke)
        note = {}
        for label, point in (("start", start), ("end", end)):
            gaps = sorted(
                (
                    (_point_to_polyline_distance(point[0], point[1], strokes_by_id[other]), other)
                    for other in ids if other != stroke_id
                ),
                key=lambda item: item[0],
            )
            within = [(gap, other) for gap, other in gaps if gap <= margin]
            if len(within) >= 2 and within[1][0] - within[0][0] <= near_tie:
                note[label] = {
                    "competing_ids": [within[0][1], within[1][1]],
                    "gaps": [round(within[0][0], 2), round(within[1][0], 2)],
                }
        if note:
            confidence = round(min(0.9, 0.5 + 0.2 * len(note)), 3)
            found.append({
                "id": stroke_id,
                "ambiguous_endpoints": note,
                "confidence": confidence,
                "provenance": {
                    "margin": margin,
                    "near_tie_threshold": round(near_tie, 2),
                    "measured_from": "endpoint-to-polyline distance ties",
                },
            })
    found.sort(key=lambda item: item["confidence"], reverse=True)
    return {
        **envelope,
        "candidates": found[:limit],
        "candidate_count": len(found),
        "margin": margin,
        "truncated": len(found) > limit,
    }


def _page_summary(
    envelope: dict[str, Any],
    canvas: Canvas,
    records: list[dict[str, Any]],
    region: Optional[Sequence[float]],
) -> dict[str, Any]:
    if not records:
        return {
            **envelope,
            "stroke_count": 0,
            "author_breakdown": {},
            "time_span_ms": None,
            "page_bbox": None,
            "group_count": 0,
        }
    authors: dict[str, int] = {}
    for record in records:
        authors[record["author"]] = authors.get(record["author"], 0) + 1
    first_ms = min(record["start_ms"] for record in records)
    last_ms = max(record["end_ms"] for record in records)
    page_bbox = BoundingBox.union_all(
        BoundingBox.from_list(record["bbox"]) for record in records
    )
    groups = analyze_ink(canvas, "grouping_candidates", region=region, limit=8)
    recorded = analyze_ink(canvas, "recorded_groups", region=region, limit=8)
    return {
        **envelope,
        "stroke_count": len(records),
        "author_breakdown": authors,
        "first_ms": first_ms,
        "last_ms": last_ms,
        "time_span_ms": last_ms - first_ms,
        "page_bbox": [round(v, 2) for v in page_bbox.to_list()],
        "recorded_group_count": recorded["group_count"],
        "recorded_groups": [
            {
                "group_id": group["group_id"],
                "label": group["label"],
                "member_ids": group["member_ids"],
                "size": group["size"],
            }
            for group in recorded["groups"]
        ],
        "group_count": groups["group_count"],
        "groups": [
            {"member_ids": group["member_ids"], "bbox": group["bbox"], "confidence": group["confidence"]}
            for group in groups["groups"]
        ],
    }


__all__ = ["REDUCER_TASKS", "reduce_ink"]
