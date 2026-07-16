"""Protocol conformance: live SDK output validates against spec/fixtures schemas.

A dependency-free subset validator keeps the core zero-dependency; external
integrators should point any real JSON Schema validator at the same files.
Covered subset: type, const, enum, required, properties, additionalProperties
(documentation-only here since all schemas allow them), items, minItems,
minimum, and local $ref into $defs.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from neeh import Canvas
from neeh.agents import ANALYSIS_OPERATIONS, REDUCER_TASKS, analyze_ink, reduce_ink
from neeh.canvas import EventLog
from neeh.ink import Author

FIXTURES = Path(__file__).resolve().parent.parent / "spec" / "fixtures"

_TYPES = {
    "object": dict, "array": list, "string": str,
    "integer": int, "number": (int, float), "boolean": bool, "null": type(None),
}


def _check(value: Any, schema: dict[str, Any], root: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []
    if "$ref" in schema:
        ref = schema["$ref"]
        assert ref.startswith("#/"), f"only local refs supported: {ref}"
        target: Any = root
        for part in ref[2:].split("/"):
            target = target[part]
        return _check(value, target, root, path)
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}, got {value!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} not in enum")
    if "type" in schema:
        expected = schema["type"]
        allowed = tuple(
            _TYPES[t] for t in ([expected] if isinstance(expected, str) else expected)
        )
        flat: tuple = ()
        for a in allowed:
            flat += a if isinstance(a, tuple) else (a,)
        if isinstance(value, bool) and bool not in flat:
            errors.append(f"{path}: bool is not {expected}")
        elif not isinstance(value, flat):
            errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required {req!r}")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                errors.extend(_check(value[key], sub, root, f"{path}.{key}"))
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, item in enumerate(value):
                errors.extend(_check(item, schema["items"], root, f"{path}[{i}]"))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: {value} < minimum {schema['minimum']}")
    return errors


def validate(payload: Any, schema_name: str) -> None:
    schema = json.loads((FIXTURES / schema_name).read_text())
    errors = _check(payload, schema, schema)
    assert not errors, f"{schema_name}:\n" + "\n".join(errors)


def _scene() -> Canvas:
    canvas = Canvas()
    a = canvas.add_stroke([(100, 100), (160, 100)], author=Author.USER, created_at_ms=1_000_000)
    b = canvas.add_stroke([(100, 102), (160, 98)], author=Author.USER, created_at_ms=1_005_000)
    canvas.group([a.id, b.id], label="figure")
    canvas.erase([b.id])
    canvas.undo()
    return canvas


# --- golden fixtures validate against their schemas -------------------------

@pytest.mark.parametrize("fixture,schema", [
    ("neeh-device-capture-v1.session.json", "neeh-device-capture-v1.schema.json"),
    ("ink-analysis-v1.latest_mark.json", "ink-analysis-v1.envelope.schema.json"),
    ("ink-analysis-v1.connector_candidates.json", "ink-analysis-v1.envelope.schema.json"),
    ("ink-analysis-v1.orientation.json", "ink-analysis-v1.envelope.schema.json"),
    ("ink-analysis-v1.recorded_groups.json", "ink-analysis-v1.envelope.schema.json"),
    ("ink-analysis-v1.reduce_recent_changes.json", "ink-analysis-v1.reducer.schema.json"),
    ("ink-eventlog-v1.compact.json", "ink-eventlog-v1.compact.schema.json"),
    ("ink-eventlog-v1.snapshot.json", "ink-eventlog-v1.snapshot.schema.json"),
])
def test_golden_fixture_validates(fixture: str, schema: str) -> None:
    validate(json.loads((FIXTURES / fixture).read_text()), schema)


# --- live output validates against the schemas -------------------------------

def test_every_analyzer_operation_conforms_to_envelope_schema() -> None:
    canvas = _scene()
    ids = [s.id for layer in canvas.page.layers for s in layer.strokes]
    for op in ANALYSIS_OPERATIONS:
        kwargs: dict[str, Any] = {}
        if op in ("creation_order", "stroke_dynamics", "endpoints"):
            kwargs["stroke_ids"] = ids
        if op == "containment":
            kwargs["region"] = [0, 0, 500, 500]
        validate(analyze_ink(canvas, op, **kwargs), "ink-analysis-v1.envelope.schema.json")


def test_every_reducer_task_conforms_to_reducer_schema() -> None:
    canvas = _scene()
    for task in REDUCER_TASKS:
        validate(reduce_ink(canvas, task), "ink-analysis-v1.reducer.schema.json")


def test_live_event_log_conforms_to_both_schemas() -> None:
    canvas = _scene()
    validate(canvas.events.to_dict(), "ink-eventlog-v1.compact.schema.json")
    validate(canvas.events.to_snapshot(), "ink-eventlog-v1.snapshot.schema.json")


# --- compatibility policy: unknown fields are ignored, never fatal ----------

def test_unknown_fields_are_ignored_on_read() -> None:
    canvas = _scene()
    snap = canvas.events.to_snapshot()
    snap["future_envelope_field"] = {"v": 2}
    snap["events"][0]["future_event_field"] = "x"
    snap["events"][0]["added"][0]["future_pair_field"] = 1

    restored = EventLog.from_snapshot(snap)
    assert len(restored) == len(canvas.events)

    session = canvas.session_snapshot()
    session["future"] = True
    session["document"]["future"] = 1
    assert Canvas.from_session(session) is not None


def test_snapshot_round_trip_is_stable_under_reserialization() -> None:
    canvas = _scene()
    once = EventLog.from_snapshot(canvas.events.to_snapshot()).to_snapshot()
    twice = EventLog.from_snapshot(once).to_snapshot()
    assert once == twice
