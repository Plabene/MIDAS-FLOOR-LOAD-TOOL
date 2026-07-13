from types import SimpleNamespace

from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp


def test_hatch_view_structure_preview_uses_midas_below_story_range():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0), Story("2F", 3.0), Story("3F", 6.0)]
    app.nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 0.0, 0.0, 3.0),
        Node(4, 10.0, 0.0, 3.0),
        Node(5, 0.0, 0.0, 6.0),
        Node(6, 10.0, 0.0, 6.0),
        Node(7, 20.0, 0.0, 0.0),
        Node(8, 20.0, 0.0, 3.0),
        Node(9, 30.0, 0.0, -3.0),
        Node(10, 30.0, 0.0, 0.0),
        Node(11, 0.0, 10.0, 3.0),
        Node(12, 10.0, 10.0, 3.0),
        Node(13, 10.0, 20.0, 3.0),
        Node(14, 0.0, 20.0, 3.0),
    ]
    app.elements = [
        Element(1, "PLATE", node_ids=(1, 2, 4, 3)),
        Element(2, "PLATE", node_ids=(3, 4, 6, 5)),
        Element(3, "BEAM", node_ids=(3, 4)),
        Element(4, "BEAM", node_ids=(11, 12)),
        Element(5, "COLUMN", node_ids=(7, 8)),
        Element(6, "COLUMN", node_ids=(8, 6)),
        Element(7, "COLUMN", node_ids=(9, 10)),
        Element(8, "SLAB", node_ids=(3, 4, 13, 14)),
        Element(9, "SURFACE", node_ids=(3, 4, 13)),
    ]
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    app.current_mgt_text = ""

    items = app._structure_preview_items_for_story("2F")
    by_id = {item["element_id"]: item for item in items}

    assert set(by_id) == {1, 3, 4, 5}
    assert by_id[1]["kind"] == "WALL"
    assert by_id[3]["kind"] == "BEAM"
    assert by_id[5]["kind"] == "COLUMN"
    assert 8 not in by_id
    assert 9 not in by_id
