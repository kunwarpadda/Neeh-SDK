"""Neeh SDK — a common foundation for building AI-powered notebook,
whiteboard, and handwriting applications."""
from neeh.canvas import Canvas, History, Selection, Viewport
from neeh.context import (
    DEFAULT_GRID_LONG_EDGE,
    DEFAULT_MAX_POINTS_PER_STROKE,
    DEFAULT_MAX_STROKES,
    DEFAULT_RESAMPLE_GRID_STEP,
    InkContextError,
    ParsedInkPath,
    SemanticItem,
    build_ink_context,
    build_ink_context_v1,
    build_ink_index,
    build_ink_paths,
    parse_ink_paths,
)
from neeh.document import Document, Layer, Page
from neeh.ink import Author, BoundingBox, Brush, Point, Stroke, StrokeStyle
from neeh.rendering import Renderer, SvgRenderer, render_page_ascii, render_page_svg

# Single source of truth is pyproject.toml; read the installed metadata so the
# runtime version can never drift from the published one. The fallback covers
# running from an uninstalled checkout.
try:
    from importlib.metadata import PackageNotFoundError, version as _dist_version

    __version__ = _dist_version("neeh")
except PackageNotFoundError:  # pragma: no cover - uninstalled checkout
    __version__ = "0.2.0"
del _dist_version, PackageNotFoundError

__all__ = [
    "Author",
    "BoundingBox",
    "Brush",
    "Canvas",
    "DEFAULT_GRID_LONG_EDGE",
    "DEFAULT_MAX_POINTS_PER_STROKE",
    "DEFAULT_MAX_STROKES",
    "DEFAULT_RESAMPLE_GRID_STEP",
    "Document",
    "History",
    "InkContextError",
    "Layer",
    "Page",
    "ParsedInkPath",
    "Point",
    "Renderer",
    "Selection",
    "SemanticItem",
    "Stroke",
    "StrokeStyle",
    "SvgRenderer",
    "Viewport",
    "build_ink_context",
    "build_ink_context_v1",
    "build_ink_index",
    "build_ink_paths",
    "parse_ink_paths",
    "render_page_ascii",
    "render_page_svg",
]
