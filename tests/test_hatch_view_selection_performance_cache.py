from types import SimpleNamespace

from shapely.geometry import Polygon

import app.main as main_module
from app.main import FloorLoadAutoApp


def test_story_below_allowed_polygons_cache_reuses_detect_closed_cells(monkeypatch):
    app = _bare_app()
    calls = []

    def fake_detect_closed_cells(**_kwargs):
        calls.append(True)
        return [
            SimpleNamespace(
                story_name="3F",
                polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
            )
        ]

    monkeypatch.setattr(main_module, "detect_closed_cells", fake_detect_closed_cells)

    first = app._story_below_allowed_polygons_by_name(("3F",))
    second = app._story_below_allowed_polygons_by_name(("3F",))

    assert len(first["3F"]) == 1
    assert len(second["3F"]) == 1
    assert len(calls) == 1

    app.snap_tol_var.set(0.25)
    app._story_below_allowed_polygons_by_name(("3F",))

    assert len(calls) == 1


def test_continuous_target_below_reason_cache_skips_allowed_polygon_lookup():
    app = _bare_app()
    polygon_xy = ((0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0))
    allowed = Polygon(polygon_xy)
    calls = []

    app._continuous_target_polygon_xy_for_below_check = lambda _key, _target: polygon_xy
    app._story_below_allowed_polygons_by_name = lambda _names: calls.append(True) or {"2F": (allowed,)}

    first = app._continuous_target_below_allowed_reason("A", "2F")
    second = app._continuous_target_below_allowed_reason("A", "2F")

    assert first == ""
    assert second == ""
    assert len(calls) == 1


def test_single_hatch_click_refreshes_continuous_tree_once():
    app = _app_for_click()
    refresh_calls = []
    app._refresh_continuous_candidate_tree = lambda *args, **kwargs: refresh_calls.append((args, kwargs))

    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0))

    assert len(refresh_calls) <= 1
    assert app.render_calls == []


def test_continuous_tree_fingerprint_skips_duplicate_delete_insert():
    app = _bare_app()
    app.story_shape_profiles = [SimpleNamespace(story_name="1F"), SimpleNamespace(story_name="2F")]
    app.continuous_tree = _ContinuousTree()
    app.continuous_apply_status_var = _Var()
    app.continuous_apply_targets_by_region = {}
    app.continuous_active_region_keys = ()
    app.continuous_active_region_key = ""
    app._continuous_load_conflict_reason_for_region_keys = lambda _keys, _target: ""
    candidate = _candidate("2F", True)

    app._refresh_continuous_candidate_tree("1F", (candidate,), region_key="A", visible_targets=("2F",))
    first_inserts = app.continuous_tree.insert_count
    first_deletes = app.continuous_tree.delete_count
    app._refresh_continuous_candidate_tree("1F", (candidate,), region_key="A", visible_targets=("2F",))

    assert app.continuous_tree.insert_count == first_inserts
    assert app.continuous_tree.delete_count == first_deletes


def test_select_dxf_tree_region_uses_reverse_lookup_without_scan():
    app = object.__new__(FloorLoadAutoApp)
    app.dxf_tree = _DxfTree()
    app.dxf_tree_iid_by_region_key = {"region-A": "iid-A"}
    app.dxf_region_key_by_tree_iid = _NoItemsDict({"iid-B": "region-B"})

    app._select_dxf_tree_region("region-A")

    assert app.dxf_tree.selected == "iid-A"
    assert app.dxf_tree.seen == "iid-A"


def _bare_app():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [SimpleNamespace(name="1F"), SimpleNamespace(name="2F"), SimpleNamespace(name="3F")]
    app.nodes = [object()]
    app.elements = [object()]
    app.current_mgt_text = "MGT"
    app.story_tol_var = _Var(0.001)
    app.snap_tol_var = _Var(0.5)
    app.generated_dxf_layout_metadata = None
    app.loaded_regions = []
    app.hatch_edit_states_by_story = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_region_by_key = {}
    app.continuous_hatch_checks = {}
    app.continuous_apply_targets_by_region = {}
    app.continuous_materialized_targets_by_region = {}
    app.continuous_active_region_keys = ()
    app.continuous_active_region_key = ""
    app.continuous_base_story_name = _Var()
    app.continuous_apply_status_var = _Var()
    app.logger = SimpleNamespace(warning=lambda *args, **kwargs: None, debug=lambda *args, **kwargs: None)
    return app


def _app_for_click():
    app = _bare_app()
    key = "1F|A"
    region = SimpleNamespace(region=SimpleNamespace(story_name="1F", vertices=[]), load=None, status="OK")
    app.loaded_regions = [region]
    app.hatch_view_region_by_key = {key: region}
    app.hatch_view_region_items = {key: 1}
    app.hatch_view_checkbox_items = {key: (2, 3)}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_edit_region_items = {}
    app.hatch_view_edit_checkbox_items = {}
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_edit_region_keys = set()
    app.continuous_hatch_checks = {
        key: {"region": region, "base_story": "1F", "can_select": True, "candidates": ()}
    }
    app.story_shape_profiles = [SimpleNamespace(story_name="1F")]
    app.generated_dxf_story_names = ()
    app.selected_hatch_story_var = _Var()
    app.hatch_view_selected_story_var = _Var()
    app.hatch_preview_canvas = _Canvas(("hatch_region", f"region:{key}"), existing_items={1, 2, 3})
    app.render_calls = []
    app._render_hatch_preview = lambda *args, **kwargs: app.render_calls.append(kwargs)
    return app


def _candidate(target_story: str, can_apply: bool):
    return SimpleNamespace(
        target_story_name=target_story,
        can_apply=can_apply,
        similarity_score=1.0 if can_apply else 0.0,
        boundary_node_match_ratio=1.0 if can_apply else 0.0,
        iou=1.0 if can_apply else 0.0,
        reason="OK" if can_apply else "not available",
    )


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Canvas:
    def __init__(self, current_tags, *, existing_items):
        self.current_tags = tuple(current_tags)
        self.existing_items = set(existing_items)
        self.configs = []

    def winfo_exists(self):
        return True

    def find_withtag(self, tag):
        return [999] if tag == "current" and self.current_tags else []

    def find_closest(self, *_args):
        return [999] if self.current_tags else []

    def canvasx(self, value):
        return value

    def canvasy(self, value):
        return value

    def gettags(self, item_id):
        return self.current_tags if item_id == 999 else ()

    def itemconfig(self, item_id, **kwargs):
        if item_id not in self.existing_items:
            raise ValueError(f"missing item {item_id}")
        self.configs.append((item_id, dict(kwargs)))


class _ContinuousTree:
    def __init__(self):
        self.values = {}
        self.tags = {}
        self.selected = set()
        self.insert_count = 0
        self.delete_count = 0

    def get_children(self):
        return list(self.values)

    def delete(self, item):
        self.delete_count += 1
        self.values.pop(item, None)
        self.tags.pop(item, None)

    def insert(self, _parent, _index, *, iid, values, tags=()):
        self.insert_count += 1
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


class _DxfTree:
    def __init__(self):
        self.selected = None
        self.seen = None

    def selection_set(self, iid):
        self.selected = iid

    def see(self, iid):
        self.seen = iid


class _NoItemsDict(dict):
    def items(self):
        raise AssertionError("fallback scan should not be used when reverse map exists")
