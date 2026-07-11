# Transport-era findings (ICF v2 program)

*Live codex-cli (default-low), S0-derived episode corpora. Design:
icf-v2-transport-design.md. Started 2026-07-10.*

## H6 delta context (T7): deltas match full resend; raster loses on capability

64 rows (4 episodes × 4 arms × 4 questions), 0 failures:

| arm | count t1 | count t2 (combined) | count t3 (post-erase) | erased-id | final-turn window |
|---|---|---|---|---|---|
| D0 raster resend | 1.00 | **0.25** | 1.00 | **0.00** | 1,424 chars + image |
| D1 v1 full resend | 1.00 | 1.00 | 1.00 | 1.00 | 7,070 chars |
| D2 deltas (ids) | 1.00 | 1.00 | 1.00 | 1.00 | **3,386 chars** |
| D2n deltas (no ids) | 1.00 | 1.00 | 1.00 | 1.00 | 3,359 chars |

- **H6 core claim holds:** per-turn deltas keyed by stable ids match full
  resend on every question, at a context window 52% smaller after 3 turns.
  The window grows ~60 chars/turn under D2 vs ~2,300 under D1 — at the
  design's 10-turn horizon that's ~4k vs ~23k (≈ the pre-registered <25%).
  Raw CLI tokens (55.3k vs 61.9k) understate this because the ~12.3k/call
  scaffold dominates a 4-call episode — same lesson as H7: stateless
  transports hide transport wins; hence H7-S.
- **Raster fails on capability, not cost:** D0 collapsed to 0.25 on
  combined-state counting (the classic VLM counting weakness at 11 items)
  and 0.00 on erase identification (pixels have no ids, and the superseded
  snapshot can't be diffed). The cheap window buys a consumer that can't
  track state.
- **Prediction falsified (reported as pre-registered):** D2n was predicted
  to lose on erase-tracking; it scored 1.00. The ablation was too weak —
  the turn-1 base context carries the id→bbox binding, so a location-only
  delta ("erased_near [x,y]") is trivially resolved back to an id. The
  identity signal lives in the *format* (base context), not the delta
  encoding; the honest stronger ablation would strip bboxes from the base.
  Net: delta payloads may omit ids when the base has geometry-id bindings —
  a wire-format simplification, not a loss for the thesis (D0, with no ids
  anywhere, scored 0.00).

## H7-S stateful foveation: pending (runner queued)
