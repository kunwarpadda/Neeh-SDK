"""Geometry-based ink structure recognizer: strokes -> clusters -> links.

Pipeline:
  1. connectors — long, straight strokes that span between ink groups
  2. heads — small bent strokes riding a connector endpoint (arrowheads)
  3. clusters — bbox-expansion union-find over the remaining strokes
  4. links — each connector binds its endpoints to the nearest clusters;
     direction comes from the head if present, else from drawing order
     (people draw arrows source -> target), at lower confidence

Every output item is a valid ICF ``semantics`` entry: page-unit
coordinates, resolvable stroke ids, ``confidence``, and
``source="neeh-geometric/0.1"``. Links carry the relation in ``edges``
(``{"from": <cluster id>, "to": <cluster id>}``).
"""
from __future__ import annotations

import math
from typing import Any, Optional

from neeh.document.page import Page
from neeh.ink.geometry import BoundingBox
from neeh.ink.stroke import Stroke

RECOGNIZER_SOURCE = "neeh-geometric/0.1"

CLUSTER_MARGIN = 14.0        # page units
CONNECTOR_MIN_SPAN = 150.0   # endpoints at least this far apart
CONNECTOR_STRAIGHTNESS = 0.92  # chord / path length
HEAD_MAX_DIAG = 80.0         # arrowheads are small ...
HEAD_MAX_STRAIGHTNESS = 0.85 # ... and bent
HEAD_BIND_RADIUS = 12.0      # head passes (nearly) through the endpoint
LINK_BIND_RADIUS = 60.0      # endpoint-to-cluster-bbox distance


def _length(stroke: Stroke) -> float:
    pts = stroke.points
    return sum(math.hypot(pts[i + 1].x - pts[i].x, pts[i + 1].y - pts[i].y)
               for i in range(len(pts) - 1))


def _chord(stroke: Stroke) -> float:
    pts = stroke.points
    return math.hypot(pts[-1].x - pts[0].x, pts[-1].y - pts[0].y)


def _bbox_distance(x: float, y: float, box: BoundingBox) -> float:
    dx = max(box.min_x - x, 0.0, x - box.max_x)
    dy = max(box.min_y - y, 0.0, y - box.max_y)
    return math.hypot(dx, dy)


def _is_connector(stroke: Stroke) -> bool:
    if len(stroke.points) < 2:
        return False
    chord = _chord(stroke)
    return chord >= CONNECTOR_MIN_SPAN and chord >= CONNECTOR_STRAIGHTNESS * _length(stroke)


def _is_head(stroke: Stroke, endpoints: list[tuple[float, float]]) -> Optional[int]:
    """Index of the connector endpoint this stroke crowns, or None."""
    box = stroke.bbox
    if math.hypot(box.width, box.height) > HEAD_MAX_DIAG or len(stroke.points) < 2:
        return None
    length = _length(stroke)
    if length > 0 and _chord(stroke) > HEAD_MAX_STRAIGHTNESS * length:
        return None
    # An arrowhead is drawn through the tip: its middle point sits on the
    # connector endpoint. Letters merely pass near it, at arbitrary phase.
    mid = stroke.points[len(stroke.points) // 2]
    for i, (ex, ey) in enumerate(endpoints):
        if math.hypot(mid.x - ex, mid.y - ey) <= HEAD_BIND_RADIUS:
            return i
    return None


def _visible_strokes(page: Page) -> list[Stroke]:
    return [s for layer in page.layers if layer.visible for s in layer.strokes]


def _union_clusters(strokes: list[Stroke]) -> list[list[Stroke]]:
    parent = list(range(len(strokes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    boxes = [s.bbox.expanded(CLUSTER_MARGIN) for s in strokes]
    for i in range(len(strokes)):
        for j in range(i + 1, len(strokes)):
            if boxes[i].intersects(boxes[j]):
                parent[find(i)] = find(j)
    groups: dict[int, list[Stroke]] = {}
    for i, stroke in enumerate(strokes):
        groups.setdefault(find(i), []).append(stroke)
    return sorted(groups.values(), key=lambda g: min(s.created_at_ms for s in g))


def build_semantics(page: Page) -> list[dict[str, Any]]:
    """Recognize clusters and directed links; return ICF semantics items."""
    strokes = _visible_strokes(page)
    connectors = [s for s in strokes if _is_connector(s)]
    endpoints: list[tuple[float, float]] = []
    for c in connectors:
        endpoints.append((c.points[0].x, c.points[0].y))
        endpoints.append((c.points[-1].x, c.points[-1].y))

    heads: dict[str, int] = {}  # stroke id -> endpoint index
    connector_ids = {c.id for c in connectors}
    rest = []
    for s in strokes:
        if s.id in connector_ids:
            continue
        at = _is_head(s, endpoints)
        if at is not None:
            heads[s.id] = at
        else:
            rest.append(s)

    items: list[dict[str, Any]] = []
    cluster_of: list[tuple[str, BoundingBox]] = []
    for n, group in enumerate(_union_clusters(rest)):
        box = BoundingBox.union_all(s.bbox for s in group)
        cid = f"cl_{page.id}_{n:02d}"
        cluster_of.append((cid, box))
        items.append({
            "id": cid, "kind": "cluster",
            "stroke_ids": [s.id for s in group],
            "region": [round(v, 1) for v in box.to_list()],
            "confidence": 0.9, "source": RECOGNIZER_SOURCE,
        })

    def nearest_cluster(x: float, y: float) -> Optional[str]:
        best, best_d = None, LINK_BIND_RADIUS
        for cid, box in cluster_of:
            d = _bbox_distance(x, y, box)
            if d <= best_d:
                best, best_d = cid, d
        return best

    for k, c in enumerate(connectors):
        p0, p1 = c.points[0], c.points[-1]
        ends = [(p0.x, p0.y), (p1.x, p1.y)]
        head_ids = [sid for sid, ei in heads.items()
                    if endpoints[ei] in ends and ei // 2 == k]
        # Direction: the head marks the target; else trust drawing order.
        to_end, confidence = (1, 0.55)
        for sid, ei in heads.items():
            if ei // 2 == k:
                to_end, confidence = (ei % 2, 0.85)
                break
        src = nearest_cluster(*ends[1 - to_end])
        dst = nearest_cluster(*ends[to_end])
        if src is None or dst is None or src == dst:
            continue
        items.append({
            "id": f"lk_{page.id}_{k:02d}", "kind": "link",
            "stroke_ids": [c.id, *head_ids],
            "region": [round(v, 1) for v in c.bbox.to_list()],
            "edges": {"from": src, "to": dst},
            "confidence": confidence, "source": RECOGNIZER_SOURCE,
        })
    return items
