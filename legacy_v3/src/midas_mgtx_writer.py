import json
import re
from pathlib import Path
from collections import OrderedDict

import pandas as pd

from load_case_resolver import load_case_family
from name_normalizer import is_bad_floor_load_type_name, load_usage_order, normalize_floor_usage_name


LOG_COLUMNS = [
    "source_pdf", "source_page", "source_type", "source_index", "raw_text",
    "pdf_page_type", "text_layer_exists", "text_extraction_available", "ocr_required", "extraction_method",
    "extracted_text_length", "extracted_text_preview", "image_object_count",
    "page_width", "page_height", "page_rotation", "render_dpi", "ocr_available",
    "color_mode", "estimated_dpi", "scan_noise_score", "skew_angle", "margin_bbox", "contrast_score",
    "load_table_keywords_found", "number_unit_pattern_count",
    "extraction_confidence", "fallback_reason", "page_rotation_detected", "page_deskew_applied",
    "ocr_confidence", "ocr_engine", "ocr_engine_available", "tesseract_languages",
    "rendered_image_saved", "preprocessed_image_saved", "ocr_word_count", "ocr_line_count",
    "numeric_candidate_count", "unit_candidate_count", "keyword_candidate_count",
    "table_block_count", "final_candidate_row_count", "mgtx_row_count", "failure_stage", "failure_reason",
    "debug_dir", "bbox", "extraction_debug",
    "table_block_id", "table_block_keywords", "table_block_numbers", "table_block_confidence",
    "table_block_is_load_table", "estimated_unit", "inferred_unit", "unit_inferred",
    "unit_source", "parser_type", "block_order", "block_summary_detection_score",
    "block_summary_block_count", "block_summary_complete_block_count",
    "generated_dl", "generated_ll",
    "table_cells", "table_header", "floor_usage_name", "floor_load_group_key",
    "table_scope_key", "exclude_from_mgtx", "exclusion_reason", "load_selection_rule",
    "load_value_role", "column_role", "exclude_reason", "writer_level_filter_reason",
    "has_slab_context", "has_roof_exception", "has_foundation_keyword",
    "detected_slab_keywords", "detected_floor_keywords", "detected_roof_keywords",
    "detected_foundation_keywords", "detected_load_keywords", "floor_context_score",
    "foundation_context_score", "floor_load_inclusion_status",
    "floor_load_inclusion_decision", "floor_load_inclusion_reason",
    "load_item", "load_component_type", "load_value", "unit", "load_value_kn_per_m2",
    "original_value", "original_unit", "normalized_value", "normalized_unit",
    "unit_conversion_factor", "unit_normalization_warning", "structural_load_type",
    "pdf_final_dead_load", "calculated_dead_detail_sum", "dead_load_difference",
    "dead_load_check_ok", "suspected_reason", "dl_value_used_for_mgtx", "dl_value_source",
    "analysis_method", "service_load", "factored_load",
    "service_expected", "factored_expected", "service_check_ok", "factored_check_ok",
    "dl_factored", "ll_factored", "total_service", "total_factored",
    "service_total_check_ok", "factored_total_check_ok",
    "category", "load_case_name", "floor_load_type_name", "floor_load_value",
    "mgtx_load_type_code", "sub_beam_weight_include", "matched_keyword",
    "review_flag", "review_reason", "name_source", "name_normalized",
    "classification_reason", "validation_status", "validation_messages",
    "review_required_reason", "confidence_score", "is_valid_for_mgtx", "manual_override", "manual_override_action",
    "manual_override_reason", "errors", "warnings",
]


def _format_number(value):
    if value is None:
        return ""
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text == "-0" else text


def _clean_text(value):
    return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())


def _mgtx_field(value):
    text = _clean_text(value).replace('"', "'")
    if "," in text:
        return f'"{text}"'
    return text


def _safe_ascii_text(value):
    text = _clean_text(value)
    safe_chars = []
    for char in text:
        if char.isascii() and (char.isalnum() or char in " _-."):
            safe_chars.append(char)
        elif char.isspace():
            safe_chars.append(" ")
    return " ".join("".join(safe_chars).split())


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)


