import json

import pytest

from neeh import Canvas
from neeh.ink import Author
from neeh.tools import all_tools, call_tool, get_tool, tool_schemas

EXPECTED_TOOLS = {
    "view_page",
    "view_region",
    "get_strokes",
    "add_stroke",
    "erase",
    "select",
    "move",
    "highlight",
    "write_text",
    "undo",
    "redo",
}


def test_registry_exposes_v1_surface():
    assert {t.name for t in all_tools()} == EXPECTED_TOOLS
    schemas = tool_schemas()
    assert all(set(s) == {"name", "description", "input_schema"} for s in schemas)
    json.dumps(schemas)  # manifest must be JSON-serializable as-is

    with pytest.raises(KeyError):
        get_tool("recognize_region")  # not part of v1 — deferred understanding layer


def test_view_page_returns_svg():
    result = call_tool(Canvas(), "view_page")
    assert result["format"] == "svg"
    assert result["data"].startswith("<svg ")


def test_view_region_echoes_region():
    result = call_tool(Canvas(), "view_region", {"region": [0, 0, 100, 100]})
    assert result["region"] == [0, 0, 100, 100]
    assert 'viewBox="0 0 100 100"' in result["data"]


def test_get_strokes_returns_vector_context_and_filters():
    canvas = Canvas()
    user = canvas.add_stroke([(0, 0), (10, 10)])
    agent = call_tool(canvas, "add_stroke", {"points": [[100, 100], [120, 120]]})["stroke_id"]

    all_strokes = call_tool(canvas, "get_strokes")
    assert all_strokes["stroke_count"] == 2
    assert {s["id"] for s in all_strokes["strokes"]} == {user.id, agent}
    assert all_strokes["strokes"][0]["points"][0][:2] == [0, 0]
    assert all_strokes["strokes"][0]["bbox"] == [0, 0, 10, 10]

    agent_only = call_tool(canvas, "get_strokes", {"author": "agent", "include_points": False})
    assert agent_only["stroke_count"] == 1
    assert agent_only["strokes"][0]["id"] == agent
    assert "points" not in agent_only["strokes"][0]

    region = call_tool(canvas, "get_strokes", {"region": [-1, -1, 20, 20]})
    assert [s["id"] for s in region["strokes"]] == [user.id]


def test_add_stroke_is_agent_authored():
    canvas = Canvas()
    result = call_tool(canvas, "add_stroke", {"points": [[0, 0], [10, 10]], "color": "#ff0000"})
    layer, stroke = canvas.page.find(result["stroke_id"])
    assert stroke.author is Author.AGENT
    assert layer.author is Author.AGENT
    assert stroke.style.color == "#ff0000"


def test_erase_select_move_flow():
    canvas = Canvas()
    a = call_tool(canvas, "add_stroke", {"points": [[0, 0], [10, 10]]})["stroke_id"]
    b = call_tool(canvas, "add_stroke", {"points": [[500, 500], [510, 510]]})["stroke_id"]

    selected = call_tool(canvas, "select", {"region": [-1, -1, 20, 20]})
    assert selected["selected"] == [a]
    assert selected["bounds"] == [0, 0, 10, 10]

    assert call_tool(canvas, "move", {"dx": 5, "dy": 5})["moved"] == 1
    assert call_tool(canvas, "erase", {"stroke_ids": [b]})["erased"] == [b]


def test_highlight_creates_translucent_agent_stroke():
    canvas = Canvas()
    result = call_tool(canvas, "highlight", {"region": [0, 100, 200, 140]})
    _, stroke = canvas.page.find(result["stroke_id"])
    assert stroke.author is Author.AGENT
    assert stroke.style.opacity < 1.0
    assert stroke.style.width == 40  # spans the region height


def test_undo_redo_via_tools():
    canvas = Canvas()
    call_tool(canvas, "add_stroke", {"points": [[0, 0]]})
    assert call_tool(canvas, "undo") == {"undone": "add_stroke"}
    assert canvas.page.all_strokes() == []
    assert call_tool(canvas, "redo") == {"redone": "add_stroke"}
    assert call_tool(canvas, "undo", {})["undone"] == "add_stroke"
    assert call_tool(canvas, "undo")["undone"] is None


def test_write_text_prints_ink_and_user_font_is_reserved():
    canvas = Canvas()
    result = call_tool(canvas, "write_text", {"text": "hi", "region": [0, 0, 100, 40]})
    assert result["stroke_ids"]
    with pytest.raises(NotImplementedError):
        call_tool(
            canvas, "write_text",
            {"text": "hi", "region": [0, 0, 100, 40], "style": "user_font"},
        )
