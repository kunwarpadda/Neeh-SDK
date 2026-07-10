"""Neeh SDK — a common foundation for building AI-powered notebook,
whiteboard, and handwriting applications."""
from neeh.canvas import Canvas, History, Selection, Viewport
from neeh.context import (
    DEFAULT_GRID_LONG_EDGE,
    DEFAULT_MAX_POINTS_PER_STROKE,
    DEFAULT_MAX_STROKES,
    DEFAULT_RESAMPLE_GRID_STEP,
    InkContextError,
    SemanticItem,
    build_ink_context,
    build_ink_context_v1,
    build_ink_paths,
)
from neeh.document import Document, Layer, Page
from neeh.ink import Author, BoundingBox, Brush, Point, Stroke, StrokeStyle
from neeh.rendering import Renderer, SvgRenderer, render_page_svg

__version__ = "0.1.0.dev0"

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
    "build_ink_paths",
    "render_page_svg",
]
