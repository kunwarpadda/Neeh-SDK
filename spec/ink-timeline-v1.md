# Ink Timeline v1

Status: experimental SDK protocol. `ink-timeline/v1` is the temporal index
behind Ink Moment Retrieval. It complements the spatial `ink-index/v1` and is
exposed to models through the Ink Agent Interface (IAI).

## Purpose

A final page raster cannot answer questions about stroke direction, creation
order, pauses, pressure, or later overlays. Sending every raw point is also too
expensive. Ink Timeline groups the sparse event stream into stable creation
episodes ("ink moments") that can be ranked against the current instruction and
expanded only when needed.

The design borrows three useful patterns from long-video systems without
pretending ink is dense video:

- relevance plus coverage under a fixed context budget;
- instruction-conditioned temporal retrieval;
- coarse-to-fine inspection of a selected episode.

The retrieval unit is an episode of related strokes, not an individual point.

## Timeline object

`build_ink_timeline(page)` returns:

| Field | Meaning |
|---|---|
| `schema` | `ink-timeline/v1`. |
| `page_id` | Page the timeline describes. |
| `history_complete` | Whether the source contains destructive revision history. |
| `history_limitations` | Explicit missing evidence. |
| `episode_gap_ms` | Maximum temporal gap used while grouping nearby strokes. |
| `moment_count` | Total episode count. |
| `moments` | Ordered creation episodes. |

Each moment has a stable content-derived id, time interval, bbox, stroke ids,
authors, coarse event types, directions, affected prior ids, and per-stroke
features. Per-stroke features include duration, path length, direction, pause,
pressure statistics, tilt magnitude, point count, and bbox.

`cross_out_candidate` is intentionally evidence, not a semantic fact. It means
a later elongated open stroke passes through the interior of prior ink. Product
code should retain the distinction until a recognizer or user confirms intent.

## Episode grouping

Visible strokes are ordered by absolute point time, with page order as a stable
tiebreak. Consecutive strokes join one moment when:

1. their temporal gap is within `episode_gap_ms`;
2. the new stroke touches the episode bbox expanded by the spatial margin; and
3. the episode has not crossed its stroke-count bound.

Moment ids are deterministic hashes of the page id and ordered stroke ids.

## Retrieval

`find_ink_moments(...)` accepts a query plus optional page region and object
ids. Ranking combines:

- lexical and temporal-intent relevance;
- object and region matches;
- cross-out, pause, order, and direction evidence;
- recency;
- a novelty penalty so results cover distinct parts of the timeline.

The IAI action promotes returned moment ids, stroke ids, and regions into the
trajectory working set.

## Inspection

`inspect_ink_moment(moment_id, view)` supports:

| View | Evidence |
|---|---|
| `before` | Nearby strokes completed before the episode. |
| `after` | Nearby strokes present through the episode end. |
| `current` | Current nearby visible strokes. |
| `diff` | Strokes added by the episode plus affected prior ids. |
| `replay` | Bounded ordered creation steps and directions. |

Replay is structured evidence rather than a generated video. A model may call
IAI `view_region` separately when pixels are useful.

## Honest history boundary

The current Neeh document snapshot stores present strokes with creation and
point timing, pressure, tilt, authorship, and stable ids. It does not retain
erased strokes or undone edits. Therefore v1 sets `history_complete=false` and
must not manufacture destructive history. A future append-only document event
log can make the same protocol complete without changing its model-facing
retrieval shape.

## Evaluation

The perception-policy harness contains controlled pairs whose final PNG bytes
are identical but whose trajectories run in opposite directions. `raster-only`
and static-index arms have no evidence for the correct answer; temporal IAI
arms receive direction evidence. The older `raster-always` arm retains compact
SVG geometry and therefore is not a valid direction-blind control. Reports
record tool/action correctness, answer text, telemetry, model id, and reasoning
effort.
