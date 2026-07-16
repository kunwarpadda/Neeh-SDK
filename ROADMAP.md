# Neeh SDK roadmap

Updated 2026-07-14 from current code, tests, and controlled internal experiments.

## Product thesis

Neeh makes digital ink safely usable by applications and language-model agents
without flattening the document into pixels or dumping every point into a
prompt.

The active architecture is:

1. **Ink source of truth** - ordered strokes, timing, pressure, tilt,
   authorship, stable ids, pages, layers, persistence, and native hosts.
2. **Deterministic analysis** - compute exact temporal/geometric facts locally.
3. **Structured map** - expose compact marks, relations, and confidence.
4. **Query-aware retrieval** - promote only relevant strokes, moments, and
   regions into an agent working set.
5. **Raster/geometry on demand** - use pixels or paths only when the structured
   evidence is insufficient.
6. **Validated edits** - act through bounded anchored tools, dry-run atomically,
   and allow one repair pass.

A native learned ink encoder is not on the active roadmap. It may be reconsidered
only after a benchmark demonstrates a valuable failure that this stack cannot
solve within its latency and context budgets.

## Shipped substrate

- Python document, ink, canvas, history, rendering, context, semantics, and
  tool packages.
- C++17 core, C ABI, SVG/RGBA rendering, CMake package, and native tests.
- UIM 3.1 adapter plus versioned `neeh-uim/v1` profile.
- Versioned `ink-context/v0`, `ink-context/v1`, and `neeh-tools/v1` contracts.
- Structured `ink-index/v1`, ASCII rendering, region fetch, and stable target ids.
- Reusable Codex/Claude/mock assistant adapters and inspectable model payloads.
- IAI map-first policies, read-only MCP perception, telemetry, bounded working
  set, atomic action validation, and one repair pass.
- Experimental `ink-timeline/v1` and Ink Moment Retrieval.
- Deterministic `ink-analysis/v1` analyzers split into exact measurements
  (latest mark, creation order, stroke dynamics, containment, intersection,
  endpoints, spatial collision) and inferences that carry confidence and
  provenance (cross-out, connector, and grouping candidates).
- Task-specific reducers (`reduce_ink`) for recent changes, overwritten ink,
  revisions, ambiguous connectors, and page summaries.
- Analyzer-signal retrieval ranking and explicit intent routing that
  pre-computes the matching reducer into the IAI observation workspace.
- Append-only `ink-eventlog/v1` document event log capturing add, erase, move,
  restyle, group, agent, undo, and redo mutations with stable ids, plus
  replay/diff/snapshot/recover queries over erased and replaced ink.
- `ink-timeline/v1` reconstruction from the event log, with an honest
  `history_complete` claim gated on the log actually covering the page.
- Event-log persistence: full snapshot serialization, a `neeh-session/v1`
  document+log bundle (`Canvas.save_session`/`load_session`), and a UIM
  `.events.json` sidecar (`save_uim(..., event_log=)` / `load_uim_events`).
- `Canvas.group`/`ungroup` recording grouping in the log, with current
  membership folded back from group/ungroup events.
- Move 3 grounding harness (`research/move3_grounding.py`): a deterministic
  `--dry-run` policy comparison (raster-only, raster+geometry, index-only,
  active-index, marked-index, analyzer-first) over history-bearing tasks,
  scoring grounding level against context and pixel cost with adversarial
  leak/balance controls. The live GPT-5.5 accuracy/abstention arm and real-device
  datasets remain to be run (M3 exit gate).
- Public `benchmarks/` evidence surface: the three harnesses, their raw results
  (dry-run and archived GPT-5.5 transcripts), and a claim→command→result
  reproducibility index, linked from the README Evidence section.
- JSON Schema conformance fixtures (`spec/fixtures/`) for `ink-analysis/v1`
  (analyzer + reducer envelopes) and `ink-eventlog/v1` (compact + snapshot),
  with golden payloads, live-output conformance tests, and a documented
  ignore-unknown-fields compatibility policy; experimental protocols surfaced
  via `neeh.protocol.experimental_protocol_versions()`.
- MCP hardening: JSON-RPC-correct error codes (-32700 parse / -32600 invalid
  request), request-id preservation on unexpected failures, and adversarial
  tests for malformed input, wrong-shaped params, unknown tools, and budget
  exhaustion over stdio.
- Native analyzer parity (`neeh::analysis`, C++17 + C ABI): all seven
  measurement operations (latest mark, creation order, stroke dynamics,
  containment, exact intersection, spatial collision, endpoints) with
  semantics mirroring the Python analyzers (same ordering keys, same 8-way
  compass with ties-to-even rounding); C ABI exposes `neeh_stroke_analyze`,
  `neeh_page_latest_mark`, and `neeh_page_creation_order`. Inference
  operations remain Python-only by design.
