from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.mgt_parser import Element, Node, Story
from app.core.model_floorload_diagnostics import (
    NO_TARGET_REGION,
    READY,
    READY_WITH_WARNINGS,
    _validate_polygon_xy,
    analyze_floorload_model,
    has_elastic_path_to_boundary,
)


def test_model_diagnostics_does_not_block_one_way_five_node_existing_floorload():
    story = Story("1F", 0.0)
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 12.0, 5.0, 0.0),
        Node(4, 5.0, 10.0, 0.0),
        Node(5, 0.0, 5.0, 0.0),
    ]
    text = _mgt_text(
        """
*FLOORLOAD
   Office, 1, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4, 5
"""
    )

    result = analyze_floorload_model(nodes=nodes, elements=[], stories=[story], mgt_text=text)

    assert result.summary.status == READY
    assert all(issue.issue_type != "INVALID_ONE_WAY_FLOORLOAD_NODE_COUNT" for issue in result.issues)
    assert all(issue.issue_type != "AMBIGUOUS_ONEWAY_DIRECTION" for issue in result.issues)


def test_one_way_node_count_rule_is_opt_in_for_generation_style_validation():
    region = _region("Office", [(0.0, 0.0), (10.0, 0.0), (12.0, 5.0), (5.0, 10.0), (0.0, 5.0)], pattern="ANSI31")

    default_issues = _validate_polygon_xy(region.region.vertices, "1F", [], [], 0.0, 0.0, load_region=region)
    generation_issues = _validate_polygon_xy(
        region.region.vertices,
        "1F",
        [],
        [],
        0.0,
        0.0,
        load_region=region,
        validate_one_way_rules=True,
    )

    assert all(issue.issue_type != "INVALID_ONE_WAY_FLOORLOAD_NODE_COUNT" for issue in default_issues)
    assert any(issue.issue_type == "INVALID_ONE_WAY_FLOORLOAD_NODE_COUNT" for issue in generation_issues)


def test_internal_member_connected_to_boundary_by_elastic_link_is_not_blocked():
    story = Story("1F", 0.0)
    nodes = _square_nodes() + [Node(10, 5.0, 5.0, 0.0), Node(11, 6.0, 5.0, 0.0)]
    elements = [Element(100, "BEAM", node_ids=(10, 11))]
    region = _region("Office", _square_vertices())
    text = _mgt_text(
        """
*ELASTICLINK
   1, GENERAL, 10, 1
   2, GENERAL, 11, 2
"""
    )

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story], mgt_text=text, planned_load_regions=[region])

    assert result.summary.status == READY
    assert any(issue.issue_type == "INTERNAL_MEMBER_SUPPORTED_BY_ELASTIC_LINK" and issue.severity == "INFO" for issue in result.issues)
    assert all(issue.issue_type != "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD" for issue in result.issues)


def test_internal_member_without_elastic_link_is_warning_not_blocked():
    story = Story("1F", 0.0)
    nodes = _square_nodes() + [Node(10, 5.0, 5.0, 0.0), Node(11, 6.0, 5.0, 0.0)]
    elements = [Element(100, "BEAM", node_ids=(10, 11))]
    region = _region("Office", _square_vertices())

    result = analyze_floorload_model(
        nodes=nodes,
        elements=elements,
        stories=[story],
        mgt_text=_mgt_text(),
        planned_load_regions=[region],
    )

    assert result.summary.status == READY_WITH_WARNINGS
    assert any(issue.issue_type == "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD" and issue.severity == "WARNING" for issue in result.issues)
    assert not any(issue.severity == "ERROR" and issue.issue_type.startswith("INTERNAL_MEMBER") for issue in result.issues)


def test_without_planned_region_internal_elastic_precision_check_is_skipped():
    story = Story("1F", 0.0)
    nodes = _square_nodes() + [Node(10, 5.0, 5.0, 0.0), Node(11, 6.0, 5.0, 0.0)]
    elements = [Element(100, "BEAM", node_ids=(10, 11))]

    result = analyze_floorload_model(
        nodes=nodes,
        elements=elements,
        stories=[story],
        mgt_text=_mgt_text(
            """
*ELASTICLINK
   1, GENERAL, 10, 1
"""
        ),
        planned_load_regions=None,
    )

    assert result.summary.status == NO_TARGET_REGION
    assert result.summary.elastic_link_count == 1
    assert all(not issue.issue_type.startswith("INTERNAL_MEMBER") for issue in result.issues)


def test_elastic_link_graph_path_respects_max_depth():
    graph = {
        10: {20},
        20: {10, 30},
        30: {20, 1},
        1: {30},
    }

    assert has_elastic_path_to_boundary(10, {1}, graph, max_depth=3)
    assert not has_elastic_path_to_boundary(10, {1}, graph, max_depth=2)


def test_internal_member_linked_to_near_boundary_node_is_supported():
    story = Story("1F", 0.0)
    nodes = _square_nodes() + [
        Node(10, 5.0, 5.0, 0.0),
        Node(11, 6.0, 5.0, 0.0),
        Node(99, 0.0, 5.0, 0.0),
    ]
    elements = [Element(100, "BEAM", node_ids=(10, 11))]
    region = _region("Office", _square_vertices())
    text = _mgt_text(
        """
*ELASTICLINK
   1, GENERAL, 10, 99
   2, GENERAL, 11, 99
"""
    )

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story], mgt_text=text, planned_load_regions=[region])

    assert result.summary.status == READY
    assert any(issue.issue_type == "INTERNAL_MEMBER_SUPPORTED_BY_ELASTIC_LINK" for issue in result.issues)
    assert all(issue.issue_type != "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD" for issue in result.issues)


def test_diagnostics_missing_story_does_not_use_all_nodes_for_internal_member_check():
    stories = [Story("1F", 0.0)]
    nodes = _square_nodes() + [Node(10, 5.0, 5.0, 0.0), Node(11, 6.0, 5.0, 0.0)]
    elements = [Element(100, "BEAM", node_ids=(10, 11))]
    region = _region("Office", _square_vertices(), story_name="2F")

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=stories, mgt_text=_mgt_text(), planned_load_regions=[region])

    assert any(issue.issue_type == "STORY_NOT_DETECTED" and issue.severity == "WARNING" for issue in result.issues)
    assert all(issue.issue_type != "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD" for issue in result.issues)
    assert all(issue.issue_type != "INTERNAL_MEMBER_SUPPORTED_BY_ELASTIC_LINK" for issue in result.issues)


def _square_vertices() -> list[tuple[float, float]]:
    return [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def _square_nodes() -> list[Node]:
    return [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
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


def _mgt_text(extra_sections: str = "") -> str:
    return f"""
*UNIT
   KN, M, KCAL, C
*STLDCASE
   DL, DEAD
*FLOADTYPE
   Office
   DL, -1.0, NO
{extra_sections}
*ENDDATA
"""
