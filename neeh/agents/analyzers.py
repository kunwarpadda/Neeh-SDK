"""Deterministic, bounded reducers for common ink questions.

These analyzers keep mechanical work out of the language-model context. They
turn a large page into the exact evidence needed for common temporal and
geometric questions before IAI spends model tokens.

Two kinds of claim are returned and are kept explicitly distinct:

* **measurements** (``claim_type="measurement"``) are exact geometric or
  temporal facts read straight off the document -- containment, endpoint
  coordinates, true path crossings, chronological order. They are ground truth.
* **inferences** (``claim_type="inference"``) are recognizer-style hypotheses
  -- cross-out, connector, and grouping candidates. Every inferred item carries
  a ``confidence`` in ``[0, 1]`` and a ``provenance`` block naming the exact
  measurements it was derived from. They are never asserted as user intent.
"""
from __future__ import annotations

import math
from typing import Any, Optional, Sequence

from neeh.canvas import Canvas
from neeh.ink import BoundingBox, Stroke
from neeh.agents.timeline import build_ink_timeline, stroke_analysis_record

ANALYSIS_VERSION = "ink-analysis/v1"

# Exact facts read off the document; ground truth.
_MEASUREMENT_OPERATIONS = (
    "latest_mark",
    "creation_order",
    "stroke_dynamics",
    "containment",
    "intersection",
    "endpoints",
    "spatial_collision",
)
# Recognizer hypotheses; carry confidence and provenance, never asserted.
_INFERENCE_OPERATIONS = (
    "cross_out_candidates",
    "connector_candidates",
    "grouping_candidates",
)
ANALYSIS_OPERATIONS = _MEASUREMENT_OPERATIONS + _INFERENCE_OPERATIONS
_INFERENCE_SET = frozenset(_INFERENCE_OPERATIONS)


def _records(
    canvas: Canvas,
) -> tuple[dict[str, dict[str, Any]], dict[str, int], dict[str, Stroke]]:
    strokes = [
        stroke
        for layer in canvas.page.layers if layer.visible
        for stroke in layer.strokes
    ]
    records = {stroke.id: stroke_analysis_record(stroke) for stroke in strokes}
    page_order = {stroke.id: index for index, stroke in enumerate(strokes)}
    strokes_by_id = {stroke.id: stroke for stroke in strokes}
    return records, page_order, strokes_by_id


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


# --- exact geometry helpers -------------------------------------------------

def _endpoints(stroke: Stroke) -> tuple[list[float], list[float]]:
    first, last = stroke.points[0], stroke.points[-1]
    return [round(first.x, 2), round(first.y, 2)], [round(last.x, 2), round(last.y, 2)]


def _segment_intersection(
    p1: tuple[float, float], p2: tuple[float, float],
    p3: tuple[float, float], p4: tuple[float, float],
) -> Optional[tuple[float, float]]:
    """Exact crossing point of segments p1p2 and p3p4, or None."""
    (x1, y1), (x2, y2), (x3, y3), (x4, y4) = p1, p2, p3, p4
    denom = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if denom == 0:  # parallel or collinear; collinear overlap is not reported
        return None
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / denom
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / denom
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))
    return None


def _polyline_crossing(a: Stroke, b: Stroke) -> Optional[list[float]]:
    """First exact crossing point between two stroke polylines, or None."""
    a_pts = [(p.x, p.y) for p in a.points]
    b_pts = [(p.x, p.y) for p in b.points]
    for i in range(len(a_pts) - 1):
        for j in range(len(b_pts) - 1):
            hit = _segment_intersection(a_pts[i], a_pts[i + 1], b_pts[j], b_pts[j + 1])
            if hit is not None:
                return [round(hit[0], 2), round(hit[1], 2)]
    return None


def _point_to_polyline_distance(x: float, y: float, stroke: Stroke) -> float:
    pts = [(p.x, p.y) for p in stroke.points]
    if len(pts) == 1:
        return math.hypot(x - pts[0][0], y - pts[0][1])
    best = math.inf
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq == 0.0:
            dist = math.hypot(x - ax, y - ay)
        else:
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length_sq))
            dist = math.hypot(x - (ax + t * dx), y - (ay + t * dy))
        best = min(best, dist)
    return best


