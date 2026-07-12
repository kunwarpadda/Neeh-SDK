# Neeh architecture and design rationale

Status: vision and design-history document. It records why Neeh is built the
way it is; it is not itself a protocol specification. The normative wire
formats live in [`spec/`](spec/); the current milestone-by-milestone status
lives in [ROADMAP.md](ROADMAP.md). Individual architectural decisions, dated
and with their reasoning preserved, live in [`docs/adr/`](docs/adr/).

## Motivation

Digital ink — handwriting, sketches, diagrams, annotations, structured pen
strokes — is usually handed to software, and to AI agents, as a rendered
image: a screenshot or a PNG export. That flattening throws away information
a stylus actually captures: the order strokes were drawn in, their direction,
their timing, their pressure, and any revision history (crossed-out or
replaced ink). Once flattened to pixels, none of that is recoverable — two
different ink histories can rasterize to identical pixels while differing in
every one of those dimensions.

Neeh explores an alternative: keep the ink's native structure — ordered,
timestamped, addressable strokes — as the source of truth, and treat a
rendered image as one derived view among several, not the primary
representation. An agent then gets both a rendered view (for what pixels
alone answer well) and native structure (for what pixels cannot answer at
all — draw order, revision, precise addressability by id).

This is not a claim that Neeh is the first system to prefer structure over
pixels — the same trade-off is well established in adjacent domains (web
accessibility trees over screenshots, structured document formats over
scanned images). Neeh is an implementation of that idea specifically for
digital ink, where the analogous "structured" representation did not have an
established shape before this project.

## Design principles

These are principles actually reflected in the current code, not aspirations:

**The document is the source of truth; the model interface is a view onto
it.** `neeh.document.Document`/`Page`/`Layer` and `neeh.ink.Stroke` hold the
canonical ink — ordered points with timestamps, pressure, tilt, authorship,
and a stable id. Every representation sent to a model (`neeh.context`,
`neeh.agents.iai`) is derived from that document on demand; none of them is
itself where state lives. This lets Neeh change what it shows a model without
ever touching what it stores.

**A structured index is the primary model-facing channel; a raster is
fetched on demand, not attached by default.** `neeh.context.build_ink_index`
produces a compact map of stable-id marks with shape and position; a full
page image costs roughly an order of magnitude more tokens for the same
page and cannot be queried by id. Raster is available through the tool
surface (`view_page`, `view_region`) and the agent perception actions
(`neeh.agents.iai.InkAgentInterface.view_region`) when the index is
insufficient — chiefly for reading handwriting content, which the structured
index intentionally does not attempt to transcribe.

**Deterministic local computation happens before model reasoning, not
instead of it.** `neeh.agents.analyzers.analyze_ink` answers mechanical
questions — the latest-drawn stroke, chronological order of named strokes,
stroke dynamics, cross-out candidates — by computing the exact answer locally
and returning one bounded, typed record, rather than asking a model to search
or calculate over a serialized page. This is deliberately the alternative to
a learned representation for this class of question; see
[`docs/adr/0002-deterministic-analyzers-over-learned-encoder.md`](docs/adr/0002-deterministic-analyzers-over-learned-encoder.md).

**Edits are proposed, validated, and applied atomically — never applied
speculatively.** A planned batch of tool calls is replayed on a cloned
document (`neeh/agents/assistant.py`'s `_validate_planned_actions`) before
touching the live canvas; a failing batch gets exactly one repair turn with
concise validation feedback, and nothing partial is ever committed.

## From raw ink to agent action

Neeh's modules correspond to distinct points on one path from captured
strokes to an applied edit:

| Stage | What it is | Module |
|---|---|---|
| Raw ink | Ordered, timestamped points with pressure/tilt; strokes; pages/layers | `neeh.ink`, `neeh.document` |
| Rendered image | SVG, optional PNG, and token-cheap ASCII views of a page or region | `neeh.rendering` |
| Recognition / semantics | Geometric clustering and directed links between marks (shape recognition, not handwriting transcription) | `neeh.semantics` |
| Deterministic analysis | Exact local answers to temporal/geometric questions, bounded regardless of page size | `neeh.agents.analyzers` |
| Temporal structure | Ink grouped into creation episodes ("moments"), ranked and retrievable by relevance to a query | `neeh.agents.timeline` |
| Structured index / context | Compact, addressable model-facing snapshots (`ink-context`, `ink-index`) | `neeh.context` |
| Agent tools | The mutation API (`add_stroke`, `mark`, `annotate`, `insert_text`, ...) and the read-only perception surface (`find_marks`, `analyze_ink`, `view_region`, ...) | `neeh.tools`, `neeh.agents.iai` |

A raster is a *derived, lossy* view produced from raw ink at any of these
stages — it is not upstream of them. This is the inversion at the center of
the project: existing pipelines usually start from an image and add
recognition on top; Neeh starts from structure and renders an image as one
output of it.

## The perception-action-feedback loop

As implemented in `neeh.agents.iai` and `neeh.agents.assistant`:

1. **Bootstrap.** `build_observation_workspace` returns a budgeted
   `page_map`, the ink new since the model's last turn, and (for policies
   that allow it) a set of typed, read-only perception actions and their
   remaining budget.
2. **Perceive, if needed.** The model may call `find_marks`, `analyze_ink`,
   `view_region`, `find_ink_moments`, `inspect_ink_moment`, `get_ink`, or
   `expand_relations` — each bounded, each declaring what page-space region
   or fidelity it covers, exposed over a read-only stdio MCP server
   (`neeh.agents.iai_mcp`) so perception cannot mutate the live document.
3. **Plan.** The model returns a batch of edit-tool calls.
4. **Validate.** The batch is replayed atomically on a document clone.
5. **Repair, once.** A failing batch gets one corrected attempt with the
   validation feedback attached; there is no open-ended retry loop.
6. **Apply.** Only a fully valid batch touches the live document.

This loop is deliberately bounded at every stage — a fixed action budget, a
fixed observation-character budget, a fixed raster-pixel budget, and exactly
one repair pass — so that context cost and reasoning cost stay predictable as
a page grows, instead of scaling with page size or trajectory length.

## Status: what's shipped, experimental, planned, or open

- **Shipped**: the ink/document/canvas substrate, SVG/PNG/ASCII rendering, the
  `neeh-tools/v1` mutation surface, `ink-context` v0/v1, the geometric
  semantics recognizer, UIM 3.1 persistence, the C++17 core and C ABI.
- **Experimental** (versioned, but the protocol boundary is not yet frozen):
  `ink-agent-interface/v1`, `ink-analysis/v1`, `ink-timeline/v1` — the
  perception-action layer described above.
- **Planned**: an append-only document event log so destructive-history
  claims (`history_complete`) are honest rather than best-effort; broader
  analyzer coverage (containment, intersection, connectors, grouping);
  evaluation against real handwriting/diagrams rather than only synthetic
  fixtures. See [ROADMAP.md](ROADMAP.md) for the full milestone list.
- **Open research question**: whether a native learned ink encoder is ever
  worth building. The current position is that it is not, on the evidence
  gathered so far — see
  [`docs/adr/0002-deterministic-analyzers-over-learned-encoder.md`](docs/adr/0002-deterministic-analyzers-over-learned-encoder.md)
  and ROADMAP.md's explicit reconsideration criteria. This is a standing
  question the project tracks, not a closed one.

## Design decisions and their reasoning

Individual decisions — what was tried, what the evidence showed, what was
decided and why — are recorded as dated Architecture Decision Records in
[`docs/adr/`](docs/adr/) rather than narrated here, so the reasoning behind a
specific choice stays attached to that choice as the project evolves.
