# Phase 0 Assistant Demo

This example is a thin HTTP/UI shell around `neeh.agents`: a page of ink is rendered for a model,
paired with vector stroke context, and the model writes back onto the page through Neeh tools.
Applications can reuse the model loop directly without importing this demo server.

## Run

```bash
pip install -e ".[agents]"
python examples/assistant/server.py --port 8787 --agent codex
```

Open `http://127.0.0.1:8787`, draw a small handwritten prompt, and press Ask.
Press Inspect to see the PNG transport details, compact Ink Context payload, concise action tool
contract, prompt preview, and payload sizes that will be sent to Codex CLI. Press Raw when you
need the exact full prompt and full tool schemas.

The page context defaults to **Ink Context Format v1** (compact SVG
geometry — far fewer prompt characters; see `../../spec/ink-context-format-v1.md`), with
an explicit grid→page coordinate note so tool calls stay in page units. Pass
`--context v0` for the original Phase 0 payload; press Inspect to see either
live.

`--agent codex` uses the local Codex CLI login. Other modes:

- `--agent claude`: Claude CLI.
- `--agent mock`: no external model.
- `--agent auto`: Codex CLI, Claude CLI, then mock fallback.

## Use from Python

```python
from neeh import Canvas
from neeh.agents import agent_input_preview, run_codex_cli

canvas = Canvas()
print(agent_input_preview(canvas))
result = run_codex_cli(canvas, "Answer the question on the page")
```

## What This Proves

- Raster perception: the model receives a PNG of the page.
- Vector context: the model receives compact Ink Context Format v1 SVG paths with stable stroke
  ids; pull mode can request detailed geometry only for a relevant region.
- Tool action: model output is converted into bounded `insert_text`, `mark`, `move`, `write_text`,
  `highlight`, or `add_stroke` calls.
- Safety invariant: agent output lands as agent-authored ink and remains undoable.

## Recording Checklist

Record one short clip that shows:

1. Start the server with `--agent codex`.
2. Draw a handwritten prompt such as `x = 2`, `x^3 =`, and circle the target expression.
3. Press Ask.
4. Show the status bar reporting `[codex-cli:default-profile]` or `[claude-cli:default-profile]`.
5. Show the blue agent answer written on the page.

The clip is the Phase 0 artifact. Keep it raw and short; the point is to prove the loop, not make
a polished product video yet.

## Known Limits

- Codex CLI currently plans actions in one shot; it does not run a multi-turn tool loop.
- The semantic layer is still empty. Recognition, scene graphs, anchors, and search belong in
  later specs/plugins.
- Free-form placement remains model-driven; `insert_text` handles bounded same-line reflow for
  corrections relative to existing stroke IDs.
