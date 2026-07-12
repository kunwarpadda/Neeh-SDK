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
    "insert_text",
    "mark",
    "connect",
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


def test_write_text_defaults_to_agent_hand_and_user_font_is_reserved():
    canvas = Canvas()
    result = call_tool(canvas, "write_text", {"text": "hi", "region": [0, 0, 100, 40]})
    assert result["stroke_ids"]
    assert result["style"] == "handwritten"
    assert get_tool("write_text").parameters["properties"]["style"]["enum"] == [
        "print", "handwritten"
    ]
    with pytest.raises(NotImplementedError):
        call_tool(
            canvas, "write_text",
            {"text": "hi", "region": [0, 0, 100, 40], "style": "user_font"},
        )


def _anchor(canvas):
    """A word-like anchor stroke: 40 units tall, at (200..320, 300..340)."""
    return canvas.add_stroke([(200, 300), (320, 300), (320, 340), (200, 340)])


def test_mark_strike_crosses_the_anchor():
    canvas = Canvas()
    anchor = _anchor(canvas)
    result = call_tool(canvas, "mark", {"stroke_ids": [anchor.id], "kind": "strike"})
    _, stroke = canvas.page.find(result["stroke_id"])
    assert stroke.author is Author.AGENT
    ys = {p.y for p in stroke.points}
    assert ys == {320}  # vertical center of the anchor
    assert stroke.bbox.min_x < 200 and stroke.bbox.max_x > 320


def test_mark_underline_sits_below_and_circle_rings_the_anchor():
    canvas = Canvas()
    anchor = _anchor(canvas)
    under = call_tool(canvas, "mark", {"stroke_ids": [anchor.id], "kind": "underline"})
    _, stroke = canvas.page.find(under["stroke_id"])
    assert min(p.y for p in stroke.points) > 340

    ring = call_tool(canvas, "mark", {"stroke_ids": [anchor.id], "kind": "circle"})
    _, stroke = canvas.page.find(ring["stroke_id"])
    box = stroke.bbox
    assert box.min_x < 200 and box.max_x > 320
    assert box.min_y < 300 and box.max_y > 340


def test_mark_check_lands_right_of_the_anchor():
    canvas = Canvas()
    anchor = _anchor(canvas)
    result = call_tool(canvas, "mark", {"stroke_ids": [anchor.id], "kind": "check"})
    _, stroke = canvas.page.find(result["stroke_id"])
    assert stroke.bbox.min_x > 320


def test_mark_rejects_unknown_ids_and_kinds():
    canvas = Canvas()
    anchor = _anchor(canvas)
    with pytest.raises(ValueError, match="unknown stroke ids"):
        call_tool(canvas, "mark", {"stroke_ids": ["st_nope"], "kind": "strike"})
    with pytest.raises(ValueError, match="kind"):
        call_tool(canvas, "mark", {"stroke_ids": [anchor.id], "kind": "wavy"})
    with pytest.raises(ValueError, match="at least one"):
        call_tool(canvas, "mark", {"stroke_ids": [], "kind": "strike"})


def _distance_to_box(box, x, y):
    dx = max(box[0] - x, 0.0, x - box[2])
    dy = max(box[1] - y, 0.0, y - box[3])
    return (dx * dx + dy * dy) ** 0.5


def test_connect_points_at_the_target_without_touching_it():
    canvas = Canvas()
    target = _anchor(canvas)
    result = call_tool(canvas, "connect", {"stroke_ids": [target.id]})

    assert result["target_bbox"] == [200, 300, 320, 340]
    assert result["source_bbox"] is None
    assert len(result["stroke_ids"]) == 2  # shaft + head, one gesture
    tip_x, tip_y = result["to"]
    gap = _distance_to_box(result["target_bbox"], tip_x, tip_y)
    assert 0 < gap <= 14.5  # just outside the ink, never on it
    tail_x, tail_y = result["from"]
    assert ((tip_x - tail_x) ** 2 + (tip_y - tail_y) ** 2) ** 0.5 >= 12
    for stroke_id in result["stroke_ids"]:
        _, stroke = canvas.page.find(stroke_id)
        assert stroke.author is Author.AGENT

    assert canvas.undo() == "add_strokes"  # the whole arrow is one edit
    assert all(canvas.page.find(sid) is None for sid in result["stroke_ids"])


