# Phase 0 Assistant Demo

This is the Phase 0 "magic loop" spike from `NEEH_SDK_PLAN.md`: a page of ink is rendered for a
model, paired with vector stroke context, and the model writes back onto the page through Neeh
tools.

## Run

```bash
pip install -e ".[agents]"
python examples/assistant/server.py --port 8787 --agent codex
```

Open `http://127.0.0.1:8787`, draw a small handwritten prompt, and press Ask.
Press Inspect to see the PNG transport details, compact Ink Context payload, concise action tool
contract, prompt preview, and payload sizes that will be sent to Codex CLI. Press Raw when you
need the exact full prompt and full tool schemas.

`--agent codex` uses the local Codex CLI login. Other modes:

- `--agent codex-api`: OpenAI Responses API with `OPENAI_API_KEY`.
- `--agent claude`: Claude API.
- `--agent mock`: no external model.
- `--agent auto`: Codex CLI, Codex API, Claude, then mock fallback.

## What This Proves

- Raster perception: the model receives a PNG of the page.
- Vector context: the model also receives compact Ink Context Format v0 with stroke ids, boxes,
  sampled points, timestamps, layer names, and user/agent authorship.
- Tool action: model output is converted into `write_text`, `highlight`, or `add_stroke` calls.
- Safety invariant: agent output lands as agent-authored ink and remains undoable.

## Recording Checklist

Record one short clip that shows:

1. Start the server with `--agent codex`.
2. Draw a handwritten prompt such as `x = 2`, `x^3 =`, and circle the target expression.
3. Press Ask.
4. Show the status bar reporting `[codex-cli:default-profile]`.
5. Show the blue agent answer written on the page.

The clip is the Phase 0 artifact. Keep it raw and short; the point is to prove the loop, not make
a polished product video yet.

## Known Limits

- Codex CLI currently plans actions in one shot; it does not run a multi-turn tool loop.
- The semantic layer is still empty. Recognition, scene graphs, anchors, and search belong in
  later specs/plugins.
- Placement is model-driven. There is no collision-avoidance pass yet.
