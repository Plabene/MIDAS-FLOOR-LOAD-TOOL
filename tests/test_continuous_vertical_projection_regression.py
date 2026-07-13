from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from shapely.geometry import Polygon

from app.core.closed_region_detector import ClosedCell
from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.floorload_mgt_builder import filter_dxf_regions_overridden_by_internal_regions
from app.core.hatch_region_editor import EditableHatchRegion, HatchEditState, create_edit_state
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Story
from app.core.typical_floor_detector import ClosedRegionProfile, StoryShapeProfile, compare_hatch_to_target_story
from app.main import FloorLoadAutoApp


SQUARE = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))


def _quad(x1, y1, x2, y2):
    return ((float(x1), float(y1)), (float(x2), float(y1)), (float(x2), float(y2)), (float(x1), float(y2)))


def test_story_profile_uses_projected_union_for_split_target_regions():
    profile = _profile("TARGET", (_quad(0, 0, 5, 10), _quad(5, 0, 10, 10)))

    match = compare_hatch_to_target_story(SQUARE, profile, xy_tolerance=0.01)

    assert match.ok is True
    assert match.reason == "LOCAL_PROJECTED_UNION_MATCH"
    assert match.source_coverage == pytest.approx(1.0)
    assert match.target_overreach_ratio == pytest.approx(0.0)


@pytest.mark.parametrize(
    "target_polygons, expected_reason",
    [
        ((_quad(0, 0, 5, 10),), "LOCAL_SOURCE_COVERAGE_MISMATCH"),
        ((_quad(-5, -5, 15, 15),), "LOCAL_TARGET_OVERREACH"),
    ],
)
def test_story_profile_rejects_partial_or_oversized_projected_target(target_polygons, expected_reason):
    match = compare_hatch_to_target_story(SQUARE, _profile("TARGET", target_polygons), xy_tolerance=0.01)

    assert match.ok is False
    assert match.reason == expected_reason


def test_target_cell_projection_matches_all_split_cells_as_one_union():
    app = _app()
    source = _editable("SOURCE", "BASE", SQUARE, load_name="Office")
    target = create_edit_state("TARGET", [_cell("L", "TARGET", _quad(0, 0, 5, 10)), _cell("R", "TARGET", _quad(5, 0, 10, 10))])

    match = app._matching_target_cell_projection_for_region(source, target)

    assert match.ok is True
    assert set(match.cell_ids) == {"L", "R"}
    assert match.source_coverage == pytest.approx(1.0)
    assert match.target_overreach_ratio == pytest.approx(0.0)


@pytest.mark.parametrize(
    "target_cells, expected_status",
    [
        (("HALF", _quad(0, 0, 5, 10)), "INCOMPLETE_SOURCE_COVERAGE"),
        (("BIG", _quad(-5, -5, 15, 15)), "NO_SAFE_TARGET_CELLS"),
    ],
)
def test_target_cell_projection_rejects_partial_and_oversized_cells(target_cells, expected_status):
    app = _app()
    source = _editable("SOURCE", "BASE", SQUARE, load_name="Office")
    cell_id, points = target_cells
    target = create_edit_state("TARGET", [_cell(cell_id, "TARGET", points)])

    match = app._matching_target_cell_projection_for_region(source, target)

    assert match.ok is False
    assert match.status == expected_status


@pytest.mark.parametrize("distribution", ["TWO_WAY", "ONE_WAY"])
def test_split_target_cells_receive_two_way_and_one_way_loads(distribution):
    app = _app()
    angle = 0.0 if distribution == "ONE_WAY" else None
    source = _editable("SOURCE", "BASE", SQUARE, load_name="Office", distribution=distribution, angle=angle)
    target = create_edit_state("TARGET", [_cell("L", "TARGET", _quad(0, 0, 5, 10)), _cell("R", "TARGET", _quad(5, 0, 10, 10))])
    _install_source_and_target(app, source, target)

    app.continuous_apply_targets_by_region[source.region_key] = ("TARGET",)
    app._sync_load_to_continuous_targets_for_region_keys((source.region_key,))

    loaded = [region for region in app.hatch_edit_states_by_story["TARGET"].regions_by_key.values() if region.load_name]
    assert {cell_id for region in loaded for cell_id in region.cell_ids} == {"L", "R"}
    assert {region.distribution for region in loaded} == {distribution}
    if distribution == "ONE_WAY":
        assert all(region.one_way_angle == pytest.approx(0.0) for region in loaded)


