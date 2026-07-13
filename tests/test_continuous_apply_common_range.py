from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.hatch_region_editor import EditableHatchRegion, HatchEditState
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Element, Node, Story
from app.core.typical_floor_detector import build_story_shape_profiles
from app.main import FloorLoadAutoApp


def test_common_continuous_apply_range_uses_intersection_and_single_run():
    app = object.__new__(FloorLoadAutoApp)
    app.story_shape_profiles = [SimpleNamespace(story_name=name) for name in ("1F", "2F", "3F", "4F", "5F", "6F")]
    app.generated_dxf_story_names = ()
    app.stories = []
    app.loaded_regions = []
    app.hatch_view_region_by_key = {}
    app.hatch_view_selected_region_keys = ("A", "B")
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_edit_region_keys = set()
    app.continuous_hatch_checks = {
        "A": {"base_story": "1F", "can_select": True, "applicable_targets": ("2F", "3F", "4F", "6F")},
        "B": {"base_story": "1F", "can_select": True, "applicable_targets": ("3F", "4F", "6F")},
    }
    app.continuous_apply_status_var = _Var()

    common = app._common_applicable_story_names_for_selected_regions(("A", "B"))
    common_range = app._common_continuous_story_range_for_selected_regions(("A", "B"))
    app._refresh_selected_hatch_continuous_info()

    assert common == ("3F", "4F", "6F")
    assert common_range == ("3F", "4F", "6F")
    assert app.continuous_apply_status_var.value == "선택 영역 2개 공통 연속층 적용 가능: 3F, 4F, 6F"


def test_internal_editable_region_builds_continuous_check():
    app = _app_with_story_profiles()
    internal = _editable_region("INTERNAL|1F|A", "1F")
    app.hatch_edit_states_by_story = {"1F": HatchEditState("1F", {}, {internal.region_key: internal}, {internal.region_key}, set())}
    app.hatch_view_edit_region_by_key = {internal.region_key: internal}
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_edit_region_keys = {internal.region_key}

    check = app._continuous_check_for_region_key(internal.region_key)

    assert check is not None
    assert check["base_story"] == "1F"
    assert check["can_select"] is True
    assert check["applicable_targets"] == ("2F",)


def test_common_range_works_with_dxf_and_internal_region_selection():
    app = _app_with_story_profiles()
    dxf = _load_region("DXF")
    dxf_key = app._region_key(dxf, index=1)
    internal = _editable_region("INTERNAL|1F|A", "1F")
    app.loaded_regions = [dxf]
    app.hatch_view_region_by_key = {dxf_key: dxf}
    app.hatch_view_edit_region_by_key = {internal.region_key: internal}
    app.hatch_edit_states_by_story = {"1F": HatchEditState("1F", {}, {internal.region_key: internal}, {internal.region_key}, set())}
    app.hatch_view_selected_region_keys = (dxf_key,)
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_edit_region_keys = {internal.region_key}
    app.continuous_hatch_checks = {
        dxf_key: {"base_story": "1F", "can_select": True, "applicable_targets": ("2F", "3F"), "candidates": ()}
    }

    common = app._common_applicable_story_names_for_selected_regions((dxf_key, internal.region_key))

    assert common == ("2F",)


def test_common_range_status_reports_none_when_no_common_targets():
    app = object.__new__(FloorLoadAutoApp)
    app.story_shape_profiles = [SimpleNamespace(story_name=name) for name in ("1F", "2F", "3F")]
    app.generated_dxf_story_names = ()
    app.stories = []
    app.loaded_regions = []
    app.hatch_view_region_by_key = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_selected_region_keys = ("A", "B")
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_edit_region_keys = set()
    app.continuous_hatch_checks = {
        "A": {"base_story": "1F", "can_select": True, "applicable_targets": ("2F",), "candidates": ()},
        "B": {"base_story": "1F", "can_select": True, "applicable_targets": ("3F",), "candidates": ()},
    }
    app.continuous_apply_status_var = _Var()
    app.continuous_apply_targets_by_region = {}

    app._refresh_selected_hatch_continuous_info()

    assert app.continuous_apply_status_var.value == "선택 영역 2개 공통 적용 가능층 없음"


def test_common_range_limits_tree_to_common_applicable_targets_and_prunes_saved_targets():
    app = object.__new__(FloorLoadAutoApp)
    app.story_shape_profiles = [SimpleNamespace(story_name=name) for name in ("1F", "2F", "3F")]
    app.generated_dxf_story_names = ()
    app.stories = []
    app.loaded_regions = []
    app.hatch_view_region_by_key = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_selected_region_keys = ("A", "B")
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_edit_region_keys = set()
    app.continuous_tree = _ContinuousTree()
    app.continuous_apply_status_var = _Var()
    app.continuous_apply_targets_by_region = {"A": ("2F", "3F"), "B": ("2F", "3F")}
    candidates = (
        _candidate("1F", "2F", True),
        _candidate("1F", "3F", True),
    )
    app.continuous_hatch_checks = {
        "A": {"base_story": "1F", "can_select": True, "applicable_targets": ("2F", "3F"), "candidates": candidates},
        "B": {"base_story": "1F", "can_select": True, "applicable_targets": ("2F",), "candidates": candidates},
    }

    app._refresh_selected_hatch_continuous_info()

    status_by_story = {values[1]: values[5] for values in app.continuous_tree.values.values()}
    assert status_by_story == {"2F": "가능", "3F": "불가"}
    assert app.continuous_apply_targets_by_region["A"] == ("2F",)
    assert app.continuous_apply_targets_by_region["B"] == ("2F",)


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _ContinuousTree:
    def __init__(self):
        self.values = {}
        self.tags = {}
        self.selected = set()

    def get_children(self):
        return list(self.values)

    def delete(self, item):
        self.values.pop(item, None)
        self.tags.pop(item, None)

    def insert(self, _parent, _index, *, iid, values, tags=()):
        self.values[iid] = tuple(values)
        self.tags[iid] = tuple(tags)

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


def _candidate(base_story: str, target_story: str, can_apply: bool):
    return SimpleNamespace(
        base_story_name=base_story,
        target_story_name=target_story,
        can_apply=can_apply,
        similarity_score=1.0,
        boundary_node_match_ratio=1.0,
        iou=1.0,
        reason="OK",
    )


def _app_with_story_profiles():
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
    app.story_shape_profiles = build_story_shape_profiles(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_tolerance=0.01,
        xy_tolerance=0.02,
    )
    app.typical_floor_groups = ()
    app.snap_tol_var = _Var(0.02)
    app.config_data = SimpleNamespace(snap_tolerance=0.02)
    app.continuous_hatch_checks = {}
    app.continuous_apply_targets_by_region = {}
    app.generated_dxf_story_names = ()
    app.loaded_regions = []
    return app


def _editable_region(region_key: str, story_name: str):
    return EditableHatchRegion(
        region_key=region_key,
        story_name=story_name,
        cell_ids=("A",),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        load_name=None,
        load_layer=None,
        dl=None,
        ll=None,
        distribution="TWO_WAY",
    )


def _load_region(source_id: str):
    vertices = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle=source_id,
        vertices=vertices,
        polygon=Polygon(vertices),
        area=100.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        story_name="1F",
        source_id=source_id,
    )
    load = LoadLayerInfo(layer=hatch.layer, real_name=source_id, dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])
