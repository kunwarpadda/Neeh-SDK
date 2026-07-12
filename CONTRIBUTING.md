# Contributing to Neeh

Neeh is pre-alpha. APIs and protocol identifiers are versioned but may still
change before a first stable release — see [ROADMAP.md](ROADMAP.md) for the
current milestones and what's explicitly not planned.

## Development setup

```bash
python -m pip install -e ".[dev]"
```

`[dev]` pulls in `pytest`, the optional PNG (`Pillow`) and UIM
(`universal-ink-library`) extras, so the full test suite runs.

## Running tests

```bash
python -m pytest -q
```

Tests are pure and fast (no network, no model calls) — the full suite runs in
well under a second. If you're touching the Codex/Claude assistant adapters,
those are exercised through a mock backend (`run_mock`) in tests; nothing in
`pytest -q` shells out to a real CLI or spends model credits.

For the native core:

```bash
cmake -S . -B build -DNEEH_BUILD_TESTS=ON
cmake --build build --config Release
ctest --test-dir build --build-config Release --output-on-failure
```

CI runs Python 3.10 and 3.12, builds the native core on Linux and macOS, and
verifies the installed CMake package — see
[`.github/workflows/ci.yml`](.github/workflows/ci.yml).

## Coding conventions

- Match the existing style: small, focused functions; module/class docstrings
  that explain *why* a design choice was made, not *what* the code does line
  by line; comments only where the reason for something is genuinely
  non-obvious (a workaround, an invariant, a subtle constraint) — well-named
  code should not need a comment restating it.
- New validation on ink/document input should raise `ValueError` (or a
  documented `ValueError` subclass, like `UimImportError`) with a message
  that names the offending field and the limit — see
  `neeh/ink/geometry.py`, `neeh/ink/stroke.py`, and `neeh/tools/core.py` for
  the established pattern.
- If you're adding a bound/limit for hardening purposes (size caps, coordinate
  ranges, etc.), add an adversarial test alongside it that asserts the guard
  fires cleanly — not a test that actually performs the expensive operation
  the guard prevents (no multi-GB allocations in CI). See `tests/test_canvas.py::TestCoordinateBounds`
  and `tests/test_tools.py::test_view_region_rejects_oversized_render_area`
  for examples.
- Protocol specs live in `spec/` as versioned, normative documents (`MUST`,
  `SHOULD`, `MAY` per RFC 2119). If you change the wire shape of
  `ink-context`, `ink-agent-interface`, `ink-analysis`, `ink-timeline`, or
  `neeh-tools`, update the corresponding spec in the same PR.

## Commit messages

This repo follows `type(scope): imperative summary`, for example:

```
feat(tools): add connect — anchored arrows that point at ink by stroke id
fix(agents): drop the dead view_page/undo self-check from the planner prompt
perf(context): scope ink.hints to targets and trim semantics to links
```

Common types: `feat`, `fix`, `perf`, `docs`, `chore`. Keep the summary line
under ~70 characters; use the body for the *why* if it isn't obvious from the
diff.

## Pull requests

- Keep PRs scoped to one change; large refactors are easier to review split up.
- Run `pytest -q` (and `ctest` if you touched native code) before opening.
- If you're changing behavior an application might depend on, call it out in
  the PR description — this SDK is consumed by real assistant integrations.
- Security-relevant reports should go through [SECURITY.md](SECURITY.md)
  instead of a public PR/issue.
