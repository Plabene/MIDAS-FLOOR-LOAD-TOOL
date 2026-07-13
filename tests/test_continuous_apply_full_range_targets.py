from types import SimpleNamespace

from app.main import FloorLoadAutoApp


def test_full_range_targets_include_all_applicable_above_and_below_base():
    app = object.__new__(FloorLoadAutoApp)
    candidates = [_candidate("1F", True), _candidate("2F", True), _candidate("4F", True), _candidate("5F", True)]

    targets = app._base_centered_applicable_story_names(
        base_story="3F",
        candidates=candidates,
        story_order=("1F", "2F", "3F", "4F", "5F"),
    )

    assert targets == ("1F", "2F", "4F", "5F")


def test_full_range_targets_allow_only_above_or_only_below():
    app = object.__new__(FloorLoadAutoApp)

    above = app._base_centered_applicable_story_names(
        base_story="3F",
        candidates=[_candidate("4F", True), _candidate("5F", True)],
        story_order=("1F", "2F", "3F", "4F", "5F"),
    )
    below = app._base_centered_applicable_story_names(
        base_story="3F",
        candidates=[_candidate("1F", True), _candidate("2F", True)],
        story_order=("1F", "2F", "3F", "4F", "5F"),
    )

    assert above == ("4F", "5F")
    assert below == ("1F", "2F")


def test_auto_select_uses_visible_targets_and_excludes_base_story():
    app = _app_with_tree()

    app.select_applicable_continuous_stories()

    assert app.continuous_tree.selected == {"i1", "i2", "i4", "i5"}
    assert app.continuous_apply_targets_by_region["R1"] == ("1F", "2F", "4F", "5F")
    assert app.continuous_tree.values["i3"][0] == ""


def _app_with_tree():
    app = object.__new__(FloorLoadAutoApp)
    app.continuous_tree = _Tree(["i1", "i2", "i3", "i4", "i5"])
    app.continuous_candidate_by_iid = {
        "i1": _candidate("1F", True),
        "i2": _candidate("2F", True),
        "i3": _candidate("3F", False),
        "i4": _candidate("4F", True),
        "i5": _candidate("5F", True),
    }
    app.continuous_ordered_iids = ["i1", "i2", "i3", "i4", "i5"]
    app.story_shape_profiles = [SimpleNamespace(story_name=name) for name in ("1F", "2F", "3F", "4F", "5F")]
    app.continuous_active_region_key = "R1"
    app.hatch_view_selected_region_key = "R1"
    app.continuous_hatch_checks = {
        "R1": {
            "base_story": "3F",
            "applicable_targets": ("1F", "2F", "4F", "5F"),
            "recommended_targets": ("1F", "2F", "4F", "5F"),
            "base_centered_targets": ("1F", "2F", "4F", "5F"),
        }
    }
    app.continuous_apply_targets_by_region = {}
    app.continuous_base_story_name = _Var("3F")
    app.continuous_apply_status_var = _Var()
    app._render_hatch_preview = lambda *args, **kwargs: None
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


class _Tree:
    def __init__(self, iids):
        self.values = {iid: ("", iid, "", "", "", "가능", "") for iid in iids}
        self.tags = {iid: ("can_apply",) for iid in iids}
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
        return {"values": self.values[iid], "tags": self.tags[iid]}


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
