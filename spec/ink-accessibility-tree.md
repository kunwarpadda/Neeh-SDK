# Design note: the ink accessibility tree

Status: implementation direction, not yet a normative protocol. This note
records why Neeh should treat a **structured, labeled index** as the primary way
a model perceives a page, with detail exposed through a small agent interface
rather than shipped eagerly on every turn.

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

## The coding-agent refinement: an Ink Agent Interface

The closest analogy is now coding agents, not screenshot-only GUI agents. A
coding agent does not receive the whole repository in every prompt. It gets a
compact map, then uses narrow search/view actions to build a working set and
uses test or linter feedback to repair mistakes. The research gives five useful
constraints for Neeh:

1. **Design the interface for the model.** SWE-agent found that simple actions,
   compact operations, concise environment feedback, and automatic guardrails
   materially improve a fixed model. For ink, `view_region`, `get_ink`, and
   anchored edit actions should be small and explicit; invalid ids, collisions,
   and impossible placements should produce short repairable observations, not
   silently degraded output. [SWE-agent ACI paper](https://papers.neurips.cc/paper_files/paper/2024/file/5a7c947568c1b1328ccc5230172e1e7c-Paper-Conference.pdf)
2. **Give a ranked map, not a dump.** Aider's repository map keeps key symbols
   under a token budget and ranks them using the dependency graph and current
   chat. The ink index should likewise rank marks by task relevance, recency,
   spatial/semantic relations, and current selection rather than only taking a
   fixed newest-stroke tail. [Aider repository map](https://aider.chat/docs/repomap.html)
3. **Retrieval should be iterative and optional.** RepoCoder improves over
   one-shot retrieval by using the model's first hypothesis to retrieve better
   context; RLCoder adds an explicit stop decision because extra context is not
   always useful. An ink planner should be able to localize from the index,
   inspect only the likely region, and stop when its target is unambiguous.
   [RepoCoder](https://arxiv.org/abs/2303.12570),
   [RLCoder](https://arxiv.org/abs/2407.19487)
4. **Context is working state, not append-only history.** CAT makes context
   maintenance a callable action over stable task semantics, condensed
   long-term memory, and high-fidelity recent interactions. OpenHands similarly
   keeps an event log while presenting a condensed view. Neeh should preserve
   stable page/task facts, keep new and currently targeted ink at high fidelity,
   and collapse answered ink to a summary with recoverable ids.
   [Context as a Tool](https://arxiv.org/abs/2512.22087),
   [OpenHands condenser](https://docs.openhands.dev/sdk/arch/condenser)
5. **Prefer a staged baseline over unconstrained autonomy.** Agentless shows
   that a simple localize → repair → validate pipeline can rival more elaborate
   software agents, and that correct localization strongly tracks final solve
   rate. Neeh's default loop should therefore be bounded: localize → inspect if
   needed → act → validate, with at most one repair pass before surfacing a
   failure. [Agentless](https://arxiv.org/abs/2407.01489)

This makes the next protocol an **Ink Agent Interface (IAI)** with two distinct
surfaces:

- **Observation workspace:** `task`, a budgeted `page_map`, `recent_delta`, a
  high-fidelity `working_set`, and explicit `budget`/`capabilities` metadata.
- **Perception actions:** `analyze_ink` (deterministic reducers), `find_marks` (query the structured map), `view_region`
  (`raster` or `ascii`), `get_ink` (bboxes or paths for ids/region), and
  `expand_relations` (neighbors of a recognized object). Each returns a bounded
  observation and declares its page-space region and fidelity.
- **Edit actions:** the existing anchored tools (`annotate`, `connect`, `mark`,
  `insert_text`) plus sparse free placement where appropriate.
- **Validation feedback:** action validity, missing/ambiguous ids, collision or
  overflow details, and the affected region. A failed batch gets one concise
  repair turn rather than partial silent success.
- **Context maintenance:** pin the current working set, summarize answered ink,
  and retain the append-only page/event history outside the prompt so detail is
recoverable.

The implemented experimental wire shape is specified in
[`ink-agent-interface-v1.md`](ink-agent-interface-v1.md).

The current assistant's `active-index` mode is the first compatibility adapter for
this direction: it bootstraps both Codex and Claude with `build_ink_index`,
exposes bounded typed perception actions through a read-only MCP server, and
keeps `raster-always` as the control arm. Edit batches are dry-run atomically
and receive at most one repair pass before live application.

## Evaluation: compare policies, not only payloads

The decisive evaluation should retain the A/B/C payload measurements but add an
agentic arm:

| Policy | Bootstrap | Allowed escalation |
|---|---|---|
| P0 raster-always | raster + compact geometry | none |
| P1 index-only | structured index | none |
| P2 active-index | structured index | region raster and/or stroke detail |
| P3 marked-index | structured index + marks overlay | region raster/stroke detail |

Report results by task class (read, point, annotate, correct, relate), because a
single aggregate hides whether the index grounds shapes well but forces raster
retrieval for handwriting. Alongside final task accuracy, record target-id
accuracy, invalid-action rate, repair success, number and type of perception
actions, initial and paged-in tokens/pixels, latency, and cost. P2 is the
production candidate only if it approaches P0 accuracy while materially
reducing average paged-in context; P1 remains the clean grounding ablation.

This follows the same harness lesson reported by OpenAI's coding-agent work:
give the agent a map and mechanically useful feedback loops, not a giant manual
or an undifferentiated context dump.
[OpenAI harness engineering](https://openai.com/index/harness-engineering/)

## What still needs an eval

The token economics are settled here; **grounding and escalation policy** are
not. The next experiment should measure whether the model points and annotates
at least as well from the index alone, and whether active retrieval restores
raster-level reading/correction accuracy without making every request pay the
raster cost. The web/GUI and coding-agent evidence predicts that map-first,
tool-mediated context will help; ink should be confirmed, not assumed.

## References

Set-of-Mark (arXiv:2310.11441); OmniParser (Microsoft); accessibility-tree vs
screenshot token economics; ASCIIBench (arXiv:2512.04125); MemGPT
(arXiv:2310.08560); Manus context-engineering notes; Aider repo map.
