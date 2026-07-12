"""Canvas: one editing session over a document.

Holds the current page, viewport, selection, and undo history. All mutations
go through History so every operation — user or agent — is undoable.
"""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Union

from neeh.canvas.history import History, StrokeEdit
from neeh.canvas.selection import Selection
from neeh.canvas.viewport import Viewport
from neeh.document import Document, Layer, Page
from neeh.ink import Author, BoundingBox, Point, Stroke, StrokeStyle

PointLike = Union[Point, Sequence[float]]


def _coerce_points(points: Iterable[PointLike]) -> tuple[Point, ...]:
    return tuple(p if isinstance(p, Point) else Point.from_list(p) for p in points)


# Point/BoundingBox only reject non-finite coordinates, not magnitude — an
# unbounded coordinate (e.g. 1e12) is a valid Stroke but makes every future
# page raster (bbox-cropped to content) attempt an unbounded allocation.
# Bound coordinates relative to the page instead, with a generous margin so
# legitimate off-canvas scratch content still fits.
_MAX_COORD_MARGIN_FACTOR = 10.0


def _validate_points_in_bounds(points: Iterable[Point], page: Page) -> None:
    bound = page.rect.expanded(max(page.width, page.height) * _MAX_COORD_MARGIN_FACTOR)
    for point in points:
        if not bound.contains(point.x, point.y):
            raise ValueError(
                f"stroke point ({point.x:g}, {point.y:g}) is far outside the "
                f"page bounds {page.rect.to_list()}"
            )


