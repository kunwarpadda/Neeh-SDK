# Security policy

## Reporting a vulnerability

Please report security issues privately using [GitHub Security
Advisories](../../security/advisories/new) for this repository rather than a
public issue. Include the affected version, a minimal reproduction, and the
impact you'd expect (crash, resource exhaustion, incorrect validation, etc.).

We aim to acknowledge reports within a few days and to publish a fix or
mitigation before any public disclosure.

## Trust model

Neeh is a library, not a hosted service. It enforces structural bounds on the
data it accepts (see below), but **the embedding application is the trust
boundary** for anything originating from an untrusted end user. Concretely:

- Neeh validates coordinate finiteness and magnitude, per-stroke point counts,
  tool-input text length, and renderable region/page area — see
  `neeh/ink/geometry.py`, `neeh/ink/stroke.py`, `neeh/canvas/canvas.py`, and
  `neeh/tools/core.py` for the specific limits.
- Neeh does **not** enforce a maximum file size when loading a document
  (`Document.load`, `neeh.adapters.uim.load_uim`) or a maximum request size on
  its own beyond the read-side transport it's given. An application that
  accepts document uploads, or exposes the `neeh.agents.iai_mcp` stdio server
  to a process it does not fully control, must enforce its own size limits and
  process isolation.
- The Codex/Claude assistant adapters (`neeh.agents.assistant`) shell out to
  the `codex`/`claude` CLIs using list-form `subprocess` calls (never
  `shell=True`); document and instruction content passed to them cannot be
  interpreted as extra shell flags or commands, but a compromised or
  misconfigured CLI binary (e.g. via `NEEH_CODEX_CLI_BIN`) is by definition
  outside Neeh's trust boundary — only point these at binaries you trust.
- Model-planned edit batches are dry-run validated on a document clone before
  being applied to the live canvas, with one bounded repair pass — but Neeh
  does not sandbox the CLI subprocess itself; that's the embedding
  application's responsibility if the planner's output should be treated as
  untrusted.

## Supported versions

Neeh is pre-alpha (`0.x`). Security fixes land on `main` and the latest
release; there is no long-term-support branch yet.
