from app.core.mgt_parser import Element, Node, Story
from app.core.model_floorload_diagnostics import analyze_floorload_model


def test_floorload_diagnostics_detects_duplicate_nodes_and_elements():
    story = Story("1F", 0.0)
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 0.001, 0.0, 0.0),
        Node(3, 5.0, 0.0, 0.0),
    ]
    elements = [
        Element(1, "BEAM", node_ids=(1, 3)),
        Element(2, "BEAM", node_ids=(3, 1)),
    ]

    issues = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story], story_tolerance=0.01, snap_tolerance=0.01)
    issue_types = {issue.issue_type for issue in issues}

    assert "NEAR_DUPLICATE_NODE" in issue_types
    assert "DUPLICATE_ELEMENT" in issue_types


def test_floorload_diagnostics_detects_node_on_unsplit_member():
    story = Story("1F", 0.0)
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 5.0, 0.0, 0.0),
    ]
    elements = [Element(1, "BEAM", node_ids=(1, 2))]

    issues = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story], story_tolerance=0.01, snap_tolerance=0.01)

    assert any(issue.issue_type == "UNSPLIT_MEMBER" and issue.node_ids[0] == 3 for issue in issues)