- Release readiness: installed-artifact packaging gate (wheel into a fresh
  venv; caught and fixed a Pillow hard-import and a stale `__version__`),
  `benchmarks/perf.py` latency/memory harness (drove grid-bucketed spatial
  analysis: page_summary 25x, spatial_collision 18x, workspace 3.7x faster
  at 5000 strokes), a public API reference (docs/API.md), and a versioning/
  deprecation/release-gate policy (docs/RELEASING.md).
- Controlled render-identical and token-scaling experiments. A render-identical
  pairs study establishes that ink history prevents PNG-only confabulation; a
  token-budget scaling study establishes that local reduction beats both
  coordinate and index dumps for mechanical tasks.

## Active milestones

### M1 - Finish the analysis plane

- Add exact containment, intersection, endpoint, connector, grouping, and
  spatial-collision analyzers.
- Add task-specific reducers for recent changes, revisions, overwritten math,
  ambiguous connectors, and page/object summaries.
- Separate recognizer claims from exact measurements with confidence and
  provenance on every inferred fact.
- Replace lexical-only retrieval ranking with analyzer signals and explicit
  intent routing.

Exit gate: representative mechanical ink questions are answered from bounded
analyzer results without page-sized prompt growth.

### M2 - Make history complete

- Add an append-only document event log covering add, erase, move, restyle,
  undo, redo, grouping, and agent actions.
- Give events stable ids and persist them across internal snapshots and UIM
  sidecar/interchange boundaries where possible.
- Rebuild `ink-timeline/v1` from the event log so `history_complete=true` is an
  honest claim.
- Add before/after/diff/replay queries over erased and replaced ink.

Exit gate: correction, replacement, and provenance tasks survive save/load and
can be replayed without reconstructing history from the final page.

### M3 - Prove grounding on real ink

Status 2026-07-14: first live arm complete (four synthetic kinds + six kinds
built from human MathWriting ink with scripted, event-logged histories;
gpt-5.6-luna/high — owner decision superseding the GPT-5.5 pin; 360-row grid,
`benchmarks/README.md` §B2). Structured arms beat the best raster arm 0.72–0.78
vs 0.30 at zero pixels and 6/6 exact action targets, but the exit gate is NOT
met: priced context does not drop against cheap cropped pixels, and misrouted/
mis-ranked precomputed evidence produces more unsupported claims than the
all-abstaining raster baseline. Three mechanistic analysis-plane defects
account for the failures (intent-routing order, geometry-only revisions
reducer ignoring the event log, recorded groups surfacing in no evidence
channel) — fixing them and re-measuring is the path to the gate, alongside the
remaining scope below.

Status 2026-07-15: four of six planned genuine-device recordings landed
(`research/data/device/raw/{s1_notes,s2_math,s3_diagram,s4_dense}`, real
device captures on a Samsung Galaxy Tab S9/S10, ~671 live strokes,
32 real erasures, no pressure/tilt on this hardware). `s5_edit` and
`s6_crossouts` were not recorded (time-boxed); real undo/redo and genuine
scribble-cross-out therefore remain untested against device data (both paths
are still covered by the synthetic fixture) and every capture so far is
single-page. All four pass the deterministic real-capture regression gate
(`benchmarks/real_capture_regression.py`) with 100% erase/history recovery,
and two new `dc_erased_ink`/`dc_recent_change` task kinds in
`benchmarks/move3_grounding.py` draw round-robin across whichever sessions are
present. This work directly found and fixed two real defects: a Samsung S
Pen pressure/tilt capability-detection race in the device recorder (fixed
in `research_capture.cpp`/`renderer.cpp`/`MainActivity.kt`), and a
`grouping_candidates`/`connector_candidates` proximity margin that scaled off
raw page dimensions instead of content extent — invisible on synthetic scenes
sized to their content, but badly wrong on a real device page (the tablet's
full screen resolution) — caught specifically by `s3_diagram`'s real,
multi-stroke diagram geometry (`neeh/agents/analyzers.py`). A live smoke
sweep across all four sessions also surfaced a new failure mode not seen on
a single session: under `index-only`, gpt-5.6-luna sometimes fabricates a
plausible-sounding but factually ungrounded citation (an invented gap in
stroke-id sequencing) rather than abstaining -- a genuine false-explanation
case worth tracking alongside the three routing defects above.

