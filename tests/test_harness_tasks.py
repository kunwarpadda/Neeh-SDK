"""Tasks, scorers, and the mock end-to-end sweep."""
import pytest

from research.harness.backends import MockBackend
from research.harness.corpus_s0 import generate_corpus
from research.harness.ledger import Ledger
from research.harness.runner import SweepConfig, assemble_prompt, run_sweep
from research.harness.scorers import score_cer, score_exact, score_set_f1
from research.harness.tasks import generate_tasks
from research.harness.encoders import encode_e2


class TestScorers:
    def test_cer(self):
        assert score_cer("apple bridge", "apple bridge") == 1.0
        assert score_cer("Apple  Bridge!", "apple bridge") == 1.0  # normalization
        assert score_cer("", "apple") == 0.0
        assert 0.0 < score_cer("aple bridge", "apple bridge") < 1.0

    def test_exact(self):
        assert score_exact("Top-Left", "top-left") == 1.0
        assert score_exact("top right", "top-left") == 0.0

    def test_set_f1(self):
        truth = ["st_a_0001", "st_a_0002"]
        assert score_set_f1("st_a_0001 st_a_0002", truth) == 1.0
        assert score_set_f1("The strokes are st_a_0001 and st_a_0002.", truth) == 1.0
        assert score_set_f1("st_a_0001", truth) == pytest.approx(2 / 3)
        assert score_set_f1("none", truth) == 0.0


def test_task_generation_is_deterministic_and_covers_families():
    pages = generate_corpus(seed=1, n_text_pages=2, n_shape_pages=2)
    tasks_a = generate_tasks(pages)
    tasks_b = generate_tasks(pages)
    assert [t.task_id for t in tasks_a] == [t.task_id for t in tasks_b]
    families = {t.family for t in tasks_a}
    assert families == {"T1", "T3", "T4"}
    # T1 per text page; T3 two per shape page; T4 two per text + one per shape.
    assert sum(t.family == "T1" for t in tasks_a) == 2
    assert sum(t.family == "T3" for t in tasks_a) == 4
    assert sum(t.family == "T4" for t in tasks_a) == 6


def test_prompt_assembly_is_identical_outside_context():
    pages = generate_corpus(seed=1, n_text_pages=1, n_shape_pages=0)
    task = generate_tasks(pages, families=("T1",))[0]
    encoded = encode_e2(pages[0].page)
    prompt = assemble_prompt(encoded, task)
    assert prompt.count("=== PAGE CONTEXT ===") == 1
    assert prompt.endswith(task.prompt)
    assert encoded.legend in prompt and encoded.text in prompt


def test_mock_sweep_end_to_end(tmp_path):
    pages = generate_corpus(seed=2, n_text_pages=1, n_shape_pages=1)
    tasks = generate_tasks(pages)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    config = SweepConfig(arms=["E2", "E4"], ledger=ledger, include_ctrl=True)
    counts = run_sweep(MockBackend(), pages, tasks, config, log=lambda *a, **k: None)

    rows = list(ledger.rows())
    assert counts["failed"] == 0
    assert counts["run"] == len(rows) == 3 * len(tasks)  # E2, E4, CTRL
    # The oracle mock answers from truth, so every score is 1.0.
    assert all(row["score"] == 1.0 for row in rows)
    assert all(row["input_tokens"] is not None for row in rows)

    # Resume: a second sweep runs nothing new.
    counts_again = run_sweep(MockBackend(), pages, tasks, config, log=lambda *a, **k: None)
    assert counts_again["run"] == 0
    assert counts_again["skipped"] == 3 * len(tasks)


def test_summary_builds_from_ledger(tmp_path):
    pages = generate_corpus(seed=2, n_text_pages=1, n_shape_pages=1)
    tasks = generate_tasks(pages)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    run_sweep(MockBackend(), pages, tasks,
              SweepConfig(arms=["E2"], ledger=ledger), log=lambda *a, **k: None)

    from research.harness.report import build_summary

    summary = build_summary(ledger)
    assert "| mock" not in summary  # model column holds the model name, not backend
    assert "| oracle | E2 | T1 |" in summary
    assert "Pareto view" in summary
