# M0 — Ink Context Research Protocol

Status: v0.1 draft, 2026-07-09. Governs milestones M1–M3.
Evidence base: [prior-art-digest.md](prior-art-digest.md).

## 1. Purpose

Neeh's central claim is that stroke-native structured context can replace raster rendering as
the way models perceive ink. This protocol defines the hypotheses, encodings, tasks, corpora,
metrics, and decision rules used to test that claim. Its output is the evidence that designs
ICF v1. The protocol is pre-registered in spirit: hypotheses and decision rules are stated
before data collection; changes after M1 data exists are recorded in a changelog (§10).

Nothing in this protocol modifies shipped contracts. `ink-context/v0`, `neeh-tools/v1`, and
`neeh-uim/v1` stay frozen; experimental encoders live in the research harness, not in `neeh/`.
Encodings graduate into an ICF v1 draft only through the decision rules in §8.

## 2. Hypotheses

- **H1 — zero-shot perception parity.** At least one text encoding of ink achieves ≥95% of
  raster-arm accuracy on perception tasks (T1–T3) on a frontier model, zero-shot, at ≤60% of
  the raster arm's input-token cost. *(Prior art: proven with fine-tuned small VLMs
  [arXiv 2402.15307]; unproven zero-shot — this is the ownable gap.)*
- **H2 — addressing is vector-native.** On addressing and action tasks (T4–T5), any vector arm
  outperforms the best raster-only arm by a wide margin, because raster context provides no
  stable references to act on. Expected: raster arms near floor.
- **H3 — abstraction wins global, compression wins local.** Grouped/described encodings (E5)
  beat coordinate encodings (E2–E4) on global-layout tasks (T3); quantized-relative (E2) matches
  raw ICF v0 (E1) on local tasks (T1) at a fraction of the tokens. *(Motivated by VGBench and
  VDLM findings; by the local >80% / global <50% spatial-reasoning gap.)*
- **H4 — hybrid dominates at fixed budget.** At a fixed total token budget, a mixed
  raster+vector arm Pareto-dominates both pure channels across task families.
- **H5 — temporal signal is real and raster-invisible.** On temporal tasks (T6), any
  order-preserving vector arm succeeds where static raster arms are at chance; the temporal
  raster (E6) recovers part of the gap without text.

Falsification is a reportable outcome. If raster dominates T1–T3 everywhere at every budget,
ICF v1 keeps raster primary and vector context is repositioned as the addressing/editing channel
(H2 alone still justifies it).

## 3. Encoding arms

Every encoder is a deterministic, versioned function `encode(page, params) -> str` (or PNG for
raster arms). Version id format: `E<n>/<semver>`, recorded in every run row. Exact grammars are
fixed in the harness; summaries:

| Arm | Name | Spec summary |
|---|---|---|
| E0 | Raster control | Page PNG at render scale 1.0 (1000×1414 → ~1,836 visual tokens on Claude). No vector. |
| E1a | ICF v0 status quo | `build_ink_context` JSON + attached PNG, defaults (80 strokes / 12 pts). The shipped baseline. |
| E1b | ICF v0 vector-only | E1a JSON without the image. Isolates what today's vector record is worth. |
| E2 | Quantized relative polyline (QRP) | Per stroke: header `id author brush`; first point absolute on an integer grid (G=256 across the long page edge), subsequent points as integer Δx Δy; resampled by arc length (target ~Δ=4 grid units); stroke order = document order. No per-point time; `created_at` rank retained per stroke. *(Google 2402.15307 recipe, adapted.)* |
| E3 | Grid language | Coarse 50×50 lettered/numbered grid; strokes as cell-sequence strings with an in-context legend and one worked example in the prompt. *(SketchAgent recipe.)* |
| E4 | SVG path text | `<path id="st_…" d="M x y L x y …"/>` with coordinates quantized to integers; page as `<svg viewBox>`. Tests the "models have seen SVG" bet directly. |
| E5 | Structural scene graph | Strokes clustered (temporal gap + spatial proximity) into groups; per group: bbox, stroke count, stroke ids, orientation, size class, per-stroke compact geometry (dominant direction sequence, curvature class); NO recognizer output — structure only, so it's computable today. |
| E6 | Temporal raster | PNG with stroke order/velocity in color channels (InkFM style): hue by stroke rank, value by point velocity. Raster transport carrying temporal signal. |
| E7 | Hybrid | Best-performing text arm + downscaled raster (0.5 scale ≈ 460 visual tokens), for H4. Composed after first results. |

