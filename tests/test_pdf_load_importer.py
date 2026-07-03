from pathlib import Path

from app.core.pdf_load_importer import (
    detect_floor_load_presence_from_text,
    extract_load_layer_lines,
    merge_pdf_mgtx_into_full_mgt,
)


def test_detect_floor_load_presence_counts_assigned_floorload():
    text = """
*STLDCASE
   DL, D, PDF_AUTO
*FLOADTYPE
   사무실, PDF_AUTO
   DL, -1.2, YES
*FLOORLOAD
   사무실, 2, 0, 0, 0, 0, GZ, NO, DXF, NO, YES, G, 1, 2, 3, 4
*ENDDATA
"""
    result = detect_floor_load_presence_from_text(text)
    assert result.has_floorload is True
    assert result.floorload_count == 1
    assert result.floadtype_count == 1
    assert result.stldcase_count == 1


def test_extract_load_layer_lines_groups_dl_ll():
    rows = [
        {"floor_load_type_name": "사무실", "load_case_name": "DL", "floor_load_value": -1.2},
        {"floor_load_type_name": "사무실", "load_case_name": "LL", "floor_load_value": -3.0},
        {"floor_load_type_name": "복도", "load_case_name": "LIVE", "floor_load_value": 4.0},
    ]
    lines = extract_load_layer_lines(rows)
    assert "사무실, DL:1.2 LL:3" in lines
    assert "복도, DL:0 LL:4" in lines


def test_merge_pdf_mgtx_into_full_mgt_skips_duplicates(tmp_path: Path):
    source = tmp_path / "source.mgt"
    source.write_text(
        "*UNIT\n   KN, M\n*STLDCASE\n   DL, D, OLD\n*FLOADTYPE\n   기존, OLD\n   DL, -1, YES\n*ENDDATA\n",
        encoding="utf-8",
    )
    mgtx = tmp_path / "pdf.mgtx"
    mgtx.write_text(
        "*STLDCASE\n   DL, D, PDF_AUTO\n   LL, L, PDF_AUTO\n*FLOADTYPE\n   기존, PDF_AUTO\n   DL, -1.2, YES\n   사무실, PDF_AUTO\n   DL, -1.2, YES, LL, -3, NO\n*ENDDATA\n",
        encoding="utf-8",
    )
    out = tmp_path / "merged.mgt"
    result = merge_pdf_mgtx_into_full_mgt(source_mgt_path=source, pdf_mgtx_path=mgtx, output_mgt_path=out, encoding="utf-8")
    merged = out.read_text(encoding="utf-8")
    assert result.added_stldcase_count == 1
    assert result.added_floadtype_count == 1
    assert "LL, L, PDF_AUTO" in merged
    assert "사무실, PDF_AUTO" in merged
    assert result.skipped_floadtype_names == ("기존",)
