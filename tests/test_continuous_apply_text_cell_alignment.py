from types import SimpleNamespace

from app.main import FloorLoadAutoApp


def test_status_text_and_tree_possible_rows_use_same_visible_targets():
    app = _app_with_candidates()
    app.hatch_view_selected_region_keys = ("A",)

    app._refresh_continuous_candidate_tree("3F", app.continuous_hatch_checks["A"]["candidates"], region_key="A")
    app._refresh_selected_hatch_continuous_info()

    possible_stories = _stories_by_status(app.continuous_tree, "가능")
    assert possible_stories == ["1F", "2F", "4F", "5F"]
    assert app.continuous_apply_status_var.value == "3F 기준 연속층 적용 가능: 1F, 2F, 4F, 5F"


def test_auto_select_v_checks_match_visible_targets():
    app = _app_with_candidates()
    app.hatch_view_selected_region_keys = ("A",)
    app._refresh_continuous_candidate_tree("3F", app.continuous_hatch_checks["A"]["candidates"], region_key="A")

    app.select_applicable_continuous_stories()

    checked = [values[1] for values in app.continuous_tree.values.values() if values[0] == "✓"]
    assert checked == ["1F", "2F", "4F", "5F"]
    assert app.continuous_apply_targets_by_region["A"] == ("1F", "2F", "4F", "5F")


def test_multi_region_common_targets_drive_text_and_possible_rows():
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

    assert app.continuous_apply_status_var.value == "선택 영역 2개 공통 연속층 적용 가능: 2F, 4F"
    assert _stories_by_status(app.continuous_tree, "가능") == ["2F", "4F"]


def test_multi_region_without_common_targets_marks_rows_unavailable():
    app = _app_with_candidates()
    app.hatch_view_selected_region_keys = ("A", "B")
    app.continuous_hatch_checks["B"] = {
        "base_story": "3F",
        "applicable_targets": ("6F",),
        "recommended_targets": ("6F",),
        "base_centered_targets": ("6F",),
        "candidates": app.continuous_hatch_checks["A"]["candidates"],
    }

    app._refresh_selected_hatch_continuous_info()

    assert app.continuous_apply_status_var.value == "선택 영역 2개 공통 적용 가능층 없음"
    assert _stories_by_status(app.continuous_tree, "가능") == []


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
    app._render_hatch_preview = lambda *args, **kwargs: None
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
        reason="OK" if can_apply else "불가",
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
