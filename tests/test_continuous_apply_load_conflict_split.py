from app.core.closed_region_detector import ClosedCell
from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.hatch_region_editor import apply_load_to_selection, create_edit_state
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp
from shapely.geometry import Polygon


def test_continuous_conflict_replaces_only_matching_cells_and_keeps_non_overlapping_load():
    app = object.__new__(FloorLoadAutoApp)
    base_state = create_edit_state("5F", [_cell("B", 10.0, "5F"), _cell("C", 20.0, "5F")])
    base_state.selected_region_keys = set(base_state.regions_by_key)
    base_state.selected_cell_ids = {"B", "C"}
    base_state = apply_load_to_selection(base_state, load_name="Office", load_layer="LOAD_Office", dl=1.2, ll=3.4)
    base_region = next(region for region in base_state.regions_by_key.values() if region.load_name)

    target_state = create_edit_state("6F", [_cell("A", 0.0, "6F"), _cell("B", 10.0, "6F"), _cell("C", 20.0, "6F"), _cell("D", 30.0, "6F")])
    target_state.selected_region_keys = set(target_state.regions_by_key)
    target_state.selected_cell_ids = {"A", "B", "C", "D"}
    target_state = apply_load_to_selection(target_state, load_name="Lobby", load_layer="LOAD_Lobby", dl=2.0, ll=4.0)
    target_state.selected_region_keys = set()
    target_state.selected_cell_ids = set()

    app.hatch_edit_states_by_story = {"5F": base_state, "6F": target_state}
    app.hatch_view_edit_region_by_key = {base_region.region_key: base_region}
    app.hatch_view_selected_edit_region_keys = {base_region.region_key}
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_region_by_key = {}
    app.loaded_regions = []
    app.stories = []
    app.nodes = []
    app.elements = []
    app.generated_dxf_story_names = ()
    app.continuous_apply_targets_by_region = {base_region.region_key: ("6F",)}
    app.continuous_materialized_targets_by_region = {}
    app.continuous_hatch_checks = {}
    app.continuous_active_visible_targets = ()
    app.continuous_active_region_key = base_region.region_key
    app.continuous_active_region_keys = ()
    app.continuous_base_story_name = _Var("5F")
    app.snap_tol_var = _Var(6.0)
    app.hatch_preview_info_var = _Var()
    app.continuous_apply_status_var = _Var()
    app._render_hatch_preview = lambda *args, **kwargs: None
    app._refresh_selected_hatch_continuous_info = lambda *args, **kwargs: None

    app._sync_load_to_continuous_targets_for_region_keys((base_region.region_key,))

    loads_by_cell = _loads_by_cell(app.hatch_edit_states_by_story["6F"])
    assert loads_by_cell["A"] == "Lobby"
    assert loads_by_cell["B"] == "Office"
    assert loads_by_cell["C"] == "Office"
    assert loads_by_cell["D"] == "Lobby"
    assert app.continuous_materialized_targets_by_region[base_region.region_key] == ("6F",)


def test_continuous_conflict_reason_is_reported_for_different_existing_load():
    app = object.__new__(FloorLoadAutoApp)
    base_state = create_edit_state("5F", [_cell("B", 10.0, "5F")])
    base_state.selected_region_keys = set(base_state.regions_by_key)
    base_state.selected_cell_ids = {"B"}
    base_state = apply_load_to_selection(base_state, load_name="Office", load_layer="LOAD_Office", dl=1.2, ll=3.4)
    base_region = next(region for region in base_state.regions_by_key.values() if region.load_name)

    target_state = create_edit_state("6F", [_cell("B", 10.0, "6F")])
    target_state.selected_region_keys = set(target_state.regions_by_key)
    target_state.selected_cell_ids = {"B"}
    target_state = apply_load_to_selection(target_state, load_name="Lobby", load_layer="LOAD_Lobby", dl=2.0, ll=4.0)

    app.hatch_edit_states_by_story = {"5F": base_state, "6F": target_state}
    app.hatch_view_edit_region_by_key = {base_region.region_key: base_region}
    app.hatch_view_region_by_key = {}
    app.loaded_regions = []
    app.snap_tol_var = _Var(0.5)

    reason = app._continuous_target_load_conflict_reason(
        base_region.region_key,
        "6F",
        app._load_payload_from_edit_region(base_region),
    )

    assert "이미 다른 하중" in reason
    assert "겹치는 영역만" in reason


