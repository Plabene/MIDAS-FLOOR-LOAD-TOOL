from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.closed_region_detector import ClosedCell
from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.hatch_region_editor import apply_load_to_selection, create_edit_state
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


def test_render_creates_one_way_handles_for_internal_and_dxf_regions_only():
    app = _render_app()
    one_way_dxf = _load_region("D1", _quad(0, 0, 10, 10), _load("DxfOne", distribution="ONE_WAY", angle=0.0))
    two_way_dxf = _load_region("D2", _quad(20, 0, 30, 10), _load("DxfTwo", distribution="TWO_WAY", angle=None))
    app.loaded_regions = [one_way_dxf, two_way_dxf]
    app.continuous_hatch_checks = {
        app._region_key(region, index=index): {"can_select": True}
        for index, region in enumerate(app.loaded_regions, start=1)
    }

    state = create_edit_state("1F", [_cell("E1", _quad(0, 20, 10, 30))])
    key = next(iter(state.regions_by_key))
    state.selected_region_keys = {key}
    state.selected_cell_ids = {"E1"}
    state = apply_load_to_selection(
        state,
        load_name="EditOne",
        load_layer="LOAD_EditOne",
        dl=1.0,
        ll=1.0,
        distribution="ONE_WAY",
        one_way_angle=90.0,
    )
    app.hatch_edit_states_by_story = {"1F": state}
    app.hatch_preview_canvas = _Canvas()

    app._render_hatch_preview()

    handle_lines = [(_args, kwargs) for _args, kwargs in app.hatch_preview_canvas.lines if "hatch_one_way_handle" in kwargs.get("tags", ())]
    handle_tags = [kwargs["tags"] for _args, kwargs in handle_lines]
    visual_lines = _one_way_arrow_lines(app.hatch_preview_canvas)
    hitbox_lines = _one_way_hitbox_lines(app.hatch_preview_canvas)
    assert len(handle_tags) == 4
    assert len(visual_lines) == 2
    assert len(hitbox_lines) == 2
    assert all(str(kwargs.get("arrow")) == "both" for _args, kwargs in visual_lines)
    assert all(kwargs.get("fill") == "" for _args, kwargs in hitbox_lines)
    assert any("one_way_source:dxf" in tags for tags in handle_tags)
    assert any("one_way_source:edit" in tags for tags in handle_tags)
    assert all("D2" not in "".join(tags) for tags in handle_tags)


def test_horizontal_one_way_handle_uses_top_or_bottom_band_and_avoids_checkbox():
    app = _render_app()
    vertices = _quad(0, 0, 120, 120)
    canvas = _Canvas()

    app._draw_one_way_direction_handles(canvas, "R1", vertices, 0.0, lambda x, y: (float(x), float(y)), source="dxf")

    assert len(canvas.lines) == 2
    visual_lines = _one_way_arrow_lines(canvas)
    hitbox_lines = _one_way_hitbox_lines(canvas)
    assert len(visual_lines) == 1
    assert len(hitbox_lines) == 1
    checkbox_half = app._hatch_checkbox_canvas_half_size(vertices, lambda x, y: (float(x), float(y)))
    checkbox_bbox = (60.0 - checkbox_half, 60.0 - checkbox_half, 60.0 + checkbox_half, 60.0 + checkbox_half)
    for args, kwargs in canvas.lines:
        x1, y1, x2, y2 = [float(value) for value in args[:4]]
        bbox = _line_bbox(args)
        assert not _bbox_intersects(checkbox_bbox, bbox)
        assert 0.0 <= min(x1, x2) <= 120.0
        assert 0.0 <= max(x1, x2) <= 120.0
        assert 0.0 <= min(y1, y2) <= 120.0
        assert 0.0 <= max(y1, y2) <= 120.0
    args, kwargs = visual_lines[0]
    x1, y1, x2, y2 = [float(value) for value in args[:4]]
    center_x, center_y = _line_center(args)
    assert abs(y1 - y2) < 1.0e-9
    assert checkbox_bbox[0] <= center_x <= checkbox_bbox[2]
    assert center_y < checkbox_bbox[1] or center_y > checkbox_bbox[3]
    assert str(kwargs.get("arrow")) == "both"
    assert int(kwargs.get("width")) >= 4


