from app.main import FloorLoadAutoApp, HATCH_VIEW_STRUCTURE_STYLE


def test_column_style_uses_strong_green_fill_and_marker_colors():
    style = HATCH_VIEW_STRUCTURE_STYLE["COLUMN"]

    assert style["fill"] == "#22c55e"
    assert style["outline"] == "#064e3b"
    assert style["stroke_width"] >= 3
    assert style["marker_fill"] == "#16a34a"
    assert style["marker_outline"] == "#052e16"


def test_column_with_section_size_draws_footprint_fill_and_center_marker():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _Canvas()

    app._draw_hatch_structure_items(
        canvas,
        [{"kind": "COLUMN", "points": [(10.0, 20.0)], "width": 0.5, "depth": 0.7}],
        lambda x, y: (x * 100.0, y * 100.0),
    )

    rectangles = [call for call in canvas.calls if call["kind"] == "rectangle"]
    assert len(rectangles) == 2
    footprint = rectangles[0]
    marker = rectangles[1]
    assert footprint["kwargs"]["fill"] == "#22c55e"
    assert footprint["kwargs"]["outline"] == "#064e3b"
    assert footprint["kwargs"]["stipple"] == "gray12"
    assert footprint["kwargs"]["width"] == 3
    assert "structure_fill" in footprint["kwargs"]["tags"]
    assert marker["kwargs"]["fill"] == "#16a34a"
    assert "structure_marker" in marker["kwargs"]["tags"]


def test_column_without_section_size_draws_visible_fallback_and_marker():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _Canvas()

    app._draw_hatch_structure_items(
        canvas,
        [{"kind": "COLUMN", "points": [(10.0, 20.0)], "width": None, "depth": None}],
        lambda x, y: (x, y),
    )

    oval = next(call for call in canvas.calls if call["kind"] == "oval")
    marker = next(call for call in canvas.calls if call["kind"] == "rectangle")
    assert oval["kwargs"]["fill"] == "#22c55e"
    assert oval["kwargs"]["stipple"] == "gray12"
    assert marker["kwargs"]["fill"] == "#16a34a"


class _Canvas:
    def __init__(self):
        self.calls = []

    def create_line(self, *args, **kwargs):
        self.calls.append({"kind": "line", "args": args, "kwargs": kwargs})

    def create_polygon(self, *args, **kwargs):
        self.calls.append({"kind": "polygon", "args": args, "kwargs": kwargs})

    def create_rectangle(self, *args, **kwargs):
        self.calls.append({"kind": "rectangle", "args": args, "kwargs": kwargs})

    def create_oval(self, *args, **kwargs):
        self.calls.append({"kind": "oval", "args": args, "kwargs": kwargs})
