# Ink Agent Interface v1

Status: experimental SDK protocol. IAI v1 defines the model-facing observation
workspace and read-only perception actions used by the reusable assistant
adapters. It is additive to Ink Context Format and Tool Surface v1.

## Design boundary

IAI separates two surfaces that have different safety and context properties:

- **Perception actions** are read-only and budgeted. They expand the model's
  working context without changing the page.
- **Edit actions** remain the existing Neeh tools. The assistant validates a
  complete batch on a document clone before applying it to the live canvas.

The default loop is bounded:

1. localize from the bootstrap page map;
2. inspect only when the map is insufficient;
3. plan a complete edit batch;
4. validate the batch atomically;
5. allow one repair plan if validation fails;
6. apply only a fully valid batch.

## Observation workspace

`build_observation_workspace(...)` returns a JSON object with
`schema="ink-agent-interface/v1"`:

| Field | Meaning |
|---|---|
| `policy` | One of the evaluation/production policies below. |
| `task` | Stable task semantics for this turn. |
| `page_map` | Budgeted `ink-index/v1`, ranked marks, compact relations, recorded groups (exact membership folded from the event log), and optional marked view. |
| `recent_delta` | New user strokes since the latest agent ink, with stable ids and bboxes. |
| `analysis` | Optional deterministic evidence precomputed from an unambiguous task intent. |
| `timeline_map` | Budgeted `ink-timeline/v1` creation episodes for active policies. |
| `working_set` | Moment ids, regions, and stroke ids promoted during this trajectory. |
| `budget` | Hard limits for marks, actions, text observations, and raster pixels. |
| `capabilities` | Typed perception actions available under the selected policy. |
| `bootstrap_chars` | Serialized bootstrap size for telemetry and budget verification. |

Marks are ranked by task/label match, current selection, recognized relations,
recency, and authorship. `find_marks` searches the full index even when the
bootstrap includes only its highest-ranked slice.

IAI currently precomputes `latest_mark` for latest/most-recent/last-drawn
questions and `cross_out_candidates` for explicit cross-out questions. Other
operations remain callable so ambiguous intent does not trigger a confident
local conclusion.

## Perception policies

| Policy | Bootstrap | Perception actions |
|---|---|---|
| `raster-only` | Attached raster and page/crop metadata only | None; clean temporal control |
| `raster-always` | Attached raster plus compact ICF geometry | None |
| `index-only` | Structured page map | None; strict ablation |
| `active-index` | Structured page map | All IAI actions |
| `marked-index` | Page map plus ASCII Set-of-Marks and legend | All IAI actions |

`index` and `raster` are assistant compatibility aliases for `active-index` and
`raster-always`.

## Perception actions

### `find_marks`

Search the full ranked map by stable id, shape, or position. Results remain
bounded by `limit` and preserve rank.

### `analyze_ink`

Run a deterministic reducer for `latest_mark`, `creation_order`,
`stroke_dynamics`, or `cross_out_candidates`. These operations collapse a
potentially large page to bounded exact evidence before using LLM context.
The response contract is documented in
[`ink-analysis-v1.md`](ink-analysis-v1.md).

### `view_region`

Inspect one page-space region as `raster` or `ascii`. Raster calls consume the
raster-pixel budget; ASCII data consumes the text-observation budget.

### `find_ink_moments`

Rank creation episodes against the instruction and optional region/object
constraints. Ranking balances relevance with coverage and novelty, then
promotes returned evidence into the working set.

### `inspect_ink_moment`

Expand one episode as `before`, `after`, `current`, `diff`, or bounded `replay`
evidence. The response explicitly reports whether destructive history is
complete.

### `get_ink`

Retrieve addressable detail by exactly one of `stroke_ids` or `region`:

- `bboxes` returns compact stroke records without points;
- `paths` returns stroke points for ids or compact SVG paths for a region.

### `expand_relations`

Return recognizer clusters and directed links connected to a stroke or semantic
id. This is the ink equivalent of expanding dependencies from a repository map.

## Budget behavior

`PerceptionBudget` limits:

- bootstrap marks and serialized characters;
- perception action count;
- cumulative textual observation characters;
- cumulative raster pixels;
- recent-delta stroke records.
- bootstrap moments and replay steps.

An action that would cross a limit returns a concise error. Invalid attempts
consume an action slot so repeated malformed retrieval cannot bypass the
trajectory bound.

## CLI transport

`neeh.agents.iai_mcp` exposes the perception actions as a read-only stdio MCP
server over a temporary internal Neeh document snapshot. Codex and Claude get a
fresh server per planner invocation. The server cannot mutate the live canvas;
edit actions still arrive through the bounded final JSON plan.

Active policies materialize only the internal page snapshot consumed by the
read-only MCP server; they do not expose raw raster/detail files that could
bypass telemetry. `raster-always` separately materializes and attaches its
control raster.

## Validation and telemetry

The assistant result includes:

- `perception_policy`;
- `validation.{passed,repair_attempted,failure_count}`;
- `perception_telemetry` with bootstrap characters, action types/count,
  observation characters, raster pixels, and an estimated token footprint.
- moment query count, replay steps, and promoted working-set sizes.
- deterministic analyzer query count.

`examples/evaluate_perception_policies.py` runs P0-P4 over read, point,
annotate, and identical-raster temporal cases. It scores tool choice, exact
target ids, answer text, validation success, repair use, escalation behavior,
and estimated context cost. `--dry-run` reports bootstrap economics without
invoking a model.
