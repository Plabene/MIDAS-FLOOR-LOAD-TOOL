from app.core.load_selection import apply_load_display_names


def test_apply_load_display_names_keeps_unique_names_plain():
    items = [
        {"source": "MODEL", "name": "복도", "dl": 1.0, "ll": 4.0},
        {"source": "PDF", "name": "사무실", "dl": 1.2, "ll": 3.0},
    ]
    result = apply_load_display_names(items)
    assert [item["display_name"] for item in result] == ["복도", "사무실"]


def test_apply_load_display_names_marks_model_pdf_duplicates():
    items = [
        {"source": "MODEL", "name": "사무실", "dl": 1.2, "ll": 3.0},
        {"source": "PDF", "name": "사무실", "dl": 1.2, "ll": 3.0},
    ]
    result = apply_load_display_names(items)
    assert [item["display_name"] for item in result] == ["사무실 - MODEL", "사무실 - PDF"]


def test_apply_load_display_names_numbers_same_source_duplicates():
    items = [
        {"source": "PDF", "name": "사무실", "dl": 1.2, "ll": 3.0},
        {"source": "PDF", "name": "사무실", "dl": 1.0, "ll": 2.0},
    ]
    result = apply_load_display_names(items)
    assert [item["display_name"] for item in result] == ["사무실 - PDF", "사무실 - PDF #2"]
