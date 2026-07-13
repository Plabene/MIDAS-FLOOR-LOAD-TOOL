from app.core.closed_region_detector import ClosedCell
from app.core.hatch_region_editor import create_edit_state
from app.main import FloorLoadAutoApp


def test_delete_key_removes_selected_load_and_undo_redo_restores_state():
    app = _app_with_selected_cell()

    assert app._apply_hatch_load_item_to_selected_regions(_load_item("Office", 1.2, 3.4)) is True
    assert _loaded_region(app).load_name == "Office"
    assert len(app.hatch_edit_undo_stack) == 1

    app._on_hatch_view_delete_key()
    assert _loaded_region(app) is None

    app.undo_hatch_view_edit()
    assert _loaded_region(app).load_name == "Office"

    app.redo_hatch_view_edit()
    assert _loaded_region(app) is None


def test_hatch_undo_redo_button_state_follows_stacks():
    app = _app_with_selected_cell()
    app.hatch_undo_button = _Button()
    app.hatch_redo_button = _Button()

    app._update_hatch_undo_redo_buttons()
    assert app.hatch_undo_button.state == "disabled"
    assert app.hatch_redo_button.state == "disabled"

    app._apply_hatch_load_item_to_selected_regions(_load_item("Office", 1.2, 3.4))
    assert app.hatch_undo_button.state == "normal"
    assert app.hatch_redo_button.state == "disabled"

    app.undo_hatch_view_edit()
    assert app.hatch_undo_button.state == "disabled"
    assert app.hatch_redo_button.state == "normal"


def _app_with_selected_cell():
    app = object.__new__(FloorLoadAutoApp)
    cell = ClosedCell(
        cell_id="A",
        story_name="5F",
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        area=100.0,
        centroid=(5.0, 5.0),
        boundary_element_ids=(),
    )
    state = create_edit_state("5F", [cell])
    key = next(iter(state.regions_by_key))
    state.selected_region_keys = {key}
    state.selected_cell_ids = {"A"}
    app.hatch_edit_states_by_story = {"5F": state}
    app.hatch_view_selected_edit_region_keys = {key}
    app.hatch_view_edit_region_by_key = {key: state.regions_by_key[key]}
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_region_by_key = {}
    app.loaded_regions = []
    app.stories = []
    app.nodes = []
    app.elements = []
    app.generated_dxf_story_names = ()
    app.continuous_apply_targets_by_region = {}
    app.continuous_materialized_targets_by_region = {}
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


def _loaded_region(app):
    return next(
        (
            region
            for state in app.hatch_edit_states_by_story.values()
            for region in state.regions_by_key.values()
            if region.load_name
        ),
        None,
    )


def _load_item(name: str, dl: float, ll: float):
    return {"key": f"MODEL::{name}", "display_name": name, "name": name, "dl": dl, "ll": ll}


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Button:
    def __init__(self):
        self.state = None

    def configure(self, **kwargs):
        self.state = kwargs.get("state", self.state)
