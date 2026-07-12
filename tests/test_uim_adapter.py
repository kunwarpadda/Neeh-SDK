"""Round-trip tests for the UIM adapter (the Neeh profile of UIM 3.1).

What must hold: structure, ids, authorship, flags, and millisecond times are
exact; geometry/style survive UIM's documented quantization (float32
coordinates, 8-bit color, 1e-4 pressure/tilt); and a round trip is
idempotent — re-exporting an imported document reproduces it exactly.
"""
import pytest

pytest.importorskip("uim")

from neeh.adapters.uim import (
    NEEH_PROFILE,
    UimImportError,
    document_from_uim,
    document_to_uim,
    load_uim,
    save_uim,
)
from neeh.document import Document, Layer, Page
from neeh.ink import Author, Point, Stroke
from neeh.ink.style import Brush, StrokeStyle


def make_document() -> Document:
    pen = Stroke(
        points=(
            Point(100.5, 50.0, t_ms=0, pressure=0.25, tilt_x=15.0, tilt_y=-30.0),
            Point(200.25, 60.5, t_ms=16, pressure=0.5),
            Point(300.125, 70.75, t_ms=33, pressure=1.0, tilt_x=-45.0, tilt_y=5.0),
        ),
        style=StrokeStyle(color="#1a2b3c", width=2.5, brush=Brush.PEN, opacity=1.0),
        id="st_pen00000001",
        author=Author.USER,
        created_at_ms=1751234567890,
    )
    highlight = Stroke(
        points=(Point(10.0, 20.0, t_ms=5),),
        style=StrokeStyle.highlighter(),
        id="st_agent000001",
        author=Author.AGENT,
        created_at_ms=1751234570000,
    )
    marker = Stroke(
        points=(Point(1.5, 2.5), Point(3.5, 4.5, t_ms=100, pressure=0.75)),
        style=StrokeStyle(color="#ff0000", width=6.0, brush=Brush.MARKER),
        id="st_marker00001",
        author=Author.USER,
        created_at_ms=1751234580000,
    )
    page_one = Page(
        id="pg_0000000001",
        width=1000.0,
        height=1414.0,
        background="#fffdf5",
        layers=[
            Layer(id="ly_ink0000001", name="ink", author=Author.USER, strokes=[pen, marker]),
            Layer(
                id="ly_agent00001",
                name="agent",
                author=Author.AGENT,
                visible=False,
                locked=True,
                strokes=[highlight],
            ),
        ],
    )
    page_two = Page(
        id="pg_0000000002",
        width=500.0,
        height=500.0,
        background="#ffffff",
        layers=[Layer(id="ly_empty00001", name="empty", strokes=[])],
    )
    return Document(
        id="doc_000000001",
        title="UIM round trip ✎",
        created_at_ms=1751234560000,
        pages=[page_one, page_two],
    )


def roundtrip(doc: Document) -> Document:
    return document_from_uim(document_to_uim(doc))


def test_structure_ids_and_authorship_are_exact():
    doc = make_document()
    out = roundtrip(doc)

    assert out.id == doc.id
    assert out.title == doc.title
    assert out.created_at_ms == doc.created_at_ms
    assert [p.id for p in out.pages] == ["pg_0000000001", "pg_0000000002"]

    page = out.pages[0]
    assert (page.width, page.height, page.background) == (1000.0, 1414.0, "#fffdf5")
    assert [(l.id, l.name, l.author, l.visible, l.locked) for l in page.layers] == [
        ("ly_ink0000001", "ink", Author.USER, True, False),
        ("ly_agent00001", "agent", Author.AGENT, False, True),
    ]
    assert [s.id for s in page.layers[0].strokes] == ["st_pen00000001", "st_marker00001"]
    assert page.layers[1].strokes[0].author is Author.AGENT
    assert out.pages[1].layers[0].strokes == []


def test_time_is_exact():
    out = roundtrip(make_document())
    pen = out.pages[0].layers[0].strokes[0]
    assert pen.created_at_ms == 1751234567890
    assert [p.t_ms for p in pen.points] == [0, 16, 33]
    marker = out.pages[0].layers[0].strokes[1]
    assert [p.t_ms for p in marker.points] == [0, 100]