def test_connect_runs_from_source_ink_to_target_ink():
    canvas = Canvas()
    target = _anchor(canvas)  # centered at (260, 320)
    source = canvas.add_stroke([(500, 300), (560, 340)])  # centered at (530, 320)
    result = call_tool(canvas, "connect", {
        "stroke_ids": [target.id], "source_stroke_ids": [source.id],
        "color": "#1d4ed8",
    })

    assert result["source_bbox"] == [500, 300, 560, 340]
    tip_x, tip_y = result["to"]
    tail_x, tail_y = result["from"]
    assert tip_y == pytest.approx(320) and tail_y == pytest.approx(320)
    assert 320 < tip_x < 340  # tip stands off the target's source-facing side
    assert 470 < tail_x < 500  # tail stands off the source's target-facing side
    _, shaft = canvas.page.find(result["stroke_ids"][0])
    assert shaft.style.color == "#1d4ed8"


def test_connect_rejects_unknown_ids_and_coincident_endpoints():
    canvas = Canvas()
    target = _anchor(canvas)
    with pytest.raises(ValueError, match="unknown stroke ids"):
        call_tool(canvas, "connect", {"stroke_ids": ["st_nope"]})
    with pytest.raises(ValueError, match="source_stroke_ids"):
        call_tool(canvas, "connect", {
            "stroke_ids": [target.id], "source_stroke_ids": ["st_nope"],
        })
    with pytest.raises(ValueError, match="coincide"):
        call_tool(canvas, "connect", {
            "stroke_ids": [target.id], "source_stroke_ids": [target.id],
        })
    with pytest.raises(ValueError, match="too close"):
        near = canvas.add_stroke([(322, 300), (330, 340)])
        call_tool(canvas, "connect", {
            "stroke_ids": [target.id], "source_stroke_ids": [near.id],
        })
    assert not canvas.page.agent_layer().strokes  # failures never mutate


def test_insert_text_before_and_after_hug_the_anchor():
    canvas = Canvas()
    anchor = _anchor(canvas)
    before = call_tool(
        canvas, "insert_text",
        {"text": '"', "stroke_ids": [anchor.id], "position": "before"},
    )
    assert before["region"][2] <= 200  # right edge at or left of anchor start
    assert before["size"] == pytest.approx(36.0)  # 0.9 x anchor height
    after = call_tool(
        canvas, "insert_text",
        {"text": '"', "stroke_ids": [anchor.id], "position": "after"},
    )
    assert after["region"][0] >= 320
    for result in (before, after):
        assert result["style"] == "handwritten"
        for sid in result["stroke_ids"]:
            _, stroke = canvas.page.find(sid)
            assert stroke.author is Author.AGENT


def test_insert_text_above_below_and_no_room_error():
    canvas = Canvas()
    anchor = _anchor(canvas)
    above = call_tool(
        canvas, "insert_text",
        {"text": "fix", "stroke_ids": [anchor.id], "position": "above"},
    )
    assert above["region"][3] <= 300
    below = call_tool(
        canvas, "insert_text",
        {"text": "fix", "stroke_ids": [anchor.id], "position": "below"},
    )
    assert below["region"][1] >= 340

    edge = canvas.add_stroke([(0, 500), (40, 540)])  # anchor at the left edge
    with pytest.raises(ValueError, match="no room"):
        call_tool(
            canvas, "insert_text",
            {"text": "long correction", "stroke_ids": [edge.id], "position": "before"},
        )


def test_insert_text_validates_inputs():
    canvas = Canvas()
    anchor = _anchor(canvas)
    with pytest.raises(ValueError, match="position"):
        call_tool(
            canvas, "insert_text",
            {"text": "x", "stroke_ids": [anchor.id], "position": "inside"},
        )
    with pytest.raises(ValueError, match="non-empty"):
        call_tool(
            canvas, "insert_text",
            {"text": "  ", "stroke_ids": [anchor.id], "position": "before"},
        )


def test_insert_text_uses_horizontal_punctuation_width_for_auto_size():
    canvas = Canvas()
    hyphen = canvas.add_stroke([(200, 320), (232, 320)])

    result = call_tool(
        canvas, "insert_text",
        {"text": "_", "stroke_ids": [hyphen.id], "position": "below"},
    )

    assert result["size"] == pytest.approx(28.8)


def test_insert_text_after_opens_room_by_shifting_only_trailing_same_line_ink():
    canvas = Canvas()
    opener = canvas.add_stroke([(200, 300), (210, 340)])
    word = canvas.add_stroke([(214, 300), (260, 340)])
    closer = canvas.add_stroke([(264, 300), (270, 340)])
    other_row = canvas.add_stroke([(214, 450), (260, 490)])
    tall_arrow = canvas.add_stroke([(280, 290), (500, 600)])

    result = call_tool(
        canvas, "insert_text",
        {"text": '"', "stroke_ids": [opener.id], "position": "after"},
    )

    reflow = result["reflow"]
    assert 0 < reflow["dx"] <= 64
    assert reflow["moved_stroke_ids"] == [word.id, closer.id]
    assert canvas.page.find(opener.id)[1].bbox.min_x == 200
    assert canvas.page.find(word.id)[1].bbox.min_x == pytest.approx(214 + reflow["dx"])
    assert canvas.page.find(closer.id)[1].bbox.min_x == pytest.approx(264 + reflow["dx"])
    assert canvas.page.find(other_row.id)[1].bbox.min_x == 214
    assert canvas.page.find(tall_arrow.id)[1].bbox.min_x == 280
    assert result["region"][2] < canvas.page.find(word.id)[1].bbox.min_x

    assert canvas.undo() == "insert_text"
    assert canvas.page.find(word.id)[1].bbox.min_x == 214
    assert all(canvas.page.find(stroke_id) is None for stroke_id in result["stroke_ids"])
    assert canvas.redo() == "insert_text"


