from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.hatch_region_editor import EditableHatchRegion, select_regions_by_rect
from app.main import FloorLoadAutoApp


def test_window_requires_full_polygon_coverage_and_accepts_box_boundary():
    inside = _editable("inside", ((0, 0), (5, 0), (5, 5), (0, 5)))
    partial = _editable("partial", ((4, 0), (7, 0), (7, 5), (4, 5)))

    selected = select_regions_by_rect(
        (inside, partial),
        (0, 0, 5, 5),
        selection_rule="window",
    )

    assert selected == {"inside"}


def test_crossing_includes_partial_overlap_and_boundary_touch():
    partial = _editable("partial", ((4, 0), (7, 0), (7, 5), (4, 5)))
    touching = _editable("touching", ((5, 6), (7, 6), (7, 8), (5, 8)))

    selected = select_regions_by_rect(
        (partial, touching),
        (0, 0, 5, 6),
        selection_rule="crossing",
    )

    assert selected == {"partial", "touching"}


def test_crossing_uses_real_triangle_not_only_overlapping_bounding_boxes():
    triangle = _editable("triangle", ((0, 0), (10, 0), (0, 10)))

    selected = select_regions_by_rect(
        (triangle,),
        (8, 8, 9, 9),
        selection_rule="crossing",
    )

    assert selected == set()


def test_core_ctrl_add_and_replace_modes_remain_supported():
    region = _editable("new", ((0, 0), (2, 0), (2, 2), (0, 2)))

    added = select_regions_by_rect(
        (region,),
        (-1, -1, 3, 3),
        selection_rule="window",
        mode="add",
        current={"old"},
    )
    replaced = select_regions_by_rect(
        (region,),
        (-1, -1, 3, 3),
        selection_rule="window",
        mode="replace",
        current={"old"},
    )

    assert added == {"old", "new"}
    assert replaced == {"new"}


def test_release_uses_left_to_right_window_and_right_to_left_crossing_for_both_sources():
    app = _drag_app()
    app.hatch_view_drag_start = (0.0, 0.0)
    app.hatch_view_drag_item = 99
    app.hatch_view_drag_moved = True

    app._on_hatch_view_button_release(SimpleNamespace(x=10, y=10, state=0))

    assert app.hatch_view_selected_edit_region_keys == {"E_INSIDE"}
    assert app.hatch_view_selected_region_keys == set()

    app.hatch_view_drag_start = (10.0, 0.0)
    app.hatch_view_drag_item = 100
    app.hatch_view_drag_moved = True
    app._on_hatch_view_button_release(SimpleNamespace(x=0, y=10, state=0))

    assert app.hatch_view_selected_edit_region_keys == {"E_INSIDE"}
    assert app.hatch_view_selected_region_keys == {"D_PARTIAL"}
    assert app.visual_updates == 2
    assert app.refresh_delays == [120, 120]


def test_release_ctrl_add_preserves_existing_internal_and_dxf_selection():
    app = _drag_app()
    app.hatch_view_selected_edit_region_keys = {"E_OLD"}
    app.hatch_view_selected_region_keys = {"D_OLD"}
    app.hatch_view_drag_start = (10.0, 10.0)
    app.hatch_view_drag_item = 99
    app.hatch_view_drag_moved = True

    app._on_hatch_view_button_release(SimpleNamespace(x=0, y=0, state=0x0004))

    assert app.hatch_view_selected_edit_region_keys == {"E_OLD", "E_INSIDE"}
    assert app.hatch_view_selected_region_keys == {"D_OLD", "D_PARTIAL"}


def test_drag_box_style_distinguishes_window_and_crossing():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _Canvas()
    app.hatch_preview_canvas = canvas
    app.hatch_view_drag_start = (5.0, 5.0)
    app.hatch_view_drag_item = 7
    app.hatch_view_drag_moved = False

    app._on_hatch_view_drag(SimpleNamespace(x=10, y=8))
    app._on_hatch_view_drag(SimpleNamespace(x=0, y=2))

    assert canvas.configs[0] == {"outline": "#1a73e8", "dash": ()}
    assert canvas.configs[1] == {"outline": "#16a34a", "dash": (4, 3)}