def test_distant_sources_map_independently_and_selection_order_is_irrelevant():
    def applied(order):
        app = _app()
        first = _editable("SOURCE", "A", _quad(0, 0, 10, 10), load_name="Office")
        second = _editable("SOURCE", "B", _quad(20, 0, 30, 10), load_name="Lobby")
        source_state = HatchEditState("SOURCE", {}, {first.region_key: first, second.region_key: second}, set(), set())
        target = create_edit_state(
            "TARGET",
            [_cell("TA", "TARGET", first.polygon_xy), _cell("TB", "TARGET", second.polygon_xy)],
        )
        app.hatch_edit_states_by_story = {"SOURCE": source_state, "TARGET": target}
        app._refresh_hatch_edit_region_index()
        app.continuous_apply_targets_by_region = {first.region_key: ("TARGET",), second.region_key: ("TARGET",)}
        app._sync_load_to_continuous_targets_for_region_keys(tuple(first.region_key if key == "A" else second.region_key for key in order))
        result = {}
        for region in app.hatch_edit_states_by_story["TARGET"].regions_by_key.values():
            for cell_id in region.cell_ids:
                result[cell_id] = region.load_name
        return result

    assert applied(("A", "B")) == applied(("B", "A")) == {"TA": "Office", "TB": "Lobby"}


def test_sources_from_different_stories_keep_independent_target_story_context():
    app = _app()
    first = _editable("S1", "A", _quad(0, 0, 10, 10), load_name="Office")
    second = _editable("S2", "B", _quad(20, 0, 30, 10), load_name="Lobby")
    app.hatch_edit_states_by_story = {
        "S1": HatchEditState("S1", {}, {first.region_key: first}, set(), set()),
        "S2": HatchEditState("S2", {}, {second.region_key: second}, set(), set()),
        "T1": create_edit_state("T1", [_cell("TA", "T1", first.polygon_xy)]),
        "T2": create_edit_state("T2", [_cell("TB", "T2", second.polygon_xy)]),
    }
    app._refresh_hatch_edit_region_index()
    app.continuous_apply_targets_by_region = {first.region_key: ("T1",), second.region_key: ("T2",)}

    app._sync_load_to_continuous_targets_for_region_keys((second.region_key, first.region_key))

    assert _loaded_names(app, "T1") == ["Office"]
    assert _loaded_names(app, "T2") == ["Lobby"]


def test_common_target_intersection_keeps_empty_region_set():
    app = _app()
    app.continuous_hatch_checks = {
        "A": {"applicable_targets": ("T1", "T2")},
        "B": {"applicable_targets": ()},
    }

    assert app._visible_common_targets_for_region_keys(("A", "B")) == ()
    assert app._visible_common_targets_for_region_keys(("B", "A")) == ()


def test_target_state_is_lazily_created_and_preopen_result_is_identical():
    app = _app()
    source = _editable("SOURCE", "BASE", SQUARE, load_name="Office")
    app.hatch_edit_states_by_story = {"SOURCE": HatchEditState("SOURCE", {}, {source.region_key: source}, set(), set())}
    app._refresh_hatch_edit_region_index()
    app.stories = [object()]
    app.nodes = [object()]
    app.elements = [object()]
    target = create_edit_state("TARGET", [_cell("T", "TARGET", SQUARE)])

    def ensure(story_name):
        app.hatch_edit_states_by_story.setdefault(story_name, target)

    app._ensure_hatch_edit_states = ensure
    unopened = app._continuous_target_polygon_xy_for_below_check(source.region_key, "TARGET")
    opened = app._continuous_target_polygon_xy_for_below_check(source.region_key, "TARGET")

    assert unopened == opened == SQUARE


