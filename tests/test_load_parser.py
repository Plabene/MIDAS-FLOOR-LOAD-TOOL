from app.core.load_parser import parse_load_layer, make_safe_load_layer_name


def test_parse_common_layer_patterns():
    assert parse_load_layer("사무실, DL:1.2 LL:3.0").real_name == "사무실"
    assert parse_load_layer("사무실,DL:1.2,LL:3.0").ll == 3.0
    assert parse_load_layer("LOAD_001_사무실_DL_1.2_LL_3.0").dl == 1.2


def test_safe_layer_name_keeps_values():
    name = make_safe_load_layer_name(1, "사무실/회의실", 1.2, 3.0)
    assert name.startswith("LOAD_001_")
    assert "DL_1.2_LL_3" in name