def test_vertical_one_way_handle_uses_left_or_right_band_and_avoids_checkbox():
    app = _render_app()
    vertices = _quad(0, 0, 120, 120)
    canvas = _Canvas()

    app._draw_one_way_direction_handles(canvas, "R1", vertices, 90.0, lambda x, y: (float(x), float(y)), source="dxf")

    visual_lines = _one_way_arrow_lines(canvas)
    hitbox_lines = _one_way_hitbox_lines(canvas)
    assert len(visual_lines) == 1
    assert len(hitbox_lines) == 1
    checkbox_half = app._hatch_checkbox_canvas_half_size(vertices, lambda x, y: (float(x), float(y)))
    checkbox_bbox = (60.0 - checkbox_half, 60.0 - checkbox_half, 60.0 + checkbox_half, 60.0 + checkbox_half)
    for args, _kwargs in canvas.lines:
        x1, y1, x2, y2 = [float(value) for value in args[:4]]
        assert not _bbox_intersects(checkbox_bbox, _line_bbox(args))
        assert 0.0 <= min(x1, x2) <= 120.0
        assert 0.0 <= max(x1, x2) <= 120.0
        assert 0.0 <= min(y1, y2) <= 120.0
        assert 0.0 <= max(y1, y2) <= 120.0
    args, kwargs = visual_lines[0]
    x1, y1, x2, y2 = [float(value) for value in args[:4]]
    center_x, center_y = _line_center(args)
    assert abs(x1 - x2) < 1.0e-9
    assert center_x < checkbox_bbox[0] or center_x > checkbox_bbox[2]
    assert checkbox_bbox[1] <= center_y <= checkbox_bbox[3]
    assert str(kwargs.get("arrow")) == "both"


def test_one_way_handle_visual_size_and_hitbox_are_scale_aware():
    app = _render_app()
    vertices = _quad(0, 0, 120, 120)
    canvas = _Canvas()

    app._draw_one_way_direction_handles(canvas, "R1", vertices, 0.0, lambda x, y: (float(x), float(y)), source="dxf")

    visual_lines = _one_way_arrow_lines(canvas)
    hitbox_lines = _one_way_hitbox_lines(canvas)
    assert len(visual_lines) == 1
    assert len(hitbox_lines) == 1
    visual_args, visual_kwargs = visual_lines[0]
    hitbox_args, hitbox_kwargs = hitbox_lines[0]
    big_length = _line_length(visual_args)
    big_width = int(visual_kwargs.get("width"))
    big_hitbox_width = int(hitbox_kwargs.get("width"))

    small_canvas = _Canvas()
    app._draw_one_way_direction_handles(small_canvas, "R1", vertices, 0.0, lambda x, y: (float(x) * 0.20, float(y) * 0.20), source="dxf")

    small_visual_lines = _one_way_arrow_lines(small_canvas)
    small_hitbox_lines = _one_way_hitbox_lines(small_canvas)
    assert len(small_visual_lines) == 1
    assert len(small_hitbox_lines) == 1
    small_args, small_kwargs = small_visual_lines[0]
    _small_hitbox_args, small_hitbox_kwargs = small_hitbox_lines[0]
    assert _line_length(small_args) < big_length
    assert int(small_kwargs.get("width")) < big_width
    assert int(small_hitbox_kwargs.get("width")) < big_hitbox_width


def test_too_small_one_way_handle_is_omitted_instead_of_overlapping_checkbox():
    app = _render_app()
    vertices = _quad(0, 0, 18, 18)
    canvas = _Canvas()

    app._draw_one_way_direction_handles(canvas, "R1", vertices, 0.0, lambda x, y: (float(x), float(y)), source="dxf")

    assert canvas.lines == []


