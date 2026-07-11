# Ink assistant example

This example provides a local drawing page backed by the reusable model adapters in
`neeh.agents`. It renders the current page, builds an Ink Context Format payload, asks a local
model to plan bounded Neeh tool calls, and applies successful actions as undoable agent ink.

## Run

From the repository root:

```bash
python -m pip install -e ".[agents]"
python examples/assistant/server.py --agent codex
```

Open <http://127.0.0.1:8787>, draw on the page, and press **Ask**.

Available backends:

- `--agent codex`: use the local Codex CLI login.
- `--agent claude`: use the local Claude CLI login.
- `--agent mock`: run without an external model.
- `--agent auto`: try Codex CLI, then Claude CLI, then the mock fallback.

The default context is `ink-context/v1`. Use `--context pull` to send a bounding-box index and
fetch detailed vector geometry by region, or `--context v0` for compatibility testing.

## Inspect model input

The **Inspect** view shows the raster metadata, compact ink context, action-tool contract, prompt
preview, and payload sizes. **Raw** shows the complete prompt and tool schemas. The same data is
available from `GET /agent-input`; add `?full=1` for the raw representation.

## Use the adapter directly

```python
from neeh import Canvas
from neeh.agents import agent_input_preview, run_codex_cli

canvas = Canvas()
print(agent_input_preview(canvas))
result = run_codex_cli(canvas, "Answer the question on the page")
```

Planned actions are restricted to a small allowlist and bounded action count. Relative
corrections use stroke IDs through `insert_text` and `mark`; explicit `move` calls are limited to
small offsets. Agent-created strokes are stored on the agent layer and remain undoable.

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
