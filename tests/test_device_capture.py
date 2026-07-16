"""Experimental device-capture contract and importer."""
from __future__ import annotations

import copy
import json
import math
import zipfile
from pathlib import Path

import pytest

from neeh.adapters.device_capture import (
    DEVICE_CAPTURE_VERSION,
    DeviceCaptureError,
    convert_device_capture,
    import_device_capture,
    load_device_capture,
    validate_device_capture,
)
from neeh.canvas.events import EVENT_KINDS
from neeh.ink import Author
from neeh.protocol import experimental_protocol_versions, protocol_versions

FIXTURES = Path(__file__).resolve().parent.parent / "spec" / "fixtures"
CAPTURE = FIXTURES / "neeh-device-capture-v1.session.json"
SCHEMA = FIXTURES / "neeh-device-capture-v1.schema.json"


def _payload() -> dict:
    return json.loads(CAPTURE.read_text(encoding="utf-8"))


def test_fixture_validates_and_reconstructs_visible_erased_and_crossed_ink() -> None:
    payload = _payload()
    validate_device_capture(payload)
    imported = import_device_capture(payload)

    assert imported.capture == payload
    assert [page.id for page in imported.document.pages] == ["pg_notes", "pg_more"]
    visible = {
        stroke.id for page in imported.document.pages for stroke in page.all_strokes()
    }
    assert visible == set(payload["ground_truth"]["visible_stroke_ids"])
    assert imported.event_log.recover("st_erased").id == "st_erased"

    # A cross-out is retained later ink, not a delete operation.
    assert imported.event_log.recover("st_crossed") is None
    assert imported.event_log.recover("st_crossout") is None
    assert {"st_crossed", "st_crossout"} <= visible

    # Explicit undo/redo remains in the append-only log and redo restores it.
    assert [event.kind for event in imported.event_log.for_stroke("st_rewrite")] == [
        "add", "undo", "redo",
    ]
    assert imported.event_log.replay()["st_rewrite"][1].id == "st_rewrite"


def test_import_preserves_epoch_and_relative_time_axes() -> None:
    payload = _payload()
    imported = import_device_capture(payload)
    keep = imported.document.page("pg_notes").find("st_keep")[1]

    assert keep.created_at_ms == payload["session"]["started_at_ms"] + 10
    assert [point.t_ms for point in keep.points] == [0, 15]
    assert imported.event_log.for_stroke("st_keep")[0].at_ms == (
        payload["session"]["started_at_ms"] + 25
    )
    # Raw Android monotonic time/orientation are retained losslessly.
    raw_point = imported.capture["events"][1]["point"]
    assert raw_point["event_time_ms"] == 4_000_010
    assert raw_point["orientation_rad"] == 0.1


def test_android_cardinal_orientation_projects_to_the_expected_tilt_axis() -> None:
    payload = _payload()
    # The first stroke is not referenced by a later snapshot, so its two raw
    # sample orientations can be changed independently for this conversion test.
    payload["events"][1]["point"]["orientation_rad"] = 0.0
    payload["events"][2]["point"]["orientation_rad"] = math.pi / 2
    keep = import_device_capture(payload).document.page("pg_notes").find("st_keep")[1]

    assert keep.points[0].tilt_x == pytest.approx(math.degrees(0.2))
    assert keep.points[0].tilt_y == pytest.approx(0.0, abs=1e-10)
    assert keep.points[1].tilt_x == pytest.approx(0.0, abs=1e-10)
    assert keep.points[1].tilt_y == pytest.approx(math.degrees(0.25))


def test_argb_and_app_authorship_map_to_sdk_without_losing_raw_values() -> None:
    imported = load_device_capture(CAPTURE)
    stroke = imported.document.page("pg_more").find("st_page2")[1]

    assert stroke.author is Author.AGENT
    assert stroke.style.color == "#0057B8"
    assert stroke.style.opacity == pytest.approx(0xCC / 255)
    begin = next(event for event in imported.capture["events"] if event["event_id"] == "raw_page2_begin")
    assert begin["author"] == "app"
    assert begin["style"]["color_argb"] == "#CC0057B8"


