from app.main import FloorLoadAutoApp, HatchDisplayTransform


def test_structure_scale_report_uses_display_dimension_scale_once():
    app = object.__new__(FloorLoadAutoApp)
    app.loaded_regions = []
    app.current_mgt_text = ""
    app.hatch_view_view_bbox = (0.0, 0.0, 10.0, 10.0)
    app._hatch_story_display_offsets = lambda _regions: {}
    app._hatch_display_transform_for_story = lambda *_args: HatchDisplayTransform(story_name="1F", scale_x=2.0, scale_y=2.0)
    app._structure_preview_items_for_story = lambda _story: [
        {"kind": "BEAM", "points": [(0.0, 0.0), (10.0, 0.0)], "width": 0.5, "element_id": 101}
    ]
    app._hatch_view_display_mode = lambda: "ALL"
    app._hatch_view_is_all_story_display = lambda: True

    report = app._debug_hatch_structure_scale_report("1F")

    assert report["dimension_scale"] == 2.0
    assert report["sample_width_model"] == 0.5
    assert report["sample_width_display"] == 1.0
    assert report["sample_width_px"] == 100.0
