import pytest

from app.core.mgt_parser import Element, Node, Story
from app.core.typical_floor_detector import (
    TypicalFloorGroup,
    analyze_typical_floors,
    build_story_shape_profiles,
    compare_story_profiles,
    evaluate_continuous_apply_candidates,
)


def test_identical_floors_create_group_and_select_typical():
    stories, nodes, elements = _stacked_rectangles(
        [
            ("2F", 0.0, (0.0, 0.0, 10.0, 8.0)),
            ("3F", 3.0, (0.0, 0.0, 10.0, 8.0)),
            ("4F", 6.0, (0.0, 0.0, 10.0, 8.0)),
            ("5F", 9.0, (0.0, 0.0, 10.0, 8.0)),
        ]
    )

    result = analyze_typical_floors(stories=stories, nodes=nodes, elements=elements, story_tolerance=0.01, xy_tolerance=0.02)

    assert len(result.groups) == 1
    assert result.groups[0].story_names == ("2F", "3F", "4F", "5F")
    assert result.groups[0].typical_story_name in {"3F", "4F"}
    assert result.groups[0].typical_score >= 0.99


def test_transition_floor_splits_low_and_high_groups():
    stories, nodes, elements = _stacked_rectangles(
        [
            ("1F", 0.0, (0.0, 0.0, 12.0, 8.0)),
            ("2F", 3.0, (0.0, 0.0, 12.0, 8.0)),
            ("3F", 6.0, (0.0, 0.0, 12.0, 8.0)),
            ("4F", 9.0, (0.0, 0.0, 7.0, 5.0)),
            ("5F", 12.0, (0.0, 0.0, 9.0, 6.0)),
            ("6F", 15.0, (0.0, 0.0, 9.0, 6.0)),
            ("7F", 18.0, (0.0, 0.0, 9.0, 6.0)),
        ]
    )

    result = analyze_typical_floors(stories=stories, nodes=nodes, elements=elements, story_tolerance=0.01, xy_tolerance=0.02)
    typical_groups = [group for group in result.groups if group.typical_story_name]
    transition_groups = [group for group in result.groups if "4F" in group.transition_floor_names]

    assert [group.story_names for group in typical_groups] == [("1F", "2F", "3F"), ("5F", "6F", "7F")]
    assert transition_groups
    assert transition_groups[0].typical_story_name is None


def test_internal_node_difference_is_ignored_for_similarity():
    stories, nodes, elements = _stacked_rectangles(
        [
            ("1F", 0.0, (0.0, 0.0, 10.0, 10.0)),
            ("2F", 3.0, (0.0, 0.0, 10.0, 10.0)),
        ]
    )
    nodes.append(Node(999, 5.0, 5.0, 3.0))

    profiles = build_story_shape_profiles(stories=stories, nodes=nodes, elements=elements, story_tolerance=0.01, xy_tolerance=0.02)
    similarity = compare_story_profiles(profiles[0], profiles[1], xy_tolerance=0.02)

    assert similarity.score == pytest.approx(1.0)
    assert similarity.node_match_ratio == pytest.approx(1.0)


def test_outer_node_within_tolerance_is_similar():
    stories, nodes, elements = _stacked_rectangles(
        [
            ("1F", 0.0, (0.0, 0.0, 10.0, 10.0)),
            ("2F", 3.0, (0.003, -0.002, 10.003, 9.998)),
        ]
    )

    profiles = build_story_shape_profiles(stories=stories, nodes=nodes, elements=elements, story_tolerance=0.01, xy_tolerance=0.02)
    similarity = compare_story_profiles(profiles[0], profiles[1], xy_tolerance=0.02)

    assert similarity.score >= 0.99


def test_story_without_closed_region_is_excluded_from_typical():
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
    ]
    elements = [Element(1, "BEAM", node_ids=(1, 2)), Element(2, "BEAM", node_ids=(11, 12))]

    result = analyze_typical_floors(stories=stories, nodes=nodes, elements=elements, story_tolerance=0.01, xy_tolerance=0.02)

    assert all(not profile.valid for profile in result.profiles)
    assert all(group.typical_story_name is None for group in result.groups)


def test_diagnostic_penalty_pushes_story_out_of_typical_selection():
    stories, nodes, elements = _stacked_rectangles(
        [
            ("1F", 0.0, (0.0, 0.0, 10.0, 8.0)),
            ("2F", 3.0, (0.0, 0.0, 10.0, 8.0)),
            ("3F", 6.0, (0.0, 0.0, 10.0, 8.0)),
        ]
    )

    result = analyze_typical_floors(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_tolerance=0.01,
        xy_tolerance=0.02,
        story_penalties={"2F": 0.30},
    )

    assert result.groups[0].typical_story_name != "2F"


