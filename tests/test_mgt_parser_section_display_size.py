from app.core.mgt_parser import section_display_size_by_id_from_text


def test_section_display_size_parses_name_pairs_before_prefix_numbers():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
1, DBUSER, 600*600
2, DBUSER, 600x500
3, DBUSER, 600X500
4, DBUSER, 600×500
5, DBUSER, C1 600*600
6, DBUSER, G1 600*500
7, DBUSER, C1_B1-4F_1000x700
8, DBUSER, B300x600
9, DBUSER, C500x500
"""
    )

    assert (sizes[1].width, sizes[1].depth) == (0.6, 0.6)
    assert (sizes[2].width, sizes[2].depth) == (0.6, 0.5)
    assert (sizes[3].width, sizes[3].depth) == (0.6, 0.5)
    assert (sizes[4].width, sizes[4].depth) == (0.6, 0.5)
    assert (sizes[5].width, sizes[5].depth) == (0.6, 0.6)
    assert (sizes[6].width, sizes[6].depth) == (0.6, 0.5)
    assert (sizes[7].width, sizes[7].depth) == (1.0, 0.7)
    assert (sizes[8].width, sizes[8].depth) == (0.3, 0.6)
    assert (sizes[9].width, sizes[9].depth) == (0.5, 0.5)
    assert sizes[6].plan_width == 0.5
    assert sizes[7].plan_width == 1.0
    assert sizes[8].plan_width == 0.3


def test_section_display_size_does_not_treat_member_ids_as_dimensions():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
1, DBUSER, C1
2, DBUSER, B1
3, DBUSER, G1
4, DBUSER, W1
5, DBUSER, W200
6, DBUSER, C500
7, DBUSER, B300
"""
    )

    assert sizes[1].width is None
    assert sizes[2].width is None
    assert sizes[3].width is None
    assert sizes[4].width is None
    assert (sizes[5].width, sizes[5].depth) == (0.2, 0.2)
    assert (sizes[6].width, sizes[6].depth) == (0.5, 0.5)
    assert (sizes[7].width, sizes[7].depth) == (0.3, 0.3)
    assert sizes[5].plan_width == 0.2
    assert sizes[6].plan_width == 0.5
    assert sizes[7].plan_width == 0.3


def test_section_display_size_skips_shape_mode_flag_in_fields():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
1, DBUSER, FIELD_M, CC, 0, 0, 0, YES, SB, 2, 0.5, 0.6
2, DBUSER, FIELD_MM, CC, 0, 0, 0, YES, SB, 2, 500, 600
"""
    )

    assert (sizes[1].width, sizes[1].depth) == (0.5, 0.6)
    assert (sizes[2].width, sizes[2].depth) == (0.5, 0.6)
    assert sizes[1].plan_width == 0.5
    assert sizes[2].plan_width == 0.5


def test_beam_plan_width_uses_smaller_field_dimension_for_m_unit_cm_style_name():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
52, DBUSER, G1_60*90, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.9, 0.6
"""
    )

    assert sizes[52].plan_width == 0.6


def test_beam_plan_width_uses_smaller_field_dimension_for_mm_unit():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, MM, KJ, C
*SECTION
6, DBUSER, B2, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 800, 300
"""
    )

    assert sizes[6].plan_width == 300


def test_column_width_depth_not_changed_by_beam_plan_width_rule():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KJ, C
*SECTION
300, DBUSER, C1_B1-4F_1000x700, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 1, 0.7
"""
    )

    assert sizes[300].width == 1.0
    assert sizes[300].depth == 0.7
    assert sizes[300].plan_width == 1.0


def test_b2_section_509_sb_d1_depth_d2_width():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KCAL, C
*SECTION
509, DBUSER, B2, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.7, 0.5, 0, 0, 0, 0, 0, 0, 0, 0
"""
    )

    size = sizes[509]
    assert size.shape == "SB"
    assert size.offset_code == "CC"
    assert size.d1 == 0.7
    assert size.d2 == 0.5
    assert size.width == 0.5
    assert size.depth == 0.7
    assert size.plan_width == 0.5


def test_wall_thickness_unchanged_by_beam_d1_d2_rule():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KCAL, C
*SECTION
20, DBUSER, W1, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 3.0, 0.2
"""
    )

    size = sizes[20]
    assert size.width == 0.2
    assert size.depth == 3.0
    assert size.plan_width == 0.2


def test_cg_section_is_beam_not_column():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KCAL, C
*SECTION
7011, DBUSER, 3F CG1, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.7, 0.5
7012, DBUSER, CGB1, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.8, 0.4
7013, DBUSER, C1_B1-4F_1000x700, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 1.0, 0.7
"""
    )

    assert sizes[7011].width == 0.5
    assert sizes[7011].depth == 0.7
    assert sizes[7011].plan_width == 0.5
    assert sizes[7012].width == 0.4
    assert sizes[7012].depth == 0.8
    assert sizes[7012].plan_width == 0.4
    assert sizes[7013].width == 1.0
    assert sizes[7013].depth == 0.7
    assert sizes[7013].plan_width == 1.0


def test_h_catalog_pair_takes_priority_over_database_identifier_number():
    sizes = section_display_size_by_id_from_text(
        """
*UNIT
KN, M, KCAL, C
*SECTION
203, DBUSER, SG1B, CC, 0, 0, 0, 0, 0, 0, YES, NO, H, 1, KS21, H 900x300x16/28
261, DBUSER, SB0, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.25, 0.125
"""
    )

    h_size = sizes[203]
    assert h_size.shape == "H"
    assert h_size.d1 == 0.9
    assert h_size.d2 == 0.3
    assert h_size.width == 0.3
    assert h_size.depth == 0.9
    assert h_size.plan_width == 0.3

    sb_size = sizes[261]
    assert sb_size.width == 0.125
    assert sb_size.depth == 0.25
    assert sb_size.plan_width == 0.125
