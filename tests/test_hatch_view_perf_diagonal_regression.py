from types import SimpleNamespace

import pytest

import app.main as main_module
from app.core.dxf_load_reader import _entity_elevation_z, _transform_entity_ocs_points
from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp


def test_non_square_canvas_uniform_transform_preserves_diagonal_angle():
    app = object.__new__(FloorLoadAutoApp)

    transform, width, height = app._hatch_canvas_transform((0.0, 0.0, 10.0, 10.0), 400, 200)
    start = transform(0.0, 0.0)
    end = transform(10.0, 10.0)

    assert (width, height) == (400.0, 200.0)
    assert abs(end[0] - start[0]) == pytest.approx(abs(end[1] - start[1]))
    assert start[0] == pytest.approx(100.0)
    assert end[0] == pytest.approx(300.0)


def test_hatch_canvas_to_world_roundtrip_with_letterbox_offsets():
    app = object.__new__(FloorLoadAutoApp)
    bbox = (-5.0, 2.0, 15.0, 12.0)
    transform, _width, _height = app._hatch_canvas_transform(bbox, 300, 300)

    for world in ((-5.0, 2.0), (3.25, 9.75), (15.0, 12.0)):
        canvas = transform(*world)
        restored = app._hatch_canvas_to_world(*canvas, bbox, 300, 300)
        assert restored == pytest.approx(world, abs=1.0e-9)


def test_fallback_wall_thickness_parses_unit_once_per_mgt_text(monkeypatch):
    app = object.__new__(FloorLoadAutoApp)
    app.current_mgt_text = "*UNIT\nKN, MM, KJ, C\n"
    calls = []

    def fake_parse(text):
        calls.append(text)
        return SimpleNamespace(length="MM")

    monkeypatch.setattr(main_module, "parse_unit_from_text", fake_parse)

    assert app._fallback_wall_display_thickness() == 200.0
    assert app._fallback_wall_display_thickness() == 200.0
    assert calls == [app.current_mgt_text]


def test_duplicate_structure_status_does_not_repeat_stringvar_set():
    app = object.__new__(FloorLoadAutoApp)
    info_var = _CountingVar()
    app.hatch_preview_info_var = info_var

    app._set_hatch_structure_preview_status("same status")
    app._set_hatch_structure_preview_status("same status")

    assert info_var.values == ["same status"]


def test_structure_preview_story_cache_reuses_items_and_returns_copies():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0)]
    app.elements = [Element(1, "BEAM", prop=1, node_ids=(1, 2))]
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n*SECTION\n1, DBUSER, B300x600\n"
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    calls = []
    original = app._hatch_structure_item

    def counted_item(*args, **kwargs):
        calls.append(True)
        return original(*args, **kwargs)

    app._hatch_structure_item = counted_item
    first = app._structure_preview_items_for_story("1F")
    second = app._structure_preview_items_for_story("1F")
    first[0]["points"] = [(99.0, 99.0)]
    third = app._structure_preview_items_for_story("1F")

    assert len(calls) == 1
    assert second[0] is not third[0]
    assert third[0]["points"] == [(0.0, 0.0), (10.0, 0.0)]


def test_diagonal_planar_wall_preserves_three_node_story_edge_order():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("0F", 0.0), Story("1F", 3.0)]
    nodes = [
        Node(1, 0.0, 0.0, 3.0),
        Node(2, 1.0, 1.0, 3.0),
        Node(3, 2.0, 2.0, 3.0),
        Node(4, 2.0, 2.0, 0.0),
        Node(5, 0.0, 0.0, 0.0),
    ]
    node_by_id = {node.node_id: node for node in nodes}
    element = Element(10, "PLATE", node_ids=(1, 2, 3, 4, 5))

    points = app._planar_wall_edge_points_for_story(element, node_by_id, 3.0, 0.01)

    assert points == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0)]


def test_fake_ocs_entity_points_are_transformed_to_wcs_xy():
    class FakeOcs:
        def to_wcs(self, point):
            x, y, z = point
            return SimpleNamespace(x=x + z, y=y - z, z=z)

    entity = SimpleNamespace(
        dxf=SimpleNamespace(elevation=(0.0, 0.0, 5.0)),
        ocs=lambda: FakeOcs(),
    )

    assert _entity_elevation_z(entity) == 5.0
    assert _transform_entity_ocs_points(entity, [(1.0, 2.0), (3.0, 4.0)]) == [
        (6.0, -3.0),
        (8.0, -1.0),
    ]


def test_wheel_events_are_coalesced_into_one_scheduled_render():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _ScheduledCanvas()
    app.hatch_preview_canvas = canvas
    app.hatch_view_fit_bbox = (0.0, 0.0, 100.0, 50.0)
    app.hatch_view_view_bbox = app.hatch_view_fit_bbox
    app.hatch_view_manual_zoom = False
    renders = []
    app._render_hatch_preview = lambda **kwargs: renders.append(kwargs)

    event = SimpleNamespace(delta=120, x=100, y=50)
    app._on_hatch_view_mousewheel(event)
    app._on_hatch_view_mousewheel(event)

    assert len(canvas.callbacks) == 1
    assert renders == []
    canvas.callbacks[0]()
    assert renders == [{}]


class _ScheduledCanvas:
    def __init__(self):
        self.callbacks = []

    def winfo_width(self):
        return 200

    def winfo_height(self):
        return 100

    def after(self, _delay, callback):
        self.callbacks.append(callback)
        return f"after-{len(self.callbacks)}"

    def after_cancel(self, _after_id):
        return None


class _CountingVar:
    def __init__(self):
        self.values = []

    def set(self, value):
        self.values.append(value)
