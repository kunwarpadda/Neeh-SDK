"""S0 corpus: determinism and ground-truth integrity."""
from research.harness.corpus_s0 import generate_corpus, make_shape_page, make_text_page


def test_corpus_is_deterministic():
    a = make_text_page(0, seed=7)
    b = make_text_page(0, seed=7)
    assert a.document.to_dict() == b.document.to_dict()
    assert a.words == b.words

    c = make_shape_page(3, seed=7)
    d = make_shape_page(3, seed=7)
    assert c.document.to_dict() == d.document.to_dict()
    assert c.shapes == d.shapes


def test_different_seeds_differ():
    assert (
        make_text_page(0, seed=1).document.to_dict()
        != make_text_page(0, seed=2).document.to_dict()
    )


def test_text_truth_resolves_to_page_strokes():
    page = make_text_page(1, seed=0)
    on_page = {s.id for layer in page.page.layers for s in layer.strokes}
    seen: set[str] = set()
    for word in page.words:
        assert word["stroke_ids"], word["word"]
        assert set(word["stroke_ids"]) <= on_page
        assert not (set(word["stroke_ids"]) & seen), "words must not share strokes"
        seen |= set(word["stroke_ids"])
    orders = [w["order"] for w in page.words]
    assert orders == sorted(orders) == list(range(len(page.words)))


def test_shape_truth_matches_quadrants():
    page = make_shape_page(2, seed=0)
    for shape in page.shapes:
        cx, cy = shape["center"]
        horizontal = "left" if cx < 500 else "right"
        vertical = "top" if cy < 707 else "bottom"
        assert shape["quadrant"] == f"{vertical}-{horizontal}"
        # The whole shape stays inside its quadrant half-planes with margin.
        min_x, min_y, max_x, max_y = shape["bbox"]
        if horizontal == "left":
            assert max_x < 500
        else:
            assert min_x > 500
        if vertical == "top":
            assert max_y < 707
        else:
            assert min_y > 707


def test_generate_corpus_shapes_and_kinds():
    pages = generate_corpus(seed=0, n_text_pages=2, n_shape_pages=2)
    assert [p.kind for p in pages] == ["text", "text", "shapes", "shapes"]
    page_ids = [p.page.id for p in pages]
    assert len(set(page_ids)) == len(page_ids)


def test_jitter_changes_geometry_but_not_structure():
    plain = make_text_page(0, seed=5, jitter=0.0)
    noisy = make_text_page(0, seed=5, jitter=2.0)
    assert [w["word"] for w in plain.words] == [w["word"] for w in noisy.words]
    assert plain.document.to_dict() != noisy.document.to_dict()
