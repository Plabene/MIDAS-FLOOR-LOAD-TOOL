from app.core.mgt_parser import (
    iter_floorload_records_from_text,
    parse_floorload_type_names_from_text,
    parse_floadtype_specs_from_text,
)


def test_parse_floadtype_specs_groups_dl_ll_and_abs_values():
    text = """
*FLOADTYPE
   사무실, DESC
   DL, -1.2, YES, LL, -3.0, NO
   복도, DESC
   DEAD, 0.8, YES, LIVE, 4.0, NO
*ENDDATA
"""
    specs = parse_floadtype_specs_from_text(text)
    assert [(spec.name, spec.dl, spec.ll) for spec in specs] == [
        ("사무실", 1.2, 3.0),
        ("복도", 0.8, 4.0),
    ]


def test_parse_floadtype_specs_treats_unknown_case_as_dl():
    text = """
*FLOADTYPE
   장비실, DESC
   WIND, -2.5, NO
*ENDDATA
"""
    specs = parse_floadtype_specs_from_text(text)
    assert len(specs) == 1
    assert specs[0].name == "장비실"
    assert specs[0].dl == 2.5
    assert specs[0].ll == 0.0


def test_parse_floorload_type_names_fallback():
    text = """
*FLOORLOAD
   사무실, 2, 0, 0, 0, 0, GZ, NO, DXF, NO, YES, G, 1, 2, 3
   사무실, 2, 0, 0, 0, 0, GZ, NO, DXF, NO, YES, G, 4, 5, 6
   복도, 2, 0, 0, 0, 0, GZ, NO, DXF, NO, YES, G, 7, 8, 9
*ENDDATA
"""
    assert parse_floorload_type_names_from_text(text) == ["사무실", "복도"]
