# Ink Context Format v1 — evidence-driven draft

Proposed protocol identifier: `ink-context/v1-draft`

Status: **draft under evaluation** — composed 2026-07-10 from the M1/E7 live results
([m1-findings.md](results/m1-findings.md)); open questions below are gated on the
completed M2 matrix and the S1 real-ink run. Promoted to `spec/` (as `ink-context/v1`)
only after those gates and the protocol §8/§9 criteria pass. ICF v0
([spec/ink-context-format.md](../spec/ink-context-format.md)) remains the shipped format
until then.

## What the evidence established

Every design decision below is traceable to a measured result (S0 synthetic,
codex-cli; 420 clean rows):

1. **Stroke IDs are the core value.** Addressing (T4) and stroke-targeted actions
   (T5 erase): raster = 0.000/impossible; every ID-bearing vector arm = 1.000.
   This is the capability that justifies ICF's existence.
2. **Geometry should ride in SVG path syntax, not bespoke JSON point arrays.**
   One `<path id=…>` per stroke scored 1.000 on addressing where a dense
   quantized stream (E2) mis-bound IDs to words (0.722); ICF v0's JSON points
   cost 6× more tokens for no accuracy gain on any family. SVG also tokenizes
   measurably better than a bespoke text format with near-identical characters
   (E7v layout: +189 tokens vs E2's +692).
3. **Layout-grade quantization is nearly free and loses nothing structural.**
   Integer grid (long edge 256) with ~4-grid-unit arc-length resampling holds
   1.000 on layout and addressing at a small fraction of full-precision cost.
4. **Drawn order carries the temporal signal.** Listing strokes in drawn order
   was sufficient for perfect temporal answers (T6: ICF arms 1.000, raster
   0.500 = chance). Per-point timestamps were not needed for these tasks.
5. **Raster is an optional fidelity add-on, not the foundation.** The compact
   SVG alone (E7v) transcribes at 0.910 for fewer tokens than the PNG itself;
   adding the PNG (E7) buys the last ~9% of transcription fidelity. Pixels are
   a tier you pay for when the task demands it.

## Draft data model

A v1 payload is a UTF-8 JSON object:

```json
{
  "schema": "ink-context/v1-draft",
  "page": { "id": "pg_...", "width": 1000.0, "height": 1414.0, "background": "#ffffff" },
  "raster": {
    "format": "png",
    "transport": "none",
    "coordinate_space": "page",
    "region": null
  },
  "ink": {
    "encoding": "svg-paths/grid",
    "grid": [181, 256],
    "drawn_order": true,
    "region": null,
    "stroke_count": 74,
    "included_stroke_count": 74,
    "omitted_older_stroke_count": 0,
    "truncated": false,
    "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 181 256\">\n<path id=\"st_...\" d=\"M18 18l4 0 ...\"/>\n</svg>"
  },
  "semantics": []
}
```

Changes from v0, with rationale:

| v0 | v1 draft | Why (evidence) |
|---|---|---|
| `vector.strokes`: JSON records with `points_sample` arrays | `ink.svg`: one `<path id>` per stroke, `M x y` + relative `l` offsets on an integer grid | #2, #3 — 1.000 addressing at ~1/9 of v0's cost |
| `raster.transport` MUST be `attached_image` | `transport` is `attached_image` **or** `none` | #5 — text-only holds most of the frontier |
| per-point `[x, y, t_ms, pressure, tilt, tilt]` | geometry only; temporal = drawn order (`drawn_order: true`) | #4 — order sufficed; per-point time/pressure never paid for itself in any task family |
| per-stroke `layer_id`, `author`, `style`, `created_at_ms`, `bbox` records | omitted from the wire by default | none of these earned tokens in any measured family; see open questions |

Kept from v0 unchanged: the page record; coordinate conventions (top-left origin,
y down); region semantics (bbox intersection, `ink.region == raster.region`);
newest-tail deterministic truncation with the four count invariants; the
`semantics` list (closed shape, stroke references must resolve); image bytes
never inside the JSON.

### The `ink` member

- `encoding` MUST be `svg-paths/grid` in this draft. Future encodings get new
  identifiers, not silent changes.
- `grid` is `[grid_w, grid_h]`: the page scaled so its long edge is 256 (default)
  and rounded to integers. Path coordinates are grid cells. The consumer maps
  back to page units via `page.width / grid_w`.
- `svg` contains one `<path>` per included stroke, in drawn order (document
  layer order, then stroke order — same as v0 eligibility order). Path data is
  `M x y` (absolute grid start) followed by `l dx dy ...` (relative offsets of
  arc-length-resampled points, step ≈ 4 grid units). No style attributes.
- `drawn_order` MUST be `true` in this draft (a later version may admit
  re-sorted subsets, which would set it to `false`).

## Fidelity tiers

One request-time choice, since no single fidelity wins all task families:

| tier | payload | measured cost/score profile |
|---|---|---|
| **structure** (default) | `ink.svg` only, `transport: none` | layout 1.000 @ +189 tok; addressing 1.000 @ +1474; transcription 0.910 @ +1186 (synthetic) |
| **perception** | `ink.svg` + `ink.bboxes` + attached PNG | real ink: classification/layout/addressing/temporal 1.000; handwriting reading 0.672 @ +3.4k tok — matches full ICF v0 (0.664 @ +11.1k) at 30% of the cost (E7b, real-ink-findings.md) |
| **archive** | ICF v0 payload | full points/time/pressure; 6-9× cost; for provenance and replay, not routine model context |

**Frame rule** (from E7b's action failures): path geometry is grid-quantized,
but every coordinate a consumer might echo back into a tool call — `ink.bboxes`,
regions, semantic boxes — is in **page units**. A model must never need a frame
conversion to act.

## Open questions (gated on pending results)

1. **Style/author metadata.** No measured family needed them. S1/S2 tasks that
   distinguish authors or colors may justify optional `data-author`-style
   attributes; until then they stay off the wire. (M2 E5/E6 rows + S1 run.)
2. **Cluster/semantic pre-summaries.** E5's scene-graph was the smallest
   encoding measured; if its M2 counting/action scores hold, an optional
   producer-side `semantics` population (kind=cluster) may join the draft.
3. **Grid resolution.** 256 was inherited from Google's ink-tokenization recipe
   and never swept. A resolution sweep (128/256/512) belongs in M3 before v1
   freezes; transcription fidelity is the sensitive family.
4. **Real-ink robustness.** All numbers above are synthetic S0; the S1
   Quick, Draw! sweep must confirm before any promotion (protocol §5 risk 3).

## Reference implementation

`neeh.context.build_ink_context_v1()` (and the bare-string
`neeh.context.build_ink_paths()`) implement this draft; the harness arm
`E7v/0.1.0` is the evaluated encoding and the SDK builder is tested to produce
byte-identical `svg` output for the same page.
