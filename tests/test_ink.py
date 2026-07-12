import pytest

from neeh.ink import Author, BoundingBox, Brush, Point, Stroke, StrokeStyle


class TestPoint:
    def test_from_list_defaults(self):
        p = Point.from_list([10, 20])
        assert (p.x, p.y, p.t_ms, p.pressure, p.tilt_x, p.tilt_y) == (10, 20, 0, 1.0, 0.0, 0.0)

    def test_roundtrip(self):
        p = Point(1, 2, t_ms=30, pressure=0.5, tilt_x=10, tilt_y=-5)
        assert Point.from_list(p.to_list()) == p

    def test_translated(self):
        p = Point(1, 2, t_ms=7, pressure=0.5)
        q = p.translated(10, 20)
        assert (q.x, q.y) == (11, 22)
        assert (q.t_ms, q.pressure) == (7, 0.5)

    @pytest.mark.parametrize(
        "values",
        [
            [float("nan"), 0],
            [0, float("inf")],
            [0, 0, -1],
            [0, 0, 2**63],
            [0, 0, 0.5],
            [0, 0, 0, 1.1],
            [0, 0, 0, 1, 91],
            [0, 0, 0, 1, 0, -91],
        ],
    )
    def test_rejects_invalid_channels(self, values):
        with pytest.raises(ValueError):
            Point.from_list(values)

    def test_rejects_invalid_tuple_lengths(self):
        with pytest.raises(ValueError):
            Point.from_list([1])
        with pytest.raises(ValueError):
            Point.from_list([1, 2, 3, 4, 5, 6, 7])
        with pytest.raises(ValueError):
            Point.from_list("123456")


class TestBoundingBox:
    def test_inverted_raises(self):
        with pytest.raises(ValueError):
            BoundingBox(10, 0, 0, 10)

    def test_basic_geometry(self):
        box = BoundingBox(0, 0, 10, 20)
        assert box.width == 10 and box.height == 20
        assert box.center == (5, 10)
        assert box.contains(5, 5) and not box.contains(11, 5)

    def test_union_and_intersects(self):
        a = BoundingBox(0, 0, 10, 10)
        b = BoundingBox(5, 5, 20, 20)
        c = BoundingBox(100, 100, 110, 110)
        assert a.intersects(b) and not a.intersects(c)
        assert a.union(c) == BoundingBox(0, 0, 110, 110)

    def test_from_points(self):
        box = BoundingBox.from_points([Point(1, 5), Point(3, 2)])
        assert box == BoundingBox(1, 2, 3, 5)
        with pytest.raises(ValueError):
            BoundingBox.from_points([])

    def test_union_all_empty_is_none(self):
        assert BoundingBox.union_all([]) is None

    def test_rejects_non_finite_coordinates_and_wrong_length(self):
        with pytest.raises(ValueError):
            BoundingBox(0, 0, float("inf"), 1)
        with pytest.raises(ValueError):
            BoundingBox.from_list([0, 1, 2])
        with pytest.raises(ValueError):
            BoundingBox.from_list("0123")


class TestStrokeStyle:
    def test_validation(self):
        with pytest.raises(ValueError):
            StrokeStyle(width=0)
        with pytest.raises(ValueError):
            StrokeStyle(opacity=1.5)

    def test_brush_coercion(self):
        assert StrokeStyle(brush="highlighter").brush is Brush.HIGHLIGHTER

    def test_highlighter_preset(self):
        style = StrokeStyle.highlighter()
        assert style.brush is Brush.HIGHLIGHTER and style.opacity < 1.0

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"color": "red"},
            {"color": "#12"},
            {"width": float("inf")},
            {"width": True},
            {"opacity": float("nan")},
        ],
    )
    def test_rejects_invalid_wire_values(self, kwargs):
        with pytest.raises(ValueError):
            StrokeStyle(**kwargs)

    def test_accepts_short_and_long_hex_colors(self):
        assert StrokeStyle(color="#abc").color == "#abc"
        assert StrokeStyle(color="#aabbcc").color == "#aabbcc"


class TestStroke:
    def test_list_points_coerced_to_tuple(self):
        s = Stroke(points=[Point(0, 0), Point(1, 1)])
        assert isinstance(s.points, tuple)

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            Stroke(points=())

    def test_exceeding_max_points_raises(self):
        from neeh.ink.stroke import _MAX_POINTS_PER_STROKE

        with pytest.raises(ValueError, match="point limit"):
            Stroke(points=tuple(Point(i, i) for i in range(_MAX_POINTS_PER_STROKE + 1)))
        # exactly at the limit is still valid
        Stroke(points=tuple(Point(i, i) for i in range(_MAX_POINTS_PER_STROKE)))

    def test_bbox_and_duration(self):
        s = Stroke(points=(Point(0, 0, t_ms=0), Point(10, 5, t_ms=120)))
        assert s.bbox == BoundingBox(0, 0, 10, 5)
        assert s.duration_ms == 120

    def test_translated_preserves_identity(self):
        s = Stroke.from_xy([(0, 0), (10, 10)])
        t = s.translated(5, 5)
        assert t.id == s.id
        assert t.created_at_ms == s.created_at_ms
        assert t.bbox == BoundingBox(5, 5, 15, 15)

    def test_serialization_roundtrip(self):
        s = Stroke(
            points=(Point(0, 0, 0, 0.8), Point(4, 4, 50, 0.9)),
            style=StrokeStyle(color="#ff0000", width=3.5, brush=Brush.MARKER),
            author=Author.AGENT,
        )
        restored = Stroke.from_dict(s.to_dict())
        assert restored == s
        assert restored.author is Author.AGENT

    def test_rejects_invalid_identity_time_and_point_order(self):
        with pytest.raises(ValueError):
            Stroke(points=(Point(0, 0),), id="")
        with pytest.raises(ValueError):
            Stroke(points=(Point(0, 0),), created_at_ms=-1)
        with pytest.raises(ValueError):
            Stroke(points=(Point(0, 0),), created_at_ms=2**63)
        with pytest.raises(ValueError):
            Stroke(points=(Point(0, 0, 5), Point(1, 1, 4)))
