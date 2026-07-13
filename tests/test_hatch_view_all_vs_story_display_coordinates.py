from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.dxf_story_layout import Affine2D, BBox2D, StoryLayout
from app.core.hatch_region_editor import EditableHatchRegion
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


def test_all_story_and_story_modes_use_different_hatch_coordinates():
    app = _app_with_layouts(mode="ALL")
    region = _load_region("1F")

    assert app._region_display_vertices(region, {}) == [(1000.0, 1000.0), (1010.0, 1000.0), (1010.0, 1010.0), (1000.0, 1010.0)]

    app.hatch_view_display_mode_var.set("STORY")

    assert app._region_display_vertices(region, {}) == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_all_story_and_story_modes_use_different_internal_region_coordinates():
    app = _app_with_layouts(mode="ALL")
    region = EditableHatchRegion(
        region_key="edit-1",
        story_name="1F",
        cell_ids=("cell-1",),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        load_name=None,
        load_layer=None,
        dl=None,
        ll=None,
        distribution="TWO_WAY",
    )

    assert app._hatch_edit_region_display_vertices(region) == [(100.0, 0.0), (110.0, 0.0), (110.0, 10.0), (100.0, 10.0)]

    app.hatch_view_display_mode_var.set("STORY")

    assert app._hatch_edit_region_display_vertices(region) == [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def test_story_mode_render_fit_bbox_does_not_include_other_story_layout_bbox():
    app = _app_with_layouts(mode="STORY")
    region = _load_region("1F")
    app.loaded_regions = [region]
    app.hatch_view_selected_story_var = _Var("1F")
    app.hatch_preview_canvas = _Canvas()
    app.hatch_view_show_full_plan_var = _Var(False)
    app.hatch_view_show_structure_var = _Var(False)
    app.hatch_view_highlight_continuous_var = _Var(False)
    app.hatch_view_manual_zoom = False
    app.hatch_view_fit_bbox = None
    app.hatch_view_view_bbox = None
    app.continuous_hatch_checks = {app._region_key(region, index=1): {"can_select": True}}
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_region_key = ""
    app.hatch_load_drag_hover_key = ""
    app.hatch_edit_states_by_story = {}
    app.hatch_preview_info_var = _Var("")
    app.hatch_preview_legend_var = _Var("")

    app._render_hatch_preview()

    assert app.hatch_view_fit_bbox[2] < 30.0


def _app_with_layouts(*, mode: str):
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = "ALL_STORIES"
    app.generated_dxf_layout_metadata = (_layout("1F", 100.0), _layout("2F", 10000.0))
    app.generated_dxf_story_names = ("1F", "2F")
    app.hatch_view_display_mode_var = _Var(mode)
    app.hatch_view_selected_story_var = _Var("1F")
    app.stories = []
    app.nodes = []
    app.elements = []
    return app


def _layout(story_name: str, dx: float) -> StoryLayout:
    return StoryLayout(
        story_name=story_name,
        story_index=None,
        elevation=None,
        source_bbox=BBox2D(0.0, 0.0, 10.0, 10.0),
        placed_bbox=BBox2D(dx, 0.0, dx + 10.0, 10.0),
        offset_x=dx,
        offset_y=0.0,
        scale=1.0,
        rotation_deg=0.0,
        insertion_x=dx,
        insertion_y=0.0,
        transform=Affine2D(e=dx),
        inverse_transform=Affine2D(e=-dx),
        label_x=dx,
        label_y=0.0,
        text_height=1.0,
    )


def _load_region(story_name: str):
    model_vertices = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    placed_vertices = [(1000.0, 1000.0), (1010.0, 1000.0), (1010.0, 1010.0), (1000.0, 1010.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle="A",
        vertices=model_vertices,
        polygon=Polygon(model_vertices),
        area=100.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        story_name=story_name,
        source_id="A",
        placed_vertices=placed_vertices,
        placed_bbox=(1000.0, 1000.0, 1010.0, 1010.0),
        model_bbox=(0.0, 0.0, 10.0, 10.0),
        transform_applied=True,
    )
    load = LoadLayerInfo(layer=hatch.layer, real_name="A", dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Canvas:
    def __init__(self):
        self.calls = []

    def winfo_exists(self):
        return True

    def winfo_width(self):
        return 400

    def winfo_height(self):
        return 400

    def delete(self, *args):
        self.calls.append(("delete", args))

    def configure(self, **kwargs):
        self.calls.append(("configure", kwargs))

    def create_text(self, *args, **kwargs):
        self.calls.append(("text", args, kwargs))

    def create_polygon(self, *args, **kwargs):
        self.calls.append(("polygon", args, kwargs))
        return len(self.calls)

    def create_rectangle(self, *args, **kwargs):
        self.calls.append(("rectangle", args, kwargs))
        return len(self.calls)

    def create_line(self, *args, **kwargs):
        self.calls.append(("line", args, kwargs))
        return len(self.calls)
