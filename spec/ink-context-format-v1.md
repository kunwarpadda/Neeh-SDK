# Ink Context Format v1

Protocol identifier: `ink-context/v1`

Status: promoted 2026-07-10 from `ink-context/v1-draft`. Every normative rule
in this document traces to a measured result in `research/results/` (evidence
pointers inline); the evaluation protocol is `research/protocol-m0.md`. The
key words MUST, MUST NOT, SHOULD, and MAY are normative.

ICF v1 is the model-facing snapshot of one ink page. It replaces v0's JSON
point arrays with grid-quantized SVG paths at roughly 1/6th to 1/9th the
context cost, at equal or better task accuracy (m1-findings.md,
real-ink-findings.md). ICF is not a persistence format ([UIM profile
v1](uim-profile-v1.md)) and not a tool schema ([tool surface
v1](tool-surface-v1.md)).

## Envelope

A v1 payload is a UTF-8 JSON object with exactly these top-level members:

| member | requirement |
|---|---|
| `schema` | MUST be `"ink-context/v1"` |
| `page` | MUST hold `id`, `width`, `height`, `background` (page units, hex color) |
| `raster` | MUST describe the raster tier (see *Tiers*); no image bytes in the JSON |
| `ink` | MUST hold the geometry block (below) |
| `semantics` | MUST be an array (possibly empty) of semantic items (v0 item shape) |

## The `ink` block

| field | rule |
|---|---|
| `encoding` | MUST be `"svg-paths/grid"` |
| `grid` | `[grid_w, grid_h]`, integer grid covering the page; long edge SHOULD be 256 (evidence: resolution is not the transcription bottleneck — E7v512 ≈ E7v, real-ink-findings.md) |
| `svg` | one `<path>` per stroke; `id` attribute MUST be the stable stroke id; `d` MUST be absolute `M x y` + relative `l dx dy …` on integer grid cells; paths MUST appear in drawn order (drawn order carries the temporal signal: T6 1.000 vs raster chance) |
| `drawn_order` | MUST be `true` |
| `bboxes` | OPTIONAL map stroke id → `[min_x, min_y, max_x, max_y]` in **page units** — the segmentation cue that recovers full-vector reading accuracy at ~30% of its cost (E7b) |
| `rate_point` | present when the builder ran rate control: the chosen `grid_long_edge` and `simplify_eps_grid` |
| `stroke_count` / `included_stroke_count` / `omitted_older_stroke_count` / `truncated` | stroke budget accounting; when capped, producers MUST keep the newest strokes |
| `region` | the page-unit region this snapshot covers, or `null` for the whole page |

Producers SHOULD apply polyline simplification (RDP, tolerance ~1 grid unit)
before quantization: it cuts characters ~38% and *raises* structure-task
scores (E7vS: addressing 0.778 → 1.000; corroborated by SVGenius's
complexity finding).

## The frame rule (normative)

Path geometry is grid-quantized; **every coordinate a consumer might echo
back — `ink.bboxes`, `semantics` regions, `ink.region` — MUST be page
units.** A model must never need a frame conversion to act. Violations are
measured, not hypothetical: grid-unit bboxes collapsed action grounding to
0.167; page-unit bboxes restored 0.833 (real-ink-findings.md). Any prose
legend accompanying the payload SHOULD state the grid→page scale factor.

## Tiers

| tier | composition | measured profile |
|---|---|---|
| **structure** (default) | `ink.svg` only, `raster.transport: "none"` | layout/addressing/temporal at or near 1.000; cannot classify drawings or read handwriting |
| **perception** | `ink.svg` + `ink.bboxes` + attached full-scale PNG | everything, incl. reading at full-vector parity (0.672 ≈ 0.664) at 30% of v0's cost |
| **gestalt raster** | perception tier with a quarter-scale raster | classification/layout/addressing 1.000 at ~40% of perception cost; reading degrades with resolution (0.672 → 0.481) |
| **archive** | ICF v0 payload | provenance/replay only; 6–9× cost |

Raster cost is pixel-metered by current providers, not byte-metered (E8j:
JPEG q40 = identical tokens, half the bytes, small legibility tax). Producers
SHOULD choose raster scale, not compression codec, to control cost.

Rate control: `build_ink_context_v1(char_budget=…)` walks the fidelity
ladder (512 grid → 256 → 256+RDP → 128+RDP) and returns the best payload
that fits, recording the operating point in `ink.rate_point`.

## The pull extension (foveated context)

For dense pages, a producer MAY send only an index — `ink.bboxes` (and
optionally cluster `semantics`) with `ink.svg` omitted — and expose the
`fetch_ink_region` tool (tool surface v1): region in page units → compact
SVG + bboxes for the strokes intersecting it. Measured (H7, T8 episodes):
accuracy holds (addressing 1.000), ink content read drops ~86%, and the
vector fetch is strictly more capable than a raster crop, which cannot
address (0.000). The pull regime pays off in persistent sessions; one-shot
transports pay per-call scaffolding twice and SHOULD push instead.

## Consumption guidance (informative)

- Counting/gist: attach cluster items in `semantics` (E5: counting 1.000 at
  +260 tokens where flat listings over-count).
- Reading handwriting: use the perception tier; text-only geometry reads
  poorly regardless of fidelity (E1b 0.354, E7v 0.421 vs E1a 0.664).
- Legend wording is not load-bearing (E7vB ≈ E7v); the encoding is.

## Changelog

- v1 (2026-07-10): promoted from v1-draft. Evidence chain:
  results/m1-findings.md → m2-findings.md → real-ink-findings.md →
  geometry-fidelity.md → embedded-coding-exhibit.md; 2,292-row ledger.
