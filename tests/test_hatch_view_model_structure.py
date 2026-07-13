from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp


def test_hatch_view_structure_uses_loaded_model_data_and_excludes_artifacts():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0), Story("2F", 3.0)]
    app.nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
        Node(5, 5.0, 5.0, 0.0),
        Node(6, 5.0, 5.0, 3.0),
        Node(7, 0.0, 0.0, 3.0),
        Node(8, 10.0, 0.0, 3.0),
    ]
    app.elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "WALL", node_ids=(1, 2, 3, 4)),
        Element(3, "COLUMN", node_ids=(5, 6)),
        Element(4, "BEAM", node_ids=(7, 8)),
        Element(5, "LOAD_DM", node_ids=(1, 2)),
        Element(6, "ELASTICLINK", node_ids=(1, 2)),
        Element(7, "SLAB", node_ids=(1, 2, 3, 4)),
        Element(8, "LINK", node_ids=(1, 2)),
    ]
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    app._diagnostic_story_nodes_and_elements = _raise_if_called

    items = app._structure_preview_items_for_story("1F")

    by_id = {item["element"].elem_id: item for item in items}
    assert set(by_id) == {1, 2}
    assert by_id[1]["kind"] == "BEAM"
    assert by_id[2]["kind"] == "WALL"


def test_hatch_view_structure_uses_section_size_for_dashed_outlines():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 5.0, 5.0, 0.0),
    ]
    app.elements = [
        Element(1, "BEAM", prop=1, node_ids=(1, 2)),
        Element(2, "COLUMN", prop=2, node_ids=(3,)),
    ]
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n*SECTION\n1, DBUSER, B300x600\n2, DBUSER, C500x500\n"
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)

    items = app._structure_preview_items_for_story("1F")
    by_id = {item["element_id"]: item for item in items}
    canvas = _StructureCanvas()
    app._draw_hatch_structure_items(canvas, items, lambda x, y: (x * 100.0, y * 100.0))

    assert by_id[1]["width"] == 0.3
    assert by_id[1]["depth"] == 0.6
    assert by_id[2]["width"] == 0.5
    assert any(call["kind"] == "rectangle" and call["kwargs"].get("fill") == "#22c55e" for call in canvas.calls)
    assert any(call["kind"] == "rectangle" and "structure_marker" in call["kwargs"].get("tags", ()) for call in canvas.calls)
    assert any(call["kind"] == "line" and call["kwargs"].get("dash") == (5, 3) for call in canvas.calls)


def test_hatch_view_structure_uses_hatch_placed_geometry_transform():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_selected_region_key = "region-1"
    region = _load_region_with_placed_geometry()

    transform = app._hatch_structure_display_transform_for_story("1F", [("region-1", region, region.region.placed_vertices)], {})
    transformed = app._transform_structure_preview_items([{"kind": "BEAM", "points": [(5.0, 5.0), (10.0, 10.0)]}], transform)

    assert transform == (2.0, 3.0, 100.0, 200.0)
    assert transformed[0]["points"] == [(110.0, 215.0), (120.0, 230.0)]


def test_hatch_view_structure_transform_scales_width_and_depth():
    app = object.__new__(FloorLoadAutoApp)

    transformed = app._transform_structure_preview_items(
        [{"kind": "BEAM", "points": [(0.0, 0.0), (1.0, 0.0)], "width": 0.3, "depth": 0.6}],
        (1000.0, 1000.0, 0.0, 0.0),
    )

    assert transformed[0]["points"] == [(0.0, 0.0), (1000.0, 0.0)]
    assert transformed[0]["width"] == 300.0
    assert transformed[0]["depth"] == 600.0


def test_hatch_view_structure_without_section_width_keeps_dashed_fallback():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _StructureCanvas()

    app._draw_hatch_structure_items(
        canvas,
        [{"kind": "BEAM", "points": [(0.0, 0.0), (10.0, 0.0)], "width": None}],
        lambda x, y: (x, y),
    )

    assert any(call["kind"] == "line" and call["kwargs"].get("dash") == (5, 3) for call in canvas.calls)


