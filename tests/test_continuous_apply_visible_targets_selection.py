from types import SimpleNamespace

from app.main import FloorLoadAutoApp


def test_single_region_refresh_sets_active_visible_targets_and_rows():
    app = _app_with_candidates()
    app.hatch_view_selected_region_keys = ("A",)

    app._refresh_selected_hatch_continuous_info()

    assert app.continuous_active_visible_targets == ("1F", "2F", "4F", "5F")
    assert _stories_by_status(app.continuous_tree, "가능") == ["1F", "2F", "4F", "5F"]


def test_direct_selection_inside_active_visible_range_is_saved_and_rendered():
    app = _app_with_candidates()
    app.hatch_view_selected_region_keys = ("A",)
    app._refresh_selected_hatch_continuous_info()

    app._set_continuous_tree_selection(["continuous_1", "continuous_2", "continuous_4", "continuous_5"])

    assert app.continuous_apply_targets_by_region["A"] == ("1F", "2F", "4F", "5F")
    assert app.render_count == 1


def test_jump_selection_inside_visible_targets_is_not_saved():
    app = _app_with_candidates()
    app.hatch_view_selected_region_keys = ("A",)
    app._refresh_selected_hatch_continuous_info()

    app._set_continuous_tree_selection(["continuous_1", "continuous_5"])

    assert app.continuous_apply_targets_by_region["A"] == ()


def test_multi_region_auto_selection_uses_active_common_targets():
    app = _app_with_candidates()
    app.hatch_view_selected_region_keys = ("A", "B")
    app.continuous_hatch_checks["B"] = {
        "base_story": "3F",
        "applicable_targets": ("2F", "4F"),
        "recommended_targets": ("2F", "4F"),
        "base_centered_targets": ("2F", "4F"),
        "candidates": app.continuous_hatch_checks["A"]["candidates"],
    }

    app._refresh_selected_hatch_continuous_info()
    app.select_applicable_continuous_stories()

    assert app.continuous_active_visible_targets == ("2F", "4F")
    assert app.continuous_apply_targets_by_region["A"] == ("2F", "4F")
    assert app.continuous_apply_targets_by_region["B"] == ("2F", "4F")


def _app_with_candidates():
    app = object.__new__(FloorLoadAutoApp)
    app.story_shape_profiles = [SimpleNamespace(story_name=name) for name in ("1F", "2F", "3F", "4F", "5F", "6F")]
    app.generated_dxf_story_names = ()
    app.stories = []
    app.loaded_regions = []
    app.hatch_view_region_by_key = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_edit_region_keys = set()
    app.continuous_tree = _ContinuousTree()
    app.continuous_apply_status_var = _Var()
    app.continuous_apply_targets_by_region = {}
    app.continuous_base_story_name = _Var("3F")
    app._sync_continuous_base_story_from_selection = lambda: ""
    app._selected_hatch_story_names = lambda: ()
    app.render_count = 0

    def _render():
        app.render_count += 1

    app._render_hatch_preview = _render
    candidates = (
        _candidate("1F", True),
        _candidate("2F", True),
        _candidate("3F", False),
        _candidate("4F", True),
        _candidate("5F", True),
    )
    app.continuous_hatch_checks = {
        "A": {
            "base_story": "3F",
            "can_select": True,
            "applicable_targets": ("1F", "2F", "4F", "5F"),
            "recommended_targets": ("1F", "2F", "4F", "5F"),
            "base_centered_targets": ("1F", "2F", "4F", "5F"),
            "candidates": candidates,
        }
    }
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


def _stories_by_status(tree, status: str):
    return [values[1] for values in tree.values.values() if values[5] == status]


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


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
