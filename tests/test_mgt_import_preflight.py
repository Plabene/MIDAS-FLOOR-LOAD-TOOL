from app.core.mgt_import_validator import compare_source_and_patched_model_sections, validate_mgt_for_import


SOURCE = """*UNIT
N, MM, KJ, C
*MATERIAL
1, CONC, C30
*SECTION
1, DBUSER, B1
*NODE
1, 0, 0, 0
2, 1, 0, 0
3, 0, 1, 0
*ELEMENT
1, BEAM, 1, 1, 1, 2
*STORY
1F, 0, 3
*STLDCASE
DL, D
*ENDDATA
"""


def test_source_and_patched_comparison_allows_only_new_load_sections():
    patched = SOURCE.replace(
        "*ENDDATA",
        "*FLOADTYPE\nRoof,\nDL, -1, YES\n*FLOORLOAD\nRoof, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3\n*ENDDATA",
    )

    issues = compare_source_and_patched_model_sections(SOURCE, patched)
    result = validate_mgt_for_import(text=patched, original_source_text=SOURCE)

    assert issues == []
    assert result.model_fingerprint.node_count == 3
    assert result.model_fingerprint.element_count == 1
    assert result.model_fingerprint.floorload_count == 1
    assert not result.has_errors


def test_source_node_coordinate_change_is_an_error():
    patched = SOURCE.replace("2, 1, 0, 0", "2, 1.5, 0, 0")

    codes = {issue.code for issue in compare_source_and_patched_model_sections(SOURCE, patched)}

    assert "SOURCE_NODE_COORDINATES_CHANGED" in codes
    assert "SOURCE_MODEL_SECTION_CHANGED" in codes