def test_page_lifecycle_uses_the_existing_event_log_kind() -> None:
    imported = load_device_capture(CAPTURE)
    page_events = [event for event in imported.event_log.events if event.kind == "page"]

    assert "page" in EVENT_KINDS
    assert [event.label for event in page_events] == ["page_create", "page_change"]
    assert page_events[1].meta["to_page_id"] == "pg_more"


def test_page_delete_removes_final_page_but_keeps_its_ink_recoverable() -> None:
    payload = _payload()
    page2_begin = next(e for e in payload["events"] if e["event_id"] == "raw_page2_begin")
    page2_points = [
        e["point"] for e in payload["events"]
        if e.get("stroke_id") == "st_page2" and e["kind"] == "stroke_sample"
    ]
    payload["events"].append({
        "seq": 29,
        "event_id": "raw_page_delete",
        "kind": "page_delete",
        "t_ms": 600,
        "page_id": "pg_more",
        "page": copy.deepcopy(payload["pages"][1]),
        "removed": [{
            "stroke_id": "st_page2",
            "layer_id": page2_begin["layer_id"],
            "author": page2_begin["author"],
            "tool": page2_begin["tool"],
            "style": copy.deepcopy(page2_begin["style"]),
            "created_at_ms": page2_begin["created_at_ms"],
            "points": copy.deepcopy(page2_points),
        }],
        "added": [],
    })

    imported = import_device_capture(payload)

    assert [page.id for page in imported.document.pages] == ["pg_notes"]
    assert imported.event_log.events[-1].kind == "page"
    assert imported.event_log.events[-1].label == "page_delete"
    assert imported.event_log.recover("st_page2").id == "st_page2"


def test_validator_rejects_non_contiguous_events_and_unrecoverable_delete() -> None:
    payload = _payload()
    payload["events"][3]["seq"] = 99
    with pytest.raises(DeviceCaptureError, match="contiguous"):
        validate_device_capture(payload)

    payload = _payload()
    delete = next(event for event in payload["events"] if event["kind"] == "stroke_delete")
    delete["removed"] = []
    with pytest.raises(DeviceCaptureError, match="non-empty removed"):
        validate_device_capture(payload)


def test_loader_accepts_direct_json_directory_and_canonical_zip(tmp_path: Path) -> None:
    directory = tmp_path / "bundle-dir"
    directory.mkdir()
    (directory / "session.events.json").write_bytes(CAPTURE.read_bytes())
    assert load_device_capture(directory).document.page("pg_notes") is not None

    archive_path = tmp_path / "capture.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("session.tink", b"TINK fixture placeholder")
        archive.writestr("session.events.json", CAPTURE.read_bytes())
    assert load_device_capture(archive_path).event_log.recover("st_erased") is not None


def test_zip_loader_rejects_missing_or_extra_bundle_members(tmp_path: Path) -> None:
    for name, members in (
        ("missing.zip", {"session.events.json": CAPTURE.read_bytes()}),
        (
            "extra.zip",
            {
                "session.tink": b"TINK",
                "session.events.json": CAPTURE.read_bytes(),
                "notes.txt": b"not part of the canonical bundle",
            },
        ),
    ):
        path = tmp_path / name
        with zipfile.ZipFile(path, "w") as archive:
            for member, content in members.items():
                archive.writestr(member, content)
        with pytest.raises(DeviceCaptureError, match="exactly session.tink"):
            load_device_capture(path)


def test_converter_writes_a_complete_neeh_session(tmp_path: Path) -> None:
    destination = tmp_path / "derived.session.json"
    imported = convert_device_capture(CAPTURE, destination)
    restored = imported.canvas.load_session(destination)

    assert restored.events.recover("st_erased") is not None
    assert {stroke.id for stroke in restored.document.page("pg_notes").all_strokes()} == {
        "st_keep", "st_rewrite", "st_crossed", "st_crossout",
    }


def test_schema_and_protocol_discovery_keep_capture_experimental() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["properties"]["schema"]["const"] == DEVICE_CAPTURE_VERSION
    assert experimental_protocol_versions()["device_capture"] == DEVICE_CAPTURE_VERSION
    assert DEVICE_CAPTURE_VERSION not in protocol_versions().values()