def test_continuous_visible_targets_excludes_target_without_below_allowed_region():
    app = object.__new__(FloorLoadAutoApp)
    base_state = create_edit_state("3F", [_cell("A", 0.0, "3F")])
    base_state.selected_region_keys = set(base_state.regions_by_key)
    base_state.selected_cell_ids = {"A"}
    base_state = apply_load_to_selection(base_state, load_name="Office", load_layer="LOAD_Office", dl=1.2, ll=3.4)
    base_region = next(region for region in base_state.regions_by_key.values() if region.load_name)
    target_state = create_edit_state("B2", [_cell("A", 0.0, "B2")])

    app.hatch_edit_states_by_story = {"3F": base_state, "B2": target_state}
    app.hatch_view_edit_region_by_key = {base_region.region_key: base_region}
    app.hatch_view_region_by_key = {}
    app.loaded_regions = []
    app.stories = ["B2", "3F"]
    app.nodes = [object()]
    app.elements = [object()]
    app.snap_tol_var = _Var(0.5)
    app._story_below_allowed_polygons_by_name = lambda _story_names: {"B2": []}

    assert app._continuous_below_allowed_visible_targets(base_region.region_key, ("B2",)) == ()
    reason = app._continuous_target_visibility_reason(base_region.region_key, "B2")
    assert "BELOW 하중입력 가능 영역" in reason
    assert app.continuous_below_blocked_targets_by_region[base_region.region_key]["B2"] == reason


def test_continuous_dxf_target_partial_overlap_splits_only_intersection():
    app = _dxf_sync_app()
    base = _dxf_region("5F", "BASE", _load("Office", 1.2, 3.4), 10.0, 30.0)
    target = _dxf_region("6F", "TARGET", _load("Lobby", 2.0, 4.0), 0.0, 40.0)
    app.loaded_regions = [base, target]
    base_key = app._region_key(base, index=1)
    app.hatch_view_region_by_key = {base_key: base, app._region_key(target, index=2): target}
    app.continuous_apply_targets_by_region[base_key] = ("6F",)

    app._sync_load_to_continuous_targets_for_region_keys((base_key,))

    target_regions = [region for region in app.loaded_regions if region.region.story_name == "6F"]
    office_area = sum(region.region.area for region in target_regions if region.load and region.load.real_name == "Office")
    lobby_area = sum(region.region.area for region in target_regions if region.load and region.load.real_name == "Lobby")
    assert office_area == 200.0
    assert lobby_area == 200.0
    assert all(region.region.area < 400.0 for region in target_regions if region.load and region.load.real_name == "Office")
    assert app.continuous_materialized_targets_by_region[base_key] == ("6F",)


def test_continuous_dxf_split_failure_does_not_overwrite_whole_target_region():
    app = _dxf_sync_app()
    source = _dxf_region("5F", "BASE", _load("Office", 1.2, 3.4), 50.0, 60.0)
    target = _dxf_region("6F", "TARGET", _load("Lobby", 2.0, 4.0), 0.0, 40.0)
    app.loaded_regions = [target]

    applied = app._split_dxf_region_by_overlap_and_apply_load(
        target_key="6F|TARGET",
        base_region_key="5F|BASE",
        source_region=source,
        target_region=target,
        target_story="6F",
        payload={"load_name": "Office", "load_layer": "LOAD_Office", "dl": 1.2, "ll": 3.4, "distribution": "TWO_WAY"},
    )

    assert applied is False
    assert target.load.real_name == "Lobby"
    assert target.region.area == 400.0
    assert "겹치는 target DXF" in app.continuous_apply_status_var.value


