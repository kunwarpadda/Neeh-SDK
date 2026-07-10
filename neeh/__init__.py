"""Neeh SDK — a common foundation for building AI-powered notebook,
whiteboard, and handwriting applications."""
from neeh.canvas import Canvas, History, Selection, Viewport
from neeh.document import Document, Layer, Page
from neeh.ink import Author, BoundingBox, Brush, Point, Stroke, StrokeStyle
from neeh.rendering import Renderer, SvgRenderer, render_page_svg

__version__ = "0.1.0.dev0"

__all__ = [
    "Author",
    "BoundingBox",
    "Brush",
    "Canvas",
    "Document",
    "History",
    "Layer",
    "Page",
    "Point",
    "Renderer",
    "Selection",
    "Stroke",
    "StrokeStyle",
    "SvgRenderer",
    "Viewport",
    "render_page_svg",
]
