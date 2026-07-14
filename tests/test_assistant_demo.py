"""The browser demo examples exercise real deterministic SDK behavior."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from neeh.agents import analyze_ink


MODULE_PATH = Path(__file__).parents[1] / "examples" / "assistant" / "server.py"
SPEC = importlib.util.spec_from_file_location("assistant_demo_server", MODULE_PATH)
assert SPEC and SPEC.loader
demo = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(demo)


@pytest.mark.parametrize("name", ["latest", "direction", "crossout"])
def test_demo_scenarios_are_deterministic_and_described(name):
    first, first_metadata = demo.make_scenario(name)
    second, second_metadata = demo.make_scenario(name)

    assert first_metadata == second_metadata
    assert (
        [stroke.to_dict() for stroke in first.page.layers[0].strokes]
        == [stroke.to_dict() for stroke in second.page.layers[0].strokes]
    )
    assert first_metadata["question"]
    assert first_metadata["analysis"]["operation"]


def test_latest_mark_scenario_resolves_to_upper_right_check():
    canvas, metadata = demo.make_scenario("latest")

    result = analyze_ink(canvas, **metadata["analysis"])

    assert result["latest"]["id"] == "st_check"
    assert result["latest"]["vertical_half"] == "upper"
    assert result["latest"]["horizontal_half"] == "right"


def test_direction_scenario_preserves_leftward_capture_order():
    canvas, metadata = demo.make_scenario("direction")

    result = analyze_ink(canvas, **metadata["analysis"])

    assert result["strokes"][0]["id"] == "st_direction"
    assert result["strokes"][0]["direction"] == "left"


def test_crossout_scenario_identifies_affected_prior_ink():
    canvas, metadata = demo.make_scenario("crossout")

    result = analyze_ink(canvas, **metadata["analysis"])

    assert result["candidates"][0]["stroke_ids"] == ["st_cross"]
    assert result["candidates"][0]["affected_prior_ids"] == ["st_original"]


def test_unknown_demo_scenario_is_rejected():
    with pytest.raises(ValueError, match="unknown scenario"):
        demo.make_scenario("missing")


def test_status_stroke_count_can_distinguish_blank_and_existing_pages():
    blank = demo.Canvas()
    existing, _ = demo.make_scenario("latest")

    assert sum(len(layer.strokes) for layer in blank.page.layers) == 0
    assert sum(len(layer.strokes) for layer in existing.page.layers) == 3


def test_server_urls_include_loopback_and_deduplicated_lan_addresses():
    assert demo._server_urls(
        "0.0.0.0",
        8787,
        ["192.168.1.20", "192.168.1.20", "10.0.0.8"],
    ) == [
        "http://127.0.0.1:8787",
        "http://192.168.1.20:8787",
        "http://10.0.0.8:8787",
    ]


def test_server_urls_preserve_an_explicit_bind_host():
    assert demo._server_urls("192.168.1.20", 9000) == [
        "http://192.168.1.20:9000"
    ]


def test_explicit_codex_mode_surfaces_backend_failure(monkeypatch):
    monkeypatch.setattr(demo, "agent_mode", "codex")
    monkeypatch.setattr(
        demo,
        "run_codex_cli",
        lambda *_: (_ for _ in ()).throw(demo.ModelUnavailableError("usage limit")),
    )
    mock_called = False

    def mock(*_):
        nonlocal mock_called
        mock_called = True
        return {}

    monkeypatch.setattr(demo, "run_mock", mock)

    with pytest.raises(demo.ModelUnavailableError, match="usage limit"):
        demo.ask(None)
    assert mock_called is False


def test_auto_mode_can_fall_back_to_mock(monkeypatch):
    monkeypatch.setattr(demo, "agent_mode", "auto")
    monkeypatch.setattr(
        demo,
        "run_codex_cli",
        lambda *_: (_ for _ in ()).throw(demo.ModelUnavailableError("unavailable")),
    )
    monkeypatch.setattr(
        demo,
        "run_claude",
        lambda *_: (_ for _ in ()).throw(demo.ModelUnavailableError("unavailable")),
    )
    monkeypatch.setattr(demo, "run_mock", lambda *_: {"reply": "mock", "actions": []})

    result = demo.ask(None)

    assert result["mode"] == "mock"
    assert result["fallback_reason"].startswith("claude-cli:")
