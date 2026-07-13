from types import SimpleNamespace
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from app.core.dummy_member_generator import generate_load_dm_dummy_members
from app.core.floorload_mgt_builder import run_mgt_build_pipeline
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Node, Story


def test_creates_load_dm_dummy_for_internal_free_node_without_elastic_link():
    summary = generate_load_dm_dummy_members(mgt_text=_base_mgt(), assignments=[_assignment()])

    assert summary.created_count == 1
    assert summary.material_id == 9999
    assert summary.section_id == 9999
    record = _created(summary)
    assert record.free_node_id == 5
    assert record.boundary_node_id == 1
    assert f"{record.dummy_element_id}, BEAM, 9999, 9999, 5, 1" in summary.patched_text
    assert "*FRAME-RLS" in summary.patched_text
    assert f"{record.dummy_element_id}, NO, 000011, 0, 0, 0, 0, 0, 0" in summary.patched_text
    assert "000011, 0, 0, 0, 0, 0, 0," in summary.patched_text


def test_elastic_link_to_boundary_skips_dummy_creation():
    text = _base_mgt(
        """
*ELASTICLINK
   1, 5, 1
"""
    )

    summary = generate_load_dm_dummy_members(mgt_text=text, assignments=[_assignment()])

    assert summary.created_count == 0
    assert summary.skipped_count >= 1
    assert any(record.skip_reason == "SUPPORTED_BY_ELASTIC_LINK" for record in summary.records)
    assert "LOAD DM" not in summary.patched_text


def test_intersecting_nearest_boundary_path_uses_next_clear_boundary_node():
    text = _base_mgt(
        extra_nodes="""
  7, 0.2, 1.8, 0
  8, 1.8, 0.2, 0
""",
        extra_elements="""
  2, COLUMN, 1, 1, 7, 8, 0, 0
""",
    )

    summary = generate_load_dm_dummy_members(mgt_text=text, assignments=[_assignment()])

    record = _created(summary)
    assert record.boundary_node_id != 1
    assert record.boundary_node_id in {2, 4}


def test_material_and_section_id_collision_uses_next_descending_id():
    text = _base_mgt(
        extra_material="""
  9999, CONC, EXISTING, 0, 0, , C, NO, 0.05, 2, 2.5e7, 0.167, 1.0e-5, 0, 2.4
""",
        extra_section="""
  9999, DBUSER, EXISTING, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.0001, 0.0001, 0, 0, 0, 0, 0, 0, 0, 0
""",
    )

    summary = generate_load_dm_dummy_members(mgt_text=text, assignments=[_assignment()])

    assert summary.material_id == 9998
    assert summary.section_id == 9998
    assert "9999, CONC, EXISTING" in summary.patched_text
    assert "9999, DBUSER, EXISTING" in summary.patched_text


def test_existing_load_dm_name_with_different_dm_payload_creates_new_id():
    text = _base_mgt(
        extra_material="""
  9999, CONC, LOAD DM, 0, 0, , C, NO, 0.10, 2, 3.0e7, 0.200, 1.0e-5, 0, 2.4
""",
        extra_section="""
  9999, DBUSER, LOAD DM, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.003, 0.003, 0, 0, 0, 0, 0, 0, 0, 0
""",
    )

    summary = generate_load_dm_dummy_members(mgt_text=text, assignments=[_assignment()])

    assert summary.material_id == 9998
    assert summary.section_id == 9998
    assert "LOAD_DM_MATERIAL_NAME_CONFLICT_CREATED_NEW_ID" in summary.warnings
    assert "LOAD_DM_SECTION_NAME_CONFLICT_CREATED_NEW_ID" in summary.warnings
    assert "9999, CONC, LOAD DM, 0, 0, , C, NO, 0.10" in summary.patched_text
    assert "9998, CONC, LOAD DM, 0, 0, , C, NO, 0.05" in summary.patched_text
    assert "9998, DBUSER, LOAD DM, CC" in summary.patched_text


def test_free_node_selection_prefers_inner_tip_not_centroid_nearest_node():
    text = _base_mgt(
        extra_nodes="""
  7, 2, 5, 0
""",
        extra_elements="""
  2, BEAM, 1, 1, 5, 7, 0, 0
""",
    )

    summary = generate_load_dm_dummy_members(mgt_text=text, assignments=[_assignment()])

    record = _created(summary)
    assert record.free_node_id == 6
    assert record.free_node_id != 5
    assert record.source_element_ids == (1,)


def test_elastic_link_to_boundary_near_node_skips_dummy_creation():
    text = _base_mgt(
        extra_nodes="""
  99, 0.2, 5, 0
""",
        extra_tail="""
*ELASTICLINK
   1, 5, 99
""",
    )

    summary = generate_load_dm_dummy_members(mgt_text=text, assignments=[_assignment()])

    assert summary.created_count == 0
    assert any(record.skip_reason == "SUPPORTED_BY_ELASTIC_LINK" for record in summary.records)


