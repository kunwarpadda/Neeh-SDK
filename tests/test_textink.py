"""Tests for text-as-ink layout and the write_text tool."""
import pytest

from neeh.canvas import Canvas
from neeh.ink import Author, BoundingBox
from neeh.ink.hershey_simplex import GLYPHS
from neeh.ink.textink import MIN_SIZE, layout_text
from neeh.tools import call_tool


def flatten(polylines):
    return [pt for pl in polylines for pt in pl]


def test_layout_stays_inside_region_horizontally():
    box = BoundingBox(100, 200, 500, 400)
    polylines, size = layout_text("What is the derivative of x squared?", box)
    assert polylines, "text should produce ink"
    assert size >= MIN_SIZE
    xs = [x for x, _ in flatten(polylines)]
    ys = [y for _, y in flatten(polylines)]
    assert min(xs) >= box.min_x and max(xs) <= box.max_x
    overshoot = size * 4 / 21  # tall glyphs may poke above the cap box
    assert min(ys) >= box.min_y - overshoot
    assert max(ys) <= box.max_y + size  # descenders may dip below the last baseline


def test_longer_text_wraps_and_shrinks():
    box = BoundingBox(0, 0, 300, 100)
    _, size_short = layout_text("Hi", box)
    _, size_long = layout_text(
        "This is a much longer answer that must wrap onto several lines to fit", box
    )
    assert size_long < size_short


def test_explicit_newlines_make_lines():
    box = BoundingBox(0, 0, 1000, 500)
    one_line, size = layout_text("ab", box, size=20)
    two_lines, _ = layout_text("a\nb", box, size=20)
    ys_one = {round(y) for _, y in flatten(one_line)}
    ys_two = {round(y) for _, y in flatten(two_lines)}
    assert max(ys_two) > max(ys_one), "second line must sit lower"


def test_unknown_chars_fall_back_instead_of_crashing():
    box = BoundingBox(0, 0, 500, 100)
    polylines, _ = layout_text("héllo → ok", box)
    assert polylines


def test_handwritten_style_is_distinct_deterministic_and_bounded():
    box = BoundingBox(100, 200, 700, 360)
    printed, _ = layout_text("The quick brown fox 123", box, size=36, style="print")
    handwritten, _ = layout_text(
        "The quick brown fox 123", box, size=36, style="handwritten"
    )
    repeated, _ = layout_text(
        "The quick brown fox 123", box, size=36, style="handwritten"
    )

    assert handwritten == repeated
    assert handwritten != printed
    assert len(handwritten) > len(printed)  # Script Complex adds calligraphic strokes.
    xs = [x for x, _ in flatten(handwritten)]
    assert min(xs) >= box.min_x and max(xs) <= box.max_x


def test_handwritten_style_keeps_all_supported_glyphs_inside_their_line():
    box = BoundingBox(0, 0, 10000, 200)
    text = "".join(ch for ch in GLYPHS if not ch.isspace())
    handwritten, _ = layout_text(text, box, size=20, style="handwritten")
    xs = [x for x, _ in flatten(handwritten)]
    assert min(xs) >= box.min_x and max(xs) <= box.max_x


def test_write_text_tool_is_agent_ink_and_one_undo():
    canvas = Canvas()
    result = call_tool(
        canvas,
        "write_text",
        {"text": "6x", "region": [100, 100, 400, 200], "color": "#1d4ed8",
         "style": "handwritten"},
    )
    assert result["stroke_ids"]
    assert result["style"] == "handwritten"
    agent_layer = canvas.page.agent_layer()
    assert {s.id for s in agent_layer.strokes} == set(result["stroke_ids"])
    assert all(s.author is Author.AGENT for s in agent_layer.strokes)

    call_tool(canvas, "undo")
    assert agent_layer.strokes == [], "written text must undo as a single edit"


def test_write_text_user_font_still_reserved():
    canvas = Canvas()
    with pytest.raises(NotImplementedError):
        call_tool(
            canvas,
            "write_text",
            {"text": "hi", "region": [0, 0, 100, 100], "style": "user_font"},
        )
