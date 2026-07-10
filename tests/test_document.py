import time

import pytest

from neeh.document import Document, Layer, Page
from neeh.ink import Author, BoundingBox, Stroke


def make_stroke(x0=0, y0=0):
    return Stroke.from_xy([(x0, y0), (x0 + 10, y0 + 10)])


class TestLayer:
    def test_add_get_remove(self):
        layer = Layer()
        s = layer.add(make_stroke())
        assert layer.get(s.id) is s
        assert layer.remove(s.id) is s
        assert layer.get(s.id) is None

    def test_locked_rejects_edits(self):
        layer = Layer(locked=True)
        with pytest.raises(ValueError):
            layer.add(make_stroke())
        with pytest.raises(ValueError):
            layer.remove("st_whatever")

    def test_strokes_in(self):
        layer = Layer()
        near = layer.add(make_stroke(0, 0))
        layer.add(make_stroke(500, 500))
        found = layer.strokes_in(BoundingBox(0, 0, 50, 50))
        assert found == [near]


class TestPage:
    def test_default_ink_layer(self):
        page = Page()
        assert page.layer("ink") is not None

    def test_agent_layer_is_idempotent(self):
        page = Page()
        agent = page.agent_layer()
        assert agent.author is Author.AGENT
        assert page.agent_layer() is agent
        assert len(page.layers) == 2

    def test_find_across_layers(self):
        page = Page()
        s = page.agent_layer().add(make_stroke())
        layer, found = page.find(s.id)
        assert found is s and layer.author is Author.AGENT
        assert page.find("st_missing") is None

    def test_strokes_since(self):
        page = Page()
        old = make_stroke()
        object.__setattr__(old, "created_at_ms", 1000)
        page.layer("ink").add(old)
        recent = page.layer("ink").add(make_stroke())
        cutoff = int(time.time() * 1000) - 60_000
        assert page.strokes_since(cutoff) == [recent]


class TestDocument:
    def test_pages(self):
        doc = Document()
        second = doc.new_page(width=500, height=500)
        assert doc.page(1) is second
        assert doc.page(second.id) is second
        assert doc.page(99) is None

    def test_json_roundtrip(self, tmp_path):
        doc = Document(title="Notes")
        page = doc.pages[0]
        page.layer("ink").add(make_stroke())
        page.agent_layer().add(make_stroke(100, 100))

        path = tmp_path / "notes.neeh"
        doc.save(path)
        restored = Document.load(path)

        assert restored.id == doc.id
        assert restored.title == "Notes"
        assert restored.to_dict() == doc.to_dict()

    def test_rejects_foreign_format(self):
        with pytest.raises(ValueError):
            Document.from_dict({"format": "uim/1.0", "id": "doc_x"})
