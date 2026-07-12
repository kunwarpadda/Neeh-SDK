# 0002: Deterministic local analyzers, not a learned ink encoder, for bounded temporal/geometric evidence

Date: 2026-07-12
Status: Accepted

## Context

An early research direction for Neeh (documented in an initial ChatGPT-
assisted research report, and reflected in a since-superseded earlier
version of this project's roadmap) proposed a two-track plan: ship a
structured-context product path now, and separately pursue a native learned
ink encoder — a stroke/point encoder feeding learned query tokens into a
language model — as a research track, on the theory that raw ink trajectories
carry information a rendered PNG provably cannot (stroke order, direction,
pressure, revision history).

That existence argument is correct but insufficient to justify building an
encoder: it establishes that *some* representation beyond a PNG can carry
this information, not that a *learned* representation is the right one when
plain structured data already exists as an alternative.

Two controlled experiments tested this directly. The first: paired ink
samples certified pixel-identical, differing only in draw direction or
creation order, given to the same model under three input conditions — image
only, image plus structured facts, and plain coordinate serialization. The
image-only condition sat at exactly chance and, on the direction task,
produced confident but false visual justifications for its answers rather
than abstaining — a real product/safety finding independent of the encoder
question. Both the structured-facts and coordinate-serialization conditions
reached full accuracy, with coordinate serialization costing roughly a third
of the structured-facts token cost.

The second experiment tested the resulting hypothesis: does that advantage
hold as ink density grows? A temporal task (locate the most-recently-drawn
mark among N marks) was run at N from 4 to 320. Accuracy stayed perfect
(no degradation) at every density tested through N=320 for both a full
coordinate dump and a compact per-mark index — the model's *reasoning* never
broke down. What broke down was token cost: full coordinate serialization
crossed a representative context budget near N≈300, growing roughly linearly
with mark count. A deterministic local reducer — compute the exact answer
locally, return one bounded, typed record — held the same task at an
approximately *constant* prompt cost across the same range (measured at
roughly 268–270 tokens from N=4 through N=320; see the table in
[`spec/ink-analysis-v1.md`](../../spec/ink-analysis-v1.md)), against roughly
4,700–8,600 tokens for the two serialization approaches at N=320.

In short: the accuracy gap a learned encoder would need to close does not
exist at the densities tested; the actual problem is a token-budget scaling
problem, and a deterministic reducer solves that problem exactly, without
training data, inference cost, or a new model artifact.

## Decision

Neeh does not build a native learned ink encoder, Q-Former-style query
bridge, or ink pretraining pipeline. The active architecture for bounded
agent evidence is: exact deterministic analyzers first
(`neeh.agents.analyzers`), then structured retrieval, then targeted
raster/geometry on demand, then model reasoning over the bounded result — see
[ARCHITECTURE.md](../../ARCHITECTURE.md) and ROADMAP.md's "Explicitly not
planned" section.

## Consequences

- Neeh's engineering effort goes toward broader analyzer coverage
  (containment, intersection, connectors, grouping — ROADMAP milestone M1)
  rather than model training infrastructure.
- This is a reversible position, not a permanent one. ROADMAP.md states the
  explicit gate for reopening it: a valuable real task must repeatedly fail
  under exact analyzers, structured retrieval, targeted paths, *and* raster
  evidence; the failure must be representational rather than a recognizer or
  tooling defect; a learned prototype must then beat the complete structured
  baseline on held-out writers and devices; and the resulting gain must
  justify training, inference, privacy, and maintenance cost.
- The two experiments behind this decision used synthetic, controlled ink
  pairs and a single model configuration. The finding that accuracy doesn't
  degrade with density is strong evidence against an encoder being
  *necessary*, not proof it would never help on messier real handwriting or
  diagrams — that broader evaluation is ROADMAP's M3 milestone.
