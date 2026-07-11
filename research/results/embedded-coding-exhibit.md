# Embedded (anytime) ink coding — offline exhibit, mostly negative

*2026-07-10. EE import test: SPIHT/JPEG2000-style embedded coding — one
string, truncatable anywhere, refinements emitted in steepest
rate-distortion-slope order. Measured offline (geometry only, no model
calls) via research/harness/embedded.py before any model-facing claim.*

## Result: naive text embedding is dominated

| encoding | S0 text: chars @ mean err (page units) | S0 shapes |
|---|---|---|
| embedded L0 (coarse eps=8) | 3,433 @ 11.81 | 272 @ 17.11 |
| embedded L1 | 4,580 @ 4.53 | 441 @ 6.77 |
| embedded L2 | 5,632 @ 2.51 | 659 @ 2.42 |
| fixed grid-128 | 3,599 @ **6.38** | 419 @ 3.81 |
| fixed grid-256 | **4,108 @ 2.51** | **642 @ 2.42** |
| fixed grid-512 | 4,954 @ 1.01 | 1,090 @ 1.18 |

At every budget, simply *choosing the right fixed encoding* beats the
truncatable string. Two reasons, both text-specific:

1. **Re-emission overhead.** Bit-domain embedded coders refine coefficients
   with additional bits; a text refinement must re-send the whole path
   (~40% overhead). A "delta refinement" syntax would avoid it but is
   exactly the alien-syntax bet the E2-vs-E4 result warns against.
2. **Broadcast vs unicast.** Embedded coding wins when one artifact must
   serve every consumer at unknown budgets (broadcast). LLM context is
   generated per call — we can re-encode for each budget, so truncatability
   buys nothing that per-call rate control doesn't buy better.

## What survives from the EE import

- **Rate-distortion framing.** Our Pareto frontiers are empirical
  rate-distortion curves with task score as the distortion axis. The formal
  frame ("rate-task-distortion") names what the harness measures and is the
  theory spine for the writeup.
- **Rate control** (the video-codec concept): given a token budget, the
  *encoder* picks the operating point — grid, RDP epsilon, bbox/raster
  tiers — from measured curves. This is the practical winner: a
  `budget`-aware `build_ink_context_v1` that auto-selects, validated
  against the ladder above. Queued as an SDK feature.
- **Nyquist/oversampling.** Pen capture (~100 Hz) is ~10x above hand-motion
  bandwidth (~5-10 Hz); dense point streams are physiologically redundant,
  which is why resampling+RDP costs no task accuracy. Grounds the epsilon
  choice in physics rather than taste.

## Verdict

Embedded-string context: **rejected on offline evidence** (kept here so
nobody re-derives it). Rate control per call: **adopt** — it delivers the
same any-budget property without the overhead, and composes with the
foveated protocol (H7): rate-control the gist, pull the detail.
