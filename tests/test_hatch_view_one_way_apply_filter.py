from shapely.geometry import Polygon

from app.core.closed_region_detector import ClosedCell
from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.hatch_region_editor import apply_load_to_selection, create_edit_state
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


def test_internal_one_way_apply_filters_non_tri_quad_and_preserves_existing_load():
    app = _base_app()
    state = create_edit_state("1F", [_cell("Q", _quad(0, 0, 10, 10)), _cell("P", _pentagon(20, 0))])
    pentagon_key = [key for key, region in state.regions_by_key.items() if region.cell_ids == ("P",)][0]
    state.selected_region_keys = {pentagon_key}
    state.selected_cell_ids = {"P"}
    state = apply_load_to_selection(state, load_name="Old", load_layer="LOAD_Old", dl=1.0, ll=1.0)
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = {"Q", "P"}
    app.hatch_edit_states_by_story = {"1F": state}
    app.hatch_view_edit_region_by_key = dict(state.regions_by_key)
    app.hatch_view_selected_edit_region_keys = set(state.regions_by_key)

    assert app._apply_hatch_load_item_to_selected_regions(_one_way_item("New")) is True

    loaded = {region.cell_ids: region for region in app.hatch_edit_states_by_story["1F"].regions_by_key.values() if region.load_name}
    assert loaded[("Q",)].load_name == "New"
    assert loaded[("Q",)].distribution == "ONE_WAY"
    assert loaded[("P",)].load_name == "Old"
    assert "선택 2개 중 1개 적용" in app.hatch_preview_info_var.value
    assert "1개 제외" in app.hatch_preview_info_var.value


def test_dxf_one_way_apply_filters_non_tri_quad_and_preserves_existing_load():
    app = _base_app()
    quad = _load_region("Q", _quad(0, 0, 10, 10), load=None)
    pentagon = _load_region("P", _pentagon(20, 0), load=_load("Old"))
    app.loaded_regions = [quad, pentagon]
    app.hatch_view_region_by_key = {app._region_key(region, index=index): region for index, region in enumerate(app.loaded_regions, start=1)}
    app.hatch_view_selected_region_keys = set(app.hatch_view_region_by_key)
    app.hatch_view_selected_region_key = next(iter(app.hatch_view_region_by_key))

    assert app._apply_load_item_to_dxf_regions(_one_way_item("New"), tuple(app.hatch_view_region_by_key)) is True

    assert quad.load.real_name == "New"
    assert quad.load.distribution == "ONE_WAY"
    assert quad.load.one_way_angle_deg is not None
    assert pentagon.load.real_name == "Old"
    assert pentagon.load.distribution == "TWO_WAY"
    assert "선택 2개 중 1개 적용" in app.hatch_preview_info_var.value
    assert "1개 제외" in app.hatch_preview_info_var.value


def test_tree_activate_applies_one_way_to_selected_dxf_region():
    app = _base_app()
    app.hatch_one_way_mode_var = _Var(True)
    quad = _load_region("Q", _quad(0, 0, 10, 10), load=None)
    app.loaded_regions = [quad]
    key = app._region_key(quad, index=1)
    app.hatch_view_region_by_key = {key: quad}
    app.hatch_view_selected_region_keys = {key}
    app._selected_hatch_load_item = lambda: {"display_name": "New", "name": "New", "dl": 2.0, "ll": 3.0}

    assert app._on_hatch_load_tree_activate() == "break"

    assert quad.load.real_name == "New"
    assert quad.load.distribution == "ONE_WAY"
    assert quad.load.one_way_angle_deg is not None


def test_tree_activate_rejects_one_way_dxf_pentagon_and_preserves_load():
    app = _base_app()
    app.hatch_one_way_mode_var = _Var(True)
    pentagon = _load_region("P", _pentagon(20, 0), load=_load("Old"))
    app.loaded_regions = [pentagon]
    key = app._region_key(pentagon, index=1)
    app.hatch_view_region_by_key = {key: pentagon}
    app.hatch_view_selected_region_keys = {key}
    app._selected_hatch_load_item = lambda: {"display_name": "New", "name": "New", "dl": 2.0, "ll": 3.0}

    assert app._on_hatch_load_tree_activate() == "break"

    assert pentagon.load.real_name == "Old"
    assert pentagon.load.distribution == "TWO_WAY"
    assert "적용 가능한 선택 영역이 없습니다" in app.hatch_preview_info_var.value


def test_continuous_internal_one_way_target_guard_preserves_non_tri_quad_cell_load():
    app = _base_app()
    app.snap_tol_var = _Var(0.5)
    source_state = create_edit_state("1F", [_cell("P", _pentagon(0, 0))])
    source_region = next(iter(source_state.regions_by_key.values()))
    target_state = create_edit_state("2F", [_cell("P", _pentagon(0, 0), story_name="2F")])
    target_state.selected_region_keys = set(target_state.regions_by_key)
    target_state.selected_cell_ids = {"P"}
    target_state = apply_load_to_selection(target_state, load_name="Old", load_layer="LOAD_Old", dl=1.0, ll=1.0)
    target_state.selected_region_keys = set()
    target_state.selected_cell_ids = set()
    app.hatch_edit_states_by_story = {"2F": target_state}

    applied = app._apply_or_remove_continuous_load_to_target_edit_region(
        base_region_key=source_region.region_key,
        source_region=source_region,
        target_story="2F",
        payload=_one_way_item("New"),
        remove=False,
    )

    assert applied is False
    loaded = next(region for region in app.hatch_edit_states_by_story["2F"].regions_by_key.values() if region.load_name)
    assert loaded.load_name == "Old"
    assert "ONE-WAY 연속층 하중" in app.continuous_apply_status_var.value


def _base_app():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_one_way_mode_var = _Var(False)
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_region_by_key = {}
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


def _cell(cell_id: str, points, *, story_name: str = "1F"):
    polygon = Polygon(points)
    return ClosedCell(
        cell_id=cell_id,
        story_name=story_name,
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=tuple(points),
        area=float(polygon.area),
        centroid=(float(polygon.centroid.x), float(polygon.centroid.y)),
        boundary_element_ids=(),
    )


def _load_region(source_id: str, points, *, load):
    polygon = Polygon(points)
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
        status="OK" if load else "NO_LOAD",
        warnings=[],
    )


def _load(name: str):
    return LoadLayerInfo(layer=f"LOAD_{name}", real_name=name, dl=1.0, ll=1.0, distribution="TWO_WAY")


def _one_way_item(name: str):
    return {"key": name, "display_name": name, "name": name, "dl": 2.0, "ll": 3.0, "distribution": "ONE_WAY"}


def _quad(x1, y1, x2, y2):
    return ((float(x1), float(y1)), (float(x2), float(y1)), (float(x2), float(y2)), (float(x1), float(y2)))


def _pentagon(x, y):
    return ((x, y), (x + 4, y), (x + 6, y + 3), (x + 3, y + 6), (x, y + 4))


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
