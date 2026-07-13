import time
from types import SimpleNamespace

from app.core.closed_region_detector import ClosedCell
from app.core.hatch_region_editor import apply_load_to_selection_with_stats, create_edit_state
from app.core.load_input_policy import DISTRIBUTION_ONE_WAY
from app.main import FloorLoadAutoApp


def test_preselected_targets_remap_by_cell_intersection_after_region_merge():
    app = _app_with_story_cells(("5F", "6F", "7F"), ("A", "B"))
    base = app.hatch_edit_states_by_story["5F"]
    base.selected_region_keys = set(base.regions_by_key)
    base.selected_cell_ids = {"A", "B"}
    app.hatch_view_selected_edit_region_keys = set(base.regions_by_key)
    app.hatch_view_edit_region_by_key = dict(base.regions_by_key)
    key_by_cell = {
        region.cell_ids[0]: key
        for key, region in base.regions_by_key.items()
    }
    app.continuous_apply_targets_by_region[key_by_cell["A"]] = ("6F", "7F")
    app.continuous_apply_targets_by_region[key_by_cell["B"]] = ("6F",)

    assert app._apply_hatch_load_item_to_selected_regions(_load_item("Office")) is True

    merged_key = next(iter(app.hatch_view_selected_edit_region_keys))
    assert app.continuous_apply_targets_by_region[merged_key] == ("6F",)
    assert _loaded_region(app, "6F").load_name == "Office"
    assert _loaded_region(app, "7F") is None


def test_stale_continuous_active_key_never_overrides_current_hatch_selection():
    app = _app_with_story_cells(("5F", "6F"), ("A",))
    base = app.hatch_edit_states_by_story["5F"]
    current_key = next(iter(base.regions_by_key))
    base.selected_region_keys = {current_key}
    base.selected_cell_ids = {"A"}
    app.hatch_view_selected_edit_region_keys = {current_key}
    app.hatch_view_edit_region_by_key = dict(base.regions_by_key)
    app.continuous_active_region_key = "INTERNAL|OLD|STALE|UNLOADED"
    app.continuous_active_region_keys = ()
    app.continuous_tree = _Tree(("6F",))
    app.continuous_candidate_by_iid = {"i6": _candidate("6F")}
    app.continuous_ordered_iids = ["i6"]
    app.story_shape_profiles = [SimpleNamespace(story_name=name) for name in ("5F", "6F")]

    app._set_continuous_tree_selection(["i6"])
    assert app.continuous_apply_targets_by_region[current_key] == ("6F",)
    assert "INTERNAL|OLD|STALE|UNLOADED" not in app.continuous_apply_targets_by_region

    app._apply_hatch_load_item_to_selected_regions(_load_item("Office"))
    assert _loaded_region(app, "6F").load_name == "Office"


def test_two_way_to_one_way_16_cells_is_fast_and_one_history_step():
    app = _base_app()
    cells = [_grid_cell("5F", row, column) for row in range(4) for column in range(4)]
    state = create_edit_state("5F", cells)
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = set(state.cells_by_id)
    state, _stats = apply_load_to_selection_with_stats(
        state,
        load_name="Office",
        load_layer="LOAD_Office",
        dl=1.2,
        ll=3.4,
        distribution="TWO_WAY",
    )
    app.hatch_edit_states_by_story = {"5F": state}
    app.hatch_view_edit_region_by_key = dict(state.regions_by_key)
    app.hatch_view_selected_edit_region_keys = set(state.selected_region_keys)

    started = time.perf_counter()
    app._apply_hatch_load_item_to_selected_regions(
        {**_load_item("Office"), "distribution": DISTRIBUTION_ONE_WAY, "one_way_angle": 0.0}
    )
    elapsed = time.perf_counter() - started

    final_regions = tuple(app.hatch_edit_states_by_story["5F"].regions_by_key.values())
    assert elapsed < 1.0
    assert len(final_regions) == 1
    assert final_regions[0].distribution == DISTRIBUTION_ONE_WAY
    assert len(app.hatch_edit_undo_stack) == 1

    app.undo_hatch_view_edit()
    assert next(iter(app.hatch_edit_states_by_story["5F"].regions_by_key.values())).distribution == "TWO_WAY"
    app.redo_hatch_view_edit()
    assert next(iter(app.hatch_edit_states_by_story["5F"].regions_by_key.values())).distribution == DISTRIBUTION_ONE_WAY


