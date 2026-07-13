from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp


def test_hatch_preview_renders_all_regions_without_selection():
    app = object.__new__(FloorLoadAutoApp)
    app.loaded_regions = [
        _load_region("A", "LOAD_001_A_DL_1_LL_1"),
        _load_region("B", "LOAD_002_B_DL_1_LL_1", offset=20.0),
    ]
    app.hatch_view_selected_region_key = None
    app.hatch_view_region_by_key = {}
    app.hatch_view_region_items = {}
    app.hatch_view_checkbox_items = {}
    app.continuous_hatch_checks = {
        app._region_key(app.loaded_regions[0], index=1): {"can_select": True, "applicable_targets": ("2F",), "blocked_targets": ()},
        app._region_key(app.loaded_regions[1], index=2): {"can_select": False, "reason": "불가", "applicable_targets": (), "blocked_targets": ()},
    }
    app.stories = []
    app.hatch_view_focus_selected_var = SimpleNamespace(get=lambda: False)
    app.hatch_view_highlight_continuous_var = SimpleNamespace(get=lambda: False)
    app.hatch_view_show_legend_var = SimpleNamespace(get=lambda: False)
    app.hatch_preview_info_var = _Var()
    app.hatch_preview_legend_var = _Var()
    app.hatch_preview_canvas = _FakeCanvas()

    app._render_hatch_preview()

    assert len(app.hatch_preview_canvas.polygons) == 2
    assert len(app.hatch_view_region_items) == 2
    assert len(app.hatch_view_checkbox_items) == 2


def test_hatch_preview_uses_distinct_palette_for_different_layers():
    app = object.__new__(FloorLoadAutoApp)
    first = _load_region("A", "LOAD_001_A_DL_1_LL_1")
    second = _load_region("B", "LOAD_002_B_DL_1_LL_1")

    assert app._region_display_color(first) != app._region_display_color(second)


def test_structure_preview_items_include_beam_wall_and_column():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0), Story("2F", 3.0)]
    app.nodes = [
        Node(5, 5.0, 5.0, 0.0),
        Node(6, 5.0, 5.0, 3.0),
        Node(7, 0.0, 0.0, 3.0),
        Node(8, 10.0, 0.0, 3.0),
        Node(9, 10.0, 10.0, 3.0),
        Node(10, 0.0, 10.0, 3.0),
    ]
    app.elements = [
        Element(1, "BEAM", node_ids=(7, 8)),
        Element(2, "WALL", node_ids=(8, 9, 10, 7)),
        Element(3, "COLUMN", node_ids=(5, 6)),
    ]
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)

    kinds = {item["kind"] for item in app._structure_preview_items_for_story("2F")}

    assert {"BEAM", "WALL", "COLUMN"} <= kinds


def test_hatch_preview_focus_bbox_uses_selected_hatch_not_far_structure():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_selected_region_key = "selected"
    app.hatch_view_show_full_plan_var = SimpleNamespace(get=lambda: False)
    display_regions = [
        ("selected", object(), [(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)]),
    ]
    structure_items = [{"kind": "BEAM", "points": [(100.0, 100.0), (120.0, 100.0)]}]

    bbox = app._hatch_preview_focus_bbox(display_regions, structure_items)

    assert bbox[2] < 5.0
    assert bbox[3] < 5.0


def test_filter_structure_items_near_focus_bbox_keeps_near_items():
    app = object.__new__(FloorLoadAutoApp)
    near = {"kind": "BEAM", "points": [(1.0, 1.0), (3.0, 1.0)]}
    far = {"kind": "BEAM", "points": [(100.0, 100.0), (110.0, 100.0)]}

    filtered = app._filter_structure_items_near_bbox([near, far], (0.0, 0.0, 4.0, 4.0), margin_ratio=0.25)

    assert filtered == [near]


class _Var:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = value


class _FakeCanvas:
    def __init__(self):
        self.polygons = []
        self._next_id = 1

    def winfo_width(self):
        return 640

    def winfo_height(self):
        return 520

    def delete(self, *_args):
        self.polygons.clear()

    def configure(self, **_kwargs):
        return None

    def create_polygon(self, *args, **kwargs):
        self.polygons.append((args, kwargs))
        return self._id()

    def create_text(self, *_args, **_kwargs):
        return self._id()

    def create_rectangle(self, *_args, **_kwargs):
        return self._id()

    def create_line(self, *_args, **_kwargs):
        return self._id()

    def create_oval(self, *_args, **_kwargs):
        return self._id()

    def _id(self):
        value = self._next_id
        self._next_id += 1
        return value


def _load_region(source_id: str, layer: str, *, offset: float = 0.0):
    vertices = [(offset, 0.0), (offset + 10.0, 0.0), (offset + 10.0, 10.0), (offset, 10.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer=layer,
        handle=source_id,
        vertices=vertices,
        polygon=Polygon(vertices),
        area=100.0,
        bbox=(offset, 0.0, offset + 10.0, 10.0),
        story_name="1F",
        source_id=source_id,
    )
    load = LoadLayerInfo(layer=layer, real_name=source_id, dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])