class Canvas:
    def __init__(self, document: Optional[Document] = None) -> None:
        self.document = document or Document()
        self._page_index = 0
        self.viewport = Viewport()
        self.selection = Selection()
        self.history = History()

    @property
    def page(self) -> Page:
        return self.document.pages[self._page_index]

    def goto_page(self, index: int) -> Page:
        if not 0 <= index < len(self.document.pages):
            raise IndexError(f"page index {index} out of range")
        self._page_index = index
        self.selection.clear()
        return self.page

    # -- mutations (all undoable) ---------------------------------------

    def add_stroke(
        self,
        points: Iterable[PointLike],
        style: Optional[StrokeStyle] = None,
        author: Author = Author.USER,
        layer: Optional[Layer] = None,
    ) -> Stroke:
        # Build and validate the immutable value before resolving a default
        # layer, because agent-layer resolution may create one.
        stroke = Stroke(
            points=_coerce_points(points),
            style=style or StrokeStyle(),
            author=author,
        )
        _validate_points_in_bounds(stroke.points, self.page)
        target = layer or self._default_layer(author)
        if target.locked:
            raise ValueError(f"layer '{target.name}' is locked")
        edit = StrokeEdit("add_stroke", self.page.id, added=[(target.id, stroke)])
        self.history.push(edit, self.document)
        return stroke

    def add_strokes(
        self,
        strokes_points: Iterable[Iterable[PointLike]],
        style: Optional[StrokeStyle] = None,
        author: Author = Author.USER,
        layer: Optional[Layer] = None,
    ) -> list[Stroke]:
        """Add several strokes as ONE edit — undo removes them all together
        (a written word or shape is one gesture, not one command per line)."""
        strokes = [
            Stroke(points=_coerce_points(pts), style=style or StrokeStyle(), author=author)
            for pts in strokes_points
        ]
        for stroke in strokes:
            _validate_points_in_bounds(stroke.points, self.page)
        if not strokes:
            return []
        # As above, default-layer lookup happens only after every stroke has
        # validated, so a failed atomic batch cannot leave an empty layer.
        target = layer or self._default_layer(author)
        if target.locked:
            raise ValueError(f"layer '{target.name}' is locked")
        edit = StrokeEdit("add_strokes", self.page.id, added=[(target.id, s) for s in strokes])
        self.history.push(edit, self.document)
        return strokes

    def add_styled_strokes(
        self,
        groups: Iterable[tuple[Iterable[PointLike], StrokeStyle]],
        author: Author = Author.AGENT,
        layer: Optional[Layer] = None,
        label: str = "add_strokes",
    ) -> list[Stroke]:
        """Add several strokes with individual styles as ONE undoable edit.

        Unlike add_strokes (one shared style), each (points, style) pair keeps
        its own style — so a composed gesture like a captioned arrow (thin text
        strokes plus a thicker shaft) is a single undo step."""
        strokes = [
            Stroke(points=_coerce_points(pts), style=style, author=author)
            for pts, style in groups
        ]
        for stroke in strokes:
            _validate_points_in_bounds(stroke.points, self.page)
        if not strokes:
            return []
        target = layer or self._default_layer(author)
        if target.locked:
            raise ValueError(f"layer '{target.name}' is locked")
        edit = StrokeEdit(label, self.page.id, added=[(target.id, s) for s in strokes])
        self.history.push(edit, self.document)
        return strokes

    def move_and_add_strokes(
        self,
        strokes_points: Iterable[Iterable[PointLike]],
        *,
        move_stroke_ids: Iterable[str],
        dx: float,
        dy: float,
        style: Optional[StrokeStyle] = None,
        author: Author = Author.AGENT,
        layer: Optional[Layer] = None,
        label: str = "move_and_add_strokes",
    ) -> tuple[list[Stroke], list[str]]:
        """Translate existing strokes and add new strokes as one undo step."""
        strokes = [
            Stroke(points=_coerce_points(pts), style=style or StrokeStyle(), author=author)
            for pts in strokes_points
        ]
        for stroke in strokes:
            _validate_points_in_bounds(stroke.points, self.page)
        if not strokes:
            return [], []

        ids = list(dict.fromkeys(move_stroke_ids))
        removed: list[tuple[str, Stroke]] = []
        moved: list[tuple[str, Stroke]] = []
        for stroke_id in ids:
            found = self.page.find(stroke_id)
            if found is None:
                raise ValueError(f"unknown stroke id {stroke_id!r}")
            source_layer, stroke = found
            if source_layer.locked:
                raise ValueError(f"layer '{source_layer.name}' is locked")
            removed.append((source_layer.id, stroke))
            moved.append((source_layer.id, stroke.translated(dx, dy)))

        for _, moved_stroke in moved:
            _validate_points_in_bounds(moved_stroke.points, self.page)

        target = layer or self._default_layer(author)
        if target.locked:
            raise ValueError(f"layer '{target.name}' is locked")
        added = moved + [(target.id, stroke) for stroke in strokes]
        self.history.push(
            StrokeEdit(label, self.page.id, removed=removed, added=added),
            self.document,
        )
        return strokes, ids

    def erase(
        self,
        stroke_ids: Optional[Iterable[str]] = None,
        region: Optional[BoundingBox] = None,
    ) -> list[str]:
        """Erase by explicit ids or by region (bbox intersection for now;
        point-accurate hit-testing arrives with the geometry layer)."""
        targets: list[tuple[Layer, Stroke]] = []
        if stroke_ids is not None:
            for stroke_id in dict.fromkeys(stroke_ids):
                found = self.page.find(stroke_id)
                if found is not None and not found[0].locked:
                    targets.append(found)
        elif region is not None:
            for layer in self.page.layers:
                if layer.locked:
                    continue
                targets.extend((layer, s) for s in layer.strokes_in(region))
        else:
            raise ValueError("erase needs stroke_ids or a region")

        if not targets:
            return []
        edit = StrokeEdit(
            "erase",
            self.page.id,
            removed=[(layer.id, stroke) for layer, stroke in targets],
        )
        self.history.push(edit, self.document)
        erased = [stroke.id for _, stroke in targets]
        self.selection.discard(erased)
        return erased

    def move(self, dx: float, dy: float, stroke_ids: Optional[Iterable[str]] = None) -> int:
        """Translate the given strokes (default: current selection). Ids are
        preserved, so references to moved strokes stay valid."""
        ids = (
            list(dict.fromkeys(stroke_ids))
            if stroke_ids is not None
            else list(self.selection.stroke_ids)
        )
        removed: list[tuple[str, Stroke]] = []
        added: list[tuple[str, Stroke]] = []
        for stroke_id in ids:
            found = self.page.find(stroke_id)
            if found is None or found[0].locked:
                continue
            layer, stroke = found
            removed.append((layer.id, stroke))
            added.append((layer.id, stroke.translated(dx, dy)))
        if not removed:
            return 0
        for _, moved_stroke in added:
            _validate_points_in_bounds(moved_stroke.points, self.page)
        self.history.push(StrokeEdit("move", self.page.id, removed=removed, added=added), self.document)
        return len(removed)

    def undo(self) -> Optional[str]:
        return self.history.undo(self.document)

    def redo(self) -> Optional[str]:
        return self.history.redo(self.document)

    # -- queries ---------------------------------------------------------

    def select(
        self,
        region: Optional[BoundingBox] = None,
        stroke_ids: Optional[Iterable[str]] = None,
    ) -> Selection:
        if region is not None:
            self.selection.replace(s.id for s in self.page.strokes_in(region))
        elif stroke_ids is not None:
            self.selection.replace(stroke_ids)
        else:
            self.selection.clear()
        return self.selection

    def strokes_in_view(self) -> list[Stroke]:
        return self.page.strokes_in(self.viewport.visible_bounds, visible_only=True)

    # -- internals ---------------------------------------------------------

    def _default_layer(self, author: Author) -> Layer:
        """First user layer, locked or not — a locked default layer makes
        add_stroke fail loudly rather than spawn a shadow layer."""
        if author is Author.AGENT:
            return self.page.agent_layer()
        for layer in self.page.layers:
            if layer.author is Author.USER:
                return layer
        return self.page.add_layer("ink")