def test_matching_cache_invalidates_when_target_cell_geometry_changes():
    app = _app()
    source = _editable("SOURCE", "BASE", SQUARE, load_name="Office")
    target = create_edit_state("TARGET", [_cell("T", "TARGET", SQUARE)])

    assert app._matching_target_cell_projection_for_region(source, target).ok is True
    target.cells_by_id["T"] = _cell("T", "TARGET", _quad(-5, -5, 15, 15))
    changed = app._matching_target_cell_projection_for_region(source, target)

    assert changed.ok is False
    assert app._matching_target_cell_geometry_cache_misses == 2


def test_dxf_split_regions_are_compared_as_a_projected_union():
    app = _app()
    source = _dxf("SOURCE", "BASE", SQUARE, "Office")
    left = _dxf("TARGET", "LEFT", _quad(0, 0, 5, 10), None)
    right = _dxf("TARGET", "RIGHT", _quad(5, 0, 10, 10), None)
    app.loaded_regions = [source, left, right]
    source_key = app._region_key(source, index=1)
    app.hatch_view_region_by_key = {source_key: source}

    match = app._matching_target_dxf_projection_for_region_key(source_key, "TARGET")

    assert match.ok is True
    assert len(match.cell_ids) == 2
    assert match.source_coverage == pytest.approx(1.0)


def test_loaded_internal_geometry_overrides_stale_dxf_even_with_different_load():
    internal = _editable("TARGET", "T", SQUARE, load_name="Office")
    stale = _dxf("TARGET", "STALE", SQUARE, "Lobby")

    kept, removed = filter_dxf_regions_overridden_by_internal_regions([stale], [internal])

    assert kept == []
    assert removed == 1


def test_sync_updates_authoritative_state_index_and_does_not_duplicate_on_repeat():
    app = _app()
    source = _editable("SOURCE", "BASE", SQUARE, load_name="Office")
    target = create_edit_state("TARGET", [_cell("T", "TARGET", SQUARE)])
    _install_source_and_target(app, source, target)
    app.continuous_apply_targets_by_region[source.region_key] = ("TARGET",)

    app._sync_load_to_continuous_targets_for_region_keys((source.region_key,))
    first_keys = set(app.hatch_edit_states_by_story["TARGET"].regions_by_key)
    app._sync_load_to_continuous_targets_for_region_keys((source.region_key,))

    target_state = app.hatch_edit_states_by_story["TARGET"]
    assert set(target_state.regions_by_key) == first_keys
    loaded = [region for region in target_state.regions_by_key.values() if region.load_name]
    assert len(loaded) == 1
    assert loaded[0].region_key in app.hatch_view_edit_region_by_key
    assert app.continuous_materialized_targets_by_region[source.region_key] == ("TARGET",)


def test_apply_rejects_unverifiable_empty_target_state_when_model_geometry_exists():
    app = _app()
    source = _editable("SOURCE", "BASE", SQUARE, load_name="Office")
    app.hatch_edit_states_by_story = {
        "SOURCE": HatchEditState("SOURCE", {}, {source.region_key: source}, set(), set()),
        "TARGET": HatchEditState("TARGET", {}, {}, set(), set()),
    }
    app._refresh_hatch_edit_region_index()
    app.stories = [object()]
    app.nodes = [object()]
    app.elements = [object()]

    changed = app._apply_or_remove_continuous_load_to_target_edit_region(
        base_region_key=source.region_key,
        source_region=source,
        target_story="TARGET",
        payload=app._load_payload_from_region_key(source.region_key),
    )

    assert changed is False
    assert app.hatch_edit_states_by_story["TARGET"].regions_by_key == {}


