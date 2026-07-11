# Neeh SDK

**Digital ink should be as programmable as source code.**

Neeh SDK is a common foundation for notebook, whiteboard, and handwriting applications that
treat ink as structured, addressable data rather than pictures of pen movement. Strokes have
stable IDs, timestamps, and authors; edits are reversible commands; and the surface is exposed
through typed, versioned tools. Scripts, test harnesses, and agents can inspect and modify ink
without flattening away its structure or context.

> **Status: pre-alpha; Phase 1 complete, Phase 2 baseline present.** The reference Python model,
> canvas, renderer, UIM adapter, research-backed ICF v1 builder, reusable agent adapters, v1
> tools, and public contracts are in place. A
> host-tested C++17 core and versioned C ABI now provide the portable substrate; app dogfooding,
> consumption, and extraction of the broader app algorithm set are still Phase 2 follow-through.
> Package APIs may evolve, but protocol compatibility follows the identifiers below rather than
> the package version.

## What is here

```text
neeh/
├── ink/         Point, Stroke, StrokeStyle, BoundingBox — the L0 substrate
├── document/    Layer, Page, Document + internal JSON snapshots
├── canvas/      Canvas, Viewport, Selection, History — the editing session
├── rendering/   Renderer protocol + reference SVG and optional PNG renderers
├── tools/       Registry and the versioned agent tool surface
├── agents/      Optional Codex CLI, Claude CLI, and mock model loops
├── adapters/    Optional UIM 3.1 persistence/interchange adapter
├── context.py   Ink Context Format v0 and research-backed v1 builders
└── protocol.py  Independently versioned public protocol identifiers

spec/
├── ink-context-format-v1.md  Model-facing compact SVG ICF v1 contract
├── tool-surface-v1.md     Tool schemas, errors, batching, limits, and cursor design
└── uim-profile-v1.md      Canonical Neeh-to-UIM 3.1 mapping and fidelity contract

research/
├── protocol-m0.md         Research protocol: hypotheses, encodings, tasks, decision rules
└── prior-art-digest.md    Prior art, datasets, and token-economics evidence base

cpp/
├── include/neeh/core.hpp   Portable C++17 ink/document substrate
├── include/neeh/render.hpp Reference SVG and CPU RGBA rendering
└── include/neeh/c_api.h    ABI v1 opaque-handle C boundary
```

## Quickstart

```python
from neeh import Canvas
from neeh.context import build_ink_context_v1
from neeh.protocol import protocol_versions
from neeh.tools import call_tool, tool_manifest

canvas = Canvas()

# Direct Python calls return result objects; remote bindings add the v1 result envelope.
page_view = call_tool(canvas, "view_page", {"format": "svg"})
strokes = call_tool(canvas, "get_strokes")
stroke = call_tool(
    canvas,
    "add_stroke",
    {"points": [[100, 100], [200, 140], [300, 100]]},
)
call_tool(canvas, "highlight", {"region": [80, 80, 320, 160]})
call_tool(canvas, "undo")

context = build_ink_context_v1(canvas, raster="attached_image", stroke_bboxes=True)
print(protocol_versions())
print(tool_manifest())
```

Model adapters are optional: install `neeh[agents]`. PNG rendering is available through
`neeh[png]`. UIM persistence is also optional:
`pip install "neeh[uim]"`. The core Python package remains dependency-free on Python 3.10+.

## The research program

The research program established where stroke-native structured context complements raster
perception. A PNG tells a model what a page looks like; ink-native
context carries what a raster destroys — stroke order, direction, authorship, and stable stroke
identity that makes ink *addressable*, not just visible. ICF v1 is the evidence-backed compact
SVG format; attach a raster when the task requires reading or visual classification.

[research/protocol-m0.md](research/protocol-m0.md) pre-registers the hypotheses, encoding arms,
task families, corpora, and decision rules; [research/prior-art-digest.md](research/prior-art-digest.md)
collects the supporting literature, datasets, and token economics. The v1 tool surface and the
UIM persistence profile are the stable substrate this research stands on.

## Public contracts

The package and its three public data/protocol surfaces have independent compatibility clocks:

| Surface | Identifier | Specification |
|---|---|---|
| Model context snapshot | `ink-context/v1` | [Ink Context Format v1](spec/ink-context-format-v1.md) |
| Tool calls | `neeh-tools/v1` | [Neeh Tool Surface v1](spec/tool-surface-v1.md) |
| Persistence/interchange profile | `neeh-uim/v1` over UIM 3.1 | [Neeh UIM Profile v1](spec/uim-profile-v1.md) |

Use `neeh.protocol.protocol_versions()` to discover all three and
`neeh.tools.tool_manifest()` to discover the exact v1 tool schemas. Do not infer wire support from
the Python distribution version. Compatibility rules and the layer boundaries are documented in
[Architecture](ARCHITECTURE.md).

## Design invariants

- **Stable IDs everywhere.** `st_…`, `ly_…`, and `pg_…` survive moves, style edits, and
  serialization. References do not drift when geometry changes.
- **Time is a first-class axis.** Every point carries a stroke-relative `t_ms`; every stroke has
  epoch `created_at_ms`. Temporal queries are substrate behavior, not recognition metadata.
- **Agent ink is never user ink.** Tool-created strokes have `author=agent` on a dedicated agent
  layer. User ink is not silently mutated or relabeled.
- **Strokes are immutable; edits are atomic commands.** Transforms produce replacement values
  with the same ID. Every successful mutation is one undoable history entry, including actions
  that create or erase several strokes.
- **Coordinates agree.** Raster, vector, tool, and semantic regions use top-left page space with x
  right and y down.

## Persistence is UIM

There is no bespoke `.neeh` format. Documents persist and interchange as Universal Ink Model
(UIM) 3.1 through `neeh.adapters.uim`. Pages and layers map to ordered UIM ink-tree groups;
Neeh-only structure and authorship use knowledge-graph triples; geometry, brushes, style, time,
pressure, and tilt use native UIM fields.

UIM normalization quantizes some numeric values, so the [profile](spec/uim-profile-v1.md)
specifies exact fields, tolerances, compatibility, and semantic idempotence. Built-in
`Document.to_json()` is an internal snapshot for debugging and fixtures and carries no
interchange compatibility promise.

## Phase 1 completion

Phase 1 establishes the contract that later runtimes and transports implement:

- immutable ink primitives, document/page/layer structure, stable IDs, and millisecond time;
- editing session state with selection, viewport, locked-layer safety, and undo/redo;
- reference SVG/PNG rendering and fourteen schema-registered v1 tools;
- deterministic, bounded ICF v0 and v1 page context with rate control and optional semantics;
- UIM 3.1 persistence under the formal `neeh-uim/v1` profile;
- independently discoverable protocol versions and a versioned tool manifest; and
- normative errors plus capability-gated designs for pagination, batching, limits, and the future
  event cursor.

The Phase 2 portable baseline now implements the substrate and render boundary in C++17 and
exposes ABI version 1 for Swift, Kotlin/JNI, Rust, and other host integrations. It is a shipped,
host-tested baseline, not a declaration that Phase 2 is complete; app consumption and broader
algorithm extraction remain.

The proven assistant loop now ships in `neeh.agents`: it sends a PNG plus ICF v1 context to Codex
CLI or Claude CLI and applies returned actions as agent ink. `examples/assistant/` is its localhost
HTTP/UI shell.

## Deliberately not shipped yet

Recognition/OCR, diagram understanding, embeddings, semantic search, durable anchors, and
user-handwriting extraction remain pluggable future layers. `describe_page`, `search_ink`,
`get_events`, `anchor`, and `draw_shape` are reserved capabilities, not callable v1 core tools.
The event cursor is designed in the tool specification but intentionally unadvertised until an
atomic snapshot-plus-cursor handoff and retention policy exist. Raw stylus telemetry remains a
separate local data plane rather than being forced through tool calls.

See [Architecture](ARCHITECTURE.md) for the full layer map and deferred boundaries.

## Development

Python reference:

```bash
pip install -e ".[dev]"
pytest
```

Portable core:

```bash
cmake -S . -B build -DNEEH_BUILD_TESTS=ON
cmake --build build
ctest --test-dir build --output-on-failure
```

Licensed under the [Apache License 2.0](LICENSE).