def _text_items(value):
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item or "").strip()]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item or "").strip()]
    text = str(value).strip()
    if not text:
        return []
    return [text]


def should_mark_desc_review(row, review_threshold=60):
    if row.get("dl_value_source") == "SERVICE_MINUS_LIVE_FROM_OCR_SUMMARY":
        return True
    if _truthy(row.get("unit_inferred")):
        return True
    if _truthy(row.get("name_normalized")):
        return True
    if row.get("name_source") == "NORMALIZED_FROM_OCR":
        return True

    confidence = row.get("confidence_score")
    if confidence is not None:
        try:
            if float(confidence) < float(review_threshold):
                return True
        except (TypeError, ValueError):
            pass

    if not row.get("review_flag"):
        return False

    review_texts = []
    for key in ("review_required_reason", "warnings", "validation_messages", "errors"):
        review_texts.extend(_text_items(row.get(key)))
    combined = " ".join(review_texts)
    if not combined:
        return False

    ignored_keywords = [
        "OCR fallback",
        "ocr fallback",
        "OCR_FALLBACK",
        "scan_ocr",
        "scan ocr",
        "스캔 OCR",
    ]
    meaningful_keywords = [
        "사용하중-활하중",
        "SERVICE_MINUS_LIVE",
        "단위 추정",
        "단위를 직접 읽지 못해",
        "단위가 없어",
        "이름 정규화",
        "NORMALIZED_FROM_OCR",
        "confidence",
        "검토 필요",
        "불일치",
    ]
    if any(keyword in combined for keyword in meaningful_keywords):
        return True
    return bool(combined) and not any(keyword in combined for keyword in ignored_keywords)


def _desc(row, prefix_auto_desc="PDF_AUTO", max_length=60, include_review=True, review_threshold=60):
    parts = [prefix_auto_desc, _safe_ascii_text(row.get("load_case_name"))]
    if row.get("source_page"):
        parts.append(f"p{row.get('source_page')}")
    if include_review and should_mark_desc_review(row, review_threshold=review_threshold):
        parts.append("REVIEW")
    return " ".join(part for part in parts if part)[:max_length]


def _stable_stldcase_desc(row, prefix_auto_desc="PDF_AUTO", max_length=60):
    return _desc(row, prefix_auto_desc=prefix_auto_desc, max_length=max_length, include_review=False)


def _representative_desc_row(group):
    sorted_group = sorted(group, key=lambda item: (_load_case_sort_key(item.get("load_case_name")), _row_order(item)))
    dl_rows = [row for row in sorted_group if load_case_family(row.get("load_case_name")) == "DL"]
    if dl_rows:
        return dl_rows[0]
    ll_rows = [row for row in sorted_group if load_case_family(row.get("load_case_name")) == "LL"]
    if ll_rows:
        return ll_rows[0]
    return sorted_group[0] if sorted_group else {}


def _group_rows_for_floor_types(rows):
    grouped_rows = []
    used_groups = set()
    for row in rows:
        group_key = row.get("floor_load_type_name") or row.get("floor_load_group_key") or row.get("load_case_name")
        if group_key in used_groups:
            continue
        group = [
            item for item in rows
            if (item.get("floor_load_type_name") or item.get("floor_load_group_key") or item.get("load_case_name")) == group_key
        ]
        used_groups.add(group_key)
        grouped_rows.append(group)
    return sorted(grouped_rows, key=_floor_type_group_sort_key)


