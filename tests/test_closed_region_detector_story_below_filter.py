from app.core.closed_region_detector import detect_closed_cells
from app.core.mgt_parser import Element, Node, Story


def test_detect_closed_cells_uses_below_walls_not_above_duplicate_edges():
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
        Node(22, 10.0, 0.0, 6.0),
        Node(23, 10.0, 10.0, 6.0),
        Node(24, 0.0, 10.0, 6.0),
    ]
    elements = [
        Element(200, "SLAB", node_ids=(11, 12, 13, 14)),
        Element(101, "PLATE", node_ids=(11, 12, 22, 21)),
        Element(102, "PLATE", node_ids=(12, 13, 23, 22)),
        Element(103, "PLATE", node_ids=(13, 14, 24, 23)),
        Element(104, "PLATE", node_ids=(14, 11, 21, 24)),
        Element(1, "PLATE", node_ids=(1, 2, 12, 11)),
        Element(2, "PLATE", node_ids=(2, 3, 13, 12)),
        Element(3, "PLATE", node_ids=(3, 4, 14, 13)),
        Element(4, "PLATE", node_ids=(4, 1, 11, 14)),
    ]

    cells = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_name="2F",
        story_tolerance=0.01,
        xy_tolerance=0.01,
    )

    assert len(cells) == 1
    assert set(cells[0].boundary_element_ids) == {1, 2, 3, 4}
    assert set(cells[0].boundary_element_ids).isdisjoint({101, 102, 103, 104})
    assert 200 not in cells[0].boundary_element_ids


def test_detect_closed_cells_does_not_use_horizontal_slab_outline_as_boundary():
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    nodes = [
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
        Node(13, 10.0, 10.0, 3.0),
        Node(14, 0.0, 10.0, 3.0),
    ]
    elements = [
        Element(200, "SLAB", node_ids=(11, 12, 13, 14)),
    ]

    cells = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_name="2F",
        story_tolerance=0.01,
        xy_tolerance=0.01,
    )

    assert cells == ()
