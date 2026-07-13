from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.hatch_region_editor import EditableHatchRegion
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


def test_dxf_hatch_checkboxes_scale_with_rendered_region_size_in_all_story_view():
    app = _app(mode="ALL")
    small = _load_region("S", 0.0, 0.0, 5.0)
    large = _load_region("L", 20.0, 0.0, 100.0)
    app.loaded_regions = [small, large]
    app.continuous_hatch_checks = {
        app._region_key(small, index=1): {"can_select": True},
        app._region_key(large, index=2): {"can_select": True},
    }

    app._render_hatch_preview()

    check_rects = [
        call
        for call in app.hatch_preview_canvas.rectangles
        if "hatch_check" in tuple(call["kwargs"].get("tags", ()))
    ]
    small_size = _rect_size(check_rects[0]["args"])
    large_size = _rect_size(check_rects[1]["args"])

    assert small_size < large_size
    assert small_size <= 16.0
    assert small_size >= 5.0


def test_checkbox_metrics_keep_story_view_click_target_usable():
    app = _app(mode="STORY")

    half_size, font_size, show_text = app._hatch_checkbox_canvas_metrics(
        [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)],
        lambda x, y: (x, y),
    )

    assert half_size * 2.0 >= 10.0
    assert font_size >= 6
    assert show_text


def test_internal_hatch_checkboxes_use_same_scaling_helper():
    app = _app(mode="ALL")
    canvas = _Canvas()
    app.hatch_view_edit_region_items = {}
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_load_drag_hover_key = ""
    small = _editable_region("small", 2.0)
    large = _editable_region("large", 80.0)

    app._draw_hatch_edit_regions(
        canvas,
        [
            ("small", small, small.polygon_xy),
            ("large", large, large.polygon_xy),
        ],
        lambda x, y: (x, y),
        {},
    )

    small_size = _rect_size(canvas.rectangles[0]["args"])
    large_size = _rect_size(canvas.rectangles[1]["args"])

    assert small_size < large_size
    assert small_size <= 16.0
    assert small_size >= 5.0


def _app(*, mode: str):
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = "ALL_STORIES"
    app.generated_dxf_story_names = ("1F",)
    app.generated_dxf_layout_metadata = ()
    app.hatch_view_display_mode_var = _Var(mode)
    app.hatch_view_selected_story_var = _Var("1F")
    app.hatch_view_show_full_plan_var = _Var(False)
    app.hatch_view_show_structure_var = _Var(False)
    app.hatch_view_highlight_continuous_var = _Var(False)
    app.hatch_view_show_legend_var = _Var(False)
    app.hatch_view_focus_selected_var = _Var(False)
    app.hatch_view_manual_zoom = False
    app.hatch_view_fit_bbox = None
    app.hatch_view_view_bbox = None
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_region_key = ""
    app.hatch_load_drag_hover_key = ""
    app.hatch_edit_states_by_story = {}
    app.stories = []
    app.nodes = []
    app.elements = []
    app.typical_floor_groups = ()
    app.hatch_preview_canvas = _Canvas()
    app.hatch_preview_info_var = _Var("")
    app.hatch_preview_legend_var = _Var("")
    app.loaded_regions = []
    app.continuous_hatch_checks = {}
    return app


def _load_region(source_id: str, x: float, y: float, size: float):
    vertices = [(x, y), (x + size, y), (x + size, y + size), (x, y + size)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer=f"LOAD_{source_id}_DL_1_LL_1",
        handle=source_id,
        vertices=vertices,
        polygon=Polygon(vertices),
        area=size * size,
        bbox=(x, y, x + size, y + size),
        story_name="1F",
        source_id=source_id,
    )
    return LoadRegion(
        region=hatch,
        load=LoadLayerInfo(layer=hatch.layer, real_name=source_id, dl=1.0, ll=1.0, source="test"),
        status="OK",
        warnings=[],
    )


def _editable_region(region_key: str, size: float):
    return EditableHatchRegion(
        region_key=region_key,
        story_name="1F",
        cell_ids=(region_key,),
        polygon_xy=((0.0, 0.0), (size, 0.0), (size, size), (0.0, size)),
        load_name=None,
        load_layer=None,
        dl=None,
        ll=None,
        distribution="TWO_WAY",
    )


def _rect_size(args) -> float:
    x1, _y1, x2, _y2 = [float(value) for value in args[:4]]
    return abs(x2 - x1)


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Canvas:
    def __init__(self):
        self.rectangles = []
        self._next_id = 1

    def winfo_exists(self):
        return True

    def winfo_width(self):
        return 800

    def winfo_height(self):
        return 600

    def delete(self, *_args):
        self.rectangles.clear()

    def configure(self, **_kwargs):
        return None

    def create_polygon(self, *_args, **_kwargs):
        return self._id()

    def create_rectangle(self, *args, **kwargs):
        self.rectangles.append({"args": args, "kwargs": kwargs})
        return self._id()

    def create_text(self, *_args, **_kwargs):
        return self._id()

    def create_line(self, *_args, **_kwargs):
        return self._id()

    def create_oval(self, *_args, **_kwargs):
        return self._id()

    def _id(self):
        value = self._next_id
        self._next_id += 1
        return value
