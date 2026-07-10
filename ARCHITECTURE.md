# Architecture

Neeh separates durable ink, an editing session, model context, and agent control. The Python
implementation is the behavioral reference; the portable C++17 core and versioned C ABI provide
the Phase 2 host-integration baseline without changing the public protocol clocks.

## Layer map

| Layer | Responsibility | Current implementation |
|---|---|---|
| L0 — ink substrate | Points, immutable strokes, styles, IDs, pages, layers, documents, time | `neeh/ink`, `neeh/document`; `cpp/include/neeh/core.hpp` |
| L1 — geometry/rendering | Bounds, region queries, hit testing, raster/vector output | `neeh/rendering`; `cpp/include/neeh/render.hpp` |
| Session | Current page, viewport, selection, atomic edit history | `neeh/canvas` (Python reference) |
| Context | Bounded raster + vector + semantic snapshot for models | `neeh/context.py`; [ICF v0](spec/ink-context-format.md) |
| L2 — understanding | Recognition, HWR, segmentation, semantic scene graph | deferred plugin boundary |
| L3 — agent surface | Versioned schemas, reads, selection, edits, undo/redo | `neeh/tools`; [Tool Surface v1](spec/tool-surface-v1.md) |
| L4 — higher actions | Ink writing, highlighting, future shapes/anchors | shipped primitives in `neeh/tools/core.py`; higher actions reserved |
| Persistence | Portable document snapshot and interchange | `neeh/adapters/uim.py`; [Neeh UIM Profile v1](spec/uim-profile-v1.md) |
| Native ABI | Stable-language boundary for app hosts | `cpp/include/neeh/c_api.h`, ABI version 1 |

The editing session is deliberately above the document model. A native app, web host, test, or
headless agent can share document semantics while choosing its own UI/session integration.

## Runtime boundaries

### Python reference

The Python packages define the complete Phase 1 behavior:

- immutable point/stroke values and stable-ID replacement transforms;
- ordered documents, pages, layers, and strokes;
- current-page canvas state, selection, viewport, and reversible `StrokeEdit` history;
- SVG/PNG rendering and bounding-box region queries;
- deterministic ICF v0 snapshot construction;
- UIM 3.1 profile import/export; and
- the schema-registered v1 tool surface.

Direct Python tool calls return result dictionaries or raise mapped Python exceptions. A remote
binding adds the standardized success/error envelope from the tool specification.

### Portable core baseline

The Phase 2 baseline is present as a C++17 library target, `Neeh::Core`, with installable headers
and CMake package metadata. It provides:

- `neeh::Point`, `BoundingBox`, `StrokeStyle`, `Stroke`, `Layer`, `Page`, and `Document`;
- stable-ID translate/restyle operations and region/time snapshot queries;
- `SvgRenderer` plus a CPU RGBA renderer; and
- `cpp/include/neeh/c_api.h`, a versioned C ABI with opaque ownership handles,
  `neeh_status_t`, thread-local `neeh_last_error_message()`, copy-out strings, stroke lists, and
  rendered image handles.

The native target is host-built and testable independently of Python. This is a substrate/C API
baseline, not completion of all Phase 2 work: app dogfooding, host consumption, session/history
integration, UIM codec wiring, and extraction of the broader app algorithm set remain follow-up.

### Control plane and data plane

The v1 tools are a low-rate control and snapshot plane. They are appropriate for MCP/function
calls, render requests, bounded vector reads, and committed edits. Raw stylus samples belong in a
local/native capture data plane; forcing 120–240 Hz input through JSON tool calls would add
latency and confuse transport resumability with ink history.

