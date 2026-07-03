from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.dxf_story_layout import read_layout_metadata
from app.core.dxf_template_writer import LoadLayerSpec, write_all_story_centerline_dxf
from app.core.mgt_parser import Element, Node, Story


def test_all_story_dxf_hatch_maps_back_to_source_story_coordinates(tmp_path: Path):
    out = tmp_path / "all_story_template.dxf"
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
        Node(13, 10.0, 10.0, 3.0),
        Node(14, 0.0, 10.0, 3.0),
    ]
    elements = [
        Element(1, "SLAB", node_ids=(1, 2, 3, 4)),
        Element(2, "SLAB", node_ids=(11, 12, 13, 14)),
    ]
    load = LoadLayerSpec("Office", 1.2, 3.4)

    result = write_all_story_centerline_dxf(
        output_path=out,
        stories=stories,
        nodes=nodes,
        elements=elements,
        load_layers=[load],
    )
    layouts = read_layout_metadata(result.layout_metadata_path)
    second_story_layout = next(layout for layout in layouts if layout.story_name == "2F")
    load_layer = "LOAD_001_Office_DL_1.2_LL_3.4"
    source_polygon = [(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)]
    placed_polygon = [second_story_layout.transform.apply(x, y) for x, y in source_polygon]

    doc = ezdxf.readfile(out)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": load_layer})
    hatch.paths.add_polyline_path(placed_polygon, is_closed=True)
    doc.saveas(out)

    regions = read_load_regions(out, mapping_path=result.mapping_json_path)

    assert len(regions) == 1
    region = regions[0]
    assert region.region.story_name == "2F"
    assert region.load and region.load.real_name == "Office"
    assert region.status == "OK"
    assert region.region.bbox == pytest.approx((2.0, 2.0, 4.0, 4.0))
    assert region.area == pytest.approx(4.0)