def test_dxf_drag_candidates_prefer_placed_vertices_in_all_story_view():
    app = object.__new__(FloorLoadAutoApp)
    hatch = SimpleNamespace(
        source_id="DXF-A",
        handle="DXF-A",
        story_name="1F",
        layer="LOAD_A",
        vertices=((0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0)),
        placed_vertices=((20.0, 0.0), (22.0, 0.0), (22.0, 2.0), (20.0, 2.0)),
    )
    app.loaded_regions = [SimpleNamespace(region=hatch)]
    app._hatch_edit_regions_for_display_selection = lambda: ()
    app._hatch_view_is_all_story_display = lambda: True
    app._hatch_story_display_offsets = lambda _regions: {}
    app._hatch_view_story_filter = lambda: ""

    edit_candidates, dxf_candidates = app._hatch_drag_selection_candidates()

    assert edit_candidates == ()
    assert dxf_candidates == (
        (
            "1F|DXF-A",
            ((20.0, 0.0), (22.0, 0.0), (22.0, 2.0), (20.0, 2.0)),
        ),
    )


def test_dxf_drag_candidates_fall_back_to_polygon_when_vertices_are_missing():
    app = object.__new__(FloorLoadAutoApp)
    polygon = Polygon(((3.0, 4.0), (5.0, 4.0), (5.0, 6.0), (3.0, 6.0)))
    hatch = SimpleNamespace(
        source_id="DXF-POLYGON",
        handle="DXF-POLYGON",
        story_name="1F",
        layer="LOAD_A",
        vertices=(),
        placed_vertices=(),
        polygon=polygon,
    )
    app.loaded_regions = [SimpleNamespace(region=hatch)]
    app._hatch_edit_regions_for_display_selection = lambda: ()
    app._hatch_view_is_all_story_display = lambda: False
    app._hatch_view_story_filter = lambda: ""

    _edit_candidates, dxf_candidates = app._hatch_drag_selection_candidates()

    assert dxf_candidates == (
        ("1F|DXF-POLYGON", ((3.0, 4.0), (5.0, 4.0), (5.0, 6.0), (3.0, 6.0))),
    )


def _drag_app():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_preview_canvas = _Canvas()
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.visual_updates = 0
    app.refresh_delays = []
    app._one_way_handle_region_key_from_event = lambda _event: None
    app._canvas_point_to_hatch_world = lambda x, y: (float(x), float(y))
    app._hatch_drag_selection_candidates = lambda: (
        (("E_INSIDE", ((1, 1), (4, 1), (4, 4), (1, 4))),),
        (("D_PARTIAL", ((9, 1), (12, 1), (12, 4), (9, 4))),),
    )
    app._sync_continuous_base_story_from_selection = lambda: ""
    app._hatch_selection_snapshot = lambda: (frozenset(), frozenset())
    app._update_hatch_selection_visuals = lambda _previous=None: setattr(
        app, "visual_updates", app.visual_updates + 1
    ) or True
    app._schedule_selected_hatch_continuous_refresh = lambda delay: app.refresh_delays.append(delay)
    app._render_hatch_preview = lambda *args, **kwargs: None
    return app


def _editable(key: str, points) -> EditableHatchRegion:
    return EditableHatchRegion(
        region_key=key,
        story_name="1F",
        cell_ids=(key,),
        polygon_xy=tuple((float(x), float(y)) for x, y in points),
        load_name=None,
        load_layer=None,
        dl=None,
        ll=None,
        distribution="TWO_WAY",
    )


class _Canvas:
    def __init__(self):
        self.deleted = []
        self.configs = []

    def delete(self, item_id):
        self.deleted.append(item_id)

    def coords(self, *_args):
        return None

    def itemconfig(self, _item_id, **kwargs):
        self.configs.append(dict(kwargs))
