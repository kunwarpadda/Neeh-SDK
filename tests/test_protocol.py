import json

from neeh.protocol import (
    INK_CONTEXT_VERSION,
    TOOL_SURFACE_VERSION,
    UIM_PROFILE_VERSION,
    protocol_versions,
)
from neeh.tools import tool_manifest


def test_protocol_identifiers_are_independently_versioned() -> None:
    assert protocol_versions() == {
        "ink_context": "ink-context/v0",
        "tool_surface": "neeh-tools/v1",
        "persistence_profile": "neeh-uim/v1",
    }
    assert INK_CONTEXT_VERSION.startswith("ink-context/")
    assert TOOL_SURFACE_VERSION.startswith("neeh-tools/")
    assert UIM_PROFILE_VERSION.startswith("neeh-uim/")


def test_protocol_manifest_is_json_serializable_and_defensive() -> None:
    manifest = protocol_versions()
    manifest["ink_context"] = "changed-by-caller"

    assert json.loads(json.dumps(protocol_versions())) == protocol_versions()
    assert protocol_versions()["ink_context"] == INK_CONTEXT_VERSION


def test_tool_manifest_carries_its_protocol_version() -> None:
    manifest = tool_manifest()

    assert manifest["protocol"] == TOOL_SURFACE_VERSION
    assert {tool["name"] for tool in manifest["tools"]} >= {
        "view_page",
        "get_strokes",
        "add_stroke",
        "undo",
        "redo",
    }
    assert json.loads(json.dumps(manifest)) == manifest
    assert all(tool["input_schema"]["additionalProperties"] is False for tool in manifest["tools"])

    manifest["tools"][0]["input_schema"]["type"] = "mutated"
    assert tool_manifest()["tools"][0]["input_schema"]["type"] == "object"
