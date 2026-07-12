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
- source and matched stroke counts;
- operation-specific bounded evidence.

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

### `cross_out_candidates`

Returns bounded timeline episodes whose geometry suggests a later open stroke
passes through older ink. Candidates remain hypotheses and include affected
prior ids plus `history_complete`; they are not asserted as user intent.

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

