"""L1 perception: reference rendering so agents can see pages anywhere."""
from neeh.rendering.renderer import Renderer
from neeh.rendering.svg import SvgRenderer, render_page_svg

__all__ = ["Renderer", "SvgRenderer", "render_page_svg"]
