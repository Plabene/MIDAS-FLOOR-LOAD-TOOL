from pathlib import Path

import pytest
from shapely.geometry import Polygon

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import HatchRegion, LoadRegion, read_load_regions
from app.core.dxf_story_layout import read_layout_metadata
from app.core.dxf_template_writer import LoadLayerSpec, write_all_story_centerline_dxf
from app.core.floorload_mgt_builder import build_assignments_from_regions, run_mgt_build_pipeline
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Element, Node, Story


def test_all_story_region_uses_own_story_nodes_for_snapping(tmp_path: Path):
    result = _write_three_story_template(tmp_path)
    third_floor = next(layout for layout in read_layout_metadata(result.layout_metadata_path) if layout.story_name == "3F")
    user_dxf = tmp_path / "model_ALL_STORIES_floorload_template_edited.dxf"
    source_polygon = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    placed_polygon = [third_floor.transform.apply(x, y) for x, y in source_polygon]

    doc = ezdxf.readfile(result.dxf_path)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "LOAD_001_Office_DL_1.2_LL_3.4"})
    hatch.paths.add_polyline_path(placed_polygon, is_closed=True)
    doc.saveas(user_dxf)

    regions = read_load_regions(user_dxf, metadata_search_dirs=[tmp_path])
    story_nodes_by_name = {
        "1F": [Node(1, 100.0, 100.0, 0.0), Node(2, 110.0, 100.0, 0.0), Node(3, 110.0, 110.0, 0.0)],
        "3F": [
            Node(21, 0.0, 0.0, 9.5),
            Node(22, 10.0, 0.0, 9.5),
            Node(23, 10.0, 10.0, 9.5),
            Node(24, 0.0, 10.0, 9.5),
        ],
    }

    assignments = build_assignments_from_regions(
        regions=regions,
        story_nodes=story_nodes_by_name["1F"],
        story_nodes_by_name=story_nodes_by_name,
        snap_tolerance=0.01,
        include_zero_load=True,
    )

    assert len(assignments) == 1
    assignment = assignments[0]
    assert assignment.status == "OK"
    assert assignment.story_name == "3F"
    assert assignment.node_ids == (21, 22, 23, 24)
    assert assignment.transform_applied is True
    assert assignment.snap_before_transform and assignment.snap_before_transform > 10.0
    assert assignment.snap_after_transform == pytest.approx(0.0)


def test_no_valid_assignments_does_not_write_success_full_mgt(tmp_path: Path):
    source_mgt = tmp_path / "source.mgt"
    source_mgt.write_text("*ENDDATA\n", encoding="cp949")
    output_mgt = tmp_path / "floorload_full.mgt"
    report_dir = tmp_path / "reports"
    preview = report_dir / "preview.dxf"
    vertices = [(100.0, 100.0), (110.0, 100.0), (110.0, 110.0), (100.0, 110.0)]
    polygon = Polygon(vertices)
    region = LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer="LOAD_001_Office_DL_1.2_LL_3.4",
            handle="AA",
            vertices=vertices,
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(v) for v in polygon.bounds),
        ),
        load=LoadLayerInfo("LOAD_001_Office_DL_1.2_LL_3.4", "Office", 1.2, 3.4),
        status="OK",
        warnings=[],
    )

    with pytest.raises(RuntimeError, match="MGT에 입력 가능한 FLOORLOAD가 0개"):
        run_mgt_build_pipeline(
            source_mgt_path=source_mgt,
            output_mgt_path=output_mgt,
            report_dir=report_dir,
            preview_dxf_path=preview,
            model_name="model.mgb",
            story=Story("1F", 0.0),
            dxf_name="user.dxf",
            regions=[region],
            story_nodes=[
                Node(1, 0.0, 0.0, 0.0),
                Node(2, 10.0, 0.0, 0.0),
                Node(3, 10.0, 10.0, 0.0),
                Node(4, 0.0, 10.0, 0.0),
            ],
            snap_tolerance=0.01,
            include_zero_load=True,
        )

    assert not output_mgt.exists()
    assert (report_dir / "model_1F_floorload_report.csv").exists()
    assert preview.exists()


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
