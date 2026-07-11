"""Tool registry: the agent-facing surface, described by JSON Schema.

Every tool is registered with a name, description, and parameter schema so
MCP and model integrations can expose the surface mechanically. The registry
is the authoritative tool manifest.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Optional

from neeh.canvas import Canvas
from neeh.protocol import TOOL_SURFACE_VERSION

ToolHandler = Callable[..., dict[str, Any]]

_REGISTRY: dict[str, "ToolSpec"] = {}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema for the arguments object
    handler: ToolHandler


def tool(name: str, description: str, parameters: dict[str, Any]) -> Callable[[ToolHandler], ToolHandler]:
    def decorator(fn: ToolHandler) -> ToolHandler:
        if name in _REGISTRY:
            raise ValueError(f"tool {name!r} is already registered")
        normalized_parameters = deepcopy(parameters)
        normalized_parameters.setdefault("additionalProperties", False)
        _REGISTRY[name] = ToolSpec(
            name=name,
            description=description,
            parameters=normalized_parameters,
            handler=fn,
        )
        return fn

    return decorator


def get_tool(name: str) -> ToolSpec:
    if name not in _REGISTRY:
        known = ", ".join(sorted(_REGISTRY))
        raise KeyError(f"unknown tool {name!r} (known tools: {known})")
    return _REGISTRY[name]


def all_tools() -> list[ToolSpec]:
    return list(_REGISTRY.values())


def tool_schemas() -> list[dict[str, Any]]:
    """Tool manifest in Claude-API / MCP shape."""
    return [
        {
            "name": spec.name,
            "description": spec.description,
            "input_schema": deepcopy(spec.parameters),
        }
        for spec in _REGISTRY.values()
    ]


def tool_manifest() -> dict[str, Any]:
    """Return the versioned, JSON-serializable tool-surface manifest."""

    return {"protocol": TOOL_SURFACE_VERSION, "tools": tool_schemas()}


def call_tool(canvas: Canvas, name: str, arguments: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    if arguments is None:
        arguments = {}
    elif not isinstance(arguments, dict):
        raise ValueError("tool arguments must be an object")
    return get_tool(name).handler(canvas, **arguments)