def test_one_way_handle_layout_is_bidirectional_scale_aware_and_avoids_checkbox():
    app = _render_app()
    vertices = _quad(0, 0, 120, 120)
    canvas = _Canvas()

    app._draw_one_way_direction_handles(canvas, "R1", vertices, 0.0, lambda x, y: (float(x), float(y)), source="dxf")

    visual_lines = _one_way_arrow_lines(canvas)
    hitbox_lines = _one_way_hitbox_lines(canvas)
    assert len(visual_lines) == 1
    assert len(hitbox_lines) == 1
    checkbox_half = app._hatch_checkbox_canvas_half_size(vertices, lambda x, y: (float(x), float(y)))
    checkbox_bbox = (60.0 - checkbox_half, 60.0 - checkbox_half, 60.0 + checkbox_half, 60.0 + checkbox_half)
    lengths = []
    for args, kwargs in visual_lines:
        bbox = _line_bbox(args)
        assert not _bbox_intersects(checkbox_bbox, bbox)
        assert str(kwargs.get("arrow")) == "both"
        assert int(kwargs.get("width")) >= 4
        lengths.append(_line_length(args))
    for args, kwargs in hitbox_lines:
        assert not _bbox_intersects(checkbox_bbox, _line_bbox(args))
        assert kwargs.get("fill") == ""
        assert int(kwargs.get("width")) > int(visual_lines[0][1].get("width"))

    small_canvas = _Canvas()
    app._draw_one_way_direction_handles(small_canvas, "R1", vertices, 0.0, lambda x, y: (float(x) * 0.20, float(y) * 0.20), source="dxf")

    small_lengths = [_line_length(args) for args, _kwargs in _one_way_arrow_lines(small_canvas)]
    assert len(_one_way_arrow_lines(small_canvas)) <= len(visual_lines)
    if small_lengths:
        assert max(small_lengths) <= max(lengths)
        assert max(int(kwargs.get("width")) for _args, kwargs in _one_way_arrow_lines(small_canvas)) <= max(int(kwargs.get("width")) for _args, kwargs in visual_lines)


def test_one_way_handle_single_click_rotates_angle_and_records_undo():
    app = _angle_app()
    key = next(iter(app.hatch_view_region_by_key))
    app.after = lambda _delay, func: (func(), "after-id")[1]
    app.after_cancel = lambda _after_id: None

    assert app._on_one_way_handle_click(SimpleNamespace(region_key=key, source="dxf")) == "break"

    assert app.loaded_regions[0].load.one_way_angle_deg == 90.0
    assert len(app.hatch_edit_undo_stack) == 1
    assert "90도 회전" in app.hatch_preview_info_var.value


def test_one_way_handle_double_click_sets_angle_and_records_undo():
    app = _angle_app()
    key = next(iter(app.hatch_view_region_by_key))
    app._ask_one_way_angle = lambda _current: 30.0

    assert app._on_one_way_handle_double_click(SimpleNamespace(region_key=key, source="dxf")) == "break"

    assert app.loaded_regions[0].load.one_way_angle_deg == 30.0
    assert len(app.hatch_edit_undo_stack) == 1
    assert "30.0도" in app.hatch_preview_info_var.value


