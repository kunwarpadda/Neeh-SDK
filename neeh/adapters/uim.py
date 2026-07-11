"""Universal Ink Model (UIM) persistence: the Neeh profile of UIM 3.1.

This module defines how a Neeh `Document` maps onto one UIM 3.1 `InkModel`:

- pages and layers are ink-tree groups (root -> page groups -> layer groups
  -> stroke nodes), in document order; node UUIDs are uuid5 hashes of the
  Neeh ids, so they are stable across exports,
- Neeh-only fields (ids, page geometry, layer flags, authorship) are
  `neeh:*` triples in the knowledge graph, keyed by node URI,
- everything UIM models natively stays native: geometry in splines, width /
  color / opacity in path-point properties, brushes as `neeh://brush/<name>`
  URIs, per-point time / pressure / tilt in sensor channels, and
  `Stroke.created_at_ms` as the SensorData timestamp.

Fidelity: structure, ids, authorship, flags, and millisecond times survive
exactly. UIM quantizes the rest — coordinates and width to float32, color and
opacity to 8 bits per channel, pressure and tilt to the channel precision
(1e-4; tilt also passes through the W3C tilt <-> azimuth/altitude
conversion). A round trip is idempotent: re-exporting an imported document
reproduces it exactly.
"""
from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Any, Union

try:
    from uim.codec.parser.uim import UIMParser
    from uim.codec.writer.encoder.encoder_3_1_0 import UIMEncoder310
    from uim.model.base import UUIDIdentifier
    from uim.model.ink import InkModel, InkTree
    from uim.model.inkdata.brush import BrushPolygonUri, VectorBrush
    from uim.model.inkdata.strokes import (
        LayoutMask,
        PathPointProperties,
        Spline,
        Stroke as UimStroke,
        Style as UimStyle,
    )
    from uim.model.inkinput.inputdata import (
        Environment,
        InkInputProvider,
        InkInputType,
        InkSensorMetricType,
        InkSensorType,
        InputContext,
        InputDevice,
        SensorChannel,
        SensorChannelsContext,
        SensorContext,
    )
    from uim.model.inkinput.sensordata import InkState, SensorData
    from uim.model.semantics.node import StrokeGroupNode, StrokeNode
    from uim.model.semantics.schema import SemanticTriple
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "neeh.adapters.uim needs the universal-ink-library — "
        'install it with `pip install "neeh[uim]"`'
    ) from exc

from neeh.document import Document, Layer, Page
from neeh.ink import Author, Point
from neeh.ink.stroke import Stroke
from neeh.ink.style import Brush, StrokeStyle
from neeh.protocol import UIM_PROFILE_VERSION

NEEH_PROFILE = UIM_PROFILE_VERSION
_LEGACY_NEEH_PROFILES = {"1"}
_NS = uuid.NAMESPACE_URL

# Triple predicates of the Neeh profile.
_TYPE = "neeh:type"
_ID = "neeh:id"
_NAME = "neeh:name"
_AUTHOR = "neeh:author"
_VISIBLE = "neeh:visible"
_LOCKED = "neeh:locked"
_WIDTH = "neeh:width"
_HEIGHT = "neeh:height"
_BACKGROUND = "neeh:background"

_ANGLE_PRECISION = 4  # decimal digits kept by the angle/pressure channels


def _node_uuid(kind: str, neeh_id: str) -> uuid.UUID:
    return uuid.uuid5(_NS, f"neeh:{kind}:{neeh_id}")