def test_insert_text_before_shifts_anchor_and_following_ink_as_one_group():
    canvas = Canvas()
    word = canvas.add_stroke([(200, 300), (280, 340)])
    closer = canvas.add_stroke([(285, 300), (295, 340)])
    trailing = canvas.add_stroke([(300, 300), (310, 340)])

    result = call_tool(
        canvas, "insert_text",
        {"text": '"', "stroke_ids": [closer.id], "position": "before"},
    )

    reflow = result["reflow"]
    assert reflow["moved_stroke_ids"] == [closer.id, trailing.id]
    assert result["anchor_bbox"][0] == pytest.approx(285 + reflow["dx"])
    assert result["original_anchor_bbox"][0] == 285
    assert canvas.page.find(word.id)[1].bbox.min_x == 200
    assert result["region"][0] > canvas.page.find(word.id)[1].bbox.max_x


def test_insert_text_sequence_reserves_both_quote_gaps_inside_parentheses():
    canvas = Canvas()
    opener = canvas.add_stroke([(200, 300), (210, 340)])
    word = canvas.add_stroke([(214, 300), (260, 340)])
    closer = canvas.add_stroke([(264, 300), (270, 340)])

    opening_quote = call_tool(
        canvas, "insert_text",
        {"text": '"', "stroke_ids": [opener.id], "position": "after"},
    )
    closing_quote = call_tool(
        canvas, "insert_text",
        {"text": '"', "stroke_ids": [closer.id], "position": "before"},
    )

    moved_word = canvas.page.find(word.id)[1]
    moved_closer = canvas.page.find(closer.id)[1]
    assert opening_quote["region"][2] < moved_word.bbox.min_x
    assert closing_quote["region"][0] > moved_word.bbox.max_x
    assert closing_quote["region"][2] < moved_closer.bbox.min_x
    assert closing_quote["reflow"]["moved_stroke_ids"] == [closer.id]


def test_insert_text_does_not_reflow_when_the_existing_gap_is_large_enough():
    canvas = Canvas()
    anchor = canvas.add_stroke([(200, 300), (210, 340)])
    distant = canvas.add_stroke([(400, 300), (440, 340)])

    result = call_tool(
        canvas, "insert_text",
        {"text": '"', "stroke_ids": [anchor.id], "position": "after"},
    )

    assert result["reflow"] == {"moved_stroke_ids": [], "dx": 0.0, "dy": 0.0}
    assert canvas.page.find(distant.id)[1].bbox.min_x == 400


def test_insert_text_reflow_rejects_page_overflow_without_mutating():
    canvas = Canvas()
    anchor = canvas.add_stroke([(940, 300), (950, 340)])
    trailing = canvas.add_stroke([(960, 300), (999, 340)])

    with pytest.raises(ValueError, match="beyond the page"):
        call_tool(
            canvas, "insert_text",
            {"text": '"', "stroke_ids": [anchor.id], "position": "after"},
        )

    assert canvas.page.find(anchor.id)[1].bbox.min_x == 940
    assert canvas.page.find(trailing.id)[1].bbox.min_x == 960
    assert all(layer.author is Author.USER for layer in canvas.page.layers)


def test_insert_text_reflow_treats_locked_ink_as_an_unmovable_obstacle():
    canvas = Canvas()
    anchor = canvas.add_stroke([(200, 300), (210, 340)])
    locked = canvas.page.add_layer("locked")
    trailing = canvas.add_stroke([(214, 300), (260, 340)], layer=locked)
    locked.locked = True

    with pytest.raises(ValueError, match="locked or non-user ink"):
        call_tool(
            canvas, "insert_text",
            {"text": '"', "stroke_ids": [anchor.id], "position": "after"},
        )

    assert canvas.page.find(anchor.id)[1].bbox.min_x == 200
    assert canvas.page.find(trailing.id)[1].bbox.min_x == 214
    assert not any(layer.author is Author.AGENT for layer in canvas.page.layers)
