from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.closed_region_detector import ClosedCell
from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.hatch_region_editor import create_edit_state
from app.main import FloorLoadAutoApp


def test_dragged_load_item_applies_to_dxf_hatch_region_and_rerenders():
    app = object.__new__(FloorLoadAutoApp)
    region = _load_region()
    region_key = app._region_key(region, index=1)
    app.hatch_view_region_by_key = {region_key: region}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.final_load_items = [{"key": "office", "display_name": "Office", "name": "Office", "dl": 1.2, "ll": 3.4}]
    app.continuous_hatch_checks = {}
    app.hatch_preview_info_var = _Var()
    app.continuous_apply_status_var = _Var()
    renders = []
    app._render_hatch_preview = lambda *args, **kwargs: renders.append(kwargs)

    app._apply_dragged_load_to_hatch_region(dict(app.final_load_items[0]), region_key)

    assert region.load is not None
    assert region.load.real_name == "Office"
    assert region.load.dl == 1.2
    assert region.load.ll == 3.4
    assert app.hatch_view_selected_region_key == region_key
    assert renders == [{"focus_region_key": region_key}]
    assert "자동 저장됨" in app.hatch_preview_info_var.value


def test_dragged_load_on_selected_internal_region_applies_to_all_selected_internal_regions():
    app = _app_with_internal_regions()
    keys = tuple(app.hatch_view_selected_edit_region_keys)

    app._apply_dragged_load_to_hatch_region(_load_item("Office", 1.2, 3.4), keys[0])

    state = app.hatch_edit_states_by_story["1F"]
    loaded_regions = [region for region in state.regions_by_key.values() if region.load_name]
    assert len(loaded_regions) == 1
    assert loaded_regions[0].load_name == "Office"
    assert set(loaded_regions[0].cell_ids) == {"A", "B"}
    assert app.hatch_view_selected_edit_region_keys == set(state.selected_region_keys)
    assert "선택 해치 2개" in app.hatch_preview_info_var.value


def test_dragged_load_on_selected_dxf_region_applies_to_all_selected_dxf_regions():
    app = _app_with_dxf_regions()
    keys = tuple(app.hatch_view_selected_region_keys)

    app._apply_dragged_load_to_hatch_region(_load_item("Retail", 2.5, 4.5), keys[0])

    assert [region.load.real_name for region in app.loaded_regions[:2]] == ["Retail", "Retail"]
    assert app.loaded_regions[2].load is None


def test_dragged_load_on_unselected_dxf_region_keeps_single_target_behavior():
    app = _app_with_dxf_regions()
    selected_keys = set(app.hatch_view_selected_region_keys)
    third_key = [key for key in app.hatch_view_region_by_key if key not in selected_keys][0]

    app._apply_dragged_load_to_hatch_region(_load_item("Storage", 1.0, 2.0), third_key)

    assert [region.load for region in app.loaded_regions[:2]] == [None, None]
    assert app.loaded_regions[2].load.real_name == "Storage"


def test_drag_release_always_destroys_drag_ghost():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_load_drag_item = {"display_name": "Office"}
    app.hatch_load_drag_start = (0.0, 0.0)
    app.hatch_load_drag_active = False
    app.hatch_load_drag_hover_key = None
    destroyed = []
    app._destroy_hatch_load_drag_ghost = lambda: destroyed.append(True)
    app._root_point_to_hatch_canvas_point = lambda _x, _y: None
    app._hatch_region_key_at_canvas_point = lambda _x, _y: None
    app._render_hatch_preview = lambda *args, **kwargs: None

    app._on_hatch_load_drag_release(SimpleNamespace(x_root=1, y_root=1))

    assert destroyed == [True]


def test_drag_motion_hover_key_change_rerenders_and_release_clears_hover():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_load_drag_item = {"display_name": "Office"}
    app.hatch_load_drag_start = (0.0, 0.0)
    app.hatch_load_drag_active = False
    app.hatch_load_drag_hover_key = None
    app.hatch_preview_info_var = _Var()
    app.continuous_apply_status_var = _Var()
    renders = []
    applied = []
    app._root_point_to_hatch_canvas_point = lambda _x, _y: (5.0, 5.0)
    app._hatch_region_key_at_canvas_point = lambda _x, _y: "R1"
    app._render_hatch_preview = lambda *args, **kwargs: renders.append(kwargs)
    app._apply_dragged_load_to_hatch_region = lambda item, key: applied.append((item, key))

    app._on_hatch_load_drag_motion(SimpleNamespace(x_root=10, y_root=10))
    app._on_hatch_load_drag_motion(SimpleNamespace(x_root=11, y_root=11))
    app._on_hatch_load_drag_release(SimpleNamespace(x_root=12, y_root=12))

    assert app.hatch_load_drag_hover_key is None
    assert len(renders) == 2
    assert applied == [({"display_name": "Office"}, "R1")]


