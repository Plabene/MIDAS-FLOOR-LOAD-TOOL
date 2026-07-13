from types import SimpleNamespace

import pytest

from app.core.mgt_parser import (
    Element,
    Node,
    Story,
    parse_elements_from_text,
    section_display_size_by_id_from_text,
    thickness_value_by_id_from_text,
)
from app.main import FloorLoadAutoApp


MODEL_TEXT = """
*UNIT
KN, MM, KJ, C
*SECTION
4, DBUSER, 2~9 B1, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 600, 200
*THICKNESS
2, VALUE, 200, YES, 200, 0, NO, 0, 0
"""


def test_story_prefixed_rc_sb_beam_maps_d1_depth_and_d2_plan_width():
    size = section_display_size_by_id_from_text(MODEL_TEXT)[4]

    assert size.name == "2~9 B1"
    assert size.role == "BEAM"
    assert size.shape == "SB"
    assert size.d1 == 600.0
    assert size.d2 == 200.0
    assert size.width == 200.0
    assert size.depth == 600.0
    assert size.plan_width == 200.0
    assert size.reason == "fields_sb_beam_d1_depth_d2_width"


def test_element_2738_beta_zero_uses_rc_beam_d2_width():
    app = object.__new__(FloorLoadAutoApp)
    size = section_display_size_by_id_from_text(MODEL_TEXT)[4]
    element = parse_elements_from_text(
        """
*ELEMENT
2738, BEAM, 1, 4, 1419, 1420, 0, 0
"""
    )[0]

    assert element.elem_id == 2738
    assert element.angle_deg == 0.0
    assert app._beam_plan_display_width(element, size) == 200.0


def test_wall_2641_and_2649_use_thickness_property_without_fallback():
    app = object.__new__(FloorLoadAutoApp)
    sizes = section_display_size_by_id_from_text(MODEL_TEXT)
    thicknesses = thickness_value_by_id_from_text(MODEL_TEXT)

    assert thicknesses == {2: 200.0}
    for element_id in (2641, 2649):
        element = SimpleNamespace(elem_id=element_id, elem_type="WALL", prop=2, angle_deg=0.0)
        item = app._hatch_structure_item("WALL", [(0.0, 0.0), (1000.0, 0.0)], element, sizes, thicknesses)
        assert item["width"] == 200.0
        assert item["wall_thickness_property"] == 200.0
        assert item["fallback_thickness"] is False
        assert item["width_resolution_reason"] == "wall_thickness_property"


def test_beam_and_wall_widths_have_identical_pixels_under_common_transform():
    app = object.__new__(FloorLoadAutoApp)
    transform, _content_width, _content_height = app._hatch_canvas_transform(
        (0.0, 0.0, 10000.0, 10000.0),
        1000,
        1000,
    )

    widths = [
        app._structure_canvas_dimension(200.0, transform, (0.0, 0.0)),
        app._structure_canvas_dimension(200.0, transform, (0.0, 1000.0)),
        app._structure_canvas_dimension(200.0, transform, (0.0, 2000.0)),
    ]

    assert widths[0] is not None
    assert widths == pytest.approx([widths[0], widths[0], widths[0]])


@pytest.mark.parametrize(
    ("name", "expected_role"),
    [
        ("2~9 B1", "BEAM"),
        ("B6~B1 C1", "COLUMN"),
        ("B1~B2 SG5B", "BEAM"),
        ("B4~B1 SC1", "COLUMN"),
        ("3F CG1", "BEAM"),
    ],
)
def test_story_prefix_is_removed_before_member_role_resolution(name, expected_role):
    size = section_display_size_by_id_from_text(
        f"""
*UNIT
KN, MM, KJ, C
*SECTION
1, DBUSER, {name}, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 600, 200
"""
    )[1]

    assert size.role == expected_role


