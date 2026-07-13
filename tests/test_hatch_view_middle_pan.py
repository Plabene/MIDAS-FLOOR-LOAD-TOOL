from types import SimpleNamespace

from app.main import FloorLoadAutoApp


def test_middle_button_pan_moves_view_bbox_and_sets_manual_zoom():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_preview_canvas = _Canvas()
    app.hatch_view_fit_bbox = (0.0, 0.0, 100.0, 50.0)
    app.hatch_view_view_bbox = (0.0, 0.0, 100.0, 50.0)
    app.hatch_view_manual_zoom = False
    renders = []
    app._render_hatch_preview = lambda *args, **kwargs: renders.append(kwargs)

    assert app._on_hatch_view_middle_pan_start(SimpleNamespace(x=50, y=25, widget=app.hatch_preview_canvas)) == "break"
    assert app.hatch_view_middle_pan_active is True

    assert app._on_hatch_view_middle_pan_drag(SimpleNamespace(x=70, y=35, widget=app.hatch_preview_canvas)) == "break"

    assert app.hatch_view_view_bbox == (-10.0, 5.0, 90.0, 55.0)
    assert app.hatch_view_manual_zoom is True
    assert renders == [{}]
    assert app._on_hatch_view_middle_pan_end(SimpleNamespace(widget=app.hatch_preview_canvas)) == "break"
    assert app.hatch_view_middle_pan_active is False
    assert app.hatch_view_middle_pan_last is None


def test_middle_pan_does_not_create_left_drag_rectangle():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_preview_canvas = _Canvas()
    app.hatch_view_fit_bbox = (0.0, 0.0, 100.0, 50.0)
    app.hatch_view_view_bbox = (0.0, 0.0, 100.0, 50.0)
    app._render_hatch_preview = lambda *args, **kwargs: None

    app._on_hatch_view_middle_pan_start(SimpleNamespace(x=10, y=10, widget=app.hatch_preview_canvas))
    app._on_hatch_view_middle_pan_drag(SimpleNamespace(x=15, y=15, widget=app.hatch_preview_canvas))

    assert "hatch_view_drag_item" not in app.__dict__
    assert app.hatch_preview_canvas.rectangles == []


class _Canvas:
    def __init__(self):
        self.configs = []
        self.rectangles = []

    def winfo_width(self):
        return 200

    def winfo_height(self):
        return 100

    def configure(self, **kwargs):
        self.configs.append(kwargs)

    def create_rectangle(self, *args, **kwargs):
        self.rectangles.append((args, kwargs))
        return len(self.rectangles)
