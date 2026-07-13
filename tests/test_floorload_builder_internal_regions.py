from pathlib import Path

import pytest
from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.floorload_mgt_builder import filter_dxf_regions_overridden_by_internal_regions, run_mgt_build_pipeline
from app.core.hatch_region_editor import EditableHatchRegion
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Node, Story


def test_run_mgt_build_pipeline_accepts_loaded_internal_hatch_regions_without_dxf(tmp_path: Path):
    pytest.importorskip("ezdxf")
    source_mgt = tmp_path / "source.mgt"
    output_mgt = tmp_path / "floorload_full.mgt"
    report_dir = tmp_path / "reports"
    preview = report_dir / "preview.dxf"
    source_mgt.write_text("*ENDDATA\n", encoding="cp949")
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
    ]
    region = EditableHatchRegion(
        region_key="INTERNAL|1F|A|LOADED|Office",
        story_name="1F",
        cell_ids=("A",),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        load_name="Office",
        load_layer="LOAD_001_Office_DL_1.2_LL_3.4",
        dl=1.2,
        ll=3.4,
        distribution="TWO_WAY",
    )

    result = run_mgt_build_pipeline(
        source_mgt_path=source_mgt,
        output_mgt_path=output_mgt,
        report_dir=report_dir,
        preview_dxf_path=preview,
        model_name="model.mgb",
        story=Story("1F", 0.0),
        dxf_name="HATCH_VIEW_INTERNAL",
        regions=[],
        internal_regions=[region],
        story_nodes=nodes,
        story_nodes_by_name={"1F": nodes},
        snap_tolerance=0.01,
        include_zero_load=True,
    )

    patched = output_mgt.read_text(encoding="cp949")
    assert result.assignment_count == 1
    assert "*FLOORLOAD" in patched
    assert "   Office, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4" in patched
    assert "LOAD_001_" not in patched


def test_internal_regions_override_duplicate_dxf_regions_only_when_story_load_and_geometry_match():
    internal = _internal_region("1F", ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
    duplicate = _dxf_region("1F", ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
    other_story = _dxf_region("2F", ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)))
    other_geometry = _dxf_region("1F", ((20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)))

    kept, removed = filter_dxf_regions_overridden_by_internal_regions(
        [duplicate, other_story, other_geometry],
        [internal],
    )

    assert removed == 1
    assert kept == [other_story, other_geometry]


def _internal_region(story_name: str, polygon_xy) -> EditableHatchRegion:
    return EditableHatchRegion(
        region_key=f"INTERNAL|{story_name}|A|LOADED|Office",
        story_name=story_name,
        cell_ids=("A",),
        polygon_xy=tuple(polygon_xy),
        load_name="Office",
        load_layer="LOAD_001_Office_DL_1.2_LL_3.4",
        dl=1.2,
        ll=3.4,
        distribution="TWO_WAY",
    )


def _dxf_region(story_name: str, vertices) -> LoadRegion:
    polygon = Polygon(vertices)
    layer = "LOAD_001_Office_DL_1.2_LL_3.4"
    return LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer=layer,
            handle=f"DXF_{story_name}",
            vertices=list(vertices),
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(value) for value in polygon.bounds),
            story_name=story_name,
            source_id=f"DXF_{story_name}",
        ),
        load=LoadLayerInfo(layer, "Office", 1.2, 3.4),
        status="OK",
        warnings=[],
    )
