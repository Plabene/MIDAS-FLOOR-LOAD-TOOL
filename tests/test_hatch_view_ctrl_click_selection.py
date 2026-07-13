import inspect
from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


def test_hatch_view_does_not_bind_ctrl_left_click_to_context_menu():
    source = inspect.getsource(FloorLoadAutoApp._build_hatch_view_panel)

    assert '<Button-3>' in source
    assert '<Control-Button-1>' not in source


def test_ctrl_left_click_toggles_internal_region_selection():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_preview_canvas = _ClickCanvas(("hatch_edit_region", "edit_region:E1"))
    app.hatch_view_edit_region_by_key = {"E1": SimpleNamespace(story_name="1F")}
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.continuous_hatch_checks = {}
    app.continuous_apply_status_var = _Var()
    app.continuous_base_story_name = _Var()
    app.selected_hatch_story_var = _Var()
    renders = []
    app._render_hatch_preview = lambda *args, **kwargs: renders.append(kwargs)

    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0x0004))
    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0x0004))

    assert app.hatch_view_selected_edit_region_keys == set()
    assert len(renders) == 2
    assert app.selected_hatch_story_var.value == "기준 STORY: 선택 해치층 자동"


def test_ctrl_left_click_toggles_dxf_region_selection_and_plain_click_replaces():
    app = object.__new__(FloorLoadAutoApp)
    first = _load_region("A", "1F")
    second = _load_region("B", "1F")
    first_key = app._region_key(first, index=1)
    second_key = app._region_key(second, index=2)
    app.hatch_view_region_by_key = {first_key: first, second_key: second}
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.continuous_hatch_checks = {
        first_key: {"region": first, "base_story": "1F", "can_select": False, "reason": "test", "candidates": ()},
        second_key: {"region": second, "base_story": "1F", "can_select": False, "reason": "test", "candidates": ()},
    }
    app.continuous_base_story_name = _Var()
    app.selected_hatch_story_var = _Var()
    app.continuous_apply_status_var = _Var()
    renders = []
    app._render_hatch_preview = lambda *args, **kwargs: renders.append(kwargs)
    app._select_dxf_tree_region = lambda _key: None

    app.hatch_preview_canvas = _ClickCanvas(("hatch_region", f"region:{first_key}"))
    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0x0004))
    app.hatch_preview_canvas = _ClickCanvas(("hatch_region", f"region:{second_key}"))
    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0x0004))

    assert app.hatch_view_selected_region_keys == {first_key, second_key}
    assert app.hatch_view_selected_region_key == second_key

    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0))

    assert app.hatch_view_selected_region_keys == {second_key}
    assert app.hatch_view_selected_region_key == second_key


def test_plain_empty_click_clears_selection_but_ctrl_empty_click_keeps_it():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_preview_canvas = _ClickCanvas(())
    app.hatch_view_selected_region_key = "R1"
    app.hatch_view_selected_region_keys = {"R1"}
    app.hatch_view_selected_edit_region_keys = {"E1"}
    app.hatch_edit_states_by_story = {}
    app.continuous_base_story_name = _Var()
    app.selected_hatch_story_var = _Var()
    app.continuous_apply_status_var = _Var()
    renders = []
    app._render_hatch_preview = lambda *args, **kwargs: renders.append(kwargs)

    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0x0004))

    assert app.hatch_view_selected_region_keys == {"R1"}
    assert app.hatch_view_selected_edit_region_keys == {"E1"}

    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0))

    assert app.hatch_view_selected_region_keys == set()
    assert app.hatch_view_selected_edit_region_keys == set()


class _ClickCanvas:
    def __init__(self, tags):
        self.tags = tuple(tags)

    def find_withtag(self, tag):
        return [1] if tag == "current" and self.tags else []

    def find_closest(self, *_args):
        return [1] if self.tags else []

    def canvasx(self, value):
        return value

    def canvasy(self, value):
        return value

    def gettags(self, _item_id):
        return self.tags


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def _load_region(source_id: str, story_name: str):
    vertices = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle=source_id,
        vertices=vertices,
        polygon=Polygon(vertices),
        area=100.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        story_name=story_name,
        source_id=source_id,
    )
    load = LoadLayerInfo(layer=hatch.layer, real_name=source_id, dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])
