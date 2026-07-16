"""Focused tests for the standalone real-capture regression runner."""
from __future__ import annotations

import json

from benchmarks import real_capture_regression as regression


def test_fixture_report_contains_the_required_real_capture_measurements():
    report = regression.evaluate_capture(regression.DEFAULT_CAPTURE)

    assert report["passed"] is True
    assert report["capture_schema"] == "neeh-device-capture/v1"
    assert report["page_count"] == 2
    assert report["grounded_evidence"]["available"] is True
    assert report["grounded_evidence"]["raw_sample_count"] == 12
    assert report["context"]["serialized_chars"] > 0
    assert report["context"]["estimated_tokens"] == (
        report["context"]["serialized_chars"] + 3
    ) // 4
    assert report["stroke_selection"] == {
        "selected_stroke_count": 5,
        "included_stroke_count": 5,
        "omitted_stroke_count": 0,
    }
    assert report["retrieval"] == {
        "calls": 4,
        "raw_detail_calls": 2,
        "bounded": True,
    }
    assert report["timeline"]["history_complete"] is True
    assert report["timeline"]["erased_stroke_count"] == 1
    assert report["history_recovery"]["complete"] is True
    assert report["history_recovery"]["erased_recovered_ids"] == ["st_erased"]
    assert report["history_recovery"]["replaced_or_restored_recovered_ids"] == [
        "st_rewrite"
    ]


def test_cli_emits_the_same_passing_report(capsys):
    assert regression.main([str(regression.DEFAULT_CAPTURE), "--compact"]) == 0
    report = json.loads(capsys.readouterr().out)

    assert report["schema"] == regression.REPORT_VERSION
    assert report["checks"]["analyzer_first_workspace"] is True
    assert report["passed"] is True
