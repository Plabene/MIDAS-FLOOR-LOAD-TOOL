from app.main import FloorLoadAutoApp


def test_beam_with_width_draws_blue_stipple_fill_and_outline():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _Canvas()

    app._draw_hatch_structure_items(
        canvas,
        [{"kind": "BEAM", "points": [(0.0, 0.0), (10.0, 0.0)], "width": 10.0}],
        lambda x, y: (x, y),
    )

    polygon = _first_call(canvas, "polygon")
    line = _first_call(canvas, "line")
    assert polygon["kwargs"]["fill"] == "#93c5fd"
    assert polygon["kwargs"]["stipple"] == "gray25"
    assert "structure_fill" in polygon["kwargs"]["tags"]
    assert line["kwargs"]["fill"] == "#1d4ed8"
    assert line["kwargs"]["width"] <= 2


def test_wall_with_width_draws_pink_stipple_fill_and_outline():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _Canvas()

    app._draw_hatch_structure_items(
        canvas,
        [{"kind": "WALL", "points": [(0.0, 0.0), (10.0, 0.0)], "width": 10.0}],
        lambda x, y: (x, y),
    )

    polygon = _first_call(canvas, "polygon")
    line = _first_call(canvas, "line")
    assert polygon["kwargs"]["fill"] == "#f9a8d4"
    assert polygon["kwargs"]["stipple"] == "gray25"
    assert line["kwargs"]["fill"] == "#be185d"
    assert line["kwargs"]["width"] <= 2


def test_beam_without_width_draws_centerline_without_fill():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _Canvas()

    app._draw_hatch_structure_items(
        canvas,
        [{"kind": "BEAM", "points": [(0.0, 0.0), (10.0, 0.0)], "width": None}],
        lambda x, y: (x, y),
    )

    assert not [call for call in canvas.calls if call["kind"] == "polygon"]
    line = _first_call(canvas, "line")
    assert line["kwargs"]["fill"] == "#1d4ed8"
    assert line["kwargs"]["width"] == 2


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


def _first_call(canvas, kind: str):
    return next(call for call in canvas.calls if call["kind"] == kind)