def test_existing_mgt_lines_are_preserved_when_dummy_is_inserted():
    text = _base_mgt(
        extra_tail="""
*FRAME-RLS    ; Beam End Release
   100, NO, 000011, 0, 0, 0, 0, 0, 0
        000011, 0, 0, 0, 0, 0, 0,
*FLOORLOAD
   Office, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4
"""
    )

    summary = generate_load_dm_dummy_members(mgt_text=text, assignments=[_assignment()])

    assert "100, NO, 000011" in summary.patched_text
    assert "Office, 2, 0, 0, 0, 0, GZ" in summary.patched_text
    assert summary.patched_text.rstrip().endswith("*ENDDATA")


def test_missing_story_skips_without_arbitrary_cross_story_snap():
    summary = generate_load_dm_dummy_members(mgt_text=_base_mgt(), assignments=[_assignment(story_name="2F")])

    assert summary.created_count == 0
    assert summary.skipped_count >= 1
    assert any(record.skip_reason == "STORY_NOT_DETECTED" for record in summary.records)


def test_build_pipeline_can_apply_dummy_patch_before_floorload_append(tmp_path: Path):
    pytest.importorskip("ezdxf")
    from app.core.dxf_load_reader import HatchRegion, LoadRegion

    source_mgt = tmp_path / "source.mgt"
    output_mgt = tmp_path / "floorload_full.mgt"
    report_dir = tmp_path / "reports"
    preview = report_dir / "preview.dxf"
    source_mgt.write_text(_base_mgt(), encoding="cp949")
    vertices = _assignment().polygon_vertices
    polygon = Polygon(vertices)
    region = LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer="LOAD_001_Office_DL_1.2_LL_3.4",
            handle="AA",
            vertices=vertices,
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(value) for value in polygon.bounds),
            story_name="1F",
            source_id="R1",
        ),
        load=LoadLayerInfo("LOAD_001_Office_DL_1.2_LL_3.4", "Office", 1.2, 3.4),
        status="OK",
        warnings=[],
    )

    result = run_mgt_build_pipeline(
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
        story_nodes_by_name={
            "1F": [
                Node(1, 0.0, 0.0, 0.0),
                Node(2, 10.0, 0.0, 0.0),
                Node(3, 10.0, 10.0, 0.0),
                Node(4, 0.0, 10.0, 0.0),
                Node(5, 5.0, 5.0, 0.0),
                Node(6, 5.0, 7.0, 0.0),
            ],
        },
        snap_tolerance=0.01,
        include_zero_load=True,
        auto_load_dm_dummy_members=True,
        story_tolerance=0.01,
    )

    patched = output_mgt.read_text(encoding="cp949")
    assert result.dummy_summary is not None
    assert result.dummy_summary.created_count == 1
    assert "*FLOORLOAD" in patched
    assert "LOAD DM" in patched
    assert "*FRAME-RLS" in patched
    assert result.dummy_report_csv_path and result.dummy_report_csv_path.exists()


def _created(summary):
    return next(record for record in summary.records if record.status == "CREATED")


def _assignment(*, story_name: str = "1F"):
    return SimpleNamespace(
        story_name=story_name,
        source_id="R1",
        merge_group_id="",
        load_type_name="Office",
        node_ids=(1, 2, 3, 4),
        polygon_vertices=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        status="OK",
    )


def _base_mgt(
    extra_tail: str = "",
    *,
    extra_nodes: str = "",
    extra_elements: str = "",
    extra_material: str = "",
    extra_section: str = "",
) -> str:
    return f"""
*UNIT
   KN, M, KJ, C
*STORY
   NAME=1F, 0
*NODE
  1, 0, 0, 0
  2, 10, 0, 0
  3, 10, 10, 0
  4, 0, 10, 0
  5, 5, 5, 0
  6, 5, 7, 0
{extra_nodes}
*ELEMENT
  1, BEAM, 1, 1, 6, 5, 0, 0
  10, BEAM, 1, 1, 1, 2, 0, 0
  11, BEAM, 1, 1, 2, 3, 0, 0
  12, BEAM, 1, 1, 3, 4, 0, 0
  13, BEAM, 1, 1, 4, 1, 0, 0
{extra_elements}
*MATERIAL
  1, CONC, DM, 0, 0, , C, NO, 0.05, 2, 2.5e7, 0.167, 1.0e-5, 0, 2.4
{extra_material}
*SECTION
  1, DBUSER, DM, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.0001, 0.0001, 0, 0, 0, 0, 0, 0, 0, 0
{extra_section}
{extra_tail}
*ENDDATA
"""
