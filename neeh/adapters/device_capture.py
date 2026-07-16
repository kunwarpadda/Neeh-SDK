"""Import device-capture research data into Neeh's existing session model.

``neeh-device-capture/v1`` is an experimental, lossless event stream.  It is
deliberately separate from the normal ``.tink`` document: the latter is a
final rendered snapshot and cannot recover raw timing or erased ink.

The importer keeps the original JSON on :class:`ImportedDeviceCapture` while
deriving a normal :class:`~neeh.canvas.Canvas`.  Consequently Android's raw
tilt/orientation values remain available even though Neeh's core ``Point``
stores the equivalent two-axis tilt representation.
"""
from __future__ import annotations

import copy
import json
import math
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

from neeh.canvas import Canvas, EventLog
from neeh.document import Document, Layer, Page
from neeh.ink import Author, Brush, Point, Stroke, StrokeStyle

DEVICE_CAPTURE_VERSION = "neeh-device-capture/v1"

_EVENT_KINDS = {
    "page_create", "page_delete", "page_change",
    "stroke_begin", "stroke_sample", "stroke_end", "stroke_delete",
    "stroke_transform", "stroke_restyle", "undo", "redo", "group", "ungroup",
}
_MUTATION_KINDS = {
    "stroke_delete", "stroke_transform", "stroke_restyle", "undo", "redo",
}
_DELETE_REASONS = {"eraser", "scratch_erase", "page_delete", "other"}
_HEX_RGB = re.compile(r"#[0-9a-fA-F]{6}\Z")
_HEX_ARGB = re.compile(r"#[0-9a-fA-F]{8}\Z")
_MAX_I64 = 2**63 - 1


class DeviceCaptureError(ValueError):
    """A malformed or internally inconsistent device capture."""


@dataclass(frozen=True)
class ImportedDeviceCapture:
    """A reconstructed Neeh session plus its untouched raw capture payload."""

    canvas: Canvas
    capture: dict[str, Any]

    @property
    def document(self) -> Document:
        return self.canvas.document

    @property
    def event_log(self) -> EventLog:
        return self.canvas.events


def _fail(path: str, message: str) -> None:
    raise DeviceCaptureError(f"{path}: {message}")