def test_geometry_and_style_survive_quantization():
    doc = make_document()
    out = roundtrip(doc)
    pen_in = doc.pages[0].layers[0].strokes[0]
    pen_out = out.pages[0].layers[0].strokes[0]

    for p_in, p_out in zip(pen_in.points, pen_out.points):
        assert p_out.x == pytest.approx(p_in.x, abs=1e-3)
        assert p_out.y == pytest.approx(p_in.y, abs=1e-3)
        assert p_out.pressure == pytest.approx(p_in.pressure, abs=1e-4)
        assert p_out.tilt_x == pytest.approx(p_in.tilt_x, abs=0.05)
        assert p_out.tilt_y == pytest.approx(p_in.tilt_y, abs=0.05)

    assert pen_out.style.color == "#1a2b3c"
    assert pen_out.style.brush is Brush.PEN
    assert pen_out.style.width == pytest.approx(2.5, abs=1e-4)
    assert pen_out.style.opacity == pytest.approx(1.0, abs=1 / 255)

    hl_out = out.pages[0].layers[1].strokes[0]
    assert hl_out.style.brush is Brush.HIGHLIGHTER
    assert hl_out.style.color == "#ffe066"
    assert hl_out.style.opacity == pytest.approx(0.35, abs=1 / 255)


def test_roundtrip_is_idempotent():
    once = roundtrip(make_document())
    twice = roundtrip(once)
    assert twice.to_dict() == once.to_dict()


def test_default_document_roundtrips():
    doc = Document()
    out = roundtrip(doc)
    assert out.id == doc.id
    assert len(out.pages) == 1
    assert out.pages[0].layers[0].name == "ink"


def test_rejects_non_neeh_uim():
    from uim.codec.writer.encoder.encoder_3_1_0 import UIMEncoder310
    from uim.model.base import UUIDIdentifier
    from uim.model.ink import InkModel, InkTree
    from uim.model.semantics.node import StrokeGroupNode

    model = InkModel()
    model.ink_tree = InkTree()
    model.ink_tree.root = StrokeGroupNode(UUIDIdentifier.id_generator())
    blob = UIMEncoder310().encode(model)
    with pytest.raises(ValueError, match="neeh"):
        document_from_uim(blob)


def test_corrupted_document_raises_uim_import_error_not_raw_key_error():
    # A truncated/corrupted file that passes the profile check but is missing
    # required node facts must surface as one documented UimImportError, not
    # an unspecified KeyError leaking from dict access deep in traversal.
    from uim.codec.writer.encoder.encoder_3_1_0 import UIMEncoder310
    from uim.codec.parser.uim import UIMParser

    blob = document_to_uim(make_document())
    model = UIMParser().parse(blob)
    for triple in [t for t in model.knowledge_graph.statements if t.predicate == "neeh:id"]:
        model.knowledge_graph.remove_semantic_triple(triple)
    corrupted = UIMEncoder310().encode(model)

    with pytest.raises(UimImportError, match="malformed UIM document"):
        document_from_uim(corrupted)


def test_profile_identifier_is_canonical_and_unknown_versions_are_rejected():
    from uim.codec.parser.uim import UIMParser
    from uim.codec.writer.encoder.encoder_3_1_0 import UIMEncoder310

    blob = document_to_uim(make_document())
    model = UIMParser().parse(blob)
    assert dict(model.properties)["neeh.profile"] == NEEH_PROFILE == "neeh-uim/v1"

    model.properties = [
        (key, "neeh-uim/v999" if key == "neeh.profile" else value)
        for key, value in model.properties
    ]
    with pytest.raises(ValueError, match="unsupported Neeh UIM profile"):
        document_from_uim(UIMEncoder310().encode(model))


def test_initial_numeric_profile_remains_readable():
    from uim.codec.parser.uim import UIMParser
    from uim.codec.writer.encoder.encoder_3_1_0 import UIMEncoder310

    model = UIMParser().parse(document_to_uim(make_document()))
    model.properties = [
        (key, "1" if key == "neeh.profile" else value) for key, value in model.properties
    ]

    assert document_from_uim(UIMEncoder310().encode(model)).id == make_document().id


def test_save_and_load_file(tmp_path):
    doc = make_document()
    path = tmp_path / "roundtrip.uim"
    save_uim(doc, path)
    assert path.read_bytes()[:4] == b"RIFF"
    out = load_uim(path)
    assert out.to_dict() == roundtrip(doc).to_dict()
