"""Append-only document event log.

Undo/redo (``neeh.canvas.history``) is a *mutable* stack: it pops on undo and
clears the redo branch on the next edit, so it cannot answer "what was here
before I erased it?". This log is the complement -- an immutable, append-only
record of every mutation, keyed by a monotonically increasing sequence number
and a stable event id.

Every event snapshots the exact strokes it removed and added (strokes are
immutable, so the snapshot is a safe reference). Because nothing is ever
removed from the log, erased and replaced ink stays fully recoverable: replay,
diff, and before/after queries all read straight off the log rather than
reconstructing history from the final page.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from neeh.ids import new_id
from neeh.ink import Stroke

EVENTLOG_VERSION = "ink-eventlog/v1"

# Recognized event kinds. ``label`` keeps the finer-grained edit name.
EVENT_KINDS = (
    "add", "erase", "move", "restyle", "group", "page", "agent", "undo", "redo",
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def kind_for_label(label: str) -> str:
    """Map a StrokeEdit label to a coarse event kind (label is kept verbatim)."""
    if label.startswith("add") or label.startswith("insert"):
        return "add"
    if label.startswith("erase") or label.startswith("delete"):
        return "erase"
    if label.startswith("restyle") or "style" in label:
        return "restyle"
    if label.startswith("move"):
        return "move"
    if label.startswith("group") or label.startswith("ungroup"):
        return "group"
    if label.startswith("agent"):
        return "agent"
    return label


@dataclass(frozen=True)
class DocumentEvent:
    """One immutable, applied mutation in document order."""

    seq: int
    event_id: str
    kind: str
    label: str
    page_id: str
    at_ms: int
    removed: tuple[tuple[str, Stroke], ...] = ()  # (layer_id, stroke) actually removed
    added: tuple[tuple[str, Stroke], ...] = ()     # (layer_id, stroke) actually added
    # Kind-specific payload for events that change no strokes (e.g. grouping).
    meta: Optional[dict[str, Any]] = None

    @property
    def removed_ids(self) -> tuple[str, ...]:
        return tuple(stroke.id for _, stroke in self.removed)

    @property
    def added_ids(self) -> tuple[str, ...]:
        return tuple(stroke.id for _, stroke in self.added)

    @property
    def stroke_ids(self) -> tuple[str, ...]:
        return self.removed_ids + self.added_ids

    def touches(self, stroke_id: str) -> bool:
        return stroke_id in self.removed_ids or stroke_id in self.added_ids

    def authors(self) -> tuple[str, ...]:
        seen = []
        for _, stroke in self.added + self.removed:
            value = stroke.author.value
            if value not in seen:
                seen.append(value)
        return tuple(seen)

    def to_dict(self) -> dict[str, Any]:
        """Compact, model-facing view: ids only, no full stroke geometry."""
        payload = {
            "seq": self.seq,
            "event_id": self.event_id,
            "kind": self.kind,
            "label": self.label,
            "page_id": self.page_id,
            "at_ms": self.at_ms,
            "removed_ids": list(self.removed_ids),
            "added_ids": list(self.added_ids),
            "authors": list(self.authors()),
        }
        if self.meta is not None:
            payload["meta"] = self.meta
        return payload

    def to_snapshot(self) -> dict[str, Any]:
        """Full, round-trippable serialization including stroke snapshots."""
        return {
            "seq": self.seq,
            "event_id": self.event_id,
            "kind": self.kind,
            "label": self.label,
            "page_id": self.page_id,
            "at_ms": self.at_ms,
            "removed": [
                {"layer_id": layer_id, "stroke": stroke.to_dict()}
                for layer_id, stroke in self.removed
            ],
            "added": [
                {"layer_id": layer_id, "stroke": stroke.to_dict()}
                for layer_id, stroke in self.added
            ],
            "meta": self.meta,
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> "DocumentEvent":
        def _pairs(items: Any) -> tuple[tuple[str, Stroke], ...]:
            return tuple(
                (item["layer_id"], Stroke.from_dict(item["stroke"]))
                for item in items or ()
            )

        return cls(
            seq=data["seq"],
            event_id=data["event_id"],
            kind=data["kind"],
            label=data["label"],
            page_id=data["page_id"],
            at_ms=data["at_ms"],
            removed=_pairs(data.get("removed")),
            added=_pairs(data.get("added")),
            meta=data.get("meta"),
        )


class EventLog:
    """An append-only sequence of :class:`DocumentEvent`."""

    def __init__(self) -> None:
        self._events: list[DocumentEvent] = []

    def __len__(self) -> int:
        return len(self._events)

    @property
    def events(self) -> tuple[DocumentEvent, ...]:
        return tuple(self._events)

    @property
    def head_seq(self) -> int:
        """Sequence number of the last event, or -1 when empty."""
        return self._events[-1].seq if self._events else -1

    def record(
        self,
        *,
        kind: str,
        label: str,
        page_id: str,
        removed: Iterable[tuple[str, Stroke]] = (),
        added: Iterable[tuple[str, Stroke]] = (),
        meta: Optional[dict[str, Any]] = None,
        at_ms: Optional[int] = None,
    ) -> DocumentEvent:
        event = DocumentEvent(
            seq=len(self._events),
            event_id=new_id("evt"),
            kind=kind,
            label=label,
            page_id=page_id,
            at_ms=at_ms if at_ms is not None else _now_ms(),
            removed=tuple(removed),
            added=tuple(added),
            meta=meta,
        )
        self._events.append(event)
        return event

    def current_groups(self) -> dict[str, dict[str, Any]]:
        """Fold group/ungroup events into current group membership.

        Groups live only in the log -- they are relations over strokes, not
        stroke content -- so current membership is reconstructed by replaying
        the group and ungroup events in order.
        """
        groups: dict[str, dict[str, Any]] = {}
        for event in self._events:
            if event.kind != "group" or not event.meta:
                continue
            group_id = event.meta.get("group_id")
            if group_id is None:
                continue
            if event.meta.get("ungroup"):
                groups.pop(group_id, None)
            else:
                groups[group_id] = {
                    "group_id": group_id,
                    "member_ids": list(event.meta.get("member_ids", [])),
                    "label": event.meta.get("label"),
                }
        return groups

    def for_stroke(self, stroke_id: str) -> list[DocumentEvent]:
        """Every event that added or removed the given stroke, in order."""
        return [event for event in self._events if event.touches(stroke_id)]

    def replay(self, to_seq: Optional[int] = None) -> dict[str, tuple[str, Stroke]]:
        """Reconstruct the live strokes as of ``to_seq`` (inclusive).

        Returns a mapping ``stroke_id -> (layer_id, stroke)``. ``to_seq=None``
        replays the whole log. Because every event carries its exact removed and
        added snapshots, this rebuilds any past state -- including strokes that
        were later erased -- without touching the current document.
        """
        live: dict[str, tuple[str, Stroke]] = {}
        for event in self._events:
            if to_seq is not None and event.seq > to_seq:
                break
            for _, stroke in event.removed:
                live.pop(stroke.id, None)
            for layer_id, stroke in event.added:
                live[stroke.id] = (layer_id, stroke)
        return live

    def snapshot(self, stroke_id: str, at_seq: Optional[int] = None) -> Optional[Stroke]:
        """The stroke's state as of ``at_seq``, or None if it was not live then."""
        entry = self.replay(at_seq).get(stroke_id)
        return entry[1] if entry is not None else None

    def diff(self, from_seq: int, to_seq: Optional[int] = None) -> dict[str, Any]:
        """Net change between two sequence points: added, removed, changed ids."""
        before = self.replay(from_seq)
        after = self.replay(to_seq)
        added = sorted(set(after) - set(before))
        removed = sorted(set(before) - set(after))
        changed = sorted(
            stroke_id for stroke_id in set(before) & set(after)
            if before[stroke_id][1] != after[stroke_id][1]
        )
        return {
            "from_seq": from_seq,
            "to_seq": to_seq if to_seq is not None else self.head_seq,
            "added_ids": added,
            "removed_ids": removed,
            "changed_ids": changed,
        }

    def recover(self, stroke_id: str) -> Optional[Stroke]:
        """The last known snapshot of a stroke that is no longer live.

        Returns None if the stroke is still live or was never seen. This is how
        "restore what I erased" reads the erased ink back out of the log.
        """
        last: Optional[Stroke] = None
        live = False
        for event in self._events:
            for _, stroke in event.removed:
                if stroke.id == stroke_id:
                    last, live = stroke, False
            for _, stroke in event.added:
                if stroke.id == stroke_id:
                    last, live = stroke, True
        return None if live else last

    def to_dict(self) -> dict[str, Any]:
        """Compact, model-facing view of the log (ids only)."""
        return {
            "schema": EVENTLOG_VERSION,
            "event_count": len(self._events),
            "head_seq": self.head_seq,
            "events": [event.to_dict() for event in self._events],
        }

    def to_snapshot(self) -> dict[str, Any]:
        """Full, round-trippable serialization for persistence across saves."""
        return {
            "schema": EVENTLOG_VERSION,
            "event_count": len(self._events),
            "events": [event.to_snapshot() for event in self._events],
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> "EventLog":
        log = cls()
        log._events = [
            DocumentEvent.from_snapshot(event) for event in data.get("events", [])
        ]
        return log


__all__ = [
    "EVENTLOG_VERSION",
    "EVENT_KINDS",
    "DocumentEvent",
    "EventLog",
    "kind_for_label",
]
