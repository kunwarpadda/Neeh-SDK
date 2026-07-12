# Architecture Decision Records

This directory records significant architectural decisions for Neeh: the
context at the time, what was decided, and the consequences — following the
[Michael Nygard ADR format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions).

An ADR is written when a decision has real evidence behind it (a measurement,
a failed alternative, an external precedent) and materially shapes the
architecture — not for every commit or minor implementation choice. Once
accepted, an ADR is not edited to match new decisions; a later decision that
supersedes an earlier one gets its own ADR that says so, so the history of
*why* stays intact.

| ADR | Decision |
|---|---|
| [0001](0001-structured-index-primary-raster-on-demand.md) | Structured index is the primary model-facing channel; raster is fetched on demand |
| [0002](0002-deterministic-analyzers-over-learned-encoder.md) | Deterministic local analyzers, not a learned ink encoder, for bounded temporal/geometric evidence |
| [0003](0003-stateless-per-turn-sessions.md) | Stateless-per-turn model sessions with document-derived delta context, not provider session resume |
