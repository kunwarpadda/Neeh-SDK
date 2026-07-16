# Neeh benchmarks — reproducible evidence

Every claim Neeh makes about digital ink as model context is backed by a
harness you can run. This page maps each **claim → command → expected numbers →
raw result**, split into two tiers of verifiability:

- **Tier A — reproducible by anyone.** Deterministic `--dry-run` harnesses.
  No API key, no model, no secrets. You clone the repo and get the exact
  numbers below. This is the credential-free core of the evidence.
- **Tier B — needs a live model.** Live runs through the Codex/Claude CLIs.
  Not reproducible without your own credentials and quota, so we archive the
  **raw model outputs** here for inspection.

```bash
pip install -e ".[png]"          # Pillow, for the raster arms
python -m pytest benchmarks/ -q  # the harnesses' own ground-truth tests (43)
```

---

## Tier A — reproducible by anyone (`--dry-run`)

### A1. Pixels destroy ink history

Byte-identical renders can carry opposite history. The generator certifies that
pairs differing only in draw direction/order rasterize to **identical pixels**.

```bash
python benchmarks/move1_render_identical_pairs.py --dry-run
```

| Metric | Value |
|---|---|
| Render-identical pairs certified | **18 / 18** |
| Token cost — png / png+struct / coords | 379 / 501 / 221 |

Raw: [`results/move1_pixel_identity_dryrun.json`](results/move1_pixel_identity_dryrun.json)

### A2. Structured reduction is flat; serialization isn't

As ink density grows, serialized ink grows linearly and crosses a representative
context budget; a deterministic reducer answers the same question at ~constant
cost.

```bash
python benchmarks/move1b_token_budget.py --dry-run
```

| Marks (N) | png | coords-full | index-compact | **analyzer-reduced** |
|---:|---:|---:|---:|---:|
| 4 | 806 | 265 | 218 | **275** |
| 48 | 1806 | 1408 | 835 | **276** |
| 320 | 1913 | 8554 | 4712 | **277** |

`coords-full` crosses the 8,000-token budget near N=320; `analyzer-reduced`
stays flat (~275) across an 80× density range.

Raw: [`results/move1b_token_scaling_dryrun.json`](results/move1b_token_scaling_dryrun.json)

### A3. Only structure-aware policies ground a history answer

Six perception policies compared over history-bearing tasks (most-recent mark,
cross-out, grouping, most-recent change). Ground truth is read exactly off the
document and event log; grounding is scored conservatively.

```bash
python benchmarks/move3_grounding.py --dry-run
```

| Arm | Grounded | Context chars | Raster pixels |
|---|---:|---:|---:|
| raster-only | **0.0** | 2,650 | 669,576 |
| raster+geometry | **0.0** | 3,107 | 669,576 |
| index-only | **0.0** | 2,649 | 0 |
| active-index | **1.0** | 5,217 | 0 |
| marked-index | **1.0** | 5,524 | 669,576 |
| **analyzer-first** | **1.0 (exact)** | 5,217 | **0** |

Pixels and a static map cannot recover a temporal/history/grouping signal;
analyzer-bearing policies can, and **analyzer-first grounds every task exactly
at zero pixels**. Adversarial controls confirm no answer leaks into the question
and the dataset stays balanced (`adversarial_leak_free: true`).

Raw: [`results/move3_grounding_dryrun_full.json`](results/move3_grounding_dryrun_full.json)

---

## Tier B — needs a live model (archived transcripts)

### B1. Raster-only confabulates; structure grounds

The same model, the same certified-identical pixels, three input conditions.
Run through GPT-5.5 at high reasoning effort via the Codex CLI (requires your
own login):

```bash
python benchmarks/move1_render_identical_pairs.py --agent codex
```

| Axis | png (image only) | png+struct | coords |
|---|---:|---:|---:|
| direction | **6/12 = 0.50** | 12/12 = 1.00 | 12/12 = 1.00 |
| order | **6/12 = 0.50** | 12/12 = 1.00 | 12/12 = 1.00 |

Raster-only sits at chance **and does not abstain** — on the direction task it
confabulated the *same* nonexistent visual cue ("a tapered, lighter endpoint")
in all 12/12 trials. The full per-trial responses, including every `why`, are
archived so you can read what the model actually said:

