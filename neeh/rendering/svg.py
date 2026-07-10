"""Reference SVG renderer — dependency-free, runs anywhere.

This is the perception fallback so agents can "see" a page on any host
(server, CI, laptop — no tablet). PNG tiles for multimodal models come next
(optional Pillow backend); app-quality low-latency rendering stays in the
Neeh app.
"""
from __future__ import annotations

from typing import Optional

from neeh.document import Page
from neeh.ink import BoundingBox, Brush, Stroke


def _fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _stroke_svg(stroke: Stroke) -> str:
    style = stroke.style
    opacity = f' opacity="{_fmt(style.opacity)}"' if style.opacity < 1.0 else ""
    if len(stroke.points) == 1:
        p = stroke.points[0]
        return (
            f'<circle cx="{_fmt(p.x)}" cy="{_fmt(p.y)}" r="{_fmt(style.width / 2)}"'
            f' fill="{style.color}"{opacity}/>'
        )
    pts = " ".join(f"{_fmt(p.x)},{_fmt(p.y)}" for p in stroke.points)
    linecap = "butt" if style.brush is Brush.HIGHLIGHTER else "round"
    return (
        f'<polyline points="{pts}" fill="none" stroke="{style.color}"'
        f' stroke-width="{_fmt(style.width)}" stroke-linecap="{linecap}"'
        f' stroke-linejoin="round"{opacity}/>'
    )


class SvgRenderer:
    def render_page(
        self,
        page: Page,
        region: Optional[BoundingBox] = None,
        scale: float = 1.0,
    ) -> str:
        region = region or page.rect
        w = max(region.width, 1e-6) * scale
        h = max(region.height, 1e-6) * scale
        parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(w)}" height="{_fmt(h)}"'
            f' viewBox="{_fmt(region.min_x)} {_fmt(region.min_y)} {_fmt(region.width)} {_fmt(region.height)}">',
            f'<rect x="{_fmt(region.min_x)}" y="{_fmt(region.min_y)}" width="{_fmt(region.width)}"'
            f' height="{_fmt(region.height)}" fill="{page.background}"/>',
        ]
        for layer in page.layers:
            if not layer.visible:
                continue
            for stroke in layer.strokes:
                if region.intersects(stroke.bbox.expanded(stroke.style.width)):
                    parts.append(_stroke_svg(stroke))
        parts.append("</svg>")
        return "".join(parts)


def render_page_svg(page: Page, region: Optional[BoundingBox] = None, scale: float = 1.0) -> str:
    return SvgRenderer().render_page(page, region=region, scale=scale)
