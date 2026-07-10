# M1 findings — first live sweep (S0 synthetic, codex-cli)

*2026-07-10. 252 ledger rows: 5 arms + CTRL × T1/T3/T4 × 12 pages, backend
`codex exec` (default model), 1 repeat. Source of truth:
[ledger.jsonl](ledger.jsonl), tables in [summary.md](summary.md). Protocol:
[protocol-m0.md](../protocol-m0.md).*

## Hypothesis verdicts (per §8 decision rules)

| # | Hypothesis | Rule | Verdict |
|---|---|---|---|
| H1 | Vector context reaches zero-shot parity with PNG | ≥95% of E0 score | **Supported** — E1a (ICF v0) = 1.000 on T1 and T3, equal to E0, no pixels sent |
| H2 | Stroke IDs enable addressing raster cannot do | ≥80% set-F1; E0 near 0 | **Strongly supported** — E0 = 0.000 (18/18 misses); E1a, E1b, E4 = 1.000 |
| H3 | Abstraction wins on global layout | ≤60% of E0 token cost at parity | **Supported** — E2 = 1.000 at +692 tok vs E0's +1790 (39%) |
| H4 | A hybrid dominates the frontier | — | **Untested** — E7 is composed from these results (below) |
| H5 | Temporal order is recoverable | — | **Untested** — T2/T5/T6 + M2 arms not yet run live |

## The three-family picture

- **T1 transcription: raster is still king.** E0 = 1.000 at +1793 tok.
  Vector parity exists (E1a = 1.000) but at +10,729 tok — 6× the price.
  Compressed vector trades accuracy: E2 = 0.830, E4 = 0.754.
- **T3 layout: everything solves it; compression wins on cost.**
  All arms = 1.000. Frontier is E2 at +692 tok. (CTRL = 0.500 — the
  quadrant/relation questions have a guessing floor, so parity at 1.000 is
  still meaningful.)
- **T4 addressing: the capability gap, now measured.** PNG scores zero by
  construction. The surprise is **E4 (SVG path text) = 1.000 at +3320 tok**
  — perfect addressing at a quarter of ICF v0's cost (+13,349). Familiar
  format beats bespoke format: one `<path id=…>` element per stroke makes
  the ID→geometry binding trivial for the model.

## Error taxonomy (every sub-1.0 cell inspected)

1. **E2 T1 is bimodal, not uniformly degraded.** Four pages ≥0.91 with
   single-letterform confusions ("jingle"/"jungle", "stops"/"stone");
   two pages collapse outright (0.00, 0.11). Quantization noise
   occasionally crosses a legibility threshold and the whole page goes.
2. **E2 T4 misses are word-alignment errors, not ID-parsing errors.** The
   model returns contiguous ID runs of plausible length but for the wrong
   word (e.g. truth 0025–0031, answer 0066–0070). It can read IDs from the
   dense quantized stream but mis-segments which strokes form which word.
   E4's discrete per-stroke elements eliminate exactly this failure (1.000).
3. **Classification phrasing, not perception:** E1b's single T1 miss is
   "right arrow" vs truth "arrow"; E4 likewise ("rectangle" vs "square").
   Same prompt across arms per the fairness rule, so left as-is.
4. **CTRL failures are benign.** All 11 backend failures ("no final
   message") are CTRL rows — the model declines contextless questions.
   CTRL is the token baseline only; conclusions unaffected.

## Decision: E7 composition

Evidence says the hybrid is **PNG for perception + compact ID-bearing
vector for addressing**:

- **E7 = E0 raster + E4-style SVG paths with E2-grade coordinate
  simplification** (resampled, integer-quantized `d` attributes to cut
  E4's 7.3k chars). Predicted: 1.000 across T1/T3/T4 at roughly +4–5k tok
  — vs E1a's +13.3k for the same scores. That is H4's test.
- Secondary arm worth one sweep: **compressed SVG alone** (no raster), to
  see whether a pure-text arm can hold the whole frontier when
  transcription fidelity matters less.

## Consequences for ICF v1

- Stroke IDs are the non-negotiable core (H2). Raw point streams are not:
  ICF v0's full sampled points cost 6× PNG for zero accuracy gain on these
  families.
- The wire format should lean on formats models already read fluently
  (SVG-like paths) rather than bespoke JSON point arrays.
- Fidelity must be tiered: layout-grade geometry (E2-level, ~40% of PNG
  cost) vs transcription-grade (raster or full points) — selectable per
  request, since no single fidelity wins all families.

## Caveats

- Synthetic S0 ink only; S1 (Quick, Draw!) live run pending — E2's
  legibility-threshold collapse may behave differently on real ink.
- One model (codex default), one repeat; no variance estimate yet.
- Token deltas include CLI scaffolding subtraction via CTRL mean (see
  summary.md header); absolute values are backend-specific.
