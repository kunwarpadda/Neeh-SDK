"""Adversarial coverage for the stdio MCP server: malformed input, wrong
shapes, protocol error codes, id preservation, and budget behavior over MCP."""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from neeh import Canvas
from neeh.ink import Author


@pytest.fixture()
def state(tmp_path):
    canvas = Canvas()
    canvas.add_stroke([(40, 40), (180, 180)], author=Author.USER)
    path = tmp_path / "state.json"
    canvas.document.save(path)
    return path


def _serve(state, lines: list[str], extra_args: list[str] = ()) -> list[dict]:
    completed = subprocess.run(
        [sys.executable, "-m", "neeh.agents.iai_mcp", "--state", str(state), *extra_args],
        input="\n".join(lines) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    return [json.loads(line) for line in completed.stdout.splitlines()]


def test_malformed_json_gets_parse_error_and_server_survives(state):
    responses = _serve(state, [
        "{this is not json",
        json.dumps({"jsonrpc": "2.0", "id": 7, "method": "ping"}),
    ])
    assert responses[0]["error"]["code"] == -32700
    assert responses[0]["id"] is None
    # The server kept serving after the bad line.
    assert responses[1]["id"] == 7 and responses[1]["result"] == {}


def test_non_object_messages_get_invalid_request(state):
    responses = _serve(state, [
        json.dumps("just a string"),
        json.dumps([1, 2, 3]),
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
    ])
    assert responses[0]["error"]["code"] == -32600
    assert responses[1]["error"]["code"] == -32600
    assert responses[2]["result"] == {}


def test_unknown_method_and_unknown_tool_are_clean_errors(state):
    responses = _serve(state, [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "no/such_method"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "no_such_tool", "arguments": {}}}),
    ])
    assert responses[0]["error"]["code"] == -32601
    call = responses[1]["result"]
    assert call["isError"] is True
    assert "unknown IAI perception action" in call["content"][0]["text"]


def test_wrong_shaped_params_keep_the_request_id(state):
    # params as a list (not an object) must not lose the caller's id.
    responses = _serve(state, [
        json.dumps({"jsonrpc": "2.0", "id": 42, "method": "tools/call", "params": [1, 2]}),
    ])
    assert responses[0]["id"] == 42
    body = responses[0].get("error") or responses[0]["result"]
    assert body  # an addressed error, not a null-id orphan


def test_wrong_argument_types_are_tool_errors_not_crashes(state):
    responses = _serve(state, [
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "find_marks", "arguments": {"query": 5}}}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "find_marks",
                               "arguments": {"query": "x", "bogus_kwarg": 1}}}),
        json.dumps({"jsonrpc": "2.0", "id": 3, "method": "ping"}),
    ])
    assert responses[0]["result"]["isError"] is True
    assert responses[1]["result"]["isError"] is True
    assert responses[2]["result"] == {}  # still alive


def test_action_budget_is_enforced_over_mcp(state):
    calls = [
        json.dumps({"jsonrpc": "2.0", "id": i, "method": "tools/call",
                    "params": {"name": "find_marks", "arguments": {"query": "line"}}})
        for i in range(1, 4)
    ]
    responses = _serve(state, calls, extra_args=["--max-actions", "2"])
    assert responses[0]["result"]["isError"] is False
    assert responses[1]["result"]["isError"] is False
    assert responses[2]["result"]["isError"] is True
    assert "budget exhausted" in responses[2]["result"]["content"][0]["text"]


def test_notifications_get_no_response(state):
    responses = _serve(state, [
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}),
    ])
    assert len(responses) == 1  # only the ping was answered
    assert responses[0]["id"] == 1