Fairness rules: identical page content across arms; identical task instruction block; each arm
gets one fixed legend/preamble explaining its encoding (in-context teaching is part of the
encoding, per SketchAgent); prompt text outside the context block is byte-identical across arms.

## 4. Task families

Each task instance is generated with ground truth from the Neeh document itself. Scoring is
automatic; no human rating in M1–M2.

| Family | Task | Ground truth / metric |
|---|---|---|
| T1 Local perception | Transcribe written text/math; classify a sketch | CER (text/LaTeX); accuracy (class) |
| T2 Object comprehension | Count shapes; identify shape kinds; compare sizes/lengths | Exact-match accuracy |
| T3 Global layout | Spatial relations ("is A left of B"), region occupancy ("what is in the top-right"), overlap/crossing questions | Accuracy |
| T4 Addressing | "Which stroke ids form the word/shape X?" | Set F1 against ground-truth stroke sets |
| T5 Action grounding | "Highlight X / circle Y / erase Z" executed through `neeh-tools/v1` calls | Correct-target rate (erase: exact stroke set; highlight/circle: IoU ≥ 0.5 with target region, no overlap with foreign ink) |
| T6 Temporal | "What was written last / in what order / what changed after time t" | Order accuracy (Kendall-τ for full orderings, exact match for pointwise) |

T4–T6 are the differentiator families: raster arms are expected near floor on T4/T5 (no ids)
and at chance on T6 (no time). They measure the capability delta, not just parity.

## 5. Corpora

Staged; every corpus enters through an adapter that maps its native format to a Neeh `Document`
(points as `[x, y, t_ms, pressure?]`), so all encoders and task generators run unchanged.

- **S0 — Synthetic (M1).** Neeh-generated: `write_text` (Hershey) words/sentences, programmatic
  shapes/arrows/diagrams, multi-layer user+agent pages, scripted temporal sequences. Perfect
  labels, no licensing, unlimited volume. *Known limitation:* Hershey print is not human
  handwriting; T1 results on S0 are an upper bound on legibility. Mitigation: parameterized
  perturbation (jitter, baseline wobble, point dropout) with severity swept, and S2/S3
  validation before any ICF v1 claim.
- **S1 — Quick, Draw!** (CC BY 4.0; raw ndjson `x[], y[], t[]`). Sketch classification (T1),
  counting/relations on composed multi-sketch pages (T2/T3). *Contamination note:* models may
  know Quick!Draw categories; report S0-vs-S1 deltas rather than S1 absolutes.
- **S2 — CROHME** (CC BY-NC-SA; InkML with symbol-level stroke segmentation). Real-data T4
  addressing: "which strokes form the exponent" has ground truth for free.
- **S3 — IAM-OnDB / MathWriting** (research licenses). Real-handwriting T1 validation at M2.

Redistribution: only S0 fixtures ship in-repo. S1–S3 are fetched by loader scripts; NC-licensed
data never enters the package or published fixtures.

## 6. Models and inference protocol

- M1: one frontier Claude model and one small Claude model (capability spread on a single API).
  M2 adds at least one non-Claude frontier model for generality.
- Zero-shot only through M2 (no fine-tuning): temperature 0, fixed max reasoning budget across
  arms (reasoning aids low-level formats per VGBench — it must be constant to not confound),
  N ≥ 3 repeats per cell for variance, refusals/format failures scored as errors and reported
  separately as a failure rate.
- Token accounting: input tokens measured via the API token-counting endpoint per request —
  never estimated. Visual tokens per Claude's 28×28-patch rule enter the same ledger.

## 7. Infrastructure (built in M1)

Lives in `research/harness/` (Python package importing `neeh`; not shipped with the SDK):

1. **Encoder registry** — E0–E7 as versioned pure functions with golden-file tests.
2. **Corpus adapters** — S0 generator; ndjson/InkML/XML loaders for S1–S3.
3. **Task generators** — per family, seeded, emitting (page, prompt, ground truth, scorer id).
4. **Runner** — model × arm × task sweeps; resumable; rate-limit aware.
5. **Scorers** — CER, exact match, set F1, IoU-based action scoring, Kendall-τ.
6. **Ledger** — append-only JSONL: run id, encoder version, model id, prompt hash, seed, corpus
   revision, tokens in/out, score, failure class. Summary tables and Pareto plots derived from
   the ledger only. A result that isn't in the ledger doesn't exist.

Reproducibility bar: any reported number regenerable from (ledger row → seed + versions).

## 8. Decision rules for ICF v1 (pre-registered)

An encoding graduates to ICF v1 candidate if either:

