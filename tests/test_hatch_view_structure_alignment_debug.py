from types import SimpleNamespace

from app.main import FloorLoadAutoApp


def test_structure_centerline_offset_report_is_zero_on_matching_hatch_boundary():
    app = object.__new__(FloorLoadAutoApp)
    app.loaded_regions = []
    app._hatch_story_display_offsets = lambda _regions: {}
    app._hatch_view_display_edit_regions = lambda _offsets=None: [
        (
            "edit-1",
            SimpleNamespace(story_name="1F"),
            [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)],
        )
    ]
    app._structure_preview_items_for_story = lambda _story: [
        {"kind": "BEAM", "points": [(0.0, 0.0), (10.0, 0.0)], "width": 0.5, "element_id": 101}
    ]
    app._hatch_view_is_all_story_display = lambda: False
    app._continuous_sync_xy_tolerance = lambda: 0.5

    report = app._structure_centerline_to_hatch_boundary_offset_report("1F")

    assert len(report) == 1
    assert report[0]["element_id"] == 101
    assert report[0]["max_offset"] == 0.0
