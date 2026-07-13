from types import SimpleNamespace

from app.core.mgt_parser import Element, Node, Story
from app.main import (
    HATCH_VIEW_STRUCTURE_EXCLUDED_TYPES,
    HATCH_VIEW_STRUCTURE_WALL_TYPES,
    FloorLoadAutoApp,
)


def test_planar_wall_types_are_wall_candidates_not_excluded():
    planar_types = {"PLATE", "SHELL", "PLANE", "PLANAR", "QUAD"}

    assert planar_types.issubset(HATCH_VIEW_STRUCTURE_WALL_TYPES)
    assert not planar_types.intersection(HATCH_VIEW_STRUCTURE_EXCLUDED_TYPES)


def test_vertical_planar_element_displays_story_wall_edge_and_horizontal_slab_is_skipped():
    app = _app_with_planar_wall_model()

    items = app._structure_preview_items_for_story("2F")
    by_id = {item["element_id"]: item for item in items}

    assert 1 in by_id
    assert by_id[1]["kind"] == "WALL"
    assert set(by_id[1]["points"]) == {(0.0, 0.0), (10.0, 0.0)}
    assert by_id[1]["width"] == 0.2
    assert 2 not in by_id


def test_planar_wall_without_section_uses_visual_fallback_thickness():
    app = _app_with_planar_wall_model(include_fallback_wall=True)

    items = app._structure_preview_items_for_story("2F")
    fallback = next(item for item in items if item["element_id"] == 3)

    assert fallback["kind"] == "WALL"
    assert fallback["width"] == 0.2
    assert fallback["fallback_thickness"] is True


def test_wall_items_draw_dashed_offset_outline():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _Canvas()

    app._draw_hatch_structure_items(
        canvas,
        [{"kind": "WALL", "points": [(0.0, 0.0), (10.0, 0.0)], "width": 0.2}],
        lambda x, y: (x * 100.0, y * 100.0),
    )

    line_calls = [call for call in canvas.calls if call["kind"] == "line"]
    assert line_calls
    assert all(call["kwargs"].get("dash") == (5, 3) for call in line_calls)
    assert all(call["kwargs"].get("width") <= 2 for call in line_calls)


def _app_with_planar_wall_model(*, include_fallback_wall: bool = False):
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0), Story("2F", 3.0)]
    app.nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 0.0, 3.0),
        Node(4, 0.0, 0.0, 3.0),
        Node(11, 0.0, 20.0, 3.0),
        Node(12, 10.0, 20.0, 3.0),
        Node(13, 10.0, 30.0, 3.0),
        Node(14, 0.0, 30.0, 3.0),
        Node(21, 20.0, 0.0, 0.0),
        Node(22, 30.0, 0.0, 0.0),
        Node(23, 30.0, 0.0, 3.0),
        Node(24, 20.0, 0.0, 3.0),
    ]
    app.elements = [
        Element(1, "PLATE", prop=1, node_ids=(1, 2, 3, 4)),
        Element(2, "SHELL", prop=1, node_ids=(11, 12, 13, 14)),
    ]
    if include_fallback_wall:
        app.elements.append(Element(3, "PLANAR", prop=99, node_ids=(21, 22, 23, 24)))
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n*SECTION\n1, DBUSER, W200\n"
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    return app


class _Canvas:
    def __init__(self):
        self.calls = []

    def create_line(self, *args, **kwargs):
        self.calls.append({"kind": "line", "args": args, "kwargs": kwargs})

    def create_rectangle(self, *args, **kwargs):
        self.calls.append({"kind": "rectangle", "args": args, "kwargs": kwargs})

    def create_oval(self, *args, **kwargs):
        self.calls.append({"kind": "oval", "args": args, "kwargs": kwargs})
