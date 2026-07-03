from app.core.floorload_mgt_builder import FloorLoadAssignment, patch_full_mgt_text


def test_two_way_polygon_uses_allow_polygon_yes():
    assignment = FloorLoadAssignment(
        "Office",
        1.2,
        3.4,
        (1, 2, 3, 4, 5),
        "LOAD_001_Office_DL_1.2_LL_3.4",
        "HATCH",
        20.0,
        "OK",
        tuple(),
        distribution="TWO_WAY",
        effective_idist=2,
        allow_polygon_type=True,
    )

    patched = patch_full_mgt_text("*ENDDATA", assignments=[assignment])

    assert "   Office, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4, 5" in patched


def test_one_way_record_uses_angle():
    assignment = FloorLoadAssignment(
        "Office",
        1.2,
        3.4,
        (1, 2, 3, 4),
        "LOAD_001_Office_OW_45_DL_1.2_LL_3.4",
        "HATCH",
        20.0,
        "OK",
        tuple(),
        distribution="ONE_WAY",
        effective_idist=1,
        one_way_angle_deg=45.0,
    )

    patched = patch_full_mgt_text("*ENDDATA", assignments=[assignment])

    assert "   Office, 1, 45, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4" in patched


def test_mgt_never_contains_dxf_layer_or_internal_tracking_text():
    assignment = FloorLoadAssignment(
        "Office",
        1.2,
        3.4,
        (1, 2, 3, 4),
        "LOAD_001_Office_DL_1.2_LL_3.4",
        "HATCH",
        20.0,
        "OK",
        tuple(),
        source_id="DXF_AUTO layer=LOAD_001_Office",
        direction_marker_source_id="DXF_FLOORLOAD",
    )

    patched = patch_full_mgt_text("*ENDDATA", assignments=[assignment])

    assert "LOAD_001_" not in patched
    assert "DXF_AUTO layer=" not in patched
    assert "DXF_FLOORLOAD" not in patched
