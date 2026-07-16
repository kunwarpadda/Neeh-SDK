"""M3 exit-gate arithmetic on synthetic summaries."""
from __future__ import annotations

import pytest

gate = pytest.importorskip("benchmarks.move3_gate")


def _cell(accuracy, tokens, false_expl, pixels=0):
    return {
        "accuracy": accuracy,
        "mean_estimated_tokens": tokens,
        "false_explanation_rate": false_expl,
        "mean_raster_pixels": pixels,
    }


def test_gate_passes_on_match_with_material_reduction():
    summary = {
        "raster-only": _cell(0.5, 2000, 0.2, pixels=650_000),
        "raster+geometry": _cell(0.6, 2400, 0.25, pixels=650_000),
        "analyzer-first": _cell(0.9, 1200, 0.05),
    }
    verdict = gate.evaluate_exit_gate(summary)
    assert verdict["decidable"] and verdict["gate_passed"]
    # Baseline is the better raster arm, not the weaker one.
    assert verdict["raster_baseline"] == "raster+geometry"
    assert verdict["context_reduction"] == 0.5


def test_gate_fails_when_context_reduction_is_immaterial():
    summary = {
        "raster-only": _cell(0.5, 1300, 0.2),
        "analyzer-first": _cell(0.9, 1200, 0.05),
    }
    verdict = gate.evaluate_exit_gate(summary)
    assert verdict["matches_or_beats_accuracy"] is True
    assert verdict["materially_reduces_context"] is False
    assert verdict["gate_passed"] is False


def test_gate_fails_on_accuracy_regression_or_more_confabulation():
    lower_accuracy = {
        "raster-only": _cell(0.9, 2000, 0.0),
        "analyzer-first": _cell(0.8, 500, 0.0),
    }
    assert gate.evaluate_exit_gate(lower_accuracy)["gate_passed"] is False
    more_confabulation = {
        "raster-only": _cell(0.5, 2000, 0.1),
        "analyzer-first": _cell(0.9, 500, 0.3),
    }
    verdict = gate.evaluate_exit_gate(more_confabulation)
    assert verdict["reduces_unsupported_claims"] is False
    assert verdict["gate_passed"] is False


def test_gate_is_undecidable_without_scored_rows():
    assert gate.evaluate_exit_gate({})["decidable"] is False
    only_candidate = {"analyzer-first": _cell(1.0, 100, 0.0)}
    assert gate.evaluate_exit_gate(only_candidate)["decidable"] is False
