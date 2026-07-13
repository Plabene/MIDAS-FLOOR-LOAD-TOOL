from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.dxf_story_layout import Affine2D, BBox2D, StoryLayout
from app.core.hatch_region_editor import EditableHatchRegion, HatchEditState
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp


def test_story_mode_uses_selected_story_regions_and_structure_without_layout_transform():
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = "ALL_STORIES"
    app.generated_dxf_story_names = ("1F", "2F")
    app.generated_dxf_layout_metadata = (_layout("1F", 1000.0), _layout("2F", 2000.0))
    app.hatch_view_display_mode_var = SimpleNamespace(get=lambda: "STORY")
    app.hatch_view_selected_story_var = SimpleNamespace(get=lambda: "2F")
    app.hatch_edit_states_by_story = {
        "1F": HatchEditState("1F", {}, {"edit-1": _edit_region("1F", "edit-1")}, set(), set()),
        "2F": HatchEditState("2F", {}, {"edit-2": _edit_region("2F", "edit-2")}, set(), set()),
    }
    app.stories = [Story("1F", 0.0), Story("2F", 3.0)]
    app.nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 0.0, 0.0, 3.0),
        Node(4, 10.0, 0.0, 3.0),
    ]
    app.elements = [
        Element(1, "BEAM", prop=1, node_ids=(1, 2)),
        Element(2, "BEAM", prop=1, node_ids=(3, 4)),
    ]
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n*SECTION\n1, DBUSER, B300x600\n"
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    app.snap_tol_var = SimpleNamespace(get=lambda: 0.5)
    app.config_data = SimpleNamespace(story_tolerance=0.01, snap_tolerance=0.5)

    edit_display = app._hatch_view_display_edit_regions()
    structure_items = app._structure_preview_items_for_hatch_view([("2F|B", _load_region("2F", "B"), [])], {})
    labels = app._hatch_view_story_label_items([("2F|B", _load_region("2F", "B"), [(0.0, 0.0), (10.0, 0.0)])], edit_display, structure_items)

    assert [region.story_name for _key, region, _vertices in edit_display] == ["2F"]
    assert edit_display[0][2][0] == (0.0, 0.0)
    assert [item["story_name"] for item in structure_items] == ["2F"]
    assert structure_items[0]["points"] == [(0.0, 0.0), (10.0, 0.0)]
    assert labels == []


def _layout(story_name: str, dx: float) -> StoryLayout:
    return StoryLayout(
        story_name=story_name,
        story_index=None,
        elevation=None,
        source_bbox=BBox2D(0.0, 0.0, 10.0, 10.0),
        placed_bbox=BBox2D(dx, 0.0, dx + 10.0, 10.0),
        offset_x=dx,
        offset_y=0.0,
        scale=1.0,
        rotation_deg=0.0,
        insertion_x=dx,
        insertion_y=0.0,
        transform=Affine2D(e=dx),
        inverse_transform=Affine2D(e=-dx),
        label_x=dx,
        label_y=0.0,
        text_height=1.0,
    )


def _edit_region(story_name: str, region_key: str):
    return EditableHatchRegion(
        region_key=region_key,
        story_name=story_name,
        cell_ids=(region_key,),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        load_name=None,
        load_layer=None,
        dl=None,
        ll=None,
        distribution="TWO_WAY",
    )


def _load_region(story_name: str, handle: str):
    vertices = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle=handle,
        vertices=vertices,
        polygon=Polygon(vertices),
        area=100.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        story_name=story_name,
        source_id=handle,
    )
    load = LoadLayerInfo(layer=hatch.layer, real_name="A", dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])
