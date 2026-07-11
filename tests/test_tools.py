import json

import pytest

from neeh import Canvas
from neeh.ink import Author
from neeh.tools import all_tools, call_tool, get_tool, tool_schemas

EXPECTED_TOOLS = {
    "view_page",
    "view_region",
    "fetch_ink_region",
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


def test_render_format_is_validated_for_direct_python_calls():
    with pytest.raises(ValueError, match="format"):
        call_tool(Canvas(), "view_page", {"format": "jpeg"})


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

    assert call_tool(canvas, "get_strokes", {"stroke_ids": []})["stroke_count"] == 0

    with pytest.raises(ValueError, match="author"):
        call_tool(canvas, "get_strokes", {"author": "robot"})
    with pytest.raises(ValueError, match="non-empty strings"):
        call_tool(canvas, "get_strokes", {"stroke_ids": [""]})


def test_add_stroke_is_agent_authored():
    canvas = Canvas()
    result = call_tool(canvas, "add_stroke", {"points": [[0, 0], [10, 10]], "color": "#ff0000"})
    layer, stroke = canvas.page.find(result["stroke_id"])
    assert stroke.author is Author.AGENT
    assert layer.author is Author.AGENT
    assert stroke.style.color == "#ff0000"


def test_add_stroke_does_not_turn_invalid_falsey_values_into_defaults():
    canvas = Canvas()
    with pytest.raises(ValueError, match="width"):
        call_tool(canvas, "add_stroke", {"points": [[0, 0]], "width": 0})
    with pytest.raises(ValueError, match="color"):
        call_tool(canvas, "add_stroke", {"points": [[0, 0]], "color": ""})
    assert canvas.page.all_strokes() == []


@pytest.mark.parametrize(
    "points",
    [[], [[0, 0, 1.5]], [[float("inf"), 0]]],
)
def test_failed_agent_stroke_validation_does_not_create_a_layer(points):
    canvas = Canvas()
    before_layers = [layer.id for layer in canvas.page.layers]

    with pytest.raises(ValueError):
        call_tool(canvas, "add_stroke", {"points": points})

    assert [layer.id for layer in canvas.page.layers] == before_layers
    assert canvas.history.can_undo is False


def test_erase_select_move_flow():
    canvas = Canvas()
    a = call_tool(canvas, "add_stroke", {"points": [[0, 0], [10, 10]]})["stroke_id"]
    b = call_tool(canvas, "add_stroke", {"points": [[500, 500], [510, 510]]})["stroke_id"]

    selected = call_tool(canvas, "select", {"region": [-1, -1, 20, 20]})
    assert selected["selected"] == [a]
    assert selected["bounds"] == [0, 0, 10, 10]

    assert call_tool(canvas, "move", {"dx": 5, "dy": 5})["moved"] == 1
    assert call_tool(canvas, "erase", {"stroke_ids": [b]})["erased"] == [b]


def test_selector_cross_fields_and_move_numbers_are_validated_atomically():
    canvas = Canvas()
    stroke_id = call_tool(canvas, "add_stroke", {"points": [[0, 0], [10, 10]]})["stroke_id"]

    with pytest.raises(ValueError, match="exactly one"):
        call_tool(
            canvas,
            "erase",
            {"stroke_ids": [stroke_id], "region": [-1, -1, 20, 20]},
        )
    with pytest.raises(ValueError, match="at most one"):
        call_tool(
            canvas,
            "select",
            {"stroke_ids": [stroke_id], "region": [-1, -1, 20, 20]},
        )
    with pytest.raises(ValueError, match="finite"):
        call_tool(canvas, "move", {"stroke_ids": [stroke_id], "dx": float("inf"), "dy": 0})

    assert canvas.page.find(stroke_id) is not None


def test_duplicate_id_selectors_are_idempotent_and_undo_safe():
    canvas = Canvas()
    stroke_id = call_tool(canvas, "add_stroke", {"points": [[0, 0], [10, 10]]})["stroke_id"]

    assert call_tool(
        canvas,
        "move",
        {"stroke_ids": [stroke_id, stroke_id], "dx": 5, "dy": 0},
    ) == {"moved": 1}
    assert len(canvas.page.all_strokes()) == 1
    assert call_tool(canvas, "undo") == {"undone": "move"}
    assert len(canvas.page.all_strokes()) == 1

    assert call_tool(canvas, "erase", {"stroke_ids": [stroke_id, stroke_id]}) == {
        "erased": [stroke_id]
    }
    assert call_tool(canvas, "undo") == {"undone": "erase"}
    assert [stroke.id for stroke in canvas.page.all_strokes()] == [stroke_id]


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


@pytest.mark.parametrize("arguments", [[], False, 0, ""])
def test_non_object_arguments_are_rejected_without_executing(arguments):
    canvas = Canvas()
    stroke = canvas.add_stroke([(0, 0)])

    with pytest.raises(ValueError, match="arguments must be an object"):
        call_tool(canvas, "undo", arguments)

    assert canvas.page.find(stroke.id) is not None
    assert canvas.history.can_undo is True


def test_write_text_prints_ink_and_user_font_is_reserved():
    canvas = Canvas()
    result = call_tool(canvas, "write_text", {"text": "hi", "region": [0, 0, 100, 40]})
    assert result["stroke_ids"]
    with pytest.raises(NotImplementedError):
        call_tool(
            canvas, "write_text",
            {"text": "hi", "region": [0, 0, 100, 40], "style": "user_font"},
        )
