# Ink assistant example

This example provides a local drawing page backed by the reusable model adapters in
`neeh.agents`. It renders the current page, builds an Ink Context Format payload, asks a local
model to plan bounded Neeh tool calls, and applies successful actions as undoable agent ink.

## Run

From the repository root:

```bash
python -m pip install -e ".[agents]"
python examples/assistant/server.py --agent codex --perception active-index
```

Open <http://127.0.0.1:8787>, draw on the page, and press **Ask**.

Available backends:

- `--agent codex`: use the local Codex CLI login.
- `--agent claude`: use the local Claude CLI login.
- `--agent mock`: run without an external model.
- `--agent auto`: try Codex CLI, then Claude CLI, then the mock fallback.

The default perception is `--perception active-index`: the model receives a budgeted IAI page map,
then can call typed `analyze_ink`, `find_marks`, `view_region`, `get_ink`, and `expand_relations` actions when it
needs handwriting, visual detail, relations, or omitted stroke IDs. `index` and `raster` remain
compatibility aliases for `active-index` and `raster-always`. The evaluation policies are:

Active policies also expose Ink Moment Retrieval through `find_ink_moments` and
`inspect_ink_moment`. These tools retrieve creation order, direction, pauses,
pressure summaries, overlays, and bounded replay evidence without dumping the
complete point stream.

`analyze_ink` is preferred for mechanical questions. It deterministically
reduces latest-mark, creation-order, stroke-dynamics, and cross-out queries to
bounded evidence before the model sees them.

- `raster-only`: attached pixels with no geometry or temporal evidence (clean control).
- `raster-always`: attached raster plus compact geometry (legacy control).
- `index-only`: strict structured-map ablation with no perception fallback.
- `active-index`: map first, typed perception on demand (production candidate).
- `marked-index`: active index plus an ASCII Set-of-Marks bootstrap view.

Set `NEEH_PERCEPTION_MODE` when using the adapter outside this demo. In raster mode the default
context is `ink-context/v1`; use `--context pull` to keep geometry in the on-demand detail file, or
`--context v0` for compatibility testing.

Run the policy harness without model calls using:

```bash
python examples/evaluate_perception_policies.py --dry-run
```

Remove `--dry-run` to execute the P0-P4 grounding cases through Codex CLI, or pass
`--agent claude` for Claude CLI.

The first controlled direction smoke result is checked in at
`examples/results/ink_moment_direction_ab_gpt55_high.json`: the two samples
have identical PNG bytes, raster-only answered `right` twice (1/2), and the
temporal active index answered `right` then `left` (2/2). Treat this as harness
validation, not a statistical accuracy claim.

Codex-backed assistant and evaluation runs are intentionally pinned to
`gpt-5.5` with `model_reasoning_effort="high"`. The adapter ignores user model
configuration and does not accept an environment override to GPT-5.6.

## Inspect model input

The **Inspect** view shows the selected perception mode, raster transport, compact context,
action-tool contract, prompt preview, and payload sizes. **Raw** shows the complete prompt and tool
schemas. The same data is available from `GET /agent-input`; add `?full=1` for the raw
representation.

## Use the adapter directly

```python
from neeh import Canvas
from neeh.agents import agent_input_preview, run_codex_cli

canvas = Canvas()
print(agent_input_preview(canvas))
result = run_codex_cli(canvas, "Answer the question on the page")
```

Planned actions are restricted to a small allowlist and bounded action count. Relative
corrections use stroke IDs through `insert_text` and `mark`; arrows that reference existing ink use
stroke IDs through `connect`; and captioned pointers use `annotate`, which writes a note beside a
target and binds an arrow to it in one step so labels stay paired with their targets. The model
picks targets from `ink.hints`, which labels each stroke by shape and position. Explicit `move`
calls are limited to small offsets. Blue agent text uses the cursive Hershey Script Complex face so it remains visually
distinct from regular print. Agent-created strokes are stored on the agent layer and remain
undoable.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/` | Drawing interface |
| `GET` | `/page.svg` | Current page render |
| `GET` | `/agent-input` | Model-input preview |
| `POST` | `/stroke` | Add user ink |
| `POST` | `/ask` | Run one assistant turn |
| `POST` | `/undo` | Undo the latest edit |
| `POST` | `/clear` | Reset the canvas |

The server binds to `127.0.0.1` and is intended for local development, not production hosting.
