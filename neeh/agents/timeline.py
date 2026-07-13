"""Query-aware temporal indexing for digital ink.

The timeline treats a drawing as a sparse sequence of creation episodes rather
than a dense video.  Given the append-only event log (``neeh.canvas.events``)
it reconstructs a complete history -- erased and replaced strokes fold back into
their creation episodes and ``history_complete`` is true. Without the log it
falls back to the current page snapshot and reports history as incomplete.
"""
from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from neeh.document import Page
from neeh.ink import BoundingBox, Stroke

TIMELINE_VERSION = "ink-timeline/v1"


@dataclass(frozen=True)
class TimelineConfig:
    episode_gap_ms: int = 1_500
    spatial_margin: float = 72.0
    max_episode_strokes: int = 24

    def __post_init__(self) -> None:
        if self.episode_gap_ms < 0 or self.spatial_margin < 0:
            raise ValueError("timeline gaps and margins must be non-negative")
        if self.max_episode_strokes < 1:
            raise ValueError("max_episode_strokes must be positive")


def _visible_strokes(page: Page) -> list[Stroke]:
    return [stroke for layer in page.layers if layer.visible for stroke in layer.strokes]


def _start_ms(stroke: Stroke) -> int:
    return stroke.created_at_ms + stroke.points[0].t_ms


def _end_ms(stroke: Stroke) -> int:
    return stroke.created_at_ms + stroke.points[-1].t_ms


def _length(stroke: Stroke) -> float:
    return sum(
        math.hypot(b.x - a.x, b.y - a.y)
        for a, b in zip(stroke.points, stroke.points[1:])
    )


def _direction(stroke: Stroke) -> str:
    first, last = stroke.points[0], stroke.points[-1]
    dx, dy = last.x - first.x, last.y - first.y
    distance = math.hypot(dx, dy)
    diagonal = math.hypot(stroke.bbox.width, stroke.bbox.height)
    if distance <= max(4.0, diagonal * 0.12):
        return "closed-or-stationary"
    angle = math.atan2(dy, dx)
    directions = ("right", "down-right", "down", "down-left", "left", "up-left", "up", "up-right")
    return directions[round(angle / (math.pi / 4)) % 8]


def stroke_analysis_record(stroke: Stroke, pause_before_ms: Optional[int] = None) -> dict[str, Any]:
    pressures = [point.pressure for point in stroke.points]
    tilts = [math.hypot(point.tilt_x, point.tilt_y) for point in stroke.points]
    record: dict[str, Any] = {
        "id": stroke.id,
        "author": stroke.author.value,
        "start_ms": _start_ms(stroke),
        "end_ms": _end_ms(stroke),
        "duration_ms": stroke.duration_ms,
        "bbox": stroke.bbox.to_list(),
        "point_count": len(stroke.points),
        "path_length": round(_length(stroke), 2),
        "direction": _direction(stroke),
        "pressure": {
            "mean": round(sum(pressures) / len(pressures), 4),
            "min": round(min(pressures), 4),
            "max": round(max(pressures), 4),
        },
        "tilt_magnitude_mean": round(sum(tilts) / len(tilts), 3),
    }
    if pause_before_ms is not None:
        record["pause_before_ms"] = pause_before_ms
    return record


def _stable_moment_id(page_id: str, stroke_ids: Sequence[str]) -> str:
    digest = hashlib.sha256((page_id + "\0" + "\0".join(stroke_ids)).encode()).hexdigest()[:12]
    return f"moment_{digest}"