def test_structure_canvas_dimension_returns_actual_pixels_without_preview_clamp():
    app = object.__new__(FloorLoadAutoApp)

    pixels = app._structure_canvas_dimension(2.0, lambda x, y: (x * 100.0, y * 100.0), (0.0, 0.0))

    assert pixels == 200.0


def test_multi_point_wall_draws_one_joined_offset_outline_without_thick_centerline():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _StructureCanvas()

    app._draw_dashed_offset_polyline(
        canvas,
        [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)],
        80.0,
        outline="#be185d",
        fill="#f9a8d4",
        stipple="gray25",
        tags=("hatch_structure", "structure:WALL"),
    )

    line_calls = [call for call in canvas.calls if call["kind"] == "line"]
    assert len(line_calls) == 1
    assert all(call["kwargs"].get("width") <= 2 for call in line_calls)


def test_hatch_view_structure_uses_story_offset_when_geometry_is_not_placed():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_selected_region_key = "region-1"
    region = _load_region_without_placed_geometry()

    transform = app._hatch_structure_display_transform_for_story("1F", [("region-1", region, region.region.vertices)], {"1F": (50.0, 0.0)})

    assert transform == (1.0, 1.0, 50.0, 0.0)


def test_hatch_view_full_plan_structure_story_prefers_selected_then_first_displayed():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_show_full_plan_var = SimpleNamespace(get=lambda: True)
    app.hatch_view_selected_region_key = "selected"
    app.continuous_base_story_name = SimpleNamespace(get=lambda: "99F")
    first = _load_region_without_placed_geometry(story_name="1F")
    selected = _load_region_without_placed_geometry(story_name="2F")

    assert app._hatch_structure_story_name([("first", first, first.region.vertices), ("selected", selected, selected.region.vertices)]) == "2F"

    app.hatch_view_selected_region_key = ""

    assert app._hatch_structure_story_name([("first", first, first.region.vertices), ("selected", selected, selected.region.vertices)]) == "1F"


def _raise_if_called(*_args, **_kwargs):
    raise AssertionError("Hatch View structure overlay must use loaded model data directly.")


class _StructureCanvas:
    def __init__(self):
        self.calls = []

    def create_rectangle(self, *args, **kwargs):
        self.calls.append({"kind": "rectangle", "args": args, "kwargs": kwargs})

    def create_line(self, *args, **kwargs):
        self.calls.append({"kind": "line", "args": args, "kwargs": kwargs})

    def create_oval(self, *args, **kwargs):
        self.calls.append({"kind": "oval", "args": args, "kwargs": kwargs})


def _load_region_with_placed_geometry():
    model_vertices = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    placed_vertices = [(100.0, 200.0), (120.0, 200.0), (120.0, 230.0), (100.0, 230.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle="A",
        vertices=model_vertices,
        polygon=Polygon(model_vertices),
        area=100.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        story_name="1F",
        source_id="A",
        placed_vertices=placed_vertices,
        placed_bbox=(100.0, 200.0, 120.0, 230.0),
        model_bbox=(0.0, 0.0, 10.0, 10.0),
        transform_applied=True,
    )
    load = LoadLayerInfo(layer=hatch.layer, real_name="A", dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])


def _load_region_without_placed_geometry(*, story_name: str = "1F"):
    model_vertices = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle="A",
        vertices=model_vertices,
        polygon=Polygon(model_vertices),
        area=100.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        story_name=story_name,
        source_id="A",
        placed_bbox=(0.0, 0.0, 10.0, 10.0),
        model_bbox=(0.0, 0.0, 10.0, 10.0),
    )
    load = LoadLayerInfo(layer=hatch.layer, real_name="A", dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])
