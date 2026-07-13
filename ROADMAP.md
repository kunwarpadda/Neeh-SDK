# Neeh SDK roadmap

Updated 2026-07-12 from current code, tests, and controlled internal experiments.

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

- Expand beyond synthetic shapes to handwriting, math, diagrams, corrections,
  dense notes, and multi-turn edits from real devices/writers.
- Compare raster-only, raster+geometry, index-only, active-index, marked-index,
  and analyzer-first policies with GPT-5.5/high fixed for Codex runs.
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

