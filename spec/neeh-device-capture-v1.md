# Neeh Device Capture v1

Status: experimental SDK protocol. `neeh-device-capture/v1` is fixture-backed
and appears only in `neeh.protocol.experimental_protocol_versions()`. It is
not part of stable protocol discovery.

## Purpose

A normal `.tink` v4 file is a final document snapshot. It does not
contain raw per-sample time or a complete record of erased/replaced versions,
so it is not sufficient for temporal Move 3 evaluation. This protocol is the
lossless research sidecar: ordered raw samples plus explicit edit deltas.

The canonical shareable ZIP contains exactly:

```text
session.tink
session.events.json
```

`session.events.json` validates against
`spec/fixtures/neeh-device-capture-v1.schema.json`. The SDK loader also accepts
the JSON file directly, or a directory containing `session.events.json`, for
local tooling. It never treats the `.tink` body as a substitute for the event
sidecar.

## Time and coordinates

- `session.started_at_ms`, optional `session.ended_at_ms`, and every stroke
  `created_at_ms` are Unix epoch milliseconds.
- An event `t_ms` is a non-negative offset from `session.started_at_ms`.
- A point `t_ms` is a non-negative offset from that stroke's begin event.
- Optional point `event_time_ms` is the untouched Android monotonic event time;
  it is not interpreted as Unix time.
- v1 page coordinates are pixels with a top-left origin.

`pressure`, `tilt_rad`, `orientation_rad`, `action`, and `event_time_ms` are
optional per point because hardware and Android input paths vary. The device
availability flags describe the session; they do not manufacture missing
samples. Raw values remain in `ImportedDeviceCapture.capture`. For the derived
Neeh `Point`, Android scalar tilt is projected using orientation 0 along +x.

## Envelope

The top-level object contains:

- `schema="neeh-device-capture/v1"`;
- `session` identity/name and epoch anchors;
- `device` Android/hardware and sensor-availability metadata;
- `app` name, package, version, and optional build metadata;
- `coordinate_space={"unit":"px","origin":"top-left"}`;
- `pages`, an inventory of every page referenced by the event stream;
- `events`, ordered with unique IDs and contiguous zero-based `seq` values.

Unknown additive fields are ignored. A consumer MUST reject a different
`schema`, missing required values, non-contiguous sequences, backward event or
stroke offsets, duplicate IDs, invalid stroke state transitions, and mutation
deltas that do not match the reconstructed live state.

## Strokes

Raw capture uses three events:

1. `stroke_begin` declares stable `stroke_id`, `layer_id`, author, tool, style,
   and epoch `created_at_ms`.
2. Each `stroke_sample` carries the exact point object.
3. `stroke_end` completes the stroke; `cancelled=true` discards the derived
   stroke while retaining the raw events in the capture.

A style requires positive `width` and either `color="#RRGGBB"` or Android
`color_argb="#AARRGGBB"`. `opacity` and SDK `brush` are optional. When ARGB is
used, the importer derives opacity from alpha. Tool strings are open and may
include values such as `pen`, `marker`, `generated`, or `eraser`.
Authors are `user`, `agent`, or `app`; the SDK maps `app` to `Author.AGENT`
while preserving the raw value.

## Edits and recoverability

`stroke_delete`, `stroke_transform`, `stroke_restyle`, `undo`, and `redo`
carry explicit `removed` and `added` arrays. Each member is a complete snapshot:

```json
{
  "stroke_id": "stable-id",
  "layer_id": "ink",
  "author": "user",
  "tool": "pen",
  "style": {"color_argb": "#FF202020", "width": 3.0},
  "created_at_ms": 1784000000100,
  "points": [{"x": 80, "y": 200, "t_ms": 0}]
}
```

This deliberate duplication makes erased and transformed states recoverable
without consulting the final `.tink` file. `stroke_delete.reason` distinguishes
`eraser`, `scratch_erase`, `page_delete`, and `other`. A visual cross-out is
ordinary retained ink: it has begin/sample/end events and no delete event.

Page create/delete/change operations are folded into the existing
`ink-eventlog/v1` as `kind="page"`, with the original operation in `label` and
descriptor/transition facts in `meta`. Stroke completion maps to `add`;
deletion to `erase`; transforms/restyles/undo/redo/groups retain their existing
EventLog kinds. Page deletion includes removed stroke snapshots so EventLog
replay and recovery remain exact.

## Python import

```python
from neeh.adapters.device_capture import load_device_capture

capture = load_device_capture("device-session.zip")
canvas = capture.canvas
event_log = capture.event_log
raw_json = capture.capture
```

`load_device_capture()` accepts the canonical ZIP, a sidecar JSON path, or a
directory. `import_device_capture(payload)` accepts an already-decoded object.
`convert_device_capture(source, destination)` writes a complete
`neeh-session/v1` JSON session snapshot. The derived Canvas mutable undo/redo
stacks are intentionally empty after import; replay, historical inspection,
and recovery use the complete append-only `event_log`.

The conformance fixture
`spec/fixtures/neeh-device-capture-v1.session.json` covers retained
writing, erased-and-rewritten ink, a visual cross-out, undo/redo, raw stylus
axes, app-authored ink, and two pages.