The future `get_events` cursor therefore describes committed edits, not point samples. It remains
designed but unshipped until snapshot capture and cursor acquisition can be atomic. See
[Designed event cursor protocol](spec/tool-surface-v1.md#designed-event-cursor-protocol-not-shipped).

## The v1 tool surface

The shipped names are:

```text
view_page       view_region      get_strokes
add_stroke      erase            select            move
highlight       write_text       undo              redo
```

`neeh.tools.tool_manifest()` returns:

```json
{
  "protocol": "neeh-tools/v1",
  "tools": [
    {"name": "...", "description": "...", "input_schema": {}}
  ]
}
```

The registry is the discovery truth. `describe_page`, `search_ink`, `get_events`, `anchor`, and
`draw_shape` are reserved names and are unavailable unless a future host explicitly advertises
them. Request-array batching is an optional transport capability, not an `add_strokes` core tool.

## Invariants

1. **Stable identity.** A geometric or style transform preserves the stroke ID. Page, layer, and
   document IDs survive persistence round trips.
2. **Attribution.** Agent-created output has `Author.AGENT` and lands on an agent layer. Tools do
   not silently relabel user ink.
3. **Atomicity and reversibility.** Each successful mutation is one history entry; a failed call
   leaves document, selection, and history unchanged. Undo restores a validated prior state even
   if a layer was subsequently locked.
4. **Locked-layer safety.** Locked content is not changed by new operations. Erase/move may skip
   locked targets but never report them as changed.
5. **Time.** `Point.t_ms` is a non-negative, non-decreasing offset within a stroke;
   `Stroke.created_at_ms` is epoch milliseconds. Temporal reads live in L0.
6. **Coordinate agreement.** Page, render, ICF, tool, and semantic geometry share top-left page
   coordinates with x right and y down.
7. **Bounded context.** Model-facing snapshots disclose every truncation. Reads paginate with an
   opaque, query-bound cursor when a host advertises pagination.

## Persistence: UIM 3.1

There is no bespoke `.neeh` format. A Neeh document persists as UIM 3.1 under profile identifier
`neeh-uim/v1`:

- the primary ink tree is `document → page → layer → stroke` in document order;
- deterministic UUIDv5 node IDs bridge opaque Neeh IDs to UIM nodes;
- required `neeh:*` triples carry page geometry, layer flags, and user/agent authorship;
- splines, path-point style, brush URIs, sensor channels, and timestamps remain native UIM; and
- exact structural fields plus bounded UIM quantization are conformance requirements.

The writer emits canonical `neeh.profile=neeh-uim/v1`. Readers accept the initial prototype value
`1` but reject missing or unknown profiles. A generic UIM file without profile metadata is not a
Neeh document. `Document.to_json()` remains an internal debug/fixture snapshot without a
compatibility promise.

UIM is a full-model RIFF/Protobuf snapshot, not an append-only history stream. The designed event
cursor is a separate synchronization concern and does not create another persistence format.

## Versioning

Package, protocol, and persistence versions advance independently:

| Version domain | Current value | Compatibility trigger |
|---|---|---|
| Python distribution | `0.1.0.dev0` | Python API/package release |
| Native C ABI | `NEEH_ABI_VERSION == 1` | C symbol, ownership, layout, or semantic ABI break |
| Model context | `ink-context/v0` | ICF JSON shape or field-semantic break |
| Tool surface | `neeh-tools/v1` | Tool name/schema/result/invariant break |
| UIM profile | `neeh-uim/v1` | Persistence mapping or fidelity break |
| Base UIM serialization | `3.1.0` | Upstream container/model revision |

`neeh.protocol.protocol_versions()` returns the three public Python data/protocol identifiers.
Consumers MUST negotiate exact identifiers and MUST NOT derive them from the package version.

Within a named protocol version, optional fields and advertised capabilities may be added only
where its specification explicitly allows them. A breaking meaning or closed-object shape gets a
new identifier. A library release may implement more than one protocol version during migration.

## Phase status

| Phase | Status | Exit condition / remaining work |
|---|---|---|
| Phase 0 — assistant spike | complete | PNG + vector context drives model actions in `examples/assistant`. |
| Phase 1 — reference contracts | complete | Python substrate/session/rendering/tools, ICF v0, tool v1, UIM profile v1, discovery, and conformance docs/tests. |
| Phase 2 — portable substrate | baseline present, integration pending | C++17/C ABI and host tests exist; app dogfooding, consumption, and broader algorithm extraction remain. |
| Phase 3 — host/control integration | not started | MCP/host binding, pagination storage, batch transaction adapter, and atomic event-cursor handoff. |
| Phase 4 — understanding/actions | not started | Recognition providers, confidence-gated semantics, search, anchors, user handwriting, and higher drawing actions. |

## Deferred ownership

| Deferred capability | Intended boundary |
|---|---|
| HWR/OCR/segmentation | recognizer plugin interface above ICF |
| Diagram/scene understanding | semantic provider; UIM knowledge graph for persistence |
| Embeddings/search | semantic index service, exposed only when `search_ink` is advertised |
| Durable anchors | semantic reference service, exposed only when `anchor` is advertised |
| Point-accurate hit testing/spatial index | native geometry layer |
| Large-page tiling/cache | host rendering/cache layer, reflected in a future ICF version |
| MCP server and language bindings | transport packages over `neeh-tools/v1` and the C ABI |
| Edit event retention/cursors | host synchronization store; not UIM and not raw stylus transport |
