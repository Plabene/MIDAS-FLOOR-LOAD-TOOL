from app.core.mgt_parser import iter_floorload_records_from_text, parse_floorload_type_names_from_text


def test_iter_floorload_records_handles_continuation_line():
    text = """
*FLOORLOAD
   Housing, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1178, 1168, 1237, 3444, 1166, 1199, \\
        1197, 1196
*ENDDATA
"""
    records = iter_floorload_records_from_text(text)

    assert len(records) == 1
    assert records[0].ltname == "Housing"
    assert records[0].node_ids[-2:] == (1197, 1196)


def test_floorload_continuation_does_not_create_fake_load_name():
    text = """
*FLOORLOAD
   Housing, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1178, 1168, \\
        1197, 1196
*ENDDATA
"""
    assert parse_floorload_type_names_from_text(text) == ["Housing"]
