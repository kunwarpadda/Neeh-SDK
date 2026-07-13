"""Undo/redo as reversible stroke edits.

One command shape covers everything: an edit removes some strokes and adds
some strokes on one page. add = {added}, erase = {removed},
move/restyle = {removed originals, added replacements with the same ids}.

Replay bypasses layer locks deliberately: validity is checked when the edit
is first made, and undo must always be able to restore state.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from neeh.canvas.events import EventLog, kind_for_label
from neeh.document import Document, Layer, Page
from neeh.ink import Stroke


def _layer(document: Document, page_id: str, layer_id: str) -> Layer:
    page = document.page(page_id)
    if page is None:
        raise KeyError(f"page {page_id!r} not in document")
    layer = page.layer(layer_id)
    if layer is None:
        raise KeyError(f"layer {layer_id!r} not on page {page_id!r}")
    return layer


def _pluck(layer: Layer, stroke_id: str) -> None:
    for i, stroke in enumerate(layer.strokes):
        if stroke.id == stroke_id:
            layer.strokes.pop(i)
            return


def _replace(layer: Layer, stroke: Stroke) -> bool:
    for i, current in enumerate(layer.strokes):
        if current.id == stroke.id:
            layer.strokes[i] = stroke
            return True
    return False


@dataclass
class StrokeEdit:
    label: str
    page_id: str
    removed: list[tuple[str, Stroke]] = field(default_factory=list)  # (layer_id, stroke)
    added: list[tuple[str, Stroke]] = field(default_factory=list)

    def apply(self, document: Document) -> None:
        removed_keys = {(layer_id, stroke.id) for layer_id, stroke in self.removed}
        replacements = {
            (layer_id, stroke.id): stroke
            for layer_id, stroke in self.added
            if (layer_id, stroke.id) in removed_keys
        }
        for layer_id, stroke in self.removed:
            layer = _layer(document, self.page_id, layer_id)
            replacement = replacements.get((layer_id, stroke.id))
            if replacement is not None:
                _replace(layer, replacement)
            else:
                _pluck(layer, stroke.id)
        for layer_id, stroke in self.added:
            if (layer_id, stroke.id) not in replacements:
                _layer(document, self.page_id, layer_id).strokes.append(stroke)

    def revert(self, document: Document) -> None:
        added_keys = {(layer_id, stroke.id) for layer_id, stroke in self.added}
        originals = {
            (layer_id, stroke.id): stroke
            for layer_id, stroke in self.removed
            if (layer_id, stroke.id) in added_keys
        }
        for layer_id, stroke in self.added:
            layer = _layer(document, self.page_id, layer_id)
            original = originals.get((layer_id, stroke.id))
            if original is not None:
                _replace(layer, original)
            else:
                _pluck(layer, stroke.id)
        for layer_id, stroke in self.removed:
            if (layer_id, stroke.id) not in originals:
                _layer(document, self.page_id, layer_id).strokes.append(stroke)


class History:
    def __init__(self, limit: int = 200) -> None:
        self.limit = limit
        self._undo: list[StrokeEdit] = []
        self._redo: list[StrokeEdit] = []
        # Append-only record of every mutation; unlike the undo/redo stacks it
        # is never popped, so erased and replaced ink stays recoverable.
        self.log = EventLog()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def push(self, edit: StrokeEdit, document: Document, *, kind: Optional[str] = None) -> None:
        edit.apply(document)
        self._undo.append(edit)
        if len(self._undo) > self.limit:
            self._undo.pop(0)
        self._redo.clear()
        self.log.record(
            kind=kind or kind_for_label(edit.label),
            label=edit.label,
            page_id=edit.page_id,
            removed=edit.removed,
            added=edit.added,
        )

    def record_action(
        self,
        *,
        kind: str,
        label: str,
        page_id: str,
        meta: Optional[dict] = None,
    ) -> None:
        """Append a non-stroke mutation (e.g. grouping) to the log.

        Such actions change relations, not stroke content, so they are logged
        but do not enter the stroke undo/redo stacks.
        """
        self.log.record(kind=kind, label=label, page_id=page_id, meta=meta)

    def undo(self, document: Document) -> Optional[str]:
        if not self._undo:
            return None
        edit = self._undo.pop()
        edit.revert(document)
        self._redo.append(edit)
        # An undo is itself an event: it removed what the edit had added and
        # restored what the edit had removed (the inverse net effect).
        self.log.record(
            kind="undo",
            label=f"undo:{edit.label}",
            page_id=edit.page_id,
            removed=edit.added,
            added=edit.removed,
        )
        return edit.label

    def redo(self, document: Document) -> Optional[str]:
        if not self._redo:
            return None
        edit = self._redo.pop()
        edit.apply(document)
        self._undo.append(edit)
        self.log.record(
            kind="redo",
            label=f"redo:{edit.label}",
            page_id=edit.page_id,
            removed=edit.removed,
            added=edit.added,
        )
        return edit.label
