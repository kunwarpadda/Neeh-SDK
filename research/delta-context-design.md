# Delta context — experiment design (pre-registered before any run)

*2026-07-10. Ranked #2 in the post-real-ink engineering push; the one
capability no raster format can copy.*

## Hypothesis H6

In a multi-turn session over a changing page, an ICF consumer that sends the
full context once and then only **per-turn deltas** (new/changed strokes by
stable id) matches full-resend accuracy at a per-turn cost that is O(change),
not O(page). A raster consumer *must* re-send the whole image every turn —
its per-turn cost is O(page) forever.

Cost model at S2-measured rates: 10-turn session, ~3 strokes drawn per turn.
- E0 full-resend: 10 × ~1,878 = **~18,800 tok**
- E7b full-resend: 10 × ~3,325 = ~33,300 tok
- v1 delta: 1 × ~1,450 + 9 × ~120 = **~2,500 tok** (≈ 7× cheaper than PNG)

## Task family T7 (multi-turn state tracking)

Each trial is a scripted 3-turn episode on an S0/S1 page:
1. Turn 1: context for the page at time t0 + a warm-up question (scored).
2. Turn 2: k strokes are "drawn"; arm-dependent update payload + a question
   that requires *combined* state (e.g., counting across old+new, or
   addressing a new stroke relative to an old one).
3. Turn 3: one stroke is erased by id; question requires noticing removal.

Scoring reuses T2/T4 scorers. The episode transcript is replayed to the CLI
backend as a single prompt with turn markers (CLI backends are stateless;
the *encoding* of history is the variable under test, matching how an
agent's context window actually accumulates).

## Arms

- **D0** — full PNG re-sent at every turn (raster baseline).
- **D1** — full v1 context re-sent at every turn (vector baseline).
- **D2** — v1 context at turn 1; turns 2+ send only
  `{"delta": {"added_svg": "<path .../>", "erased": ["st_x"]}}`.
- **D2n** — D2 without stable ids in the delta (ablation: is it the ids or
  the smallness that carries it?).

## Predictions (falsifiable)

- D2 ≈ D1 ≈ D0 on accuracy for counting; D2 ≈ D1 > D0 on addressing
  (raster still can't address).
- D2 per-episode cost < 40% of D0, < 25% of D1.
- D2n < D2 on erase-tracking (removal needs identity).

## Status

Designed; not yet implemented. Needs: T7 generator + episode runner
(~150 lines in the harness), no SDK changes — `build_ink_context_v1`
already emits per-stroke `<path id>` elements that can ride as deltas.
