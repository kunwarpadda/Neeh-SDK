# Neeh Python API reference

The curated public surface, by module. Anything not listed here is internal
and may change without notice. Optional dependencies are loaded lazily: every
module below imports without Pillow or the UIM library installed; only the
calls that actually need them do (`neeh[png]`, `neeh[uim]`).

## `neeh` — ink model and rendering

Core value types (immutable):

- `Point(x, y, t_ms=0, pressure=1.0, tilt_x=0.0, tilt_y=0.0)` — one sample;
  `t_ms` is an offset from the owning stroke's `created_at_ms`.
- `Stroke(points, style=..., id=..., author=..., created_at_ms=...)` — an
  immutable timestamped point sequence with a stable `st_*` id, `bbox`, and
  `duration_ms`.
- `StrokeStyle(color, width, brush, opacity)`, `Brush`, `Author` (user/agent).
- `BoundingBox(min_x, min_y, max_x, max_y)` — `contains`, `contains_box`,
  `intersects`, `union`, `expanded`, `center`, `from_points`, `union_all`.

Structure:

- `Document` — pages; `to_dict`/`from_dict`, `to_json`/`from_json`,
  `save`/`load` (`neeh/v…` JSON snapshot).
- `Page` — layers, size, background, `rect`; `Layer` — strokes, visibility,
  lock state.
- `Canvas(document=None)` — one editing session; see `neeh.canvas` below.

Model context:

- `build_ink_context(page)` / `build_ink_context_v1(page)` — Ink Context
  Format snapshots (`ink-context/v0`, `/v1`).
- `build_ink_index(page)` — the structured mark index (stable ids, shape,
  position) used as cheap, groundable model context.
- `build_ink_paths(page)` / `parse_ink_paths(text)` — addressable stroke
  geometry as text; `ParsedInkPath`, `InkContextError`.

Rendering:

- `render_page_svg(page, region=None, scale=1.0)` and `SvgRenderer`.
- `render_page_ascii(page)` — token-cheap gestalt view.
- `neeh.rendering.png.render_page_png(page, region=None, scale=1.0)` —
  requires `neeh[png]`.

## `neeh.canvas` — editing session and history

- `Canvas.add_stroke(points, style=None, author=USER, layer=None,
  created_at_ms=None)` — validated, undoable; explicit `created_at_ms` for
  synthetic/timed ink. Also `add_strokes`, `add_styled_strokes`, `erase`,
  `move`, `undo`, `redo`, `select`, `strokes_in_view`.
- `Canvas.group(stroke_ids, label=None) -> group_id`, `ungroup(group_id)`,
  `groups()` — grouping recorded as events, membership folded from the log.
- `Canvas.events -> EventLog` — the append-only document event log
  (`ink-eventlog/v1`):
  - `events`, `head_seq`, `for_stroke(id)`
  - `replay(to_seq=None)` — live strokes at any past sequence point
  - `snapshot(stroke_id, at_seq=None)`, `diff(from_seq, to_seq=None)`
  - `recover(stroke_id)` — last snapshot of erased ink
  - `to_dict()` (compact) / `to_snapshot()` + `from_snapshot()` (full round trip)
- `Canvas.session_snapshot()` / `save_session(path)` / `load_session(path)` —
  `neeh-session/v1` bundle of document + event log.
- `History`, `StrokeEdit`, `DocumentEvent`, `Selection`, `Viewport`.

## `neeh.agents` — analyzers, reducers, and the agent interface

Deterministic analysis (`ink-analysis/v1`; every result carries
`claim_type: measurement | inference`, inferences carry confidence +
provenance):

- `analyze_ink(canvas, operation, *, stroke_ids=None, region=None, limit=16)`
  — operations in `ANALYSIS_OPERATIONS`: `latest_mark`, `creation_order`,
  `stroke_dynamics`, `containment`, `intersection`, `endpoints`,
  `spatial_collision` (measurements); `cross_out_candidates`,
  `connector_candidates`, `grouping_candidates` (inferences).
- `reduce_ink(canvas, task, *, region=None, since_ms=None, limit=8)` — tasks
  in `REDUCER_TASKS`: `recent_changes`, `overwritten_ink`, `revisions`,
  `ambiguous_connectors`, `page_summary`.

Temporal retrieval (`ink-timeline/v1`):

- `build_ink_timeline(page, config=None, event_log=None)` — with the event
  log, erased ink folds back in and `history_complete` is honestly claimed.
- `find_ink_moments(timeline, query, ...)`, `inspect_ink_moment(...)`,
  `TimelineConfig`.

Ink Agent Interface (`ink-agent-interface/v1`):

- `build_observation_workspace(canvas, task=None, *, policy="active-index",
  budget=None)` — budgeted bootstrap with intent routing (mechanical
  questions get their reducer pre-computed into `workspace["analysis"]`).
- `InkAgentInterface(canvas, task=None, *, policy, budget)` — stateful,
  budget-enforcing perception surface; `call(name, arguments)` for the typed
  actions (`find_marks`, `analyze_ink`, `reduce_ink`, `find_ink_moments`,
  `inspect_ink_moment`, `view_region`, `get_ink`, `expand_relations`);
  `telemetry()`, `workspace()`.
- `PerceptionBudget`, `PERCEPTION_POLICIES`
  (`raster-only | raster-always | index-only | active-index | marked-index`).
- `python -m neeh.agents.iai_mcp --state doc.json` — the read-only stdio MCP
  server exposing the same actions.
- Model runners: `run_codex_cli`, `run_claude`, `run_mock`,
  `agent_input_preview`, `ModelUnavailableError`.

## `neeh.tools` — validated edit tools

- `tool_schemas()` / `tool_manifest()` — JSON-Schema tool surface
  (`neeh-tools/v1`).
- `call_tool(canvas, name, arguments)` — validated, undoable edits.
- `all_tools()`, `get_tool(name)`, `ToolSpec`, `@tool`.

## `neeh.protocol` — discovery

- `protocol_versions()` — the stable manifest.
- `experimental_protocol_versions()` — fixture-backed, not yet stable
  (see `spec/fixtures/` and docs/RELEASING.md for the graduation rule).

## `neeh.adapters.uim` — interchange (requires `neeh[uim]`)

- `save_uim(document, path, *, event_log=None)` / `load_uim(path)` — UIM 3.1
  via the `neeh-uim/v1` profile; the optional event log persists as a
  `<name>.events.json` sidecar, read back by `load_uim_events(path)`.