def _hex_to_rgb(color: str) -> tuple[float, float, float]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    if len(c) != 6:
        raise ValueError(f"expected #rgb or #rrggbb color, got {color!r}")
    return tuple(int(c[i : i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _rgb_to_hex(red: float, green: float, blue: float) -> str:
    return "#%02x%02x%02x" % tuple(round(v * 255) for v in (red, green, blue))


def _tilt_to_azimuth_altitude(tilt_x: float, tilt_y: float) -> tuple[float, float]:
    """W3C pointer-event tilt (degrees) -> pen azimuth/altitude (radians)."""
    if tilt_x == 0.0 and tilt_y == 0.0:
        return 0.0, math.pi / 2
    tan_x = math.tan(math.radians(tilt_x))
    tan_y = math.tan(math.radians(tilt_y))
    return math.atan2(tan_y, tan_x), math.atan2(1.0, math.hypot(tan_x, tan_y))


def _azimuth_altitude_to_tilt(azimuth: float, altitude: float) -> tuple[float, float]:
    if altitude >= math.pi / 2:
        return 0.0, 0.0
    tan_alt = math.tan(altitude)
    return (
        math.degrees(math.atan2(math.cos(azimuth), tan_alt)),
        math.degrees(math.atan2(math.sin(azimuth), tan_alt)),
    )


# --- export -----------------------------------------------------------------


def document_to_uim(doc: Document) -> bytes:
    """Encode a document as UIM 3.1 bytes (RIFF container)."""
    model = InkModel()
    model.properties.append(("neeh.profile", NEEH_PROFILE))
    model.properties.append(("neeh.document.id", doc.id))
    model.properties.append(("neeh.document.title", doc.title))
    model.properties.append(("neeh.document.created_at_ms", str(doc.created_at_ms)))

    channels, input_context_id = _build_input_configuration(model)
    triples = model.knowledge_graph

    root = StrokeGroupNode(_node_uuid("document", doc.id))
    model.ink_tree = InkTree()
    model.ink_tree.root = root

    used_brushes: set[Brush] = set()
    for page in doc.pages:
        page_node = StrokeGroupNode(_node_uuid("page", page.id))
        root.add(page_node)
        triples.append(SemanticTriple(page_node.uri, _TYPE, "page"))
        triples.append(SemanticTriple(page_node.uri, _ID, page.id))
        triples.append(SemanticTriple(page_node.uri, _WIDTH, repr(page.width)))
        triples.append(SemanticTriple(page_node.uri, _HEIGHT, repr(page.height)))
        triples.append(SemanticTriple(page_node.uri, _BACKGROUND, page.background))

        for layer in page.layers:
            layer_node = StrokeGroupNode(_node_uuid("layer", layer.id))
            page_node.add(layer_node)
            triples.append(SemanticTriple(layer_node.uri, _TYPE, "layer"))
            triples.append(SemanticTriple(layer_node.uri, _ID, layer.id))
            triples.append(SemanticTriple(layer_node.uri, _NAME, layer.name))
            triples.append(SemanticTriple(layer_node.uri, _AUTHOR, layer.author.value))
            triples.append(
                SemanticTriple(layer_node.uri, _VISIBLE, "true" if layer.visible else "false")
            )
            triples.append(
                SemanticTriple(layer_node.uri, _LOCKED, "true" if layer.locked else "false")
            )

            for stroke in layer.strokes:
                used_brushes.add(stroke.style.brush)
                stroke_node = _export_stroke(model, stroke, channels, input_context_id)
                layer_node.add(stroke_node)
                triples.append(SemanticTriple(stroke_node.uri, _TYPE, "stroke"))
                triples.append(SemanticTriple(stroke_node.uri, _ID, stroke.id))
                triples.append(SemanticTriple(stroke_node.uri, _AUTHOR, stroke.author.value))

    for brush in used_brushes:
        model.brushes.add_vector_brush(
            VectorBrush(
                _brush_uri(brush),
                [BrushPolygonUri("will://brush/3.0/shape/Circle?precision=20&radius=1", 0.0)],
            )
        )
    return UIMEncoder310().encode(model)


def _build_input_configuration(model: InkModel) -> tuple[dict, uuid.UUID]:
    """One shared pen input context; returns sensor channels by type + context id."""
    env = Environment()
    env.properties.append(("app.id", "neeh-sdk"))
    provider = InkInputProvider(input_type=InkInputType.PEN)
    device = InputDevice()
    model.input_configuration.environments.append(env)
    model.input_configuration.ink_input_providers.append(provider)
    model.input_configuration.devices.append(device)

    ids = {"ink_input_provider_id": provider.id, "input_device_id": device.id}
    channels = {
        InkSensorType.TIMESTAMP: SensorChannel(
            channel_type=InkSensorType.TIMESTAMP,
            metric=InkSensorMetricType.TIME,
            resolution=1000.0,
            precision=0,
            **ids,
        ),
        InkSensorType.PRESSURE: SensorChannel(
            channel_type=InkSensorType.PRESSURE,
            metric=InkSensorMetricType.NORMALIZED,
            resolution=1.0,
            precision=_ANGLE_PRECISION,
            channel_min=0.0,
            channel_max=1.0,
            **ids,
        ),
        InkSensorType.AZIMUTH: SensorChannel(
            channel_type=InkSensorType.AZIMUTH,
            metric=InkSensorMetricType.ANGLE,
            resolution=1.0,
            precision=_ANGLE_PRECISION,
            channel_min=-math.pi,
            channel_max=math.pi,
            **ids,
        ),
        InkSensorType.ALTITUDE: SensorChannel(
            channel_type=InkSensorType.ALTITUDE,
            metric=InkSensorMetricType.ANGLE,
            resolution=1.0,
            precision=_ANGLE_PRECISION,
            channel_min=0.0,
            channel_max=math.pi / 2,
            **ids,
        ),
    }
    scc = SensorChannelsContext(channels=list(channels.values()), **ids)
    sensor_context = SensorContext()
    sensor_context.add_sensor_channels_context(scc)
    model.input_configuration.sensor_contexts.append(sensor_context)
    input_context = InputContext(environment_id=env.id, sensor_context_id=sensor_context.id)
    model.input_configuration.input_contexts.append(input_context)
    return channels, input_context.id


def _export_stroke(
    model: InkModel, stroke: Stroke, channels: dict, input_context_id: uuid.UUID
) -> StrokeNode:
    sensor = SensorData(
        UUIDIdentifier.id_generator(),
        input_context_id=input_context_id,
        state=InkState.PLANE,
        timestamp=stroke.created_at_ms,
    )
    base_s = stroke.created_at_ms / 1000.0
    sensor.add_timestamp_data(
        channels[InkSensorType.TIMESTAMP], [base_s + p.t_ms / 1000.0 for p in stroke.points]
    )
    sensor.add_data(channels[InkSensorType.PRESSURE], [p.pressure for p in stroke.points])
    tilts = [_tilt_to_azimuth_altitude(p.tilt_x, p.tilt_y) for p in stroke.points]
    sensor.add_data(channels[InkSensorType.AZIMUTH], [az for az, _ in tilts])
    sensor.add_data(channels[InkSensorType.ALTITUDE], [alt for _, alt in tilts])
    model.sensor_data.add(sensor)

    data: list[float] = []
    for p in stroke.points:
        data.extend((p.x, p.y))
    spline = Spline(layout_mask=LayoutMask.X.value | LayoutMask.Y.value, data=data)

    red, green, blue = _hex_to_rgb(stroke.style.color)
    style = UimStyle(
        properties=PathPointProperties(
            size=stroke.style.width, red=red, green=green, blue=blue, alpha=stroke.style.opacity
        ),
        brush_uri=_brush_uri(stroke.style.brush),
    )
    uim_stroke = UimStroke(
        sid=_node_uuid("stroke", stroke.id), spline=spline, style=style, sensor_data_id=sensor.id
    )
    return StrokeNode(uim_stroke)


def _brush_uri(brush: Brush) -> str:
    return f"neeh://brush/{brush.value}"


# --- import -----------------------------------------------------------------


def document_from_uim(data: bytes) -> Document:
    """Decode UIM 3.1 bytes written by `document_to_uim`."""
    model = UIMParser().parse(data)

    props = dict(model.properties)
    profile = props.get("neeh.profile")
    if profile is None:
        raise ValueError("not a Neeh-profile UIM file (missing neeh.profile property)")
    if profile != NEEH_PROFILE and profile not in _LEGACY_NEEH_PROFILES:
        raise ValueError(
            f"unsupported Neeh UIM profile {profile!r}; supported profile is {NEEH_PROFILE!r}"
        )

    facts: dict[str, dict[str, str]] = {}
    for triple in model.knowledge_graph.statements:
        facts.setdefault(triple.subject, {})[triple.predicate] = triple.object

    channel_types = {
        channel.id: channel.type
        for context in model.input_configuration.sensor_contexts
        for scc in context.sensor_channels_contexts
        for channel in scc.channels
    }

    pages = [
        _import_page(model, page_node, facts, channel_types)
        for page_node in model.ink_tree.root.children
    ]
    return Document(
        id=props["neeh.document.id"],
        title=props.get("neeh.document.title", "Untitled"),
        created_at_ms=int(props.get("neeh.document.created_at_ms", 0)),
        pages=pages,
    )


def _import_page(
    model: InkModel, page_node: Any, facts: dict, channel_types: dict
) -> Page:
    about = facts.get(page_node.uri, {})
    if about.get(_TYPE) != "page":
        raise ValueError(f"unexpected ink-tree node {page_node.uri}: not a neeh page")
    layers = [
        _import_layer(model, layer_node, facts, channel_types)
        for layer_node in page_node.children
    ]
    return Page(
        id=about[_ID],
        width=float(about[_WIDTH]),
        height=float(about[_HEIGHT]),
        background=about[_BACKGROUND],
        layers=layers,
    )


def _import_layer(
    model: InkModel, layer_node: Any, facts: dict, channel_types: dict
) -> Layer:
    about = facts.get(layer_node.uri, {})
    if about.get(_TYPE) != "layer":
        raise ValueError(f"unexpected ink-tree node {layer_node.uri}: not a neeh layer")
    strokes = [
        _import_stroke(model, stroke_node, facts.get(stroke_node.uri, {}), channel_types)
        for stroke_node in layer_node.children
    ]
    return Layer(
        id=about[_ID],
        name=about[_NAME],
        author=Author(about[_AUTHOR]),
        visible=about[_VISIBLE] == "true",
        locked=about[_LOCKED] == "true",
        strokes=strokes,
    )


def _import_stroke(
    model: InkModel, stroke_node: Any, about: dict, channel_types: dict
) -> Stroke:
    uim_stroke = stroke_node.stroke
    xs = uim_stroke.splines_x
    ys = uim_stroke.splines_y

    sensor = model.sensor_data.sensor_data_by_id(uim_stroke.sensor_data_id)
    created_at_ms = sensor.timestamp
    by_type: dict = {}
    for channel_data in sensor.data_channels:
        channel_type = channel_types.get(channel_data.id)
        if channel_type is not None:
            # Channel values are delta-decoded; re-round to the channel
            # precision to shed float accumulation noise.
            by_type[channel_type] = channel_data.values
    t_ms = [round(v * 1000) - created_at_ms for v in by_type[InkSensorType.TIMESTAMP]]
    pressures = [round(v, _ANGLE_PRECISION) for v in by_type[InkSensorType.PRESSURE]]
    azimuths = [round(v, _ANGLE_PRECISION) for v in by_type[InkSensorType.AZIMUTH]]
    altitudes = [round(v, _ANGLE_PRECISION) for v in by_type[InkSensorType.ALTITUDE]]

    points = []
    for i, (x, y) in enumerate(zip(xs, ys)):
        tilt_x, tilt_y = _azimuth_altitude_to_tilt(azimuths[i], altitudes[i])
        points.append(
            Point(x=x, y=y, t_ms=t_ms[i], pressure=pressures[i], tilt_x=tilt_x, tilt_y=tilt_y)
        )

    pp = uim_stroke.style.path_point_properties
    style = StrokeStyle(
        color=_rgb_to_hex(pp.red, pp.green, pp.blue),
        width=pp.size,
        brush=Brush(uim_stroke.style.brush_uri.rsplit("/", 1)[-1]),
        opacity=pp.alpha,
    )
    return Stroke(
        points=tuple(points),
        style=style,
        id=about[_ID],
        author=Author(about[_AUTHOR]),
        created_at_ms=created_at_ms,
    )


# --- file helpers -----------------------------------------------------------


def save_uim(doc: Document, path: Union[str, Path]) -> None:
    Path(path).write_bytes(document_to_uim(doc))


def load_uim(path: Union[str, Path]) -> Document:
    return document_from_uim(Path(path).read_bytes())
