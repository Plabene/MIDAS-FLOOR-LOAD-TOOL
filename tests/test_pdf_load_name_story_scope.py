from app.core.pdf_load_importer import (
    normalize_pdf_usage_name,
    pdf_floor_load_type_name,
    split_pdf_usage_story_scope,
)


def test_story_scope_is_split_before_specific_usage_alias():
    usage, raw_scope, stories = split_pdf_usage_story_scope("기계식 주차장 (지하1층)")
    assert usage == "기계식 주차장"
    assert raw_scope == "지하1층"
    assert stories == ("B1F",)

    normalized, _raw, normalized_stories = normalize_pdf_usage_name("기계식 주차장 (지하1층)")
    assert normalized == "기계식 주차장"
    assert normalized_stories == ("B1F",)
    assert pdf_floor_load_type_name(normalized, normalized_stories) == "기계식 주차장(지하1층)"


def test_mechanical_parking_never_collapses_into_generic_parking():
    mechanical = normalize_pdf_usage_name("기계식주차장 B1F")
    ordinary = normalize_pdf_usage_name("주차통로 및 주차장 (1F)")
    assert mechanical[0] == "기계식 주차장"
    assert ordinary[0] == "주차통로 및 주차장"
    assert mechanical[0] != ordinary[0]
    assert mechanical[2] == ("B1F",)
    assert ordinary[2] == ("1F",)
