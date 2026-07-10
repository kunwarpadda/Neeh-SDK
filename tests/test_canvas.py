import pytest

from neeh import Canvas, Document, Viewport
from neeh.ink import Author, BoundingBox


class TestCanvasEditing:
    def test_add_stroke_lands_on_ink_layer(self):
        canvas = Canvas()
        s = canvas.add_stroke([(0, 0), (10, 10)])
        layer, found = canvas.page.find(s.id)
        assert found is s and layer.name == "ink"

    def test_agent_stroke_lands_on_agent_layer(self):
        canvas = Canvas()
        s = canvas.add_stroke([(0, 0), (10, 10)], author=Author.AGENT)
        layer, _ = canvas.page.find(s.id)
        assert layer.author is Author.AGENT

    def test_erase_by_id_and_region(self):
        canvas = Canvas()
        a = canvas.add_stroke([(0, 0), (10, 10)])
        b = canvas.add_stroke([(500, 500), (510, 510)])
        assert canvas.erase(stroke_ids=[a.id]) == [a.id]
        assert canvas.erase(region=BoundingBox(490, 490, 520, 520)) == [b.id]
        assert canvas.page.all_strokes() == []
        with pytest.raises(ValueError):
            canvas.erase()

    def test_erase_updates_selection(self):
        canvas = Canvas()
        s = canvas.add_stroke([(0, 0), (10, 10)])
        canvas.select(stroke_ids=[s.id])
        canvas.erase(stroke_ids=[s.id])
        assert not canvas.selection

    def test_move_selection_preserves_ids(self):
        canvas = Canvas()
        s = canvas.add_stroke([(0, 0), (10, 10)])
        canvas.select(region=BoundingBox(-1, -1, 11, 11))
        assert canvas.move(100, 50) == 1
        _, moved = canvas.page.find(s.id)
        assert moved.bbox == BoundingBox(100, 50, 110, 60)

    def test_locked_layer_is_protected(self):
        canvas = Canvas()
        s = canvas.add_stroke([(0, 0), (10, 10)])
        canvas.page.layer("ink").locked = True
        assert canvas.erase(stroke_ids=[s.id]) == []
        assert canvas.move(5, 5, stroke_ids=[s.id]) == 0
        with pytest.raises(ValueError):
            canvas.add_stroke([(1, 1)])
        canvas.page.layer("ink").locked = False


class TestUndoRedo:
    def test_full_cycle(self):
        canvas = Canvas()
        s = canvas.add_stroke([(0, 0), (10, 10)])
        canvas.move(100, 0, stroke_ids=[s.id])

        assert canvas.undo() == "move"
        assert canvas.page.find(s.id)[1].bbox.min_x == 0
        assert canvas.undo() == "add_stroke"
        assert canvas.page.all_strokes() == []
        assert canvas.undo() is None

        assert canvas.redo() == "add_stroke"
        assert canvas.redo() == "move"
        assert canvas.page.find(s.id)[1].bbox.min_x == 100
        assert canvas.redo() is None

    def test_new_edit_clears_redo(self):
        canvas = Canvas()
        canvas.add_stroke([(0, 0)])
        canvas.undo()
        canvas.add_stroke([(5, 5)])
        assert canvas.redo() is None

    def test_undo_restores_erased_strokes(self):
        canvas = Canvas()
        s = canvas.add_stroke([(0, 0), (10, 10)])
        canvas.erase(stroke_ids=[s.id])
        canvas.undo()
        assert canvas.page.find(s.id) is not None


class TestViewport:
    def test_view_page_roundtrip(self):
        vp = Viewport(x=100, y=50, zoom=2.0)
        px, py = vp.to_page(*vp.to_view(123, 456))
        assert (px, py) == pytest.approx((123, 456))

    def test_zoom_at_keeps_anchor_fixed(self):
        vp = Viewport()
        anchor_page = vp.to_page(100, 100)
        vp.zoom_at(2.0, 100, 100)
        assert vp.zoom == 2.0
        assert vp.to_page(100, 100) == pytest.approx(anchor_page)

    def test_fit_centers_content(self):
        vp = Viewport(width=1000, height=1000)
        bounds = BoundingBox(0, 0, 100, 100)
        vp.fit(bounds)
        assert vp.visible_bounds.contains_box(bounds)
        assert vp.visible_bounds.center == pytest.approx(bounds.center)

    def test_strokes_in_view(self):
        canvas = Canvas(Document())
        inside = canvas.add_stroke([(10, 10), (20, 20)])
        canvas.add_stroke([(5000, 5000), (5010, 5010)])
        canvas.viewport = Viewport(width=100, height=100, zoom=1.0)
        visible = canvas.strokes_in_view()
        assert [s.id for s in visible] == [inside.id]


class TestPages:
    def test_goto_page_clears_selection(self):
        canvas = Canvas()
        s = canvas.add_stroke([(0, 0)])
        canvas.select(stroke_ids=[s.id])
        canvas.document.new_page()
        canvas.goto_page(1)
        assert not canvas.selection
        with pytest.raises(IndexError):
            canvas.goto_page(5)
