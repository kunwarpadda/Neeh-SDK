# Real-ink findings — S1 (Quick, Draw!) + S2 (MathWriting)

*2026-07-10. S1: 294 cells (6 composed sketch pages × 6 arms + CTRL × all six
families). S2: 36+ cells (6 handwritten-math pages, T1 LaTeX transcription,
raw CER). All at the low-effort condition, 0 failures. This is the protocol's
synthetic-vs-real gate (§5 risk 3) for the ICF v1 draft.*

## The tier split is real, and it's clean

Every synthetic **capability** result replicated on real ink; every synthetic
**perception ceiling** broke. That divides the format exactly along the v1
draft's tier boundary:

**Structure tier holds on real ink** (compact SVG, ~+1.2k tok):

| family | E7v | E0 raster | verdict |
|---|---|---|---|
| T4 addressing | 0.778 (E1a/E7: **1.000**) | 0.000 | ids work; raster can't |
| T6 temporal | **1.000** | 0.333 (chance) | drawn order works; raster can't |
| T3 layout | 0.917 | 1.000 | near-parity at 2/3 the cost |

**Perception needs pixels** (classify a drawing, read handwriting):

| task | best text-only | with raster |
|---|---|---|
| S1 classify drawings | E7v 0.500, E2 0.333, E5 0.000 | E0/E1a/E7 **1.000** |
| S2 transcribe math (raw CER) | E7v 0.421, E7v512 0.402 | E0 0.517, **E1a 0.664** |

## Headline: the hybrid wins real ink

**E7 (PNG + compact SVG) is the only arm at 1.000 on S1 classification,
layout, AND addressing — at +2,988 tokens, half of E1a's +5,708.** On real
sketch pages the hybrid does everything the full ICF does at half its cost,
and everything raster does plus the things raster cannot.

## S2: what vector adds to reading, and what it doesn't

- **E1a (PNG + full ICF) reads handwriting at 0.664 vs raster-alone 0.517**
  — vector structure adds real perception signal beyond pixels (+0.15 CER on
  the same pages). On synthetic ink this was invisible at the ceiling.
- **Resolution is not the bottleneck:** E7v512 ≈ E7v-256 (0.402 vs 0.421).
  Draft open question #3 is answered — do not spend characters on finer
  grids; whatever full ICF adds (per-stroke bboxes/segmentation cues), it is
  not coordinate precision. E7 ≈ E0 (0.516 vs 0.517) confirms the compact
  SVG contributes ~nothing to *reading*.
- **The E1b addendum settles the mechanism: vector is complementary, not a
  reading channel.** Full ICF vector *alone* scores 0.354 — worse than the
  compact SVG alone (0.421) — yet the same payload beside a PNG scores
  0.664 vs the PNG's 0.517. Dense point JSON drowns the model on its own,
  but paired with pixels it contributes segmentation structure the raster
  lacks. Reading order on S2: E1b 0.354 < E7v512 0.402 < E7v 0.421 <
  E7 0.516 ≈ E0 0.517 < **E1a 0.664**.
