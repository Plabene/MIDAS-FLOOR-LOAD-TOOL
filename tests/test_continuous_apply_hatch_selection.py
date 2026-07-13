from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Element, Node, Story
from app.core.typical_floor_detector import build_story_shape_profiles
from app.main import FloorLoadAutoApp


def test_recompute_hatch_checks_is_region_key_based():
    app = _app_with_profiles()
    region_a = _load_region("A", "LOAD_001_A_DL_1_LL_1")
    region_b = _load_region("B", "LOAD_002_B_DL_1_LL_1")
    app.loaded_regions = [region_a, region_b]

    app._recompute_hatch_continuous_checks()

    keys = list(app.continuous_hatch_checks)
    assert len(keys) == 2
    assert all(app.continuous_hatch_checks[key]["can_select"] for key in keys)
    assert keys[0] != keys[1]


def test_regions_with_continuous_apply_clones_only_selected_region_key():
    app = _app_with_profiles()
    region_a = _load_region("A", "LOAD_001_A_DL_1_LL_1")
    region_b = _load_region("B", "LOAD_002_B_DL_1_LL_1")
    regions = [region_a, region_b]
    app.loaded_regions = regions
    app._recompute_hatch_continuous_checks()
    region_a_key = app._region_key(region_a, index=1)
    app.continuous_apply_targets_by_region[region_a_key] = ("2F",)

    expanded = app._regions_with_continuous_apply(regions)

    cloned = [item for item in expanded if item.region.source_id.endswith("@2F")]
    assert len(cloned) == 1
    assert cloned[0].region.layer == region_a.region.layer
    assert all(item.region.layer != region_b.region.layer for item in cloned)


def test_regions_with_continuous_apply_ignores_legacy_base_story_map():
    app = _app_with_profiles()
    region = _load_region("A", "LOAD_001_A_DL_1_LL_1")
    app.loaded_regions = [region]
    app._recompute_hatch_continuous_checks()
    app.continuous_apply_targets["1F"] = ("2F",)

    expanded = app._regions_with_continuous_apply([region])

    assert expanded == [region]


def test_unavailable_hatch_can_still_be_selected_and_loads_base_story():
    app = object.__new__(FloorLoadAutoApp)
    region = _load_region("A", "LOAD_001_A_DL_1_LL_1")
    region_key = app._region_key(region, index=1)
    app.hatch_view_region_by_key = {region_key: region}
    app.hatch_view_selected_region_key = None
    app.continuous_hatch_checks = {
        region_key: {
            "region": region,
            "base_story": "1F",
            "can_select": False,
            "reason": "no available target",
            "candidates": (),
        }
    }
    app.continuous_base_story_name = _Var()
    app.selected_hatch_story_var = _Var()
    app.continuous_apply_status_var = _Var()
    app.hatch_preview_canvas = _ClickCanvas(region_key)
    app._render_hatch_preview = lambda *args, **kwargs: None

    app._on_hatch_view_click(SimpleNamespace(x=10, y=10))

    assert app.hatch_view_selected_region_key == region_key
    assert app.continuous_base_story_name.value == "1F"
    assert app.continuous_apply_status_var.value == "적용 조건을 만족하지 않아 자동 적용할 수 없습니다."


def test_continuous_tree_selection_auto_saves_continuous_targets_and_rerenders():
    app, renders = _app_with_continuous_tree()

    app._set_continuous_tree_selection(["i2", "i3"])

    assert app.continuous_apply_targets_by_region["region"] == ("2F", "3F")
    assert app.continuous_apply_status_var.value == "자동 저장됨: 1F -> 2F, 3F"
    assert renders == [True]


def test_continuous_tree_selection_rejects_non_continuous_targets():
    app, renders = _app_with_continuous_tree()
    app.continuous_apply_targets_by_region["region"] = ("2F", "3F")

    app._set_continuous_tree_selection(["i2", "i4"])

    assert app.continuous_apply_targets_by_region["region"] == ()
    assert "비연속 층은" in app.continuous_apply_status_var.value
    assert renders == [True]


