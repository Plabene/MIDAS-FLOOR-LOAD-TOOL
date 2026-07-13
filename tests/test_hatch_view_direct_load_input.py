from app.core.closed_region_detector import ClosedCell
from app.core.hatch_region_editor import create_edit_state
from app.main import FloorLoadAutoApp


def test_hatch_view_direct_load_apply_and_remove_updates_internal_regions():
    app = object.__new__(FloorLoadAutoApp)
    cell = ClosedCell(
        cell_id="A",
        story_name="1F",
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        area=100.0,
        centroid=(5.0, 5.0),
        boundary_element_ids=(),
    )
    state = create_edit_state("1F", [cell])
    region_key = next(iter(state.regions_by_key))
    state.selected_region_keys = {region_key}
    state.selected_cell_ids = {"A"}
    app.hatch_edit_states_by_story = {"1F": state}
    app.hatch_view_selected_edit_region_keys = {region_key}
    app.hatch_view_selected_region_key = None
    app.generated_dxf_mode = None
    app.generated_dxf_story_names = ()
    app.stories = []
    app.nodes = []
    app.elements = []
    app.final_load_items = [{"key": "MODEL::Office::1.2::3.4::1", "display_name": "Office", "name": "Office", "dl": 1.2, "ll": 3.4}]
    app.hatch_load_item_by_iid = {"hatch_load_1": dict(app.final_load_items[0], distribution="TWO_WAY")}
    app.hatch_load_tree = _Tree("hatch_load_1")
    app.hatch_preview_info_var = _Var()
    app.continuous_apply_status_var = _Var()
    app._render_hatch_preview = lambda *args, **kwargs: None

    assert app._on_hatch_load_tree_activate() == "break"

    loaded = app._loaded_internal_hatch_regions()
    assert len(loaded) == 1
    assert loaded[0].load_name == "Office"
    assert loaded[0].load_layer == "LOAD_001_Office_DL_1.2_LL_3.4"
    assert app.hatch_preview_info_var.value.startswith("자동 저장됨:")

    app.remove_selected_hatch_load()

    assert app._loaded_internal_hatch_regions() == ()
    assert "하중 제거" in app.hatch_preview_info_var.value


def test_hatch_load_tree_activation_without_region_selection_only_updates_status():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_edit_states_by_story = {}
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_load_item_by_iid = {"hatch_load_1": {"display_name": "Office", "name": "Office", "dl": 1.2, "ll": 3.4}}
    app.hatch_load_tree = _Tree("hatch_load_1")
    app.hatch_preview_info_var = _Var()
    app.continuous_apply_status_var = _Var()
    app.apply_selected_hatch_load = lambda: (_ for _ in ()).throw(AssertionError("load should not apply without region selection"))

    assert app._on_hatch_load_tree_activate() == "break"

    assert "하중을 선택했습니다" in app.hatch_preview_info_var.value
    assert "폐합영역" in app.hatch_preview_info_var.value


class _Tree:
    def __init__(self, selected: str):
        self.selected = selected

    def selection(self):
        return (self.selected,)

    def get_children(self):
        return (self.selected,)


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
