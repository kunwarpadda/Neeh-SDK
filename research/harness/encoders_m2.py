"""M2 encoding arms: E3 grid language, E5 structural scene graph, E6 temporal
raster (protocol §3). Registered into the same encoder registry as the M1
arms; built ahead of the live M1 sweep so one sweep session covers both.

E7 (hybrid) is deliberately absent: the protocol composes it from the best
text arm *after* first results exist.
"""
from __future__ import annotations

import colorsys
import math
from collections import defaultdict

from neeh.document import Page
from neeh.ink import BoundingBox, Stroke

from research.harness.encoders import EncodedContext, _page_strokes, _resample

GRID_CELLS = 50  # E3: SketchAgent-style square grid
E5_GROUP_MARGIN = 14.0  # page units; bboxes closer than this cluster together


# -- E3: grid language --------------------------------------------------------

E3_LEGEND = """\
The page is described on a 50x50 grid: cell (1,1) is the page's top-left
corner, x grows right to 50, y grows down to 50. Each ink stroke is one line:

  <stroke_id> <author>: (x,y) (x,y) (x,y) ...

listing the grid cells the pen passed through, in drawing order; strokes are
listed in the order they were drawn. Example: `st_x user: (10,40) (12,40)
(14,41)` is a short, nearly horizontal stroke drawn left to right near the
lower-left of the page."""


def encode_e3(page: Page) -> EncodedContext:
    cell_w = page.width / GRID_CELLS
    cell_h = page.height / GRID_CELLS
    step_page = min(cell_w, cell_h)  # about one cell per sample
    lines = []
    for stroke in _page_strokes(page):
        resampled = _resample([(p.x, p.y) for p in stroke.points], step_page)
        cells = []
        for x, y in resampled:
            cx = min(max(int(x / cell_w) + 1, 1), GRID_CELLS)
            cy = min(max(int(y / cell_h) + 1, 1), GRID_CELLS)
            if not cells or cells[-1] != (cx, cy):
                cells.append((cx, cy))
        body = " ".join(f"({cx},{cy})" for cx, cy in cells)
        lines.append(f"{stroke.id} {stroke.author.value}: {body}")
    return EncodedContext(
        arm="E3", version="E3/0.1.0", legend=E3_LEGEND,
        text="\n".join(lines), image_png=None,
    )


# -- E5: structural scene graph ----------------------------------------------

E5_LEGEND = """\
The page is described as spatial groups of ink strokes (no recognition has
been applied — geometry only). Each group is a cluster of strokes that sit
together on the page, listed in drawing order, with its bounding box as
[min_x, min_y, max_x, max_y] in page units. Each stroke line gives the stroke
id, a shape class (dot, line, curve, or loop — loop means the stroke returns
to its start), its chief direction of travel (R/L/U/D and diagonals like DR),
and its size as WIDTHxHEIGHT in page units."""

_DIRECTIONS = [
    (0, "R"), (45, "DR"), (90, "D"), (135, "DL"),
    (180, "L"), (-135, "UL"), (-90, "U"), (-45, "UR"),
]


def _chief_direction(points: list[tuple[float, float]]) -> str:
    dx = points[-1][0] - points[0][0]
    dy = points[-1][1] - points[0][1]
    if dx == 0 and dy == 0:
        return "-"
    angle = math.degrees(math.atan2(dy, dx))
    return min(_DIRECTIONS, key=lambda d: abs((angle - d[0] + 180) % 360 - 180))[1]


def _path_length(points: list[tuple[float, float]]) -> float:
    return sum(math.hypot(x1 - x0, y1 - y0)
               for (x0, y0), (x1, y1) in zip(points, points[1:]))


def _stroke_descriptor(stroke: Stroke) -> str:
    points = [(p.x, p.y) for p in stroke.points]
    length = _path_length(points)
    box = stroke.bbox
    if length < 3.0:
        kind = "dot"
    elif math.hypot(points[-1][0] - points[0][0],
                    points[-1][1] - points[0][1]) < 0.15 * length:
        kind = "loop"
    else:
        chord = math.hypot(points[-1][0] - points[0][0], points[-1][1] - points[0][1])
        kind = "line" if chord > 0.95 * length else "curve"
    return (f"{stroke.id} {kind} {_chief_direction(points)} "
            f"{box.width:.0f}x{box.height:.0f}")


def _cluster(strokes: list[Stroke]) -> list[list[Stroke]]:
    """Agglomerate strokes whose expanded bboxes touch, transitively."""
    parent = list(range(len(strokes)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    boxes = [s.bbox.expanded(E5_GROUP_MARGIN) for s in strokes]
    for i in range(len(strokes)):
        for j in range(i + 1, len(strokes)):
            if boxes[i].intersects(boxes[j]):
                parent[find(i)] = find(j)
    groups: dict[int, list[Stroke]] = defaultdict(list)
    for i, stroke in enumerate(strokes):
        groups[find(i)].append(stroke)
    # Order groups by first-drawn stroke; strokes stay in drawing order.
    return sorted(groups.values(), key=lambda g: min(s.created_at_ms for s in g))


def encode_e5(page: Page) -> EncodedContext:
    strokes = list(_page_strokes(page))
    lines = []
    for number, group in enumerate(_cluster(strokes), start=1):
        box = BoundingBox.union_all(s.bbox for s in group)
        lines.append(
            f"group {number}: bbox [{box.min_x:.0f}, {box.min_y:.0f}, "
            f"{box.max_x:.0f}, {box.max_y:.0f}], {len(group)} strokes"
        )
        lines.extend(f"  {_stroke_descriptor(s)}" for s in group)
    return EncodedContext(
        arm="E5", version="E5/0.1.0", legend=E5_LEGEND,
        text="\n".join(lines), image_png=None,
    )


# -- E6: temporal raster -------------------------------------------------------

E6_LEGEND = (
    "The page is attached as an image in which color encodes drawing order: "
    "the earliest strokes are red, progressing through orange, green, and "
    "blue to violet for the strokes drawn last. Ink color does not carry any "
    "other meaning."
)


def encode_e6(page: Page) -> EncodedContext:
    from neeh.document import Page as PageModel
    from neeh.rendering.png import render_page_png

    strokes = list(_page_strokes(page))
    order = {s.id: i for i, s in enumerate(sorted(strokes, key=lambda s: s.created_at_ms))}
    total = max(len(strokes) - 1, 1)
    recolored = PageModel.from_dict(page.to_dict())
    for layer in recolored.layers:
        for i, stroke in enumerate(list(layer.strokes)):
            hue = 0.83 * order[stroke.id] / total  # red -> violet
            r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 0.85)
            color = f"#{round(r * 255):02x}{round(g * 255):02x}{round(b * 255):02x}"
            layer.strokes[i] = stroke.with_style(
                type(stroke.style)(color=color, width=stroke.style.width,
                                   brush=stroke.style.brush, opacity=stroke.style.opacity)
            )
    return EncodedContext(
        arm="E6", version="E6/0.1.0", legend=E6_LEGEND,
        text=None, image_png=render_page_png(recolored),
    )


M2_ARMS = ["E3", "E5", "E6"]

from research.harness.encoders import ENCODERS  # noqa: E402

ENCODERS.setdefault("E3", encode_e3)
ENCODERS.setdefault("E5", encode_e5)
ENCODERS.setdefault("E6", encode_e6)
