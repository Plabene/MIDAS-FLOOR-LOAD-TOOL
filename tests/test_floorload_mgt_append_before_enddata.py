from app.core.floorload_mgt_builder import FloorLoadAssignment, patch_full_mgt_text


def _assignment(load_type_name: str = "RoofLoad", node_ids: tuple[int, ...] = (126, 128, 129, 116)) -> FloorLoadAssignment:
    return FloorLoadAssignment(
        load_type_name=load_type_name,
        dl=8.6,
        ll=1.0,
        node_ids=node_ids,
        source_layer="LOAD_001_RoofLoad_DL_8.6_LL_1",
        source_type="HATCH",
        area=28.77,
        status="OK",
        warnings=(),
    )


def test_patch_appends_new_floorload_block_before_enddata_even_when_existing_floorload_exists():
    text = """
*FLOADTYPE
   RoofLoad,
   DL, -8.6, YES, LL, -1, NO

*FLOORLOAD
   ExistingLoad, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3

*WALLMARK
   W1, 1 2

*ENDDATA
""".strip()

    patched = patch_full_mgt_text(text, assignments=[_assignment()])

    assert patched.count("*FLOORLOAD") == 2
    assert patched.rfind("*FLOORLOAD") < patched.rfind("*ENDDATA")
    assert patched.rfind("*FLOORLOAD") > patched.rfind("*WALLMARK")
    assert "   RoofLoad, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 126, 128, 129, 116" in patched
    assert "DXF_AUTO layer=" not in patched
    assert "DXF_FLOORLOAD" not in patched
    assert "LOAD_001_" not in patched


def test_existing_floadtype_is_not_duplicated_when_appending_floorload():
    text = """
*FLOADTYPE
   RoofLoad,
   DL, -8.6, YES, LL, -1, NO

*ENDDATA
""".strip()

    patched = patch_full_mgt_text(text, assignments=[_assignment()])

    assert patched.count("*FLOADTYPE") == 1
    assert patched.count("RoofLoad,") == 2


def test_auto_floorload_desc_and_group_are_blank():
    patched = patch_full_mgt_text("*ENDDATA", assignments=[_assignment()])
    record = next(line for line in patched.splitlines() if line.startswith("   RoofLoad, 2"))

    fields = [part.strip() for part in record.split(",")]
    assert fields[8] == ""
    assert fields[11] == ""
    assert "LOAD_001_" not in record
    assert "DXF_AUTO" not in record
    assert "DXF_FLOORLOAD" not in record


def test_same_load_type_multi_regions_create_multiple_floorload_records():
    patched = patch_full_mgt_text(
        "*ENDDATA",
        assignments=[
            _assignment(node_ids=(1, 2, 3, 4)),
            _assignment(node_ids=(11, 12, 13, 14)),
        ],
    )

    records = [line for line in patched.splitlines() if line.startswith("   RoofLoad, 2")]
    assert len(records) == 2
    assert "   RoofLoad, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4" in records
    assert "   RoofLoad, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 11, 12, 13, 14" in records
    assert patched.count("   RoofLoad,") == 3
    assert "LOAD_001_" not in patched
    assert "DXF_AUTO layer=" not in patched
    assert "DXF_FLOORLOAD" not in patched
