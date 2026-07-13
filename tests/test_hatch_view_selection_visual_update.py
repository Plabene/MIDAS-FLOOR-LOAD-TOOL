from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.hatch_region_editor import EditableHatchRegion, HatchEditState
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


def test_dxf_plain_click_updates_selection_visuals_without_full_render():
    app, first_key, second_key = _app_with_dxf_selection()
    app.hatch_view_selected_region_keys = {first_key}
    app.hatch_view_selected_region_key = first_key
    app.hatch_preview_canvas = _Canvas(("hatch_region", f"region:{second_key}"), existing_items={1, 2, 3, 4, 5, 6})

    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0))

    assert app.render_calls == []
    assert app.hatch_view_selected_region_keys == {second_key}
    assert app.hatch_view_selected_region_key == second_key
    assert app.hatch_preview_canvas.config_for(1)["outline"] == "#374151"
    assert app.hatch_preview_canvas.config_for(3)["text"] == ""
    assert app.hatch_preview_canvas.config_for(4)["outline"] == "#1a73e8"
    assert app.hatch_preview_canvas.config_for(6)["text"] == "V"


def test_dxf_ctrl_click_adds_selection_without_full_render():
    app, first_key, second_key = _app_with_dxf_selection()
    app.hatch_view_selected_region_keys = {first_key}
    app.hatch_view_selected_region_key = first_key
    app.hatch_preview_canvas = _Canvas(("hatch_region", f"region:{second_key}"), existing_items={1, 2, 3, 4, 5, 6})

    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0x0004))

    assert app.render_calls == []
    assert app.hatch_view_selected_region_keys == {first_key, second_key}
    assert app.hatch_preview_canvas.config_for(3)["text"] == "V"
    assert app.hatch_preview_canvas.config_for(6)["text"] == "V"


def test_internal_click_updates_selection_visuals_and_checkbox_without_full_render():
    app, region_key = _app_with_internal_selection(load_name=None)
    app.hatch_preview_canvas = _Canvas(("hatch_edit_region", f"edit_region:{region_key}"), existing_items={10, 11, 12})

    app._on_hatch_view_click(SimpleNamespace(x=8, y=8, state=0))

    assert app.render_calls == []
    assert app.hatch_view_selected_edit_region_keys == {region_key}
    assert app.hatch_preview_canvas.config_for(10)["outline"] == "#1a73e8"
    assert app.hatch_preview_canvas.config_for(12)["text"] == "V"


def test_empty_click_clears_selection_visuals_without_full_render():
    app, first_key, _second_key = _app_with_dxf_selection()
    app.hatch_view_selected_region_keys = {first_key}
    app.hatch_view_selected_region_key = first_key
    app.hatch_preview_canvas = _Canvas((), existing_items={1, 2, 3, 4, 5, 6})

    app._on_hatch_view_click(SimpleNamespace(x=30, y=30, state=0))

    assert app.render_calls == []
    assert app.hatch_view_selected_region_keys == set()
    assert app.hatch_view_selected_region_key is None
    assert app.hatch_preview_canvas.config_for(1)["outline"] == "#374151"
    assert app.hatch_preview_canvas.config_for(3)["text"] == ""


def test_selection_visual_update_falls_back_to_render_when_item_map_is_missing():
    app, _first_key, second_key = _app_with_dxf_selection()
    app.hatch_view_region_items = {}
    app.hatch_view_checkbox_items = {}
    app.hatch_preview_canvas = _Canvas(("hatch_region", f"region:{second_key}"), existing_items=set())

    app._on_hatch_view_click(SimpleNamespace(x=10, y=10, state=0))

    assert app.render_calls == [{"focus_region_key": second_key}]
    assert app.hatch_view_selected_region_keys == {second_key}


def test_drag_box_selection_updates_internal_visuals_without_full_render():
    app, region_key = _app_with_internal_selection(load_name="Office")
    app.hatch_preview_canvas = _Canvas((), existing_items={10, 11, 12, 99})
    app.hatch_view_drag_start = (0.0, 0.0)
    app.hatch_view_drag_item = 99
    app.hatch_view_drag_moved = True
    region = app.hatch_view_edit_region_by_key[region_key]
    app._canvas_point_to_hatch_world = lambda x, y: (float(x), float(y))
    app._hatch_edit_regions_for_display_selection = lambda: (region,)

    app._on_hatch_view_button_release(SimpleNamespace(x=10, y=10, state=0))

    assert app.render_calls == []
    assert app.hatch_preview_canvas.deleted == [99]
    assert app.hatch_view_selected_edit_region_keys == {region_key}
    assert app.hatch_preview_canvas.config_for(10)["outline"] == "#1a73e8"
    assert app.hatch_preview_canvas.config_for(12)["text"] == "V"


