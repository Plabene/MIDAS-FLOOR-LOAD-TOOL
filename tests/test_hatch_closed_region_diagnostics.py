import json

from app.core.closed_region_detector import (
    INCLINED_PLANE_DETECTED,
    WALL_EDGE_LONGEST_PAIR_FALLBACK,
    detect_closed_cells,
    write_closed_region_diagnostics,
)
from app.core.dxf_template_writer import _story_centerline_primitives
from app.core.mgt_parser import Element, Node, Story
from app.core.story_view_filter import story_below_range


def test_closed_region_diagnostics_records_diagonal_segments_and_writes_reports(tmp_path):
    stories = [Story("1F", 0.0)]
    nodes = [
        Node(1, 0.0, 5.0, 0.0),
        Node(2, 5.0, 10.0, 0.0),
        Node(3, 10.0, 5.0, 0.0),
        Node(4, 5.0, 0.0, 0.0),
    ]
    elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "BEAM", node_ids=(2, 3)),
        Element(3, "BEAM", node_ids=(3, 4)),
        Element(4, "BEAM", node_ids=(4, 1)),
    ]
    diagnostics = []

    cells = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_name="1F",
        story_tolerance=0.01,
        xy_tolerance=0.01,
        diagnostics=diagnostics,
    )
    json_path, csv_path = write_closed_region_diagnostics(diagnostics, tmp_path)

    assert len(cells) == 1
    assert diagnostics[0]["diagonal_segment_count"] == 4
    assert diagnostics[0]["usable_polygon_count"] == 1
    assert json_path.name == "hatch_closed_region_diagnostics.json"
    assert csv_path.name == "hatch_closed_region_diagnostics.csv"
    assert json.loads(json_path.read_text(encoding="utf-8"))[0]["story_name"] == "1F"
    assert "diagonal_segment_count" in csv_path.read_text(encoding="utf-8-sig")


def test_inclined_plane_is_reported_but_not_used_as_floorload_cell():
    stories = [Story("2F", 4.0)]
    nodes = [
        Node(1, 0.0, 0.0, 4.0),
        Node(2, 10.0, 0.0, 4.0),
        Node(3, 0.0, 10.0, 4.0),
        Node(4, 10.0, 10.0, 3.0),
        Node(5, 0.0, 10.0, 3.0),
    ]
    elements = [
        Element(10, "PLATE", node_ids=(1, 2, 4, 5)),
    ]
    diagnostics = []

    cells = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_name="2F",
        story_tolerance=0.01,
        xy_tolerance=0.01,
        diagnostics=diagnostics,
    )

    assert cells == ()
    assert diagnostics
    assert INCLINED_PLANE_DETECTED in diagnostics[0]["dropped_reason"]


def test_bent_wall_story_edge_preserves_node_sequence_without_longest_pair_fallback():
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    story = stories[1]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 0.0, 0.0, 3.0),
        Node(4, 5.0, 5.0, 3.0),
        Node(5, 10.0, 0.0, 3.0),
    ]
    elements = [
        Element(10, "PLATE", node_ids=(1, 3, 4, 5, 2)),
    ]
    node_by_id = {node.node_id: node for node in nodes}

    primitives, _points, element_count, warnings = _story_centerline_primitives(
        story,
        node_by_id,
        elements,
        0.01,
        story_range=story_below_range(stories, story, 0.01),
    )

    wall_lines = [item[2] for item in primitives if item[0] == "line" and item[1] == "CENTERLINE_WALL"]
    assert wall_lines == [
        ((0.0, 0.0), (5.0, 5.0)),
        ((5.0, 5.0), (10.0, 0.0)),
    ]
    assert element_count == 1
    assert warnings == 0


def test_discontinuous_wall_story_edge_records_longest_pair_fallback():
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    story = stories[1]
    nodes = [
        Node(1, 0.0, 0.0, 3.0),
        Node(2, 0.0, 0.0, 0.0),
        Node(3, 0.0, 5.0, 3.0),
        Node(4, 0.0, 5.0, 0.0),
        Node(5, 0.0, 10.0, 3.0),
    ]
    elements = [
        Element(10, "PLATE", node_ids=(1, 2, 3, 4, 5)),
    ]
    node_by_id = {node.node_id: node for node in nodes}
    diagnostics = []

    cells = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_name="2F",
        story_tolerance=0.01,
        xy_tolerance=0.01,
        diagnostics=diagnostics,
    )
    primitives, _points, element_count, warnings = _story_centerline_primitives(
        story,
        node_by_id,
        elements,
        0.01,
        story_range=story_below_range(stories, story, 0.01),
    )

    wall_lines = [item[2] for item in primitives if item[0] == "line" and item[1] == "CENTERLINE_WALL"]
    assert cells == ()
    assert WALL_EDGE_LONGEST_PAIR_FALLBACK in diagnostics[0]["dropped_reason"]
    assert wall_lines == [((0.0, 0.0), (0.0, 10.0))]
    assert element_count == 1
    assert warnings == 1