def _proximity_margin(canvas: Canvas, fraction: float) -> float:
    return round(fraction * min(canvas.page.width, canvas.page.height), 2)


# --- dispatch ---------------------------------------------------------------

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
    records, page_order, strokes_by_id = _records(canvas)
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
        "claim_type": "inference" if operation in _INFERENCE_SET else "measurement",
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

    if operation == "endpoints":
        if not requested:
            raise ValueError("endpoints requires stroke_ids")
        selected = sorted(candidates, key=lambda record: page_order[record["id"]])[:limit]
        height, width = canvas.page.height, canvas.page.width
        strokes_out = []
        for record in selected:
            start, end = _endpoints(strokes_by_id[record["id"]])
            strokes_out.append({
                "id": record["id"],
                "start": start,
                "end": end,
                "start_half": {
                    "vertical": "upper" if start[1] < height / 2 else "lower",
                    "horizontal": "left" if start[0] < width / 2 else "right",
                },
                "end_half": {
                    "vertical": "upper" if end[1] < height / 2 else "lower",
                    "horizontal": "left" if end[0] < width / 2 else "right",
                },
                "displacement": round(math.hypot(end[0] - start[0], end[1] - start[1]), 2),
                "direction": record["direction"],
            })
        return {
            **envelope,
            "strokes": strokes_out,
            "truncated": len(candidates) > len(selected),
        }

    if operation == "containment":
        if query_box is None:
            raise ValueError("containment requires a region")
        contained, partial = [], []
        for record in candidates:
            box = BoundingBox.from_list(record["bbox"])
            target = contained if query_box.contains_box(box) else partial
            target.append({"id": record["id"], "bbox": record["bbox"]})
        return {
            **envelope,
            "region": query_box.to_list(),
            "contained": contained[:limit],
            "partial": partial[:limit],
            "truncated": max(len(contained), len(partial)) > limit,
        }

    if operation == "spatial_collision":
        boxes = [(record["id"], BoundingBox.from_list(record["bbox"])) for record in candidates]
        collisions = []
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                (a_id, a_box), (b_id, b_box) = boxes[i], boxes[j]
                if a_box.intersects(b_box):
                    collisions.append({
                        "a": a_id,
                        "b": b_id,
                        "overlap": [
                            round(max(a_box.min_x, b_box.min_x), 2),
                            round(max(a_box.min_y, b_box.min_y), 2),
                            round(min(a_box.max_x, b_box.max_x), 2),
                            round(min(a_box.max_y, b_box.max_y), 2),
                        ],
                    })
        return {
            **envelope,
            "collisions": collisions[:limit],
            "pair_count": len(collisions),
            "truncated": len(collisions) > limit,
        }

    if operation == "intersection":
        ids = [record["id"] for record in candidates]
        crossings = []
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a, b = strokes_by_id[ids[i]], strokes_by_id[ids[j]]
                if not a.bbox.intersects(b.bbox):
                    continue  # exact crossing impossible without bbox overlap
                point = _polyline_crossing(a, b)
                if point is not None:
                    crossings.append({"a": ids[i], "b": ids[j], "at": point})
        return {
            **envelope,
            "intersections": crossings[:limit],
            "pair_count": len(crossings),
            "truncated": len(crossings) > limit,
        }

    if operation == "connector_candidates":
        margin = _proximity_margin(canvas, 0.04)
        others = [strokes_by_id[record["id"]] for record in candidates]
        found = []
        for record in candidates:
            stroke = strokes_by_id[record["id"]]
            start, end = _endpoints(stroke)
            pool = [other for other in others if other.id != stroke.id]
            from_id, from_gap = _nearest_stroke(start, pool)
            to_id, to_gap = _nearest_stroke(end, pool)
            if (
                from_id is not None and to_id is not None
                and from_id != to_id
                and from_gap <= margin and to_gap <= margin
            ):
                confidence = round(max(0.0, 1.0 - (from_gap + to_gap) / (2 * margin)), 3)
                found.append({
                    "id": stroke.id,
                    "from_id": from_id,
                    "to_id": to_id,
                    "confidence": confidence,
                    "provenance": {
                        "start_gap": round(from_gap, 2),
                        "end_gap": round(to_gap, 2),
                        "margin": margin,
                        "measured_from": "endpoint-to-polyline distance",
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

    if operation == "grouping_candidates":
        margin = _proximity_margin(canvas, 0.05)
        groups = _spatial_groups(candidates, margin)
        groups_out = []
        for members in groups:
            union = BoundingBox.union_all(
                BoundingBox.from_list(record["bbox"]) for record in members
            )
            groups_out.append({
                "member_ids": [record["id"] for record in members[:limit]],
                "size": len(members),
                "bbox": [round(v, 2) for v in union.to_list()],
                "confidence": _group_confidence(members, margin),
                "provenance": {"margin": margin, "measured_from": "bbox proximity"},
            })
        groups_out.sort(key=lambda group: group["size"], reverse=True)
        return {
            **envelope,
            "groups": groups_out[:limit],
            "group_count": len(groups_out),
            "margin": margin,
            "truncated": len(groups_out) > limit,
        }

    if operation == "cross_out_candidates":
        event_log = getattr(getattr(canvas, "history", None), "log", None)
        timeline = build_ink_timeline(canvas.page, event_log=event_log)
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
                    "confidence": _cross_out_confidence(moment),
                    "provenance": {
                        "measured_from": "later open stroke overlapping earlier ink",
                        "affected_count": len(moment["affected_prior_ids"]),
                    },
                }
                for moment in moments
            ],
            "truncated": len(all_moments) > len(moments),
            "history_complete": timeline["history_complete"],
        }

    raise ValueError(f"unhandled ink analysis operation {operation!r}")  # defensive