def _as_float(value, default=999999.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _block_order(row):
    for key in ("table_block_order", "row_order", "line_order", "y_rank", "x_rank"):
        if row.get(key) is not None:
            return _as_float(row.get(key))
    block_id = str(row.get("table_block_id") or "")
    match = re.search(r"(\d+)", block_id)
    if match:
        return float(match.group(1))
    return 999999.0


def _row_order(row):
    bbox = row.get("bbox") or []
    y_value = bbox[1] if isinstance(bbox, list) and len(bbox) >= 2 else None
    x_value = bbox[0] if isinstance(bbox, list) and len(bbox) >= 1 else None
    return (
        _as_float(row.get("source_page"), 999999.0),
        _block_order(row),
        _as_float(row.get("row_order"), _as_float(row.get("row_index"), 999999.0)),
        _as_float(row.get("line_order"), _as_float(row.get("row_index"), 999999.0)),
        _as_float(row.get("y_rank"), _as_float(y_value, 999999.0)),
        _as_float(row.get("x_rank"), _as_float(x_value, 999999.0)),
        -_as_float(row.get("confidence_score"), _as_float(row.get("extraction_confidence"), 0.0)),
    )


def _floor_type_group_sort_key(group):
    order = load_usage_order()
    first = min(group, key=_row_order)
    name = first.get("floor_load_type_name")
    if name in order:
        name_rank = order.index(name)
    else:
        name_rank = 10000
    return (name_rank, _row_order(first))


def _writer_filter_reason(row):
    role = row.get("load_value_role") or "UNKNOWN"
    case_name = row.get("load_case_name")
    name = str(row.get("floor_load_type_name") or "")
    if row.get("parser_type") != "BLOCK_SUMMARY_DL_LL_TABLE":
        bad_name, name_reason = is_bad_floor_load_type_name(name)
        if bad_name:
            return f"Floor Load Type 이름이 숫자열/상세하중/OCR 잡음 중심으로 판단되어 MGTX 작성 제외: {name_reason}"
    if case_name == "DL" and role == "LIVE_LOAD":
        return "DL Load Case에 활하중 역할 값이 연결되어 MGTX 작성 제외"
    if case_name == "DL" and role != "DEAD_FINAL_TOTAL":
        return "DL은 최종 고정합계하중만 MGTX 작성 대상"
    if case_name == "LL" and role in {"SERVICE_LOAD", "FACTORED_LOAD"}:
        return "LL에 사용하중/계수하중 역할 값이 연결되어 MGTX 작성 제외"
    if case_name == "LL" and role != "LIVE_LOAD":
        return "LL은 활하중 컬럼 값만 MGTX 작성 대상"
    if role in {"SERVICE_LOAD", "FACTORED_LOAD"}:
        return "사용하중/계수하중은 검증용 값이므로 MGTX 작성 제외"
    if name.startswith("FLT_LL_ROOF") and role == "FACTORED_LOAD":
        return "자동 생성 지붕 LL 후보가 계수하중 역할이므로 MGTX 작성 제외"
    if name.startswith("FLT_DL_GENERAL") and row.get("review_flag"):
        return "REVIEW 상태의 자동 DL 일반 후보이므로 MGTX 작성 제외"
    value = row.get("floor_load_value")
    try:
        abs_value = abs(float(value)) if value is not None else None
    except (TypeError, ValueError):
        abs_value = None
    if abs_value is not None and (abs_value <= 0 or abs_value > 50):
        return "하중값이 비정상 범위로 판단되어 MGTX 작성 제외"
    return ""


def _filter_rows_for_mgtx(rows):
    filtered = []
    for row in rows:
        reason = _writer_filter_reason(row)
        if reason:
            row["writer_level_filter_reason"] = reason
            row["exclude_from_mgtx"] = True
            row["exclude_reason"] = row.get("exclude_reason") or reason
            continue
        filtered.append(row)
    return filtered


def _canonicalize_floor_type_names(rows):
    for row in rows:
        if row.get("parser_type") == "BLOCK_SUMMARY_DL_LL_TABLE":
            continue
        name = row.get("floor_load_type_name")
        canonical, reason = normalize_floor_usage_name(name)
        if canonical:
            row["floor_load_type_name"] = canonical
            if row.get("floor_usage_name"):
                usage_canonical, _usage_reason = normalize_floor_usage_name(row.get("floor_usage_name"))
                if usage_canonical:
                    row["floor_usage_name"] = usage_canonical
            row["floor_load_type_name_normalization_reason"] = reason
    return rows


def _case_value_by_name(rows, name, case_name):
    values = [
        abs(float(row.get("floor_load_value")))
        for row in rows
        if row.get("floor_load_type_name") == name
        and row.get("load_case_name") == case_name
        and row.get("floor_load_value") is not None
    ]
    return sum(values) if values else None


def _normalize_roof_solar_pair(rows):
    names = {row.get("floor_load_type_name") for row in rows}
    base_name = "지붕층"
    solar_names = [name for name in names if name and "태양광" in str(name)]
    if base_name not in names or not solar_names:
        return rows
    solar_name = sorted(solar_names, key=len)[0]
    base_dl = _case_value_by_name(rows, base_name, "DL")
    solar_dl = _case_value_by_name(rows, solar_name, "DL")
    base_ll = _case_value_by_name(rows, base_name, "LL")
    solar_ll = _case_value_by_name(rows, solar_name, "LL")
    if None in {base_dl, solar_dl, base_ll, solar_ll}:
        return rows
    if abs(base_ll - solar_ll) <= 0.01 and solar_dl < base_dl:
        for row in rows:
            if row.get("floor_load_type_name") == base_name:
                row["floor_load_type_name"] = solar_name
                if row.get("floor_usage_name") == base_name:
                    row["floor_usage_name"] = solar_name
                row["writer_level_filter_reason"] = row.get("writer_level_filter_reason", "")
                row["name_correction_reason"] = "태양광 지붕 DL이 일반 지붕보다 작게 배정되어 두 지붕 용도명을 교정"
            elif row.get("floor_load_type_name") == solar_name:
                row["floor_load_type_name"] = base_name
                if row.get("floor_usage_name") == solar_name:
                    row["floor_usage_name"] = base_name
                row["writer_level_filter_reason"] = row.get("writer_level_filter_reason", "")
                row["name_correction_reason"] = "태양광 지붕 DL이 일반 지붕보다 작게 배정되어 두 지붕 용도명을 교정"
    return rows


def _load_case_sort_key(case_name):
    family = load_case_family(case_name)
    if family == "DL":
        return 0
    if family == "LL":
        return 1
    return 2


def write_mgtx_file(rows, mgtx_path, encoding="cp949", prefix_auto_desc="PDF_AUTO", desc_review_threshold=60):
    mgtx_path = Path(mgtx_path)
    mgtx_path.parent.mkdir(parents=True, exist_ok=True)
    rows = _canonicalize_floor_type_names(list(rows or []))
    rows = _filter_rows_for_mgtx(rows)
    rows = _normalize_roof_solar_pair(rows)

    lines = [
        "; =========================================================",
        "; AUTO GENERATED BY PDF TO MIDAS FLOOR LOAD TYPE AUTOMATION",
        "; File type: MGTX",
        f"; Encoding: {encoding.upper()}",
        "; This file creates Static Load Cases and Floor Load Types.",
        "; Floor Load area assignment is intentionally skipped.",
        "; =========================================================",
        "",
        "*STLDCASE    ; Static Load Cases",
        "; LCNAME, LCTYPE, DESC",
    ]

    used_cases = set()
    for row in sorted(rows, key=lambda item: (_load_case_sort_key(item.get("load_case_name")), str(item.get("load_case_name") or ""))):
        case_name = row.get("load_case_name")
        if not case_name or case_name in used_cases:
            continue
        used_cases.add(case_name)
        lines.append(f"   {_mgtx_field(case_name)}, {row.get('mgtx_load_type_code')}, {_mgtx_field(_stable_stldcase_desc(row, prefix_auto_desc))}")

    lines.extend([
        "",
        "*FLOADTYPE    ; Define Floor Load Type",
        "; NAME, DESC                                           ; 1st line",
        "; LCNAME1, FLOAD1, bSBU1, ..., LCNAME8, FLOAD8, bSBU8  ; 2nd line",
    ])

    for group in _group_rows_for_floor_types(rows):
        first = group[0]
        desc_row = _representative_desc_row(group)
        desc = _desc(desc_row, prefix_auto_desc, review_threshold=desc_review_threshold)
        lines.append(f"   {_mgtx_field(first.get('floor_load_type_name'))}, {_mgtx_field(desc)}")
        fields = []
        combined_cases = OrderedDict()
        for row in sorted(group, key=lambda item: (_load_case_sort_key(item.get("load_case_name")), _row_order(item))):
            case_name = row.get("load_case_name")
            if not case_name:
                continue
            if case_name not in combined_cases:
                combined_cases[case_name] = {
                    "value": 0.0,
                    "sub_beam_weight_include": row.get("sub_beam_weight_include", "NO"),
                }
                combined_cases[case_name]["value"] = float(row.get("floor_load_value") or 0.0)
            if row.get("sub_beam_weight_include") == "YES":
                combined_cases[case_name]["sub_beam_weight_include"] = "YES"

        sorted_cases = sorted(
            combined_cases.items(),
            key=lambda item: (_load_case_sort_key(item[0]), item[0]),
        )
        for case_name, data in sorted_cases[:8]:
            fields.extend([
                _mgtx_field(case_name),
                _format_number(data["value"]),
                data["sub_beam_weight_include"],
            ])
        lines.append("   " + ", ".join(str(field) for field in fields))

    lines.extend([
        "",
        "; FLOORLOAD block is not generated.",
        "; Assign Floor Loads shall be performed inside MIDAS NX.",
        "",
        "*ENDDATA",
        "",
    ])

    with open(mgtx_path, "w", encoding=encoding, errors="replace", newline="") as file:
        file.write("\r\n".join(lines))
    return mgtx_path


def _stringify(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _normalize_for_log(rows):
    normalized = []
    for row in rows:
        normalized_row = {column: row.get(column) for column in LOG_COLUMNS}
        normalized_row["table_cells"] = _stringify(normalized_row.get("table_cells") or [])
        normalized_row["table_header"] = _stringify(normalized_row.get("table_header") or [])
        normalized_row["bbox"] = _stringify(normalized_row.get("bbox") or [])
        normalized_row["margin_bbox"] = _stringify(normalized_row.get("margin_bbox") or [])
        normalized_row["extraction_debug"] = _stringify(normalized_row.get("extraction_debug") or {})
        for column in [
            "detected_slab_keywords", "detected_floor_keywords", "detected_roof_keywords",
            "detected_foundation_keywords", "detected_load_keywords", "validation_messages",
            "tesseract_languages", "table_block_keywords", "table_block_numbers",
        ]:
            normalized_row[column] = _stringify(normalized_row.get(column) or [])
        normalized_row["errors"] = _stringify(normalized_row.get("errors") or [])
        normalized_row["warnings"] = _stringify(normalized_row.get("warnings") or [])
        normalized.append(normalized_row)
    return normalized


def write_log_files(all_rows, error_rows, output_dir):
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    log_rows = _normalize_for_log(all_rows)
    error_log_rows = _normalize_for_log(error_rows)

    pd.DataFrame(log_rows, columns=LOG_COLUMNS).to_excel(output_path / "auto_input_log.xlsx", index=False)

    with open(output_path / "auto_input_log.json", "w", encoding="utf-8") as file:
        json.dump(log_rows, file, ensure_ascii=False, indent=2)

    with open(output_path / "error_log.txt", "w", encoding="utf-8") as file:
        if not error_log_rows:
            file.write("MGTX 생성에서 제외된 항목이 없습니다.\n")
        else:
            for index, row in enumerate(error_log_rows, start=1):
                file.write(f"[{index}]\n")
                file.write(f"source_pdf: {row.get('source_pdf')}\n")
                file.write(f"source_page: {row.get('source_page')}\n")
                file.write(f"extraction_method: {row.get('extraction_method')}\n")
                file.write(f"failure_stage: {row.get('failure_stage')}\n")
                file.write(f"failure_reason: {row.get('failure_reason')}\n")
                file.write(f"ocr_word_count: {row.get('ocr_word_count')}\n")
                file.write(f"ocr_line_count: {row.get('ocr_line_count')}\n")
                file.write(f"numeric_candidate_count: {row.get('numeric_candidate_count')}\n")
                file.write(f"unit_candidate_count: {row.get('unit_candidate_count')}\n")
                file.write(f"keyword_candidate_count: {row.get('keyword_candidate_count')}\n")
                file.write(f"final_candidate_row_count: {row.get('final_candidate_row_count')}\n")
                file.write(f"raw_text: {row.get('raw_text')}\n")
                file.write(f"errors: {row.get('errors')}\n")
                file.write(f"warnings: {row.get('warnings')}\n\n")
