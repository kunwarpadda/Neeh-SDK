import json

import pytest

from neeh import (
    Canvas,
    Document,
    InkContextError,
    Page,
    SemanticItem,
    build_ink_context,
)
from neeh.document import Layer
from neeh.ink import Author, BoundingBox, Point, Stroke, StrokeStyle


def make_stroke(
    stroke_id: str,
    x: float,
    *,
    author: Author = Author.USER,
    created_at_ms: int = 1_000,
    point_count: int = 2,
) -> Stroke:
    points = tuple(
        Point(x + index, x + index / 2, index * 10, 0.5, 1.25, -1.25)
        for index in range(point_count)
    )
    return Stroke(
        id=stroke_id,
        points=points,
        style=StrokeStyle(color="#123456", width=2.345, opacity=0.75),
        author=author,
        created_at_ms=created_at_ms,
    )


def test_schema_and_page_metadata_from_page_canvas_and_document():
    page = Page(id="pg_primary", width=640, height=480, background="#fafafa")
    document = Document(id="doc_notes", pages=[page])
    canvas = Canvas(document)

    for source in (page, document, canvas):
        context = build_ink_context(source)
        assert context["schema"] == "ink-context/v0"
        assert context["page"] == {
            "id": "pg_primary",
            "width": 640.0,
            "height": 480.0,
            "background": "#fafafa",
        }
        assert context["raster"] == {
            "format": "png",
            "transport": "attached_image",
            "coordinate_space": "page",
            "region": None,
        }
        assert context["vector"]["page_id"] == "pg_primary"
        assert context["semantics"] == []


def test_document_page_selector_does_not_mutate_canvas_page():
    first = Page(id="pg_first")
    second = Page(id="pg_second", width=200, height=300)
    canvas = Canvas(Document(pages=[first, second]))

    context = build_ink_context(canvas, page="pg_second")

    assert context["page"]["id"] == "pg_second"
    assert canvas.page is first


def test_point_compaction_is_even_and_keeps_endpoints():
    page = Page(id="pg_sampling")
    long_stroke = make_stroke("st_long", 10.123, point_count=8)
    short_stroke = make_stroke("st_short", 30.456, point_count=3)
    page.layer("ink").strokes.extend([long_stroke, short_stroke])

    strokes = build_ink_context(page, max_points_per_stroke=4)["vector"]["strokes"]

    assert strokes[0]["point_count"] == 8
    # round(i * 7 / 3) selects 0, 2, 5, 7, including exact endpoints.
    assert [point[0] for point in strokes[0]["points_sample"]] == [
        long_stroke.points[index].x for index in (0, 2, 5, 7)
    ]
    assert strokes[0]["points_sample"][0][2] == 0
    assert strokes[0]["points_sample"][-1][2] == 70
    # Strokes at or below the cap retain every point.
    assert len(strokes[1]["points_sample"]) == 3


def test_vector_records_preserve_identity_authorship_layers_and_time():
    page = Page(id="pg_records")
    agent_layer = page.add_layer("answers", author=Author.AGENT)
    stroke = make_stroke(
        "st_answer",
        20,
        author=Author.AGENT,
        created_at_ms=9_876,
        point_count=3,
    )
    agent_layer.add(stroke)

    record = build_ink_context(page)["vector"]["strokes"][0]

    assert record == {
        "id": "st_answer",
        "layer_id": agent_layer.id,
        "layer_name": "answers",
        "author": "agent",
        "created_at_ms": 9_876,
        "duration_ms": 20,
        "bbox": [20.0, 20.0, 22.0, 21.0],
        "style": {
            "color": "#123456",
            "width": 2.345,
            "opacity": 0.75,
            "brush": "pen",
        },
        "point_count": 3,
        "points_sample": [
            [20.0, 20.0, 0, 0.5, 1.25, -1.25],
            [21.0, 20.5, 10, 0.5, 1.25, -1.25],
            [22.0, 21.0, 20, 0.5, 1.25, -1.25],
        ],
    }