def test_hatch_view_hover_key_uses_hover_polygon_style():
    app = object.__new__(FloorLoadAutoApp)
    region = _load_region()
    region_key = app._region_key(region, index=1)
    app.loaded_regions = [region]
    app.hatch_view_selected_region_key = ""
    app.hatch_load_drag_hover_key = region_key
    app.hatch_edit_states_by_story = {}
    app.generated_dxf_story_names = ()
    app.generated_dxf_layout_metadata = ()
    app.generated_dxf_mode = None
    app.stories = []
    app.nodes = []
    app.elements = []
    app.continuous_hatch_checks = {region_key: {"can_select": True, "applicable_targets": ("2F",), "blocked_targets": ()}}
    app.hatch_view_highlight_continuous_var = SimpleNamespace(get=lambda: False)
    app.hatch_view_show_structure_var = SimpleNamespace(get=lambda: False)
    app.hatch_preview_info_var = _Var()
    app.hatch_preview_legend_var = _Var()
    app.hatch_preview_canvas = _RenderCanvas()

    app._render_hatch_preview()

    hover_polygons = [
        kwargs
        for _args, kwargs in app.hatch_preview_canvas.polygons
        if kwargs.get("tags") == ("hatch_region", f"region:{region_key}")
    ]
    assert hover_polygons
    assert hover_polygons[0]["outline"] == "#fbbc04"
    assert hover_polygons[0]["width"] == 4
    assert hover_polygons[0]["dash"] == (4, 2)


def _app_with_internal_regions():
    app = object.__new__(FloorLoadAutoApp)
    state = create_edit_state("1F", [_cell("A", 0.0), _cell("B", 10.0)])
    keys = set(state.regions_by_key)
    state.selected_region_keys = set(keys)
    state.selected_cell_ids = {"A", "B"}
    app.hatch_edit_states_by_story = {"1F": state}
    app.hatch_view_edit_region_by_key = dict(state.regions_by_key)
    app.hatch_view_selected_edit_region_keys = set(keys)
    app.hatch_view_region_by_key = {}
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.loaded_regions = []
    app.stories = []
    app.nodes = []
    app.elements = []
    app.generated_dxf_story_names = ()
    app.continuous_apply_targets_by_region = {}
    app.continuous_materialized_targets_by_region = {}
    app.continuous_active_visible_targets = ()
    app.continuous_active_region_key = None
    app.continuous_active_region_keys = ()
    app.continuous_base_story_name = _Var("1F")
    app.final_load_items = []
    app.hatch_preview_info_var = _Var()
    app.continuous_apply_status_var = _Var()
    app._render_hatch_preview = lambda *args, **kwargs: None
    app._refresh_selected_hatch_continuous_info = lambda *args, **kwargs: None
    return app


def _app_with_dxf_regions():
    app = object.__new__(FloorLoadAutoApp)
    regions = [_load_region("A", 0.0), _load_region("B", 20.0), _load_region("C", 40.0)]
    app.loaded_regions = regions
    app.hatch_view_region_by_key = {app._region_key(region, index=index): region for index, region in enumerate(regions, start=1)}
    first_two = tuple(app.hatch_view_region_by_key)[:2]
    app.hatch_view_selected_region_keys = set(first_two)
    app.hatch_view_selected_region_key = first_two[0]
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.stories = []
    app.nodes = []
    app.elements = []
    app.generated_dxf_story_names = ()
    app.continuous_apply_targets_by_region = {}
    app.continuous_materialized_targets_by_region = {}
    app.continuous_active_visible_targets = ()
    app.continuous_active_region_key = None
    app.continuous_active_region_keys = ()
    app.continuous_base_story_name = _Var("1F")
    app.final_load_items = []
    app.hatch_preview_info_var = _Var()
    app.continuous_apply_status_var = _Var()
    app._render_hatch_preview = lambda *args, **kwargs: None
    app._refresh_selected_hatch_continuous_info = lambda *args, **kwargs: None
    return app


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _RenderCanvas:
    def __init__(self):
        self.polygons = []
        self._next_id = 1

    def winfo_width(self):
        return 640

    def winfo_height(self):
        return 520

    def delete(self, *_args):
        self.polygons.clear()

    def configure(self, **_kwargs):
        return None

    def create_polygon(self, *args, **kwargs):
        self.polygons.append((args, kwargs))
        value = self._next_id
        self._next_id += 1
        return value

    def create_text(self, *_args, **_kwargs):
        value = self._next_id
        self._next_id += 1
        return value

    def create_rectangle(self, *_args, **_kwargs):
        value = self._next_id
        self._next_id += 1
        return value


def _cell(cell_id: str, x0: float) -> ClosedCell:
    return ClosedCell(
        cell_id=cell_id,
        story_name="1F",
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=((x0, 0.0), (x0 + 10.0, 0.0), (x0 + 10.0, 10.0), (x0, 10.0)),
        area=100.0,
        centroid=(x0 + 5.0, 5.0),
        boundary_element_ids=(),
    )


def _load_item(name: str, dl: float, ll: float):
    return {"key": f"MODEL::{name}", "display_name": name, "name": name, "dl": dl, "ll": ll}


def _load_region(handle="A", x0=0.0):
    vertices = [(x0, 0.0), (x0 + 10.0, 0.0), (x0 + 10.0, 10.0), (x0, 10.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="",
        handle=handle,
        vertices=vertices,
        polygon=Polygon(vertices),
        area=100.0,
        bbox=(x0, 0.0, x0 + 10.0, 10.0),
        story_name="1F",
        source_id=handle,
    )
    return LoadRegion(region=hatch, load=None, status="NO_LOAD", warnings=[])
