# Ink Context Format v2 — evidence-driven draft

Proposed protocol identifier: `ink-context/v2-draft`

Status: **draft under evaluation** — composed 2026-07-10 from the completed
transport program ([transport-findings.md](results/transport-findings.md)).
ICF v1 ([spec/ink-context-format-v1.md](../spec/ink-context-format-v1.md))
remains the shipped snapshot format; v2 wraps it in a stateful protocol.
Promotion gates at the end.

## What v2 is

v1 answers "what is the best single payload?"; v2 answers "what should
move across a *session*?" Four pieces, each with a measured verdict:

| piece | wire surface | evidence |
|---|---|---|
| **base** | a v1 payload (any tier), sent once | all of v1 |
| **pull** | `fetch_ink_region` tool (shipped); region → compact SVG + bboxes | H7/H7-S |
| **delta** | per-turn `{"delta": {"added_svg": ..., "erased": [ids]}}` | H6 |
| **graph** | `semantics` items + the `edges` field (shipped in SemanticItem) | H9 (corrected) |

Explicitly **rejected**: a multiresolution fidelity ladder (H8 — geometry
fidelity is not ink's binding constraint; 64-grid reads at parity on
synthetic and real-ink reading fails on style, not resolution).

## The delta piece

After the base, a producer SHOULD send only changes, keyed by stable
stroke ids in drawn order:

```json
{"delta": {"added_svg": "<path id=\"st_x\" d=\"...\"/>", "erased": ["st_y"]}}
```

- Added paths use the base's grid (the grid always spans the page, so
  deltas and base share one frame).
- Measured: accuracy identical to full resend on counting, combined-state
  and erase-tracking; window growth ~60 chars/turn vs ~2,300 (H6). A
  raster consumer cannot do this at all (0.25 combined counting, 0.00
  erase identification).
- Ids MAY be omitted from delta events when the base carries id→bbox
  bindings (H6's D2n ablation) — but ids in the *base* are load-bearing.

## The pull piece

Ship the index (bboxes ± cluster semantics), let the consumer fetch.
Measured pricing rule (H7-S): pull pays off **only** where the fetch does
not re-read history — ranked: in-turn tool loop > cached resume > cold
resume > stateless two-shot (loses). Producers on one-shot transports
SHOULD push instead. Legends for the coarse index MUST state what it is
reliably good for; hedged legends cause over-fetching (H8's RP arm
fetched on every reading question it could already answer).

## The graph piece

`semantics` items form a hierarchy via `edges` (directed, named):

```json
{"id": "st_07", "kind": "statement", "text": "ocean", "stroke_ids": [...],
 "region": [...], "edges": {"supports": "cl_01"}, "confidence": 0.9,
 "source": "neeh-geometric/0.1"}
```

- Measured (H9 corrected): oracle **edges + labels** lift level-crossing
  tasks 0.75 → 1.00 at +2.1% tokens. **Edges without labels do not help**
  (G1r ≤ flat): questions arrive in natural language, so an unlabeled
  graph adds an id-indirection the model bridges by reading geometry
  anyway. Producers SHOULD NOT ship structure-only graphs.
- The SDK's geometric recognizer (`neeh.semantics.build_semantics`)
  computes clusters (recovery 0.969) and directed links (F1 1.000,
  synthetic) — the missing input is per-cluster *text*, which lives in
  the perception tier: crop the cluster raster, transcribe once, attach
  as `text`, and let the label ride every subsequent turn as delta state.
- Every referenced stroke id must resolve; every edge target must name an
  item in the same list (both enforced by the reference implementation).

## Session accounting (normative for evaluation)

Cost claims about v2 MUST be reported as both raw input tokens and
uncached input (provider cache splits), per turn. Stateless replay is an
acceptable proxy only for *accumulating* arms (the replayed prompt equals
the real window); resend arms must be charged per turn.

## Promotion gates (v2-draft → spec/ink-context-format-v2.md)

1. **Labeled recognized graph** (G1rt: recognizer edges + transcribed
   labels) closes most of the G1r→G1 gap on T9 live.
2. **Real-ink recognizer eval**: clusters/links measured on S1 sketches,
   not only synthetic arrows.
3. **Demo session proof**: one assistant session using base + pull +
   delta + graph together, with per-turn token accounting showing the
   O(change) profile.
4. Second-model replication of H6 and H9 headline rows (claude backend).

## Reference implementation

- base/pull: `neeh.context.build_ink_context_v1`, `fetch_ink_region`
  (tool surface v1), demo `--context pull`.
- delta: wire shape validated in `research/harness/run_h6.py`; SDK
  emitter is gate-3 work.
- graph: `neeh.context.SemanticItem` (`edges` field),
  `neeh.semantics.build_semantics`, demo ships recognized semantics on
  every context build.