def test_existing_h_box_and_b2_dimension_regressions_are_preserved():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, MM, KJ, C
*SECTION
10, DBUSER, SG1B, CC, 0, 0, 0, 0, 0, 0, YES, NO, H, 1, KS21, H 900x300x16/28
11, DBUSER, SG2B, CC, 0, 0, 0, 0, 0, 0, YES, NO, BOX, 1, DB, BOX 800x250x12/20
12, DBUSER, B2, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 700, 500
"""
    )

    assert (sizes[10].shape, sizes[10].width, sizes[10].depth) == ("H", 300.0, 900.0)
    assert (sizes[11].shape, sizes[11].width, sizes[11].depth) == ("BOX", 250.0, 800.0)
    assert (sizes[12].width, sizes[12].depth, sizes[12].plan_width) == (500.0, 700.0, 500.0)


def test_mgt_text_change_refreshes_section_wall_and_preview_caches_together():
    app = _regression_app(MODEL_TEXT)
    first = {item["element_id"]: item for item in app._structure_preview_items_for_story("1F")}
    assert first[2738]["width"] == 200.0
    assert first[2641]["width"] == 200.0

    updated_text = MODEL_TEXT.replace("600, 200", "600, 250").replace(
        "2, VALUE, 200, YES, 200, 0",
        "2, VALUE, 250, YES, 250, 0",
    )
    app.current_mgt_text = updated_text
    second = {item["element_id"]: item for item in app._structure_preview_items_for_story("1F")}

    assert second[2738]["width"] == 250.0
    assert second[2641]["width"] == 250.0
    assert app._hatch_section_display_sizes_cache[0] == updated_text
    assert app._hatch_wall_thicknesses_cache[0] == updated_text


def test_element_debug_report_contains_resolved_section_and_thickness_details():
    app = _regression_app(MODEL_TEXT)

    beam_report = app._debug_hatch_structure_element_report(2738, "1F")
    wall_report = app._debug_hatch_structure_element_report(2641, "1F")

    assert beam_report["element_type"] == "BEAM"
    assert beam_report["property_id"] == 4
    assert beam_report["beta_deg"] == 0.0
    assert beam_report["section_name"] == "2~9 B1"
    assert beam_report["section_shape"] == "SB"
    assert beam_report["section_d1"] == 600.0
    assert beam_report["section_d2"] == 200.0
    assert beam_report["resolved_width"] == 200.0
    assert beam_report["resolved_depth"] == 600.0
    assert beam_report["canvas_pixel_width"] is not None
    assert beam_report["width_resolution_reason"].endswith(";beta_0_b")

    assert wall_report["element_type"] == "WALL"
    assert wall_report["property_id"] == 2
    assert wall_report["wall_thickness_property"] == 200.0
    assert wall_report["resolved_width"] == 200.0
    assert wall_report["fallback_thickness"] is False
    assert wall_report["canvas_pixel_width"] == pytest.approx(beam_report["canvas_pixel_width"])
    assert wall_report["width_resolution_reason"] == "wall_thickness_property"


def _regression_app(text: str):
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [
        Node(1419, 0.0, 0.0, 0.0),
        Node(1420, 1000.0, 0.0, 0.0),
        Node(2001, 0.0, 1000.0, 0.0),
        Node(2002, 1000.0, 1000.0, 0.0),
        Node(2003, 0.0, 2000.0, 0.0),
        Node(2004, 1000.0, 2000.0, 0.0),
    ]
    app.elements = [
        Element(2738, "BEAM", mat=1, prop=4, node_ids=(1419, 1420), angle_deg=0.0),
        Element(2641, "WALL", mat=1, prop=2, node_ids=(2001, 2002)),
        Element(2649, "WALL", mat=1, prop=2, node_ids=(2003, 2004)),
    ]
    app.current_mgt_text = text
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    app.loaded_regions = []
    app.hatch_view_fit_bbox = (0.0, 0.0, 10000.0, 10000.0)
    app.hatch_view_view_bbox = app.hatch_view_fit_bbox
    return app
