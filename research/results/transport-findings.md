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

## H7-S stateful foveation: the pull win is real but conditional

19/24 rows (stopped early), real `codex exec resume` sessions, per-turn
cache splits recorded:

| arm | addressing | reading | raw input/episode | uncached input/episode |
|---|---|---|---|---|
| F0 push (1 turn) | 1.000 | 1.000 | ~22.5k | ~11.3k (steady state) |
| F1 pull (2 turns) | 0.985 | 0.456 | ~39.3k | 4.3k–22.8k (mean ≈ F0) |
| F3 gist only | 0.000 | 0.000 | ~38.9k | ~3.9k best case |

Three findings, all about economics rather than capability:

1. **A resumed turn re-reads the whole thread.** F1's raw input is ~39k
   because turn 2 replays turn 1 plus the fetch. Under raw-input billing,
   pull *loses* to push on a one-question episode: the extra turn costs a
   full history read (~16.8k), more than the ~10k of content pull saves.
2. **Under cache-aware serving, pull wins — when the cache holds.** Best
   episodes: F1 uncached 4.3k vs F0's 11.3k (62% cheaper). But roughly
   half the resumed turns missed cache (uncached 16–23k), erasing the win.
   The pull advantage is bounded between "62% cheaper" (warm cache) and
   "worse than push" (cold resume); the mean landed at parity.
3. **The demo regime dodges the tax entirely.** An agentic tool-loop pull
   (`fetch_ink_region` as an in-turn tool call) appends the fetch to the
   *same* turn — no new user turn, no history re-read. H7-S measured the
   worst transport for pull (user-turn resume); the tool-loop transport,
   which the assistant demo already implements, pays only the fetch
   content. That is where the H7 stateless −86% content saving converts
   to real tokens.

Accuracy note: F1 reading dropped to 0.456 (from 0.850 stateless) because
the phase-2 follow-up said "answer the question from the first message" —
leaving question recall to a low-effort model. Fixed in the runner
(follow-up now restates the question verbatim, ~30 tokens); re-measure
with the next quota window if desired. Addressing was unaffected (0.985).

## H8 progressive refinement (T8p): falsified on this corpus — no gap to close

32/32 clean, real sessions, S0d dense pages:

| arm | read | layout | uncached input |
|---|---|---|---|
| R64 static coarse | **1.000** | 1.000 | ~12.5k |
| R128 static | 0.708 | 1.000 | ~13.1k |
| R512 static fine | 1.000 | 0.750 | ~15.2k |
| RP 64-base + refine | 1.000 | 1.000 | 27.8k read / 12.9k layout |

- **The premise failed, informatively: 64-grid is not a floor.** Synthetic
  Hershey words remain perfectly readable at 64 cells, so there was no
  accuracy gap for refinement to close — and the refinement turn (a session
  resume, ~27.8k uncached) costs nearly double static-fine for nothing.
  This was predictable from the v1 resolution sweep (E7v512 ≈ E7v:
  "resolution is not the transcription bottleneck") and we should have
  connected the two at pre-registration. On S2 real handwriting, vector
  reading fails for *style* reasons, not resolution — refinement wouldn't
  close that gap either. Verdict: **for ink, geometry fidelity is rarely
  the binding constraint; multiresolution transport solves a problem ink
  doesn't have.** The wavelet analogy earns its keep in the delta/pull
  pieces (never resend what the receiver has), not in fidelity laddering.
- **Two fresh non-monotonicities** reinforce the RDP finding that more
  detail can hurt: R128 read 0.708 < R64's 1.000, and R512 *layout* 0.750
  < everyone's 1.000. Fidelity is not a safety axis you can only ascend.
- **Self-triage is conservative:** RP requested refinement on every reading
  question (avg 10.2 strokes) even though the coarse base sufficed — the
  model can't know detail is unnecessary without trying. In pull protocols
  the consumer's uncertainty, not the task's true need, drives cost; gist
  legends should say what the coarse tier is reliably good for (ours
  hedged with "may not be legible", inviting the fetch).

**Program verdict:** push/pull is not a binary — it's priced by transport.
Ranked by pull-friendliness: in-turn tool loop (demo) > cached resume >
cold resume > stateless two-shot. ICF v2's pull extension should say
exactly this: pull pays off in agentic loops and cached sessions; push
remains right for one-shot transports. The spec's wording already matches.