Raw transcript: [`results/move1_render_identical_gpt55_high.json`](results/move1_render_identical_gpt55_high.json)

### B2. Live grounding on real ink — accuracy, abstention, and cost per policy

Move 3's live arm: 60 tasks (four synthetic kinds plus six built from human
MathWriting ink with scripted, event-logged histories) × six perception arms,
gpt-5.6-luna at high reasoning effort through the Codex CLI. Answers are
JSON with an explicit abstention channel; a *false explanation* is a wrong,
non-abstained answer asserted with cited evidence. Adversarial controls
(question-leak, balance, label-contamination) are enforced at run time.

```bash
python benchmarks/move3_live.py --agent codex            # resumable ledger
python benchmarks/move3_gate.py --agent codex --model gpt-5.6-luna \
    --ledger benchmarks/results/move3_ledger_v2.jsonl    # exit-gate verdict
```

| Arm | Accuracy | Abstention | False expl. | Est. tokens | Pixels | Action target acc. |
|---|---:|---:|---:|---:|---:|---:|
| raster-only | 0.000 | 1.000 | 0.000 | 1,019 | 724,607 | 0/6 |
| raster+geometry | 0.296 | 0.667 | 0.037 | 1,019 | 724,607 | 1/6 |
| index-only | 0.667 | 0.222 | 0.111 | **717** | 0 | 5/6 |
| active-index | 0.741 | 0.130 | 0.130 | 1,317 | 0 | **6/6** |
| marked-index | **0.778** | 0.111 | 0.111 | 2,392 | 724,607 | **6/6** |
| analyzer-first | 0.722 | 0.130 | 0.148 | 1,351 | **0** | **6/6** |

What the live data establishes, beyond the dry run:

- **Structure dominates pixels on history tasks.** The best raster arm reaches
  0.296; every structured arm at least doubles it, and the pixel-free arms do
  it at zero raster cost. Given an abstention channel, raster-only abstains on
  **every** question (0 false explanations) — pixels have no stroke-id
  vocabulary, and the model knows it.
- **The static index outperforms its conservative dry-run model.** `ink-index/v1`
  marks carry creation order, so index-only grounds erased-rewrite and
  recent-change tasks the dry run scored as unreachable — at 717 tokens, the
  cheapest cell in the grid.
- **The model never retrieves.** 0 MCP perception calls across all 360 rows,
  with tool availability verified end-to-end. Bootstrap quality decides
  everything; step 4 of the architecture (query-aware retrieval) went unused
  by this model.
- **Wrong precomputed evidence is worse than none.** The three IAI-arm failure
  kinds are mechanistic SDK defects, not model failures: intent routing sends
  "changed most recently" to the wrong analyzer; the revisions reducer is
  geometry-only and buries the event-log-provable replacement below spurious
  bbox-overwrite candidates (index-only scores **1.0** on erased-rewrite while
  analyzer arms score 0.5–0.67 — evidence poisoning); and recorded groups
  surface in no arm's evidence at all (`mw_grouping` = 0.0 everywhere).
- **Exit gate: not passed.** IAI arms match-or-beat raster accuracy, but do
  not reduce priced context (a cropped ink page is only ~1k token-equivalents)
  and currently make *more* unsupported claims than all-abstaining raster arms.
  The gate verdict with per-clause numbers is archived below.

Raw: [`results/move3_ledger_v2.jsonl`](results/move3_ledger_v2.jsonl),
[`results/move3_gate_v2_luna.json`](results/move3_gate_v2_luna.json),
[`results/move3_v2_luna.json`](results/move3_v2_luna.json)

---

## What each result establishes

- **A1 + A2 + A3** are the load-bearing, credential-free claims: pixels lose
  history, structured reduction is cost-flat, and only structure grounds a
  history answer. Anyone can reproduce these in seconds.
- **B1** is the safety finding (confident confabulation) — it needs a model, so
  we publish the transcripts rather than ask you to take it on faith.
- **B2** is the live grounding study on real ink: structure beats pixels on
  accuracy and honesty, the M3 exit gate is *not yet met*, and the three
  failure modes are named, mechanistic analysis-plane defects — each with a
  ledger row you can read.

The full argument, methodology, and threats to validity are in the paper:
[`../paper/neeh-icf.pdf`](../paper/neeh-icf.pdf).
