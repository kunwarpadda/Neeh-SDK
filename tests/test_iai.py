"""Ink Agent Interface workspace, retrieval, and MCP adapter coverage."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from neeh import Canvas
from neeh.agents import InkAgentInterface, PerceptionBudget, build_observation_workspace
from neeh.ink import Author


def _scene() -> tuple[Canvas, str]:
    canvas = Canvas()
    loop = canvas.add_stroke(
        [(40, 40), (180, 40), (180, 180), (40, 180), (40, 40)],
        author=Author.USER,
    )
    for i in range(12):
        x = 300 + i * 12
        canvas.add_stroke([(x, 400), (x + 6, 414), (x + 2, 426)], author=Author.USER)
    return canvas, loop.id


def test_intent_routing_selects_the_matching_reducer():
    canvas, _ = _scene()

    cases = {
        "what is the most recent mark?": ("operation", "latest_mark"),
        "was anything crossed out?": ("operation", "cross_out_candidates"),
        "what did I revise on this page?": ("task", "revisions"),
        "show me recent changes since I started": ("task", "recent_changes"),
        "give me a summary of the page": ("task", "page_summary"),
        "which arrow connects the two boxes?": ("operation", "connector_candidates"),
        "how are these strokes grouped?": ("operation", "grouping_candidates"),
    }
    for query, (key, expected) in cases.items():
        workspace = build_observation_workspace(canvas, query)
        analysis = workspace["analysis"]
        assert analysis is not None, query
        assert analysis[key] == expected, (query, analysis.get(key))


def test_find_marks_ranks_equal_matches_by_analyzer_signal_not_insertion():
    canvas = Canvas()
    # Two equally-matching lines; the second is created later, so the analyzer's
    # page-map rank (creation-order signal) places it ahead of the first.
    early = canvas.add_stroke([(40, 40), (40, 200)], author=Author.USER)
    late = canvas.add_stroke([(600, 600), (600, 760)], author=Author.USER)
    interface = InkAgentInterface(canvas, policy="active-index")

    result = interface.call("find_marks", {"query": "line"})

    ids = [mark["id"] for mark in result["marks"]]
    assert set(ids) == {early.id, late.id}  # both match lexically
    assert ids[0] == late.id  # analyzer rank, not insertion order, wins


def test_workspace_is_budgeted_ranked_and_task_conditioned():
    canvas, loop_id = _scene()
    workspace = build_observation_workspace(
        canvas,
        "annotate the loop in the upper left",
        budget=PerceptionBudget(max_marks=1, max_bootstrap_chars=4000),
    )

    assert workspace["schema"] == "ink-agent-interface/v1"
    assert workspace["policy"] == "active-index"
    assert workspace["page_map"]["marks"][0]["id"] == loop_id
    assert workspace["page_map"]["marks"][0]["rank"] == 1
    assert workspace["page_map"]["handwriting_stroke_count"] == 12
    assert workspace["bootstrap_chars"] <= 4000
    assert workspace["capabilities"] == [
        "find_marks", "analyze_ink", "reduce_ink", "find_ink_moments",
        "inspect_ink_moment", "view_region", "get_ink", "expand_relations",
    ]
    with pytest.raises(ValueError, match="minimal observation workspace"):
        build_observation_workspace(
            canvas,
            budget=PerceptionBudget(max_marks=0, max_bootstrap_chars=10),
        )


def test_marked_policy_adds_set_of_marks_binding():
    canvas, loop_id = _scene()
    workspace = build_observation_workspace(canvas, policy="marked-index")

    marked = workspace["page_map"]["marked_view"]
    assert marked["format"] == "ascii-set-of-marks"
    assert loop_id in marked["legend"].values()
    assert marked["data"]


def test_typed_perception_actions_enforce_policy_and_budget():
    canvas, loop_id = _scene()
    interface = InkAgentInterface(
        canvas,
        "find the loop",
        budget=PerceptionBudget(max_actions=2, max_raster_pixels=100_000),
    )

    found = interface.call("find_marks", {"query": "loop"})
    assert found["marks"][0]["id"] == loop_id
    ink = interface.call("get_ink", {"stroke_ids": [loop_id], "detail": "bboxes"})
    assert ink["strokes"][0]["bbox"] == [40, 40, 180, 180]
    assert interface.telemetry()["action_types"] == ["find_marks", "get_ink"]
    with pytest.raises(ValueError, match="budget exhausted"):
        interface.call("view_region", {"region": [0, 0, 200, 200], "modality": "ascii"})

    strict = InkAgentInterface(canvas, policy="index-only")
    with pytest.raises(ValueError, match="does not allow"):
        strict.call("find_marks", {"query": "loop"})


def test_raster_budget_is_enforced():
    canvas, _ = _scene()
    interface = InkAgentInterface(
        canvas,
        budget=PerceptionBudget(max_raster_pixels=100),
    )
    with pytest.raises(ValueError, match="raster pixel budget"):
        interface.call("view_region", {"region": [0, 0, 20, 20], "modality": "raster"})


def test_stdio_mcp_lists_and_calls_iai_tools(tmp_path):
    canvas, loop_id = _scene()
    state = tmp_path / "state.json"
    canvas.document.save(state)
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "find_marks", "arguments": {"query": "loop"}},
        },
    ]
    completed = subprocess.run(
        [sys.executable, "-m", "neeh.agents.iai_mcp", "--state", str(state)],
        input="\n".join(json.dumps(request) for request in requests) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines()]

    assert responses[0]["result"]["serverInfo"]["name"] == "neeh-iai"
    assert {tool["name"] for tool in responses[1]["result"]["tools"]} == {
        "find_marks", "analyze_ink", "reduce_ink", "find_ink_moments",
        "inspect_ink_moment", "view_region", "get_ink", "expand_relations",
    }
    called = responses[2]["result"]["structuredContent"]
    assert called["marks"][0]["id"] == loop_id


def test_stdio_mcp_rejects_oversized_line_without_crashing(tmp_path):
    from neeh.agents.iai_mcp import _MAX_LINE_BYTES

    canvas, _ = _scene()
    state = tmp_path / "state.json"
    canvas.document.save(state)
    oversized_line = "x" * (_MAX_LINE_BYTES + 500) + "\n"
    normal_request = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    ) + "\n"
    completed = subprocess.run(
        [sys.executable, "-m", "neeh.agents.iai_mcp", "--state", str(state)],
        input=oversized_line + normal_request,
        text=True,
        capture_output=True,
        check=True,
    )
    responses = [json.loads(line) for line in completed.stdout.splitlines()]

    assert responses[0]["error"]["code"] == -32600
    assert "byte limit" in responses[0]["error"]["message"]
    # the server kept running and answered the next, well-formed request
    assert responses[1]["result"]["serverInfo"]["name"] == "neeh-iai"


def test_intent_routing_reads_history_and_recorded_groups_exactly():
    canvas = Canvas()
    a = canvas.add_stroke([(100, 100), (160, 100)], author=Author.USER)
    b = canvas.add_stroke([(100, 200), (160, 200)], author=Author.USER)
    c = canvas.add_stroke([(400, 400), (460, 400)], author=Author.USER)
    group_id = canvas.group([a.id, b.id], label="pair")
    canvas.erase([c.id])
    rewrite = canvas.add_stroke([(404, 404), (466, 404)], author=Author.USER)
    canvas.move(9, 9, stroke_ids=[a.id])

    # "erased" routes to event-log-backed revisions; the erase and its rewrite
    # arrive as the top-ranked, confidence-1.0 entry.
    erased = build_observation_workspace(canvas, "which stroke id was erased?")["analysis"]
    assert erased["task"] == "revisions"
    top = erased["revisions"][0]
    assert top["kind"] == "erase_rewrite"
    assert top["target_ids"] == [c.id]
    assert top["by_ids"] == [rewrite.id]
    assert top["confidence"] == 1.0

    # "changed most recently" is about modification history, so it must not be
    # shadowed by the latest_mark intent ("...most recent..."): the answer is
    # the moved stroke, which no drawing-time measure can see.
    changed = build_observation_workspace(
        canvas, "which stroke id was changed most recently?"
    )["analysis"]
    assert changed["task"] == "recent_changes"
    assert changed["changes"][0]["id"] == a.id
    assert changed["changes"][0]["change"] == "move"

    # Group questions read recorded membership, never a spatial guess, when
    # the log has groups.
    groups = build_observation_workspace(
        canvas, f"which stroke ids belong to group {group_id}?"
    )["analysis"]
    assert groups["operation"] == "recorded_groups"
    assert groups["groups"][0]["member_ids"] == [a.id, b.id]

    # ...and recorded membership rides in the static page map for every
    # policy, including index-only, which has no perception actions.
    workspace = build_observation_workspace(canvas, "hello", policy="index-only")
    page_groups = workspace["page_map"]["groups"]
    assert page_groups[0]["group_id"] == group_id
    assert page_groups[0]["member_ids"] == [a.id, b.id]
