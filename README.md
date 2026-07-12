# Neeh SDK

Neeh is a structured digital-ink SDK for notebook, whiteboard, and handwriting applications.
It represents ink as ordered strokes with stable IDs, timing, authorship, and style so clients
can render, query, edit, persist, and expose ink to tools without flattening it into an image.

> Neeh is pre-alpha. The protocol specifications are versioned, but the Python and native APIs
> may change before the first stable release.

## Why not OCR, a canvas API, or an image pipeline

A rendered image or a handwriting-recognition transcript is a *many-to-one* view of digital ink:
two different stroke histories can rasterize to identical pixels while differing in draw order,
direction, pressure, and revision — and once flattened, that information cannot be recovered. A
typical canvas or whiteboard API exposes pixels or opaque vector paths, not a stable, agent-
addressable structure: there is no consistent id a tool call can target, no bounded way to ask
"what changed since I last looked," and no local computation of temporal or spatial facts before
spending model context on them.

Neeh proposes giving agents both channels deliberately: a rendered view for what pixels alone can
answer, and native ink structure — addressable strokes, deterministic geometric/temporal analysis,
and a bounded tool surface — for what pixels cannot. See [ARCHITECTURE.md](ARCHITECTURE.md) for the
full design rationale, the perception-action-feedback loop, and the trade-offs this implies.

## Features

- Immutable points and strokes with pressure, tilt, timestamps, style, and stable IDs.
- Ordered documents, pages, and layers with visibility and lock state.
- A canvas session with selection, atomic edits, undo, and redo.
- SVG, optional PNG, and token-cheap ASCII rendering in a shared page coordinate system.
- A discoverable, JSON Schema-based tool surface for model and automation integrations.
- Compact Ink Context Format snapshots with addressable stroke geometry.
- A structured ink index (marks with stable ids, shape, and position) for cheap, groundable model context.
- Deterministic ink analyzers and query-aware temporal retrieval for bounded agent evidence.
- Optional Universal Ink Model 3.1 import and export.
- A C++17 core and versioned C ABI for native hosts.

## Install from a checkout

The Python core has no runtime dependencies:

```bash
python -m pip install -e .
```

Install optional features as needed:

```bash
python -m pip install -e ".[png]"      # PNG rendering
python -m pip install -e ".[uim]"      # UIM 3.1 persistence
python -m pip install -e ".[agents]"   # local model adapters
python -m pip install -e ".[dev]"      # complete development environment
```

Python 3.10 or newer is required.

## Python quickstart

```python
from neeh import Canvas, StrokeStyle
from neeh.tools import call_tool

canvas = Canvas()
stroke = canvas.add_stroke(
    [(100, 100), (180, 140), (260, 100)],
    style=StrokeStyle(color="#1d4ed8", width=3),
)

canvas.select(stroke_ids=[stroke.id])
canvas.move(20, 10)
canvas.undo()

svg = call_tool(canvas, "view_page", {"format": "svg"})["data"]
```

See [`examples/quickstart.py`](examples/quickstart.py) for a complete executable example.

## Context and tools

Neeh keeps model-facing context separate from the mutation API:

```python
from neeh.context import build_ink_context_v1
from neeh.protocol import protocol_versions
from neeh.tools import call_tool, tool_manifest

context = build_ink_context_v1(
    canvas,
    raster="attached_image",
    stroke_bboxes=True,
)

result = call_tool(
    canvas,
    "mark",
    {"stroke_ids": [stroke.id], "kind": "circle"},
)

print(protocol_versions())
print(tool_manifest())
```

The current public contracts are:

| Surface | Identifier | Specification |
|---|---|---|
| Compact model context | `ink-context/v1` | [Ink Context Format v1](spec/ink-context-format-v1.md) |
| Legacy model context | `ink-context/v0` | [Ink Context Format v0](spec/ink-context-format.md) |
| Tool calls | `neeh-tools/v1` | [Tool Surface v1](spec/tool-surface-v1.md) |
| UIM mapping | `neeh-uim/v1` | [UIM Profile v1](spec/uim-profile-v1.md) |
| Agent perception workspace | `ink-agent-interface/v1` | [Ink Agent Interface v1](spec/ink-agent-interface-v1.md) |
| Deterministic ink analysis | `ink-analysis/v1` | [Ink Analysis v1](spec/ink-analysis-v1.md) |
| Temporal retrieval | `ink-timeline/v1` | [Ink Timeline v1](spec/ink-timeline-v1.md) |

Applications should discover protocol identifiers and tool schemas at runtime instead of deriving
them from the Python package version. The design rationale behind the Ink Agent Interface — why a
structured index is the primary model-facing channel, with raster fetched on demand — is in
[Ink accessibility tree](spec/ink-accessibility-tree.md).

## Persistence

UIM 3.1 is the supported interchange format. The adapter preserves Neeh page/layer structure,
stable IDs, authorship, style, and capture metadata within the limits documented by the profile.

```python
from neeh.adapters.uim import load_uim, save_uim

save_uim(canvas.document, "notes.uim")
document = load_uim("notes.uim")
```

`Document.to_json()` is intended for internal snapshots and fixtures. It is not a stable file
format.

## Native core

The native library exposes the ink/document substrate and SVG/RGBA rendering through C++17 and
ABI version 1 of the C interface.

```bash
cmake -S . -B build -DNEEH_BUILD_TESTS=ON
cmake --build build --config Release
ctest --test-dir build --build-config Release --output-on-failure
cmake --install build --prefix /path/to/prefix
```

CMake consumers can use `find_package(NeehSDK CONFIG REQUIRED)` and link `Neeh::Core`.
The C interface is declared in [`cpp/include/neeh/c_api.h`](cpp/include/neeh/c_api.h).

## Assistant example

`examples/assistant/` is a local browser demo built on the reusable adapters in `neeh.agents`.
It can use an existing Codex CLI or Claude CLI login and includes a mock backend for offline use.
Agent answers use blue ink with the cursive Hershey Script Complex face.
See the [assistant example guide](examples/assistant/README.md).

The current product direction and remaining milestones are tracked in
[ROADMAP.md](ROADMAP.md). The active path is deterministic analysis + structured
retrieval + raster on demand; learned ink encoders are not planned without a
measured failure of that baseline.

## Development

```bash
python -m pip install -e ".[dev]"
python -m pytest -q
```

CI tests Python 3.10 and 3.12, builds the native core on Linux and macOS, runs the C and C++ test
suites, and verifies the installed CMake package.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup and conventions, and
[SECURITY.md](SECURITY.md) to report a vulnerability.

## Authorship

Neeh is created and maintained by **Kunwarbir Singh Padda**. See
[AUTHORS](AUTHORS) for project authorship and [CITATION.cff](CITATION.cff) to
cite this work.

Licensed under the [Apache License 2.0](LICENSE). Copyright and vendored-data
attribution are listed in [`NOTICE`](NOTICE) and
[`THIRD_PARTY_NOTICES`](THIRD_PARTY_NOTICES).
