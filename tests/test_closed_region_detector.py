import pytest

from app.core.closed_region_detector import detect_closed_cells
from app.core.mgt_parser import Element, Node, Story
from shapely.geometry import Polygon


def test_detect_closed_cells_from_story_beam_edges_and_ignores_load_dm_diagonal():
    stories = [Story("1F", 0.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
        Node(5, 0.0, 0.0, 3.0),
    ]
    elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "BEAM", node_ids=(2, 3)),
        Element(3, "BEAM", node_ids=(3, 4)),
        Element(4, "BEAM", node_ids=(4, 1)),
        Element(5, "LOAD DM", node_ids=(1, 3)),
        Element(6, "COLUMN", node_ids=(1, 5)),
        Element(7, "ELASTIC LINK", node_ids=(2, 4)),
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
    assert cells[0].story_name == "1F"
    assert set(cells[0].node_ids) == {1, 2, 3, 4}
    assert cells[0].boundary_element_ids == (1, 2, 3, 4)
    assert cells[0].area == 100.0


def test_closed_cell_preserves_original_endpoints_even_with_large_weld_tolerance():
    stories = [Story("1F", 0.0)]
    coordinates = [(0.123, 0.217), (3.987, 1.653), (3.211, 4.789), (-0.653, 3.353)]
    nodes = [Node(index, x, y, 0.0) for index, (x, y) in enumerate(coordinates, start=1)]
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
        xy_tolerance=0.5,
    )

    assert len(cells) == 1
    assert set(cells[0].polygon_xy) == set(coordinates)
    assert cells[0].area == pytest.approx(Polygon(coordinates).area, abs=1.0e-12)
    assert any(not (x * 2.0).is_integer() or not (y * 2.0).is_integer() for x, y in cells[0].polygon_xy)


def test_close_duplicate_endpoint_welds_to_existing_source_coordinate_without_grid_rounding():
    stories = [Story("1F", 0.0)]
    nodes = [
        Node(1, 0.123, 0.217, 0.0),
        Node(2, 4.0, 0.0, 0.0),
        Node(3, 4.0, 4.0, 0.0),
        Node(4, 0.0, 4.0, 0.0),
        Node(5, 0.1234, 0.2173, 0.0),
    ]
    elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "BEAM", node_ids=(2, 3)),
        Element(3, "BEAM", node_ids=(3, 4)),
        Element(4, "BEAM", node_ids=(4, 5)),
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
    assert (0.123, 0.217) in cells[0].polygon_xy
    assert (0.1234, 0.2173) not in cells[0].polygon_xy
    assert (0.123, 0.217) != (round(0.123 / 0.01) * 0.01, round(0.217 / 0.01) * 0.01)