- **Parity gate:** ≥95% of the E0 raster arm's accuracy on T1–T3 (macro-average per family) at
  ≤60% of E0's token cost, on the frontier model, on at least one real corpus (S1–S3); or
- **Capability gate:** ≥80% set-F1 on T4 and ≥80% correct-target rate on T5 at any cost, where
  the raster arm scores <20% — i.e., it unlocks what raster cannot do at all.

ICF v1 design then follows the data: if a text arm passes the parity gate, raster becomes
optional in v1; if only the capability gate passes, v1 keeps raster primary and adds the winning
vector encoding as the addressing channel. Threshold changes after M1 data exists require a
changelog entry with rationale (§10).

## 9. Milestones and exit criteria

| Milestone | Scope | Exit criterion |
|---|---|---|
| M1 | S0 corpus; arms E0, E1a, E1b, E2, E4; tasks T1, T3, T4; two Claude models | Ledger with full sweep; first Pareto frontiers; the ICF-v0-costs-more-than-PNG conjecture measured |
| M2 | + S1/S2 (S3 as available); + E3, E5, E6, E7; all task families; + one non-Claude model | Decision rules §8 evaluated with confidence intervals; synthetic-vs-real deltas reported |
| M3 | ICF v1 draft spec + conformance tests, derived from M2 evidence; negative results documented either way | Spec review ready |

## 10. Threats to validity (acknowledged up front)

1. **Prompt sensitivity.** A bad legend can sink a good encoding. Mitigation: two legend
   variants per arm in M1; report the max and the spread.
2. **Training-data contamination.** Quick!Draw categories, SVG idioms. Mitigation: S0 synthetic
   novel content as the control; report deltas.
3. **Synthetic-real gap.** Hershey ≠ handwriting. Mitigation: perturbation sweep + S2/S3 gates
   before any v1 claim.
4. **Reasoning confound.** CoT budget differentially helps low-level encodings. Mitigation:
   fixed reasoning budget across arms; a budget-sweep sub-experiment if variance warrants.
5. **Model nondeterminism.** Temperature 0 + N ≥ 3 repeats; report variance, not just means.
6. **Experimenter drift.** Decision rules pre-registered here; post-hoc changes logged:

Changelog:
- v0.1 (2026-07-09) — initial protocol.
- v0.2 (2026-07-09) — M1 inference runs through local `claude` / `codex` CLI logins instead of
  raw APIs (owner decision). Consequences: (a) temperature is not controllable — repeats measure
  variance as before; (b) reported token usage includes CLI scaffolding, so per-arm context cost
  is computed as the delta against a CTRL (empty-context) arm run per model with an otherwise
  byte-identical prompt; (c) the free token-counting endpoint is unavailable — exact offline
  measurements (context chars, PNG bytes, visual tokens by the 28×28-patch rule) are recorded in
  `results/context-sizes.md` beside the ledger's model-reported usage.
- v0.3 (2026-07-09) — M2 harness components (arms E3/E5/E6; families T2/T5/T6 with executed
  action scoring) built ahead of the live M1 sweep so one sweep session can cover both
  milestones. Milestone exit criteria in §9 are unchanged; E7 still waits for first results.
- v0.4 (2026-07-10) — E7 composed from the live M1 evidence (results/m1-findings.md), amending
  the §2 placeholder: full-scale E0 raster + compact SVG whose path data uses E2's resampling
  and integer-grid quantization (`M x y` + relative `l` offsets, one `<path id>` per stroke),
  rather than a downscaled raster — M1 showed the vector side must carry addressable IDs in a
  familiar syntax (E4 = 1.000 on T4 at ~4× less than ICF v0), and E2-grade geometry suffices
  for layout. A secondary arm E7v (the compact SVG alone, no raster) probes whether a pure-text
  arm holds the whole frontier. Also: sweep resume now treats a cell's *latest* ledger row as
  authoritative — `--retry-failed` re-runs cells whose latest row failed (quota outages), and
  reports deduplicate to the newest row per key.
- v0.5 (2026-07-10) — reasoning-effort amendment. ChatGPT-account codex rejects every explicit
  `--model` value on CLI 0.133.0, so conditions are set via the CODEX_HOME config
  (`model_reasoning_effort`) and named in the ledger with `--model-label`. The M2 matrix
  completed across an effort split: `default-high` (morning rows, effort high) and `default`
  (afternoon completion, effort low, 0 failures). Cross-split comparisons are caveated in
  results/m2-findings.md; subsequent sweeps run at effort low uniformly, which also satisfies
  the §5 risk-4 fixed-reasoning-budget mitigation.
