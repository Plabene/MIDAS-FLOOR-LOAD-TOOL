from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp


def test_story_below_element_index_cache_is_reused_on_second_call():
    app = _bare_app()
    app.stories = [Story("1F", 0.0), Story("2F", 3.0)]
    app.nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
    ]
    app.elements = [
        Element(1, "PLATE", node_ids=(1, 2, 12, 11)),
        Element(2, "BEAM", node_ids=(11, 12)),
    ]

    first = app._story_below_elements_for_story("2F")
    second = app._story_below_elements_for_story("2F")

    assert [element.elem_id for element in first] == [1, 2]
    assert [element.elem_id for element in second] == [1, 2]
    assert app._story_below_element_index_cache_misses == 1
    assert app._story_below_element_index_cache_hits >= 1


def test_matching_target_cell_geometry_cache_reuses_second_call():
    app = _bare_app()
    source = SimpleNamespace(
        region_key="edit:1F:C1",
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
    )
    target_state = SimpleNamespace(
        story_name="2F",
        cells_by_id={
            "C1": SimpleNamespace(
                polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
            )
        },
    )

    first = app._matching_target_cell_geometry_for_region(source, target_state)
    second = app._matching_target_cell_geometry_for_region(source, target_state)

    assert first[0] == ("C1",)
    assert second == first
    assert app._matching_target_cell_geometry_cache_misses == 1
    assert app._matching_target_cell_geometry_cache_hits == 1


def test_hatch_viewport_culling_skips_offscreen_region_items():
    app = _render_app()
    visible = _load_region("visible", _quad(0.0, 0.0, 10.0, 10.0))
    offscreen = _load_region("offscreen", _quad(1000.0, 1000.0, 1010.0, 1010.0))
    app.loaded_regions = [visible, offscreen]
    app.continuous_hatch_checks = {
        app._region_key(region, index=index): {"can_select": True}
        for index, region in enumerate(app.loaded_regions, start=1)
    }
    app.hatch_preview_canvas = _Canvas()

    app._render_hatch_preview()

    assert len(app.hatch_preview_canvas.polygons) == 1
    assert len(app.hatch_view_region_by_key) == 2
    assert len(app.hatch_view_region_items) == 1


def test_display_simplification_does_not_mutate_source_polygon_vertices():
    app = _render_app()
    points = tuple((float(index), 0.0) for index in range(12)) + (
        (11.0, 10.0),
        (0.0, 10.0),
    )
    region = _load_region("dense", points)
    original_vertices = tuple(region.region.vertices)
    app.loaded_regions = [region]
    app.continuous_hatch_checks = {app._region_key(region, index=1): {"can_select": True}}
    app.hatch_preview_canvas = _Canvas()

    app._render_hatch_preview()

    assert tuple(region.region.vertices) == original_vertices


def _bare_app():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = []
    app.nodes = []
    app.elements = []
    app.loaded_regions = []
    app.hatch_edit_states_by_story = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_region_by_key = {}
    app.current_mgt_text = ""
    app.story_tol_var = _Var(0.01)
    app.snap_tol_var = _Var(0.5)
    app.generated_dxf_layout_metadata = ()
    app.generated_dxf_mode = None
    app.hatch_view_display_mode_var = _Var("STORY")
    app.hatch_view_selected_story_var = _Var("1F")
    app.logger = SimpleNamespace(debug=lambda *args, **kwargs: None, warning=lambda *args, **kwargs: None)
    app._story_below_element_index_cache_hits = 0
    app._story_below_element_index_cache_misses = 0
    app._matching_target_cell_geometry_cache_hits = 0
    app._matching_target_cell_geometry_cache_misses = 0
    app._hatch_state_version = 0
    return app


def _render_app():
    app = _bare_app()
    app.stories = [Story("1F", 0.0)]
    app.hatch_view_show_structure_var = _Var(False)
    app.hatch_view_show_full_plan_var = _Var(False)
    app.hatch_view_show_legend_var = _Var(False)
    app.hatch_view_highlight_continuous_var = _Var(False)
    app.hatch_view_focus_selected_var = _Var(False)
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_load_drag_hover_key = ""
    app.hatch_view_manual_zoom = True
    app.hatch_view_fit_bbox = (0.0, 0.0, 20.0, 20.0)
    app.hatch_view_view_bbox = (0.0, 0.0, 20.0, 20.0)
    app.hatch_preview_info_var = _Var()
    app.hatch_preview_legend_var = _Var()
    app.continuous_hatch_checks = {}
    app.continuous_active_visible_targets = ()
    app._draw_hatch_structure_items = lambda *args, **kwargs: None
    app._draw_hatch_story_labels = lambda *args, **kwargs: None
    app._draw_hatch_legend = lambda *args, **kwargs: None
    return app


def _load_region(source_id: str, points):
    polygon = Polygon(points)
    load = LoadLayerInfo(layer=f"LOAD_{source_id}", real_name=source_id, dl=1.0, ll=1.0)
    return LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer=f"LOAD_{source_id}",
            handle=source_id,
            vertices=list(points),
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(value) for value in polygon.bounds),
            story_name="1F",
            source_id=source_id,
        ),
        load=load,
        status="OK",
        warnings=[],
    )


def _quad(x1, y1, x2, y2):
    return ((float(x1), float(y1)), (float(x2), float(y1)), (float(x2), float(y2)), (float(x1), float(y2)))


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Canvas:
    def __init__(self):
        self.polygons = []
        self.rectangles = []
        self.texts = []
        self.lines = []
        self._next_id = 1

    def winfo_exists(self):
        return True

    def winfo_width(self):
        return 500

    def winfo_height(self):
        return 500

    def canvasx(self, value):
        return value

    def canvasy(self, value):
        return value

    def delete(self, *_args):
        self.polygons.clear()
        self.rectangles.clear()
        self.texts.clear()
        self.lines.clear()

    def configure(self, **_kwargs):
        return None

    def create_polygon(self, *args, **kwargs):
        self.polygons.append((args, kwargs))
        return self._id()

    def create_rectangle(self, *args, **kwargs):
        self.rectangles.append((args, kwargs))
        return self._id()

    def create_text(self, *args, **kwargs):
        self.texts.append((args, kwargs))
        return self._id()

    def create_line(self, *args, **kwargs):
        self.lines.append((args, kwargs))
        return self._id()

    def tag_bind(self, *_args):
        return None

    def tag_raise(self, *_args):
        return None

    def _id(self):
        value = self._next_id
        self._next_id += 1
        return value
