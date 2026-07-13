from types import SimpleNamespace

from app.core.dxf_story_layout import Affine2D, BBox2D, StoryLayout
from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp, HatchDisplayTransform


def test_all_story_structure_uses_each_layout_transform_and_scales_dimensions():
    app = _app_with_two_story_structure()

    items = app._structure_preview_items_for_hatch_view([], {})
    by_story = {item["story_name"]: item for item in items}

    assert by_story["1F"]["points"] == [(0.0, 0.0), (1000.0, 0.0)]
    assert by_story["1F"]["width"] == 300.0
    assert by_story["2F"]["points"] == [(10000.0, 0.0), (11000.0, 0.0)]
    assert by_story["2F"]["width"] == 300.0


def test_structure_transform_available_without_display_regions_when_layout_exists():
    app = _app_with_two_story_structure()

    transform = app._hatch_display_transform_for_story("2F", [], {})
    item = app._transform_structure_preview_items(
        [{"kind": "BEAM", "points": [(0.0, 0.0), (1.0, 0.0)], "width": 0.3}],
        transform,
    )[0]

    assert isinstance(transform, HatchDisplayTransform)
    assert transform.source == "layout_metadata"
    assert item["points"] == [(10000.0, 0.0), (11000.0, 0.0)]
    assert item["width"] == 300.0


def test_story_mode_structure_uses_selected_story_only():
    app = _app_with_two_story_structure()
    app.hatch_view_display_mode_var = SimpleNamespace(get=lambda: "STORY")
    app.hatch_view_selected_story_var = SimpleNamespace(get=lambda: "2F")

    items = app._structure_preview_items_for_hatch_view([], {})

    assert [item["story_name"] for item in items] == ["2F"]
    assert items[0]["points"] == [(0.0, 0.0), (1.0, 0.0)]


def test_canvas_view_transform_moves_region_and_structure_together_after_pan():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_fit_bbox = (0.0, 0.0, 100.0, 100.0)
    app.hatch_view_view_bbox = (10.0, 0.0, 110.0, 100.0)

    transform, _width, _height = app._hatch_canvas_transform(app.hatch_view_view_bbox, 200, 200)

    assert transform(10.0, 0.0) == (0.0, 200.0)
    assert transform(20.0, 0.0) == (20.0, 200.0)


def _app_with_two_story_structure():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0), Story("2F", 3.0)]
    app.nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 1.0, 0.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 1.0, 0.0, 3.0),
    ]
    app.elements = [
        Element(1, "BEAM", prop=1, node_ids=(1, 2)),
        Element(2, "BEAM", prop=1, node_ids=(11, 12)),
    ]
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n*SECTION\n1, DBUSER, B300x600\n"
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    app.hatch_view_display_mode_var = SimpleNamespace(get=lambda: "ALL")
    app.hatch_view_selected_story_var = SimpleNamespace(get=lambda: "")
    app.generated_dxf_mode = "ALL_STORIES"
    app.generated_dxf_story_names = ("1F", "2F")
    app.generated_dxf_layout_metadata = (
        _layout("1F", 0.0),
        _layout("2F", 10000.0),
    )
    return app


def _layout(story_name: str, offset_x: float) -> StoryLayout:
    return StoryLayout(
        story_name=story_name,
        story_index=0,
        elevation=0.0,
        source_bbox=BBox2D(0.0, 0.0, 1.0, 1.0),
        placed_bbox=BBox2D(offset_x, 0.0, offset_x + 1000.0, 1000.0),
        offset_x=offset_x,
        offset_y=0.0,
        scale=1000.0,
        rotation_deg=0.0,
        insertion_x=offset_x,
        insertion_y=0.0,
        transform=Affine2D(a=1000.0, d=1000.0, e=offset_x),
        inverse_transform=Affine2D(a=0.001, d=0.001, e=-offset_x * 0.001),
        label_x=offset_x,
        label_y=0.0,
        text_height=1.0,
    )
