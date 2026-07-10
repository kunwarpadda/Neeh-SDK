# Research harness (M1 scope, M2-ready)

Implements [protocol-m0.md](../protocol-m0.md) §7: S0 synthetic corpus, encoding arms
E0 / E1a / E1b / E2 / E4 plus the M2 arms E3 (grid language) / E5 (structural scene
graph) / E6 (temporal raster) and a CTRL scaffolding baseline, task families T1–T6
(T5 executes model tool calls through `neeh-tools/v1` and scores them geometrically),
CLI model backends, append-only ledger, and summary/Pareto reporting. Imports `neeh`;
never shipped with it. E7 (hybrid) is composed only after first live results, per the
protocol.

## Run (from the repo root)

```bash
# validate the pipeline without a model (oracle answers, scores must be 1.0)
python -m research.harness.run_m1 --backend mock

# tiny live slice first: 1 text + 1 shape page, arms E0+E2 (+CTRL)
python -m research.harness.run_m1 --backend codex --smoke
python -m research.harness.run_m1 --backend claude --model claude-haiku-4-5-20251001 --smoke

# full M1 sweep per model (resumable; re-running skips completed cells)
python -m research.harness.run_m1 --backend codex
python -m research.harness.run_m1 --backend claude --model claude-haiku-4-5-20251001
python -m research.harness.run_m1 --backend claude --model claude-opus-4-8

# full matrix including M2 arms and all task families
python -m research.harness.run_m1 --backend codex \
  --arms E0 E1a E1b E2 E3 E4 E5 E6 --families T1 T2 T3 T4 T5 T6

# artifacts
python -m research.harness.run_m1 --report   # results/summary.md from the ledger
python -m research.harness.run_m1 --sizes    # results/context-sizes.md (offline, exact)
```

The ledger (`results/ledger.jsonl`) is the source of truth; delete a row's file only to
redo the whole sweep. Mock rows should never share a ledger with real rows — the mock is
for pipeline validation only.

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
