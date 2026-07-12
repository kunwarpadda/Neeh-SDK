"""PNG rasterizer — the perception backend for multimodal models.

Optional: needs Pillow (`pip install "neeh[png]"`). Mirrors the reference SVG
renderer's semantics (constant stroke width, round caps, butt-capped
translucent highlighters) so both backends show agents the same page.
Renders supersampled and downscales for antialiasing.
"""
from __future__ import annotations

import io
from typing import Optional

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        'neeh.rendering.png needs Pillow — install it with `pip install "neeh[png]"`'
    ) from exc

from neeh.document import Page
from neeh.ink import BoundingBox, Brush, Stroke

_SUPERSAMPLE = 2


def _rgba(color: str, opacity: float) -> tuple[int, int, int, int]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16), round(opacity * 255))


def _draw_stroke(draw: "ImageDraw.ImageDraw", stroke: Stroke, origin: tuple[float, float],
                 ss: float) -> None:
    style = stroke.style
    color = _rgba(style.color, style.opacity)
    width = max(style.width * ss, 1.0)
    pts = [((p.x - origin[0]) * ss, (p.y - origin[1]) * ss) for p in stroke.points]

    # Constant-brush rendering is independent of capture direction. Canonical
    # point order removes tiny ImageDraw/LANCZOS direction artifacts, allowing
    # controlled experiments whose final raster is truly identical while the
    # underlying trajectory runs in the opposite direction.
    if len(pts) > 1 and pts[-1] < pts[0]:
        pts.reverse()

    if len(pts) == 1:
        x, y = pts[0]
        r = width / 2
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)
        return

    draw.line(pts, fill=color, width=round(width), joint="curve")
    if style.brush is not Brush.HIGHLIGHTER:  # round caps; highlighter stays butt-capped
        r = width / 2
        for x, y in (pts[0], pts[-1]):
            draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def render_page_png(
    page: Page,
    region: Optional[BoundingBox] = None,
    scale: float = 1.0,
) -> bytes:
    """Rasterize a page (or a region of it) to PNG bytes.

    `scale` maps page units to output pixels: the default page becomes a
    1000x1414 image at scale 1.0.
    """
    region = region or page.rect
    out_w = max(round(region.width * scale), 1)
    out_h = max(round(region.height * scale), 1)
    ss = scale * _SUPERSAMPLE

    base = Image.new("RGBA", (max(round(region.width * ss), 1), max(round(region.height * ss), 1)))
    ImageDraw.Draw(base).rectangle([0, 0, base.width, base.height],
                                   fill=_rgba(page.background, 1.0))
    origin = (region.min_x, region.min_y)

    for layer in page.layers:
        if not layer.visible:
            continue
        for stroke in layer.strokes:
            if not region.intersects(stroke.bbox.expanded(stroke.style.width)):
                continue
            if stroke.style.opacity < 1.0:
                # Translucent ink must blend with what's below it, and Pillow's
                # draw writes RGBA verbatim — composite through an overlay.
                overlay = Image.new("RGBA", base.size)
                _draw_stroke(ImageDraw.Draw(overlay), stroke, origin, ss)
                base = Image.alpha_composite(base, overlay)
            else:
                _draw_stroke(ImageDraw.Draw(base), stroke, origin, ss)

    final = base.convert("RGB").resize((out_w, out_h), Image.LANCZOS)
    buf = io.BytesIO()
    final.save(buf, format="PNG")
    return buf.getvalue()
