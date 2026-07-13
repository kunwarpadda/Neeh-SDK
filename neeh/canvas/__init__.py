"""The editing session: canvas, viewport, selection, undo history."""
from neeh.canvas.canvas import SESSION_VERSION, Canvas
from neeh.canvas.events import (
    EVENTLOG_VERSION,
    DocumentEvent,
    EventLog,
)
from neeh.canvas.history import History, StrokeEdit
from neeh.canvas.selection import Selection
from neeh.canvas.viewport import Viewport

__all__ = [
    "Canvas",
    "SESSION_VERSION",
    "DocumentEvent",
    "EventLog",
    "EVENTLOG_VERSION",
    "History",
    "Selection",
    "StrokeEdit",
    "Viewport",
]
