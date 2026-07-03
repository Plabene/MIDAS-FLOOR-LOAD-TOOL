from pathlib import Path

import yaml


def _load_validation_settings():
    default = {
        "allow_review_rows_in_mgtx": False,
        "allow_inferred_unit_rows_in_mgtx": True,
        "min_confidence_for_mgtx": 60,
    }
    config_path = Path(__file__).resolve().parent.parent / "config" / "midas_settings.yml"
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            settings = yaml.safe_load(file) or {}
        default.update(settings.get("ocr", {}) or {})
    except Exception:
        pass
    return default


def _append_unique(items, message):
    if message and message not in items:
        items.append(message)


def _mgtx_exclude_reason(row):
    role = row.get("load_value_role") or "UNKNOWN"
    case_name = row.get("load_case_name")
    auto_name = str(row.get("floor_load_type_name") or "")
    if row.get("exclude_from_mgtx"):
        return row.get("exclusion_reason") or row.get("exclude_reason") or "자동 입력 제외"
    if role == "SERVICE_LOAD":
        return "사용하중은 검증용 값이므로 MGTX Floor Load Type 생성 제외"
    if role == "FACTORED_LOAD":
        return "계수하중은 설계조합 검산용 값이므로 MGTX Floor Load Type 생성 제외"
    if role == "FORMULA_TEXT":
        return "계수하중 공식 텍스트는 MGTX Floor Load Type 생성 제외"
    if role == "UNKNOWN":
        return "컬럼 의미가 불명확한 숫자 후보이므로 MGTX 생성 제외"
    if case_name == "DL" and role != "DEAD_FINAL_TOTAL":
        return "DL은 최종 고정합계하중 또는 고정하중 합계만 MGTX 생성 대상"
    if case_name == "LL" and role != "LIVE_LOAD":
        return "LL은 활하중 컬럼 값만 MGTX 생성 대상"
    if auto_name.startswith("FLT_") and row.get("review_flag"):
        return "REVIEW 상태의 자동 일반 후보이므로 MGTX 생성 제외"
    return ""


def _as_float(value):
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _compute_confidence_score(row):
    score = 0.0
    method = str(row.get("extraction_method") or "")
    role = row.get("load_value_role") or "UNKNOWN"

    if method == "text_layer":
        score += 20
    elif row.get("parser_type") == "BLOCK_SUMMARY_DL_LL_TABLE":
        score += 35
    elif method:
        ocr_conf = _as_float(row.get("ocr_confidence"))
        score += min(20.0, max(0.0, (ocr_conf or 0.0) * 0.20))

    if role in {"DEAD_FINAL_TOTAL", "LIVE_LOAD"}:
        score += 25
    elif role in {"DEAD_DETAIL", "SERVICE_LOAD", "FACTORED_LOAD", "FORMULA_TEXT"}:
        score += 10

    if row.get("load_case_name") in {"DL", "LL"}:
        score += 15
    if row.get("normalized_unit") or row.get("unit"):
        score += 15
    if row.get("normalized_value") is not None or row.get("floor_load_value") is not None or row.get("load_value") is not None:
        score += 15

    if row.get("table_block_is_load_table") or row.get("table_block_count"):
        score += 20
    block_keywords = row.get("table_block_keywords") or []
    if isinstance(block_keywords, str):
        block_keywords = [block_keywords]
    important_hits = [
        item for item in block_keywords
        if any(token in str(item).upper() for token in ["SLAB", "S1AB", "5LAB", "합계", "TOTAL", "활", "LIVE", "사용", "SERVICE", "계수", "FACTORED"])
    ]
    if len(important_hits) >= 2:
        score += 20
    block_numbers = row.get("table_block_numbers") or []
    if isinstance(block_numbers, str):
        block_numbers = [block_numbers]
    if len(block_numbers) >= 2:
        score += 10
    if row.get("dl_value_source") == "SERVICE_MINUS_LIVE_FROM_OCR_SUMMARY" or row.get("generated_dl") is not None:
        score += 20
    if row.get("unit_inferred") and row.get("normalized_unit") == "kN/m2":
        score += 10
    if row.get("parser_type") == "BLOCK_SUMMARY_DL_LL_TABLE":
        score += 20
        if row.get("service_total_check_ok") is True:
            score += 5
        if row.get("factored_total_check_ok") is True:
            score += 5

    decision = row.get("floor_load_inclusion_decision") or row.get("floor_load_inclusion_status")
    if decision in {"INCLUDE", "INCLUDE_SLAB_CONTEXT", "INCLUDE_ROOF_EXCEPTION", "INCLUDE_CONTEXT_SCORE"}:
        score += 10
    elif decision == "REVIEW_REQUIRED":
        score += 4

    if row.get("dead_load_check_ok") is False or row.get("service_check_ok") is False or row.get("factored_check_ok") is False:
        score -= 10
    if row.get("review_flag"):
        score -= 10
    if row.get("exclude_from_mgtx"):
        score -= 15

    return max(0.0, min(100.0, round(score, 2)))


