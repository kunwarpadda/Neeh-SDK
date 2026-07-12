"""SDK-level coverage for the reusable agent orchestration surface."""

import json

from neeh import Canvas
from neeh.agents import assistant
from neeh.agents import agent_input_preview, run_claude, run_codex_cli, run_mock
from neeh.ink import Author


def test_agent_input_preview_exposes_compact_and_auditable_views():
    canvas = Canvas()

    compact = agent_input_preview(canvas)
    assert compact["mode"] == "codex-cli"
    assert compact["context"]["schema"] == "ink-context/v1"
    assert "prompt" not in compact
    assert "tool_schemas" not in compact
    assert {tool["name"] for tool in compact["tools"]} == {
        "add_stroke", "annotate", "connect", "highlight", "insert_text", "mark",
        "move", "write_text",
    }

    full = agent_input_preview(canvas, "Explain this", full=True)
    assert "User instruction: Explain this" in full["prompt"]
    assert "Use at most 6 actions" in full["prompt"]
    assert "NEVER use write_text to reproduce" in full["prompt"]
    assert 'uses the "handwritten" style' in full["prompt"]
    assert {tool["name"] for tool in full["tool_schemas"]} == {
        "add_stroke", "annotate", "connect", "highlight", "insert_text", "mark",
        "move", "write_text",
    }
    move = next(tool for tool in compact["tools"] if tool["name"] == "move")
    assert move["limits"] == {"dx": [-40.0, 40.0], "dy": [-40.0, 40.0]}
    assert compact["output_schema"].endswith("up to 6 Neeh tool actions")
    assert assistant._CODEX_CLI_RESPONSE_SCHEMA["properties"]["actions"]["maxItems"] == 6


def test_planned_move_opens_room_before_insert_text_and_preserves_anchor_ids():
    from neeh.agents import assistant

    canvas = Canvas()
    anchor = canvas.add_stroke([[200, 300], [320, 340]], author=Author.USER)
    actions = assistant._apply_planned_actions(canvas, [
        {"tool": "move", "input": {
            "stroke_ids": [anchor.id], "dx": 20, "dy": 0,
        }},
        {"tool": "insert_text", "input": {
            "text": '"', "stroke_ids": [anchor.id], "position": "before",
            "color": "#1d4ed8",
        }},
    ], None)

    assert all("error" not in action for action in actions)
    _, moved = canvas.page.find(anchor.id)
    assert moved.bbox.min_x == 220
    assert actions[1]["output"]["anchor_bbox"][0] == 220
    assert actions[1]["output"]["region"][2] < 220


def test_planned_move_requires_ids_and_rejects_large_offsets():
    from neeh.agents import assistant

    canvas = Canvas()
    anchor = canvas.add_stroke([[200, 300], [320, 340]], author=Author.USER)
    actions = assistant._apply_planned_actions(canvas, [
        {"tool": "move", "input": {"stroke_ids": [anchor.id], "dx": 41, "dy": 0}},
        {"tool": "move", "input": {"stroke_ids": None, "dx": 5, "dy": 0}},
    ], None)

    assert all("error" in action for action in actions)
    _, unchanged = canvas.page.find(anchor.id)
    assert unchanged.bbox.min_x == 200


def test_mock_runner_uses_the_real_undoable_agent_tool_path():
    canvas = Canvas()
    canvas.add_stroke([[10, 10], [40, 40]], author=Author.USER)

    result = run_mock(canvas)

    assert [action["tool"] for action in result["actions"]] == ["highlight", "write_text"]
    assert result["actions"][1]["input"]["style"] == "handwritten"
    assert all(stroke.author == Author.AGENT for stroke in canvas.page.agent_layer().strokes)
    assert canvas.undo() == "add_strokes"


def test_codex_cli_runner_applies_valid_planned_actions(monkeypatch):
    from neeh.agents import assistant

    canvas = Canvas()
    monkeypatch.setattr(assistant.shutil, "which", lambda _: "/tmp/codex")

    def fake_run(command, **kwargs):
        output_path = command[command.index("--output-last-message") + 1]
        payload = {
            "reply": "Wrote a short answer.",
            "actions": [{
                "tool": "write_text",
                "input": {
                    "points": None,
                    "region": [60, 80, 500, 180],
                    "text": "42",
                    "color": "#1d4ed8",
                    "width": None,
                    "brush": None,
                    "style": "print",
                    "size": 32,
                },
            }],
        }
        with open(output_path, "w", encoding="utf-8") as output:
            json.dump(payload, output)
        return assistant.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(assistant.subprocess, "run", fake_run)
    seen = []
    result = run_codex_cli(canvas, on_action=lambda name, args: seen.append((name, args)))

    assert result["reply"] == "Wrote a short answer."
    assert result["actions"][0]["tool"] == "write_text"
    assert result["actions"][0]["output"]["stroke_ids"]
    assert result["actions"][0]["input"]["style"] == "handwritten"
    assert result["actions"][0]["output"]["style"] == "handwritten"
    assert json.loads(result["raw_model_output"])["reply"] == "Wrote a short answer."
    assert seen[0][0] == "write_text"
    assert canvas.page.agent_layer().strokes


def test_codex_cli_reserved_user_font_is_rendered_as_agent_hand(monkeypatch):
    from neeh.agents import assistant

    canvas = Canvas()
    monkeypatch.setattr(assistant.shutil, "which", lambda _: "/tmp/codex")

    def fake_run(command, **kwargs):
        output_path = command[command.index("--output-last-message") + 1]
        payload = {
            "reply": "I wrote 8 in the answer space.",
            "actions": [{
                "tool": "write_text",
                "input": {
                    "points": None,
                    "region": [120, 420, 500, 500],
                    "text": "x³ = 2³ = 8",
                    "color": "#1d4ed8",
                    "width": None,
                    "brush": None,
                    "style": "user_font",
                    "size": 34,
                },
            }],
        }
        with open(output_path, "w", encoding="utf-8") as output:
            json.dump(payload, output)
        return assistant.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(assistant.subprocess, "run", fake_run)
    result = run_codex_cli(canvas)

    action = result["actions"][0]
    assert action["input"]["style"] == "handwritten"
    assert action["output"]["style"] == "handwritten"
    assert action["output"]["stroke_ids"]
    assert canvas.page.agent_layer().strokes


def test_claude_cli_runner_applies_valid_planned_actions(monkeypatch):
    from neeh.agents import assistant

    canvas = Canvas()
    monkeypatch.setattr(assistant.shutil, "which", lambda _: "/tmp/claude")

    def fake_run(command, **kwargs):
        output = {
            "structured_output": {
                "reply": "Wrote a short answer.",
                "actions": [{
                    "tool": "write_text",
                    "input": {
                        "points": None,
                        "region": [60, 80, 500, 180],
                        "text": "42",
                        "color": "#1d4ed8",
                        "width": None,
                        "brush": None,
                        "style": "print",
                        "size": 32,
                    },
                }],
            }
        }
        return assistant.subprocess.CompletedProcess(command, 0, json.dumps(output), "")

    monkeypatch.setattr(assistant.subprocess, "run", fake_run)
    seen = []
    result = run_claude(canvas, on_action=lambda name, args: seen.append((name, args)))

    assert result["reply"] == "Wrote a short answer."
    assert result["actions"][0]["tool"] == "write_text"
    assert result["actions"][0]["input"]["style"] == "handwritten"
    assert result["actions"][0]["output"]["style"] == "handwritten"
    assert json.loads(result["raw_model_output"])["structured_output"]["reply"] == "Wrote a short answer."
    assert seen[0][0] == "write_text"
    assert canvas.page.agent_layer().strokes
