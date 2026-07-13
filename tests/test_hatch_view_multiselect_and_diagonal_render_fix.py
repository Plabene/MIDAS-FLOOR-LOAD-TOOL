from types import SimpleNamespace

import pytest

import app.main as main_module
from app.core.closed_region_detector import ClosedCell
from app.core.mgt_parser import Story
from app.main import FloorLoadAutoApp


def test_multiselect_continuous_refresh_cancels_previous_callback_and_runs_last_once():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _AfterCanvas()
    app.hatch_preview_canvas = canvas
    refreshes = []
    app._refresh_selected_hatch_continuous_info = lambda: refreshes.append(True)

    app._schedule_selected_hatch_continuous_refresh(180)
    first_id = app._hatch_continuous_refresh_after_id
    app._schedule_selected_hatch_continuous_refresh(180)
    second_id = app._hatch_continuous_refresh_after_id
    app._schedule_selected_hatch_continuous_refresh(120)
    last_id = app._hatch_continuous_refresh_after_id

    assert first_id != second_id != last_id
    assert canvas.cancelled == [first_id, second_id]
    assert [delay for delay, _callback in canvas.callbacks.values()] == [120]
    canvas.callbacks[last_id][1]()
    assert refreshes == [True]


def test_same_section_collinear_beam_items_merge_into_one_chain():
    app = object.__new__(FloorLoadAutoApp)
    items = [
        _beam(1, [(0.0, 0.0), (1.0, 1.0)]),
        _beam(2, [(2.0, 2.0), (1.0, 1.0)]),
        _beam(3, [(2.0, 2.0), (3.0, 3.0)]),
        _beam(4, [(3.0, 3.0), (4.0, 4.0)], section_id=99),
    ]

    merged = app._merge_collinear_structure_beam_items(items)

    assert len(merged) == 2
    assert merged[0]["points"] == [(0.0, 0.0), (1.0, 1.0), (2.0, 2.0), (3.0, 3.0)]
    assert merged[0]["element_ids"] == (1, 2, 3)
    assert merged[1]["element_id"] == 4


def test_equal_collinear_branch_candidates_are_not_merged():
    app = object.__new__(FloorLoadAutoApp)
    items = [
        _beam(1, [(0.0, 0.0), (1.0, 1.0)]),
        _beam(2, [(1.0, 1.0), (2.0, 2.0)]),
        _beam(3, [(1.0, 1.0), (3.0, 3.0)]),
    ]

    merged = app._merge_collinear_structure_beam_items(items)

    assert len(merged) == 3
    assert all(len(item["points"]) == 2 for item in merged)


def test_open_multi_point_offset_fallback_does_not_close_last_to_first(monkeypatch):
    app = object.__new__(FloorLoadAutoApp)
    canvas = _DrawCanvas()

    monkeypatch.setattr(main_module, "LineString", lambda _points: (_ for _ in ()).throw(RuntimeError("buffer failed")))

    app._draw_dashed_offset_polyline(
        canvas,
        [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0)],
        20.0,
        outline="#111111",
        tags=("structure:BEAM",),
    )

    assert len(canvas.lines) == 2


def test_complete_hatch_edit_states_reuse_closed_cells_without_redetection(monkeypatch):
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [object()]
    app.elements = [object()]
    app.current_mgt_text = ""
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    app.snap_tol_var = SimpleNamespace(get=lambda: 0.5)
    cell = ClosedCell(
        cell_id="1F:C1",
        story_name="1F",
        story_elevation=0.0,
        node_ids=(1, 2, 3, 4),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        area=100.0,
        centroid=(5.0, 5.0),
        boundary_element_ids=(1, 2, 3, 4),
    )
    app.hatch_edit_states_by_story = {"1F": SimpleNamespace(cells_by_id={cell.cell_id: cell})}
    app._story_below_allowed_polygon_cache_token = lambda: ("model",)
    app._hatch_edit_state_geometry_token_by_story = {"1F": ("1F", "model")}
    app._hatch_perf_start = lambda *_args, **_kwargs: None
    app._hatch_perf_end = lambda *_args, **_kwargs: None
    app._hatch_view_display_mode = lambda: "STORY"
    app._warn_story_below_allowed_region_missing = lambda *_args, **_kwargs: None
    monkeypatch.setattr(main_module, "detect_closed_cells", lambda **_kwargs: pytest.fail("must reuse existing cells"))

    result = app._story_below_allowed_polygons_by_name(["1F"])

    assert len(result["1F"]) == 1
    assert result["1F"][0].area == pytest.approx(100.0)


def _beam(element_id, points, *, section_id=10, width=0.3):
    return {
        "kind": "BEAM",
        "story_name": "1F",
        "section_id": section_id,
        "width": width,
        "points": points,
        "element_id": element_id,
    }


class _AfterCanvas:
    def __init__(self):
        self.next_id = 0
        self.callbacks = {}
        self.cancelled = []

    def after(self, delay, callback):
        self.next_id += 1
        after_id = f"after-{self.next_id}"
        self.callbacks[after_id] = (delay, callback)
        return after_id

    def after_cancel(self, after_id):
        self.cancelled.append(after_id)
        self.callbacks.pop(after_id, None)


class _DrawCanvas:
    def __init__(self):
        self.lines = []
        self.polygons = []

    def create_line(self, *args, **kwargs):
        self.lines.append((args, kwargs))

    def create_polygon(self, *args, **kwargs):
        self.polygons.append((args, kwargs))
