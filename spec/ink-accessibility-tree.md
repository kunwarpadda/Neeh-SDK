# Design note: the ink accessibility tree

Status: exploratory direction, not yet a normative protocol. This note records
why Neeh should treat a **structured, labeled index** as the primary way a model
perceives a page, with the raster demoted to a secondary, on-demand channel.

## The convergence

How to show a 2D visual surface to an LLM agent — cheaply *and* actionably — was
solved independently by web, GUI, and computer-use agents, and they converged on
the same shape:

- **Structured index as the primary channel.** Web agents send the
  *accessibility tree* (~200–4,000 tokens) rather than a screenshot (~50,000
  tokens) — a 10×+ gap. Microsoft's OmniParser does the same for raw pixels,
  parsing a screenshot into a labeled element list and lifting GPT-4V grounding
  from 70.5% to 93.8%.
- **Set-of-Marks binding.** Overlaying numbered marks on regions so the model
  references and acts by id measurably improves grounding (Yang et al., 2023;
  WebVoyager).
- **Raster is secondary and on-demand.** The image is kept for layout and for
  reading detail, paged in when the structured channel is insufficient (MemGPT,
  Manus file-system-as-memory).

Neeh already has every primitive: the recognizer is its OmniParser, `ink.hints`
plus stroke ids are its Set-of-Marks, the tool surface acts by `stroke_id`, and
`fetch_ink_region` is its on-demand pager. The change is one of *emphasis* —
make the structured index primary and the raster on-demand.

## Measured on ink (examples/compare_context_arms.py)

| Arm | tyred_logo (3 strokes) | sidebar + question (46 strokes) |
|---|---|---|
| A. raster + SVG geometry | ~109 tok | ~1025 tok |
| B. **structured index** (`build_ink_index`) | ~115 tok | **~190 tok (5.4× cheaper)** |
| C. structured + ASCII gestalt | ~423 tok | ~380 tok |

Findings, honestly:

- **The structured index is the win**, and it grows with the page: on a
  realistic page it is ~5× cheaper because per-stroke SVG geometry and the
  raster collapse into a marks list, with handwriting summarized as a count.
- **ASCII is not a token win** — grid whitespace costs more than the index
  alone. Its value is qualitative: it is model-agnostic (text-only planners can
  "see" layout) and a natural Set-of-Marks canvas. Treat it as an *option* for
  gestalt / text-only backends, not the primary channel. (Consistent with
  ASCIIBench: models read ASCII OCR-like, not truly spatially.)
- Trivial pages are cheap under any arm; the index's advantage appears exactly
  when a page gets busy, which is when cost matters.

## Proposed shape (ICF-v3 sketch)

- **Primary:** `build_ink_index` — `marks` (id, shape, position, bbox) plus a
  handwriting count. Add `relations` (recognizer links between marks) next.
- **Marks layer:** ids are the Set-of-Marks; optionally render them onto the
  ASCII gestalt or a raster overlay when a perceptual view is warranted.
- **On-demand detail:** `fetch_ink_region` for precise geometry; the raster only
  for perception-tier reading of handwriting.
- **Across turns:** page answered ink down to index-only (delta/recency),
  keeping geometry for new or relevant strokes.

## What still needs an eval

The token economics are settled here; the **accuracy** question is not. Whether
a model points and annotates *at least as well* from the structured index (arm
B) as from the raster (arm A) must be measured by running the planner on the
pointing/annotate tasks through the model CLIs — the token win only matters if
grounding holds. The web/GUI evidence predicts it improves; ink should be
confirmed, not assumed.

## References

Set-of-Mark (arXiv:2310.11441); OmniParser (Microsoft); accessibility-tree vs
screenshot token economics; ASCIIBench (arXiv:2512.04125); MemGPT
(arXiv:2310.08560); Manus context-engineering notes; Aider repo map.
