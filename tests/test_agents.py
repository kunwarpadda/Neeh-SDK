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
    assert compact["perception_mode"] == "active-index"
    assert compact["perception_policy"] == "active-index"
    assert compact["context"]["schema"] == "ink-agent-interface/v1"
    assert compact["context"]["page_map"]["schema"] == "ink-index/v1"
    assert compact["image"]["attached"] is False
    assert compact["image"]["transport"] == "IAI view_region"
    assert compact["image"]["bytes"] == 0
    assert {tool["name"] for tool in compact["perception_tools"]} == {
        "find_marks", "analyze_ink", "find_ink_moments", "inspect_ink_moment",
        "view_region", "get_ink", "expand_relations",
    }
    assert "prompt" not in compact
    assert "tool_schemas" not in compact
    assert {tool["name"] for tool in compact["tools"]} == {
        "add_stroke", "annotate", "connect", "highlight", "insert_text", "mark",
        "move", "write_text",
    }

    full = agent_input_preview(canvas, "Explain this", full=True)
    assert "User instruction: Explain this" in full["prompt"]
    assert "Use at most 6 actions" in full["prompt"]
    # Behavioral guidance lives once in SYSTEM; the per-turn rules stay lean.
    assert "mark it up in place" in full["prompt"]  # from SYSTEM, not duplicated
    assert "handwritten style" in full["prompt"]
    assert full["prompt"].count("Make the SMALLEST edit") == 1  # no rules/SYSTEM dupe
    assert {tool["name"] for tool in full["tool_schemas"]} == {
        "add_stroke", "annotate", "connect", "highlight", "insert_text", "mark",
        "move", "write_text",
    }
    move = next(tool for tool in compact["tools"] if tool["name"] == "move")
    assert move["limits"] == {"dx": [-40.0, 40.0], "dy": [-40.0, 40.0]}
    assert compact["output_schema"].endswith("up to 6 Neeh tool actions")
    assert assistant._CODEX_CLI_RESPONSE_SCHEMA["properties"]["actions"]["maxItems"] == 6


def test_raster_perception_keeps_attached_image_context(monkeypatch):
    canvas = Canvas()
    monkeypatch.setattr(assistant, "PERCEPTION_MODE", "raster")

    preview = agent_input_preview(canvas)

    assert preview["perception_mode"] == "raster"
    assert preview["perception_policy"] == "raster-always"
    assert preview["context"]["schema"] == "ink-context/v1"
    assert preview["image"]["attached"] is True
    assert preview["image"]["transport"] == "codex exec --image"
    command = assistant._codex_cli_command(
        "codex",
        assistant.Path("/tmp"),
        assistant.Path("/tmp/schema.json"),
        assistant.Path("/tmp/output.json"),
        assistant.Path("/tmp/page.png"),
    )
    assert command[command.index("--image") + 1] == "/tmp/page.png"
    assert command[command.index("--model") + 1] == "gpt-5.5"
    effort_config = command[command.index("-c") + 1]
    assert effort_config == 'model_reasoning_effort="high"'


def test_codex_backend_cannot_be_overridden_to_gpt_5_6(monkeypatch):
    monkeypatch.setenv("NEEH_CODEX_CLI_MODEL", "gpt-5.6")

    command = assistant._codex_cli_command(
        "codex",
        assistant.Path("/tmp"),
        assistant.Path("/tmp/schema.json"),
        assistant.Path("/tmp/output.json"),
    )

    assert command[command.index("--model") + 1] == "gpt-5.5"
    assert "gpt-5.6" not in command


def test_unknown_perception_mode_is_rejected(monkeypatch):
    monkeypatch.setattr(assistant, "PERCEPTION_MODE", "unknown")
    try:
        assistant._perception(Canvas())
    except ValueError as exc:
        assert "choose index, raster" in str(exc)
    else:
        raise AssertionError("invalid perception mode was accepted")


