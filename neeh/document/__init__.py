"""L0 substrate: ink at rest — layers, pages, documents, and JSON snapshots."""
from neeh.document.document import FORMAT_VERSION, Document
from neeh.document.layer import Layer
from neeh.document.page import DEFAULT_PAGE_HEIGHT, DEFAULT_PAGE_WIDTH, Page

__all__ = [
    "DEFAULT_PAGE_HEIGHT",
    "DEFAULT_PAGE_WIDTH",
    "Document",
    "FORMAT_VERSION",
    "Layer",
    "Page",
]
