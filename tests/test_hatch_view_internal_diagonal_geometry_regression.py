from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon

import app.main as main_module
from app.core.closed_region_detector import ClosedCell, _effective_xy_tolerance, _snap_endpoint, detect_closed_cells
from app.core.hatch_region_editor import create_edit_state
from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp


PROBLEM_COORDINATES = (
    (10.888, 2.680),
    (10.052, 2.376),
    (9.821, 3.010),
    (9.736, 3.245),
    (9.360, 4.278),
    (9.094, 5.007),
    (9.343, 5.097),
    (10.034, 5.349),
    (11.462, 5.869),
    (12.618, 6.289),
    (13.598, 6.646),
    (14.577, 7.002),
    (15.557, 7.359),
    (16.603, 7.740),
    (17.648, 8.120),
    (17.922, 7.368),
    (18.196, 6.616),
    (18.606, 5.489),
    (17.600, 5.123),
    (16.594, 4.757),
    (15.588, 4.390),
    (14.582, 4.024),
    (13.576, 3.658),
    (12.261, 3.179),
    (12.036, 3.097),
)


def test_problem_diagonal_polygon_preserves_original_mgt_coordinates():
    stories = [Story("3F", 0.0)]
    nodes = [Node(index, x, y, 0.0) for index, (x, y) in enumerate(PROBLEM_COORDINATES, start=1)]
    elements = [
        Element(index + 1, "BEAM", node_ids=(index + 1, (index + 1) % len(nodes) + 1))
        for index in range(len(nodes))
    ]

    cells = detect_closed_cells(
        stories=stories,
        nodes=nodes,
        elements=elements,
        story_name="3F",
        story_tolerance=0.01,
        xy_tolerance=0.001,
    )

    assert len(cells) == 1
    assert set(cells[0].polygon_xy) == set(PROBLEM_COORDINATES)
    assert cells[0].area == pytest.approx(Polygon(PROBLEM_COORDINATES).area, abs=1.0e-9)
    assert cells[0].area == pytest.approx(25.4872, abs=0.005)
    assert not {(11.0, 2.5), (10.0, 2.5), (10.0, 3.0)}.intersection(cells[0].polygon_xy)
    assert max(
        min(((x - sx) ** 2 + (y - sy) ** 2) ** 0.5 for sx, sy in PROBLEM_COORDINATES)
        for x, y in cells[0].polygon_xy
    ) <= 1.0e-12


def test_endpoint_fallback_paths_preserve_new_source_coordinates():
    point = (0.1234, 0.2176)
    points = []

    assert _snap_endpoint(point, 0.5, None) == point
    assert _snap_endpoint(point, 0.5, points) == point
    assert points == [point]


def test_explicit_positive_geometry_tolerance_is_not_raised_to_old_floor():
    assert _effective_xy_tolerance(None) == 0.005
    assert _effective_xy_tolerance(0.0) == 0.005
    assert _effective_xy_tolerance(0.001) == 0.001
    assert _effective_xy_tolerance(1.0e-10) == 1.0e-9


def test_internal_detection_uses_unit_geometry_tolerance_not_floorload_snap(monkeypatch):
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 1.0, 0.0, 0.0), Node(3, 0.0, 1.0, 0.0)]
    app.elements = [Element(1, "BEAM", node_ids=(1, 2))]
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n"
    app.story_tol_var = _Var(0.01)
    app.snap_tol_var = _Var(0.5)
    app.generated_dxf_story_names = ()
    app.hatch_edit_states_by_story = {}
    app._hatch_edit_state_geometry_token_by_story = {}
    app._story_below_elements_for_story = lambda _name: tuple(app.elements)
    app._hatch_perf_start = lambda *_args, **_kwargs: None
    app._hatch_perf_end = lambda *_args, **_kwargs: None
    app._write_hatch_closed_region_diagnostics = lambda *_args, **_kwargs: None
    app._invalidate_continuous_below_allowed_reason_cache = lambda *_args, **_kwargs: None
    app._hatch_view_display_mode = lambda: "STORY"
    captured = []

    def fake_detect(**kwargs):
        captured.append(kwargs["xy_tolerance"])
        return ()

    monkeypatch.setattr(main_module, "detect_closed_cells", fake_detect)

    app._ensure_hatch_edit_states("1F")

    assert captured == [0.001]
    assert app.snap_tol_var.get() == 0.5


def test_allowed_polygon_cache_token_ignores_floorload_snap_tolerance():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [Node(1, 0.0, 0.0, 0.0)]
    app.elements = [Element(1, "BEAM", node_ids=(1, 1))]
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n"
    app.story_tol_var = _Var(0.01)
    app.snap_tol_var = _Var(0.5)

    first = app._story_below_allowed_polygon_cache_token()
    app.snap_tol_var.set(2.0)
    second = app._story_below_allowed_polygon_cache_token()

    assert first == second


