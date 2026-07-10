# Architecture

The SDK follows the five-layer model from `NEEH_SDK_PLAN.md` (Neeh app repo). Current package
map, bottom-up:

| Layer | Plan | Package | Contents |
|---|---|---|---|
| L0 Substrate | stroke/page/notebook model, serialization | `neeh/ink`, `neeh/document`, `neeh/adapters` | `Point`, `Stroke`, `StrokeStyle`, `BoundingBox`; `Layer`, `Page`, `Document`; internal JSON snapshot + UIM persistence (see Persistence below) |
| L1 Geometry | spatial index, hit-testing, rasterizer | `neeh/rendering` (+ future `neeh/geometry`) | `Renderer` protocol, reference SVG renderer, optional PNG rasterizer |
| L2 Understanding | segmentation, HWR, scene graph | — deferred | future `neeh/plugins` (recognizer interface) |
| L3 Agent surface | MCP server, tool schemas | `neeh/tools` | registry + JSON-Schema tool manifest; MCP server is a thin wrapper later |
| L4 Action | draw, write-as-handwriting, annotate | `neeh/tools/core.py` | `add_stroke`, `highlight`, `write_text` (`print` style now; `user_font` reserved) |

`neeh/canvas` is the editing session that L3/L4 operate on: current page, `Viewport`,
`Selection`, and `History`. It is app-agnostic — the Neeh app, a web whiteboard, or a headless
agent host can all drive one.

## The v1 tool surface

Perception: `view_page`, `view_region` (SVG or PNG), and `get_strokes` (vector ink context).
Action: `add_stroke`, `erase`, `select`, `move`, `highlight`, `write_text`, `undo`, `redo`.
All tools take/return JSON-serializable values and are registered with JSON Schemas —
`neeh.tools.tool_schemas()` is the manifest an MCP server exposes verbatim.

## Invariants

1. **Stable ids.** Geometric transforms preserve stroke ids (`Stroke.translated`), so agent
   references survive edits.
2. **Attribution.** `Author.AGENT` ink only ever lands on an agent layer
   (`Page.agent_layer()`); locked layers are untouchable by tools.
3. **Reversibility.** Every mutation is a `StrokeEdit` pushed through `History`. One command
   shape (removed + added) covers add, erase, and transform. Replay bypasses layer locks —
   validity is checked at edit time; undo must always restore state.
4. **Time.** `Point.t_ms` is an offset from `Stroke.created_at_ms` (epoch). Temporal queries
   (`Page.strokes_since`) are part of the substrate, not a feature.

## Persistence: the Neeh profile of UIM

There is no bespoke `.neeh` format. Documents persist as Universal Ink Model (UIM 3.1)
files via `neeh/adapters/uim.py` (optional extra: `pip install "neeh[uim]"`; pulls
`universal-ink-library`, which currently pins `protobuf<4`). The mapping:

- Pages and layers are ink-tree groups (root → page → layer → stroke), in document order.
  Node UUIDs are uuid5 hashes of the Neeh ids, so they are stable across exports.
- Neeh-only facts (ids, page geometry, layer flags, user/agent authorship) are `neeh:*`
  triples in UIM's knowledge graph, keyed by node URI.
- Everything UIM models natively stays native: geometry as splines, brushes as
  `neeh://brush/<name>` URIs, color/width/opacity as path-point properties, per-point
  time/pressure/tilt as sensor channels, `Stroke.created_at_ms` as the SensorData timestamp.

Fidelity (validated by `tests/test_uim_adapter.py`): structure, ids, authorship, flags, and
millisecond times round-trip exactly. UIM quantizes the rest — coordinates and width to
float32, color and opacity to 8 bits per channel, pressure and tilt to 1e-4 — and a round
trip is idempotent: re-exporting an imported document reproduces it exactly.
`Document.to_json()` stays an internal snapshot (debugging, fixtures, agent wire payloads),
not an interchange format.

## Deferred, and where it will live

| Deferred | Future home | Unblocks when |
|---|---|---|
| Recognition / OCR / HWR | `neeh/plugins` (`Recognizer` interface) | multimodal-LLM-as-recognizer first, per plan §6 Phase 4 |
| Diagram understanding, semantic scene graph | `neeh/ai` | after Phase 0 spike proves the representation; UIM's knowledge graph is the natural serialization |
| Embeddings, semantic search | `neeh/ai` | same |
| PNG tiling/caching | `neeh/rendering/png.py` + host cache | needed once pages outgrow one attached image |
| Spatial index, point-accurate hit-testing | `neeh/geometry` | erase/select currently use bbox intersection |
| MCP server, TS bindings | separate `neeh-mcp` package | plan §6 Phase 3 |

## Ink Context Format

The Phase 0 assistant demo now sends a hybrid context to models: a PNG raster plus
`get_strokes` vector JSON. The draft spec is `spec/ink-context-format.md`. Its current semantic
slot is empty; recognizers and scene graphs will fill it later without changing the substrate
or action invariants above.
