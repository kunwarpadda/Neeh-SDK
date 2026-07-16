# Reviewer start

Neeh is a pre-alpha structured digital-ink SDK. Its core idea is simple: keep
the stroke history that a stylus captures, then give applications and agents a
bounded way to inspect and edit that structure instead of treating a screenshot
as the source of truth.

## Understand it in five minutes

1. Read the root README's [problem statement](../README.md#why-not-ocr-a-canvas-api-or-an-image-pipeline)
   and [evidence summary](../README.md#evidence).
2. Scan the [technical case study](CASE_STUDY.md) for the decisions, measured
   results, and failures that changed the design.
3. Open the [benchmark index](../benchmarks/README.md) to trace each headline
   claim to a command and checked-in raw output.

The shortest accurate description is: **Neeh preserves ordered, timestamped,
addressable ink and exposes deterministic analysis plus bounded agent tools over
it.** It does not attempt to replace OCR, and it does not claim that its current
pre-alpha agent protocols have passed every release gate.

## Run the smallest proof

The Python core has no runtime dependencies:

```bash
python -m pip install -e .
python examples/quickstart.py
```

That path creates user ink, selects and moves it, undoes the edit, applies
agent-authored operations through the public tool surface, and writes a
snapshot and SVG under `build/quickstart/`.

The two credential-free benchmark commands behind the main scaling and
grounding claims are:

```bash
python benchmarks/move1b_token_budget.py --dry-run
python benchmarks/move3_grounding.py --dry-run \
  --kinds latest_mark crossed_out grouping recent_change
```

Their expected results and raw JSON outputs are indexed in
[`benchmarks/README.md`](../benchmarks/README.md). These dry runs do not call a
model.

## Try the assistant

For a fully local inspection path, including the deterministic analyzer:

```bash
python -m pip install -e ".[agents]"
python examples/assistant/server.py --agent mock --perception active-index
```

Open <http://127.0.0.1:8787>. Draw or load one of the three deterministic
scenarios, select **Analyze** to run `ink-analysis/v1`, and open **Inspect** to
see the exact bounded context and tool contract. Mock mode is useful for UI and
tool-flow inspection; it is not evidence of model quality.

To exercise a real model with an existing local login, replace `mock` with
`codex` or `claude`. Explicit modes surface backend failures instead of silently
falling back.

## Record the demo

No hero GIF or video is currently checked in. This is the exact 60--90 second
recording path to produce one without staging a result:

1. Start the server with `--agent codex --perception active-index`; add `--lan`
   if the stylus device and computer are on the same trusted Wi-Fi network.
2. Begin on a blank page. Write one short sentence or math expression with the
   stylus so the footage shows real input rather than a canned fixture.
3. Open **Inspect** briefly and show that the payload contains stable stroke ids,
   structure, and bounded perception tools.
4. Ask a mechanical question such as "Which mark was drawn last?" and select
   **Analyze** to show the deterministic evidence before any model response.
5. Ask the agent for one small visible annotation. Keep the response and the
   resulting blue agent ink in the same shot.
6. Select **Undo** once to show that the agent edit participates in normal
   document history.
7. End on the rendered page and a one-line caption linking to
   [`benchmarks/README.md`](../benchmarks/README.md), where the claims are
   independently reproducible.

If a live model is unavailable during capture, use the `latest`, `direction`,
or `crossout` scenario and **Analyze** only. Label the footage as a deterministic
SDK walkthrough, not a live-model demo.

## What to inspect next

| Interest | Source |
|---|---|
| System boundaries and trade-offs | [ARCHITECTURE.md](../ARCHITECTURE.md) and [ADRs](adr/README.md) |
| Public Python API | [API reference](API.md) |
| Native integration | [`cpp/include/neeh/c_api.h`](../cpp/include/neeh/c_api.h) and the root README's native quickstart |
| Model context and actions | [`ink-context/v1`](../spec/ink-context-format-v1.md), [`ink-agent-interface/v1`](../spec/ink-agent-interface-v1.md), and [`neeh-tools/v1`](../spec/tool-surface-v1.md) |
| Current gaps | [ROADMAP.md](../ROADMAP.md) and the [benchmark limitations](../benchmarks/README.md) |
| Authorship | [AUTHORS](../AUTHORS), [CITATION.cff](../CITATION.cff), and the dated [ADRs](adr/README.md) |