def test_edit_state_regenerates_when_model_geometry_token_changes(monkeypatch):
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 1.0, 0.0, 0.0)]
    app.elements = [Element(1, "BEAM", node_ids=(1, 2))]
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n"
    app.story_tol_var = _Var(0.01)
    app.snap_tol_var = _Var(0.5)
    app.generated_dxf_story_names = ()
    app.hatch_edit_states_by_story = {}
    app._hatch_edit_state_geometry_token_by_story = {}
    app._story_below_elements_for_story = lambda _name: tuple(app.elements)
    app._hatch_perf_start = lambda *_args, **_kwargs: None
    app._hatch_perf_end = lambda *_args, **_kwargs: None
    app._write_hatch_closed_region_diagnostics = lambda *_args, **_kwargs: None
    app._invalidate_continuous_below_allowed_reason_cache = lambda *_args, **_kwargs: None
    app._hatch_view_display_mode = lambda: "STORY"
    captured = []
    monkeypatch.setattr(main_module, "detect_closed_cells", lambda **kwargs: captured.append(kwargs["xy_tolerance"]) or ())

    app._ensure_hatch_edit_states("1F")
    app.current_mgt_text = "*UNIT\nKN, CM, KJ, C\n"
    app._ensure_hatch_edit_states("1F")

    assert captured == [0.001, 0.1]


@pytest.mark.parametrize(
    ("unit", "expected"),
    [("M", 0.001), ("CM", 0.1), ("MM", 1.0), ("FT", 0.00328084), ("IN", 0.0393701)],
)
def test_closed_region_geometry_tolerance_tracks_model_length_unit(unit, expected):
    app = object.__new__(FloorLoadAutoApp)
    app.current_mgt_text = f"*UNIT\nKN, {unit}, KJ, C\n"

    assert app._closed_region_geometry_tolerance() == pytest.approx(expected)


def test_exact_problem_polygon_simplification_is_display_only_and_round_joined():
    app = object.__new__(FloorLoadAutoApp)
    original = tuple(PROBLEM_COORDINATES)

    simplified = app._simplify_hatch_display_vertices(original, 0.3)

    assert len(simplified) < len(original)
    assert tuple(PROBLEM_COORDINATES) == original

    canvas = _Canvas()
    region = SimpleNamespace(load_name=None, distribution="TWO_WAY", polygon_xy=original)
    app.hatch_view_selected_edit_region_keys = {"R1"}
    app.hatch_load_drag_hover_key = None
    app.hatch_view_edit_region_items = {}
    app.hatch_view_edit_checkbox_items = {}
    app._draw_hatch_edit_regions(
        canvas,
        [("R1", region, list(original))],
        lambda x, y: (x, y),
        {},
        simplify_tolerance=0.3,
    )

    assert canvas.polygons[0][1]["joinstyle"] == "round"
    assert tuple(region.polygon_xy) == original


def test_internal_geometry_debug_report_matches_source_nodes_without_shift():
    app = object.__new__(FloorLoadAutoApp)
    coordinates = ((0.123, 0.217), (3.987, 1.653), (3.211, 4.789), (-0.653, 3.353))
    app.stories = [Story("1F", 0.0)]
    app.nodes = [Node(index, x, y, 0.0) for index, (x, y) in enumerate(coordinates, start=1)]
    app.elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "BEAM", node_ids=(2, 3)),
        Element(3, "BEAM", node_ids=(3, 4)),
        Element(4, "BEAM", node_ids=(4, 1)),
    ]
    cell = ClosedCell(
        cell_id="1F:C1",
        story_name="1F",
        story_elevation=0.0,
        node_ids=(1, 2, 3, 4),
        polygon_xy=coordinates,
        area=Polygon(coordinates).area,
        centroid=(1.5, 2.5),
        boundary_element_ids=(1, 2, 3, 4),
    )
    state = create_edit_state("1F", [cell])
    region_key, region = next(iter(state.regions_by_key.items()))
    app.hatch_edit_states_by_story = {"1F": state}
    app.hatch_view_edit_region_by_key = {region_key: region}
    app.hatch_view_region_by_key = {}
    app.loaded_regions = []
    app.current_mgt_text = "*UNIT\nKN, M, KJ, C\n"
    app.snap_tol_var = _Var(0.5)
    app.hatch_view_display_mode_var = _Var("STORY")
    app.generated_dxf_mode = None
    app.generated_dxf_layout_metadata = ()
    app.generated_dxf_story_names = ("1F",)
    app.hatch_view_view_bbox = None
    app.hatch_view_fit_bbox = None

    report = app._selected_hatch_geometry_debug_report(region_key)

    assert report["source"] == "INTERNAL"
    assert report["maximum_coordinate_shift"] == pytest.approx(0.0)
    assert report["average_coordinate_shift"] == pytest.approx(0.0)
    assert report["hausdorff_distance"] == pytest.approx(0.0)
    assert report["symmetric_difference_area"] == pytest.approx(0.0)
    assert report["geometry_tolerance"] == pytest.approx(0.001)
    assert report["floorload_snap_tolerance"] == pytest.approx(0.5)


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Canvas:
    def __init__(self):
        self.polygons = []
        self.rectangles = []
        self.texts = []

    def create_polygon(self, *args, **kwargs):
        self.polygons.append((args, kwargs))
        return len(self.polygons)

    def create_rectangle(self, *args, **kwargs):
        self.rectangles.append((args, kwargs))
        return 100 + len(self.rectangles)

    def create_text(self, *args, **kwargs):
        self.texts.append((args, kwargs))
        return 200 + len(self.texts)