def _app_with_dxf_selection():
    app = object.__new__(FloorLoadAutoApp)
    first = _dxf_region("A", 0.0)
    second = _dxf_region("B", 20.0)
    first_key = app._region_key(first, index=1)
    second_key = app._region_key(second, index=2)
    _attach_common_state(app)
    app.loaded_regions = [first, second]
    app.hatch_view_region_by_key = {first_key: first, second_key: second}
    app.hatch_view_region_items = {first_key: 1, second_key: 4}
    app.hatch_view_checkbox_items = {first_key: (2, 3), second_key: (5, 6)}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_edit_region_items = {}
    app.hatch_view_edit_checkbox_items = {}
    app.continuous_hatch_checks = {
        first_key: {"region": first, "base_story": "1F", "can_select": True, "candidates": ()},
        second_key: {"region": second, "base_story": "1F", "can_select": True, "candidates": ()},
    }
    return app, first_key, second_key


def _app_with_internal_selection(*, load_name: str | None):
    app = object.__new__(FloorLoadAutoApp)
    region_key = "INTERNAL|1F|A"
    region = EditableHatchRegion(
        region_key=region_key,
        story_name="1F",
        cell_ids=("A",),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        load_name=load_name,
        load_layer=f"LOAD_{load_name}" if load_name else None,
        dl=1.0 if load_name else None,
        ll=2.0 if load_name else None,
        distribution="TWO_WAY",
    )
    _attach_common_state(app)
    app.hatch_view_region_by_key = {}
    app.hatch_view_region_items = {}
    app.hatch_view_checkbox_items = {}
    app.hatch_view_edit_region_by_key = {region_key: region}
    app.hatch_view_edit_region_items = {region_key: 10}
    app.hatch_view_edit_checkbox_items = {region_key: (11, 12)}
    app.hatch_edit_states_by_story = {"1F": HatchEditState("1F", {}, {region_key: region}, set(), set())}
    return app, region_key


def _attach_common_state(app):
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.hatch_load_drag_hover_key = None
    app.continuous_hatch_checks = {}
    app.continuous_base_story_name = _Var()
    app.selected_hatch_story_var = _Var()
    app.hatch_view_selected_story_var = _Var()
    app.continuous_apply_status_var = _Var()
    app.render_calls = []
    app.refresh_calls = []
    app._render_hatch_preview = lambda *args, **kwargs: app.render_calls.append(kwargs)
    app._refresh_selected_hatch_continuous_info = lambda *args, **kwargs: app.refresh_calls.append(True)
    app._select_dxf_tree_region = lambda _key: None
    app._load_continuous_candidates_for_region = lambda *args, **kwargs: True


def _dxf_region(source_id: str, x0: float):
    polygon = Polygon(((x0, 0.0), (x0 + 10.0, 0.0), (x0 + 10.0, 10.0), (x0, 10.0)))
    load = LoadLayerInfo(layer=f"LOAD_{source_id}", real_name=source_id, dl=1.0, ll=2.0, source="test")
    return LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer=load.layer,
            handle=source_id,
            vertices=list(polygon.exterior.coords)[:-1],
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(value) for value in polygon.bounds),
            story_name="1F",
            source_id=source_id,
        ),
        load=load,
        status="OK",
        warnings=[],
    )


class _Canvas:
    def __init__(self, current_tags, *, existing_items):
        self.current_tags = tuple(current_tags)
        self.existing_items = set(existing_items)
        self.configs = []
        self.deleted = []

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

    def delete(self, item_id):
        self.deleted.append(item_id)

    def itemconfig(self, item_id, **kwargs):
        if item_id not in self.existing_items:
            raise ValueError(f"missing item {item_id}")
        self.configs.append((item_id, dict(kwargs)))

    def config_for(self, item_id):
        merged = {}
        for configured_id, kwargs in self.configs:
            if configured_id == item_id:
                merged.update(kwargs)
        return merged


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