def test_continuous_dxf_one_way_split_rejects_non_tri_quad_intersection_and_preserves_target():
    app = _dxf_sync_app()
    source = _dxf_polygon_region(
        "5F",
        "BASE",
        _load("Office", 1.2, 3.4),
        ((-1.0, -1.0), (10.0, -1.0), (10.0, 5.0), (5.0, 10.0), (-1.0, 10.0)),
    )
    target = _dxf_polygon_region("6F", "TARGET", _load("Lobby", 2.0, 4.0), ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
    app.loaded_regions = [target]

    applied = app._split_dxf_region_by_overlap_and_apply_load(
        target_key="6F|TARGET",
        base_region_key="5F|BASE",
        source_region=source,
        target_region=target,
        target_story="6F",
        payload=_one_way_payload("Office"),
    )

    assert applied is False
    assert target.load.real_name == "Lobby"
    assert target.region.area == 100.0
    assert len(app.loaded_regions) == 1
    assert "ONE-WAY 연속층 하중" in app.continuous_apply_status_var.value


def test_continuous_dxf_one_way_split_applies_to_quad_intersection():
    app = _dxf_sync_app()
    source = _dxf_polygon_region("5F", "BASE", _load("Office", 1.2, 3.4), ((0.0, 0.0), (5.0, 0.0), (5.0, 10.0), (0.0, 10.0)))
    target = _dxf_polygon_region("6F", "TARGET", _load("Lobby", 2.0, 4.0), ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
    app.loaded_regions = [target]

    applied = app._split_dxf_region_by_overlap_and_apply_load(
        target_key="6F|TARGET",
        base_region_key="5F|BASE",
        source_region=source,
        target_region=target,
        target_story="6F",
        payload=_one_way_payload("Office"),
    )

    assert applied is True
    office_regions = [region for region in app.loaded_regions if region.load and region.load.real_name == "Office"]
    lobby_regions = [region for region in app.loaded_regions if region.load and region.load.real_name == "Lobby"]
    assert sum(region.region.area for region in office_regions) == 50.0
    assert sum(region.region.area for region in lobby_regions) == 50.0
    assert all(region.load.distribution == "ONE_WAY" for region in office_regions)
    assert all(region.load.one_way_angle_deg is not None for region in office_regions)


def _loads_by_cell(state):
    result = {}
    for region in state.regions_by_key.values():
        for cell_id in region.cell_ids:
            result[cell_id] = region.load_name
    return result


def _dxf_sync_app():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_edit_states_by_story = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_region_by_key = {}
    app.loaded_regions = []
    app.stories = []
    app.nodes = []
    app.elements = []
    app.generated_dxf_story_names = ()
    app.continuous_apply_targets_by_region = {}
    app.continuous_materialized_targets_by_region = {}
    app.continuous_hatch_checks = {}
    app.continuous_apply_status_var = _Var()
    app.hatch_preview_info_var = _Var()
    app._render_hatch_preview = lambda *args, **kwargs: None
    app._refresh_selected_hatch_continuous_info = lambda *args, **kwargs: None
    return app


def _dxf_region(story_name: str, source_id: str, load, x0: float, x1: float):
    polygon = Polygon(((x0, 0.0), (x1, 0.0), (x1, 10.0), (x0, 10.0)))
    return _load_region_from_polygon(story_name, source_id, load, polygon)


def _dxf_polygon_region(story_name: str, source_id: str, load, points):
    return _load_region_from_polygon(story_name, source_id, load, Polygon(points))


def _load_region_from_polygon(story_name: str, source_id: str, load, polygon: Polygon):
    return LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer=str(getattr(load, "layer", "") or f"LOAD_{source_id}"),
            handle=source_id,
            vertices=list(polygon.exterior.coords)[:-1],
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(value) for value in polygon.bounds),
            story_name=story_name,
            source_id=source_id,
        ),
        load=load,
        status="OK" if load else "NO_LOAD",
        warnings=[],
    )


def _load(name: str, dl: float, ll: float):
    return LoadLayerInfo(layer=f"LOAD_{name}", real_name=name, dl=dl, ll=ll, distribution="TWO_WAY")


def _one_way_payload(name: str):
    return {"load_name": name, "load_layer": f"LOAD_{name}", "dl": 1.2, "ll": 3.4, "distribution": "ONE_WAY"}


def _cell(cell_id: str, x0: float, story_name: str) -> ClosedCell:
    return ClosedCell(
        cell_id=cell_id,
        story_name=story_name,
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=((x0, 0.0), (x0 + 10.0, 0.0), (x0 + 10.0, 10.0), (x0, 10.0)),
        area=100.0,
        centroid=(x0 + 5.0, 5.0),
        boundary_element_ids=(),
    )


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
