from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


def test_dxf_multi_selection_delete_undo_redo_removes_all_selected_loads():
    app = _app_with_dxf_regions(loads=True)

    app.remove_selected_hatch_load()

    assert [region.load for region in app.loaded_regions] == [None, None]

    app.undo_hatch_view_edit()
    assert [region.load.real_name for region in app.loaded_regions] == ["Lobby", "Office"]

    app.redo_hatch_view_edit()
    assert [region.load for region in app.loaded_regions] == [None, None]


def test_dxf_multi_selection_button_apply_updates_all_selected_regions_and_syncs_each_key():
    app = _app_with_dxf_regions(loads=False)
    synced = []
    app._sync_load_to_continuous_targets_for_region_keys = lambda keys, **_kwargs: synced.append(tuple(keys))
    app.hatch_load_tree = _Tree("load-1")
    app.hatch_load_item_by_iid = {"load-1": _load_item("Retail", 2.5, 4.5)}

    app.apply_selected_hatch_load()

    assert [region.load.real_name for region in app.loaded_regions] == ["Retail", "Retail"]
    assert [region.load.dl for region in app.loaded_regions] == [2.5, 2.5]
    assert synced == [tuple(app.hatch_view_region_by_key.keys())]
    assert len(app.hatch_edit_undo_stack) == 1


def test_dxf_multi_selection_context_apply_updates_all_selected_regions():
    app = _app_with_dxf_regions(loads=False)

    app._apply_context_load_item(_load_item("Storage", 1.1, 2.2))

    assert [region.load.real_name for region in app.loaded_regions] == ["Storage", "Storage"]
    assert app.hatch_preview_info_var.value == "자동 저장됨: 선택 DXF 해치 2개에 하중 적용"


def _app_with_dxf_regions(*, loads: bool):
    app = object.__new__(FloorLoadAutoApp)
    first = _dxf_region("1F", "A", _load("Lobby", 1.0, 2.0) if loads else None, 0.0)
    second = _dxf_region("1F", "B", _load("Office", 1.5, 3.0) if loads else None, 20.0)
    app.loaded_regions = [first, second]
    app.hatch_view_region_by_key = {
        app._region_key(first, index=1): first,
        app._region_key(second, index=2): second,
    }
    app.hatch_view_selected_region_keys = set(app.hatch_view_region_by_key)
    app.hatch_view_selected_region_key = next(iter(app.hatch_view_region_by_key))
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.hatch_view_edit_region_by_key = {}
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


def _dxf_region(story_name: str, source_id: str, load, x0: float):
    polygon = Polygon(((x0, 0.0), (x0 + 10.0, 0.0), (x0 + 10.0, 10.0), (x0, 10.0)))
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


def _load_item(name: str, dl: float, ll: float):
    return {"key": f"MODEL::{name}", "display_name": name, "name": name, "dl": dl, "ll": ll}


class _Tree:
    def __init__(self, iid):
        self.iid = iid

    def selection(self):
        return (self.iid,)

    def get_children(self):
        return (self.iid,)


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
