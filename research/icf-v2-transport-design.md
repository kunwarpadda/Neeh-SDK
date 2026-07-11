# ICF v2 — from payload design to context transport design

*2026-07-10. Pre-registered before any v2 run. Direction set with Kunwar:
the static-encoding well is measured to its bottom (rate-distortion ladder,
RDP, resolution sweep, embedded-coding exhibit); the remaining wins are in
how context moves across turns, not how one payload is shaped.*

## The architectural bet

ICF v1 stays the best **push snapshot**. ICF v2 is a **stateful protocol**
with four pieces:

| piece | contents | status |
|---|---|---|
| **base** | cheap page manifest: clusters, page-unit bboxes, counts, optionally a gestalt raster | exists (v1 pull gist) |
| **pull** | `fetch_ink_region` (shipped); later `fetch_time_range`, `fetch_semantic_neighborhood`, `fetch_provenance` | H7 validated the first |
| **delta** | append-only add/erase/move/style events keyed by stable stroke ids | designed (H6), this doc schedules the run |
| **graph** | consolidated semantic state: stroke → cluster → symbol/object → claim, with confidence + provenance | new (H9) |

Cross-disciplinary anchors (progressive/semantic communication, foveated
vision, wavelet multiresolution, event streams, scene-graph memory,
information bottleneck) are the same claim from six directions: **context
should be progressive, reusable, addressable, and negotiated by task and
budget — not re-sent whole each turn.** Ink is unusually well placed to
cash this in because strokes already have stable ids and drawn order.

## Why statefulness revives multiresolution (the H8 argument)

The embedded-coding exhibit rejected SPIHT-style progressive strings: in a
one-shot regime every refinement re-emits its prefix (~40% overhead), so
fixed grids dominated at every budget. **That result is regime-dependent.**
In a session, the coarse base is already in the context window; a
refinement is an *append*, never a re-emission. Progressive transmission's
classic win — never resend what the receiver has — is exactly the delta
property. So H8 re-tests multiresolution *as transport*: coarse pass pushed
once, `fetch_refinement(stroke_ids, level)` pulls finer geometry for only
the strokes the task cares about. The negative exhibit stands for static
payloads; H8 asks whether the same math wins once re-emission is free.

## Hypotheses

- **H6 (delta)** — as pre-registered in delta-context-design.md: in a
  multi-turn session over a changing page, per-turn deltas keyed by stable
  ids match full-resend accuracy at O(change) cost; identity ablation (D2n)
  degrades erase-tracking. Runner: `run_h6.py`, arms D0/D1/D2/D2n.
- **H7-S (stateful foveation)** — re-run T8 over real sessions
  (`codex exec resume`) so phase 2 pays only incremental input. Predicted:
  pull's raw session cost drops below push (the stateless run showed
  −86% content but double scaffold; sessions pay scaffold once).
- **H8 (progressive refinement)** — base at 64-grid + on-demand refinement
  beats both "128 everywhere" and "512 everywhere" on cost at matched
  accuracy for mixed task batches. Only meaningful stateful.
- **H9 (hierarchical graph)** — a stroke→cluster→object graph with
  confidence/provenance beats flat `semantics` clusters on tasks that
  require crossing levels (e.g. "which claim does this stroke support?",
  "erase the evidence for X"). Built with oracle graphs on S0 (the format
  is under test, not the recognizer — same policy as E5).

## Measurement rules

- Ledger discipline unchanged: every call is a row; per-turn rows carry a
  `turn` field; episode cost = sum of *uncached* input across turns when
  the backend reports cache splits, else final-turn input for accumulating
  arms and Σ per-turn for resend arms.
- Score **by task family, never pooled** — v1 evidence already shows no
  single format dominates reading, addressing, temporal, counting, editing.
- One-shot replay (history re-sent as one prompt) is the honest fallback
  where sessions are unavailable; it reproduces exactly what an
  accumulating context window contains.
- D0 raster resend can attach only the latest image under current
  backends; its measured cost is therefore a *lower bound* — noted
  wherever reported.

## Order of execution

1. H6 runner + live run (needs only one-shot backends — runnable now).
2. Session backend on `codex exec resume`; H7-S re-run.
3. H8 refinement arm on the session backend.
4. H9 graph arm + T9 cross-level task family (largest; needs task design
   review before code).
