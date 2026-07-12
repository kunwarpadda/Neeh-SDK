# 0001: Structured index is the primary model-facing channel; raster is fetched on demand

Date: 2026-07-11
Status: Accepted

## Context

Neeh needs to give a model enough perception of a page to act correctly,
without making every turn pay for a full page image. Two channels were
compared directly: (A) a rendered raster plus compact per-stroke SVG
geometry, and (B) a structured index (`build_ink_index`) — stable-id marks
with shape, position, and a handwriting count, no per-point geometry.

Measured on real ink (`examples/compare_context_arms.py`): on a trivial page
(3 strokes) the two arms cost about the same (~109 vs ~115 tokens). On a
realistic busy page (46 strokes: a sidebar plus a question), the structured
index cost **~190 tokens against ~1,025 for raster+geometry — 5.4× cheaper**,
because per-stroke SVG geometry and the raster collapse into a marks list
with handwriting summarized as a count. A third arm (structured index plus an
ASCII gestalt rendering) was *not* a token win — grid whitespace cost more
than the index alone; its only value is qualitative (model-agnostic layout
reading for text-only backends).

Separately, internal testing on temporal/order questions (see
[0002](0002-deterministic-analyzers-over-learned-encoder.md) for the fuller
evidence base) showed that a raster-only perception channel cannot answer
questions about stroke direction or draw order — the information is
genuinely absent from the pixels — and, worse, an unhedged raster-only model
does not reliably abstain on those questions; it can produce a confident,
specific-sounding answer with no basis. That failure mode argues for
structure being available by default wherever the answer depends on ink
history, not only for cost reasons.

This mirrors an established pattern outside Neeh: web and computer-use agents
converged on sending a structured accessibility tree as the default channel
and a screenshot as an on-demand fallback (Set-of-Mark grounding, OmniParser,
MemGPT/Manus context-paging). Microsoft's Playwright MCP server for browser
automation follows the identical shape — accessibility snapshot by default,
a "vision mode" screenshot fallback only for elements the tree doesn't cover
(canvas apps, complex SVGs) — with the explicit finding that a vision-based
action on a well-represented element is *less* reliable than an id-based one,
not just more expensive.

## Decision

The structured ink index (`ink-index` / the Ink Agent Interface's `page_map`)
is the primary channel sent to a model by default. A rendered raster is
available on demand through `view_page`/`view_region` and the IAI
`view_region` perception action, escalated to only when the structured
channel is insufficient — chiefly for reading handwriting content, which the
index deliberately does not attempt to transcribe.

## Consequences

- Bootstrap cost scales with a page's structured complexity (marks, not
  pixels), which is materially cheaper on busy pages — the case that matters,
  since trivial pages are cheap under any representation.
- The system prompt and IAI policy documentation must tell the model
  explicitly when to escalate to raster (handwriting, visual detail) — an
  instruction, not a guarantee. Whether models reliably escalate when they
  should, versus silently answering wrong from the index alone, is an open
  measurement question (see ROADMAP.md's M3 grounding milestone).
- ASCII rendering is kept as an optional, explicitly qualitative fallback
  (model-agnostic gestalt, Set-of-Marks canvas) rather than a primary or
  cost-motivated channel.
