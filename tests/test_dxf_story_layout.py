from pathlib import Path

from shapely.geometry import Polygon

from app.core.dxf_story_layout import (
    BBox2D,
    choose_story_layout_for_polygon,
    plan_story_layouts,
    read_layout_metadata,
    transform_polygon,
    write_layout_metadata,
)
from app.core.mgt_parser import Story


def test_all_story_layout_bboxes_do_not_overlap_vertically():
    layouts = plan_story_layouts(
        [Story("1F", 0.0), Story("2F", 3.0), Story("3F", 6.0)],
        [BBox2D(0.0, 0.0, 10.0, 10.0), BBox2D(-5.0, -2.0, 5.0, 8.0), BBox2D(0.0, 0.0, 20.0, 5.0)],
        dxf_unit_scale_from_model=1000.0,
    )

    for upper, lower in zip(layouts, layouts[1:]):
        assert lower.placed_bbox.max_y < upper.placed_bbox.min_y
    assert all(layout.transform.a == 1000.0 for layout in layouts)
    assert all(layout.transform.d == 1000.0 for layout in layouts)
    assert all(layout.label_x < layout.placed_bbox.min_x for layout in layouts)


def test_story_layout_metadata_roundtrip_preserves_inverse_transform(tmp_path: Path):
    layouts = plan_story_layouts(
        [Story("1F", 0.0), Story("2F", 3.0)],
        [BBox2D(10.0, 20.0, 30.0, 40.0), BBox2D(-5.0, -5.0, 5.0, 5.0)],
    )
    metadata = tmp_path / "template.layout_metadata.json"

    write_layout_metadata(metadata, layouts)
    restored = read_layout_metadata(metadata)

    assert len(restored) == 2
    assert restored[0].story_name == "1F"
    placed = restored[0].transform.apply(12.0, 24.0)
    source = restored[0].inverse_transform.apply(*placed)
    assert source == (12.0, 24.0)


def test_polygon_in_placed_story_region_maps_back_to_original_coordinates():
    layouts = plan_story_layouts(
        [Story("1F", 0.0), Story("2F", 3.0)],
        [BBox2D(0.0, 0.0, 10.0, 10.0), BBox2D(0.0, 0.0, 10.0, 10.0)],
    )
    second = layouts[1]
    source = Polygon([(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)])
    placed = transform_polygon(source, second.transform)

    layout, warning = choose_story_layout_for_polygon(placed, layouts)
    restored = transform_polygon(placed, layout.inverse_transform)

    assert warning is None
    assert layout.story_name == "2F"
    assert restored.bounds == source.bounds


def test_hatch_crossing_two_story_regions_is_ambiguous():
    layouts = plan_story_layouts(
        [Story("1F", 0.0), Story("2F", 3.0)],
        [BBox2D(0.0, 0.0, 10.0, 10.0), BBox2D(0.0, 0.0, 10.0, 10.0)],
    )
    crossing = Polygon(
        [
            (0.0, layouts[1].placed_bbox.min_y),
            (10.0, layouts[1].placed_bbox.min_y),
            (10.0, layouts[0].placed_bbox.max_y),
            (0.0, layouts[0].placed_bbox.max_y),
        ]
    )

    _layout, warning = choose_story_layout_for_polygon(crossing, layouts)

    assert warning == "AMBIGUOUS_STORY"
