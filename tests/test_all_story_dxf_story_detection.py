from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.dxf_story_layout import read_layout_metadata
from app.core.dxf_template_writer import LoadLayerSpec, write_all_story_centerline_dxf
from app.main import _format_dxf_validation_summary
from app.core.mgt_parser import Element, Node, Story


def test_random_named_user_dxf_finds_single_project_all_story_metadata(tmp_path: Path):
    template_dir = tmp_path / "dxf_templates"
    template_dir.mkdir()
    result = _write_four_story_template(template_dir / "model_ALL_STORIES_floorload_template.dxf")
    fourth_floor = next(layout for layout in read_layout_metadata(result.layout_metadata_path) if layout.story_name == "4F")
    user_dxf = tmp_path / "2222222222222222222222222222222.dxf"
    source_polygon = [(0.0, 0.0), (2.0, 0.0), (2.0, 3.0), (0.0, 3.0)]
    placed_polygon = [fourth_floor.transform.apply(x, y) for x, y in source_polygon]

    doc = ezdxf.readfile(result.dxf_path)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "LOAD_001_Office_DL_1.2_LL_3.4"})
    hatch.paths.add_polyline_path(placed_polygon, is_closed=True)
    doc.saveas(user_dxf)

    regions = read_load_regions(user_dxf, project_dxf_templates_dir=template_dir)

    assert len(regions) == 1
    region = regions[0].region
    assert region.story_name == "4F"
    assert region.layout_metadata_used is True
    assert Path(region.layout_metadata_path) == result.layout_metadata_path
    assert region.transform_applied is True
    assert region.placed_bbox == pytest.approx(tuple(_bounds(placed_polygon)))
    assert region.model_bbox == pytest.approx((0.0, 0.0, 2.0, 3.0))
    assert region.bbox == pytest.approx((0.0, 0.0, 2.0, 3.0))


def test_multiple_metadata_candidates_choose_matching_story_labels(tmp_path: Path):
    template_dir = tmp_path / "dxf_templates"
    template_dir.mkdir()
    _write_named_template(
        template_dir / "other_ALL_STORIES_floorload_template.dxf",
        [Story("B3", 0.0), Story("B2", 3.0), Story("B1", 6.0)],
    )
    result = _write_four_story_template(template_dir / "model_ALL_STORIES_floorload_template.dxf")
    fourth_floor = next(layout for layout in read_layout_metadata(result.layout_metadata_path) if layout.story_name == "4F")
    user_dxf = tmp_path / "renamed_by_user.dxf"

    doc = ezdxf.readfile(result.dxf_path)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "LOAD_001_Office_DL_1.2_LL_3.4"})
    hatch.paths.add_polyline_path([fourth_floor.transform.apply(x, y) for x, y in [(1, 1), (3, 1), (3, 2), (1, 2)]], is_closed=True)
    doc.saveas(user_dxf)

    regions = read_load_regions(user_dxf, project_dxf_templates_dir=template_dir)

    assert len(regions) == 1
    assert regions[0].region.story_name == "4F"
    assert Path(regions[0].region.layout_metadata_path) == result.layout_metadata_path


def test_dxf_validation_summary_shows_story_metadata_and_transform_counts(tmp_path: Path):
    template_dir = tmp_path / "dxf_templates"
    template_dir.mkdir()
    result = _write_four_story_template(template_dir / "model_ALL_STORIES_floorload_template.dxf")
    fourth_floor = next(layout for layout in read_layout_metadata(result.layout_metadata_path) if layout.story_name == "4F")
    user_dxf = tmp_path / "renamed_by_user.dxf"

    doc = ezdxf.readfile(result.dxf_path)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "LOAD_001_Office_DL_1.2_LL_3.4"})
    hatch.paths.add_polyline_path([fourth_floor.transform.apply(x, y) for x, y in [(1, 1), (3, 1), (3, 2), (1, 2)]], is_closed=True)
    doc.saveas(user_dxf)
    regions = read_load_regions(user_dxf, project_dxf_templates_dir=template_dir)

    summary = _format_dxf_validation_summary(regions)

    assert "- 하중영역: 1개" in summary
    assert "- Story 인식: 1개" in summary
    assert "- 4F: 1개" in summary
    assert "- metadata: 사용됨" in summary
    assert "- transform_applied: 1개" in summary


def _write_four_story_template(path: Path):
    return _write_named_template(
        path,
        [Story("1F", 0.0), Story("2F", 3.0), Story("3F", 6.0), Story("4F", 9.0)],
    )


def _write_named_template(path: Path, stories: list[Story]):
    nodes: list[Node] = []
    elements: list[Element] = []
    for index, story in enumerate(stories):
        base = index * 10
        nodes.extend(
            [
                Node(base + 1, 0.0, 0.0, story.elevation),
                Node(base + 2, 10.0, 0.0, story.elevation),
                Node(base + 3, 10.0, 10.0 + index, story.elevation),
                Node(base + 4, 0.0, 10.0 + index, story.elevation),
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


def _bounds(points):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), min(ys), max(xs), max(ys)
