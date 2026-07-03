from pathlib import Path
import json
import sys
import traceback
import uuid
import zipfile
from io import BytesIO

import pandas as pd
import streamlit as st
import yaml


# =========================================================
# 경로 설정
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
SRC_DIR = BASE_DIR / "src"
CONFIG_DIR = BASE_DIR / "config"
JOBS_DIR = BASE_DIR / "jobs"

# src 폴더 안의 기존 코드를 import하기 위해 경로 추가
sys.path.insert(0, str(SRC_DIR))

from pdf_extract import extract_pdf_load_candidates
from ocr_engine import check_tesseract_available, check_tesseract_languages, get_ocr_engine_status
from load_parser import parse_load_rows
from load_classifier import classify_loads
from manual_overrides import apply_manual_overrides, load_manual_overrides
from validators import validate_rows
from midas_mgtx_writer import write_mgtx_file, write_log_files
from tools.compare_mgtx_to_reference import compare_mgtx

try:
    from floorload_assignment_builder import run_floorload_assignment_workflow
except Exception as exc:
    DXF_IMPORT_ERROR = exc
    run_floorload_assignment_workflow = None
else:
    DXF_IMPORT_ERROR = None


# =========================================================
# 기본 함수
# =========================================================

def load_yaml(path: Path) -> dict:
    """
    YAML 설정 파일을 읽습니다.
    """
    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def save_uploaded_pdfs(uploaded_files, input_dir: Path):
    """
    Streamlit에서 업로드한 PDF 파일을 작업 폴더에 저장합니다.
    """
    input_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []

    for uploaded_file in uploaded_files:
        save_path = input_dir / uploaded_file.name

        with open(save_path, "wb") as file:
            file.write(uploaded_file.getbuffer())

        saved_files.append(save_path)

    return saved_files


def make_zip_file(result_dir: Path) -> bytes:
    """
    결과 파일들을 ZIP으로 묶어서 다운로드할 수 있게 만듭니다.
    """
    memory_file = BytesIO()

    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in result_dir.rglob("*"):
            if file_path.is_file():
                zip_file.write(file_path, arcname=str(file_path.relative_to(result_dir)))

    memory_file.seek(0)
    return memory_file.read()


