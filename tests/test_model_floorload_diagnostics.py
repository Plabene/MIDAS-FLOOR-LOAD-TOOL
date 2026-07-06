from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon

from app.core.mgt_parser import Element, Node, Story
from app.core.model_floorload_diagnostics import (
    BLOCKED,
    NO_TARGET_REGION,
    READY,
    READY_WITH_WARNINGS,
    analyze_floorload_model,
)


def test_global_open_boundary_is_not_reported_by_default():
    story = Story("1F", 0.0)
    nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0)]
    elements = [Element(1, "BEAM", node_ids=(1, 2))]

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story], planned_load_regions=None)

    assert result.summary.status == NO_TARGET_REGION
    assert all(issue.issue_type != "OPEN_BOUNDARY" for issue in result.issues)


def test_near_duplicate_does_not_use_snap_tolerance():
    story = Story("1F", 0.0)
    nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 0.4, 0.0, 0.0)]

    result = analyze_floorload_model(nodes=nodes, elements=[], stories=[story], snap_tolerance=0.5)

    assert all(issue.issue_type != "NEAR_DUPLICATE_NODE" for issue in result.issues)


def test_duplicate_element_is_warning_not_blocking_without_target_region():
    story = Story("1F", 0.0)
    nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0)]
    elements = [Element(1, "BEAM", node_ids=(1, 2)), Element(2, "BEAM", node_ids=(2, 1))]

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story])

    assert any(issue.issue_type == "DUPLICATE_ELEMENT" and issue.severity == "WARNING" for issue in result.issues)
    assert result.summary.status == NO_TARGET_REGION


def test_debug_checks_can_report_global_near_duplicate_and_unsplit_member():
    story = Story("1F", 0.0)
    nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0), Node(3, 5.0, 0.0, 0.0), Node(4, 0.00001, 0.0, 0.0)]
    elements = [Element(1, "BEAM", node_ids=(1, 2))]

    result = analyze_floorload_model(
        nodes=nodes,
        elements=elements,
        stories=[story],
        duplicate_node_tolerance=0.0001,
        include_global_debug_checks=True,
    )

    issue_types = {issue.issue_type for issue in result.issues}
    assert "NEAR_DUPLICATE_NODE" in issue_types
    assert "UNSPLIT_MEMBER" in issue_types


def test_planned_region_snap_gap_is_error():
    story = Story("1F", 0.0)
    nodes = _square_nodes(z=0.0)
    region = _region("Office", [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.8)])
    text = _mgt_text_with_floadtype("Office")

    result = analyze_floorload_model(nodes=nodes, elements=[], stories=[story], mgt_text=text, planned_load_regions=[region], snap_tolerance=0.5)

    assert any(issue.issue_type == "SNAP_ERROR_EXCEEDED" and issue.severity == "ERROR" for issue in result.issues)
    assert result.summary.status == BLOCKED


def test_missing_floadtype_is_error_for_planned_region():
    story = Story("1F", 0.0)
    nodes = _square_nodes(z=0.0)
    region = _region("Office", [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    text = _mgt_text_with_floadtype("Retail")

    result = analyze_floorload_model(nodes=nodes, elements=[], stories=[story], mgt_text=text, planned_load_regions=[region])

    assert any(issue.issue_type == "FLOADTYPE_NOT_DEFINED" for issue in result.issues)
    assert result.summary.status == BLOCKED


def test_floorload_nodes_must_be_on_same_story():
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0), Node(3, 10.0, 10.0, 3.0), Node(4, 0.0, 10.0, 0.0)]
    text = _mgt_text_with_floadtype("Office") + """
*FLOORLOAD
   Office, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4
*ENDDATA
"""

    result = analyze_floorload_model(nodes=nodes, elements=[], stories=stories, mgt_text=text)

    assert any(issue.issue_type == "FLOORLOAD_NODE_STORY_MISMATCH" for issue in result.issues)


def test_beam_wall_only_model_is_not_blocked_when_no_target_region():
    story = Story("1F", 0.0)
    nodes = _square_nodes(z=0.0)
    elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "WALL", node_ids=(2, 3)),
        Element(3, "BEAM", node_ids=(3, 4)),
        Element(4, "WALL", node_ids=(4, 1)),
    ]

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story], mgt_text=_mgt_text_with_floadtype("Office"))

    assert result.summary.status == NO_TARGET_REGION
    assert all(issue.issue_type != "SLAB_PLATE_MISSING" for issue in result.issues)


def test_diagnostic_status_ready_and_ready_with_warnings():
    story = Story("1F", 0.0)
    nodes = _square_nodes(z=0.0)
    region = _region("Office", [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    ok = analyze_floorload_model(nodes=nodes, elements=[], stories=[story], mgt_text=_mgt_text_with_floadtype("Office"), planned_load_regions=[region])
    warn = analyze_floorload_model(
        nodes=nodes,
        elements=[Element(1, "BEAM", node_ids=(1, 2)), Element(2, "BEAM", node_ids=(2, 1))],
        stories=[story],
        mgt_text=_mgt_text_with_floadtype("Office"),
        planned_load_regions=[region],
    )

    assert ok.summary.status == READY
    assert warn.summary.status == READY_WITH_WARNINGS


def _square_nodes(*, z: float) -> list[Node]:
    return [
        Node(1, 0.0, 0.0, z),
        Node(2, 10.0, 0.0, z),
        Node(3, 10.0, 10.0, z),
        Node(4, 0.0, 10.0, z),
    ]


def _region(load_name: str, vertices: list[tuple[float, float]], *, story_name: str = "1F", pattern: str = "SOLID"):
    polygon = Polygon(vertices)
    region = SimpleNamespace(
        story_name=story_name,
        vertices=vertices,
        polygon=polygon,
        source_type="HATCH",
        hatch_pattern_name=pattern,
        hatch_solid_fill=1 if pattern == "SOLID" else 0,
        direction_markers=[],
    )
    load = SimpleNamespace(real_name=load_name, floor_load_type_name=load_name, distribution="")
    return SimpleNamespace(region=region, load=load)


def _mgt_text_with_floadtype(load_name: str) -> str:
    return f"""
*UNIT
   KN, M, KCAL, C
*STLDCASE
   DL, DEAD
*FLOADTYPE
   {load_name}
   DL, -1.0, NO
"""
