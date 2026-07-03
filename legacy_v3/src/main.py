from pathlib import Path

import yaml

from load_classifier import classify_loads
from load_parser import parse_load_rows
from manual_overrides import apply_manual_overrides, load_manual_overrides
from midas_mgtx_writer import write_log_files, write_mgtx_file
from pdf_extract import extract_pdf_load_candidates
from validators import validate_rows
from block_summary_parser import extract_block_summary_candidates_from_pdfs


ROOT_DIR = Path(__file__).resolve().parent.parent
INPUT_DIR = ROOT_DIR / "input_pdfs"
OUTPUT_DIR = ROOT_DIR / "output"
CONFIG_DIR = ROOT_DIR / "config"
REFERENCE_MGTX_DIR = ROOT_DIR / "reference_mgtx"


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def main():
    INPUT_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    settings_path = CONFIG_DIR / "midas_settings.yml"
    mapping_path = CONFIG_DIR / "load_mapping.yml"
    settings = load_yaml(settings_path)

    output_file_name = settings.get("output", {}).get("file_name", "midas_auto_define_floor_load_type.mgtx")
    encoding = settings.get("output", {}).get("encoding", "cp949")
    create_empty_mgtx = bool(settings.get("output", {}).get("create_empty_mgtx_when_no_rows", False))
    prefix_auto_desc = settings.get("naming", {}).get("prefix_auto_desc", "PDF_AUTO")
    mgtx_path = OUTPUT_DIR / output_file_name

    print("========================================")
    print("PDF to MIDAS NX Floor Load Type Automation")
    print("하중표의 DL/LL/사용하중/계수하중을 분석합니다.")
    print("*STLDCASE와 *FLOADTYPE을 새로 생성합니다.")
    print("*FLOORLOAD는 생성하지 않습니다.")
    print("========================================")

    raw_rows = extract_pdf_load_candidates(INPUT_DIR)
    block_summary_rows = extract_block_summary_candidates_from_pdfs(INPUT_DIR)
    if block_summary_rows:
        raw_rows.extend(block_summary_rows)
    if not raw_rows:
        print("하중 후보를 찾지 못했습니다")
        diagnostic_rows = []
        for pdf_path in sorted(INPUT_DIR.glob("*.pdf")):
            diagnostic_rows.append({
                "source_pdf": pdf_path.name,
                "source_page": None,
                "extraction_method": "scan_ocr_fallback",
                "pdf_page_type": "UNKNOWN",
                "ocr_required": True,
                "mgtx_row_count": 0,
                "review_flag": True,
                "exclude_from_mgtx": True,
                "is_valid_for_mgtx": False,
                "failure_stage": "OCR_NOT_TRIGGERED",
                "failure_reason": "No candidate rows were returned by PDF extraction.",
                "exclude_reason": "스캔 PDF에서 유효한 하중표 row를 생성하지 못함",
                "debug_dir": str(ROOT_DIR / "debug" / "ocr_fallback" / pdf_path.stem),
            })
        if not diagnostic_rows:
            diagnostic_rows.append({
                "source_pdf": "",
                "source_page": None,
                "extraction_method": "none",
                "pdf_page_type": "UNKNOWN",
                "ocr_required": True,
                "mgtx_row_count": 0,
                "review_flag": True,
                "exclude_from_mgtx": True,
                "is_valid_for_mgtx": False,
                "failure_stage": "OCR_NOT_TRIGGERED",
                "failure_reason": "No PDF files or candidate rows were found.",
                "exclude_reason": "유효한 하중표 row를 생성하지 못함",
            })
        write_log_files(diagnostic_rows, diagnostic_rows, OUTPUT_DIR)
        print(f"로그 파일: {OUTPUT_DIR / 'auto_input_log.xlsx'}")
        return

    parsed_rows = parse_load_rows(raw_rows)
    classified_rows = classify_loads(
        parsed_rows,
        mapping_path=mapping_path,
        settings_path=settings_path,
    )
    overrides = load_manual_overrides(CONFIG_DIR / "manual_overrides.yml")
    classified_rows = apply_manual_overrides(classified_rows, overrides)
    checked_rows, valid_rows = validate_rows(classified_rows)
    for row in checked_rows:
        row["mgtx_row_count"] = len(valid_rows)
    error_rows = [row for row in checked_rows if not row.get("is_valid_for_mgtx")]

    if valid_rows or create_empty_mgtx:
        write_mgtx_file(
            rows=valid_rows,
            mgtx_path=mgtx_path,
            encoding=encoding,
            prefix_auto_desc=prefix_auto_desc,
        )
        print(f"MGTX 파일 생성 완료: {mgtx_path}")
    else:
        for row in checked_rows:
            if not row.get("is_valid_for_mgtx") and row.get("failure_stage") in {None, "", "SUCCESS"}:
                row["failure_stage"] = "MGTX_WRITE_SKIPPED_NO_VALID_ROWS"
                row["failure_reason"] = "유효한 Floor Load Type이 없어 MGTX 파일을 생성하지 않았습니다."
        if mgtx_path.exists():
            mgtx_path.unlink()
        print("MGTX로 생성 가능한 하중 항목이 없습니다.")

    write_log_files(checked_rows, error_rows, OUTPUT_DIR)

    check_warning_count = sum(
        1 for row in checked_rows
        if row.get("service_check_ok") is False or row.get("factored_check_ok") is False
    )

    print("========================================")
    print(f"전체 후보 수: {len(raw_rows)}")
    print(f"분석 후 하중 성분 수: {len(checked_rows)}")
    print(f"MGTX 생성 항목 수: {len(valid_rows)}")
    print(f"제외 항목 수: {len(error_rows)}")
    print(f"계산식 확인 필요 항목 수: {check_warning_count}")
    created_cases = sorted({
        row.get("load_case_name")
        for row in valid_rows
        if row.get("load_case_name")
    })
    print(f"생성할 Load Case: {created_cases}")
    print(f"로그 파일: {OUTPUT_DIR / 'auto_input_log.xlsx'}")
    print(f"JSON 로그: {OUTPUT_DIR / 'auto_input_log.json'}")
    print(f"오류 로그: {OUTPUT_DIR / 'error_log.txt'}")
    print("MIDAS NX에서 output/midas_auto_define_floor_load_type.mgtx 파일을 Import 하세요.")
    print("========================================")


if __name__ == "__main__":
    main()
