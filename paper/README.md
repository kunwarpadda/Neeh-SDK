# Neeh research paper

**Structure Before Pixels: Deterministic Analysis and Bounded Retrieval over
Digital Ink as Model Context** — Kunwarbir Singh Padda, July 2026.

A standalone research paper written from the Neeh SDK's specs, ADR log, and
controlled experiments. It is separate from the SDK's normative documentation:
`spec/` holds the wire formats, `docs/adr/` the dated decisions, and this paper
the synthesized argument and results.

## Contents

- `neeh-icf.tex` — LaTeX source (single file, manual bibliography).
- `neeh-icf.pdf` — compiled paper (14 pages, US Letter).

## Build

```bash
tectonic neeh-icf.tex     # self-contained; downloads packages on first run
```

Any TeX toolchain works; `pdflatex neeh-icf.tex` (run twice for cross-references)
produces the same output.

## What it reports

- **Experiment 1 (render-identical pairs):** pixel-identical ink twins that
  differ only in hidden history drive a raster-only model to chance (0.50) and
  make it *confabulate*, while structured/coordinate context recovers the answer
  perfectly (1.00). Raw data: `research/tmp/move1_sweep.json`.
- **Experiment 2 (token-budget scaling):** accuracy never degrades with ink
  density (perfect through 320 marks), but serialized ink grows linearly and
  crosses budget, whereas a deterministic reducer stays ≈constant (~270 tokens).
  Raw data: `research/tmp/move1b.json`.
- **Supporting measurements** from the ADR log, and the SDK's test validation
  (243 Python tests + 2 native suites, all passing).

Experiments were run through GPT-5.5 at high reasoning effort via a CLI login;
the harnesses are `research/move1_render_identical_pairs.py` and
`research/move1b_token_budget.py` (both support `--dry-run` for a model-free
reproduction of the token curves and pixel-identity certification).
