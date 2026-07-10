"""M2 additions: encoders E3/E5/E6, task families T2/T5/T6, action scoring."""
import json

import pytest

from research.harness.actions import score_action
from research.harness.backends import MockBackend
from research.harness.corpus_s0 import make_shape_page, make_text_page, generate_corpus
from research.harness.encoders import ALL_ARMS, ENCODERS
from research.harness.encoders_m2 import encode_e3, encode_e5, encode_e6
from research.harness.ledger import Ledger
from research.harness.runner import SweepConfig, run_sweep
from research.harness.tasks import ALL_FAMILIES, generate_tasks


def test_registry_contains_all_arms():
    for arm in ALL_ARMS + ["CTRL"]:
        assert arm in ENCODERS, arm


class TestE3:
    def test_grid_cells_and_ids(self):
        page = make_shape_page(0, seed=4)
        encoded = encode_e3(page.page)
        assert encoded.version == "E3/0.1.0"
        first = encoded.text.splitlines()[0]
        head, _, body = first.partition(": ")
        assert head.startswith("st_") and head.endswith(" user")
        cells = body.split()
        assert all(c.startswith("(") and c.endswith(")") for c in cells)
        xs = [int(c.strip("()").split(",")[0]) for c in cells]
        ys = [int(c.strip("()").split(",")[1]) for c in cells]
        assert all(1 <= v <= 50 for v in xs + ys)
        # No consecutive duplicate cells.
        assert all(a != b for a, b in zip(cells, cells[1:]))


class TestE5:
    def test_words_cluster_into_groups(self):
        page = make_text_page(0, seed=4)
        encoded = encode_e5(page.page)
        group_lines = [l for l in encoded.text.splitlines() if l.startswith("group ")]
        # Every word is a spatial cluster; clustering may merge close words but
        # must produce more than one group and no more groups than words.
        assert 1 < len(group_lines) <= len(page.words)

    def test_descriptors_cover_kinds(self):
        page = make_shape_page(0, seed=4)
        encoded = encode_e5(page.page)
        body = encoded.text
        assert "loop" in body  # closed shapes (circle/square/...) read as loops
        for shape in page.shapes:
            for sid in shape["stroke_ids"]:
                assert sid in body


class TestE6:
    def test_temporal_raster_is_png_only(self):
        pytest.importorskip("PIL")
        page = make_shape_page(0, seed=4)
        encoded = encode_e6(page.page)
        assert encoded.text is None
        assert encoded.image_png[:8] == b"\x89PNG\r\n\x1a\n"
        # Source page must be untouched (recoloring works on a copy).
        colors = {s.style.color for l in page.page.layers for s in l.strokes}
        assert colors == {"#1a1a1a"}


class TestNewFamilies:
    def test_t2_t5_t6_generated(self):
        pages = generate_corpus(seed=3, n_text_pages=2, n_shape_pages=2)
        tasks = generate_tasks(pages, families=ALL_FAMILIES)
        families = {t.family for t in tasks}
        assert families == set(ALL_FAMILIES)
        assert sum(t.family == "T2" for t in tasks) == 2   # one per shape page
        assert sum(t.family == "T5" for t in tasks) == 6   # 2 per text + 1 per shape
        assert sum(t.family == "T6" for t in tasks) == 4   # one per page

    def test_t6_truth_matches_creation_order(self):
        page = make_text_page(0, seed=3)
        task = generate_tasks([page], families=("T6",))[0]
        assert task.truth == page.words[-1]["word"]


class TestActionScoring:
    def test_erase_scores_by_executed_ids(self):
        page = make_text_page(1, seed=3)
        target = page.words[0]
        truth = {"type": "erase", "stroke_ids": list(target["stroke_ids"])}
        good = json.dumps({"tool": "erase", "input": {"stroke_ids": target["stroke_ids"]}})
        assert score_action(good, truth, page.page) == 1.0
        partial = json.dumps(
            {"tool": "erase", "input": {"stroke_ids": target["stroke_ids"][:1]}}
        )
        assert 0.0 < score_action(partial, truth, page.page) < 1.0
        assert score_action("not json", truth, page.page) == 0.0
        wrong_tool = json.dumps({"tool": "highlight", "input": {"region": [0, 0, 1, 1]}})
        assert score_action(wrong_tool, truth, page.page) == 0.0

    def test_erase_execution_does_not_mutate_source_page(self):
        page = make_text_page(1, seed=3)
        target = page.words[0]
        before = sum(len(l.strokes) for l in page.page.layers)
        truth = {"type": "erase", "stroke_ids": list(target["stroke_ids"])}
        answer = json.dumps({"tool": "erase", "input": {"stroke_ids": target["stroke_ids"]}})
        score_action(answer, truth, page.page)
        assert sum(len(l.strokes) for l in page.page.layers) == before

    def test_highlight_iou_and_foreign_overlap(self):
        page = make_text_page(2, seed=3)
        target, other = page.words[0], page.words[1]
        truth = {
            "type": "highlight",
            "target_bbox": list(target["bbox"]),
            "foreign_bboxes": [list(w["bbox"]) for w in page.words[1:]],
        }
        exact = json.dumps({"tool": "highlight", "input": {"region": list(target["bbox"])}})
        assert score_action(exact, truth, page.page) == 1.0
        miss = json.dumps({"tool": "highlight", "input": {"region": list(other["bbox"])}})
        assert score_action(miss, truth, page.page) == 0.0


def test_mock_sweep_covers_full_m2_matrix(tmp_path):
    pytest.importorskip("PIL")
    pages = generate_corpus(seed=5, n_text_pages=1, n_shape_pages=1)
    tasks = generate_tasks(pages, families=ALL_FAMILIES)
    ledger = Ledger(tmp_path / "ledger.jsonl")
    config = SweepConfig(arms=list(ALL_ARMS), ledger=ledger)
    counts = run_sweep(MockBackend(), pages, tasks, config, log=lambda *a, **k: None)
    assert counts["failed"] == 0
    rows = list(ledger.rows())
    assert len(rows) == (len(ALL_ARMS) + 1) * len(tasks)
    assert all(row["score"] == 1.0 for row in rows)