Status 2026-07-15 (later): all three analysis-plane defects are fixed and
live-verified. (1) Intent routing checks change/erase intents before the
"most recent" intent, so modification questions reach the event log instead
of being silently rewritten into drawing-time questions; an "erased" intent
now exists at all. (2) `revisions` and `recent_changes` read the event log:
erase and erase-then-rewrite arrive as exact confidence-1.0 facts ranked
above geometric inference, and a move or erase counts as the most recent
change. (3) Recorded group membership surfaces as a `recorded_groups`
measurement, in the workspace page map for every policy, and in
`page_summary`. Re-measuring the five defect-poisoned kinds live
(gpt-5.6-luna/high, `benchmarks/results/move3_ledger_v3.jsonl`):
analyzer-first went 15/30 correct with 8 false explanations → 29/30 correct
with 1, including recent_change 0/6→6/6, mw_grouping 0/6→6/6, and
mw_erased_rewrite 3/6→6/6 at zero pixels and ~1.4k estimated tokens. The
live loop also caught two evidence-quality defects in the first fix attempt
-- routed `recorded_groups` silently truncated membership at the group
limit, and `recent_changes` exposed wall-clock timestamps that tie within a
millisecond, which the model rightly refused to rank -- fixed by a declared
24-id member cap and by exposing the log's tie-proof `seq` order. Remaining
for the gate: a full 360-row grid re-run to restate the exit-gate clauses
(priced context vs cheap cropped pixels) with the fixed analysis plane.

- Expand beyond synthetic shapes to handwriting, math, diagrams, corrections,
  dense notes, and multi-turn edits from real devices/writers.
- Compare raster-only, raster+geometry, index-only, active-index, marked-index,
  and analyzer-first policies with a fixed pinned model for Codex runs
  (gpt-5.6-luna/high as of 2026-07-14).
- Measure exact target/action accuracy, abstention, false explanations,
  retrieval calls, context, pixels, latency, repair success, and human
  acceptance.
- Add adversarial controls that detect leaked answers and benchmark
  contamination.

Exit gate: analyzer-first active IAI matches or beats raster grounding while
materially reducing average model context and unsupported claims.

### M4 - Publish and harden the agent protocols

- Decide the stable boundary for `ink-analysis`, `ink-index`, `ink-timeline`,
  and IAI; add accepted identifiers to protocol discovery only after schemas
  and conformance fixtures stabilize.
- Add JSON Schema fixtures, unknown-field behavior, compatibility policy, and
  cross-version tests.
- Add native parity for analyzers that product hosts need off Python.
- Harden MCP limits, malformed-input handling, telemetry, privacy controls,
  and denial-of-service bounds.

Exit gate: another application can integrate the protocols without importing
the assistant example or depending on private Python snapshot shapes.

### M5 - Release readiness

- Resolve pre-alpha API naming and packaging boundaries.
- Complete installation, API reference, examples, migration, and security docs.
- Test supported Python/native platform matrices from installed artifacts.
- Benchmark latency and memory on realistic notebook pages and devices.
- Define semantic versioning, deprecation, and release gates.

Exit gate: first externally consumable SDK release candidate.

## Release strategy

Kept modest while the project is pre-alpha:

- **Protocol identifiers, not the package version, are the stability
  contract.** `ink-context/v1`, `neeh-tools/v1`, `ink-agent-interface/v1`,
  etc. are versioned independently; applications should discover them at
  runtime rather than infer compatibility from `neeh`'s package version (see
  README).
- **Package versioning follows semantic versioning once M5 lands.** Before a
  `1.0`, a `0.x` release may include breaking Python/native API changes
  between minor versions; a protocol identifier bump is required for any
  breaking wire-format change regardless of package version.
- **Tags are annotated git tags on `main`, one release commit per tag**
  (`chore(release): vX.Y.Z`), matching the existing `v0.1.0` precedent —
  significant versions stay identifiable directly from git history, not only
  from a changelog.
- **GitHub Releases mark each tag publicly** with the substance of what
  shipped, once the repository is public. Archival (e.g. a Zenodo DOI per
  release) is a reasonable next step once there's a public repository to
  archive, so releases stay independently citable — see
  [CITATION.cff](CITATION.cff).

## Explicitly not planned

- Training an LLM from scratch.
- Building a native ink encoder, Q-Former, learned-query bridge, or LoRA path
  without a failed bounded-analyzer baseline.
- Sending entire point streams or full document histories to the model by
  default.
- Treating heuristic cross-out/grouping recognition as ground truth.
- Using ASCII as the headline representation; it remains an optional gestalt
  and text-only fallback.

## Reconsidering a learned encoder

The gate is empirical, not aspirational. Reopen the question only if all are
true:

1. a valuable real task repeatedly fails with exact analyzers, structured
   retrieval, targeted paths, and raster evidence;
2. the failure is representational rather than a recognizer/data/tool defect;
3. a learned prototype beats the complete structured baseline on held-out
   writers/devices;
4. the gain justifies training data, inference, privacy, deployment, and
   maintenance costs.

