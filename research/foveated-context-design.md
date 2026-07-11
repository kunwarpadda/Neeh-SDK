# Foveated ink context — experiment design (pre-registered before any run)

*2026-07-10. The rethink: every arm so far PUSHES a fixed representation and
pays for the whole page regardless of the question. Vision-language research
is moving to PULL — models acquire visual detail on demand (Foveated
Reasoning, arXiv 2604.21079; AdaptVision, arXiv 2512.03794) — but nobody has
applied it to ink, where we own the source representation and every "crop"
can be lossless vector, not pixels.*

## Hypothesis H7 (pull beats push at scale)

On pages large enough that full context is expensive, an agent given a cheap
gist plus **region-fetch tools** matches full-context accuracy while its cost
scales with the *question*, not the *page*. Sub-claims:

- H7a: gist + one fetch round ≥ 0.9 × full-context score on addressing and
  reading tasks over dense pages.
- H7b: total tokens (gist + fetched detail) < 40% of the static E7b context
  for questions touching ≤ 20% of the page.
- H7c: the fetched detail is *better* as vector (compact SVG of the region,
  with ids) than as a raster crop at equal token budget — because our crops
  are lossless and addressable, which pixel foveation cannot be.

## Why our validated pieces compose into exactly this

| validated result | role in the foveated protocol |
|---|---|
| E5 clusters (counting 1.000 @ +260) | the *gist*: cluster summaries + bboxes locate content cheaply |
| E7b bboxes (reading 0.672 @ 30% cost) | the *index*: bboxes tell the model where to look before fetching |
| E7v region SVG (addressing 1.000) | the *fovea*: lossless vector detail for the region that matters |
| E8q thumbnail (pending) | optional coarse percept beside the gist |
| T5 tool execution (0.833–1.000) | proof the models can operate the fetch tools |
| frame rule (T5 0.167→0.833) | all fetch requests/returns in page units |

## Task design T8 (two-phase pull, works on one-shot CLI backends)

Dense corpus S0d: S0-style pages scaled to 300–600 strokes (10–20 words /
30+ shapes), where static context genuinely hurts.

- Phase 1: model receives the gist (cluster items + page thumbnail or none)
  and the question; must reply with a JSON fetch request: regions (page
  units) or stroke-id ranges, budgeted.
- Phase 2: harness executes the fetch (compact SVG of requested regions),
  appends it, and asks for the final answer. Score with existing T1/T3/T4
  scorers; ledger cost = phase-1 + phase-2 input tokens.

Arms: F0 static E7b on the dense page (push baseline); F1 gist+fetch with
vector fovea; F2 gist+fetch with raster-crop fovea (H7c ablation); F3 gist
only, no fetch (floor).

## Adjacent literature, parked with reasons

- **ScribeTokens** (arXiv 2603.02805): 10-token base vocabulary + BPE over
  unit pen steps; big wins *for generation with fine-tuned models*. Zero-shot
  context is our regime, and the E2-vs-E4 syntax-familiarity result predicts
  an alien merged vocabulary fails without training. Revisit if Neeh ever
  fine-tunes an ink-native model.
- **Sigma-lognormal** (Plamondon): ~6 kinematic params/stroke — the most
  compact faithful stroke code known, but its parameters are meaningless to
  a zero-shot LLM. Candidate for the archive tier / synthesis, not context.
- **SVGenius / VGBench / VectorGym**: benchmark evidence that LLM SVG
  competence degrades with path complexity — independent support for RDP
  simplification (E7vS/E8s) beyond token savings.

## Status

Designed; not implemented. Needs: dense-corpus generator (S0d), T8 two-phase
runner (~200 lines), fetch executor over existing `_compact_svg(region=...)`
machinery. No SDK changes required to test; if H7 holds, the SDK grows a
`fetch_ink_region()` context tool and ICF v2 becomes a *protocol*, not a
payload.
