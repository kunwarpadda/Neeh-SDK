"""SDK-level coverage for the reusable agent orchestration surface."""

import json

from neeh import Canvas
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
        "add_stroke", "highlight", "write_text",
    }

    full = agent_input_preview(canvas, "Explain this", full=True)
    assert "User instruction: Explain this" in full["prompt"]
    assert {tool["name"] for tool in full["tool_schemas"]} == {
        "add_stroke", "highlight", "write_text",
    }


def test_mock_runner_uses_the_real_undoable_agent_tool_path():
    canvas = Canvas()
    canvas.add_stroke([[10, 10], [40, 40]], author=Author.USER)

    result = run_mock(canvas)

    assert [action["tool"] for action in result["actions"]] == ["highlight", "write_text"]
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
    assert seen[0][0] == "write_text"
    assert canvas.page.agent_layer().strokes


def test_codex_cli_reserved_user_font_is_rendered_as_print(monkeypatch):
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
    assert action["input"]["style"] == "print"
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
    assert seen[0][0] == "write_text"
    assert canvas.page.agent_layer().strokes