def test_active_index_configures_typed_iai_for_codex(monkeypatch):
    canvas = Canvas()
    monkeypatch.setattr(assistant.shutil, "which", lambda _: "/tmp/codex")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["prompt"] = kwargs["input"]
        tmp = assistant.Path(command[command.index("-C") + 1])
        assert (tmp / "page-state.json").exists()
        assert not (tmp / "ink-context.json").exists()
        output_path = command[command.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as output:
            json.dump({"reply": "No edit needed.", "actions": []}, output)
        return assistant.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(assistant.subprocess, "run", fake_run)
    run_codex_cli(canvas)

    assert "--image" not in seen["command"]
    assert "--ignore-user-config" in seen["command"]
    assert seen["command"].count("--disable") == 2
    assert "shell_tool" in seen["command"]
    assert "unified_exec" in seen["command"]
    assert any("mcp_servers.neeh_iai.command" in part for part in seen["command"])
    assert "ink-agent-interface/v1" in seen["prompt"]
    assert "ink-index/v1" in seen["prompt"]
    assert "typed IAI perception actions" in seen["prompt"]
    assert "page.png" not in seen["prompt"]
    assert "ink-context.json" not in seen["prompt"]


def test_situation_note_conditions_on_what_is_on_the_page():
    from neeh.agents import assistant

    # A blank page names no situation.
    assert assistant._situation_note({"ink": {}}) == ""

    # A sketch with a targetable mark and a run of handwriting names both.
    canvas = Canvas()
    canvas.add_stroke([(60, 120), (300, 120), (300, 400), (60, 400), (60, 120)],
                      author=Author.USER)  # a box: a labelable mark
    for i in range(30):  # a line of handwriting
        x = 80 + i * 12
        canvas.add_stroke([(x, 600), (x + 6, 612), (x + 3, 624)], author=Author.USER)
    note = assistant._situation_note(assistant._perception(canvas))
    assert "target by id" in note and "on-demand detail" in note
    assert "(marks)" in note

    prompt = assistant._codex_cli_prompt(canvas, "help")
    assert note.strip() in prompt


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
    assert result["perception_mode"] == "active-index"
    assert result["perception_policy"] == "active-index"
    assert result["validation"] == {
        "passed": True, "repair_attempted": False, "failure_count": 0,
    }
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
        prompt = next(part for part in command if "Current perception payload:" in part)
        assert "ink-agent-interface/v1" in prompt
        assert "ink-index/v1" in prompt
        assert "ink-context.json" not in prompt
        assert "--mcp-config" in command
        assert "mcp__neeh_iai__find_marks" in command[command.index("--tools") + 1]
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
    assert result["perception_mode"] == "active-index"
    assert result["perception_policy"] == "active-index"
    assert result["actions"][0]["tool"] == "write_text"
    assert result["actions"][0]["input"]["style"] == "handwritten"
    assert result["actions"][0]["output"]["style"] == "handwritten"
    assert json.loads(result["raw_model_output"])["structured_output"]["reply"] == "Wrote a short answer."
    assert seen[0][0] == "write_text"
    assert canvas.page.agent_layer().strokes


def test_codex_validation_repairs_once_before_mutating_canvas(monkeypatch):
    canvas = Canvas()
    monkeypatch.setattr(assistant.shutil, "which", lambda _: "/tmp/codex")
    calls = 0

    def fake_run(command, **kwargs):
        nonlocal calls
        calls += 1
        output_path = command[command.index("--output-last-message") + 1]
        action = (
            {"tool": "move", "input": {"stroke_ids": ["st_missing"], "dx": 5, "dy": 0}}
            if calls == 1 else
            {"tool": "write_text", "input": {
                "text": "fixed", "region": [60, 80, 400, 160], "color": "#1d4ed8",
            }}
        )
        with open(output_path, "w", encoding="utf-8") as output:
            json.dump({"reply": "Repaired.", "actions": [action]}, output)
        return assistant.subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(assistant.subprocess, "run", fake_run)
    result = run_codex_cli(canvas)

    assert calls == 2
    assert result["validation"] == {
        "passed": True, "repair_attempted": True, "failure_count": 0,
    }
    assert [action["tool"] for action in result["actions"]] == ["write_text"]
    assert canvas.page.agent_layer().strokes
