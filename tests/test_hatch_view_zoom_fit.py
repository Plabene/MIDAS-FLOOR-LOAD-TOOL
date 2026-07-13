import inspect
from types import SimpleNamespace

from app.main import FloorLoadAutoApp


def test_hatch_view_removed_manual_buttons_are_not_built():
    source = "\n".join(
        [
            inspect.getsource(FloorLoadAutoApp._build_hatch_view_panel),
            inspect.getsource(FloorLoadAutoApp._build_typical_floor_workbench),
        ]
    )

    assert "선택 해치 확대" not in source
    assert "레이어 색상표시" not in source
    assert "선택 범위 검증" not in source
    assert "추천 연속구간 선택" not in source
    assert "연속층 적용 확정" not in source
    assert "적용 가능층 전체 선택" not in source
    assert "적용 가능층 자동 선택" in source
    assert "<MouseWheel>" in source
    assert "<Button-4>" in source
    assert "<Button-5>" in source


def test_hatch_view_mousewheel_zoom_is_cursor_centered():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_preview_canvas = _Canvas(width=200, height=100)
    app.hatch_view_fit_bbox = (0.0, 0.0, 100.0, 50.0)
    app.hatch_view_view_bbox = (0.0, 0.0, 100.0, 50.0)
    app.hatch_view_manual_zoom = False
    renders = []
    app._render_hatch_preview = lambda **_kwargs: renders.append(True)

    result = app._on_hatch_view_mousewheel(SimpleNamespace(delta=120, x=150, y=50))

    min_x, min_y, max_x, max_y = app.hatch_view_view_bbox
    world_x = 75.0
    world_y = 25.0
    assert result == "break"
    assert app.hatch_view_manual_zoom is True
    assert max_x - min_x < 100.0
    assert max_y - min_y < 50.0
    assert ((world_x - min_x) / (max_x - min_x)) * 200.0 == 150.0
    assert (1.0 - ((world_y - min_y) / (max_y - min_y))) * 100.0 == 50.0
    assert renders == [True]


def test_hatch_view_full_plan_fit_uses_canvas_width():
    app = object.__new__(FloorLoadAutoApp)

    fit_bbox = app._hatch_view_bbox_for_canvas((0.0, 0.0, 100.0, 10.0), 400, 400)
    transform, content_width, content_height = app._hatch_canvas_transform(fit_bbox, 400, 400)
    x0, _y0 = transform(0.0, 0.0)
    x1, _y1 = transform(100.0, 10.0)

    assert content_width == 400
    assert content_height == 400
    assert 0.0 < x0 < 40.0
    assert 360.0 < x1 < 400.0


def test_hatch_view_configure_fit_does_not_reset_manual_zoom():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_fit_bbox = (0.0, 0.0, 100.0, 100.0)
    app.hatch_view_view_bbox = (25.0, 25.0, 75.0, 75.0)
    app.hatch_view_manual_zoom = True

    app._set_hatch_view_fit_bbox((0.0, 0.0, 120.0, 100.0))

    assert app.hatch_view_view_bbox == (25.0, 25.0, 75.0, 75.0)
    assert app.hatch_view_manual_zoom is True


class _Canvas:
    def __init__(self, *, width: int, height: int):
        self._width = width
        self._height = height

    def winfo_width(self):
        return self._width

    def winfo_height(self):
        return self._height
