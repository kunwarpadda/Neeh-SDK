"""ASCII gestalt renderer: layout survives, marks overlay, empty is empty."""
from neeh import Canvas, render_page_ascii
from neeh.ink import Author


def _lines(text):
    return text.split("\n")


def test_empty_page_renders_empty():
    assert render_page_ascii(Canvas().page) == ""


def test_horizontal_and_vertical_strokes_use_direction_glyphs():
    canvas = Canvas()
    canvas.add_stroke([(100, 100), (400, 100)], author=Author.USER)  # horizontal
    canvas.add_stroke([(100, 100), (100, 400)], author=Author.USER)  # vertical
    art = render_page_ascii(canvas.page, cols=40)
    assert "-" in art and "|" in art
    # The horizontal run is a top row of dashes; the vertical run is a column.
    assert any(line.count("-") > 5 for line in _lines(art))
    assert sum(line[:2].count("|") for line in _lines(art)) > 3


def test_grid_is_bounded_by_cols_and_aspect_correct_rows():
    canvas = Canvas()
    canvas.add_stroke([(0, 0), (200, 0), (200, 200), (0, 200), (0, 0)], author=Author.USER)
    art = render_page_ascii(canvas.page, cols=30)
    lines = _lines(art)
    assert all(len(line) <= 30 for line in lines)
    # A square region renders about half as many rows as cols (cells are ~2:1).
    assert 12 <= len(lines) <= 18


def test_marks_overlay_on_top_of_ink_at_their_cells():
    canvas = Canvas()
    canvas.add_stroke([(100, 100), (400, 100), (400, 400), (100, 400), (100, 100)],
                      author=Author.USER)
    plain = render_page_ascii(canvas.page, cols=40)
    marked = render_page_ascii(canvas.page, cols=40, marks={"7": (250, 250)})
    assert "7" not in plain
    assert "7" in marked  # the label lands inside the box, on top of the ink


def test_strip_trailing_whitespace_by_default():
    canvas = Canvas()
    # A diagonal: each row holds one glyph, so most rows have trailing space.
    canvas.add_stroke([(100, 100), (400, 400)], author=Author.USER)
    stripped = render_page_ascii(canvas.page, cols=40)
    unstripped = render_page_ascii(canvas.page, cols=40, strip=False)
    assert len(stripped) < len(unstripped)
    assert not any(line.endswith(" ") for line in _lines(stripped))
    assert any(line.endswith(" ") for line in _lines(unstripped))
