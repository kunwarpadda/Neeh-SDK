# Research harness (M1 scope, M2-ready)

Implements [protocol-m0.md](../protocol-m0.md) §7: S0 synthetic corpus, encoding arms
E0 / E1a / E1b / E2 / E4 plus the M2 arms E3 (grid language) / E5 (structural scene
graph) / E6 (temporal raster) and a CTRL scaffolding baseline, task families T1–T6
(T5 executes model tool calls through `neeh-tools/v1` and scores them geometrically),
CLI model backends, append-only ledger, and summary/Pareto reporting. Imports `neeh`;
never shipped with it. E7/E7v (hybrid: raster + E2-quantized SVG paths) were composed
2026-07-10 from the first live results, per the protocol — see results/m1-findings.md.

## Run (from the repo root)

```bash
# validate the pipeline without a model (oracle answers, scores must be 1.0)
python -m research.harness.run_m1 --backend mock

# tiny live slice first: 1 text + 1 shape page, arms E0+E2 (+CTRL)
python -m research.harness.run_m1 --backend codex --smoke
python -m research.harness.run_m1 --backend claude --model claude-haiku-4-5-20251001 --smoke

# full M1 sweep per model (resumable; re-running skips completed cells)
# --workers parallelizes independent CLI calls; 4-6 is a good default
python -m research.harness.run_m1 --backend codex --workers 4
python -m research.harness.run_m1 --backend claude --model claude-haiku-4-5-20251001
python -m research.harness.run_m1 --backend claude --model claude-opus-4-8

# E7 hybrid arms, composed 2026-07-10 from M1 evidence (results/m1-findings.md)
python -m research.harness.run_m1 --backend codex --workers 4 --arms E7 E7v

# full matrix including M2 arms and all task families
python -m research.harness.run_m1 --backend codex --workers 4 \
  --arms E0 E1a E1b E2 E3 E4 E5 E6 E7 E7v --families T1 T2 T3 T4 T5 T6

# after a quota outage: re-run only the cells whose latest row failed
python -m research.harness.run_m1 --backend codex --retry-failed

# grid-resolution sweep (ICF v1 draft open question #3; M3 scope)
python -m research.harness.run_m1 --backend codex --workers 4 \
  --arms E7v128 E7v E7v512 --families T1 T2 T3 T4 T5 T6
```

## Next quota window — queued commands, in priority order

```bash
export NEEH_CODEX_HOME="$HOME/.neeh-codex-home"   # persistent harness-owned home

# 1. finish the M2 matrix (~345 cells incl. 5 failed retries)
python -m research.harness.run_m1 --backend codex --workers 4 --retry-failed \
  --arms E0 E1a E1b E2 E3 E4 E5 E6 E7 E7v --families T1 T2 T3 T4 T5 T6

# 2. S1 real ink, winners only (needs research/data/quickdraw/, already fetched)
python -m research.harness.run_m1 --backend codex --workers 4 --corpus s1 \
  --arms E0 E1a E2 E5 E7 E7v --families T1 T2 T3 T4 T5 T6

# 3. grid-resolution sweep (M3)
python -m research.harness.run_m1 --backend codex --workers 4 \
  --arms E7v128 E7v512 --families T1 T3 T4

python -m research.harness.run_m1 --report

# real ink (S1 Quick, Draw!): fetch category slices once, then sweep
python -m research.harness.fetch_quickdraw --categories cat house tree star
python -m research.harness.run_m1 --backend codex --corpus s1 \
  --arms E0 E1a E1b E2 E3 E4 E5 E6 --families T1 T2 T3 T4 T5 T6

# artifacts
python -m research.harness.run_m1 --report   # results/summary.md from the ledger
python -m research.harness.run_m1 --sizes    # results/context-sizes.md (offline, exact)
```

The ledger (`results/ledger.jsonl`) is the source of truth; delete a row's file only to
redo the whole sweep. Resume takes the *latest* row per key as authoritative; reports do
too. Mock runs write to `results/ledger-mock.jsonl` (gitignored scratch) — the mock is
for pipeline validation only and never shares the real ledger.

## Backend notes

- **codex**: uses your `codex` login via `codex exec --ephemeral`. If your global
  `~/.codex/config.toml` is newer than the installed CLI understands, set
  `NEEH_CODEX_HOME` to a directory containing a copied `auth.json` and a minimal valid
  `config.toml`; the harness passes it through as `CODEX_HOME`.
- **claude**: uses your `claude` login via `claude -p` with stream-json in/out (images
  ride as content blocks; no tool round-trips). Runs with `--strict-mcp-config`,
  `--disallowedTools '*'`, `--max-turns 1` from a temp cwd so no project context leaks
  into the experiment.
- Both backends retry twice with backoff; failures land in the ledger with the error
  string and count toward the failure rate, never silently dropped.