def test_one_way_handle_double_click_updates_selected_dxf_one_way_regions_with_single_undo():
    app = _angle_app()
    one_a = _load_region("D1", _quad(0, 0, 10, 10), _load("DxfOneA", distribution="ONE_WAY", angle=0.0))
    one_b = _load_region("D2", _quad(20, 0, 30, 10), _load("DxfOneB", distribution="ONE_WAY", angle=90.0))
    two_way = _load_region("D3", _quad(40, 0, 50, 10), _load("DxfTwo", distribution="TWO_WAY", angle=None))
    app.loaded_regions = [one_a, one_b, two_way]
    app.hatch_view_region_by_key = {app._region_key(region, index=index): region for index, region in enumerate(app.loaded_regions, start=1)}
    keys = tuple(app.hatch_view_region_by_key)
    app.hatch_view_selected_region_keys = set(keys)
    app.hatch_view_selected_region_key = keys[0]
    app._ask_one_way_angle = lambda _current: 30.0

    assert app._on_one_way_handle_double_click(SimpleNamespace(region_key=keys[0], source="dxf")) == "break"

    assert one_a.load.one_way_angle_deg == 30.0
    assert one_b.load.one_way_angle_deg == 30.0
    assert two_way.load.distribution == "TWO_WAY"
    assert two_way.load.one_way_angle_deg is None
    assert len(app.hatch_edit_undo_stack) == 1
    assert "2개의 재하 각도" in app.hatch_preview_info_var.value

    app.undo_hatch_view_edit()
    assert app._dxf_region_by_key(keys[0]).load.one_way_angle_deg == 0.0
    assert app._dxf_region_by_key(keys[1]).load.one_way_angle_deg == 90.0
    app.redo_hatch_view_edit()
    assert app._dxf_region_by_key(keys[0]).load.one_way_angle_deg == 30.0
    assert app._dxf_region_by_key(keys[1]).load.one_way_angle_deg == 30.0


def test_one_way_handle_double_click_updates_selected_internal_one_way_regions():
    app = _render_app()
    app.continuous_apply_targets_by_region = {}
    app.continuous_materialized_targets_by_region = {}
    app.continuous_active_visible_targets = ()
    app.continuous_active_region_key = None
    app.continuous_active_region_keys = ()
    app.continuous_base_story_name = _Var("1F")
    app.hatch_edit_undo_stack = []
    app.hatch_edit_redo_stack = []
    app._render_hatch_preview = lambda *args, **kwargs: None
    app._sync_load_to_continuous_targets_for_region_keys = lambda *args, **kwargs: None
    state = create_edit_state(
        "1F",
        [_cell("E1", _quad(0, 0, 10, 10)), _cell("E2", _quad(20, 0, 30, 10)), _cell("E3", _quad(40, 0, 50, 10))],
    )
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = {"E1", "E2", "E3"}
    state = apply_load_to_selection(
        state,
        load_name="EditOne",
        load_layer="LOAD_EditOne",
        dl=1.0,
        ll=1.0,
        distribution="ONE_WAY",
        one_way_angle=0.0,
    )
    app.hatch_edit_states_by_story = {"1F": state}
    app.hatch_view_edit_region_by_key = dict(state.regions_by_key)
    keys = tuple(state.regions_by_key)
    app.hatch_view_selected_edit_region_keys = set(keys)
    app._ask_one_way_angle = lambda _current: 45.0

    assert app._on_one_way_handle_double_click(SimpleNamespace(region_key=keys[0], source="edit")) == "break"

    assert all(region.one_way_angle == 45.0 for region in app.hatch_edit_states_by_story["1F"].regions_by_key.values())
    assert len(app.hatch_edit_undo_stack) == 1


def _render_app():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_one_way_mode_var = _Var(False)
    app.hatch_view_selected_region_key = None
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.hatch_view_region_by_key = {}
    app.hatch_view_edit_region_by_key = {}
    app.loaded_regions = []
    app.stories = []
    app.nodes = []
    app.elements = []
    app.story_shape_profiles = ()
    app.generated_dxf_story_names = ()
    app.generated_dxf_layout_metadata = ()
    app.generated_dxf_mode = None
    app.continuous_hatch_checks = {}
    app.hatch_load_drag_hover_key = None
    app.hatch_view_highlight_continuous_var = _Var(False)
    app.hatch_view_show_structure_var = _Var(False)
    app.hatch_view_show_full_plan_var = _Var(False)
    app.hatch_view_display_mode_var = _Var("STORY")
    app.hatch_view_selected_story_var = _Var("1F")
    app.hatch_preview_info_var = _Var()
    app.hatch_preview_legend_var = _Var()
    app.continuous_apply_status_var = _Var()
    app._draw_hatch_structure_items = lambda *args, **kwargs: None
    app._draw_hatch_story_labels = lambda *args, **kwargs: None
    app._draw_hatch_legend = lambda *args, **kwargs: None
    app._refresh_selected_hatch_continuous_info = lambda *args, **kwargs: None
    return app


