import pytest

from app.core.pdf_load_importer import (
    PDF_GROUP_ACCEPTED,
    PDF_GROUP_ACCEPTED_WITH_WARNING,
    PDF_GROUP_REVIEW_REQUIRED,
    build_pdf_load_table_groups,
    extract_load_layer_lines,
    filter_accepted_pdf_rows,
    score_pdf_load_semantics,
)


EXPECTED = (
    ("옥탑지붕층", 6.20, 1.0, False),
    ("지붕층", 6.20, 3.0, False),
    ("지붕층(태양광)", 7.20, 3.0, False),
    ("옥상조경", 18.20, 3.0, False),
    ("업무시설", 4.50, 3.5, False),
    ("로비 및 홀", 4.50, 5.0, False),
    ("화장실", 12.26, 3.0, False),
    ("주차통로 및 주차장 (1F)", 14.48, 3.0, False),
    ("후정 (1F)", 7.64, 5.0, False),
    ("저수조 (지하1층)", 4.60, 40.0, True),
    ("소화수조 및 정화조 (지하1층)", 4.60, 15.0, True),
    ("기계실, 발전기실 (지하1층)", 2.30, 10.0, True),
    ("제연팬룸 (지하1층)", 2.30, 5.0, True),
    ("기계식 주차장 (지하1층)", 2.30, 10.0, True),
)


def _rows():
    rows = []
    for index, (name, dl, ll, _review) in enumerate(EXPECTED, start=1):
        common = {
            "source_pdf": "reference.pdf",
            "source_page": 1 if index <= 9 else 2,
            "table_index": 1,
            "floor_load_group_key": f"group-{index}",
            "floor_usage_name": name,
            "has_slab_context": index <= 9,
            "confidence_score": 95,
            "is_valid_for_mgtx": True,
        }
        rows.append({**common, "load_case_name": "DL", "floor_load_value": -dl})
        rows.append({**common, "load_case_name": "LL", "floor_load_value": -ll})
    return rows


def test_reference_14_groups_are_recognized_as_accepted_9_review_5():
    groups = build_pdf_load_table_groups(_rows())
    accepted = [group for group in groups if group.status in {PDF_GROUP_ACCEPTED, PDF_GROUP_ACCEPTED_WITH_WARNING}]
    review = [group for group in groups if group.status == PDF_GROUP_REVIEW_REQUIRED]
    assert len(groups) == 14
    assert len(accepted) == 9
    assert len(review) == 5
    by_name = {group.usage_name_normalized: group for group in groups}
    assert by_name["기계식 주차장"].story_names == ("B1F",)
    assert by_name["기계식 주차장"].dead_total == pytest.approx(2.30)
    assert by_name["기계식 주차장"].live_load == pytest.approx(10.0)
    score = score_pdf_load_semantics(groups)
    assert score.usage_group_count == 14
    assert score.complete_pair_ratio == 1.0
    assert score.accepted_group_count == 9


def test_general_names_are_never_exported_to_ui_layers():
    rows = [
        {"floor_load_type_name": "FLT_DL_GENERAL_", "load_case_name": "DL", "floor_load_value": -1.0, "is_valid_for_mgtx": True},
        {"floor_load_type_name": "LL_GENERAL", "load_case_name": "LL", "floor_load_value": -2.0, "is_valid_for_mgtx": True},
        {"floor_load_type_name": "업무시설", "load_case_name": "DL", "floor_load_value": -4.5, "is_valid_for_mgtx": True},
        {"floor_load_type_name": "업무시설", "load_case_name": "LL", "floor_load_value": -3.5, "is_valid_for_mgtx": True},
    ]
    assert [row["floor_load_type_name"] for row in filter_accepted_pdf_rows(rows)] == ["업무시설", "업무시설"]
    assert extract_load_layer_lines(rows) == ["업무시설, DL:4.5 LL:3.5"]