def test_select_applicable_continuous_stories_selects_all_visible_targets_and_rejects_disconnected_save():
    app, _renders = _app_with_continuous_tree()
    app.continuous_candidate_by_iid["i3"].can_apply = False

    app.select_applicable_continuous_stories()

    assert app.continuous_tree.selected == {"i2", "i4"}
    assert app.continuous_apply_targets_by_region["region"] == ()
    assert "비연속 층은" in app.continuous_apply_status_var.value


def _app_with_profiles():
    app = object.__new__(FloorLoadAutoApp)
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
        Node(13, 10.0, 10.0, 3.0),
        Node(14, 0.0, 10.0, 3.0),
    ]
    elements = [
        Element(1, "SLAB", node_ids=(1, 2, 3, 4)),
        Element(2, "SLAB", node_ids=(11, 12, 13, 14)),
    ]
    app.stories = stories
    app.nodes = nodes
    app.elements = elements
    app.current_mgt_text = ""
    app.config_data = SimpleNamespace(snap_tolerance=0.02, story_tolerance=0.01)
    app.snap_tol_var = SimpleNamespace(get=lambda: 0.02)
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    app.typical_floor_groups = ()
    app.story_shape_profiles = build_story_shape_profiles(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_tolerance=0.01,
        xy_tolerance=0.02,
    )
    app.continuous_hatch_checks = {}
    app.continuous_apply_targets_by_region = {}
    app.continuous_apply_targets = {}
    app.hatch_view_region_by_key = {}
    return app


class _Var:
    def __init__(self):
        self.value = ""

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _ContinuousTree:
    def __init__(self, iids):
        self.values = {iid: ("", iid, "", "", "", "", "") for iid in iids}
        self.tags = {iid: () for iid in iids}
        self.selected = set()

    def get_children(self):
        return list(self.values)

    def selection_set(self, selected):
        self.selected = set(selected)

    def selection(self):
        return tuple(self.selected)

    def item(self, iid, option=None, **kwargs):
        if "values" in kwargs:
            self.values[iid] = tuple(kwargs["values"])
        if "tags" in kwargs:
            self.tags[iid] = tuple(kwargs["tags"])
        if option == "values":
            return self.values[iid]
        return {"values": self.values[iid], "tags": self.tags[iid]}


class _ClickCanvas:
    def __init__(self, region_key: str):
        self.region_key = region_key

    def find_withtag(self, tag):
        return [1] if tag == "current" else []

    def find_closest(self, *_args):
        return [1]

    def canvasx(self, value):
        return value

    def canvasy(self, value):
        return value

    def gettags(self, _item_id):
        return ("hatch_check", f"region:{self.region_key}")


def _load_region(source_id: str, layer: str):
    vertices = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer=layer,
        handle=source_id,
        vertices=vertices,
        polygon=Polygon(vertices),
        area=100.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        story_name="1F",
        source_id=source_id,
    )
    load = LoadLayerInfo(layer=layer, real_name=source_id, dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])


def _app_with_continuous_tree():
    app = object.__new__(FloorLoadAutoApp)
    app.continuous_tree = _ContinuousTree(["i2", "i3", "i4"])
    app.continuous_candidate_by_iid = {
        "i2": SimpleNamespace(target_story_name="2F", can_apply=True),
        "i3": SimpleNamespace(target_story_name="3F", can_apply=True),
        "i4": SimpleNamespace(target_story_name="4F", can_apply=True),
    }
    app.continuous_ordered_iids = ["i2", "i3", "i4"]
    app.story_shape_profiles = [
        SimpleNamespace(story_name="1F"),
        SimpleNamespace(story_name="2F"),
        SimpleNamespace(story_name="3F"),
        SimpleNamespace(story_name="4F"),
    ]
    app.continuous_active_region_key = "region"
    app.hatch_view_selected_region_key = "region"
    app.continuous_apply_targets_by_region = {}
    app.continuous_base_story_name = _Var()
    app.continuous_base_story_name.set("1F")
    app.continuous_apply_status_var = _Var()
    renders = []
    app._render_hatch_preview = lambda *args, **kwargs: renders.append(True)
    return app, renders
