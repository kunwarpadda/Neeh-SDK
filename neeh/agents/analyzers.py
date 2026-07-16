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
    "orientation",
    "recorded_groups",
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


def _content_margin(records: Sequence[dict[str, Any]], fraction: float) -> float:
    """Proximity margin scaled to the candidate set's own extent, not the raw
    page/canvas size. A real device page is typically just the tablet's full
    screen resolution, unrelated to how much of it the ink actually occupies,
    so a page-relative margin is far too generous on real captures relative
    to synthetic scenes whose page is sized close to their content. Uses the
    content bbox's diagonal rather than its narrower side, since a scene can
    be legitimately elongated (e.g. two boxes joined by a long, thin
    connector) without that making its objects any closer together."""
    if not records:
        return 0.0
    union = BoundingBox.union_all(BoundingBox.from_list(record["bbox"]) for record in records)
    return round(fraction * math.hypot(union.width, union.height), 2)


def _touch_margin(
    records: Sequence[dict[str, Any]], strokes_by_id: dict[str, Stroke],
    *, factor: float = 3.0, minimum: float = 6.0, maximum: float = 32.0,
) -> float:
    """A small, stroke-scale margin for merging strokes that make up one
    hand-drawn mark (a letter, a box's four sides) rather than distinct
    nearby objects -- independent of page or content size. Real ink is
    routinely several separate strokes per mark with near-zero gaps between
    them; without collapsing those first, single-linkage clustering chains
    through every touching mark on the page regardless of the outer margin."""
    widths = sorted(
        strokes_by_id[record["id"]].style.width
        for record in records if record["id"] in strokes_by_id
    )
    if not widths:
        return minimum
    median = widths[len(widths) // 2]
    return round(min(maximum, max(minimum, factor * median)), 2)


# --- dispatch ---------------------------------------------------------------

# Axis labels are mod-180 (a baseline reads the same at 0 and 180 degrees);
# "rising" is toward the upper-right as seen on screen. The 8-way labels are
# the shared compass vocabulary from ink-timeline stroke direction.
_AXIS_LABELS = ("horizontal", "diagonal-rising", "vertical", "diagonal-falling")
_COMPASS_LABELS = (
    "right", "down-right", "down", "down-left", "left", "up-left", "up", "up-right",
)


def _orientation_of(strokes: Sequence[Stroke]) -> dict[str, Any]:
    """Principal-axis orientation of a stroke set, in the visual frame.

    ``angle_deg`` is the dominant baseline angle in [0, 180): degrees
    counterclockwise from horizontal *as seen on screen* (page y grows down,
    so the visual frame negates dy). ``axis_ratio`` is the major/minor spread
    ratio — higher means more line-like; ``null`` with a non-null angle means
    exactly collinear ink. ``reading_direction`` adds the time-ordered sense
    along the axis using the shared 8-way compass, when the ink's
    chronological travel is large enough to claim one.
    """
    pts = [(p.x, -p.y) for stroke in strokes for p in stroke.points]
    n = len(pts)
    mean_u = sum(u for u, _ in pts) / n
    mean_v = sum(v for _, v in pts) / n
    cuu = sum((u - mean_u) ** 2 for u, _ in pts) / n
    cvv = sum((v - mean_v) ** 2 for _, v in pts) / n
    cuv = sum((u - mean_u) * (v - mean_v) for u, v in pts) / n
    centroid = [round(mean_u, 2), round(-mean_v, 2)]
    trace_half = (cuu + cvv) / 2
    spread = math.hypot((cuu - cvv) / 2, cuv)
    major, minor = trace_half + spread, trace_half - spread
    base = {"stroke_count": len(strokes), "point_count": n, "centroid": centroid}
    if major <= 1e-9:  # a dot: no spatial extent, no orientation
        return {
            "angle_deg": None, "axis": None, "axis_ratio": None,
            "reading_direction": None, **base,
        }
    theta = 0.5 * math.atan2(2 * cuv, cuu - cvv)
    angle = math.degrees(theta) % 180.0
    axis_ratio = round(math.sqrt(major / minor), 2) if minor > 1e-9 else None

    # Chronological travel: stroke centers first-to-last, or a single
    # stroke's own pen travel, projected on the major axis.
    ordered = sorted(strokes, key=lambda s: (s.created_at_ms, s.id))
    if len(ordered) >= 2:
        first_box, last_box = ordered[0].bbox, ordered[-1].bbox
        du = (last_box.min_x + last_box.max_x - first_box.min_x - first_box.max_x) / 2
        dv = -(last_box.min_y + last_box.max_y - first_box.min_y - first_box.max_y) / 2
    else:
        start, end = ordered[0].points[0], ordered[0].points[-1]
        du, dv = end.x - start.x, -(end.y - start.y)
    axis_u, axis_v = math.cos(theta), math.sin(theta)
    travel = du * axis_u + dv * axis_v
    reading = None
    if abs(travel) > 4.0:
        sense_u, sense_v = (axis_u, axis_v) if travel > 0 else (-axis_u, -axis_v)
        # Back to the page frame (dy = -dv) for the shared compass.
        heading = math.atan2(-sense_v, sense_u)
        reading = _COMPASS_LABELS[round(heading / (math.pi / 4)) % 8]
    return {
        "angle_deg": round(angle, 1),
        "axis": _AXIS_LABELS[round(angle / 45.0) % 4],
        "axis_ratio": axis_ratio,
        "reading_direction": reading,
        **base,
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

    if operation == "orientation":
        if not candidates:
            return {**envelope, "orientation": None, "strokes": [], "truncated": False}
        selected = sorted(candidates, key=lambda record: page_order[record["id"]])
        aggregate = _orientation_of([strokes_by_id[r["id"]] for r in selected])
        shown = selected[:limit]
        strokes_out = []
        for record in shown:
            single = _orientation_of([strokes_by_id[record["id"]]])
            strokes_out.append({
                "id": record["id"],
                "angle_deg": single["angle_deg"],
                "axis": single["axis"],
                "direction": record["direction"],
            })
        return {
            **envelope,
            "orientation": aggregate,
            "strokes": strokes_out,
            "truncated": len(selected) > len(shown),
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
        for i, j in _grid_candidate_pairs([box for _, box in boxes], 48.0):
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
        id_boxes = [strokes_by_id[stroke_id].bbox for stroke_id in ids]
        crossings = []
        for i, j in _grid_candidate_pairs(id_boxes, 48.0):
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
        margin = _content_margin(candidates, 0.04)
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

    if operation == "recorded_groups":
        # Exact membership read straight off the event log (canvas.group()/
        # ungroup() relations) -- never a spatial guess. Only groups with at
        # least one member on the current page's candidate set are returned,
        # so multi-page documents do not leak other pages' groups.
        items = []
        matched_members: set[str] = set()
        recorded = canvas.groups()
        for group_id in sorted(recorded):
            group = recorded[group_id]
            member_ids = list(group.get("member_ids", []))
            present = [sid for sid in member_ids if sid in strokes_by_id]
            if not present:
                continue
            matched_members.update(present)
            items.append({
                "group_id": group_id,
                "label": group.get("label"),
                # Membership is the answer, so it is NOT cut at ``limit`` (which
                # bounds the number of groups): a truncated member list reads as
                # complete and silently poisons any answer built from it. The
                # 24-id cap matches the IAI stroke-id array bound, and the flag
                # lets a consumer abstain instead of asserting a partial list.
                "member_ids": member_ids[:24],
                "member_ids_truncated": len(member_ids) > 24,
                "size": len(member_ids),
                "members_on_page": len(present),
                "provenance": {"measured_from": "event log group membership"},
            })
        items.sort(key=lambda item: item["size"], reverse=True)
        return {
            **envelope,
            "matched_stroke_count": len(matched_members),
            "groups": items[:limit],
            "group_count": len(items),
            "truncated": len(items) > limit,
        }

    if operation == "grouping_candidates":
        margin = _content_margin(candidates, 0.05)
        touch = _touch_margin(candidates, strokes_by_id)
        groups = _spatial_groups(candidates, margin, touch_margin=touch)
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


def _grid_candidate_pairs(
    boxes: Sequence[BoundingBox], cell: float
) -> "list[tuple[int, int]]":
    """Sorted candidate pairs (i < j) whose boxes may intersect.

    Buckets every box into the grid cells it covers; only boxes sharing a
    cell are candidates. Exact for detection (two intersecting boxes always
    share at least one cell) while avoiding the O(n^2) all-pairs scan.
    """
    cell = max(cell, 1.0)
    grid: dict[tuple[int, int], list[int]] = {}
    pairs: set[tuple[int, int]] = set()
    for i, box in enumerate(boxes):
        x0, x1 = int(box.min_x // cell), int(box.max_x // cell)
        y0, y1 = int(box.min_y // cell), int(box.max_y // cell)
        for cx in range(x0, x1 + 1):
            for cy in range(y0, y1 + 1):
                bucket = grid.setdefault((cx, cy), [])
                for j in bucket:
                    pairs.add((j, i))
                bucket.append(i)
    return sorted(pairs)


def _connected_components(boxes: Sequence[BoundingBox], margin: float) -> list[list[int]]:
    """Indices grouped by single-linkage connectivity within ``margin``."""
    expanded = [box.expanded(margin / 2) for box in boxes]
    parent = list(range(len(expanded)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in _grid_candidate_pairs(expanded, max(margin, 24.0)):
        if expanded[i].intersects(expanded[j]):
            parent[find(i)] = find(j)

    clusters: dict[int, list[int]] = {}
    for index in range(len(expanded)):
        clusters.setdefault(find(index), []).append(index)
    return list(clusters.values())


def _spatial_groups(
    records: Sequence[dict[str, Any]], margin: float, *, touch_margin: float = 0.0
) -> list[list[dict[str, Any]]]:
    """Connected components of records whose bboxes are within ``margin``.

    ``touch_margin``, when given, first merges records into "ink blobs" at
    that tighter, stroke-scale threshold before the content-scale ``margin``
    decides which distinct blobs form one group. Real ink is routinely
    several separate strokes per hand-drawn mark (a letter, a box's four
    sides) with near-zero gaps between them; without collapsing those first,
    single-linkage clustering chains through every touching mark on the page
    regardless of how tightly ``margin`` is tuned. With ``touch_margin=0``
    every record starts as its own singleton blob, matching plain
    single-linkage clustering directly on ``margin``.
    """
    boxes = [BoundingBox.from_list(record["bbox"]) for record in records]
    if touch_margin > 0:
        blob_indices = _connected_components(boxes, touch_margin)
    else:
        blob_indices = [[i] for i in range(len(records))]
    blob_boxes = [
        BoundingBox.union_all(boxes[i] for i in indices) for indices in blob_indices
    ]

    clusters: list[list[dict[str, Any]]] = []
    for blob_group in _connected_components(blob_boxes, margin):
        members = [
            records[record_index]
            for blob_index in blob_group
            for record_index in blob_indices[blob_index]
        ]
        clusters.append(members)
    return [members for members in clusters if len(members) > 1]


_CONFIDENCE_SAMPLE_CAP = 64


def _group_confidence(members: Sequence[dict[str, Any]], margin: float) -> float:
    if margin <= 0 or len(members) < 2:
        return 1.0
    centers = [BoundingBox.from_list(record["bbox"]).center for record in members]
    # Confidence is a compactness heuristic; nearest-neighbour distances over
    # an evenly spaced sample keep it O(cap^2) instead of O(m^2) on big groups.
    if len(centers) > _CONFIDENCE_SAMPLE_CAP:
        step = len(centers) / _CONFIDENCE_SAMPLE_CAP
        centers = [centers[int(i * step)] for i in range(_CONFIDENCE_SAMPLE_CAP)]
    gaps = []
    for i, (ax, ay) in enumerate(centers):
        nearest = min(
            math.hypot(ax - bx, ay - by)
            for j, (bx, by) in enumerate(centers) if j != i
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