def test_loaded_continuous_internal_region_is_drawn_after_stale_dxf_region():
    app = _app()
    internal = replace(_editable("TARGET", "T", SQUARE, load_name="Office"), source="CONTINUOUS_SYNC")
    app.hatch_edit_states_by_story = {
        "TARGET": HatchEditState("TARGET", {}, {internal.region_key: internal}, set(), set())
    }
    stale = _dxf("TARGET", "STALE", SQUARE, None)
    app.loaded_regions = [stale]
    stale_key = app._region_key(stale, index=1)
    app.continuous_hatch_checks = {stale_key: {"can_select": True}}
    app.stories = [Story("TARGET", 0.0)]
    app.hatch_view_display_mode_var = _Var("STORY")
    app.hatch_view_selected_story_var = _Var("TARGET")
    app.hatch_view_show_structure_var = _Var(False)
    app.hatch_view_show_full_plan_var = _Var(False)
    app.hatch_view_show_legend_var = _Var(False)
    app.hatch_view_highlight_continuous_var = _Var(False)
    app.hatch_view_focus_selected_var = _Var(False)
    app.hatch_load_drag_hover_key = ""
    app.hatch_view_manual_zoom = True
    app.hatch_view_fit_bbox = (0.0, 0.0, 10.0, 10.0)
    app.hatch_view_view_bbox = (0.0, 0.0, 10.0, 10.0)
    app.hatch_preview_legend_var = _Var()
    app.continuous_active_visible_targets = ()
    app.hatch_preview_canvas = _Canvas()
    app._draw_hatch_structure_items = lambda *args, **kwargs: None
    app._draw_hatch_story_labels = lambda *args, **kwargs: None
    app._draw_hatch_legend = lambda *args, **kwargs: None

    FloorLoadAutoApp._render_hatch_preview(app)

    polygon_tags = [tuple(options.get("tags", ())) for _args, options in app.hatch_preview_canvas.polygons]
    assert polygon_tags[0][0] == "hatch_region"
    assert "hatch_edit_loaded" in polygon_tags[-1]
    assert "hatch_continuous_sync" in polygon_tags[-1]


def test_continuous_multi_target_sync_is_one_undo_redo_transaction():
    app = _app()
    source = _editable("SOURCE", "BASE", SQUARE, load_name="Office")
    first = create_edit_state("T1", [_cell("A", "T1", SQUARE)])
    second = create_edit_state("T2", [_cell("B", "T2", SQUARE)])
    app.hatch_edit_states_by_story = {
        "SOURCE": HatchEditState("SOURCE", {}, {source.region_key: source}, set(), set()),
        "T1": first,
        "T2": second,
    }
    app._refresh_hatch_edit_region_index()

    with app._hatch_edit_command("연속층 적용"):
        app.continuous_apply_targets_by_region[source.region_key] = ("T1", "T2")
        app._sync_load_to_continuous_targets_for_region_keys((source.region_key,), refresh_ui=False)

    assert len(app.hatch_edit_undo_stack) == 1
    assert all(_loaded_names(app, story) == ["Office"] for story in ("T1", "T2"))
    app.undo_hatch_view_edit()
    assert all(_loaded_names(app, story) == [] for story in ("T1", "T2"))
    app.redo_hatch_view_edit()
    assert all(_loaded_names(app, story) == ["Office"] for story in ("T1", "T2"))


def _profile(story_name, polygons):
    regions = []
    for index, points in enumerate(polygons, start=1):
        polygon = Polygon(points)
        regions.append(
            ClosedRegionProfile(
                story_name,
                0.0,
                f"R{index}",
                (),
                tuple(points),
                float(polygon.area),
                float(polygon.length),
                (float(polygon.centroid.x), float(polygon.centroid.y)),
                tuple(float(value) for value in polygon.bounds),
            )
        )
    union = Polygon() if not regions else Polygon(regions[0].outer_ring_xy)
    return StoryShapeProfile(story_name, 0.0, tuple(regions), float(union.area), len(regions), True)


