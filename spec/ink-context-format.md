# Ink Context Format v0 Draft

Ink Context Format (ICF) is the model-facing snapshot that makes a page of ink legible to an
agent. It is not a persistence format. Persistence stays with the document adapter layer; ICF is
the payload a tool host sends to a model before asking it to read, reason, or act on ink.

## Status

Drafted from the Phase 0 assistant spike. The current working payload is implemented in
`examples/assistant/agent.py` and is intentionally small:

- one raster page image attached beside the prompt;
- one compact vector stroke snapshot derived from `get_strokes`;
- an empty semantic list reserved for recognizer output.

## Goals

- Give multimodal models the raster view they already understand.
- Give agents stable stroke ids, bounding boxes, timestamps, authorship, and points for precise
  references.
- Preserve enough time and layer data to distinguish user ink from agent ink and recent ink from
  older context.
- Leave a clear slot for future recognizers, scene graphs, search matches, and anchors without
  blocking the first demo on HWR.

## Non-Goals

- It is not the `.neeh`/UIM persistence format.
- It is not a live stroke-event stream.
- It is not a complete semantic scene graph.
- It does not define model prompts or provider-specific tool schemas.

## Top-Level Shape

```json
{
  "schema": "ink-context/v0",
  "page": {
    "id": "pg_...",
    "width": 1000.0,
    "height": 1414.0,
    "background": "#ffffff"
  },
  "raster": {
    "format": "png",
    "transport": "attached_image",
    "coordinate_space": "page"
  },
  "vector": {
    "page_id": "pg_...",
    "width": 1000.0,
    "height": 1414.0,
    "region": null,
    "stroke_count": 1,
    "strokes": []
  },
  "semantics": []
}
```

Coordinates are page units. The origin is top-left, x grows right, and y grows down. Raster and
vector data must use the same coordinate space.

## Raster Layer

The raster layer is the agent's broad perception path.

```json
{
  "format": "png",
  "transport": "attached_image",
  "coordinate_space": "page"
}
```

The image bytes are transported outside the JSON payload because model APIs handle images as
separate input blocks. In local demos this is the PNG attached to `codex exec --image`.

Future versions may add:

- `region`: page-space crop bounds;
- `zoom`: render scale;
- `tile_id`: stable id for large-page tiling;
- `sha256`: digest for caching and traceability.

## Vector Layer

The vector layer is the precision read path. It is currently produced by `get_strokes`.

```json
{
  "id": "st_...",
  "layer_id": "ly_...",
  "layer_name": "ink",
  "author": "user",
  "created_at_ms": 1783639700000,
  "duration_ms": 80,
  "bbox": [100.0, 100.0, 260.0, 140.0],
  "style": {
    "color": "#1a1a1a",
    "width": 2.0,
    "opacity": 1.0,
    "brush": "pen"
  },
  "point_count": 3,
  "points_sample": [
    [100.0, 100.0, 0, 1.0, 0.0, 0.0],
    [180.0, 140.0, 40, 1.0, 0.0, 0.0],
    [260.0, 100.0, 80, 1.0, 0.0, 0.0]
  ]
}
```

Point tuple order is `[x, y, t_ms, pressure, tilt_x, tilt_y]`.

Rules:

- `id` must be stable across move/style edits.
- `author` must be `user` or `agent`.
- `created_at_ms` is epoch milliseconds.
- `t_ms` is a per-stroke offset from `created_at_ms`.
- Agent-created output must stay on an agent-authored layer.

The underlying `get_strokes` tool can return full `points`. Prompt payloads should compact this
to `points_sample` by default, keeping `point_count` and `bbox`. This prevents long drawing
sessions from overflowing model context while preserving enough geometry for spatial reasoning.

## Semantic Layer

`semantics` is reserved for recognizer output. It starts empty in Phase 0.

Proposed item shape:

```json
{
  "id": "rg_...",
  "kind": "handwritten_text",
  "region": [80.0, 80.0, 340.0, 180.0],
  "stroke_ids": ["st_..."],
  "text": "x^3 = ?",
  "confidence": 0.83,
  "source": "multimodal_llm"
}
```

The semantic layer should reference stroke ids or page-space regions rather than duplicating raw
ink.

## Phase 0 Tool Mapping

Current tools:

- `view_page(format="png")` and `view_region` produce raster context.
- `get_strokes` produces vector context.
- `add_stroke`, `highlight`, and `write_text` produce agent ink.
- `undo` and `redo` keep the loop reversible.

Planned tools from `NEEH_SDK_PLAN.md` map cleanly onto this draft:

- `describe_page` fills `semantics`;
- `search_ink` returns semantic or vector matches;
- `get_events` streams deltas instead of full snapshots;
- `anchor` creates durable semantic references.

## Open Questions

- Should `schema` become `icf_version` before publication?
- Should region ids be deterministic from stroke ids and geometry?
- How much vector data should be sent by default before switching to tiling or summaries?
- Should tool responses include an ICF delta after each action?
