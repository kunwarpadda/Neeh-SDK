from neeh import Canvas, StrokeStyle, render_page_svg
from neeh.ink import BoundingBox


def test_page_svg_has_background_and_strokes():
    canvas = Canvas()
    canvas.add_stroke([(10, 10), (50, 50)], style=StrokeStyle(color="#123456"))
    svg = render_page_svg(canvas.page)
    assert svg.startswith("<svg ") and svg.endswith("</svg>")
    assert '<rect' in svg and 'fill="#ffffff"' in svg
    assert '<polyline' in svg and 'stroke="#123456"' in svg


def test_single_point_renders_as_circle():
    canvas = Canvas()
    canvas.add_stroke([(30, 40)])
    assert "<circle" in render_page_svg(canvas.page)


def test_region_crop_excludes_far_strokes():
    canvas = Canvas()
    canvas.add_stroke([(10, 10), (20, 20)], style=StrokeStyle(color="#aa0000"))
    canvas.add_stroke([(900, 900), (910, 910)], style=StrokeStyle(color="#00bb00"))
    svg = render_page_svg(canvas.page, region=BoundingBox(0, 0, 100, 100))
    assert 'stroke="#aa0000"' in svg
    assert 'stroke="#00bb00"' not in svg
    assert 'viewBox="0 0 100 100"' in svg


def test_hidden_layer_not_rendered():
    canvas = Canvas()
    canvas.add_stroke([(10, 10), (20, 20)])
    canvas.page.layer("ink").visible = False
    assert "<polyline" not in render_page_svg(canvas.page)


def test_highlighter_gets_opacity():
    canvas = Canvas()
    canvas.add_stroke([(0, 50), (100, 50)], style=StrokeStyle.highlighter())
    svg = render_page_svg(canvas.page)
    assert 'opacity="0.35"' in svg and 'stroke-linecap="butt"' in svg
