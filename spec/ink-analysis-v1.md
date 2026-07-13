# Ink Analysis v1

Status: experimental SDK protocol. `ink-analysis/v1` defines deterministic,
bounded evidence returned by local ink reducers. It is used through IAI's
`analyze_ink` perception action and is not yet part of stable protocol
discovery.

## Principle

Do not ask a language model to search or calculate over a page when Neeh can
compute the answer exactly. The analyzer reads the complete local document but
returns only task-relevant evidence. Prompt cardinality is therefore bounded by
the operation, not page stroke count.

Every response includes:

- `schema="ink-analysis/v1"`;
- the requested `operation`;
- `deterministic=true`;
- `claim_type`, either `"measurement"` or `"inference"` (see below);
- source and matched stroke counts;
- operation-specific bounded evidence.

## Measurements versus inferences

Operations fall into two explicitly separated classes so a caller never
confuses an exact fact with a recognizer guess:

- **Measurements** (`claim_type="measurement"`) are exact geometric or temporal
  facts read directly off the document: `latest_mark`, `creation_order`,
  `stroke_dynamics`, `containment`, `intersection`, `endpoints`,
  `spatial_collision`. Their values are ground truth.
- **Inferences** (`claim_type="inference"`) are recognizer-style hypotheses:
  `cross_out_candidates`, `connector_candidates`, `grouping_candidates`. Every
  inferred item carries a `confidence` in `[0, 1]` and a `provenance` block
  naming the exact measurement(s) it was derived from. These are candidates,
  never asserted as user intent.

## Operations

### `latest_mark`

Returns one latest visible stroke after optional region/id filtering. Ordering
uses stroke end time, then start time, then stable page order. The result
contains id, time, bbox, center, page halves, direction, duration, and pressure
summary.

### `creation_order`

Requires explicit stroke ids and returns their bounded chronological order.
Unknown ids fail rather than silently disappearing.

### `stroke_dynamics`

Requires explicit stroke ids and returns bounded direction, duration, pressure,
position, and time evidence.

### `containment` (measurement)

Requires a `region`. Splits the region-matched strokes into `contained` (bbox
fully inside the region) and `partial` (overlaps the region boundary). Both
lists are bounded by `limit`.

### `spatial_collision` (measurement)

Returns bounded pairs of strokes whose bounding boxes overlap, each with the
exact `overlap` box. This is a fast, bbox-level test and may over-report
relative to true path crossings — use `intersection` when exactness matters.

### `intersection` (measurement)

Returns bounded pairs of strokes whose actual polylines cross, with the exact
crossing point `at`. Unlike `spatial_collision` this tests real segment
geometry, so bbox-overlapping-but-non-crossing pairs are excluded.

### `endpoints` (measurement)

Requires explicit stroke ids. Returns each stroke's exact `start` and `end`
coordinates, the page half of each endpoint, straight-line `displacement`, and
direction. Bounded by `limit`.

### `cross_out_candidates` (inference)

Returns bounded timeline episodes whose geometry suggests a later open stroke
passes through older ink. Candidates remain hypotheses and include affected
prior ids, a `confidence`, a `provenance` block, and `history_complete`; they
are not asserted as user intent.

### `connector_candidates` (inference)

Returns strokes whose two endpoints each land within a page-relative margin of
two *distinct* other strokes, suggesting an arrow or link between them. Each
candidate names `from_id`/`to_id`, a `confidence` that decreases with endpoint
gap, and a `provenance` block with the measured gaps and margin.

### `grouping_candidates` (inference)

Returns spatial clusters of strokes (connected components under a page-relative
bbox-proximity margin). Each group carries its `member_ids`, union `bbox`,
`size`, a compactness-based `confidence`, and a `provenance` block. Bounded by
`limit`.

## Task reducers

Beyond the primitive operations above, `reduce_ink` composes them into
task-shaped answers through IAI's `reduce_ink` perception action. Each result
carries the same envelope (`schema`, `claim_type`, source/matched counts) keyed
by `task` instead of `operation`.

- `recent_changes` (measurement): the most recently ended strokes, newest
  first, with `ms_since_latest`; accepts an optional `since_ms` cutoff.
- `overwritten_ink` (inference): later strokes whose bbox overlaps an earlier
  stroke's, with overlap coverage and time gap as provenance.
- `revisions` (inference): a unified list merging `overwritten_ink` and
  `cross_out_candidates` into `overwrite`/`cross_out` revision events.
- `ambiguous_connectors` (inference): connector strokes whose endpoint has two
  near-tied target strokes, so which object it links is unclear.
- `page_summary` (measurement): exact page aggregates -- stroke count, author
  breakdown, time span, union bbox -- plus grouping candidates.

## Measured token cost

For the latest-mark task, analyzer prompt cost stayed approximately constant:

| Marks | Estimated tokens |
|---:|---:|
| 4 | 268 |
| 16 | 269 |
| 48 | 269 |
| 128 | 270 |
| 320 | 270 |

At 320 marks, the full coordinate arm used about 8,554 tokens and the compact
all-mark index used about 4,712. The analyzer computes the exact reduction
locally and exposes one typed record. This is the active alternative to a
learned fixed-size encoder.

## Boundary

Analysis does not replace perception. Handwriting, ambiguous diagrams, and
uncertain semantic intent may still require recognition, targeted geometry, or
raster evidence. The policy is:

1. exact analyzer when available;
2. structured retrieval for addressable evidence;
3. raster/path detail on demand;
4. model reasoning over the bounded result;
5. validated edit tools.