def test_history_session_reset_discards_old_snapshot_without_changing_current_load():
    app = _app_with_story_cells(("5F",), ("A",))
    state = app.hatch_edit_states_by_story["5F"]
    key = next(iter(state.regions_by_key))
    state.selected_region_keys = {key}
    state.selected_cell_ids = {"A"}
    app.hatch_view_selected_edit_region_keys = {key}
    app.hatch_view_edit_region_by_key = dict(state.regions_by_key)
    app._apply_hatch_load_item_to_selected_regions(_load_item("Office"))
    stale_entry = app.hatch_edit_undo_stack[-1]

    app._reset_hatch_edit_history("model reload")
    app.hatch_edit_undo_stack.append(stale_entry)
    current_key = next(iter(app.hatch_edit_states_by_story["5F"].regions_by_key))
    app.undo_hatch_view_edit()

    assert _loaded_region(app, "5F").load_name == "Office"
    assert next(iter(app.hatch_edit_states_by_story["5F"].regions_by_key)) == current_key
    assert app.hatch_edit_undo_stack == []


def test_strict_drag_hit_test_never_selects_nearest_region_across_blank_space():
    app = _base_app()
    app.hatch_view_edit_region_by_key = {"A": object(), "B": object()}
    app.hatch_view_selected_edit_region_keys = {"A"}
    app._hatch_drag_selection_candidates = lambda: (
        (
            ("A", ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))),
            ("B", ((20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0))),
        ),
        (),
    )
    app._canvas_point_to_hatch_world = lambda x, y: (x, y)

    assert app._hatch_region_key_containing_canvas_point(15.0, 5.0) is None
    assert app._hatch_region_key_containing_canvas_point(5.0, 5.0) == "A"
    assert app._hatch_region_key_containing_canvas_point(25.0, 5.0) == "B"
    assert app._drag_drop_target_region_keys(None, update_selection=False) == ("edit", ("A",))
    assert app._drag_drop_target_region_keys("B", update_selection=False) == ("edit", ("B",))


def _app_with_story_cells(stories, cell_ids):
    app = _base_app()
    app.hatch_edit_states_by_story = {
        story: create_edit_state(
            story,
            [_cell(story, cell_id, index * 10.0) for index, cell_id in enumerate(cell_ids)],
        )
        for story in stories
    }
    return app


def _base_app():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_edit_states_by_story = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_view_selected_region_key = None
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
    app.continuous_active_visible_targets = ()
    app.continuous_active_region_key = None
    app.continuous_active_region_keys = ()
    app.continuous_base_story_name = _Var("5F")
    app.final_load_items = []
    app.hatch_preview_info_var = _Var()
    app.continuous_apply_status_var = _Var()
    app._render_hatch_preview = lambda *args, **kwargs: None
    app._refresh_selected_hatch_continuous_info = lambda *args, **kwargs: None
    return app


def _loaded_region(app, story):
    state = app.hatch_edit_states_by_story.get(story)
    if state is None:
        return None
    return next((region for region in state.regions_by_key.values() if region.load_name), None)


def _cell(story, cell_id, x0):
    return ClosedCell(
        cell_id=cell_id,
        story_name=story,
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=((x0, 0.0), (x0 + 10.0, 0.0), (x0 + 10.0, 10.0), (x0, 10.0)),
        area=100.0,
        centroid=(x0 + 5.0, 5.0),
        boundary_element_ids=(),
    )


def _grid_cell(story, row, column):
    x0 = float(column * 10)
    y0 = float(row * 10)
    return ClosedCell(
        cell_id=f"C{row}_{column}",
        story_name=story,
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=((x0, y0), (x0 + 10.0, y0), (x0 + 10.0, y0 + 10.0), (x0, y0 + 10.0)),
        area=100.0,
        centroid=(x0 + 5.0, y0 + 5.0),
        boundary_element_ids=(),
    )


def _load_item(name):
    return {
        "key": f"MODEL::{name}",
        "display_name": name,
        "name": name,
        "dl": 1.2,
        "ll": 3.4,
        "distribution": "TWO_WAY",
    }


def _candidate(story):
    return SimpleNamespace(
        target_story_name=story,
        can_apply=True,
        similarity_score=1.0,
        boundary_node_match_ratio=1.0,
        iou=1.0,
        reason="OK",
    )


class _Tree:
    def __init__(self, stories):
        self.values = {
            f"i{story.rstrip('F')}": ("", story, "1", "1", "1", "가능", "OK")
            for story in stories
        }
        self.selected = set()

    def selection_set(self, selected):
        self.selected = set(selected)

    def get_children(self):
        return tuple(self.values)

    def item(self, iid, option=None, **kwargs):
        if "values" in kwargs:
            self.values[iid] = tuple(kwargs["values"])
        if option == "values":
            return self.values[iid]
        return {"values": self.values[iid]}


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