- **E7b ran same-day and settled it: bboxes ARE the missing cue.** Raster +
  compact SVG + per-stroke bboxes reads at **0.672 for +3,352 tok** —
  matching E1a's 0.664 at +11,104 (30% of the cost) — while holding 1.000
  on S1 classification, layout, addressing, AND temporal (it even fixes
  E7's T6 dip). The perception tier's composition is settled.
- **E7b also weaponized the frame bug**: its T5 dropped to 0.167 because
  the grid-unit `data-bbox` values look like ready-made region answers and
  get copied into tool calls unconverted. The v1 design rule that falls
  out: **geometry may be grid-quantized, but any coordinate a consumer
  might echo back (bboxes, regions, semantics) must be page units.**
  `build_ink_context_v1(stroke_bboxes=True)` implements exactly that;
  an E7b/0.2.0 harness arm with page-unit bboxes + the conversion note
  should re-measure T5.
- Real handwritten math is hard, full stop: the best arm reads at 0.664.
  Transcription-grade ICF claims need recognizer support (semantics layer),
  not more geometry.

## Weaknesses surfaced on real ink

- **E2 (QRP) degrades badly on messy strokes** (0.333–0.667 everywhere).
  Its S0 numbers were flattered by clean synthetic geometry. E7v's SVG
  syntax degrades much more gracefully from the same underlying resampling.
- **E5 cannot classify real drawings** (T1 = 0.000) and lost its counting
  edge on sketch pages (0.833, tied with everything). It remains a
  cheap-gist/counting layer for structured content, not a perception
  channel.
- **E7's T5 action dip (0.500)** continues the M2 coordinate-frame story;
  the explicit grid→page conversion note (now shipped in the assistant
  demo's v1 prompt) is the candidate fix, to be re-measured as E7/0.2.0.
- T2 counting: every arm scored 0.833 — the same one composed page trips
  all of them; inspect that page before reading anything into the family.

## Robustness follow-ups (same day)

- **The frame rule fixes actions.** E7b/0.2.0 (bboxes in page units + the
  conversion note in the legend) took T5 from 0.167 to **0.833** — parity
  with the best arm on those tasks — while holding 1.000 on
  classify/layout/addressing/temporal and keeping reading at 0.658 ≈ 0.672
  (page-unit bboxes read as well as grid-unit ones). E7b/0.2.0 is the
  complete perception-tier encoding.
- **Legend sensitivity is small.** E7vB (identical geometry, rewritten
  legend): T1 0.903 vs 0.910, T3 1.000 vs 1.000, T4 0.944 vs 1.000 —
  differences within a few points, and the comparison additionally crosses
  the effort split, so the true wording effect is at most marginal. The
  encoding, not the prompt wording, carries the results (protocol §5
  risk 1 addressed).
- Repeats for variance bars: stopped by decision at 210 clean rows of the
  323-cell N=3 grid — enough for spot variance checks on the frontier
  arms (the ±sd(rep) column in summary.md fills where coverage exists);
  full bars were judged not worth further quota given the effect sizes.

## E8 family: the raster is elastic, and the ladder is measured

The thumbnail-raster hypothesis (raster carries gestalt, not precision)
resolved cleanly into a task-dependent rate-control ladder:

| arm | raster | S1 classify | S2 read | Δtok (S1) |
|---|---|---|---|---|
| E8s | quarter + RDP svg | **1.000** | 0.447 | **+1,211** |
| E8q | quarter-scale | **1.000** | 0.481 | +1,648 |
| E8 | half-scale | **1.000** | 0.538 | +2,079 |
| E7b | full-scale | 1.000 | **0.672** | ~+2,990 |

- **Classification survives a quarter-scale raster perfectly** — gestalt is
  cheap. E8s does everything the perception tier does except read, at 40%
  of E7b's cost.
- **Reading pays linearly for resolution** (0.672 → 0.538 → 0.481): E8q
  reads *worse than a full-res PNG alone* (0.517). Handwriting legibility
  is the one consumer of full-resolution pixels.
- Rate control has its table: reading task → full raster (E7b); anything
  else → E8s.

## E7vS: simplification IMPROVES comprehension (sleeper headline)

RDP simplification didn't just cut cost — it *raised scores* on structure
tasks: S1 addressing 0.778 → **1.000** and layout 0.917 → **1.000** at ~38%
fewer tokens than E7v. Fewer path points = clearer stroke identity for the
model, independently corroborated by SVGenius's finding that LLM SVG
competence degrades with path complexity. Reading dips slightly (0.368 vs
0.421) — detail still matters there. RDP becomes the recommended default
for the structure tier.

## H7 first data: pull works on accuracy; the CLI scaffold hides the win

T8 (dense 24-word pages, locate-and-read + locate-and-address), 32 episodes,
0 failures:

| arm | address | read | raw tok | Δcontext tok* |
|---|---|---|---|---|
| F0 push (full page) | 1.000 | 1.000 | 22,530 | ~10,200 |
| F1 pull (vector fetch) | **1.000** | 0.850 | 25,990 | **~1,400** |
| F2 pull (raster fetch) | 0.000 | 1.000 | ~29,000 | ~2,500 + image |
| F3 gist only | 0.000 | 0.000 | 12,740 | ~450 |

*Δcontext = raw minus ~12.3k CLI scaffolding *per call*; F1/F2 make two calls.

- **H7a holds on accuracy**: vector pull matches push on addressing (1.000)
  and nearly on reading (0.850, one episode missed a region).
- **H7b fails in raw CLI tokens but holds in content**: the model reads
  ~1,400 tokens of actual ink content under pull vs ~10,200 under push —
  an 86% content reduction — but our stateless CLI harness pays the
  ~12.3k scaffold tax twice, swamping it. In a real agent session (one
  conversation, gist cached, fetches appended — the assistant demo's
  regime) only the content cost recurs. Pull is a *deployment* win the
  harness can only see through the Δcontext lens.
- **H7c confirmed exactly**: the raster fovea reads perfectly (1.000) and
  cannot address at all (0.000 — no ids in pixels); the vector fovea does
  both. Only ink can pull addressable detail.
- F3's floor (0.000 everywhere) proves the tasks genuinely require detail —
  the gist alone answers nothing.

## E8j: JPEG saves bytes, not tokens

Same half-scale raster as E8, JPEG q40: input tokens identical (14.2k vs
14.3k — **image cost is pixel-metered, not byte-metered**), upload halved
again (22KB → 11KB), reading dips 0.538 → 0.479 (q40 artifacts tax
legibility), classification stays 1.000. Verdict: JPEG is a
latency/bandwidth knob only; keep PNG for reading tiers, JPEG acceptable
for gestalt tiers if transport matters.

## ICF v1 draft: state of the open questions

1. Style/author metadata — still open (no S1/S2 task needed them).
2. Cluster semantics — **answered yes** (M2), unchanged by real ink.
3. Grid resolution — **answered: 256 is enough**; resolution is not the
   transcription bottleneck.
4. Real-ink robustness — **structure tier: confirmed. Perception tier:
   confirmed necessary** (raster attach or recognizer semantics for
   reading tasks).
