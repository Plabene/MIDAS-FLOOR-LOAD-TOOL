from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.dxf_story_layout import Affine2D, read_layout_metadata
from app.core.dxf_template_writer import LoadLayerSpec, write_all_story_centerline_dxf
from app.core.mgt_parser import Element, Node, Story


def test_user_input_dxf_finds_original_template_layout_metadata(tmp_path: Path):
    result = _write_three_story_template(tmp_path)
    layouts = read_layout_metadata(result.layout_metadata_path)
    third_floor = next(layout for layout in layouts if layout.story_name == "3F")
    user_dxf = tmp_path / "model_ALL_STORIES_floorload_template_사용자입력.dxf"
    source_polygon = [(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0)]
    placed_polygon = [third_floor.transform.apply(x, y) for x, y in source_polygon]

    doc = ezdxf.readfile(result.dxf_path)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "LOAD_001_Office_DL_1.2_LL_3.4"})
    hatch.paths.add_polyline_path(placed_polygon, is_closed=True)
    doc.saveas(user_dxf)

    regions = read_load_regions(user_dxf, metadata_search_dirs=[tmp_path])

    assert len(regions) == 1
    region = regions[0]
    assert region.region.story_name == "3F"
    assert region.load and region.load.real_name == "Office"
    assert region.region.layout_metadata_used is True
    assert Path(region.region.layout_metadata_path) == result.layout_metadata_path
    assert region.region.transform_applied is True
    assert region.region.placed_bbox == pytest.approx(tuple(PolygonBounds(placed_polygon)))
    assert region.region.bbox == pytest.approx((1.0, 1.0, 3.0, 3.0))


def test_3f_inverse_transform_removes_vertical_offset():
    inverse_transform = Affine2D(e=0.0, f=-110.61).inverse()

    model = inverse_transform.apply(6.585, -110.61)

    assert model == pytest.approx((6.585, 0.0))


def _write_three_story_template(tmp_path: Path):
    out = tmp_path / "model_ALL_STORIES_floorload_template.dxf"
    stories = [Story("1F", 0.0), Story("2F", 3.0), Story("3F", 9.5)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
        Node(13, 10.0, 10.0, 3.0),
        Node(14, 0.0, 10.0, 3.0),
        Node(21, 0.0, 0.0, 9.5),
        Node(22, 10.0, 0.0, 9.5),
        Node(23, 10.0, 10.0, 9.5),
        Node(24, 0.0, 10.0, 9.5),
    ]
    elements = [
        Element(1, "SLAB", node_ids=(1, 2, 3, 4)),
        Element(2, "SLAB", node_ids=(11, 12, 13, 14)),
        Element(3, "SLAB", node_ids=(21, 22, 23, 24)),
    ]
    return write_all_story_centerline_dxf(
        output_path=out,
        stories=stories,
        nodes=nodes,
        elements=elements,
        load_layers=[LoadLayerSpec("Office", 1.2, 3.4)],
    )


def PolygonBounds(points):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return (min(xs), min(ys), max(xs), max(ys))