def _app():
    app = object.__new__(FloorLoadAutoApp)
    app.config_data = SimpleNamespace(
        snap_tolerance=0.01,
        continuous_projection_min_coverage=0.995,
        continuous_projection_max_overreach_ratio=0.005,
    )
    app.snap_tol_var = _Var(0.01)
    app.story_tol_var = _Var(0.01)
    app.stories = []
    app.nodes = []
    app.elements = []
    app.current_mgt_text = ""
    app.loaded_regions = []
    app.hatch_edit_states_by_story = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_region_by_key = {}
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_edit_region_keys = set()
    app.continuous_apply_targets_by_region = {}
    app.continuous_materialized_targets_by_region = {}
    app.continuous_hatch_checks = {}
    app.story_shape_profiles = [SimpleNamespace(story_name=name) for name in ("SOURCE", "TARGET", "T1", "T2")]
    app.generated_dxf_story_names = ()
    app.generated_dxf_layout_metadata = ()
    app._hatch_state_version = 0
    app._matching_target_cell_geometry_cache_hits = 0
    app._matching_target_cell_geometry_cache_misses = 0
    app.continuous_apply_status_var = _Var()
    app.hatch_preview_info_var = _Var()
    app._render_hatch_preview = lambda *args, **kwargs: None
    app._refresh_selected_hatch_continuous_info = lambda *args, **kwargs: None
    return app


def _install_source_and_target(app, source, target):
    app.hatch_edit_states_by_story = {
        source.story_name: HatchEditState(source.story_name, {}, {source.region_key: source}, set(), set()),
        target.story_name: target,
    }
    app._refresh_hatch_edit_region_index()


def _cell(cell_id, story_name, points):
    polygon = Polygon(points)
    return ClosedCell(
        cell_id,
        story_name,
        0.0,
        (),
        tuple(points),
        float(polygon.area),
        (float(polygon.centroid.x), float(polygon.centroid.y)),
        (),
    )


def _editable(story, cell_id, points, *, load_name, distribution="TWO_WAY", angle=None):
    return EditableHatchRegion(
        region_key=f"INTERNAL|{story}|{cell_id}|LOADED|{load_name or 'NONE'}",
        story_name=story,
        cell_ids=(cell_id,),
        polygon_xy=tuple(points),
        load_name=load_name,
        load_layer=f"LOAD_{load_name}" if load_name else None,
        dl=1.2 if load_name else None,
        ll=3.4 if load_name else None,
        distribution=distribution,
        one_way_angle=angle,
    )


def _dxf(story, source_id, points, load_name):
    polygon = Polygon(points)
    load = None if not load_name else LoadLayerInfo(f"LOAD_{load_name}", load_name, 1.2, 3.4)
    return LoadRegion(
        HatchRegion(
            "HATCH",
            f"LOAD_{load_name or 'NONE'}",
            source_id,
            list(points),
            polygon,
            float(polygon.area),
            tuple(float(value) for value in polygon.bounds),
            story_name=story,
            source_id=source_id,
        ),
        load,
        "OK" if load else "NO_LOAD",
        [],
    )


def _loaded_names(app, story):
    return sorted(
        str(region.load_name)
        for region in app.hatch_edit_states_by_story[story].regions_by_key.values()
        if region.load_name
    )


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
        self._next_id = 1

    def winfo_exists(self):
        return True

    def winfo_width(self):
        return 500

    def winfo_height(self):
        return 500

    def delete(self, *_args):
        self.polygons.clear()

    def configure(self, **_kwargs):
        return None

    def create_polygon(self, *args, **kwargs):
        self.polygons.append((args, kwargs))
        return self._id()

    def create_rectangle(self, *_args, **_kwargs):
        return self._id()

    def create_text(self, *_args, **_kwargs):
        return self._id()

    def create_line(self, *_args, **_kwargs):
        return self._id()

    def tag_bind(self, *_args):
        return None

    def tag_raise(self, *_args):
        return None

    def _id(self):
        value = self._next_id
        self._next_id += 1
        return value
