import pytest

from app.core.floorload_mgt_builder import FloorLoadAssignment, expand_floorload_assignment_to_story
from app.core.mgt_parser import Element, Node, Story
from app.core.typical_floor_detector import (
    build_story_shape_profiles,
    evaluate_continuous_apply_candidates,
    split_continuous_apply_ranges,
)


def test_hatch_can_apply_to_same_outer_nodes_with_different_internal_nodes():
    stories, nodes, elements = _stories_for_continuous_apply()
    nodes.append(Node(999, 5.0, 5.0, 3.0))
    profiles = build_story_shape_profiles(stories=stories[:2], nodes=nodes, elements=elements[:2], story_tolerance=0.01, xy_tolerance=0.02)

    candidates = evaluate_continuous_apply_candidates(
        profiles,
        base_story_name="1F",
        hatch_polygon_xy=_square(),
        xy_tolerance=0.02,
    )

    assert len(candidates) == 1
    assert candidates[0].target_story_name == "2F"
    assert candidates[0].can_apply is True
    assert candidates[0].boundary_node_match_ratio == pytest.approx(1.0)


def test_missing_outer_node_blocks_continuous_apply():
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
        Node(13, 10.0, 10.0, 3.0),
    ]
    elements = [Element(1, "SLAB", node_ids=(1, 2, 3, 4)), Element(2, "SLAB", node_ids=(11, 12, 13))]
    profiles = build_story_shape_profiles(stories=stories, nodes=nodes, elements=elements, story_tolerance=0.01, xy_tolerance=0.02)

    candidates = evaluate_continuous_apply_candidates(
        profiles,
        base_story_name="1F",
        hatch_polygon_xy=_square(),
        xy_tolerance=0.02,
    )

    assert candidates[0].can_apply is False
    assert "BOUNDARY_NODE_MISMATCH" in candidates[0].reason or "IOU_BELOW_THRESHOLD" in candidates[0].reason


def test_middle_mismatch_splits_continuous_apply_range():
    candidates = [
        _candidate("2F", True),
        _candidate("3F", False),
        _candidate("4F", True),
        _candidate("5F", True),
    ]

    ranges = split_continuous_apply_ranges(candidates, ["2F", "3F", "4F", "5F"])

    assert ranges == (("2F",), ("4F", "5F"))


def test_one_way_angle_is_recalculated_from_target_story_node_order():
    assignment = FloorLoadAssignment(
        load_type_name="OneWay",
        dl=1.0,
        ll=0.0,
        node_ids=(1, 2, 3, 4),
        source_layer="LOAD_001_OneWay_DL_1_LL_0",
        source_type="HATCH",
        area=100.0,
        status="OK",
        warnings=(),
        story_name="1F",
        effective_idist=1,
        one_way_angle_deg=0.0,
        one_way_mgt_angle_deg=12.0,
        polygon_vertices=_square(),
    )
    target_nodes = [
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 0.0, 10.0, 3.0),
        Node(13, 10.0, 10.0, 3.0),
        Node(14, 10.0, 0.0, 3.0),
    ]

    expanded = expand_floorload_assignment_to_story(
        assignment,
        target_story_name="2F",
        target_story_nodes=target_nodes,
        polygon_xy=((0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0)),
        snap_tolerance=0.02,
    )

    assert expanded.story_name == "2F"
    assert expanded.node_ids == (11, 12, 13, 14)
    assert expanded.one_way_first_edge_angle_deg == pytest.approx(90.0)
    assert expanded.one_way_mgt_angle_deg == pytest.approx(90.0)
    assert expanded.one_way_mgt_angle_deg != assignment.one_way_mgt_angle_deg


def _stories_for_continuous_apply():
    stories = [Story("1F", 0.0), Story("2F", 3.0), Story("3F", 6.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
        Node(13, 10.0, 10.0, 3.0),
        Node(14, 0.0, 10.0, 3.0),
        Node(21, 0.0, 0.0, 6.0),
        Node(22, 8.0, 0.0, 6.0),
        Node(23, 8.0, 8.0, 6.0),
        Node(24, 0.0, 8.0, 6.0),
    ]
    elements = [
        Element(1, "SLAB", node_ids=(1, 2, 3, 4)),
        Element(2, "SLAB", node_ids=(11, 12, 13, 14)),
        Element(3, "SLAB", node_ids=(21, 22, 23, 24)),
    ]
    return stories, nodes, elements


def _square():
    return ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))


def _candidate(story_name, can_apply):
    from app.core.typical_floor_detector import ContinuousApplyCandidate

    return ContinuousApplyCandidate("1F", story_name, can_apply, 1.0 if can_apply else 0.2, 1.0 if can_apply else 0.0, 1.0 if can_apply else 0.0, "OK")
