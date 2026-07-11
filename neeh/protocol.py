"""Independently versioned public protocol identifiers.

The Python package follows SemVer, but wire formats and persistence profiles
need their own compatibility clocks.  Hosts should negotiate these values
instead of deriving protocol support from ``neeh.__version__``.
"""
from __future__ import annotations

from typing import Final

INK_CONTEXT_VERSION: Final = "ink-context/v0"
# Promoted 2026-07-10 from ink-context/v1-draft after the M1/M2/real-ink/H7
# evidence chain — spec/ink-context-format-v1.md is normative.
INK_CONTEXT_V1_VERSION: Final = "ink-context/v1"
# Retired draft identifier, kept so old payloads can be recognized.
INK_CONTEXT_V1_DRAFT_VERSION: Final = "ink-context/v1-draft"
TOOL_SURFACE_VERSION: Final = "neeh-tools/v1"
UIM_PROFILE_VERSION: Final = "neeh-uim/v1"

_PROTOCOL_VERSIONS: Final = {
    "ink_context": INK_CONTEXT_VERSION,
    "ink_context_v1": INK_CONTEXT_V1_VERSION,
    "tool_surface": TOOL_SURFACE_VERSION,
    "persistence_profile": UIM_PROFILE_VERSION,
}


def protocol_versions() -> dict[str, str]:
    """Return a JSON-serializable copy of the supported protocol manifest."""

    return dict(_PROTOCOL_VERSIONS)


__all__ = [
    "INK_CONTEXT_V1_DRAFT_VERSION",
    "INK_CONTEXT_VERSION",
    "TOOL_SURFACE_VERSION",
    "UIM_PROFILE_VERSION",
    "protocol_versions",
]
