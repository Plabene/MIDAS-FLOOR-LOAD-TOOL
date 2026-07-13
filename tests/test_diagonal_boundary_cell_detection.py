from app.core.closed_region_detector import (
    INTERSECTION_VERTEX_WITHOUT_MODEL_NODE,
    detect_closed_cells,
)
from app.core.mgt_parser import Element, Node, Story


def test_diagonal_beam_diamond_detects_closed_cell():
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

    cells = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_name="1F",
        story_tolerance=0.01,
        xy_tolerance=0.01,
    )

    assert len(cells) == 1
    assert set(cells[0].node_ids) == {1, 2, 3, 4}
    assert set(cells[0].boundary_element_ids) == {1, 2, 3, 4}


def test_mixed_diagonal_and_horizontal_beams_detect_trapezoid_cell():
    stories = [Story("1F", 0.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 8.0, 5.0, 0.0),
        Node(4, 2.0, 5.0, 0.0),
    ]
    elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "BEAM", node_ids=(2, 3)),
        Element(3, "BEAM", node_ids=(3, 4)),
        Element(4, "BEAM", node_ids=(4, 1)),
    ]

    cells = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_name="1F",
        story_tolerance=0.01,
        xy_tolerance=0.01,
    )

    assert len(cells) == 1
    assert set(cells[0].node_ids) == {1, 2, 3, 4}
    assert cells[0].area > 0.0


def test_diagonal_crossing_without_model_node_is_reported_and_not_used():
    stories = [Story("1F", 0.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
    ]
    elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "BEAM", node_ids=(2, 3)),
        Element(3, "BEAM", node_ids=(3, 4)),
        Element(4, "BEAM", node_ids=(4, 1)),
        Element(5, "BEAM", node_ids=(1, 3)),
        Element(6, "BEAM", node_ids=(2, 4)),
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

    assert cells == ()
    assert diagnostics
    assert diagnostics[0]["intersection_vertex_without_node_count"] > 0
    assert INTERSECTION_VERTEX_WITHOUT_MODEL_NODE in diagnostics[0]["dropped_reason"]