def test_filters_apply_before_limits_and_region_is_shared_with_raster():
    page = Page(id="pg_filters")
    old_user = make_stroke("st_old", 0, created_at_ms=100)
    recent_user = make_stroke("st_recent", 10, created_at_ms=300)
    page.layer("ink").strokes.extend([old_user, recent_user])
    agent_layer = page.add_layer("agent", author=Author.AGENT)
    agent_layer.add(make_stroke("st_agent", 12, author=Author.AGENT, created_at_ms=400))
    hidden = Layer(id="ly_hidden", name="hidden", visible=False)
    hidden.add(make_stroke("st_hidden", 12, created_at_ms=500))
    page.layers.append(hidden)

    context = build_ink_context(
        page,
        region=BoundingBox(9, 9, 20, 20),
        stroke_ids=["st_recent", "st_agent", "st_hidden"],
        author="agent",
        since_ms=350,
        visible_only=True,
        max_strokes=1,
    )

    assert context["raster"]["region"] == [9.0, 9.0, 20.0, 20.0]
    assert context["vector"]["region"] == context["raster"]["region"]
    assert context["vector"]["stroke_count"] == 1
    assert [stroke["id"] for stroke in context["vector"]["strokes"]] == ["st_agent"]

    with_hidden = build_ink_context(page, stroke_ids=["st_hidden"], visible_only=False)
    assert [stroke["id"] for stroke in with_hidden["vector"]["strokes"]] == ["st_hidden"]


def test_stroke_limit_keeps_newest_tail_in_document_order_and_is_explicit():
    page = Page(id="pg_limit")
    for index in range(5):
        page.layer("ink").add(
            make_stroke(f"st_{index}", index * 10, created_at_ms=100 + index)
        )

    first = build_ink_context(page, max_strokes=2, max_points_per_stroke=2)
    second = build_ink_context(page, max_strokes=2, max_points_per_stroke=2)

    assert first == second
    vector = first["vector"]
    assert vector["stroke_count"] == 5
    assert vector["included_stroke_count"] == 2
    assert vector["omitted_older_stroke_count"] == 3
    assert vector["truncated"] is True
    assert vector["points_policy"] == "sampled up to 2 points per stroke"
    assert [stroke["id"] for stroke in vector["strokes"]] == ["st_3", "st_4"]


def test_zero_and_unlimited_stroke_limits_are_unambiguous():
    page = Page(id="pg_zero")
    page.layer("ink").add(make_stroke("st_one", 0))

    empty = build_ink_context(page, max_strokes=0)["vector"]
    assert empty["stroke_count"] == 1
    assert empty["included_stroke_count"] == 0
    assert empty["omitted_older_stroke_count"] == 1
    assert empty["strokes"] == []

    unlimited = build_ink_context(
        page, max_strokes=None, max_points_per_stroke=None
    )["vector"]
    assert unlimited["included_stroke_count"] == 1
    assert unlimited["points_policy"] == "all points included"


def test_explicit_empty_stroke_id_filter_matches_no_strokes():
    page = Page(id="pg_empty_filter")
    page.layer("ink").add(make_stroke("st_present", 0))

    vector = build_ink_context(page, stroke_ids=[])["vector"]

    assert vector["stroke_count"] == 0
    assert vector["included_stroke_count"] == 0
    assert vector["strokes"] == []


def test_semantics_accept_mappings_and_objects_and_are_json_ready():
    page = Page(id="pg_semantics")
    stroke = page.layer("ink").add(make_stroke("st_word", 40))
    semantic = SemanticItem(
        id="rg_text",
        kind="handwritten_text",
        region=[39, 39, 45, 45],
        stroke_ids=[stroke.id],
        text="hello",
        confidence=0.85,
        source="test_recognizer",
    )

    context = build_ink_context(
        page,
        semantics=[
            semantic,
            {"id": "rg_region", "kind": "diagram", "region": [0, 0, 10, 10]},
        ],
    )

    assert context["semantics"] == [
        {
            "id": "rg_text",
            "kind": "handwritten_text",
            "region": [39.0, 39.0, 45.0, 45.0],
            "stroke_ids": ["st_word"],
            "text": "hello",
            "confidence": 0.85,
            "source": "test_recognizer",
        },
        {"id": "rg_region", "kind": "diagram", "region": [0.0, 0.0, 10.0, 10.0]},
    ]
    json.dumps(context, allow_nan=False)


