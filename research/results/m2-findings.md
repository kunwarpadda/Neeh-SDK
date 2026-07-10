# M2 findings — full matrix complete (S0 synthetic, codex-cli)

*2026-07-10. The 858-cell matrix (10 arms + CTRL × 6 families × 12 pages) is
complete across two ledger conditions: `default-high` (morning, reasoning
effort high — all M1 cells and part of the M2 families) and `default`
(afternoon, effort low — the remainder, 340 rows, **0 failures**). Cross-arm
comparisons within the afternoon block are condition-clean; comparisons that
cross the effort split are marked. Source: [ledger.jsonl](ledger.jsonl),
[summary.md](summary.md).*

## The perceptual-grouping prediction: confirmed both ways

The morning data predicted that counting fails on flat stroke listings
because multi-stroke objects (the two-stroke arrow) get counted twice, and
that E5's clustering would fix it. Both halves held:

- **E5 (scene graph, clustered): T2 = 1.000 at +260 tok** — perfect counting,
  cheapest context of any arm on the family.
- **E7v (flat compact SVG): T2 = 0.333** — over-counts 5-for-4 on every
  arrow page, exactly the predicted failure.
- E4 (flat SVG, high-effort morning: n/a; afternoon: 1.000) shows verbose
  flat listings *can* count at low effort — but at 3× E5's token cost.

**ICF v1 consequence:** open question #2 is answered — optional cluster
summaries in `semantics` are worth shipping. The composition that covers
every family is now visible: E7v geometry for addressing/layout/actions +
E5-style cluster items for counting/global gist.

## Action grounding and temporal order on the compact SVG

- **E7v T5 = 1.000 at +1955 tok** — perfect executed tool calls (erase by
  stroke id, highlight by region) from pure text at a third of E4's cost.
- **E7v T6 = 0.917** — drawn order carries temporal answers, one miss.
- **E7 (hybrid) T5 = 0.833** — *worse than its own text-only variant.* All
  three misses are highlights answered in **grid coordinates** instead of
  page units. Coordinate-frame ambiguity is the hybrid's failure mode for
  region outputs: with the raster present the model stopped converting
  frames. Fix candidates for an E7/0.2.0 revision: state the grid→page
  scale factor in the legend, or emit page-unit coordinates in the
  perception tier. (E7v answered the same tasks correctly, so conversion
  is learnable from the viewBox alone — just not reliable across variants.)

## The rest of the matrix, briefly

- **E6 (temporal raster, hue-coded): T6 = 0.917** — drawing order is
  recoverable from hue, but at 1836 visual tokens and with **T4 = 0.000**
  (no ids) it is dominated by any listing that is simply *in order*.
- **E5's ceiling:** T1 = 0.308 (descriptors cannot transcribe — by design),
  T3 = 0.583, T6 = 0.500. It is a counting/gist specialist, not a general
  encoding: use it as a semantics layer, not the geometry channel.
- **E3 (grid language):** 0.556–0.833 across T4/T5/T6 — consistently
  mid-pack; nothing it wins.

## Condition caveats

- Effort split: E0/E1a/E1b/E2 M2-family cells ran at high effort in the
  morning (see m1-findings.md "Early M2 observations": ICF arms 1.000 on
  T5/T6, raster at chance on T6); the arms above ran at low effort. Where a
  cross-split comparison matters (E5-low vs E1a-high on T2) the direction is
  robust — a 1.000 at low effort cannot be an artifact of the cheaper
  condition — but exact deltas should not be quoted across the split.
- 16 failed cells remain under `default-high` (11 CTRL declines + 5
  quota-killed E3s); a `--retry-failed` pass can clean them.
- Single repeat, synthetic S0. S1/S2 real-ink runs are queued in the
  harness README.
