from dataclasses import replace
from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.closed_region_detector import ClosedCell
from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.hatch_region_editor import EditableHatchRegion, HatchEditState, create_edit_state
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


def test_internal_region_targets_selected_before_load_receive_applied_load():
    app, base_key = _app_with_selected_internal_base()
    app.continuous_apply_targets_by_region[base_key] = ("6F", "7F")

    app._apply_hatch_load_item_to_selected_regions(_load_item("Office", 1.2, 3.4))

    loaded_base_key = next(key for key in app.hatch_view_selected_edit_region_keys if "LOADED" in key)
    assert app.continuous_apply_targets_by_region[loaded_base_key] == ("6F", "7F")
    assert _loaded_edit_region(app, "6F").load_name == "Office"
    assert _loaded_edit_region(app, "7F").load_name == "Office"


def test_internal_region_targets_selected_after_load_receive_existing_load():
    app, _base_key = _app_with_selected_internal_base()
    app._apply_hatch_load_item_to_selected_regions(_load_item("Office", 1.2, 3.4))
    loaded_base_key = next(key for key in app.hatch_view_selected_edit_region_keys if "LOADED" in key)
    app.continuous_active_region_key = loaded_base_key
    app.continuous_active_region_keys = ()
    app.continuous_active_visible_targets = ("6F", "7F")
    app.continuous_base_story_name = _Var("5F")
    app.story_shape_profiles = [SimpleNamespace(story_name=name) for name in ("5F", "6F", "7F")]
    app.continuous_tree = _ContinuousTree()
    app.continuous_candidate_by_iid = {
        "continuous_1": _candidate("6F"),
        "continuous_2": _candidate("7F"),
    }
    app.continuous_ordered_iids = ["continuous_1", "continuous_2"]

    app._set_continuous_tree_selection(["continuous_1", "continuous_2"])

    assert app.continuous_apply_targets_by_region[loaded_base_key] == ("6F", "7F")
    assert _loaded_edit_region(app, "6F").load_name == "Office"
    assert _loaded_edit_region(app, "7F").load_name == "Office"


def test_dxf_region_sync_updates_existing_target_dxf_region():
    app = _sync_app()
    base = _dxf_region("5F", "BASE", _load("Office"))
    target = _dxf_region("6F", "TARGET", None)
    app.loaded_regions = [base, target]
    base_key = app._region_key(base, index=1)
    app.hatch_view_region_by_key = {base_key: base}
    app.continuous_apply_targets_by_region[base_key] = ("6F",)

    app._sync_load_to_continuous_targets_for_region_keys((base_key,))

    assert target.load is not None
    assert target.load.real_name == "Office"
    assert app.continuous_materialized_targets_by_region[base_key] == ("6F",)


def test_dxf_region_sync_without_target_dxf_creates_internal_mirror():
    app = _sync_app()
    base = _dxf_region("5F", "BASE", _load("Office"))
    app.loaded_regions = [base]
    base_key = app._region_key(base, index=1)
    app.hatch_view_region_by_key = {base_key: base}
    app.continuous_apply_targets_by_region[base_key] = ("6F",)

    app._sync_load_to_continuous_targets_for_region_keys((base_key,))

    mirror = _loaded_edit_region(app, "6F")
    assert mirror.load_name == "Office"
    assert mirror.source == "CONTINUOUS_SYNC"
    assert app.continuous_materialized_targets_by_region[base_key] == ("6F",)


def test_materialized_target_is_not_cloned_again_for_mgt_generation():
    app = _sync_app()
    base = _dxf_region("5F", "BASE", _load("Office"))
    base_key = app._region_key(base, index=1)
    app.continuous_apply_targets_by_region[base_key] = ("6F", "7F")
    app.continuous_materialized_targets_by_region[base_key] = ("6F",)
    app.continuous_hatch_checks = {}

    expanded = app._regions_with_continuous_apply([base])

    assert [region.region.story_name for region in expanded] == ["5F", "7F"]


