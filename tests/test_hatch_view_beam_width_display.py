from types import SimpleNamespace

from app.core.mgt_parser import section_display_size_by_id_from_text
from app.main import FloorLoadAutoApp


def test_beam_section_plan_width_uses_smaller_name_pair_dimension():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
1, DBUSER, G1 600*500
2, DBUSER, B300x600
"""
    )

    assert sizes[1].plan_width == 0.5
    assert sizes[2].plan_width == 0.3


def test_beam_section_plan_width_uses_sb_d2_as_width():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
1, DBUSER, FIELD_BEAM, CC, 0, 0, 0, YES, SB, 2, 0.7, 0.5
"""
    )

    assert (sizes[1].width, sizes[1].depth, sizes[1].plan_width) == (0.5, 0.7, 0.5)


def test_hatch_structure_beam_item_uses_plan_width_not_depth():
    app = object.__new__(FloorLoadAutoApp)
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
1, DBUSER, B500x600
"""
    )

    item = app._hatch_structure_item("BEAM", [(0.0, 0.0), (10.0, 0.0)], SimpleNamespace(prop=1, elem_id=10), sizes)

    assert item["width"] == 0.5
    assert item["depth"] == 0.6


def test_hatch_structure_beam_uses_plan_width_from_smaller_field_dimension():
    app = object.__new__(FloorLoadAutoApp)
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
52, DBUSER, G1_60*90, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.9, 0.6
"""
    )

    item = app._hatch_structure_item("BEAM", [(0.0, 0.0), (10.0, 0.0)], SimpleNamespace(prop=52, elem_id=1), sizes)

    assert item["width"] == 0.6


def test_hatch_structure_column_keeps_model_width_and_depth():
    app = object.__new__(FloorLoadAutoApp)
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
1, DBUSER, C1_B1-4F_1000x700
"""
    )

    item = app._hatch_structure_item("COLUMN", [(0.0, 0.0)], SimpleNamespace(prop=1, elem_id=20), sizes)

    assert item["width"] == 1.0
    assert item["depth"] == 0.7