def test_load_dm_beam_material_or_section_is_excluded_from_profile():
    stories = [Story("1F", 0.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
    ]
    elements = [
        Element(1, "BEAM", mat=10, prop=20, node_ids=(1, 2)),
        Element(2, "BEAM", mat=10, prop=20, node_ids=(2, 3)),
        Element(3, "BEAM", mat=10, prop=20, node_ids=(3, 4)),
        Element(4, "BEAM", mat=10, prop=20, node_ids=(4, 1)),
    ]
    mgt_text = """
*MATERIAL
10, STEEL, LOAD DM MATERIAL
*SECTION
20, DBUSER, LOAD_DM_SECTION
"""

    profiles = build_story_shape_profiles(
        stories=stories,
        nodes=nodes,
        elements=elements,
        mgt_text=mgt_text,
        story_tolerance=0.01,
        xy_tolerance=0.02,
    )

    assert profiles[0].valid is False
    assert "NO_CLOSED_REGION" in profiles[0].warning_codes


def test_local_hatch_match_rejects_core_region_inside_oversized_target_cell():
    stories, nodes, elements = _stacked_rectangles(
        [
            ("1F", 0.0, (0.0, 0.0, 10.0, 10.0)),
            ("2F", 3.0, (0.0, 0.0, 20.0, 20.0)),
        ]
    )
    nodes.extend(
        [
            Node(100, 2.0, 2.0, 3.0),
            Node(101, 4.0, 2.0, 3.0),
            Node(102, 4.0, 4.0, 3.0),
            Node(103, 2.0, 4.0, 3.0),
        ]
    )
    profiles = build_story_shape_profiles(stories=stories, nodes=nodes, elements=elements, story_tolerance=0.01, xy_tolerance=0.005)
    groups = (
        TypicalFloorGroup("G001", ("1F",), "1F", 1.0, (), "OK"),
        TypicalFloorGroup("G002", ("2F",), "2F", 1.0, (), "OK"),
    )

    candidates = evaluate_continuous_apply_candidates(
        profiles,
        base_story_name="1F",
        target_story_names=["2F"],
        hatch_polygon_xy=[(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)],
        typical_groups=groups,
        xy_tolerance=0.005,
    )

    assert candidates[0].can_apply is False
    assert "AREA_RATIO_BELOW_THRESHOLD" in candidates[0].reason


def test_local_hatch_match_rejects_vertices_outside_continuous_tolerance():
    stories, nodes, elements = _stacked_rectangles(
        [
            ("1F", 0.0, (0.0, 0.0, 10.0, 10.0)),
            ("2F", 3.0, (0.0, 0.0, 20.0, 20.0)),
        ]
    )
    nodes.extend(
        [
            Node(100, 2.05, 2.05, 3.0),
            Node(101, 4.05, 2.05, 3.0),
            Node(102, 4.05, 4.05, 3.0),
            Node(103, 2.05, 4.05, 3.0),
        ]
    )
    profiles = build_story_shape_profiles(stories=stories, nodes=nodes, elements=elements, story_tolerance=0.01, xy_tolerance=0.005)
    groups = (
        TypicalFloorGroup("G001", ("1F",), "1F", 1.0, (), "OK"),
        TypicalFloorGroup("G002", ("2F",), "2F", 1.0, (), "OK"),
    )

    candidates = evaluate_continuous_apply_candidates(
        profiles,
        base_story_name="1F",
        target_story_names=["2F"],
        hatch_polygon_xy=[(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0)],
        typical_groups=groups,
        xy_tolerance=0.005,
    )

    assert candidates[0].can_apply is False
    assert "DIFFERENT_TYPICAL_GROUP" in candidates[0].reason


def _stacked_rectangles(specs):
    stories = [Story(name, elevation) for name, elevation, _bbox in specs]
    nodes = []
    elements = []
    node_id = 1
    elem_id = 1
    for _story_name, elevation, (min_x, min_y, max_x, max_y) in specs:
        ids = []
        for x, y in ((min_x, min_y), (max_x, min_y), (max_x, max_y), (min_x, max_y)):
            nodes.append(Node(node_id, x, y, elevation))
            ids.append(node_id)
            node_id += 1
        elements.append(Element(elem_id, "SLAB", node_ids=tuple(ids)))
        elem_id += 1
    return stories, nodes, elements