def test_synced_target_load_changes_and_removes_with_base_load():
    app = _sync_app()
    base_region = _editable_region("5F", "BASE", "Office", 1.2, 3.4)
    app.hatch_edit_states_by_story = {
        "5F": HatchEditState("5F", {}, {base_region.region_key: base_region}, {base_region.region_key}, set())
    }
    app.hatch_view_edit_region_by_key = {base_region.region_key: base_region}
    app.continuous_apply_targets_by_region[base_region.region_key] = ("6F",)

    app._sync_load_to_continuous_targets_for_region_keys((base_region.region_key,))
    assert _loaded_edit_region(app, "6F").load_name == "Office"

    updated_base = replace(base_region, load_name="Lobby", load_layer="LOAD_Lobby", dl=2.0, ll=4.0)
    state = app.hatch_edit_states_by_story["5F"]
    state.regions_by_key = {updated_base.region_key: updated_base}
    app.hatch_view_edit_region_by_key = {updated_base.region_key: updated_base}
    app.continuous_apply_targets_by_region[updated_base.region_key] = ("6F",)

    app._sync_load_to_continuous_targets_for_region_keys((updated_base.region_key,))
    assert _loaded_edit_region(app, "6F").load_name == "Lobby"

    app._sync_load_to_continuous_targets_for_region_keys((updated_base.region_key,), remove=True)
    assert _loaded_edit_region(app, "6F") is None


def _app_with_selected_internal_base():
    app = _sync_app()
    cell = ClosedCell(
        cell_id="A",
        story_name="5F",
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=_square(),
        area=100.0,
        centroid=(5.0, 5.0),
        boundary_element_ids=(),
    )
    state = create_edit_state("5F", [cell])
    base_key = next(iter(state.regions_by_key))
    state.selected_region_keys = {base_key}
    state.selected_cell_ids = {"A"}
    app.hatch_edit_states_by_story = {"5F": state}
    app.hatch_view_selected_edit_region_keys = {base_key}
    app.hatch_view_edit_region_by_key = {base_key: state.regions_by_key[base_key]}
    return app, base_key


def _sync_app():
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
    app.story_shape_profiles = []
    app.continuous_apply_targets_by_region = {}
    app.continuous_materialized_targets_by_region = {}
    app.continuous_hatch_checks = {}
    app.final_load_items = [_load_item("Office", 1.2, 3.4)]
    app.hatch_preview_info_var = _Var()
    app.continuous_apply_status_var = _Var()
    app._render_hatch_preview = lambda *args, **kwargs: None
    app._refresh_selected_hatch_continuous_info = lambda *args, **kwargs: None
    return app


def _loaded_edit_region(app, story_name: str):
    state = app.hatch_edit_states_by_story.get(story_name)
    if state is None:
        return None
    return next((region for region in state.regions_by_key.values() if region.load_name), None)


def _candidate(story_name: str):
    return SimpleNamespace(
        target_story_name=story_name,
        can_apply=True,
        similarity_score=1.0,
        boundary_node_match_ratio=1.0,
        iou=1.0,
        reason="OK",
    )


def _dxf_region(story_name: str, source_id: str, load):
    polygon = Polygon(_square())
    return LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer="LOAD_Office",
            handle=source_id,
            vertices=list(_square()),
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


def _editable_region(story_name: str, cell_id: str, load_name: str, dl: float, ll: float):
    return EditableHatchRegion(
        region_key=f"INTERNAL|{story_name}|{cell_id}|LOADED|{load_name}",
        story_name=story_name,
        cell_ids=(cell_id,),
        polygon_xy=_square(),
        load_name=load_name,
        load_layer=f"LOAD_{load_name}",
        dl=dl,
        ll=ll,
        distribution="TWO_WAY",
    )


def _load(name: str):
    return LoadLayerInfo(layer=f"LOAD_{name}", real_name=name, dl=1.2, ll=3.4, distribution="TWO_WAY")


def _load_item(name: str, dl: float, ll: float):
    return {"key": f"MODEL::{name}::{dl}::{ll}", "display_name": name, "name": name, "dl": dl, "ll": ll}


def _square():
    return ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))


class _ContinuousTree:
    def __init__(self):
        self.values = {
            "continuous_1": ("", "6F", "1.000", "1.000", "1.000", "가능", "OK"),
            "continuous_2": ("", "7F", "1.000", "1.000", "1.000", "가능", "OK"),
        }
        self.tags = {}
        self.selected = set()

    def get_children(self):
        return list(self.values)

    def selection_set(self, selected):
        self.selected = set(selected)

    def item(self, iid, option=None, **kwargs):
        if "values" in kwargs:
            self.values[iid] = tuple(kwargs["values"])
        if "tags" in kwargs:
            self.tags[iid] = tuple(kwargs["tags"])
        if option == "values":
            return self.values[iid]
        return {"values": self.values[iid], "tags": self.tags.get(iid, ())}


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
