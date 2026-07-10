"""PNG rasterizer tests: real pixels, matching the SVG reference semantics."""
import base64
import io

import pytest

PIL = pytest.importorskip("PIL")
from PIL import Image

from neeh.canvas import Canvas
from neeh.document import Page
from neeh.ink import BoundingBox, Stroke
from neeh.ink.style import StrokeStyle
from neeh.rendering.png import render_page_png
from neeh.tools import call_tool


def decode(data: bytes) -> Image.Image:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return Image.open(io.BytesIO(data))


def test_blank_page_renders_background():
    page = Page(width=100, height=50, background="#336699")
    img = decode(render_page_png(page))
    assert img.size == (100, 50)
    assert img.getpixel((50, 25)) == (0x33, 0x66, 0x99)


def test_stroke_pixels_land_where_drawn():
    page = Page(width=100, height=100, background="#ffffff")
    page.layers[0].add(
        Stroke.from_xy([(10, 50), (90, 50)], style=StrokeStyle(color="#ff0000", width=6.0))
    )
    img = decode(render_page_png(page))
    r, g, b = img.getpixel((50, 50))
    assert r > 200 and g < 80 and b < 80  # red ink on the line
    assert img.getpixel((50, 10)) == (255, 255, 255)  # empty area stays background


def test_hidden_layers_are_not_rendered():
    page = Page(width=50, height=50, background="#ffffff")
    layer = page.add_layer("hidden")
    layer.strokes.append(Stroke.from_xy([(0, 25), (50, 25)], style=StrokeStyle(width=10)))
    layer.visible = False
    img = decode(render_page_png(page))
    assert img.getpixel((25, 25)) == (255, 255, 255)


def test_highlighter_is_translucent():
    page = Page(width=100, height=100, background="#ffffff")
    page.layers[0].add(
        Stroke.from_xy([(10, 50), (90, 50)], style=StrokeStyle.highlighter(width=20.0))
    )
    img = decode(render_page_png(page))
    r, g, b = img.getpixel((50, 50))
    # #ffe066 at 0.35 opacity over white: yellow-ish but far from full saturation.
    assert b > 150, "highlighter should blend with the white background, not overwrite it"
    assert (r, g, b) != (255, 255, 255)


def test_region_and_scale():
    page = Page(width=200, height=200, background="#ffffff")
    page.layers[0].add(Stroke.from_xy([(100, 100)], style=StrokeStyle(color="#000000", width=8)))
    img = decode(render_page_png(page, region=BoundingBox(50, 50, 150, 150), scale=2.0))
    assert img.size == (200, 200)
    r, g, b = img.getpixel((100, 100))  # page (100,100) -> region center
    assert r < 100 and g < 100 and b < 100


def test_view_page_tool_png_format():
    canvas = Canvas()
    call_tool(canvas, "add_stroke", {"points": [[10, 10], [50, 50]]})
    result = call_tool(canvas, "view_page", {"format": "png"})
    assert result["format"] == "png"
    img = decode(base64.b64decode(result["data"]))
    assert img.size == (1000, 1414)
    # default remains svg
    assert call_tool(canvas, "view_page")["format"] == "svg"
