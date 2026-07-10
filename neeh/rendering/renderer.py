"""Renderer protocol. The app's Vulkan path, a future CPU rasterizer, and the
reference SVG renderer are all interchangeable behind this."""
from __future__ import annotations

from typing import Optional, Protocol, Union

from neeh.document import Page
from neeh.ink import BoundingBox


class Renderer(Protocol):
    def render_page(
        self,
        page: Page,
        region: Optional[BoundingBox] = None,
        scale: float = 1.0,
    ) -> Union[str, bytes]: ...
