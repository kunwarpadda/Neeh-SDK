# Neeh SDK

**Digital ink should be as programmable as source code.**

Neeh SDK is a common foundation for notebook, whiteboard, and handwriting applications that
treat ink as structured, addressable data — not pictures of pen movement. Strokes have stable
ids, timestamps, and authors; edits are reversible commands; the whole surface is exposed as a
typed tool API. Anything that can call a function — a script, a test harness, an AI agent —
can read, query, and modify handwritten notes, diagrams, sketches, and annotations without
destroying their structure and context.

> **Status: pre-alpha, API-design phase.** This Python package defines the SDK's shape — the
> document model, canvas, and agent tool surface. The portable C++ core lands behind this API
> later (see `NEEH_SDK_PLAN.md` in the Neeh app repo).

## What's here

```
neeh/
├── ink/         Point, Stroke, StrokeStyle, BoundingBox — the L0 substrate
├── document/    Layer, Page, Document + JSON snapshot serialization
├── canvas/      Canvas, Viewport, Selection, History (undo/redo) — the editing session
├── rendering/   Renderer protocol + reference SVG renderer, optional PNG rasterizer
├── tools/       The agent tool surface, registered with JSON Schemas (MCP-ready)
└── adapters/    Optional format adapters — UIM (Universal Ink Model) save/load
```

## Quickstart

```python
from neeh import Canvas
from neeh.tools import call_tool, tool_schemas

canvas = Canvas()

# An agent's session: look, draw, highlight, undo — every action attributable and reversible.
page_view = call_tool(canvas, "view_page", {"format": "png"})    # -> base64 PNG the model can see
strokes = call_tool(canvas, "get_strokes")                       # -> vector ink context
mark = call_tool(canvas, "add_stroke", {"points": [[100, 100], [200, 140], [300, 100]]})
call_tool(canvas, "highlight", {"region": [80, 80, 320, 160]})
call_tool(canvas, "undo")

print(tool_schemas())  # the manifest an MCP server / LLM tool-use loop exposes verbatim
```

## Design principles

- **Stable IDs everywhere.** `st_…`, `ly_…`, `pg_…` survive edits, moves, and serialization —
  an agent's reference to a stroke must not rot (the ink equivalent of line-number drift).
- **Time is a first-class axis.** Every point carries `t_ms`, every stroke `created_at_ms`.
  `page.strokes_since(...)` answers "what was written in the last 30 seconds" — something no
  screenshot pipeline can do.
- **Agent ink is never user ink.** Tool-created strokes are `author=agent` on a dedicated
  layer: attributable, filterable, undoable. User ink is never silently mutated.
- **Strokes are immutable; edits are commands.** Transforms produce new strokes with the same
  id, and every mutation flows through undoable `StrokeEdit`s.
- **Zero dependencies.** The core installs anywhere Python 3.10+ runs.

## Deliberately not here yet

Recognition, OCR, diagram understanding, embeddings, AI prompting, and the semantic graph are
out of scope for now — they arrive as pluggable layers (`plugins/`, `ai/`) once the substrate
is proven. There is no bespoke `.neeh` file format: persistence and interchange use the
Universal Ink Model (UIM) via `neeh.adapters.uim` (`pip install "neeh[uim]"` — the core stays
zero-dependency), and the built-in JSON (`Document.to_json()`) is an internal snapshot with no
compatibility promise. `write_text` currently supports a legible `print` style; `user_font`
remains reserved for the handwriting extraction from the Neeh app.

## Phase 0 spike

`examples/assistant/` is the current magic-loop spike: a local drawing page sends both a PNG and
Ink Context Format v0 stroke JSON to Codex CLI, then applies the returned tool actions as agent
ink. The draft model-facing context spec lives at `spec/ink-context-format.md`.

## Development

```bash
pip install -e ".[dev]"
pytest
```

License: TBD (Apache-2.0 planned).