def _object(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        _fail(path, "must be an object")
    return value


def _array(value: Any, path: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    return value


def _required(obj: Mapping[str, Any], names: Sequence[str], path: str) -> None:
    missing = [name for name in names if name not in obj]
    if missing:
        _fail(path, f"missing required field(s): {', '.join(missing)}")


def _string(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(path, "must be a non-empty string")
    return value


def _integer(value: Any, path: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        _fail(path, "must be an integer")
    if not minimum <= value <= _MAX_I64:
        _fail(path, f"must be in [{minimum}, {_MAX_I64}]")
    return value


def _number(
    value: Any,
    path: str,
    *,
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail(path, "must be a finite number")
    result = float(value)
    if minimum is not None and result < minimum:
        _fail(path, f"must be >= {minimum}")
    if maximum is not None and result > maximum:
        _fail(path, f"must be <= {maximum}")
    return result


def _boolean(value: Any, path: str) -> bool:
    if not isinstance(value, bool):
        _fail(path, "must be a boolean")
    return value


def _validate_style(value: Any, path: str) -> None:
    style = _object(value, path)
    _required(style, ("width",), path)
    _number(style["width"], f"{path}.width", minimum=1e-12)
    color = style.get("color")
    argb = style.get("color_argb")
    if color is None and argb is None:
        _fail(path, "needs color (#RRGGBB) or color_argb (#AARRGGBB)")
    if color is not None and (not isinstance(color, str) or not _HEX_RGB.fullmatch(color)):
        _fail(f"{path}.color", "must be #RRGGBB")
    if argb is not None and (not isinstance(argb, str) or not _HEX_ARGB.fullmatch(argb)):
        _fail(f"{path}.color_argb", "must be #AARRGGBB")
    if "opacity" in style:
        _number(style["opacity"], f"{path}.opacity", minimum=0.0, maximum=1.0)
        if style["opacity"] == 0:
            _fail(f"{path}.opacity", "must be greater than zero")
    if "brush" in style:
        if style["brush"] not in {brush.value for brush in Brush}:
            _fail(f"{path}.brush", "must be pen, marker, or highlighter")


def _validate_point(value: Any, path: str) -> None:
    point = _object(value, path)
    _required(point, ("x", "y", "t_ms"), path)
    _number(point["x"], f"{path}.x")
    _number(point["y"], f"{path}.y")
    _integer(point["t_ms"], f"{path}.t_ms")
    if "pressure" in point:
        _number(point["pressure"], f"{path}.pressure", minimum=0.0, maximum=1.0)
    if "tilt_rad" in point:
        _number(point["tilt_rad"], f"{path}.tilt_rad", minimum=0.0, maximum=math.pi / 2)
    if "orientation_rad" in point:
        _number(
            point["orientation_rad"], f"{path}.orientation_rad",
            minimum=-2 * math.pi, maximum=2 * math.pi,
        )
    if "event_time_ms" in point:
        _integer(point["event_time_ms"], f"{path}.event_time_ms")
    if "action" in point:
        action = point["action"]
        if isinstance(action, bool) or not isinstance(action, (str, int)):
            _fail(f"{path}.action", "must be an Android action integer or normalized string")


def _validate_snapshot(value: Any, path: str) -> None:
    stroke = _object(value, path)
    _required(
        stroke,
        ("stroke_id", "layer_id", "author", "tool", "style", "created_at_ms", "points"),
        path,
    )
    _string(stroke["stroke_id"], f"{path}.stroke_id")
    _string(stroke["layer_id"], f"{path}.layer_id")
    if stroke["author"] not in ("user", "agent", "app"):
        _fail(f"{path}.author", "must be user, agent, or app")
    _string(stroke["tool"], f"{path}.tool")
    _validate_style(stroke["style"], f"{path}.style")
    _integer(stroke["created_at_ms"], f"{path}.created_at_ms")
    points = _array(stroke["points"], f"{path}.points")
    if not points:
        _fail(f"{path}.points", "must contain at least one point")
    if len(points) > 20_000:
        _fail(f"{path}.points", "exceeds the 20,000 point SDK limit")
    previous = -1
    for index, point in enumerate(points):
        point_path = f"{path}.points[{index}]"
        _validate_point(point, point_path)
        t_ms = point["t_ms"]
        if t_ms < previous:
            _fail(point_path, "t_ms must be non-decreasing within a stroke")
        previous = t_ms


def _validate_page(value: Any, path: str) -> None:
    page = _object(value, path)
    _required(page, ("id", "index", "width", "height"), path)
    _string(page["id"], f"{path}.id")
    _integer(page["index"], f"{path}.index")
    _number(page["width"], f"{path}.width", minimum=1e-12)
    _number(page["height"], f"{path}.height", minimum=1e-12)
    if "background" in page:
        background = page["background"]
        if not isinstance(background, str) or not _HEX_RGB.fullmatch(background):
            _fail(f"{path}.background", "must be #RRGGBB")


def validate_device_capture(payload: Any) -> None:
    """Validate a ``neeh-device-capture/v1`` payload without dependencies.

    Unknown fields are ignored for forward-compatible additive metadata.
    Known fields and event state transitions are checked strictly.
    """
    root = _object(payload, "$")
    _required(root, ("schema", "session", "device", "app", "coordinate_space", "pages", "events"), "$")
    if root["schema"] != DEVICE_CAPTURE_VERSION:
        _fail("$.schema", f"expected {DEVICE_CAPTURE_VERSION!r}")

    session = _object(root["session"], "$.session")
    _required(session, ("id", "started_at_ms"), "$.session")
    _string(session["id"], "$.session.id")
    started_at_ms = _integer(session["started_at_ms"], "$.session.started_at_ms")
    if "name" in session:
        _string(session["name"], "$.session.name")
    if "ended_at_ms" in session:
        ended = _integer(session["ended_at_ms"], "$.session.ended_at_ms")
        if ended < started_at_ms:
            _fail("$.session.ended_at_ms", "must not precede started_at_ms")

    device = _object(root["device"], "$.device")
    _required(
        device,
        ("model", "android_version", "pressure_available", "tilt_available", "orientation_available"),
        "$.device",
    )
    _string(device["model"], "$.device.model")
    _string(device["android_version"], "$.device.android_version")
    for name in ("pressure_available", "tilt_available", "orientation_available"):
        _boolean(device[name], f"$.device.{name}")
    if "sdk_int" in device:
        _integer(device["sdk_int"], "$.device.sdk_int")

    app = _object(root["app"], "$.app")
    _required(app, ("name", "package_name", "version_name"), "$.app")
    for name in ("name", "package_name", "version_name"):
        _string(app[name], f"$.app.{name}")
    if "version_code" in app:
        _integer(app["version_code"], "$.app.version_code")

    coordinates = _object(root["coordinate_space"], "$.coordinate_space")
    _required(coordinates, ("unit", "origin"), "$.coordinate_space")
    if coordinates["unit"] != "px" or coordinates["origin"] != "top-left":
        _fail("$.coordinate_space", "v1 requires unit='px' and origin='top-left'")

    pages = _array(root["pages"], "$.pages")
    if not pages:
        _fail("$.pages", "must describe at least one page")
    page_ids: set[str] = set()
    page_indices: set[int] = set()
    page_by_id: dict[str, Mapping[str, Any]] = {}
    for index, page_value in enumerate(pages):
        path = f"$.pages[{index}]"
        _validate_page(page_value, path)
        page = page_value
        if page["id"] in page_ids:
            _fail(f"{path}.id", "duplicate page id")
        if page["index"] in page_indices:
            _fail(f"{path}.index", "duplicate page index")
        page_ids.add(page["id"])
        page_indices.add(page["index"])
        page_by_id[page["id"]] = page

    events = _array(root["events"], "$.events")
    active: dict[str, dict[str, Any]] = {}
    begun: set[str] = set()
    event_ids: set[str] = set()
    previous_event_t = -1
    for index, event_value in enumerate(events):
        path = f"$.events[{index}]"
        event = _object(event_value, path)
        _required(event, ("seq", "event_id", "kind", "t_ms", "page_id"), path)
        seq = _integer(event["seq"], f"{path}.seq")
        if seq != index:
            _fail(f"{path}.seq", f"must be contiguous and equal to {index}")
        event_id = _string(event["event_id"], f"{path}.event_id")
        if event_id in event_ids:
            _fail(f"{path}.event_id", "duplicate event id")
        event_ids.add(event_id)
        kind = event["kind"]
        if kind not in _EVENT_KINDS:
            _fail(f"{path}.kind", f"unsupported event kind {kind!r}")
        t_ms = _integer(event["t_ms"], f"{path}.t_ms")
        if started_at_ms + t_ms > _MAX_I64:
            _fail(f"{path}.t_ms", "overflows epoch milliseconds when added to session start")
        if t_ms < previous_event_t:
            _fail(f"{path}.t_ms", "event offsets must be non-decreasing")
        previous_event_t = t_ms
        page_id = _string(event["page_id"], f"{path}.page_id")
        if page_id not in page_ids:
            _fail(f"{path}.page_id", "does not appear in top-level pages")

        if kind == "stroke_begin":
            _required(event, ("stroke_id", "layer_id", "author", "tool", "style", "created_at_ms"), path)
            stroke_id = _string(event["stroke_id"], f"{path}.stroke_id")
            if stroke_id in begun:
                _fail(f"{path}.stroke_id", "a stable stroke id may begin only once")
            if event["author"] not in ("user", "agent", "app"):
                _fail(f"{path}.author", "must be user, agent, or app")
            _string(event["layer_id"], f"{path}.layer_id")
            _string(event["tool"], f"{path}.tool")
            _validate_style(event["style"], f"{path}.style")
            _integer(event["created_at_ms"], f"{path}.created_at_ms")
            active[stroke_id] = {"page_id": page_id, "sample_count": 0, "last_t": -1}
            begun.add(stroke_id)
        elif kind == "stroke_sample":
            _required(event, ("stroke_id", "point"), path)
            stroke_id = _string(event["stroke_id"], f"{path}.stroke_id")
            if stroke_id not in active:
                _fail(f"{path}.stroke_id", "sample has no active stroke_begin")
            if active[stroke_id]["page_id"] != page_id:
                _fail(f"{path}.page_id", "sample page differs from stroke_begin")
            _validate_point(event["point"], f"{path}.point")
            point_t = event["point"]["t_ms"]
            if point_t < active[stroke_id]["last_t"]:
                _fail(f"{path}.point.t_ms", "must be non-decreasing within a stroke")
            active[stroke_id]["last_t"] = point_t
            active[stroke_id]["sample_count"] += 1
        elif kind == "stroke_end":
            _required(event, ("stroke_id",), path)
            stroke_id = _string(event["stroke_id"], f"{path}.stroke_id")
            if stroke_id not in active:
                _fail(f"{path}.stroke_id", "end has no active stroke_begin")
            if active[stroke_id]["page_id"] != page_id:
                _fail(f"{path}.page_id", "end page differs from stroke_begin")
            cancelled = event.get("cancelled", False)
            _boolean(cancelled, f"{path}.cancelled")
            if not cancelled and active[stroke_id]["sample_count"] == 0:
                _fail(path, "a completed stroke needs at least one stroke_sample")
            del active[stroke_id]
        elif kind in _MUTATION_KINDS:
            _required(event, ("removed", "added"), path)
            removed = _array(event["removed"], f"{path}.removed")
            added = _array(event["added"], f"{path}.added")
            for side, snapshots in (("removed", removed), ("added", added)):
                for item_index, snapshot in enumerate(snapshots):
                    _validate_snapshot(snapshot, f"{path}.{side}[{item_index}]")
            if kind == "stroke_delete":
                _required(event, ("reason",), path)
                if event["reason"] not in _DELETE_REASONS:
                    _fail(f"{path}.reason", f"must be one of {sorted(_DELETE_REASONS)}")
                if not removed or added:
                    _fail(path, "stroke_delete requires non-empty removed and empty added")
        elif kind in ("page_create", "page_delete"):
            if "page" in event:
                _validate_page(event["page"], f"{path}.page")
                if event["page"]["id"] != page_id:
                    _fail(f"{path}.page.id", "must match event page_id")
                descriptor = page_by_id[page_id]
                for field in ("index", "width", "height"):
                    if event["page"][field] != descriptor[field]:
                        _fail(f"{path}.page.{field}", "must match the top-level page descriptor")
            if kind == "page_create" and "page" not in event:
                _fail(path, "page_create requires a page descriptor")
            if kind == "page_delete":
                _required(event, ("removed", "added"), path)
                for side in ("removed", "added"):
                    values = _array(event[side], f"{path}.{side}")
                    for item_index, snapshot in enumerate(values):
                        _validate_snapshot(snapshot, f"{path}.{side}[{item_index}]")
                if event["added"]:
                    _fail(f"{path}.added", "page_delete cannot add strokes")
        elif kind == "page_change":
            _required(event, ("from_page_id", "to_page_id"), path)
            if event["from_page_id"] not in page_ids or event["to_page_id"] not in page_ids:
                _fail(path, "page_change references an unknown page")
            if event["to_page_id"] != page_id:
                _fail(f"{path}.page_id", "must equal to_page_id")
        elif kind in ("group", "ungroup"):
            _required(event, ("group_id", "stroke_ids"), path)
            _string(event["group_id"], f"{path}.group_id")
            stroke_ids = _array(event["stroke_ids"], f"{path}.stroke_ids")
            for item_index, stroke_id in enumerate(stroke_ids):
                _string(stroke_id, f"{path}.stroke_ids[{item_index}]")

    if active:
        _fail("$.events", f"unterminated strokes: {sorted(active)}")


def _style(value: Mapping[str, Any], tool: str) -> StrokeStyle:
    argb = value.get("color_argb")
    if argb is not None:
        alpha = int(argb[1:3], 16) / 255.0
        color = f"#{argb[3:]}"
    else:
        alpha = 1.0
        color = value["color"]
    opacity = float(value.get("opacity", alpha))
    # Fully transparent Android colors cannot be represented by StrokeStyle;
    # validation permits raw alpha=00, so retain a tiny positive display value
    # while the untouched ARGB remains in ImportedDeviceCapture.capture.
    opacity = max(opacity, 1 / 255)
    brush_name = value.get("brush")
    if brush_name is None:
        brush_name = "marker" if tool == "marker" else "pen"
    return StrokeStyle(
        color=color,
        width=float(value["width"]),
        brush=Brush(brush_name),
        opacity=opacity,
    )


def _author(value: str) -> Author:
    return Author.USER if value == "user" else Author.AGENT


def _tilt_axes(point: Mapping[str, Any]) -> tuple[float, float]:
    """Project Android scalar tilt/orientation into Neeh/W3C tilt axes."""
    tilt = float(point.get("tilt_rad", 0.0))
    orientation = float(point.get("orientation_rad", 0.0))
    tangent = math.tan(tilt)
    # Android orientation is measured from the +x axis.  Project the scalar
    # tilt onto x/y before converting each component to W3C/Neeh tilt degrees.
    tilt_x = math.degrees(math.atan(tangent * math.cos(orientation)))
    tilt_y = math.degrees(math.atan(tangent * math.sin(orientation)))
    return tilt_x, tilt_y


def _point(value: Mapping[str, Any]) -> Point:
    tilt_x, tilt_y = _tilt_axes(value)
    return Point(
        x=float(value["x"]),
        y=float(value["y"]),
        t_ms=value["t_ms"],
        pressure=float(value.get("pressure", 1.0)),
        tilt_x=tilt_x,
        tilt_y=tilt_y,
    )


def _stroke_from_snapshot(value: Mapping[str, Any]) -> Stroke:
    return Stroke(
        id=value["stroke_id"],
        author=_author(value["author"]),
        created_at_ms=value["created_at_ms"],
        style=_style(value["style"], value["tool"]),
        points=tuple(_point(point) for point in value["points"]),
    )


def _page(value: Mapping[str, Any]) -> Page:
    return Page(
        id=value["id"],
        width=float(value["width"]),
        height=float(value["height"]),
        background=value.get("background", "#ffffff"),
        layers=[],
    )


def _ensure_layer(page: Page, layer_id: str, author: Author) -> Layer:
    layer = page.layer(layer_id)
    if layer is None:
        layer = Layer(
            id=layer_id,
            name="agent" if author is Author.AGENT else "ink",
            author=author,
        )
        page.layers.append(layer)
    return layer


def _snapshot_pairs(values: Sequence[Mapping[str, Any]]) -> list[tuple[str, Stroke]]:
    return [(value["layer_id"], _stroke_from_snapshot(value)) for value in values]


def _remove(page: Page, layer_id: str, expected: Stroke) -> None:
    layer = page.layer(layer_id)
    current = None if layer is None else layer.get(expected.id)
    if current is None:
        raise DeviceCaptureError(
            f"cannot remove stroke {expected.id!r}: it is not live on page {page.id!r}"
        )
    if current != expected:
        raise DeviceCaptureError(
            f"removed snapshot for stroke {expected.id!r} does not match its live state"
        )
    layer.strokes.remove(current)


def _apply_delta(
    page: Page,
    removed: Sequence[tuple[str, Stroke]],
    added: Sequence[tuple[str, Stroke]],
) -> None:
    for layer_id, stroke in removed:
        _remove(page, layer_id, stroke)
    for layer_id, stroke in added:
        if page.find(stroke.id) is not None:
            raise DeviceCaptureError(f"cannot add already-live stroke {stroke.id!r}")
        _ensure_layer(page, layer_id, stroke.author).strokes.append(stroke)


def import_device_capture(payload: Mapping[str, Any]) -> ImportedDeviceCapture:
    """Validate and reconstruct a device capture as a Canvas + EventLog."""
    validate_device_capture(payload)
    raw = copy.deepcopy(dict(payload))
    session = raw["session"]
    descriptors = {page["id"]: page for page in raw["pages"]}
    created_ids = {
        event["page_id"] for event in raw["events"] if event["kind"] == "page_create"
    }
    initial = [page for page in raw["pages"] if page["id"] not in created_ids]
    initial.sort(key=lambda page: page["index"])
    document = Document(
        id=session.get("document_id", session["id"]),
        title=session.get("name", f"Device capture {session['id']}"),
        created_at_ms=session["started_at_ms"],
        pages=[_page(page) for page in initial],
    )
    canvas = Canvas(document)
    active: dict[str, dict[str, Any]] = {}
    log_events: list[dict[str, Any]] = []
    active_page_id = document.pages[0].id if document.pages else None

    def page_for(page_id: str) -> Page:
        page = document.page(page_id)
        if page is None:
            raise DeviceCaptureError(f"event references page {page_id!r} before creation/after deletion")
        return page

    def append_log(
        event: Mapping[str, Any], *, kind: str, label: str,
        removed: Sequence[tuple[str, Stroke]] = (),
        added: Sequence[tuple[str, Stroke]] = (),
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        log_events.append({
            "seq": len(log_events),
            "event_id": event["event_id"],
            "kind": kind,
            "label": label,
            "page_id": event["page_id"],
            "at_ms": session["started_at_ms"] + event["t_ms"],
            "removed": [
                {"layer_id": layer_id, "stroke": stroke.to_dict()}
                for layer_id, stroke in removed
            ],
            "added": [
                {"layer_id": layer_id, "stroke": stroke.to_dict()}
                for layer_id, stroke in added
            ],
            "meta": meta,
        })

    for event in raw["events"]:
        kind = event["kind"]
        if kind == "page_create":
            descriptor = event.get("page", descriptors[event["page_id"]])
            if document.page(event["page_id"]) is not None:
                raise DeviceCaptureError(f"page {event['page_id']!r} was created twice")
            document.pages.append(_page(descriptor))
            append_log(event, kind="page", label=kind, meta={"capture_kind": kind, "page": descriptor})
        elif kind == "page_delete":
            page = page_for(event["page_id"])
            removed = _snapshot_pairs(event["removed"])
            added = _snapshot_pairs(event["added"])
            _apply_delta(page, removed, added)
            if page.all_strokes():
                raise DeviceCaptureError(
                    f"page_delete for {page.id!r} omitted live stroke snapshots"
                )
            append_log(
                event, kind="page", label=kind, removed=removed, added=added,
                meta={"capture_kind": kind, "page": event.get("page", descriptors[event["page_id"]])},
            )
            document.pages.remove(page)
            if active_page_id == page.id:
                active_page_id = document.pages[0].id if document.pages else None
        elif kind == "page_change":
            page_for(event["to_page_id"])
            active_page_id = event["to_page_id"]
            append_log(
                event, kind="page", label=kind,
                meta={
                    "capture_kind": kind,
                    "from_page_id": event["from_page_id"],
                    "to_page_id": event["to_page_id"],
                },
            )
        elif kind == "stroke_begin":
            active[event["stroke_id"]] = {"begin": event, "points": []}
        elif kind == "stroke_sample":
            active[event["stroke_id"]]["points"].append(event["point"])
        elif kind == "stroke_end":
            state = active.pop(event["stroke_id"])
            if event.get("cancelled", False):
                continue
            begin = state["begin"]
            stroke = Stroke(
                id=begin["stroke_id"],
                author=_author(begin["author"]),
                created_at_ms=begin["created_at_ms"],
                style=_style(begin["style"], begin["tool"]),
                points=tuple(_point(point) for point in state["points"]),
            )
            page = page_for(event["page_id"])
            layer = _ensure_layer(page, begin["layer_id"], stroke.author)
            _apply_delta(page, (), ((layer.id, stroke),))
            append_log(
                event,
                kind="add",
                label="device_stroke",
                added=((layer.id, stroke),),
                meta={
                    "capture_kind": kind,
                    "begin_event_id": begin["event_id"],
                    "capture_seq_range": [begin["seq"], event["seq"]],
                    "tool": begin["tool"],
                },
            )
        elif kind in _MUTATION_KINDS:
            page = page_for(event["page_id"])
            removed = _snapshot_pairs(event["removed"])
            added = _snapshot_pairs(event["added"])
            _apply_delta(page, removed, added)
            mapped_kind = {
                "stroke_delete": "erase",
                "stroke_transform": "move",
                "stroke_restyle": "restyle",
                "undo": "undo",
                "redo": "redo",
            }[kind]
            meta = {"capture_kind": kind}
            for name in ("reason", "target_event_id"):
                if name in event:
                    meta[name] = event[name]
            append_log(
                event, kind=mapped_kind, label=kind,
                removed=removed, added=added, meta=meta,
            )
        elif kind in ("group", "ungroup"):
            meta = {
                "capture_kind": kind,
                "group_id": event["group_id"],
                "member_ids": list(event["stroke_ids"]),
            }
            if kind == "ungroup":
                meta["ungroup"] = True
            append_log(event, kind="group", label=kind, meta=meta)

    document.pages.sort(key=lambda page: descriptors[page.id]["index"])
    if document.pages:
        selected = document.page(active_page_id) if active_page_id is not None else None
        canvas._page_index = document.pages.index(selected) if selected is not None else 0
    canvas.history.log = EventLog.from_snapshot({
        "schema": "ink-eventlog/v1",
        "event_count": len(log_events),
        "events": log_events,
    })
    return ImportedDeviceCapture(canvas=canvas, capture=raw)


def _select_events_path(directory: Path) -> Path:
    exact = directory / "session.events.json"
    if exact.is_file():
        return exact
    candidates = sorted(directory.rglob("*.events.json"))
    if len(candidates) != 1:
        raise DeviceCaptureError(
            f"{directory}: expected session.events.json or exactly one *.events.json"
        )
    return candidates[0]


def _select_archive_member(names: Sequence[str]) -> str:
    files = [name for name in names if not name.endswith("/")]
    required = {"session.tink", "session.events.json"}
    if len(files) != 2 or set(files) != required:
        raise DeviceCaptureError(
            "capture archive must contain exactly session.tink and "
            "session.events.json at its root"
        )
    return "session.events.json"


def load_device_capture(path: Union[str, Path]) -> ImportedDeviceCapture:
    """Load a JSON sidecar, export directory, or ZIP research bundle."""
    source = Path(path)
    try:
        if source.is_dir():
            text = _select_events_path(source).read_text(encoding="utf-8")
        elif zipfile.is_zipfile(source):
            with zipfile.ZipFile(source) as archive:
                member = _select_archive_member(archive.namelist())
                text = archive.read(member).decode("utf-8")
        else:
            text = source.read_text(encoding="utf-8")
        payload = json.loads(text)
    except DeviceCaptureError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        raise DeviceCaptureError(f"could not read device capture {source}: {exc}") from exc
    return import_device_capture(payload)


def convert_device_capture(
    source: Union[str, Path], destination: Union[str, Path]
) -> ImportedDeviceCapture:
    """Import a capture and write a complete ``neeh-session/v1`` snapshot."""
    imported = load_device_capture(source)
    imported.canvas.save_session(destination)
    return imported


# --------------------------------------------------------------------------- #
# Stitching sequential captures of the same notebook into one continuous
# session. The device recorder has no way to resume a prior session:
# every capture start re-derives whatever ink is already on the page and
# re-records it as fresh "preexisting" strokes, then finalizes as its own
# self-contained bundle on stop/export. Rather than teach the recorder to
# resume (new native JSON-parsing surface in the hot capture path), each
# recording sitting can be exported as its own small bundle and stitched here:
# bundle N+1's leading "preexisting" strokes are verified against bundle N's
# final live ink and dropped, and only genuinely new events are spliced on.
# --------------------------------------------------------------------------- #
_BBOX_TOLERANCE_PX = 6.0


def _page_live_state(payload: Mapping[str, Any]) -> list[list[tuple[str, tuple[float, float, float, float]]]]:
    """Per page (in page-index order), each live stroke's (id, bbox), in order."""
    imported = import_device_capture(payload)
    out: list[list[tuple[str, tuple[float, float, float, float]]]] = []
    for page in imported.document.pages:
        entries = []
        for stroke in page.all_strokes():
            box = stroke.bbox
            entries.append((stroke.id, (box.min_x, box.min_y, box.max_x, box.max_y)))
        out.append(entries)
    return out


def _bbox_close(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return all(abs(x - y) <= _BBOX_TOLERANCE_PX for x, y in zip(a, b))


def _leading_preexisting_run(events: Sequence[Mapping[str, Any]]) -> int:
    """Index just past the initial preexisting-stroke seed, 0 if there is none.

    Seeding emits one contiguous stroke_begin/stroke_sample*/stroke_end triple
    per pre-existing stroke, across all pages, before any real capture event.
    """
    i = 0
    n = len(events)
    while i < n and events[i]["kind"] == "stroke_begin" and events[i].get("tool") == "preexisting":
        stroke_id = events[i]["stroke_id"]
        i += 1
        while i < n and events[i]["kind"] == "stroke_sample" and events[i]["stroke_id"] == stroke_id:
            i += 1
        if i >= n or events[i]["kind"] != "stroke_end" or events[i]["stroke_id"] != stroke_id:
            raise DeviceCaptureError(
                f"malformed preexisting seed for stroke {stroke_id!r}: missing stroke_end"
            )
        i += 1
    return i


def _extract_snapshots(events: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """stroke_id -> full snapshot, rebuilt from this event list's own
    stroke_begin/stroke_sample/stroke_end triples (ignores other kinds)."""
    snapshots: dict[str, dict[str, Any]] = {}
    begins: dict[str, Mapping[str, Any]] = {}
    points: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        kind = event["kind"]
        stroke_id = event.get("stroke_id")
        if kind == "stroke_begin":
            begins[stroke_id] = event
            points[stroke_id] = []
        elif kind == "stroke_sample" and stroke_id in points:
            points[stroke_id].append(event["point"])
        elif kind == "stroke_end" and stroke_id in begins:
            begin = begins.pop(stroke_id)
            snapshots[stroke_id] = {
                "stroke_id": stroke_id,
                "layer_id": begin["layer_id"],
                "author": begin["author"],
                "tool": begin["tool"],
                "style": begin["style"],
                "created_at_ms": begin["created_at_ms"],
                "points": points.pop(stroke_id),
            }
    return snapshots


def _remap_snapshot(
    snapshot: Mapping[str, Any],
    stroke_id_map: dict[str, str],
    canonical_snapshot: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    canonical_id = stroke_id_map.get(snapshot["stroke_id"], snapshot["stroke_id"])
    if canonical_id in canonical_snapshot:
        # A carried-over stroke: this bundle's own copy is a reseed
        # reconstruction (or a stale local snapshot), not the true original
        # geometry, and downstream replay requires an exact match against
        # whatever is actually live -- so substitute the real snapshot.
        return dict(canonical_snapshot[canonical_id])
    remapped = dict(snapshot)
    remapped["stroke_id"] = canonical_id
    return remapped


def _remap_event(
    event: Mapping[str, Any],
    *,
    bundle_index: int,
    page_id_map: dict[str, str],
    stroke_id_map: dict[str, str],
    event_id_map: dict[str, str],
    canonical_snapshot: Mapping[str, Mapping[str, Any]],
    t_ms: int,
    seq: int,
) -> dict[str, Any]:
    remapped = dict(event)
    remapped["seq"] = seq
    remapped["t_ms"] = t_ms
    remapped["page_id"] = page_id_map[event["page_id"]]
    original_event_id = event["event_id"]
    new_event_id = f"b{bundle_index}:{original_event_id}"
    event_id_map[original_event_id] = new_event_id
    remapped["event_id"] = new_event_id

    for field in ("stroke_id",):
        if field in remapped:
            remapped[field] = stroke_id_map.get(remapped[field], remapped[field])
    for side in ("removed", "added"):
        if side in remapped:
            remapped[side] = [
                _remap_snapshot(s, stroke_id_map, canonical_snapshot) for s in remapped[side]
            ]
    if "stroke_ids" in remapped:
        remapped["stroke_ids"] = [
            stroke_id_map.get(sid, sid) for sid in remapped["stroke_ids"]
        ]
    if "group_id" in remapped:
        remapped["group_id"] = f"b{bundle_index}:{remapped['group_id']}"
    if "target_event_id" in remapped:
        remapped["target_event_id"] = event_id_map.get(
            remapped["target_event_id"], remapped["target_event_id"]
        )
    if "from_page_id" in remapped:
        remapped["from_page_id"] = page_id_map[remapped["from_page_id"]]
    if "to_page_id" in remapped:
        remapped["to_page_id"] = page_id_map[remapped["to_page_id"]]
    if "page" in remapped and isinstance(remapped["page"], dict):
        page = dict(remapped["page"])
        page["id"] = page_id_map.get(page["id"], f"b{bundle_index}:{page['id']}")
        remapped["page"] = page
    return remapped


def stitch_device_captures(payloads: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Merge sequential ``neeh-device-capture/v1`` bundles of one notebook.

    ``payloads`` must be given in chronological recording order (typically one
    per stop/export cycle of the same notebook). Each is validated
    independently; bundle N+1's leading preexisting-stroke seed is checked
    against bundle N's own final live ink (matched by page order, stroke
    order, and bounding box within tolerance -- preexisting geometry is a
    lossy ribbon reconstruction, not a byte-identical copy) and dropped, and
    only genuinely new events are appended, with ids remapped to stay globally
    unique and timestamps rebased onto the first bundle's session start. The
    result is itself a valid ``neeh-device-capture/v1`` payload spanning the
    whole recording, as if capture had never been stopped.

    Raises :class:`DeviceCaptureError` if any bundle fails validation, if
    bundles are out of order, or if a bundle's preexisting seed does not match
    the prior bundle's final ink (a sign these captures are not, in fact,
    sequential recordings of the same notebook).
    """
    if not payloads:
        raise DeviceCaptureError("stitch_device_captures: no captures given")
    for payload in payloads:
        validate_device_capture(payload)
    if len(payloads) == 1:
        return copy.deepcopy(dict(payloads[0]))

    for prior, nxt in zip(payloads, payloads[1:]):
        if nxt["session"]["started_at_ms"] < prior["session"]["started_at_ms"]:
            raise DeviceCaptureError(
                "stitch_device_captures: payloads must be given in chronological order"
            )

    base = copy.deepcopy(dict(payloads[0]))
    base_started = base["session"]["started_at_ms"]
    base_pages = sorted(base["pages"], key=lambda p: p["index"])
    page_id_map: dict[str, str] = {page["id"]: page["id"] for page in base_pages}
    merged_events: list[dict[str, Any]] = list(base["events"])
    merged_pages: list[dict[str, Any]] = list(base_pages)
    # True original geometry for every canonical stroke id introduced so far,
    # used to correct any later removed/added snapshot of a carried-over
    # stroke (a bundle's own reseed copy is a lossy reconstruction).
    canonical_snapshot: dict[str, dict[str, Any]] = _extract_snapshots(base["events"])

    for bundle_index, payload in enumerate(payloads[1:], start=2):
        # The expected state is the *merged* stream's own live ink so far, in
        # canonical (base) ids -- not the immediately-prior bundle's own raw
        # ids, which may themselves have already been remapped once merged.
        running = {**base, "pages": merged_pages, "events": merged_events}
        prior_state = _page_live_state(running)
        events = payload["events"]
        seed_end = _leading_preexisting_run(events)
        seed_events = events[:seed_end]

        pages_sorted = sorted(payload["pages"], key=lambda p: p["index"])
        stroke_id_map: dict[str, str] = {}
        event_id_map: dict[str, str] = {}

        # Pair this bundle's preexisting seed, per page, against the prior
        # bundle's own final live state -- by order and bounding box, since
        # ids reset every session and the seed geometry is resampled. Bboxes
        # are computed straight from each seed stroke's own sample points, not
        # from this bundle's final state, so a later real erase of a
        # preexisting stroke (part of the continuation itself) cannot shift
        # what "claimed" means here.
        cursor = 0
        for page_index in range(len(pages_sorted)):
            expected = prior_state[page_index] if page_index < len(prior_state) else []
            claimed: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
            while cursor < len(seed_events) and len(claimed) < len(expected):
                begin = seed_events[cursor]
                if begin["page_id"] != pages_sorted[page_index]["id"]:
                    break
                cursor += 1
                points: list[dict[str, Any]] = []
                while (
                    cursor < len(seed_events)
                    and seed_events[cursor]["kind"] == "stroke_sample"
                    and seed_events[cursor]["stroke_id"] == begin["stroke_id"]
                ):
                    points.append(seed_events[cursor]["point"])
                    cursor += 1
                cursor += 1  # stroke_end
                claimed.append((begin, points))
            if len(claimed) != len(expected):
                raise DeviceCaptureError(
                    f"stitch_device_captures: bundle {bundle_index} preexisting seed for "
                    f"page {page_index} has {len(claimed)} strokes, expected {len(expected)} "
                    "from the prior bundle's final live ink"
                )
            for (expected_id, expected_box), (begin, points) in zip(expected, claimed):
                stroke_id_map[begin["stroke_id"]] = expected_id
                xs = [p["x"] for p in points]
                ys = [p["y"] for p in points]
                claimed_box = (min(xs), min(ys), max(xs), max(ys))
                if not _bbox_close(expected_box, claimed_box):
                    raise DeviceCaptureError(
                        f"stitch_device_captures: bundle {bundle_index} preexisting stroke on "
                        f"page {page_index} does not match the prior bundle's ink "
                        f"(bbox {claimed_box} vs {expected_box}); these may not be sequential "
                        "captures of the same notebook"
                    )

        # Map this bundle's page ids onto the canonical (base) page ids,
        # extending the canonical page list for genuinely new pages.
        for page_index, page in enumerate(pages_sorted):
            if page_index < len(base_pages):
                page_id_map[page["id"]] = base_pages[page_index]["id"]
            elif page["id"] not in page_id_map:
                new_id = f"b{bundle_index}:{page['id']}"
                page_id_map[page["id"]] = new_id
                new_page = dict(page)
                new_page["id"] = new_id
                merged_pages.append(new_page)

        real_events = events[seed_end:]
        session_started = payload["session"]["started_at_ms"]
        bundle_new_events: list[dict[str, Any]] = []
        for event in real_events:
            if event["kind"] == "stroke_begin" and event.get("tool") != "preexisting":
                stroke_id_map[event["stroke_id"]] = f"b{bundle_index}:{event['stroke_id']}"
            absolute_ms = session_started + event["t_ms"]
            remapped = _remap_event(
                event,
                bundle_index=bundle_index,
                page_id_map=page_id_map,
                stroke_id_map=stroke_id_map,
                event_id_map=event_id_map,
                canonical_snapshot=canonical_snapshot,
                t_ms=absolute_ms - base_started,
                seq=len(merged_events),
            )
            merged_events.append(remapped)
            bundle_new_events.append(remapped)
        # This bundle's own genuinely-new strokes become canonical for any
        # later bundle that carries them forward again.
        canonical_snapshot.update(_extract_snapshots(bundle_new_events))

    base["pages"] = merged_pages
    base["events"] = merged_events
    base["session"] = dict(base["session"])
    base["session"]["ended_at_ms"] = payloads[-1]["session"].get(
        "ended_at_ms", payloads[-1]["session"]["started_at_ms"]
    )
    validate_device_capture(base)
    return base


__all__ = [
    "DEVICE_CAPTURE_VERSION",
    "DeviceCaptureError",
    "ImportedDeviceCapture",
    "convert_device_capture",
    "import_device_capture",
    "load_device_capture",
    "stitch_device_captures",
    "validate_device_capture",
]