def make_message_zip(file_name: str, message: str) -> bytes:
    memory_file = BytesIO()
    with zipfile.ZipFile(memory_file, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(file_name, message)
    memory_file.seek(0)
    return memory_file.read()


def read_file_or_message(path: Path, message: str) -> bytes:
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    return message.encode("utf-8")


def make_excel_file_or_message(path: Path, message: str) -> bytes:
    path = Path(path)
    if path.exists():
        return path.read_bytes()
    memory_file = BytesIO()
    pd.DataFrame([{"message": message}]).to_excel(memory_file, index=False)
    memory_file.seek(0)
    return memory_file.read()


def make_streamlit_safe_value(value):
    if isinstance(value, (list, dict, set, tuple)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except Exception:
            return str(value)
    return value


def make_streamlit_safe_df(df):
    if df is None or df.empty:
        return df
    safe_df = df.copy()
    for col in safe_df.columns:
        safe_df[col] = safe_df[col].apply(make_streamlit_safe_value)
    return safe_df


def show_download_section(
    safe_project_name: str,
    output_dir: Path,
    mgtx_path: Path,
    log_xlsx_path: Path,
    error_log_path: Path,
    mgtx_row_count: int = 0,
):
    st.subheader("1. MIDAS 입력 파일 다운로드")

    if mgtx_row_count > 0 and mgtx_path and mgtx_path.exists():
        st.success("✅ 자동 변환 완료")
        st.write("MIDAS GEN NX용 MGTX 파일이 생성되었습니다.")

        with open(mgtx_path, "rb") as file:
            st.download_button(
                label="MGTX 파일 다운로드",
                data=file.read(),
                file_name=mgtx_path.name,
                mime="application/octet-stream",
                type="primary",
            )
    else:
        st.warning("⚠️ MGTX 생성 대상 없음")
        st.write("OCR은 실행되었지만 유효한 DL/LL Floor Load Type을 생성하지 못했습니다.")
        st.write("MGTX 생성 대상이 없습니다. OCR 또는 하중표 인식이 실패했거나 모든 후보가 검토/제외 처리되었습니다.")
        st.write("아래의 검토 로그와 디버그 ZIP을 다운로드해서 OCR 단계, 후보 row, 제외 사유를 확인하세요.")

    download_col1, download_col2, download_col3, download_col4 = st.columns(4)

    zip_bytes = make_zip_file(output_dir) if output_dir.exists() else make_message_zip(
        "result_not_found.txt",
        "결과 폴더가 아직 생성되지 않았습니다.",
    )
    download_col1.download_button(
        label="전체 결과 ZIP 다운로드",
        data=zip_bytes,
        file_name=f"{safe_project_name}_midas_mgtx_result.zip",
        mime="application/zip",
    )

    log_bytes = make_excel_file_or_message(
        log_xlsx_path,
        "auto_input_log.xlsx가 생성되지 않았습니다. error_log.txt를 확인하세요.",
    )
    download_col2.download_button(
        label="검토 로그 Excel 다운로드",
        data=log_bytes,
        file_name="auto_input_log.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    error_bytes = read_file_or_message(
        error_log_path,
        "error_log.txt가 생성되지 않았습니다. 변환 중 Streamlit 단계에서 예외가 발생했을 수 있습니다.",
    )
    download_col3.download_button(
        label="오류 로그 다운로드",
        data=error_bytes,
        file_name="error_log.txt",
        mime="text/plain",
    )

    debug_dirs = [BASE_DIR / "debug", BASE_DIR / "debug" / "ocr_fallback", BASE_DIR / "debug" / "scan_ocr", BASE_DIR / "debug" / "ocr_screening"]
    existing_debug_dirs = [path for path in debug_dirs if path.exists()]
    debug_zip_bytes = make_zip_file(BASE_DIR / "debug") if existing_debug_dirs else make_message_zip(
        "debug_not_found.txt",
        "debug 폴더가 아직 생성되지 않았습니다.",
    )
    download_col4.download_button(
        label="디버그 ZIP 다운로드",
        data=debug_zip_bytes,
        file_name=f"{safe_project_name}_ocr_debug.zip",
        mime="application/zip",
    )


def run_automation(input_dir: Path, output_dir: Path):
    """
    기존 main.py의 자동화 흐름을 Streamlit에서 실행합니다.

    기존 흐름:
    PDF 추출
    → 하중 파싱
    → 하중 분류
    → 유효성 검사
    → MGTX 생성
    → 로그 저장
    """

    output_dir.mkdir(parents=True, exist_ok=True)

    settings_path = CONFIG_DIR / "midas_settings.yml"
    mapping_path = CONFIG_DIR / "load_mapping.yml"

    settings = load_yaml(settings_path)
    output_file_name = settings.get("output", {}).get(
        "file_name",
        "midas_auto_define_floor_load_type.mgtx"
    )
    encoding = settings.get("output", {}).get("encoding", "cp949")
    prefix_auto_desc = settings.get("naming", {}).get("prefix_auto_desc", "PDF_AUTO")

    mgtx_path = output_dir / output_file_name

    # 1. PDF 하중 후보 추출
    raw_rows = extract_pdf_load_candidates(input_dir)

    if not raw_rows:
        diagnostic_rows = []
        for pdf_path in sorted(Path(input_dir).glob("*.pdf")):
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
                "debug_dir": str(BASE_DIR / "debug" / "ocr_fallback" / pdf_path.stem),
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
        write_log_files(diagnostic_rows, diagnostic_rows, output_dir)
        return {
            "raw_rows": [],
            "parsed_rows": [],
            "classified_rows": diagnostic_rows,
            "valid_rows": [],
            "error_rows": diagnostic_rows,
            "mgtx_path": None,
            "log_xlsx_path": output_dir / "auto_input_log.xlsx",
            "json_log_path": output_dir / "auto_input_log.json",
            "error_log_path": output_dir / "error_log.txt",
        }

    # 2. 하중표 파싱
    parsed_rows = parse_load_rows(raw_rows)

    # 3. LOAD CASE / FLOOR LOAD TYPE 분류
    classified_rows = classify_loads(
        parsed_rows,
        mapping_path=mapping_path,
        settings_path=settings_path,
    )
    overrides = load_manual_overrides(CONFIG_DIR / "manual_overrides.yml")
    classified_rows = apply_manual_overrides(classified_rows, overrides)

    # 4. MGTX 생성 가능 항목과 제외 항목 분리
    checked_rows, valid_rows = validate_rows(classified_rows)
    for row in checked_rows:
        row["mgtx_row_count"] = len(valid_rows)
    error_rows = [row for row in checked_rows if not row.get("is_valid_for_mgtx")]

    # 5. MGTX 파일 생성
    create_empty_mgtx = bool(settings.get("output", {}).get("create_empty_mgtx_when_no_rows", False))
    if valid_rows or create_empty_mgtx:
        write_mgtx_file(
            rows=valid_rows,
            mgtx_path=mgtx_path,
            encoding=encoding,
            prefix_auto_desc=prefix_auto_desc,
        )
    else:
        for row in checked_rows:
            if not row.get("is_valid_for_mgtx"):
                row["mgtx_row_count"] = 0
                if row.get("failure_stage") in {None, "", "SUCCESS"}:
                    row["failure_stage"] = "MGTX_WRITE_SKIPPED_NO_VALID_ROWS"
                    row["failure_reason"] = "유효한 Floor Load Type이 없어 MGTX 파일을 생성하지 않았습니다."
        if mgtx_path.exists():
            mgtx_path.unlink()
        mgtx_path = None

    # 6. 로그 저장
    write_log_files(checked_rows, error_rows, output_dir)

    return {
        "raw_rows": raw_rows,
        "parsed_rows": parsed_rows,
        "classified_rows": checked_rows,
        "valid_rows": valid_rows,
        "error_rows": error_rows,
        "mgtx_path": mgtx_path,
        "log_xlsx_path": output_dir / "auto_input_log.xlsx",
        "json_log_path": output_dir / "auto_input_log.json",
        "error_log_path": output_dir / "error_log.txt",
    }


def dataframe_for_display(rows):
    """
    화면 표시용 DataFrame을 만듭니다.
    """
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    display_columns = [
        "source_pdf",
        "source_page",
        "pdf_page_type",
        "text_extraction_available",
        "extracted_text_length",
        "image_object_count",
        "color_mode",
        "estimated_dpi",
        "scan_noise_score",
        "skew_angle",
        "ocr_required",
        "ocr_engine_available",
        "tesseract_languages",
        "rendered_image_saved",
        "preprocessed_image_saved",
        "ocr_word_count",
        "ocr_line_count",
        "numeric_candidate_count",
        "unit_candidate_count",
        "keyword_candidate_count",
        "table_block_count",
        "final_candidate_row_count",
        "mgtx_row_count",
        "failure_stage",
        "failure_reason",
        "extraction_method",
        "parser_type",
        "source_type",
        "floor_usage_name",
        "floor_load_group_key",
        "block_order",
        "block_summary_detection_score",
        "has_slab_context",
        "has_roof_exception",
        "has_foundation_keyword",
        "floor_load_inclusion_decision",
        "floor_load_inclusion_reason",
        "exclude_from_mgtx",
        "exclude_reason",
        "writer_level_filter_reason",
        "load_value_role",
        "column_role",
        "load_item",
        "load_component_type",
        "load_value",
        "unit",
        "original_value",
        "original_unit",
        "normalized_value",
        "normalized_unit",
        "ocr_confidence",
        "dpi",
        "preprocess_candidate_name",
        "ocr_engine",
        "similarity_score",
        "confidence_score",
        "table_block_id",
        "table_block_keywords",
        "table_block_numbers",
        "table_block_confidence",
        "table_block_is_load_table",
        "estimated_unit",
        "inferred_unit",
        "unit_inferred",
        "unit_source",
        "generated_dl",
        "generated_ll",
        "row_index",
        "col_index",
        "bbox",
        "extraction_confidence",
        "fallback_reason",
        "load_value_kn_per_m2",
        "pdf_final_dead_load",
        "calculated_dead_detail_sum",
        "dead_load_difference",
        "dead_load_check_ok",
        "suspected_reason",
        "dl_value_used_for_mgtx",
        "dl_value_source",
        "service_load",
        "factored_load",
        "service_check_ok",
        "factored_check_ok",
        "dl_factored",
        "ll_factored",
        "total_service",
        "total_factored",
        "service_total_check_ok",
        "factored_total_check_ok",
        "category",
        "load_case_name",
        "floor_load_type_name",
        "floor_load_value",
        "mgtx_load_type_code",
        "sub_beam_weight_include",
        "matched_keyword",
        "review_flag",
        "validation_messages",
        "classification_reason",
        "errors",
        "warnings",
    ]

    display_columns = [col for col in display_columns if col in df.columns]

    return df[display_columns]


def inclusion_summary_dataframe(rows, decision):
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    if "floor_load_inclusion_decision" not in df.columns:
        return pd.DataFrame()

    filtered = df[df["floor_load_inclusion_decision"] == decision].copy()
    if filtered.empty:
        return pd.DataFrame()

    columns = [
        "floor_load_group_key",
        "floor_usage_name",
        "source_pdf",
        "source_page",
        "has_slab_context",
        "has_roof_exception",
        "has_foundation_keyword",
        "floor_load_inclusion_decision",
        "floor_load_inclusion_reason",
        "exclude_from_mgtx",
        "pdf_final_dead_load",
        "dl_value_used_for_mgtx",
        "dl_value_source",
        "review_flag",
        "warnings",
    ]
    columns = [column for column in columns if column in filtered.columns]
    safe_filtered = make_streamlit_safe_df(filtered[columns])
    return safe_filtered.drop_duplicates(subset=["floor_load_group_key"])



def parse_control_point_text(text):
    cad_points = []
    midas_points = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part for part in line.replace(",", " ").split() if part]
        if len(parts) != 4:
            raise ValueError("Control point rows must be: cad_x,cad_y,midas_x,midas_y")
        cad_points.append((float(parts[0]), float(parts[1])))
        midas_points.append((float(parts[2]), float(parts[3])))
    if len(cad_points) not in {0, 2} and len(cad_points) < 3:
        raise ValueError("Use 0, 2, or at least 3 control point rows.")
    return cad_points, midas_points


def save_uploaded_file(uploaded_file, save_path: Path):
    save_path.parent.mkdir(parents=True, exist_ok=True)
    with open(save_path, "wb") as file:
        file.write(uploaded_file.getbuffer())
    return save_path


def render_dxf_floorload_tab():
    st.subheader("DXF 바닥하중 배정")
    st.caption("DXF Hatch/폐합 Polyline 영역을 MGT/MGTX 층 노드 경계와 매칭해 *FLOORLOAD patch와 /db/FBLA JSON을 생성합니다.")

    if DXF_IMPORT_ERROR is not None or run_floorload_assignment_workflow is None:
        st.error(f"DXF 모듈을 불러오지 못했습니다: {DXF_IMPORT_ERROR}")
        st.info("requirements.txt의 ezdxf, shapely, scipy 설치 상태를 확인하세요.")
        return

    col_a, col_b = st.columns(2)
    with col_a:
        dxf_file = st.file_uploader("DXF 파일", type=["dxf"], key="dxf_floorload_dxf")
    with col_b:
        model_file = st.file_uploader("기준 MGT/MGTX 모델", type=["mgt", "mgtx", "txt"], key="dxf_floorload_model")

    dxf_project_name = st.text_input("DXF 배정 작업명", value="dxf_floorload_project", key="dxf_floorload_project")
    mapping_path_text = st.text_input("레이어 매핑 YAML", value=str(CONFIG_DIR / "floorload_layer_mapping.yml"), key="dxf_floorload_mapping")

    col_1, col_2, col_3 = st.columns(3)
    z_level = col_1.number_input("대상 층 Z Level", value=0.0, step=0.1, format="%.6f", key="dxf_floorload_z")
    z_tolerance = col_2.number_input("Z 허용오차", min_value=0.0, value=0.001, step=0.001, format="%.6f", key="dxf_floorload_z_tol")
    snap_tolerance = col_3.number_input("경계 노드 스냅 허용오차", min_value=0.0, value=0.5, step=0.1, format="%.6f", key="dxf_floorload_snap_tol")

    col_4, col_5, col_6 = st.columns(3)
    boundary_tolerance = col_4.number_input("내부 판정 버퍼", min_value=0.0, value=0.000001, step=0.000001, format="%.6f", key="dxf_floorload_boundary_tol")
    transform_error_limit = col_5.number_input("좌표 변환 최대오차 한계", min_value=0.0, value=0.001, step=0.001, format="%.6f", key="dxf_floorload_transform_tol")
    area_error_limit = col_6.number_input("면적 차이율 한계", min_value=0.0, value=0.20, step=0.05, format="%.4f", key="dxf_floorload_area_tol")

    control_text = st.text_area(
        "기준점 매칭",
        value="",
        placeholder="cad_x,cad_y,midas_x,midas_y\n0,0,1000,2000\n10000,0,11000,2000",
        help="비워두면 CAD XY와 MIDAS XY가 동일하다고 봅니다. 2점은 이동+균일축척+회전, 3점 이상은 affine least-squares를 사용합니다.",
        key="dxf_floorload_control_points",
    )

    col_7, col_8 = st.columns(2)
    overwrite_mode = col_7.selectbox("기존 *FLOORLOAD 처리", options=["append", "overwrite", "dedupe"], index=0, key="dxf_floorload_overwrite")
    output_encoding = col_8.text_input("Patch MGTX 인코딩", value="cp949", key="dxf_floorload_encoding")

    run_dxf = st.button("DXF 바닥하중 배정 생성", type="primary", key="dxf_floorload_run")
    if not run_dxf:
        st.info("DXF, 기준 모델, 레이어 매핑을 지정한 뒤 실행하세요.")
        return

    if not dxf_file or not model_file:
        st.warning("DXF 파일과 기준 MGT/MGTX 모델을 모두 업로드하세요.")
        return

    safe_project_name = "".join(char if char.isalnum() or char in " _-" else "_" for char in dxf_project_name).strip() or "dxf_floorload_project"
    job_id = f"{safe_project_name}_{uuid.uuid4().hex[:8]}"
    job_dir = JOBS_DIR / job_id
    input_dir = job_dir / "input"
    output_dir = job_dir / "output"

    try:
        cad_points, midas_points = parse_control_point_text(control_text)
        saved_dxf = save_uploaded_file(dxf_file, input_dir / dxf_file.name)
        saved_model = save_uploaded_file(model_file, input_dir / model_file.name)
        with st.spinner("DXF Hatch와 MGT 노드를 매칭하는 중..."):
            result = run_floorload_assignment_workflow(
                dxf_path=saved_dxf,
                model_path=saved_model,
                output_dir=output_dir,
                mapping_path=Path(mapping_path_text),
                z_level=z_level,
                z_tolerance=z_tolerance,
                cad_control_points=cad_points,
                midas_control_points=midas_points,
                transform_error_limit=transform_error_limit,
                boundary_tolerance=boundary_tolerance,
                snap_tolerance=snap_tolerance,
                area_error_limit=area_error_limit,
                overwrite_mode=overwrite_mode,
                encoding=output_encoding or "cp949",
            )
    except Exception as exc:
        st.error(f"DXF 바닥하중 배정 생성 중 오류가 발생했습니다: {exc}")
        st.code(traceback.format_exc())
        return

    summary = result.get("summary", {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("DXF 영역", result.get("hatch_count", 0))
    m2.metric("층 노드", result.get("floor_node_count", 0))
    m3.metric("생성 배정", summary.get("created_assignments", 0))
    m4.metric("검토/제외", summary.get("skipped_or_review", 0))

    st.write("좌표 변환 검토", result.get("transform_report", {}))
    if result.get("records"):
        st.dataframe(make_streamlit_safe_df(pd.DataFrame(result["records"])), use_container_width=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.download_button("Assignment JSON", data=Path(result["json_path"]).read_bytes(), file_name="floorload_assignments.json", mime="application/json")
    c2.download_button("검토 로그 Excel", data=Path(result["log_path"]).read_bytes(), file_name="floorload_assignment_log.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c3.download_button("미리보기 DXF", data=Path(result["preview_path"]).read_bytes(), file_name="floorload_assignment_preview.dxf", mime="application/dxf")
    c4.download_button("Patch MGTX", data=Path(result["patch_path"]).read_bytes(), file_name=Path(result["patch_path"]).name, mime="application/octet-stream")
    c5.download_button("전체 결과 ZIP", data=make_zip_file(output_dir), file_name=f"{safe_project_name}_dxf_floorload_result.zip", mime="application/zip")
# =========================================================
# Streamlit 화면
# =========================================================

st.set_page_config(
    page_title="MIDAS NX Floor Load Type MGTX 자동 생성기",
    layout="wide",
)

st.title("MIDAS NX Floor Load Type MGTX 자동 생성기")
st.caption("구조계산서 PDF → DL/LL 하중표 분석 → *STLDCASE + *FLOADTYPE MGTX 생성")

st.info(
    "현재 버전은 재하 영역 절점 매핑을 생략합니다. "
    "따라서 MGTX에는 *FLOORLOAD가 생성되지 않고, "
    "MIDAS NX에서 Import 후 Assign Floor Loads 위치는 MIDAS 내부에서 지정해야 합니다."
)

with st.sidebar:
    st.header("사용 방법")

    st.markdown(
        """
        1. 구조계산서 PDF 업로드  
        2. 자동 분석 실행  
        3. MGTX 다운로드  
        4. MIDAS NX에서 MGTX Import  
        5. Define Load Case / Floor Load Type 확인  
        6. MIDAS 내부에서 Assign Floor Loads 수행  
        """
    )

    st.divider()

    st.subheader("현재 설정 파일")

    st.code(str(CONFIG_DIR / "load_mapping.yml"))
    st.code(str(CONFIG_DIR / "midas_settings.yml"))

    st.divider()

    st.warning(
        "회사 공용으로 사용할 경우 구조계산서 PDF가 서버에 저장될 수 있으므로, "
        "내부망 PC 또는 회사 서버에서만 운영하는 것을 권장합니다."
    )


pdf_tab, dxf_tab = st.tabs(["PDF 하중표 자동화", "DXF 바닥하중 배정"])

with dxf_tab:
    render_dxf_floorload_tab()

with pdf_tab:
    project_name = st.text_input(
        "프로젝트명 또는 현장명",
        value="test_project",
        help="결과 폴더 이름과 ZIP 파일명에 사용됩니다."
    )

    uploaded_files = st.file_uploader(
        "구조계산서 PDF 업로드",
        type=["pdf"],
        accept_multiple_files=True,
    )

    run_button = st.button("PDF 분석 및 MGTX 생성 실행", type="primary")


    if run_button:
        if not uploaded_files:
            st.warning("먼저 PDF 파일을 업로드하세요.")
            st.stop()

        safe_project_name = "".join(
            char if char.isalnum() or char in " _-" else "_"
            for char in project_name
        ).strip() or "project"

        job_id = f"{safe_project_name}_{uuid.uuid4().hex[:8]}"

        job_dir = JOBS_DIR / job_id
        input_dir = job_dir / "input_pdfs"
        output_dir = job_dir / "output"

        job_dir.mkdir(parents=True, exist_ok=True)

        with st.spinner("PDF 파일 저장 중..."):
            saved_files = save_uploaded_pdfs(uploaded_files, input_dir)

        try:
            with st.spinner("PDF 하중표 분석 및 MGTX 생성 중..."):
                result = run_automation(input_dir, output_dir)
        except Exception as exc:
            output_dir.mkdir(parents=True, exist_ok=True)
            error_log_path = output_dir / "error_log.txt"
            log_xlsx_path = output_dir / "auto_input_log.xlsx"
            diagnostic_row = {
                "source_pdf": ", ".join(path.name for path in saved_files),
                "source_page": None,
                "extraction_method": "streamlit_exception",
                "pdf_page_type": "UNKNOWN",
                "ocr_required": True,
                "mgtx_row_count": 0,
                "review_flag": True,
                "exclude_from_mgtx": True,
                "is_valid_for_mgtx": False,
                "failure_stage": "STREAMLIT_RUNTIME_ERROR",
                "failure_reason": str(exc),
                "exclude_reason": "Streamlit 실행 중 예외가 발생해 변환을 완료하지 못했습니다.",
                "errors": [str(exc)],
                "warnings": [],
            }
            write_log_files([diagnostic_row], [diagnostic_row], output_dir)
            with open(error_log_path, "a", encoding="utf-8") as file:
                file.write("\n--- traceback ---\n")
                file.write(traceback.format_exc())
            result = {
                "raw_rows": [],
                "classified_rows": [diagnostic_row],
                "valid_rows": [],
                "error_rows": [diagnostic_row],
                "mgtx_path": None,
                "log_xlsx_path": log_xlsx_path,
                "json_log_path": output_dir / "auto_input_log.json",
                "error_log_path": error_log_path,
            }
            st.error("변환 중 오류가 발생했습니다. 아래 다운로드 버튼으로 오류 로그와 진단 파일을 받을 수 있습니다.")

        raw_rows = result["raw_rows"]
        classified_rows = result["classified_rows"]
        valid_rows = result["valid_rows"]
        error_rows = result["error_rows"]
        mgtx_path = result["mgtx_path"]
        log_xlsx_path = result["log_xlsx_path"]
        json_log_path = result["json_log_path"]
        error_log_path = result["error_log_path"]

        check_warning_count = sum(
            1 for row in classified_rows
            if row.get("service_check_ok") is False or row.get("factored_check_ok") is False
        )
        dead_check_warning_count = sum(
            1 for row in classified_rows
            if row.get("dead_load_check_ok") is False
        )

        show_download_section(
            safe_project_name=safe_project_name,
            output_dir=output_dir,
            mgtx_path=mgtx_path,
            log_xlsx_path=log_xlsx_path,
            error_log_path=error_log_path,
            mgtx_row_count=len(valid_rows),
        )

        st.divider()
        reference_mgtx = BASE_DIR / "input_pdfs" / "midas_auto_define_floor_load_type (14).mgtx"
        if mgtx_path and mgtx_path.exists() and reference_mgtx.exists():
            compare_report = compare_mgtx(reference_mgtx, mgtx_path)
            summary = compare_report.get("summary", {})
            st.subheader("PDF 2 기준과 비교한 변환 품질")
            q1, q2, q3, q4, q5 = st.columns(5)
            q1.metric("기준 항목 수", summary.get("reference_count", 0))
            q2.metric("생성 항목 수", summary.get("target_count", 0))
            q3.metric("누락 항목", summary.get("missing_count", 0))
            q4.metric("추가 항목", summary.get("extra_count", 0))
            q5.metric("순서 불일치", summary.get("order_mismatch_count", 0))
            st.write({
                "STLDCASE 순서 정상 여부": compare_report.get("stldcase_order_ok"),
                "FLOADTYPE 순서 정상 여부": compare_report.get("floadtype_order_ok"),
                "overall_pass": compare_report.get("overall_pass"),
                "누락된 Floor Load Type": compare_report.get("missing_names", []),
                "추가된 Floor Load Type": compare_report.get("extra_names", []),
                "값 불일치 항목": compare_report.get("value_mismatches", []),
                "순서 불일치 항목": compare_report.get("order_mismatches", []),
            })

        st.subheader("2. 검토 및 추출 결과")

        col1, col2, col3, col4, col5 = st.columns(5)

        col1.metric("업로드 PDF", len(saved_files))
        col2.metric("PDF 후보 수", len(raw_rows))
        col3.metric("분석 후 하중 성분 수", len(classified_rows))
        col4.metric("MGTX 생성 항목 수", len(valid_rows))
        col5.metric("제외 / 오류 항목 수", len(error_rows))

        if check_warning_count > 0:
            st.warning(f"사용하중 또는 계수하중 계산식 확인 필요 항목이 {check_warning_count}개 있습니다.")

        if dead_check_warning_count > 0:
            st.warning(f"고정하중 세부합계와 PDF 최종 고정합계하중이 불일치한 항목이 {dead_check_warning_count}개 있습니다.")

        st.subheader("Load Case 생성 검증")
        created_cases = sorted({
            row.get("load_case_name")
            for row in valid_rows
            if row.get("load_case_name")
        })
        st.write({
            "MGTX에 생성할 Load Case": created_cases,
        })

        if valid_rows:
            reference_df = pd.DataFrame(valid_rows)
            reference_columns = [
                "floor_load_type_name",
                "floor_usage_name",
                "category",
                "load_case_name",
                "floor_load_value",
            ]
            reference_columns = [column for column in reference_columns if column in reference_df.columns]
            st.dataframe(make_streamlit_safe_df(reference_df[reference_columns]), use_container_width=True)

        st.subheader("페이지별 판별 결과")
        raw_df = pd.DataFrame(raw_rows)
        page_columns = [
            "source_pdf", "source_page", "pdf_page_type", "text_extraction_available",
            "extracted_text_length", "extracted_text_preview", "image_object_count",
            "page_width", "page_height", "page_rotation", "render_dpi",
            "color_mode", "estimated_dpi", "scan_noise_score", "skew_angle", "contrast_score",
            "ocr_required", "ocr_available", "extraction_method", "dpi",
            "preprocess_candidate_name", "ocr_engine", "similarity_score", "extraction_confidence",
            "fallback_reason", "page_rotation_detected", "page_deskew_applied",
        ]
        page_columns = [column for column in page_columns if column in raw_df.columns]
        if page_columns:
            page_df = make_streamlit_safe_df(raw_df[page_columns].copy())
            st.dataframe(page_df.drop_duplicates(), use_container_width=True)

        st.subheader("추출 방식별 결과")
        if not raw_df.empty and "extraction_method" in raw_df.columns:
            method_df = raw_df["extraction_method"].value_counts(dropna=False).rename_axis("extraction_method").reset_index(name="count")
            st.dataframe(method_df, use_container_width=True)

        st.subheader("OCR 인식 품질 요약")
        ocr_status = check_tesseract_available()
        lang_status = check_tesseract_languages()
        engine_status = get_ocr_engine_status()
        st.write({
            "tesseract_available": ocr_status.get("available"),
            "tesseract_version": ocr_status.get("version"),
            "language_status": lang_status.get("message"),
            "tesseract_languages": engine_status.get("tesseract_languages"),
            "has_kor": engine_status.get("tesseract_has_kor"),
            "has_eng": engine_status.get("tesseract_has_eng"),
            "selected_ocr_language": "kor+eng" if engine_status.get("tesseract_has_kor") and engine_status.get("tesseract_has_eng") else "eng",
        })
        if not engine_status.get("tesseract_available"):
            st.error("Tesseract OCR이 설치되어 있지 않아 스캔 PDF를 인식할 수 없습니다.")
        elif not engine_status.get("tesseract_has_kor"):
            st.warning("Tesseract kor 언어팩이 없어 한글 OCR 정확도가 낮을 수 있습니다. eng OCR로 fallback합니다.")
        if not raw_df.empty and "ocr_confidence" in raw_df.columns:
            ocr_df = raw_df[raw_df["extraction_method"].isin(["ocr_fallback", "ocr_screening", "scan_ocr_screening"])].copy()
            if ocr_df.empty:
                st.info("OCR로 처리된 페이지가 없습니다.")
            else:
                ocr_columns = ["source_pdf", "source_page", "ocr_confidence", "ocr_engine", "render_dpi", "page_rotation_detected", "page_deskew_applied"]
                ocr_columns = [column for column in ocr_columns if column in ocr_df.columns]
                ocr_display_df = make_streamlit_safe_df(ocr_df[ocr_columns].copy())
                st.dataframe(ocr_display_df.drop_duplicates(), use_container_width=True)
                if valid_rows == [] and not ocr_df.empty:
                    st.warning("OCR 후보는 추출되었지만 MGTX 입력 조건을 만족하지 못했습니다. auto_input_log.xlsx에서 review_flag/exclude_reason을 확인하세요.")
                if ocr_df.empty:
                    st.warning("OCR 결과가 없습니다. Tesseract 설치, kor/eng 언어팩, 전처리 이미지를 확인하세요.")

        st.subheader("OCR 실패 진단")
        diagnostic_columns = [
            "source_pdf", "source_page", "pdf_page_type", "ocr_required",
            "text_layer_exists", "extracted_text_length", "image_object_count",
            "load_table_keywords_found", "number_unit_pattern_count",
            "ocr_engine_available", "tesseract_languages",
            "rendered_image_saved", "preprocessed_image_saved",
            "ocr_word_count", "ocr_line_count", "numeric_candidate_count",
            "unit_candidate_count", "keyword_candidate_count", "table_block_count", "final_candidate_row_count",
            "mgtx_row_count",
            "failure_stage", "failure_reason",
        ]
        diagnostic_columns = [column for column in diagnostic_columns if column in raw_df.columns]
        if diagnostic_columns:
            diagnostic_df = make_streamlit_safe_df(raw_df[diagnostic_columns].copy())
            st.dataframe(diagnostic_df.drop_duplicates(), use_container_width=True)

        st.subheader("자동 생성 결과 미리보기")

        display_df = dataframe_for_display(classified_rows)

        if display_df.empty:
            st.warning("화면에 표시할 분석 결과가 없습니다.")
        else:
            st.dataframe(make_streamlit_safe_df(display_df), use_container_width=True)

        st.subheader("표 block 진단")
        block_columns = [
            "source_pdf", "source_page", "table_block_id", "table_block_keywords",
            "table_block_numbers", "inferred_unit", "unit_inferred", "table_block_confidence",
            "confidence_score", "generated_dl", "generated_ll", "failure_reason",
        ]
        block_columns = [column for column in block_columns if column in display_df.columns]
        if block_columns and not display_df.empty:
            st.dataframe(make_streamlit_safe_df(display_df[block_columns].drop_duplicates()), use_container_width=True)

        if not display_df.empty and "dead_load_check_ok" in display_df.columns:
            dead_mismatch_df = display_df[display_df["dead_load_check_ok"] == False]
            if not dead_mismatch_df.empty:
                st.subheader("고정하중 불일치 항목")
                mismatch_columns = [
                    "source_pdf",
                    "source_page",
                    "floor_usage_name",
                    "load_item",
                    "pdf_final_dead_load",
                    "calculated_dead_detail_sum",
                    "dead_load_difference",
                    "dl_value_used_for_mgtx",
                    "dl_value_source",
                    "suspected_reason",
                    "warnings",
                ]
                mismatch_columns = [col for col in mismatch_columns if col in dead_mismatch_df.columns]
                st.dataframe(make_streamlit_safe_df(dead_mismatch_df[mismatch_columns]), use_container_width=True)

        st.subheader("Floor Load 포함 / 제외 판단")
        inclusion_sections = [
            ("슬래브 하중 정보가 있어 포함된 하중표", "INCLUDE_SLAB_CONTEXT"),
            ("슬래브는 없지만 경량 지붕/지붕마감/태양광 지붕 예외로 포함된 하중표", "INCLUDE_ROOF_EXCEPTION"),
            ("슬래브가 없고 지붕 예외도 없어 제외된 하중표", "EXCLUDE_NO_SLAB_CONTEXT"),
            ("기초 키워드가 있어 제외된 하중표", "EXCLUDE_FOUNDATION"),
            ("기초 키워드와 지붕 키워드가 동시에 감지되어 확인 필요인 하중표", "INCLUDE_ROOF_WITH_FOUNDATION_WARNING"),
        ]
        for title, decision in inclusion_sections:
            summary_df = inclusion_summary_dataframe(classified_rows, decision)
            if not summary_df.empty:
                with st.expander(f"{title} ({len(summary_df)}개)", expanded=False):
                    st.dataframe(make_streamlit_safe_df(summary_df), use_container_width=True)

        st.subheader("MGTX 생성 가능 항목")

        valid_df = dataframe_for_display(valid_rows)

        if valid_df.empty:
            st.warning("MGTX로 생성 가능한 항목이 없습니다.")
        else:
            st.dataframe(make_streamlit_safe_df(valid_df), use_container_width=True)

        if error_rows:
            st.subheader("MGTX 생성 제외 후보")
            error_df = dataframe_for_display(error_rows)
            st.dataframe(make_streamlit_safe_df(error_df), use_container_width=True)

        review_rows = [row for row in classified_rows if row.get("review_flag")]
        if review_rows:
            st.subheader("검토 필요 대상")
            st.dataframe(make_streamlit_safe_df(dataframe_for_display(review_rows)), use_container_width=True)

        st.subheader("디버그 파일 위치")
        st.code(str(BASE_DIR / "debug"))
        st.code(str(BASE_DIR / "debug" / "ocr_screening"))
        st.code(str(BASE_DIR / "debug" / "scan_ocr"))
        st.code(str(BASE_DIR / "debug" / "ocr_fallback"))
        st.caption("텍스트 추출 실패 또는 OCR fallback 페이지는 rendered, preprocessed, ocr_overlay, table_candidates, json 폴더에 중간 결과를 저장합니다.")

        st.subheader("MIDAS NX 적용 순서")

        st.markdown(
            """
            1. 위에서 생성된 `.mgtx` 파일을 다운로드합니다.  
            2. MIDAS NX를 실행합니다.  
            3. `Import`에서 MGTX 파일을 불러옵니다.  
            4. `Define Load Cases`에서 `DL`, `LL` 등 Load Case가 생성되었는지 확인합니다.  
            5. `Define Floor Load Type` 또는 `Floor Load Type Table`에서 용도별 Floor Load Type이 생성되었는지 확인합니다.  
            6. 이후 MIDAS NX 내부에서 `Assign Floor Loads`를 실행하고, 생성된 Floor Load Type을 선택해 바닥 영역에 적용합니다.  
            """
        )
    else:
        st.subheader("1. MIDAS 입력 파일 다운로드")
        st.warning("아직 MGTX 파일이 생성되지 않았습니다. PDF를 업로드하고 변환을 실행하세요.")

        st.markdown(
            """
            ## 준비 상태

            현재 프로젝트 코드 기준으로 웹앱은 다음 파일들을 사용합니다.

            ```text
            src/pdf_extract.py
            src/load_parser.py
            src/load_classifier.py
            src/validators.py
            src/midas_mgtx_writer.py
            config/load_mapping.yml
            config/midas_settings.yml
            ```

            PDF를 업로드한 뒤 **PDF 분석 및 MGTX 생성 실행** 버튼을 누르면 됩니다.
            """
        )
