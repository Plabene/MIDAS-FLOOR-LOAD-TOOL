from app.core.closed_region_detector import ExtraBoundarySegment, detect_closed_cells
from app.core.mgt_parser import Element, Node, Story


def _model():
    nodes = [Node(1, 0, 0, 0), Node(2, 10, 0, 0), Node(3, 10, 10, 0), Node(4, 0, 10, 0)]
    elements = [
        Element(1, "BEAM", 1, 1, (1, 2)),
        Element(2, "BEAM", 1, 1, (2, 3)),
        Element(3, "BEAM", 1, 1, (3, 4)),
    ]
    return [Story("1F", 0)], nodes, elements


def test_preview_omitted_approved_added_cancelled_and_commit_deduped():
    stories, nodes, elements = _model()
    assert detect_closed_cells(stories=stories, nodes=nodes, elements=elements) == ()

    approved = ExtraBoundarySegment("1F", 4, 1, (0, 10), (0, 0), issue_key="I1")
    cells = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=elements,
        extra_boundary_segments_by_story={"1F": (approved,)},
    )
    assert len(cells) == 1

    assert detect_closed_cells(stories=stories, nodes=nodes, elements=elements, extra_boundary_segments_by_story={}) == ()
    committed = [*elements, Element(4, "BEAM", 9999, 9999, (4, 1))]
    deduped = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=committed,
        extra_boundary_segments_by_story={"1F": (approved,)},
    )
    assert len(deduped) == 1
