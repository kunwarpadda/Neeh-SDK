"""Move 1b: ground truth, balance, and the token-scaling crossover."""
from __future__ import annotations

import pytest

m = pytest.importorskip(
    "benchmarks.move1b_token_budget", reason="Move 1b needs Pillow (neeh[png])",
)


def test_ground_truth_matches_last_drawn_mark():
    scenes = m.build_scenes([4, 16], trials_per_size=6, seed=3)
    for s in scenes:
        last = max(s.page.all_strokes(), key=lambda st: st.created_at_ms)
        expected = "upper" if last.bbox.center[1] < m._HALF else "lower"
        assert s.answer == expected


def test_dataset_is_balanced():
    scenes = m.build_scenes([16], trials_per_size=6, seed=0)
    uppers = sum(s.answer == "upper" for s in scenes)
    assert uppers == len(scenes) // 2


def test_mock_reads_structure_not_pixels():
    scenes = m.build_scenes([4, 16, 48], trials_per_size=6, seed=1)
    rows = [m.score(s, c, m.run_mock(s, c), cap=8) for s in scenes for c in m.CONDITIONS]
    summary = m.summarize(rows, budget=8000)
    for n in ("4", "16", "48"):
        assert summary[n]["png"]["accuracy"] == 0.5           # no timing -> chance
        assert summary[n]["coords-full"]["accuracy"] == 1.0
        assert summary[n]["index-compact"]["accuracy"] == 1.0
        assert summary[n]["analyzer-reduced"]["accuracy"] == 1.0


def test_coords_full_scales_worse_than_compact_index():
    scenes_small = m.build_scenes([4], trials_per_size=1, seed=0)
    scenes_big = m.build_scenes([320], trials_per_size=1, seed=0)
    s_small, s_big = scenes_small[0], scenes_big[0]

    full_growth = (m.estimate_tokens(s_big, "coords-full", 8)
                   / max(m.estimate_tokens(s_small, "coords-full", 8), 1))
    compact_growth = (m.estimate_tokens(s_big, "index-compact", 8)
                      / max(m.estimate_tokens(s_small, "index-compact", 8), 1))
    # both grow with N, but per-point serialization grows strictly faster
    assert full_growth > compact_growth
    # and the compact index stays far cheaper at high N
    assert m.estimate_tokens(s_big, "index-compact", 8) < m.estimate_tokens(s_big, "coords-full", 8)


def test_analyzer_reduced_stays_bounded_as_page_density_grows():
    small = m.build_scenes([4], trials_per_size=1, seed=0)[0]
    large = m.build_scenes([320], trials_per_size=1, seed=0)[0]

    small_tokens = m.estimate_tokens(small, "analyzer-reduced", 8)
    large_tokens = m.estimate_tokens(large, "analyzer-reduced", 8)

    assert large_tokens - small_tokens < 10
    assert large_tokens < 300
