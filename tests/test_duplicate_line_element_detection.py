from app.core.mgt_parser import Element, Node, Story
from app.core.model_floorload_diagnostics import analyze_floorload_model


def test_same_node_pair_duplicate_element_is_still_reported():
    story = Story("5F", 20.5)
    nodes = [
        Node(1919, 9.47, 6.0, 20.5),
        Node(4804, 9.70, 6.0, 20.5),
    ]
    elements = [
        Element(6188, "BEAM", mat=11, prop=10, node_ids=(1919, 4804)),
        Element(7000, "BEAM", mat=11, prop=10, node_ids=(4804, 1919)),
    ]

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story])

    issue = _first_issue(result, "DUPLICATE_ELEMENT")
    assert issue.severity == "WARNING"
    assert issue.element_ids == [6188, 7000]


def test_same_endpoint_coordinates_with_different_node_ids_are_reported():
    story = Story("5F", 20.5)
    nodes = [
        Node(1919, 9.47, 6.0, 20.5),
        Node(4804, 9.70, 6.0, 20.5),
        Node(9001, 9.47, 6.0, 20.5),
        Node(9002, 9.70, 6.0, 20.5),
    ]
    elements = [
        Element(6188, "BEAM", mat=11, prop=10, node_ids=(1919, 4804)),
        Element(7001, "BEAM", mat=11, prop=10, node_ids=(9001, 9002)),
    ]

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story])

    issue = _first_issue(result, "EXACT_COORD_DUPLICATE_ELEMENT")
    assert issue.severity == "WARNING"
    assert issue.node_ids == [1919, 4804, 9001, 9002]
    assert issue.element_ids == [6188, 7001]


def test_split_overlap_duplicate_element_is_reported_for_5f_fixture():
    story = Story("5F", 20.5)
    nodes = [
        Node(1919, 9.47, 6.0, 20.5),
        Node(4804, 9.70, 6.0, 20.5),
        Node(3328, 9.85, 6.0, 20.5),
        Node(5775, 9.815, 6.0, 20.5),
    ]
    elements = [
        Element(6188, "BEAM", mat=11, prop=10, node_ids=(1919, 4804)),
        Element(6189, "BEAM", mat=11, prop=10, node_ids=(4804, 3328)),
        Element(6324, "BEAM", mat=11, prop=10, node_ids=(1919, 5775)),
    ]

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story])

    split_issue = _first_issue(result, "SPLIT_OVERLAP_DUPLICATE_ELEMENT")
    assert split_issue.story_name == "5F"
    assert split_issue.severity == "WARNING"
    assert split_issue.element_ids == [6324, 6188, 6189]
    assert split_issue.node_ids == [1919, 3328, 4804, 5775]
    assert any(issue.issue_type == "OVERLAPPING_LINE_ELEMENT" for issue in result.issues)


def test_endpoint_touching_continuous_beams_are_not_overlapping_duplicates():
    story = Story("5F", 20.5)
    nodes = [
        Node(1, 0.0, 0.0, 20.5),
        Node(2, 1.0, 0.0, 20.5),
        Node(3, 2.0, 0.0, 20.5),
    ]
    elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "BEAM", node_ids=(2, 3)),
    ]

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=[story])

    assert all(issue.issue_type != "OVERLAPPING_LINE_ELEMENT" for issue in result.issues)
    assert all(issue.issue_type != "SPLIT_OVERLAP_DUPLICATE_ELEMENT" for issue in result.issues)


def test_same_xy_members_on_different_stories_are_not_duplicate_line_elements():
    stories = [Story("5F", 20.5), Story("6F", 23.5)]
    nodes = [
        Node(1, 0.0, 0.0, 20.5),
        Node(2, 1.0, 0.0, 20.5),
        Node(101, 0.0, 0.0, 23.5),
        Node(102, 1.0, 0.0, 23.5),
    ]
    elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "BEAM", node_ids=(101, 102)),
    ]

    result = analyze_floorload_model(nodes=nodes, elements=elements, stories=stories)

    duplicate_issue_types = {
        "EXACT_COORD_DUPLICATE_ELEMENT",
        "OVERLAPPING_LINE_ELEMENT",
        "SPLIT_OVERLAP_DUPLICATE_ELEMENT",
    }
    assert all(issue.issue_type not in duplicate_issue_types for issue in result.issues)


def _first_issue(result, issue_type: str):
    return next(issue for issue in result.issues if issue.issue_type == issue_type)
