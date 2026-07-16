#!/usr/bin/env python3
"""Deterministic regression report for a real-shaped device capture.

This runner is intentionally separate from the synthetic Move 3 harness.  It
measures the SDK path exercised by an exported ``neeh-device-capture/v1``
session without invoking a model or changing ``ink-context/v1``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

# Make ``python benchmarks/real_capture_regression.py`` work from any cwd.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.fspath(ROOT))

from neeh.adapters.device_capture import load_device_capture
from neeh.agents.analyzers import analyze_ink
from neeh.agents.iai import InkAgentInterface, build_observation_workspace
from neeh.agents.reducers import reduce_ink
from neeh.agents.timeline import build_ink_timeline
from neeh.context import build_ink_context_v1, build_ink_index


REPORT_VERSION = "neeh-real-capture-regression/v1"
DEFAULT_CAPTURE = (
    ROOT / "spec" / "fixtures" / "neeh-device-capture-v1.session.json"
)
_TASK = "Which ink was revised or replaced?"


def _serialized_chars(value: Any) -> int:
    return len(json.dumps(value, separators=(",", ":"), sort_keys=True))


def _estimated_tokens(chars: int) -> int:
    """Cheap, explicit reporting heuristic: one token per four JSON chars."""
    return (chars + 3) // 4


def _visible_ids(imported: Any) -> set[str]:
    return {
        stroke.id
        for page in imported.document.pages
        for stroke in page.all_strokes(visible_only=True)
    }


def _raw_evidence(capture: dict[str, Any]) -> dict[str, Any]:
    points = [
        event["point"]
        for event in capture["events"]
        if event["kind"] == "stroke_sample"
    ]
    signal_counts = {
        name: sum(name in point for point in points)
        for name in (
            "pressure",
            "tilt_rad",
            "orientation_rad",
            "event_time_ms",
        )
    }
    return {
        "raw_sample_count": len(points),
        "signal_sample_counts": signal_counts,
        "timestamps_available": bool(points)
        and all("t_ms" in point for point in points),
    }


def _history_recovery(imported: Any, visible_ids: set[str]) -> dict[str, Any]:
    ground_truth = imported.capture.get("ground_truth") or {}
    erased_ids = set(ground_truth.get("erased_stroke_ids") or [])
    if not erased_ids:
        erased_ids = {
            stroke_id
            for event in imported.event_log.events
            if event.kind == "erase"
            for stroke_id in event.removed_ids
        }

    replaced_ids = set(ground_truth.get("replaced_stroke_ids") or [])
    replaced_ids.update(ground_truth.get("restored_stroke_ids") or [])
    if not replaced_ids:
        replaced_ids = {
            stroke_id
            for event in imported.event_log.events
            if event.kind != "erase"
            for stroke_id in event.removed_ids
            if stroke_id in visible_ids
        }

    erased_recovered = {
        stroke_id
        for stroke_id in erased_ids
        if imported.event_log.recover(stroke_id) is not None
    }
    # A replaced/restored stroke is live, so EventLog.recover correctly returns
    # None.  Its historical state is instead the immutable removed snapshot.
    replaced_snapshot_ids = {
        stroke.id
        for event in imported.event_log.events
        for _, stroke in event.removed
        if stroke.id in replaced_ids
    }
    replaced_recovered = replaced_snapshot_ids & visible_ids
    candidate_ids = erased_ids | replaced_ids
    recovered_ids = erased_recovered | replaced_recovered
    return {
        "applicable": bool(candidate_ids),
        "erased_ids": sorted(erased_ids),
        "erased_recovered_ids": sorted(erased_recovered),
        "replaced_or_restored_ids": sorted(replaced_ids),
        "replaced_or_restored_recovered_ids": sorted(replaced_recovered),
        "recovered_ids": sorted(recovered_ids),
        "complete": candidate_ids <= recovered_ids,
    }


def evaluate_capture(source: str | Path) -> dict[str, Any]:
    """Import one capture and return all real-ink M3 regression measurements."""
    capture_path = Path(source).resolve()
    imported = load_device_capture(capture_path)
    visible_ids = _visible_ids(imported)
    raw_evidence = _raw_evidence(imported.capture)
    page_reports: list[dict[str, Any]] = []
    deterministic_measurements = 0
    revision_evidence = 0
    revision_provenance = 0
    analyzer_first_pages = 0
    retrieval_calls = 0
    raw_detail_calls = 0

    for page_index, page in enumerate(imported.document.pages):
        imported.canvas.goto_page(page_index)
        context = build_ink_context_v1(
            imported.canvas,
            stroke_bboxes=True,
            stroke_hints=True,
        )
        index = build_ink_index(imported.canvas)
        timeline = build_ink_timeline(page, event_log=imported.event_log)
        latest = analyze_ink(imported.canvas, "latest_mark")
        revisions = reduce_ink(imported.canvas, "revisions", limit=8)
        workspace = build_observation_workspace(
            imported.canvas,
            _TASK,
            policy="active-index",
        )
        interface = InkAgentInterface(
            imported.canvas,
            _TASK,
            policy="active-index",
        )
        interface_latest = interface.call(
            "analyze_ink", {"operation": "latest_mark"}
        )
        latest_record = interface_latest.get("latest")
        if latest_record is not None:
            interface.call(
                "get_ink",
                {"detail": "bboxes", "stroke_ids": [latest_record["id"]]},
            )
        telemetry = interface.telemetry()

        analysis = workspace.get("analysis")
        if (
            isinstance(analysis, dict)
            and analysis.get("deterministic") is True
            and analysis.get("task") == "revisions"
        ):
            analyzer_first_pages += 1
        if latest.get("deterministic") is True:
            deterministic_measurements += 1
        revision_items = revisions.get("revisions") or []
        revision_evidence += len(revision_items)
        revision_provenance += sum(
            isinstance(item.get("provenance"), dict) for item in revision_items
        )
        retrieval_calls += telemetry["perception_actions"]
        raw_detail_calls += telemetry["action_types"].count("get_ink")

        context_chars = _serialized_chars(context)
        page_reports.append(
            {
                "page_id": page.id,
                "context_chars": context_chars,
                "estimated_tokens": _estimated_tokens(context_chars),
                "selected_stroke_count": context["ink"]["stroke_count"],
                "included_stroke_count": context["ink"]["included_stroke_count"],
                "index_included_stroke_count": index["included_stroke_count"],
                "timeline_history_complete": timeline["history_complete"],
                "timeline_moment_count": timeline["moment_count"],
                "timeline_erased_stroke_count": sum(
                    len(moment["erased_ids"]) for moment in timeline["moments"]
                ),
                "latest_stroke_id": (
                    None if latest["latest"] is None else latest["latest"]["id"]
                ),
                "revision_evidence_count": len(revision_items),
                "workspace_analysis": (
                    None
                    if not isinstance(analysis, dict)
                    else analysis.get("task") or analysis.get("operation")
                ),
                "workspace_bootstrap_chars": workspace["bootstrap_chars"],
                "retrieval_calls": telemetry["perception_actions"],
                "retrieval_action_types": telemetry["action_types"],
            }
        )

    context_chars = sum(page["context_chars"] for page in page_reports)
    selected_strokes = sum(page["selected_stroke_count"] for page in page_reports)
    included_strokes = sum(page["included_stroke_count"] for page in page_reports)
    index_included = sum(
        page["index_included_stroke_count"] for page in page_reports
    )
    history_recovery = _history_recovery(imported, visible_ids)
    timeline_complete = bool(page_reports) and all(
        page["timeline_history_complete"] for page in page_reports
    )
    provenance_complete = revision_evidence == revision_provenance
    grounded_available = bool(
        raw_evidence["raw_sample_count"]
        and raw_evidence["timestamps_available"]
        and deterministic_measurements == len(page_reports)
        and provenance_complete
    )
    expected_visible = set(
        (imported.capture.get("ground_truth") or {}).get("visible_stroke_ids") or []
    )

    checks = {
        "grounded_evidence_available": grounded_available,
        "context_includes_all_selected_strokes": (
            selected_strokes == included_strokes == index_included == len(visible_ids)
        ),
        "timeline_history_complete": timeline_complete,
        "erased_replaced_recovery_complete": history_recovery["complete"],
        "analyzer_first_workspace": analyzer_first_pages == len(page_reports),
        "retrieval_is_bounded": (
            retrieval_calls <= 2 * len(page_reports)
            and raw_detail_calls <= len(page_reports)
        ),
    }
    if expected_visible:
        checks["fixture_ground_truth_matches"] = expected_visible == visible_ids

    return {
        "schema": REPORT_VERSION,
        "source": os.fspath(capture_path),
        "capture_schema": imported.capture["schema"],
        "session_id": imported.capture["session"]["id"],
        "page_count": len(page_reports),
        "event_count": len(imported.event_log),
        "grounded_evidence": {
            **raw_evidence,
            "available": grounded_available,
            "deterministic_measurement_count": deterministic_measurements,
            "revision_evidence_count": revision_evidence,
            "revision_provenance_count": revision_provenance,
            "ground_truth_available": bool(expected_visible),
        },
        "context": {
            "serialized_chars": context_chars,
            "estimated_tokens": _estimated_tokens(context_chars),
            "token_estimate": "ceil(serialized JSON chars / 4)",
        },
        "stroke_selection": {
            "selected_stroke_count": selected_strokes,
            "included_stroke_count": included_strokes,
            "omitted_stroke_count": selected_strokes - included_strokes,
        },
        "retrieval": {
            "calls": retrieval_calls,
            "raw_detail_calls": raw_detail_calls,
            "bounded": checks["retrieval_is_bounded"],
        },
        "timeline": {
            "history_complete": timeline_complete,
            "complete_page_count": sum(
                page["timeline_history_complete"] for page in page_reports
            ),
            "page_count": len(page_reports),
            "moment_count": sum(
                page["timeline_moment_count"] for page in page_reports
            ),
            "erased_stroke_count": sum(
                page["timeline_erased_stroke_count"] for page in page_reports
            ),
        },
        "history_recovery": history_recovery,
        "pages": page_reports,
        "checks": checks,
        "passed": all(checks.values()),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic Neeh real-capture regression gate."
    )
    parser.add_argument(
        "capture",
        nargs="?",
        type=Path,
        default=DEFAULT_CAPTURE,
        help="capture JSON, export directory, or ZIP bundle",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="emit compact JSON instead of indented JSON",
    )
    args = parser.parse_args(argv)
    report = evaluate_capture(args.capture)
    print(
        json.dumps(
            report,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
            sort_keys=True,
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
