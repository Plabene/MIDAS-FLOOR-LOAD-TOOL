from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


def test_story_combo_selection_switches_display_mode_to_story():
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = "ALL_STORIES"
    app.hatch_view_display_mode_var = _Var("ALL")
    app.hatch_view_selected_story_var = _Var("5F")
    calls = []
    app._reset_hatch_view_zoom = lambda: calls.append("reset")
    app._ensure_hatch_edit_states = lambda story_name=None: calls.append(("ensure", story_name))
    app._render_hatch_preview = lambda: calls.append("render")
    app._refresh_selected_hatch_continuous_info = lambda: calls.append("continuous")

    app._on_hatch_view_story_changed()

    assert app.hatch_view_display_mode_var.get() == "STORY"
    assert app._hatch_view_story_filter() == "5F"
    assert calls == ["reset", ("ensure", "5F"), "render", "continuous"]


def test_refresh_story_controls_uses_loaded_region_story_names():
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_story_names = ()
    app.generated_dxf_layout_metadata = ()
    app.loaded_regions = [_load_region("1F"), _load_region("2F")]
    app.stories = []
    app.hatch_view_story_combo = _Combo()
    app.hatch_view_selected_story_var = _Var("")

    app._refresh_hatch_view_story_controls()

    assert app._hatch_view_available_story_names()[:2] == ("1F", "2F")
    assert app.hatch_view_story_combo.values == ("1F", "2F")
    assert app.hatch_view_selected_story_var.get() == "1F"


def _load_region(story_name: str):
    vertices = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle=story_name,
        vertices=vertices,
        polygon=Polygon(vertices),
        area=100.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        story_name=story_name,
        source_id=story_name,
    )
    load = LoadLayerInfo(layer=hatch.layer, real_name="A", dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])


class _Var:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Combo:
    def __init__(self):
        self.values = ()

    def configure(self, **kwargs):
        self.values = tuple(kwargs.get("values", ()))
