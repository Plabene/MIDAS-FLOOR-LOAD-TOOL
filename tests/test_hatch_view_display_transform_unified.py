from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.dxf_story_layout import Affine2D, BBox2D, StoryLayout
from app.core.hatch_region_editor import EditableHatchRegion
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp, HatchDisplayTransform


def test_all_story_region_keeps_placed_vertices_and_internal_region_uses_layout_transform():
    app = _app_with_layout()
    region = _load_region_with_wrong_placed_vertices()
    edit_region = EditableHatchRegion(
        region_key="edit-1",
        story_name="1F",
        cell_ids=("cell-1",),
        polygon_xy=((0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)),
        load_name=None,
        load_layer=None,
        dl=None,
        ll=None,
        distribution="TWO_WAY",
    )

    expected = [(1000.0, 2000.0), (1200.0, 2000.0), (1200.0, 2100.0), (1000.0, 2100.0)]

    assert app._region_display_vertices(region, {}) == [(9000.0, 9000.0), (9010.0, 9000.0), (9010.0, 9010.0), (9000.0, 9010.0)]
    assert app._hatch_edit_region_display_vertices(edit_region) == expected


def test_structure_items_use_same_layout_display_transform_and_section_scale():
    app = _app_with_layout()
    app.stories = [Story("1F", 0.0)]
    app.nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 2.0, 0.0, 0.0)]
    app.elements = [Element(1, "BEAM", prop=1, node_ids=(1, 2))]
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n*SECTION\n1, DBUSER, B300x600\n"
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)

    display_transform = app._hatch_display_transform_for_story("1F", [], {})
    items = app._structure_preview_items_for_hatch_view([], {})

    assert isinstance(display_transform, HatchDisplayTransform)
    assert display_transform.source == "layout_metadata"
    assert items[0]["points"] == [(1000.0, 2000.0), (1200.0, 2000.0)]
    assert items[0]["width"] == 30.0
    assert items[0]["depth"] == 60.0


def test_region_display_falls_back_to_placed_vertices_without_layout_metadata():
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = "ALL_STORIES"
    app.hatch_view_display_mode_var = SimpleNamespace(get=lambda: "ALL")
    app.generated_dxf_layout_metadata = ()
    region = _load_region_with_wrong_placed_vertices()

    assert app._region_display_vertices(region, {}) == [(9000.0, 9000.0), (9010.0, 9000.0), (9010.0, 9010.0), (9000.0, 9010.0)]


def _app_with_layout():
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = "ALL_STORIES"
    app.generated_dxf_layout_metadata = (
        StoryLayout(
            story_name="1F",
            story_index=0,
            elevation=0.0,
            source_bbox=BBox2D(0.0, 0.0, 2.0, 1.0),
            placed_bbox=BBox2D(1000.0, 2000.0, 1200.0, 2100.0),
            offset_x=1000.0,
            offset_y=2000.0,
            scale=100.0,
            rotation_deg=0.0,
            insertion_x=1000.0,
            insertion_y=2000.0,
            transform=Affine2D(a=100.0, d=100.0, e=1000.0, f=2000.0),
            inverse_transform=Affine2D(a=0.01, d=0.01, e=-10.0, f=-20.0),
            label_x=1000.0,
            label_y=2000.0,
            text_height=1.0,
        ),
    )
    app.hatch_view_display_mode_var = SimpleNamespace(get=lambda: "ALL")
    return app


def _load_region_with_wrong_placed_vertices():
    model_vertices = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]
    placed_vertices = [(9000.0, 9000.0), (9010.0, 9000.0), (9010.0, 9010.0), (9000.0, 9010.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle="A",
        vertices=model_vertices,
        polygon=Polygon(model_vertices),
        area=2.0,
        bbox=(0.0, 0.0, 2.0, 1.0),
        story_name="1F",
        source_id="A",
        placed_vertices=placed_vertices,
        placed_bbox=(9000.0, 9000.0, 9010.0, 9010.0),
        model_bbox=(0.0, 0.0, 2.0, 1.0),
        transform_applied=True,
    )
    load = LoadLayerInfo(layer=hatch.layer, real_name="A", dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])