def validate_rows(rows):
    settings = _load_validation_settings()
    allow_review_rows = bool(settings.get("allow_review_rows_in_mgtx", False))
    allow_inferred_unit_rows = bool(settings.get("allow_inferred_unit_rows_in_mgtx", True))
    min_confidence_for_mgtx = float(settings.get("min_confidence_for_mgtx", 60))
    all_rows = []
    mgtx_rows = []

    for row in rows:
        checked = dict(row)
        errors = list(checked.get("errors") or [])
        warnings = list(checked.get("warnings") or [])

        if checked.get("source_type") == "error":
            _append_unique(errors, "PDF 처리 오류")

        if checked.get("category") not in {None, "dead", "live"}:
            _append_unique(errors, "DL/LL이 아닌 하중은 MGTX Floor Load Type 자동 입력에서 제외하고 검토 대상으로 남깁니다.")
            checked["review_flag"] = True

        if checked.get("floor_load_value") is None:
            _append_unique(errors, "하중값 없음")

        if not checked.get("load_case_name"):
            _append_unique(errors, "Load Case 이름 없음")

        if not checked.get("mgtx_load_type_code"):
            _append_unique(errors, "MGTX Load Type Code 없음")

        if not checked.get("unit"):
            _append_unique(warnings, "단위 미확인")
            checked["review_flag"] = True

        if checked.get("unit_normalization_warning"):
            _append_unique(warnings, checked.get("unit_normalization_warning"))
            checked["review_flag"] = True

        value = checked.get("normalized_value", checked.get("load_value_kn_per_m2"))
        try:
            numeric_value = float(value) if value is not None else None
        except (TypeError, ValueError):
            numeric_value = None
        if numeric_value is not None and (numeric_value < 0 or numeric_value > 50):
            _append_unique(warnings, "하중값이 음수이거나 일반적인 면하중 범위를 크게 벗어나 검토가 필요합니다.")
            checked["review_flag"] = True

        confidence = checked.get("ocr_confidence", checked.get("extraction_confidence"))
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None
        method_name = str(checked.get("extraction_method") or "")
        if (method_name.startswith("ocr") or method_name == "scan_ocr_screening") and confidence_value is not None and confidence_value < 60:
            _append_unique(warnings, "OCR 평균 confidence가 낮아 검토가 필요합니다.")
            checked["review_flag"] = True

        if checked.get("floor_load_inclusion_status") == "REVIEW_REQUIRED":
            _append_unique(warnings, "문맥상 하중표 후보이나 자동 확정 전 검토가 필요합니다.")
            checked["review_flag"] = True

        if checked.get("service_check_ok") is False:
            _append_unique(warnings, "사용하중 계산식 확인 필요")

        if checked.get("factored_check_ok") is False:
            _append_unique(warnings, "계수하중 계산식 확인 필요")

        if checked.get("dead_load_check_ok") is False:
            _append_unique(warnings, "고정하중 내부 합계와 PDF 최종 고정합계하중이 불일치합니다.")

        checked["confidence_score"] = _compute_confidence_score(checked)
        if checked["confidence_score"] < 50:
            checked["exclude_from_mgtx"] = True
            _append_unique(errors, "confidence_score 50점 미만으로 MGTX 자동 입력 제외")
        elif checked["confidence_score"] < min_confidence_for_mgtx:
            checked["exclude_from_mgtx"] = True
            checked["review_flag"] = True
            _append_unique(warnings, f"confidence_score가 MGTX 최소 기준({min_confidence_for_mgtx:g}) 미만입니다.")
        elif checked["confidence_score"] < 80:
            checked["review_flag"] = True
            if not allow_review_rows:
                checked["exclude_from_mgtx"] = True
            _append_unique(warnings, "confidence_score 50~79점으로 검토 필요")

        if checked.get("unit_inferred") and not allow_inferred_unit_rows:
            checked["exclude_from_mgtx"] = True
            _append_unique(warnings, "추정 단위 row는 설정상 MGTX 자동 입력에서 제외됩니다.")

        exclude_reason = _mgtx_exclude_reason(checked)
        if exclude_reason:
            checked["exclude_from_mgtx"] = True
            checked["exclude_reason"] = exclude_reason
            checked["exclusion_reason"] = checked.get("exclusion_reason") or exclude_reason
            _append_unique(errors, f"자동 입력 제외: {exclude_reason}")

        checked["errors"] = errors
        checked["warnings"] = warnings
        checked["is_valid_for_mgtx"] = not errors and not checked.get("exclude_from_mgtx")
        method = str(checked.get("extraction_method") or "")
        is_ocr_row = method.startswith("ocr") or method == "scan_ocr_screening"
        if not checked["is_valid_for_mgtx"] and is_ocr_row:
            if checked.get("failure_stage") in {None, "", "SUCCESS"}:
                checked["failure_stage"] = "CANDIDATES_BUT_NO_MGTX_ROWS"
                checked["failure_reason"] = checked.get("exclude_reason") or checked.get("exclusion_reason") or "OCR candidates were retained for review but excluded from MGTX."
        if checked["is_valid_for_mgtx"]:
            checked["validation_status"] = "OK"
            mgtx_rows.append(checked)
        elif checked.get("review_flag") or str(checked.get("extraction_method") or "").startswith("ocr"):
            checked["validation_status"] = "REVIEW_REQUIRED"
        else:
            checked["validation_status"] = "EXCLUDED"
        checked["validation_messages"] = warnings + errors
        checked["review_required_reason"] = "; ".join(warnings) if checked.get("review_flag") else ""
        all_rows.append(checked)

    return all_rows, mgtx_rows
