# Releasing Neeh

This document defines the versioning contract, deprecation policy, and the
gate checklist a release must pass. It exists so a release is a mechanical
act, not a judgment call.

## Versioning contract

Two independent clocks:

1. **Protocol identifiers are the stability contract.** `ink-context/v1`,
   `neeh-tools/v1`, `neeh-uim/v1`, and friends are versioned independently of
   the package. Applications must negotiate them at runtime
   (`neeh.protocol.protocol_versions()`); any breaking wire-format change
   requires a protocol identifier bump regardless of package version.
2. **The package follows SemVer, pre-1.0 rules.** While `0.x`, minor versions
   may break Python/native APIs; patch versions may not. From `1.0`, standard
   SemVer applies. The runtime version is read from installed metadata
   (`neeh.__version__` tracks `pyproject.toml` automatically — v0.2.0 shipped
   with a stale hardcode; the packaging test now pins this).

### Experimental protocols

Protocols listed by `neeh.protocol.experimental_protocol_versions()`
(`ink-analysis/v1`, `ink-eventlog/v1`, `ink-timeline/v1`,
`ink-agent-interface/v1`, `neeh-session/v1`) have JSON Schema fixtures under
`spec/fixtures/` but may still change without a major bump. **Graduation
rule:** an experimental protocol moves to the stable manifest once its
fixtures have survived one full release unchanged. Consumers of experimental
protocols must feature-detect and tolerate unknown fields (the fixtures'
documented compatibility policy).

## Deprecation policy

- Pre-1.0: a deprecated Python/native API is marked in its docstring and
  release notes for at least one minor version before removal.
- Wire formats are never silently reinterpreted. Old identifiers are either
  supported, or explicitly rejected with an actionable error (the
  `ink-context/v1-draft` precedent).
- Behavioral changes to analyzers/reducers that alter *answers* (not just
  performance) require a protocol note in the release even if the schema is
  unchanged — downstream evaluations depend on answer stability.

## Release gates (all must pass)

From a clean checkout:

```bash
python -m pip install -e ".[dev,uim,png]"
python -m pytest -q                      # full Python suite
python -m pytest benchmarks/ -q          # benchmark harness ground truth
cmake -S . -B build -DNEEH_BUILD_TESTS=ON && cmake --build build --parallel
ctest --test-dir build --output-on-failure   # native C++/C ABI suites
```

Artifact gates (what CI cannot see from an editable install):

```bash
python -m build                                        # sdist + wheel
python -m venv /tmp/relvenv && /tmp/relvenv/bin/pip install dist/*.whl
cd /tmp && /tmp/relvenv/bin/python -c "import neeh, neeh.agents"   # bare, no extras
/tmp/relvenv/bin/pip install 'dist/*.whl[png,dev]' && run suite against it
```

- The bare install (no Pillow) must import every public package.
- `neeh.__version__` must equal the wheel version.
- `python benchmarks/perf.py` — no operation on the 1000-stroke page may
  regress an order of magnitude against the previous release's numbers.
- Docs updated: README evidence numbers, ROADMAP shipped list, this file if
  any gate changed.

## Mechanics

- One release commit per version on `main`: `chore(release): vX.Y.Z`,
  bumping `pyproject.toml` (and `CITATION.cff` version/date).
- Annotated git tag `vX.Y.Z` on that commit.
- GitHub Release on the tag stating the substance of what shipped, with the
  paper PDF attached when it changed.
- Protocol graduation (experimental → stable) happens in the release commit,
  never between releases.