def _cross_out_targets(stroke: Stroke, earlier: Sequence[Stroke]) -> list[str]:
    if len(stroke.points) < 2 or _direction(stroke) == "closed-or-stationary":
        return []
    # A cross-out candidate is deliberately conservative: a later elongated
    # open stroke must pass through the interior of an older mark's bbox.
    if _length(stroke) < max(stroke.style.width * 4, 12.0):
        return []
    targets: list[str] = []
    samples: Optional[list[tuple[float, float]]] = None
    for prior in earlier:
        if not stroke.bbox.intersects(prior.bbox):
            continue
        if samples is None:
            # Points plus segment midpoints; they depend only on the stroke,
            # so they are built once, not per overlapping prior.
            samples = [(p.x, p.y) for p in stroke.points]
            samples.extend(
                ((a.x + b.x) / 2, (a.y + b.y) / 2)
                for a, b in zip(stroke.points, stroke.points[1:])
            )
        interior = prior.bbox.expanded(-min(prior.bbox.width, prior.bbox.height) * 0.08)
        if any(interior.contains(x, y) for x, y in samples):
            targets.append(prior.id)
    return targets


def _logged_additions(page: Page, event_log: Any) -> dict[str, Stroke]:
    """Creation snapshot (first added) per stroke id logged for this page."""
    first_added: dict[str, Stroke] = {}
    for event in event_log.events:
        if event.page_id != page.id:
            continue
        for _, stroke in event.added:
            first_added.setdefault(stroke.id, stroke)
    return first_added


