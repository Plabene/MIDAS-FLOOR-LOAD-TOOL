from app.core.dxf_template_writer import _story_centerline_primitives
from app.core.mgt_parser import Element, Node, Story
from app.core.story_view_filter import story_below_range


def test_story_centerline_primitives_use_midas_below_range():
    stories, nodes, elements = _below_filter_model()
    story = stories[1]
    node_by_id = {node.node_id: node for node in nodes}
    story_range = story_below_range(stories, story, 0.01)

    primitives, _points, element_count, warnings = _story_centerline_primitives(
        story,
        node_by_id,
        elements,
        0.01,
        story_range=story_range,
    )

    wall_lines = [item for item in primitives if item[0] == "line" and item[1] == "CENTERLINE_WALL"]
    beam_lines = [item for item in primitives if item[0] == "line" and item[1] == "CENTERLINE_BEAM"]
    reference_grids = [item for item in primitives if item[1] == "REFERENCE_GRID"]

    assert len(wall_lines) == 1
    assert set(wall_lines[0][2]) == {(0.0, 0.0), (10.0, 0.0)}
    assert len(beam_lines) == 2
    assert reference_grids == []
    assert element_count == 3
    assert warnings == 0


def _below_filter_model():
    stories = [Story("1F", 0.0), Story("2F", 3.0), Story("3F", 6.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 0.0, 0.0, 3.0),
        Node(4, 10.0, 0.0, 3.0),
        Node(5, 0.0, 0.0, 6.0),
        Node(6, 10.0, 0.0, 6.0),
        Node(11, 0.0, 10.0, 3.0),
        Node(12, 10.0, 10.0, 3.0),
        Node(13, 10.0, 20.0, 3.0),
        Node(14, 0.0, 20.0, 3.0),
    ]
    elements = [
        Element(1, "PLATE", node_ids=(1, 2, 4, 3)),
        Element(2, "PLATE", node_ids=(3, 4, 6, 5)),
        Element(3, "BEAM", node_ids=(3, 4)),
        Element(4, "BEAM", node_ids=(11, 12)),
        Element(5, "SLAB", node_ids=(3, 4, 13, 14)),
        Element(6, "SURFACE", node_ids=(3, 4, 13)),
    ]
    return stories, nodes, elements
