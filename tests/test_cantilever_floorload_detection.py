from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dummy_member_generator import generate_load_dm_dummy_members
from app.core.mgt_parser import parse_elements_from_text, parse_nodes_from_text, parse_stories_from_text
from app.core.model_floorload_diagnostics import READY, READY_WITH_WARNINGS, analyze_floorload_model


def test_planned_region_reports_cantilever_free_tip_as_separate_issue():
    text = _cantilever_mgt()
    region = _planned_region()

    result = analyze_floorload_model(
        nodes=parse_nodes_from_text(text),
        elements=parse_elements_from_text(text),
        stories=parse_stories_from_text(text),
        mgt_text=text,
        planned_load_regions=[region],
        snap_tolerance=0.6,
        story_tolerance=0.01,
    )

    cantilever = [issue for issue in result.issues if issue.issue_type == "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD"]
    assert len(cantilever) == 1
    assert cantilever[0].story_name == "5F"
    assert cantilever[0].node_ids == [5774]
    assert cantilever[0].element_ids == [6323]
    assert "5F" in cantilever[0].message
    assert "5774" in cantilever[0].message
    assert "6323" in cantilever[0].message
    assert all(issue.issue_type != "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD" for issue in result.issues)


def test_cantilever_free_tip_supported_by_elastic_link_is_info_not_blocking_warning():
    text = _cantilever_mgt(
        """
*ELASTICLINK
   1, GENERAL, 5774, 1993
"""
    )

    result = analyze_floorload_model(
        nodes=parse_nodes_from_text(text),
        elements=parse_elements_from_text(text),
        stories=parse_stories_from_text(text),
        mgt_text=text,
        planned_load_regions=[_planned_region()],
        snap_tolerance=0.6,
        story_tolerance=0.01,
    )

    assert result.summary.status == READY
    assert any(issue.issue_type == "CANTILEVER_FREE_END_SUPPORTED_BY_ELASTIC_LINK" for issue in result.issues)
    assert all(issue.issue_type != "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD" for issue in result.issues)
    assert all(issue.issue_type != "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD" for issue in result.issues)


def test_existing_floorload_region_is_used_for_cantilever_check_without_planned_region():
    text = _cantilever_mgt(
        """
*FLOORLOAD
   Office, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 2002, 1992, 1994, 2001
"""
    )

    result = analyze_floorload_model(
        nodes=parse_nodes_from_text(text),
        elements=parse_elements_from_text(text),
        stories=parse_stories_from_text(text),
        mgt_text=text,
        planned_load_regions=None,
        snap_tolerance=0.6,
        story_tolerance=0.01,
    )

    assert result.summary.status == READY_WITH_WARNINGS
    assert result.summary.planned_region_count == 0
    assert any(issue.issue_type == "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD" and issue.node_ids == [5774] for issue in result.issues)


def test_load_dm_dummy_prefers_cantilever_tip_and_skips_coincident_source_beam():
    summary = generate_load_dm_dummy_members(
        mgt_text=_cantilever_mgt(),
        assignments=[_assignment()],
        snap_tolerance=0.6,
        story_tolerance=0.01,
    )

    assert summary.created_count == 1
    record = next(item for item in summary.records if item.status == "CREATED")
    assert record.free_node_id == 5774
    assert record.source_element_ids == (6323,)
    assert record.boundary_node_id != 1993
    assert record.boundary_node_id in {1992, 1994}
    assert "LOAD DM" in summary.patched_text
    assert "*FRAME-RLS" in summary.patched_text
    assert f"{record.dummy_element_id}, BEAM, {record.material_id}, {record.section_id}, 5774, 1993" not in summary.patched_text


def _planned_region():
    vertices = _floorload_vertices()
    polygon = Polygon(vertices)
    region = SimpleNamespace(
        story_name="5F",
        vertices=vertices,
        polygon=polygon,
        source_id="R-5F",
        source_type="HATCH",
        hatch_pattern_name="SOLID",
        hatch_solid_fill=1,
        direction_markers=[],
    )
    load = SimpleNamespace(real_name="Office", floor_load_type_name="Office", distribution="")
    return SimpleNamespace(region=region, load=load, status="OK")


def _assignment():
    return SimpleNamespace(
        story_name="5F",
        source_id="R-5F",
        merge_group_id="",
        load_type_name="Office",
        node_ids=(2002, 1992, 1994, 2001),
        polygon_vertices=_floorload_vertices(),
        status="OK",
    )


def _floorload_vertices():
    return ((8.0, 2.0), (10.2, 2.0), (10.2, 4.0), (8.0, 4.0))


def _cantilever_mgt(extra_sections: str = "") -> str:
    return f"""
*UNIT
   KN, M, KJ, C
*STORY
   NAME=5F, 20.5
*NODE
   1993, 10.2, 3.0, 20.5
   5774, 9.7, 3.0, 20.5
   1992, 10.2, 2.0, 20.5
   1994, 10.2, 4.0, 20.5
   2001, 8.0, 4.0, 20.5
   2002, 8.0, 2.0, 20.5
*ELEMENT
   6323, BEAM, 12, 213, 5774, 1993, 0, 0
   6221, BEAM, 11, 10, 1992, 1993, 0, 0
*MATERIAL
   11, CONC, C24, 0, 0, , C, NO, 0.05, 2, 2.5e7, 0.167, 1.0e-5, 0, 2.4
   12, CONC, C24, 0, 0, , C, NO, 0.05, 2, 2.5e7, 0.167, 1.0e-5, 0, 2.4
   999, CONC, DM, 0, 0, , C, NO, 0.05, 2, 2.5e7, 0.167, 1.0e-5, 0, 2.4
*SECTION
   10, DBUSER, G1, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.3, 0.5, 0, 0, 0, 0, 0, 0, 0, 0
   213, DBUSER, G3, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.3, 0.5, 0, 0, 0, 0, 0, 0, 0, 0
   999, DBUSER, DM, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.0001, 0.0001, 0, 0, 0, 0, 0, 0, 0, 0
*STLDCASE
   DL, DEAD
*FLOADTYPE
   Office
   DL, -1.0, NO
{extra_sections}
*ENDDATA
"""
