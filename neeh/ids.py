"""Stable, prefixed identifiers.

Every addressable object (stroke, layer, page, document) gets an id that
survives edits, transforms, and serialization round-trips. Stable ids are
what let an agent say "highlight st_3f9a2c" and have it still mean something
after the user scrolls, moves, or re-renders — the ink equivalent of
line-number drift in coding agents.
"""
from __future__ import annotations

import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"