def _angle_app():
    app = _render_app()
    region = _load_region("D1", _quad(0, 0, 10, 10), _load("DxfOne", distribution="ONE_WAY", angle=0.0))
    app.loaded_regions = [region]
    app.hatch_view_region_by_key = {app._region_key(region, index=1): region}
    app.continuous_apply_targets_by_region = {}
    app.continuous_materialized_targets_by_region = {}
    app.continuous_active_visible_targets = ()
    app.continuous_active_region_key = None
    app.continuous_active_region_keys = ()
    app.continuous_base_story_name = _Var("1F")
    app.hatch_edit_undo_stack = []
    app.hatch_edit_redo_stack = []
    app._render_hatch_preview = lambda *args, **kwargs: None
    app._sync_load_to_continuous_targets_for_region_keys = lambda *args, **kwargs: None
    return app


def _cell(cell_id: str, points):
    polygon = Polygon(points)
    return ClosedCell(
        cell_id=cell_id,
        story_name="1F",
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=tuple(points),
        area=float(polygon.area),
        centroid=(float(polygon.centroid.x), float(polygon.centroid.y)),
        boundary_element_ids=(),
    )


def _load_region(source_id: str, points, load):
    polygon = Polygon(points)
    return LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer=f"LOAD_{source_id}",
            handle=source_id,
            vertices=list(points),
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(value) for value in polygon.bounds),
            story_name="1F",
            source_id=source_id,
        ),
        load=load,
        status="OK" if load else "NO_LOAD",
        warnings=[],
    )


def _load(name: str, *, distribution: str, angle: float | None):
    return LoadLayerInfo(
        layer=f"LOAD_{name}",
        real_name=name,
        dl=1.0,
        ll=1.0,
        distribution=distribution,
        one_way_angle_deg=angle,
    )


def _quad(x1, y1, x2, y2):
    return ((float(x1), float(y1)), (float(x2), float(y1)), (float(x2), float(y2)), (float(x1), float(y2)))


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Canvas:
    def __init__(self):
        self.lines = []
        self.polygons = []
        self.rectangles = []
        self.texts = []
        self.bindings = {}
        self._next_id = 1

    def winfo_exists(self):
        return True

    def winfo_width(self):
        return 640

    def winfo_height(self):
        return 480

    def delete(self, *_args):
        self.lines.clear()
        self.polygons.clear()
        self.rectangles.clear()
        self.texts.clear()

    def configure(self, **_kwargs):
        return None

    def create_polygon(self, *args, **kwargs):
        self.polygons.append((args, kwargs))
        return self._id()

    def create_line(self, *args, **kwargs):
        self.lines.append((args, kwargs))
        return self._id()

    def create_rectangle(self, *args, **kwargs):
        self.rectangles.append((args, kwargs))
        return self._id()

    def create_text(self, *args, **kwargs):
        self.texts.append((args, kwargs))
        return self._id()

    def tag_bind(self, tag, event, callback):
        self.bindings[(tag, event)] = callback

    def tag_raise(self, *_args):
        return None

    def _id(self):
        value = self._next_id
        self._next_id += 1
        return value


def _bbox_intersects(first, second):
    return not (
        first[2] < second[0]
        or second[2] < first[0]
        or first[3] < second[1]
        or second[3] < first[1]
    )


def _one_way_arrow_lines(canvas):
    return [
        (args, kwargs)
        for args, kwargs in canvas.lines
        if "hatch_one_way_arrow" in kwargs.get("tags", ())
    ]


def _one_way_hitbox_lines(canvas):
    return [
        (args, kwargs)
        for args, kwargs in canvas.lines
        if "hatch_one_way_hitbox" in kwargs.get("tags", ())
    ]


def _line_bbox(args):
    x1, y1, x2, y2 = [float(value) for value in args[:4]]
    return (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))


def _line_center(args):
    x1, y1, x2, y2 = [float(value) for value in args[:4]]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _line_length(args):
    x1, y1, x2, y2 = [float(value) for value in args[:4]]
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
