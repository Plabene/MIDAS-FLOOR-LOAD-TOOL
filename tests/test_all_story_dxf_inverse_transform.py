from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.dxf_story_layout import read_layout_metadata
from app.core.dxf_template_writer import LoadLayerSpec, write_all_story_centerline_dxf
from app.core.mgt_parser import Element, Node, Story


def test_all_story_inverse_transform_converts_placed_y_back_to_model_y(tmp_path: Path):
    template_dir = tmp_path / "dxf_templates"
    template_dir.mkdir()
    result = _write_template(template_dir / "model_ALL_STORIES_floorload_template.dxf")
    fourth_floor = next(layout for layout in read_layout_metadata(result.layout_metadata_path) if layout.story_name == "4F")
    user_dxf = tmp_path / "user_renamed.dxf"
    source_polygon = [(0.0, 0.0), (4.0, 0.0), (4.0, 2.0), (0.0, 2.0)]
    placed_polygon = [fourth_floor.transform.apply(x, y) for x, y in source_polygon]

    doc = ezdxf.readfile(result.dxf_path)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "LOAD_001_Office_DL_1.2_LL_3.4"})
    hatch.paths.add_polyline_path(placed_polygon, is_closed=True)
    doc.saveas(user_dxf)

    regions = read_load_regions(user_dxf, project_dxf_templates_dir=template_dir)

    assert len(regions) == 1
    region = regions[0].region
    assert region.story_name == "4F"
    assert region.placed_bbox[1] == pytest.approx(fourth_floor.placed_bbox.min_y)
    assert region.placed_bbox[1] != pytest.approx(region.model_bbox[1])
    assert region.model_bbox == pytest.approx((0.0, 0.0, 4.0, 2.0))
    assert region.vertices[0] == pytest.approx((0.0, 0.0))


def _write_template(path: Path):
    stories = [Story("1F", 0.0), Story("2F", 3.0), Story("3F", 6.0), Story("4F", 9.0)]
    nodes = []
    elements = []
    for index, story in enumerate(stories):
        base = index * 10
        nodes.extend(
            [
                Node(base + 1, 0.0, 0.0, story.elevation),
                Node(base + 2, 10.0, 0.0, story.elevation),
                Node(base + 3, 10.0, 10.0, story.elevation),
                Node(base + 4, 0.0, 10.0, story.elevation),
            ]
        )
        elements.append(Element(index + 1, "SLAB", node_ids=(base + 1, base + 2, base + 3, base + 4)))
    return write_all_story_centerline_dxf(
        output_path=path,
        stories=stories,
        nodes=nodes,
        elements=elements,
        load_layers=[LoadLayerSpec("Office", 1.2, 3.4)],
    )