def _nearest_stroke(
    point: Sequence[float], pool: Sequence[Stroke]
) -> tuple[Optional[str], float]:
    best_id, best_gap = None, math.inf
    for stroke in pool:
        gap = _point_to_polyline_distance(point[0], point[1], stroke)
        if gap < best_gap:
            best_id, best_gap = stroke.id, gap
    return best_id, best_gap


def _spatial_groups(
    records: Sequence[dict[str, Any]], margin: float
) -> list[list[dict[str, Any]]]:
    """Connected components of records whose bboxes are within ``margin``."""
    boxes = [
        (record, BoundingBox.from_list(record["bbox"]).expanded(margin / 2))
        for record in records
    ]
    parent = list(range(len(boxes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if boxes[i][1].intersects(boxes[j][1]):
                parent[find(i)] = find(j)

    clusters: dict[int, list[dict[str, Any]]] = {}
    for index, (record, _) in enumerate(boxes):
        clusters.setdefault(find(index), []).append(record)
    return [members for members in clusters.values() if len(members) > 1]


def _group_confidence(members: Sequence[dict[str, Any]], margin: float) -> float:
    if margin <= 0 or len(members) < 2:
        return 1.0
    boxes = [BoundingBox.from_list(record["bbox"]) for record in members]
    gaps = []
    for i, a in enumerate(boxes):
        ax, ay = a.center
        nearest = min(
            math.hypot(ax - b.center[0], ay - b.center[1])
            for j, b in enumerate(boxes) if j != i
        )
        gaps.append(nearest)
    avg_gap = sum(gaps) / len(gaps)
    return round(max(0.0, min(1.0, 1.0 - avg_gap / (4 * margin))), 3)


def _cross_out_confidence(moment: dict[str, Any]) -> float:
    affected = len(moment["affected_prior_ids"])
    if affected == 0:
        return 0.2
    return round(min(0.9, 0.5 + 0.2 * affected), 3)


__all__ = ["ANALYSIS_OPERATIONS", "ANALYSIS_VERSION", "analyze_ink"]