@pytest.mark.parametrize(
    ("semantic", "message"),
    [
        ({"kind": "text", "region": [0, 0, 1, 1]}, "missing required field"),
        ({"id": "rg_x", "kind": "text"}, "needs a region, stroke_ids, or both"),
        (
            {"id": "rg_x", "kind": "text", "region": [0, 0, 1, 1], "confidence": 1.1},
            "between 0 and 1",
        ),
        (
            {"id": "rg_x", "kind": "text", "region": [0, 0, 1, 1], "extra": object()},
            "unsupported field",
        ),
        (
            {"id": "rg_x", "kind": "text", "region": [0, 0, 1, 1], "text": 42},
            "text must be a non-empty string",
        ),
        (
            {"id": "rg_x", "kind": "text", "region": [0, 0, 1, 1], "text": ""},
            "text must be a non-empty string",
        ),
        (
            {"id": "rg_x", "kind": "text", "stroke_ids": ["st_missing"]},
            "missing from vector.strokes",
        ),
    ],
)
def test_semantic_validation_errors_are_specific(semantic, message):
    with pytest.raises(InkContextError, match=message):
        build_ink_context(Page(id="pg_invalid"), semantics=[semantic])


def test_builder_rejects_ambiguous_or_invalid_options():
    page = Page(id="pg_validation")

    with pytest.raises(InkContextError, match="exactly four"):
        build_ink_context(page, region=[0, 0, 1])
    with pytest.raises(InkContextError, match="at least 2"):
        build_ink_context(page, max_points_per_stroke=1)
    with pytest.raises(InkContextError, match="author"):
        build_ink_context(page, author="robot")
    with pytest.raises(InkContextError, match="different page"):
        build_ink_context(page, page="pg_other")
    with pytest.raises(InkContextError, match="has no pages"):
        build_ink_context(Canvas(Document(pages=[])))


def test_builder_defensively_validates_page_and_style_colors():
    bad_page = Page(id="pg_bad_background")
    bad_page.background = "white"
    with pytest.raises(InkContextError, match="page.background"):
        build_ink_context(bad_page)

    page = Page(id="pg_bad_style")
    stroke = make_stroke("st_bad_style", 0)
    object.__setattr__(stroke.style, "color", "red")
    page.layer("ink").add(stroke)
    with pytest.raises(InkContextError, match="style.color"):
        build_ink_context(page)


def test_semantic_stroke_references_must_resolve_after_filtering_and_limits():
    page = Page(id="pg_anchor_scope")
    page.layer("ink").strokes.extend(
        [make_stroke("st_older", 0), make_stroke("st_newer", 10)]
    )

    with pytest.raises(InkContextError, match="missing from vector.strokes"):
        build_ink_context(
            page,
            max_strokes=1,
            semantics=[{"id": "rg_old", "kind": "text", "stroke_ids": ["st_older"]}],
        )


@pytest.mark.parametrize(
    ("invalidity", "message"),
    [
        ("decreasing_time", "nondecreasing"),
        ("pressure", "pressure"),
        ("tilt_x", "tilt_x"),
    ],
)
def test_builder_validates_all_point_samples_before_compaction(invalidity, message):
    page = Page(id="pg_bad_points")
    stroke = make_stroke("st_bad", 0)
    if invalidity == "decreasing_time":
        object.__setattr__(stroke, "points", (Point(0, 0, 10), Point(1, 1, 5)))
    else:
        points = list(stroke.points)
        object.__setattr__(points[0], invalidity, 1.1 if invalidity == "pressure" else 91)
        object.__setattr__(stroke, "points", tuple(points))
    page.layer("ink").add(stroke)

    with pytest.raises(InkContextError, match=message):
        build_ink_context(page, max_points_per_stroke=2)


def test_payload_contains_no_raster_bytes_and_is_strict_json_serializable():
    page = Page(id="pg_json")
    page.layer("ink").add(make_stroke("st_json", 1.2345))

    context = build_ink_context(page)
    encoded = json.dumps(context, allow_nan=False, sort_keys=True)
    record = context["vector"]["strokes"][0]

    assert "attached_image" in encoded
    assert record["bbox"][0] == 1.2345
    assert record["points_sample"][0][0] == 1.2345
    assert record["style"]["width"] == 2.345
    assert "data" not in context["raster"]
    assert "bytes" not in context["raster"]
    assert "base64" not in context["raster"]