def build_ink_timeline(
    page: Page,
    *,
    config: Optional[TimelineConfig] = None,
    event_log: Any = None,
) -> dict[str, Any]:
    """Build stable, coarse-to-fine creation episodes for the page.

    With ``event_log`` supplied, the timeline is completed from the append-only
    log: strokes that were erased or replaced are folded back into the creation
    episodes (tagged as erased). ``history_complete`` is claimed only when every
    currently-visible stroke actually came through the log, so a page whose ink
    bypassed the log (e.g. added straight to a layer) is honestly reported as
    incomplete rather than falsely complete.
    """
    config = config or TimelineConfig()
    visible = _visible_strokes(page)
    visible_ids = {stroke.id for stroke in visible}
    erased_ids: set[str] = set()
    universe = list(visible)
    history_complete = False
    if event_log is not None:
        logged = _logged_additions(page, event_log)
        erased = [stroke for sid, stroke in logged.items() if sid not in visible_ids]
        erased_ids = {stroke.id for stroke in erased}
        universe = visible + erased
        history_complete = visible_ids <= set(logged)
    page_order = {stroke.id: i for i, stroke in enumerate(universe)}
    strokes = sorted(universe, key=lambda s: (_start_ms(s), page_order[s.id]))
    # Incremental spatial grid over earlier strokes: each stroke only tests
    # the chronologically-earlier strokes sharing a bbox grid cell, instead of
    # every earlier stroke (two intersecting bboxes always share a cell, so
    # candidate recall is exact and the scan stays near-linear on dense pages).
    target_map: dict[str, list[str]] = {}
    grid_cell = 64.0
    grid: dict[tuple[int, int], list[int]] = {}
    seen_order: list[Stroke] = []
    for stroke in strokes:
        box = stroke.bbox
        x0, x1 = int(box.min_x // grid_cell), int(box.max_x // grid_cell)
        y0, y1 = int(box.min_y // grid_cell), int(box.max_y // grid_cell)
        cells = [(cx, cy) for cx in range(x0, x1 + 1) for cy in range(y0, y1 + 1)]
        candidate_indices = sorted({
            index for cell in cells for index in grid.get(cell, ())
        })
        candidates = [seen_order[index] for index in candidate_indices]
        target_map[stroke.id] = _cross_out_targets(stroke, candidates)
        position = len(seen_order)
        seen_order.append(stroke)
        for cell in cells:
            grid.setdefault(cell, []).append(position)

    groups: list[list[Stroke]] = []
    group_box: Optional[BoundingBox] = None
    group_end = 0
    for stroke in strokes:
        gap = max(0, _start_ms(stroke) - group_end) if groups else 0
        joins = bool(
            groups
            and gap <= config.episode_gap_ms
            and len(groups[-1]) < config.max_episode_strokes
            and group_box is not None
            and group_box.expanded(config.spatial_margin).intersects(stroke.bbox)
        )
        if not joins:
            groups.append([])
            group_box = None
        groups[-1].append(stroke)
        group_box = stroke.bbox if group_box is None else group_box.union(stroke.bbox)
        group_end = max(group_end, _end_ms(stroke))

    moments: list[dict[str, Any]] = []
    previous_end: Optional[int] = None
    for group in groups:
        box = BoundingBox.union_all(stroke.bbox for stroke in group)
        assert box is not None
        records: list[dict[str, Any]] = []
        prior_end: Optional[int] = None
        affected: list[str] = []
        for stroke in group:
            records.append(
                stroke_analysis_record(
                    stroke,
                    None if prior_end is None else max(0, _start_ms(stroke) - prior_end),
                )
            )
            prior_end = _end_ms(stroke)
            affected.extend(target_map[stroke.id])
        event_types = ["creation"]
        if any(record.get("pause_before_ms", 0) >= 500 for record in records):
            event_types.append("pause")
        if affected:
            event_types.extend(["overlay", "cross_out_candidate"])
        moment = {
            "id": _stable_moment_id(page.id, [stroke.id for stroke in group]),
            "start_ms": min(_start_ms(stroke) for stroke in group),
            "end_ms": max(_end_ms(stroke) for stroke in group),
            "pause_before_ms": None if previous_end is None else max(0, min(_start_ms(s) for s in group) - previous_end),
            "bbox": box.to_list(),
            "stroke_ids": [stroke.id for stroke in group],
            "stroke_count": len(group),
            "authors": sorted({stroke.author.value for stroke in group}),
            "event_types": event_types,
            "directions": sorted({record["direction"] for record in records}),
            "affected_prior_ids": list(dict.fromkeys(affected)),
            "erased_ids": [s.id for s in group if s.id in erased_ids],
            "strokes": records,
        }
        if moment["erased_ids"] and "erased" not in moment["event_types"]:
            moment["event_types"].append("erased")
        moments.append(moment)
        previous_end = moment["end_ms"]

    return {
        "schema": TIMELINE_VERSION,
        "page_id": page.id,
        "history_complete": history_complete,
        "history_limitations": (
            []
            if history_complete
            else ["erased strokes and undone edits are absent from the document snapshot"]
        ),
        "episode_gap_ms": config.episode_gap_ms,
        "moment_count": len(moments),
        "moments": moments,
    }


def _terms(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_-]+", value.casefold()))


def _moment_overlap(a: dict[str, Any], b: dict[str, Any]) -> float:
    a_ids, b_ids = set(a["stroke_ids"]), set(b["stroke_ids"])
    if a_ids | b_ids:
        shared = len(a_ids & b_ids) / len(a_ids | b_ids)
    else:
        shared = 0.0
    a_box, b_box = BoundingBox.from_list(a["bbox"]), BoundingBox.from_list(b["bbox"])
    return max(shared, 0.5 if a_box.intersects(b_box) else 0.0)


def find_ink_moments(
    timeline: dict[str, Any],
    query: str,
    *,
    region: Optional[Sequence[float]] = None,
    object_ids: Optional[Sequence[str]] = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    """Rank moments by instruction relevance, coverage, novelty, and recency."""
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 24:
        raise ValueError("limit must be an integer between 1 and 24")
    query_terms = _terms(query)
    ids = set(object_ids or [])
    query_box = BoundingBox.from_list(region) if region is not None else None
    moments = timeline.get("moments") or []
    newest = max((moment["end_ms"] for moment in moments), default=0)
    span = max(newest - min((moment["start_ms"] for moment in moments), default=newest), 1)
    semantic = {
        "cross": {"cross", "crossed", "crossout", "cross-out", "correct", "correction", "replace"},
        "order": {"order", "before", "after", "first", "last", "earlier", "later", "when"},
        "direction": {"direction", "drawn", "toward", "left", "right", "up", "down"},
        "pause": {"pause", "hesitate", "stopped"},
    }
    scored: list[tuple[float, dict[str, Any], list[str]]] = []
    for moment in moments:
        haystack = _terms(str(moment))
        score = 4.0 * len(query_terms & haystack)
        reasons: list[str] = []
        if query_terms & haystack:
            reasons.append("term-match")
        if ids & (set(moment["stroke_ids"]) | set(moment["affected_prior_ids"])):
            score += 14.0
            reasons.append("object-match")
        if query_box is not None and query_box.intersects(BoundingBox.from_list(moment["bbox"])):
            score += 8.0
            reasons.append("region-match")
        for label, words in semantic.items():
            if not query_terms & words:
                continue
            if label == "cross" and "cross_out_candidate" in moment["event_types"]:
                score += 10.0
                reasons.append("cross-out-evidence")
            elif label == "pause" and "pause" in moment["event_types"]:
                score += 8.0
                reasons.append("pause-evidence")
            elif label in {"order", "direction"}:
                score += 3.0
                reasons.append(f"{label}-evidence")
        score += 2.0 * (moment["end_ms"] - (newest - span)) / span
        scored.append((score, moment, reasons))

    selected: list[dict[str, Any]] = []
    remaining = scored[:]
    target_count = min(limit, len(remaining))
    while remaining and len(selected) < target_count:
        best = max(
            remaining,
            key=lambda item: item[0] - 3.0 * max(
                (_moment_overlap(item[1], chosen) for chosen in selected), default=0.0
            ),
        )
        remaining.remove(best)
        score, moment, reasons = best
        selected.append({
            **{key: value for key, value in moment.items() if key != "strokes"},
            "score": round(score, 3),
            "reasons": reasons or ["coverage"],
        })
    return selected


def inspect_ink_moment(
    page: Page,
    timeline: dict[str, Any],
    moment_id: str,
    *,
    view: str = "diff",
    max_replay_steps: int = 16,
) -> dict[str, Any]:
    """Inspect a temporal episode without pretending erased history exists."""
    if view not in {"before", "after", "current", "diff", "replay"}:
        raise ValueError("view must be before, after, current, diff, or replay")
    moment = next((item for item in timeline.get("moments") or [] if item["id"] == moment_id), None)
    if moment is None:
        raise ValueError(f"unknown ink moment id {moment_id!r}")
    strokes = sorted(_visible_strokes(page), key=lambda s: (_start_ms(s), s.id))
    region = BoundingBox.from_list(moment["bbox"]).expanded(24.0)
    nearby = [stroke for stroke in strokes if region.intersects(stroke.bbox)]

    def compact(stroke: Stroke) -> dict[str, Any]:
        return {
            "id": stroke.id,
            "start_ms": _start_ms(stroke),
            "end_ms": _end_ms(stroke),
            "bbox": stroke.bbox.to_list(),
            "direction": _direction(stroke),
        }

    base: dict[str, Any] = {
        "schema": TIMELINE_VERSION,
        "moment_id": moment_id,
        "view": view,
        "region": region.to_list(),
        "history_complete": timeline.get("history_complete", False),
        "history_limitations": timeline.get("history_limitations", []),
    }
    if view == "before":
        base["strokes"] = [compact(s) for s in nearby if _end_ms(s) < moment["start_ms"]]
    elif view == "after":
        base["strokes"] = [compact(s) for s in nearby if _start_ms(s) <= moment["end_ms"]]
    elif view == "current":
        base["strokes"] = [compact(s) for s in nearby]
    elif view == "diff":
        base["added"] = moment["strokes"]
        base["affected_prior_ids"] = moment["affected_prior_ids"]
        base["event_types"] = moment["event_types"]
    else:
        moment_strokes = [s for s in strokes if s.id in set(moment["stroke_ids"])]
        steps = []
        cumulative: list[str] = []
        for stroke in moment_strokes[:max_replay_steps]:
            cumulative.append(stroke.id)
            steps.append({
                "at_ms": _end_ms(stroke),
                "added_stroke_id": stroke.id,
                "visible_moment_stroke_ids": list(cumulative),
                "direction": _direction(stroke),
            })
        base["steps"] = steps
        base["truncated"] = len(moment_strokes) > len(steps)
    return base


__all__ = [
    "TIMELINE_VERSION",
    "TimelineConfig",
    "build_ink_timeline",
    "find_ink_moments",
    "inspect_ink_moment",
    "stroke_analysis_record",
]
