# Neeh benchmarks — reproducible evidence

Every claim Neeh makes about digital ink as model context is backed by a
harness you can run. This page maps each **claim → command → expected numbers →
raw result**, split into two tiers of verifiability:

- **Tier A — reproducible by anyone.** Deterministic `--dry-run` harnesses.
  No API key, no model, no secrets. You clone the repo and get the exact
  numbers below. This is the credential-free core of the evidence.
- **Tier B — needs GPT-5.5.** Live model runs through the Codex/Claude CLIs.
  Not reproducible without your own credentials and quota, so we archive the
  **raw model outputs** here for inspection.

```bash
pip install -e ".[png]"          # Pillow, for the raster arms
python -m pytest benchmarks/ -q  # the harnesses' own ground-truth tests (17)
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

## Tier B — needs GPT-5.5 (archived transcripts)

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

---

## What each result establishes

- **A1 + A2 + A3** are the load-bearing, credential-free claims: pixels lose
  history, structured reduction is cost-flat, and only structure grounds a
  history answer. Anyone can reproduce these in seconds.
- **B1** is the safety finding (confident confabulation) — it needs a model, so
  we publish the transcripts rather than ask you to take it on faith.

The full argument, methodology, and threats to validity are in the paper:
[`../paper/neeh-icf.pdf`](../paper/neeh-icf.pdf).
