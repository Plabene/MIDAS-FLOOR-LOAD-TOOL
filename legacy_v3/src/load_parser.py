import itertools
import re
from collections import defaultdict

from load_table_context import classify_structural_load_type, evaluate_floor_load_context
from unit_normalizer import convert_to_kn_per_m2 as normalize_value_to_kn_m2
from unit_normalizer import UNIT_PATTERN, normalize_load_value, normalize_unit_text
NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z가-힣/])(?:[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?)(?![A-Za-z가-힣/])"
)

DETAIL_DEAD_KEYWORDS = ["마감", "방수", "누름", "천장", "천정", "단열", "토피", "무근"]
EXCLUDE_NOTE_KEYWORDS = ["경량칸막이", "경량 칸막이", "노트", "NOTE", "참고"]
SLAB_KEYWORDS = ["SLAB", "S1AB", "5LAB", "슬래브", "슬라브", "바닥", "바닥판", "FLOOR SLAB"]
FRAME_KEYWORDS = ["골조"]
TOTAL_KEYWORDS = ["합계", "소계", "TOTAL"]
ROOF_EXCEPTION_KEYWORDS = [
    "경량 지붕",
    "경량지붕",
    "LIGHTWEIGHT ROOF",
    "LIGHT ROOF",
    "철골지붕",
    "금속지붕",
    "지붕마감",
    "태양광 지붕",
    "태양광지붕",
    "지붕층",
    "지붕",
    "ROOF",
    "옥상",
    "태양광",
    "PV",
    "SOLAR",
]
FOUNDATION_KEYWORDS = [
    "기초",
    "기초하중",
    "기초부",
    "매트",
    "MAT",
    "RAFT",
    "풋팅",
    "FOOTING",
    "파일",
    "PILE",
    "지중보",
    "FOUNDATION",
    "PILE CAP",
    "말뚝",
    "기초판",
]
FINAL_DEAD_TOTAL_KEYWORDS = [
    "최종 고정합계하중",
    "최종 고정하중",
    "고정하중 합계",
    "고정합계",
    "DL 합계",
    "D.L 합계",
    "DEAD LOAD TOTAL",
    "TOTAL DEAD LOAD",
]


def normalize_unit(unit):
    return normalize_unit_text(unit)


def convert_to_kn_per_m2(value, unit):
    return normalize_value_to_kn_m2(value, unit)


def _parse_float(text):
    try:
        return float(str(text).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _numbers_from_text(text):
    return [_parse_float(value) for value in NUMBER_PATTERN.findall(str(text or "")) if _parse_float(value) is not None]


def _first_number(text):
    numbers = _numbers_from_text(text)
    return numbers[0] if numbers else None


def _find_unit(raw_text, cells):
    unit_match = UNIT_PATTERN.search(raw_text)
    if unit_match:
        return normalize_unit(unit_match.group(0))
    for cell in cells:
        unit_match = UNIT_PATTERN.search(str(cell or ""))
        if unit_match:
            return normalize_unit(unit_match.group(0))
    return None


def _contains(text, keywords):
    upper_text = str(text or "").upper()
    return any(keyword.upper() in upper_text for keyword in keywords)


def _apply_context_fields(parsed, raw_text):
    context = evaluate_floor_load_context(raw_text)
    existing_slab_keywords = list(parsed.get("detected_slab_keywords") or [])
    merged_slab_keywords = sorted(set(existing_slab_keywords + list(context["detected_slab_keywords"] or [])))
    parsed.update({
        "detected_slab_keywords": merged_slab_keywords,
        "detected_floor_keywords": context["detected_floor_keywords"],
        "detected_roof_keywords": context["detected_roof_keywords"],
        "detected_foundation_keywords": context["detected_foundation_keywords"],
        "detected_load_keywords": context["detected_load_keywords"],
        "floor_context_score": max(int(parsed.get("floor_context_score") or 0), int(context["floor_context_score"] or 0)),
        "foundation_context_score": context["foundation_context_score"],
        "floor_load_inclusion_status": context["floor_load_inclusion_decision"],
        "review_flag": bool(parsed.get("review_flag")) or context["review_flag"],
        "structural_load_type": classify_structural_load_type(raw_text),
    })
    parsed["has_slab_context"] = bool(parsed.get("has_slab_context") or merged_slab_keywords)
    warnings = list(parsed.get("warnings") or [])
    for warning in context.get("warnings", []):
        if warning not in warnings:
            warnings.append(warning)
    parsed["warnings"] = warnings


def _apply_unit_fields(parsed, value, unit):
    unit_info = normalize_load_value(value, unit)
    parsed.update(unit_info)
    if unit_info.get("unit_normalization_warning"):
        warnings = list(parsed.get("warnings") or [])
        if unit_info["unit_normalization_warning"] not in warnings:
            warnings.append(unit_info["unit_normalization_warning"])
        parsed["warnings"] = warnings
        parsed["review_flag"] = True


def _role_for_component(component_type, raw_text=""):
    if component_type == "dead_load":
        return "DEAD_DETAIL"
    if component_type == "live_load":
        return "LIVE_LOAD"
    if component_type == "service_load":
        return "SERVICE_LOAD"
    if component_type == "factored_load":
        return "FACTORED_LOAD"
    text = str(raw_text or "").upper()
    if any(token in text for token in ["1.2", "1.6", "FACTORED", "계수"]):
        return "FORMULA_TEXT"
    if any(token in text for token in ["SERVICE", "사용하중"]):
        return "SERVICE_LOAD"
    return "UNKNOWN"


def _column_role_from_text(text):
    kind = _column_kind(text)
    if kind == "dead_load":
        return "DEAD_LOAD"
    if kind == "live_load":
        return "LIVE_LOAD"
    if kind == "service_load":
        return "SERVICE_LOAD"
    if kind == "factored_load":
        return "FACTORED_LOAD"
    if kind == "thickness":
        return "THICKNESS"
    return ""


def _column_kind(text):
    upper = str(text or "").upper()
    if any(token in upper for token in ["THK", "두께", "두 께", "T="]):
        return "thickness"
    if any(token in upper for token in ["계수", "FACTORED", "ULTIMATE", "강도"]):
        return "factored_load"
    if any(token in upper for token in ["사용", "SERVICE"]):
        return "service_load"
    if any(token in upper for token in ["골조 활", "골조LIVE", "활하중", "LIVE", "LL", "적재"]):
        return "live_load"
    if any(token in upper for token in ["골조 고정", "고정", "사하중", "DEAD", "DL"]):
        return "dead_load"
    return None


def _analyze_by_header(cells, header):
    result = {}
    if not cells or not header:
        return result

    for index in range(min(len(cells), len(header))):
        kind = _column_kind(header[index])
        value = _first_number(cells[index])
        if kind and kind != "thickness" and value is not None:
            result[kind] = value

    if result.get("dead_load") is None and result.get("service_load") is not None and result.get("live_load") is not None:
        dead = round(float(result["service_load"]) - float(result["live_load"]), 6)
        if dead > 0:
            result["dead_load"] = dead
            result["dead_load_source"] = "SERVICE_MINUS_LIVE_FROM_SUMMARY"

    header_text = " ".join(str(item or "") for item in header).upper()
    has_load_table_labels = (
        any(token in header_text for token in ["고정", "DEAD", "DL"])
        and any(token in header_text for token in ["활", "LIVE", "LL"])
        and any(token in header_text for token in ["사용", "SERVICE"])
        and any(token in header_text for token in ["계수", "FACTORED", "ULTIMATE"])
    )
    if has_load_table_labels and "dead_load" not in result:
        thk_index = None
        for index, item in enumerate(header):
            if _column_kind(item) == "thickness":
                thk_index = index
                break
        if thk_index is not None:
            ordered_kinds = ["dead_load", "live_load", "service_load", "factored_load"]
            value_cells = cells[thk_index + 1:thk_index + 1 + len(ordered_kinds)]
            for kind, cell in zip(ordered_kinds, value_cells):
                value = _first_number(cell)
                if value is not None:
                    result.setdefault(kind, value)

    return result


def _formula_error(expected, actual):
    if expected is None or actual is None:
        return None
    return abs(expected - actual)


def _is_close(expected, actual, tolerance=0.08):
    error = _formula_error(expected, actual)
    if error is None:
        return False
    return error <= max(tolerance, abs(expected) * 0.015)


def _infer_by_formula(numbers):
    usable = [number for number in numbers if number is not None and number >= 0]
    if len(usable) < 4:
        return {}

    best = None
    for dl, ll, service, factored in itertools.permutations(usable, 4):
        service_expected = dl + ll
        factored_expected = 1.2 * dl + 1.6 * ll
        score = abs(service_expected - service) + abs(factored_expected - factored)
        if best is None or score < best["score"]:
            best = {
                "dead_load": dl,
                "live_load": ll,
                "service_load": service,
                "factored_load": factored,
                "service_expected": service_expected,
                "factored_expected": factored_expected,
                "score": score,
            }

    if best and _is_close(best["service_expected"], best["service_load"]) and _is_close(best["factored_expected"], best["factored_load"]):
        return best
    return {}


def _analyze_load_table(row):
    raw_text = str(row.get("raw_text") or "")
    cells = row.get("table_cells") or []
    header = row.get("table_header") or []
    unit = _find_unit(raw_text, list(cells) + list(header)) or row.get("inferred_unit") or row.get("page_unit")
    warnings = []

    analysis = _analyze_by_header(cells, header)
    numbers = []
    for cell in cells or [raw_text]:
        numbers.extend(_numbers_from_text(cell))

    inferred = _infer_by_formula(numbers)
    for key, value in inferred.items():
        analysis.setdefault(key, value)

    dead = analysis.get("dead_load")
    live = analysis.get("live_load")
    service = analysis.get("service_load")
    factored = analysis.get("factored_load")

    if dead is not None and live is not None:
        service_expected = dead + live
        factored_expected = 1.2 * dead + 1.6 * live
        analysis["service_expected"] = service_expected
        analysis["factored_expected"] = factored_expected
        if service is not None:
            analysis["service_check_ok"] = _is_close(service_expected, service)
            if not analysis["service_check_ok"]:
                warnings.append(f"사용하중 검산 불일치: DL+LL={service_expected:.3f}, 표기값={service:.3f}")
        if factored is not None:
            analysis["factored_check_ok"] = _is_close(factored_expected, factored)
            if not analysis["factored_check_ok"]:
                warnings.append(f"계수하중 검산 불일치: 1.2DL+1.6LL={factored_expected:.3f}, 표기값={factored:.3f}")

    if not analysis and numbers:
        analysis["selected_total_load"] = numbers[-1]
        warnings.append("표 구조를 확정하지 못해 마지막 숫자를 후보 하중값으로 사용")

    if unit is None and analysis:
        warnings.append("단위가 불명확하여 자동 입력에서 검토/제외 대상입니다.")

    analysis["analysis_method"] = "header_or_formula" if analysis else "single_value"
    return analysis, unit, warnings


def _table_scope_key(row):
    source_index = str(row.get("source_index") or "")
    table_no = source_index.split("-", 1)[0] if "-" in source_index else source_index
    return f"{row.get('source_pdf')}|{row.get('source_page')}|{row.get('source_type')}|{table_no}"


def _usage_group_key(row):
    usage = row.get("floor_usage_name") or row.get("source_index")
    return f"{_table_scope_key(row)}|{usage}"


def _component_row(row, component_type, value, unit, analysis, extra_warnings):
    raw_text = str(row.get("raw_text") or "")
    parsed = dict(row)
    warnings = list(parsed.get("warnings") or []) + list(extra_warnings)
    converted = convert_to_kn_per_m2(value, unit)
    parsed.update({
        "table_scope_key": _table_scope_key(row),
        "floor_load_group_key": _usage_group_key(row),
        "load_component_type": component_type,
        "forced_category": "dead" if component_type == "dead_load" else "live",
        "load_value_role": _role_for_component(component_type, raw_text),
        "column_role": _role_for_component(component_type, raw_text),
        "load_item": f"{raw_text} [{component_type}]",
        "load_value": value,
        "unit": unit,
        "load_value_kn_per_m2": converted,
        "table_analysis": analysis,
        "analysis_method": analysis.get("analysis_method"),
        "service_load": analysis.get("service_load"),
        "factored_load": analysis.get("factored_load"),
        "service_expected": analysis.get("service_expected"),
        "factored_expected": analysis.get("factored_expected"),
        "service_check_ok": analysis.get("service_check_ok"),
        "factored_check_ok": analysis.get("factored_check_ok"),
        "is_frame_load": _contains(raw_text, FRAME_KEYWORDS),
        "is_total_load": _contains(raw_text, TOTAL_KEYWORDS),
        "is_slab_load": _contains(raw_text, SLAB_KEYWORDS),
        "is_note_load": _contains(raw_text, EXCLUDE_NOTE_KEYWORDS),
        "is_dead_detail_load": _contains(raw_text, DETAIL_DEAD_KEYWORDS),
        "has_slab_context": bool(
            parsed.get("has_slab_context")
            or parsed.get("detected_slab_keywords")
            or (parsed.get("analysis_method") in {"ocr_summary_table_block", "ocr_summary_line_alias"} and parsed.get("table_block_is_load_table"))
        ),
        "has_roof_exception": None,
        "has_foundation_keyword": None,
        "floor_load_inclusion_decision": "",
        "floor_load_inclusion_reason": "",
        "exclude_from_mgtx": bool(parsed.get("exclude_from_mgtx")),
        "exclusion_reason": parsed.get("exclusion_reason") or parsed.get("exclude_reason") or "",
        "load_selection_rule": "",
        "pdf_final_dead_load": None,
        "calculated_dead_detail_sum": None,
        "dead_load_difference": None,
        "dead_load_check_ok": None,
        "suspected_reason": "",
        "dl_value_used_for_mgtx": None,
        "dl_value_source": parsed.get("dl_value_source") or "UNKNOWN",
        "errors": list(parsed.get("errors") or []),
        "warnings": warnings,
    })
    _apply_unit_fields(parsed, value, unit)
    _apply_context_fields(parsed, raw_text)
    return parsed


def _make_unparsed_row(row, selected_value, unit, analysis, warnings):
    raw_text = str(row.get("raw_text") or "")
    parsed = dict(row)
    parsed.update({
        "table_scope_key": _table_scope_key(row),
        "floor_load_group_key": _usage_group_key(row),
        "load_component_type": "selected_total_load",
        "load_value_role": _role_for_component("selected_total_load", raw_text),
        "column_role": _column_role_from_text(" ".join(str(item or "") for item in (row.get("table_header") or []))),
        "load_item": row.get("raw_text") or "",
        "load_value": selected_value,
        "unit": unit,
        "load_value_kn_per_m2": convert_to_kn_per_m2(selected_value, unit),
        "table_analysis": analysis,
        "analysis_method": analysis.get("analysis_method"),
        "service_load": analysis.get("service_load"),
        "factored_load": analysis.get("factored_load"),
        "service_expected": analysis.get("service_expected"),
        "factored_expected": analysis.get("factored_expected"),
        "service_check_ok": analysis.get("service_check_ok"),
        "factored_check_ok": analysis.get("factored_check_ok"),
        "is_frame_load": _contains(raw_text, FRAME_KEYWORDS),
        "is_total_load": _contains(raw_text, TOTAL_KEYWORDS),
        "is_slab_load": _contains(raw_text, SLAB_KEYWORDS),
        "is_note_load": _contains(raw_text, EXCLUDE_NOTE_KEYWORDS),
        "is_dead_detail_load": _contains(raw_text, DETAIL_DEAD_KEYWORDS),
        "has_slab_context": bool(
            parsed.get("has_slab_context")
            or parsed.get("detected_slab_keywords")
            or (parsed.get("analysis_method") in {"ocr_summary_table_block", "ocr_summary_line_alias"} and parsed.get("table_block_is_load_table"))
        ),
        "has_roof_exception": None,
        "has_foundation_keyword": None,
        "floor_load_inclusion_decision": "",
        "floor_load_inclusion_reason": "",
        "exclude_from_mgtx": bool(parsed.get("exclude_from_mgtx")),
        "exclusion_reason": parsed.get("exclusion_reason") or parsed.get("exclude_reason") or "",
        "load_selection_rule": "",
        "pdf_final_dead_load": None,
        "calculated_dead_detail_sum": None,
        "dead_load_difference": None,
        "dead_load_check_ok": None,
        "suspected_reason": "",
        "dl_value_used_for_mgtx": None,
        "dl_value_source": parsed.get("dl_value_source") or "UNKNOWN",
        "errors": list(parsed.get("errors") or []),
        "warnings": warnings,
    })
    _apply_unit_fields(parsed, selected_value, unit)
    _apply_context_fields(parsed, raw_text)
    return parsed


def _exclude(row, reason):
    row["exclude_from_mgtx"] = True
    row["exclusion_reason"] = reason
    warnings = list(row.get("warnings") or [])
    if reason and reason not in warnings:
        warnings.append(reason)
    row["warnings"] = warnings


def _group_text(group_rows):
    parts = []
    for row in group_rows:
        parts.extend([
            row.get("raw_text") or "",
            row.get("load_item") or "",
            row.get("floor_usage_name") or "",
            " ".join(str(cell or "") for cell in (row.get("table_cells") or [])),
            " ".join(str(cell or "") for cell in (row.get("table_header") or [])),
            " ".join(str(item or "") for item in (row.get("table_block_keywords") or [])),
        ])
    return " ".join(str(part) for part in parts if part)


def _set_group_inclusion_context(group_rows):
    text = _group_text(group_rows)
    context = evaluate_floor_load_context(text)
    has_slab_context = _contains(text, SLAB_KEYWORDS)
    has_roof_exception = _contains(text, ROOF_EXCEPTION_KEYWORDS)
    has_foundation_keyword = _contains(text, FOUNDATION_KEYWORDS)
    has_slab_context = has_slab_context or bool(context.get("detected_slab_keywords")) or any(row.get("has_slab_context") for row in group_rows)
    has_roof_exception = has_roof_exception or bool(context.get("detected_roof_keywords"))
    has_foundation_keyword = has_foundation_keyword or bool(context.get("detected_foundation_keywords"))

    if has_foundation_keyword and has_roof_exception:
        decision = "INCLUDE_ROOF_WITH_FOUNDATION_WARNING"
        reason = "기초 키워드와 지붕 키워드가 동시에 감지되어 지붕 예외로 포함하되 확인 필요"
    elif has_foundation_keyword:
        decision = "EXCLUDE_FOUNDATION"
        reason = "기초 관련 키워드가 있고 지붕 예외 키워드가 없어 자동 입력 제외"
    elif has_slab_context:
        decision = "INCLUDE_SLAB_CONTEXT"
        reason = "슬래브 하중 정보가 있어 Floor Load Type 생성 대상"
    elif has_roof_exception:
        decision = "INCLUDE_ROOF_EXCEPTION"
        reason = "슬래브 하중은 없지만 지붕/경량지붕 예외 키워드가 있어 Floor Load Type 생성 대상"
    elif any(
        row.get("analysis_method") == "ocr_summary_line_alias"
        and row.get("floor_usage_name_normalization_reason") == "usage_order_missing_summary_fallback"
        for row in group_rows
    ):
        decision = "INCLUDE_CONTEXT_SCORE"
        reason = "인접 요약행과 용도 순서 문맥으로 Floor Load 후보에 포함"
    else:
        decision = "EXCLUDE_NO_SLAB_CONTEXT"
        reason = "슬래브 하중 정보가 없고 지붕 예외 키워드도 없어 기초하중 또는 비바닥하중으로 판단하여 제외"

    if decision == "EXCLUDE_NO_SLAB_CONTEXT" and context.get("floor_load_inclusion_decision") in {"INCLUDE", "REVIEW_REQUIRED"}:
        decision = "INCLUDE_CONTEXT_SCORE"
        reason = "SLAB 키워드는 없지만 하중표/층/용도 문맥 점수로 Floor Load 후보에 포함"

    for row in group_rows:
        row["has_slab_context"] = bool(has_slab_context or row.get("has_slab_context"))
        row["has_roof_exception"] = has_roof_exception
        row["has_foundation_keyword"] = has_foundation_keyword
        row["floor_load_inclusion_decision"] = decision
        row["floor_load_inclusion_reason"] = reason
        row["detected_slab_keywords"] = context.get("detected_slab_keywords")
        row["detected_floor_keywords"] = context.get("detected_floor_keywords")
        row["detected_roof_keywords"] = context.get("detected_roof_keywords")
        row["detected_foundation_keywords"] = context.get("detected_foundation_keywords")
        row["detected_load_keywords"] = context.get("detected_load_keywords")
        row["floor_context_score"] = context.get("floor_context_score")
        row["foundation_context_score"] = context.get("foundation_context_score")
        row["floor_load_inclusion_status"] = context.get("floor_load_inclusion_decision")
        row["review_flag"] = bool(row.get("review_flag")) or bool(context.get("review_flag"))
        if decision == "INCLUDE_ROOF_WITH_FOUNDATION_WARNING":
            warnings = list(row.get("warnings") or [])
            if reason not in warnings:
                warnings.append(reason)
            row["warnings"] = warnings

    return decision, reason


def _dead_value(row):
    value = row.get("load_value_kn_per_m2")
    return float(value) if value is not None else None


def _service_minus_live_dead_value(row):
    service = row.get("service_load")
    live = row.get("live_load")
    if service is None or live is None:
        analysis = row.get("table_analysis") or {}
        service = analysis.get("service_load")
        live = analysis.get("live_load")
    if service is None or live is None:
        return None
    return round(float(service) - float(live), 6)


def _sum_dead_values(rows):
    values = [_dead_value(row) for row in rows]
    values = [value for value in values if value is not None]
    return round(sum(values), 6) if values else None


def _dead_suspected_reason(difference):
    if difference is None:
        return "PDF 표 인식 오류 가능성"
    if difference > 0.01:
        return "세부 고정하중 항목 중 이미 합계에 포함된 항목이 중복 반영되었을 가능성"
    if difference < -0.01:
        return "일부 세부 고정하중 항목이 누락되었을 가능성"
    return "PDF 표 인식 오류 가능성"


def _set_dead_check_columns(group_rows, pdf_final, detail_sum, used_value, source):
    difference = None
    check_ok = None
    suspected_reason = ""
    if pdf_final is not None and detail_sum is not None:
        difference = round(detail_sum - pdf_final, 6)
        check_ok = abs(difference) <= 0.01
        if not check_ok:
            suspected_reason = _dead_suspected_reason(difference)

    for row in group_rows:
        row["pdf_final_dead_load"] = pdf_final
        row["calculated_dead_detail_sum"] = detail_sum
        row["dead_load_difference"] = difference
        row["dead_load_check_ok"] = check_ok
        row["suspected_reason"] = suspected_reason
        row["dl_value_used_for_mgtx"] = used_value
        if not row.get("dl_value_source"):
            row["dl_value_source"] = source


def _choose_single_dead_row(dead_rows, selected_row, selected_value, source, rule):
    for row in dead_rows:
        if row is selected_row:
            row["load_value"] = selected_value
            row["load_value_kn_per_m2"] = selected_value
            row["load_selection_rule"] = rule
            row["dl_value_used_for_mgtx"] = selected_value
            row["dl_value_source"] = source
            row["load_value_role"] = "DEAD_FINAL_TOTAL"
            row["column_role"] = "DEAD_FINAL_TOTAL"
        elif not row.get("exclude_from_mgtx"):
            _exclude(row, "세부 고정하중 항목은 검증용으로만 사용하고 MGTX DL 입력값 계산에서는 제외")


def _apply_selection_rules(component_rows):
    groups = defaultdict(list)
    for row in component_rows:
        groups[row.get("floor_load_group_key")].append(row)

    for group_rows in groups.values():
        decision, reason = _set_group_inclusion_context(group_rows)
        if decision in {"EXCLUDE_NO_SLAB_CONTEXT", "EXCLUDE_FOUNDATION"}:
            for row in group_rows:
                _exclude(row, reason)
            continue

        dead_rows = [row for row in group_rows if row.get("load_component_type") == "dead_load"]
        live_rows = [row for row in group_rows if row.get("load_component_type") == "live_load"]

        for row in group_rows:
            if row.get("is_note_load") and row.get("analysis_method") != "block_summary_dl_ll":
                _exclude(row, "참고용 노트/경량칸막이 하중으로 자동 입력 제외")
            if (
                row.get("is_slab_load")
                and not row.get("is_frame_load")
                and row.get("analysis_method") not in {"ocr_summary_table_block", "ocr_summary_line_alias", "block_summary_dl_ll"}
            ):
                _exclude(row, "SLAB/슬래브 하중은 골조 하중이 아니므로 자동 입력 제외")
            if (
                row.get("load_component_type") == "selected_total_load"
                and row.get("is_dead_detail_load")
                and not row.get("is_total_load")
                and not row.get("is_frame_load")
            ):
                _exclude(row, "개별 마감/상세 하중은 합계 또는 골조 하중 우선 규칙에 따라 제외")

        usable_dead = [row for row in dead_rows if not row.get("exclude_from_mgtx")]
        dead_detail_rows = [
            row for row in dead_rows
            if not row.get("is_slab_load")
            and not row.get("is_note_load")
            and not row.get("is_frame_load")
            and not _contains(row.get("raw_text") or row.get("load_item"), FINAL_DEAD_TOTAL_KEYWORDS)
            and not row.get("is_total_load")
        ]
        calculated_dead_detail_sum = _sum_dead_values(dead_detail_rows)

        final_dead_candidates = [
            row for row in usable_dead
            if _contains(row.get("raw_text") or row.get("load_item"), FINAL_DEAD_TOTAL_KEYWORDS)
        ]
        service_minus_live_candidates = [
            row for row in usable_dead
            if _service_minus_live_dead_value(row) is not None
        ]
        frame_dead_candidates = [row for row in usable_dead if row.get("is_frame_load")]
        total_dead_candidates = [row for row in usable_dead if row.get("is_total_load")]

        selected_dead_row = None
        dl_value_used = None
        dl_value_source = "UNKNOWN"
        dead_rule = ""
        pdf_final_dead_load = None

        if final_dead_candidates:
            selected_dead_row = final_dead_candidates[-1]
            dl_value_used = _dead_value(selected_dead_row)
            pdf_final_dead_load = dl_value_used
            dl_value_source = selected_dead_row.get("dl_value_source") or "SERVICE_MINUS_LIVE_FROM_OCR_SUMMARY"
            dead_rule = "고정하중: PDF 최종 고정합계하중 우선 사용"
        elif service_minus_live_candidates:
            selected_dead_row = service_minus_live_candidates[-1]
            dl_value_used = _service_minus_live_dead_value(selected_dead_row)
            pdf_final_dead_load = dl_value_used
            dl_value_source = selected_dead_row.get("dl_value_source") or "PDF_FINAL_DEAD_TOTAL"
            dead_rule = "고정하중: PDF 사용하중-활하중으로 확인된 최종 고정합계하중 사용"
        elif frame_dead_candidates:
            selected_dead_row = frame_dead_candidates[-1]
            dl_value_used = _dead_value(selected_dead_row)
            pdf_final_dead_load = dl_value_used
            dl_value_source = "FRAME_LOAD"
            dead_rule = "고정하중: 골조하중 우선 사용"
        elif total_dead_candidates:
            selected_dead_row = total_dead_candidates[-1]
            dl_value_used = _dead_value(selected_dead_row)
            pdf_final_dead_load = dl_value_used
            dl_value_source = selected_dead_row.get("dl_value_source") or "PDF_FINAL_DEAD_TOTAL"
            dead_rule = "고정하중: 고정하중 합계값 우선 사용"
        else:
            fallback_dead_candidates = [
                row for row in usable_dead
                if not row.get("is_dead_detail_load")
            ]
            if fallback_dead_candidates:
                selected_dead_row = fallback_dead_candidates[-1]
                dl_value_used = _dead_value(selected_dead_row)
            elif usable_dead:
                selected_dead_row = usable_dead[-1]
                dl_value_used = _dead_value(selected_dead_row)
            dl_value_source = "DETAIL_SUM_FALLBACK" if selected_dead_row else "UNKNOWN"
            dead_rule = "고정하중: 최종 고정합계하중이 없어 fallback 값을 사용"
            for row in usable_dead:
                warnings = list(row.get("warnings") or [])
                warning = "최종 고정합계하중을 찾지 못해 fallback 로직으로 DL 값을 선택했습니다."
                if warning not in warnings:
                    warnings.append(warning)
                row["warnings"] = warnings

        _set_dead_check_columns(
            group_rows=group_rows,
            pdf_final=pdf_final_dead_load,
            detail_sum=calculated_dead_detail_sum,
            used_value=dl_value_used,
            source=dl_value_source,
        )

        if selected_dead_row is not None and dl_value_used is not None:
            selected_dead_row["load_value_role"] = "DEAD_FINAL_TOTAL"
            selected_dead_row["column_role"] = "DEAD_FINAL_TOTAL"
            _choose_single_dead_row(
                dead_rows=usable_dead,
                selected_row=selected_dead_row,
                selected_value=dl_value_used,
                source=dl_value_source,
                rule=dead_rule,
            )
        else:
            for row in usable_dead:
                _exclude(row, "고정하중 최종 입력값을 결정하지 못해 자동 입력 제외")

        usable_live = [row for row in live_rows if not row.get("exclude_from_mgtx")]
        frame_live = [row for row in usable_live if row.get("is_frame_load")]
        if frame_live:
            selected_live_ids = {id(row) for row in frame_live}
            for row in usable_live:
                if id(row) in selected_live_ids:
                    row["load_selection_rule"] = "활하중: 골조 활하중 최우선 사용"
                else:
                    _exclude(row, "골조 활하중이 별도 기재되어 있어 다른 활하중 후보 제외")
        else:
            for row in usable_live:
                row["load_selection_rule"] = "활하중: 실용도 기준 개별 값 사용"


def parse_load_rows(rows):
    parsed_rows = []

    for row in rows:
        errors = list(row.get("errors") or [])
        warnings = list(row.get("warnings") or [])

        if row.get("source_type") == "error":
            parsed = dict(row)
            parsed.update({
                "table_scope_key": _table_scope_key(row),
                "floor_load_group_key": _usage_group_key(row),
                "load_item": "",
                "load_value": None,
                "unit": None,
                "load_value_kn_per_m2": None,
                "exclude_from_mgtx": False,
                "exclusion_reason": "",
                "load_selection_rule": "",
                "errors": errors,
                "warnings": warnings,
            })
            parsed_rows.append(parsed)
            continue

        preclassified_role = row.get("load_value_role")
        if preclassified_role in {"DEAD_FINAL_TOTAL", "LIVE_LOAD", "SERVICE_LOAD", "FACTORED_LOAD", "FORMULA_TEXT"} and row.get("load_value") is not None:
            parsed = dict(row)
            unit = row.get("unit") or row.get("inferred_unit") or row.get("page_unit")
            component_type = {
                "DEAD_FINAL_TOTAL": "dead_load",
                "LIVE_LOAD": "live_load",
                "SERVICE_LOAD": "service_load",
                "FACTORED_LOAD": "factored_load",
                "FORMULA_TEXT": "formula_text",
            }.get(preclassified_role, "unknown")
            parsed.update({
                "table_scope_key": _table_scope_key(row),
                "floor_load_group_key": row.get("floor_load_group_key") or _usage_group_key(row),
                "load_component_type": component_type,
                "forced_category": row.get("forced_category") or ("dead" if preclassified_role == "DEAD_FINAL_TOTAL" else "live" if preclassified_role == "LIVE_LOAD" else None),
                "column_role": row.get("column_role") or preclassified_role,
                "unit": unit,
                "load_value_kn_per_m2": convert_to_kn_per_m2(row.get("load_value"), unit),
                "errors": errors,
                "warnings": warnings,
                "exclude_from_mgtx": bool(row.get("exclude_from_mgtx")) or preclassified_role in {"SERVICE_LOAD", "FACTORED_LOAD", "FORMULA_TEXT"},
                "exclusion_reason": row.get("exclusion_reason") or row.get("exclude_reason") or "",
                "load_selection_rule": row.get("load_selection_rule") or "",
                "is_frame_load": _contains(row.get("raw_text"), FRAME_KEYWORDS),
                "is_total_load": _contains(row.get("raw_text"), TOTAL_KEYWORDS),
                "is_slab_load": _contains(row.get("raw_text"), SLAB_KEYWORDS),
                "is_note_load": _contains(row.get("raw_text"), EXCLUDE_NOTE_KEYWORDS),
                "is_dead_detail_load": False,
                "has_slab_context": bool(
                    row.get("has_slab_context")
                    or row.get("detected_slab_keywords")
                    or (row.get("analysis_method") in {"ocr_summary_table_block", "ocr_summary_line_alias"} and row.get("table_block_is_load_table"))
                ),
            })
            if row.get("unit_inferred"):
                warning = "OCR에서 단위를 직접 읽지 못해 하중표 문맥상 kN/m2로 추정"
                if warning not in parsed["warnings"]:
                    parsed["warnings"].append(warning)
                parsed["review_flag"] = True
            _apply_unit_fields(parsed, row.get("load_value"), unit)
            _apply_context_fields(parsed, " ".join(str(part or "") for part in [
                row.get("raw_text"),
                row.get("floor_usage_name"),
                " ".join(str(item or "") for item in (row.get("table_block_keywords") or [])),
            ]))
            parsed_rows.append(parsed)
            continue

        analysis, unit, analysis_warnings = _analyze_load_table(row)
        component_rows = []
        if analysis.get("dead_load") is not None:
            component_rows.append(_component_row(row, "dead_load", analysis["dead_load"], unit, analysis, analysis_warnings))
        if analysis.get("live_load") is not None and analysis.get("live_load") != 0:
            component_rows.append(_component_row(row, "live_load", analysis["live_load"], unit, analysis, analysis_warnings))

        if component_rows:
            parsed_rows.extend(component_rows)
            continue

        selected_value = analysis.get("selected_total_load")
        if selected_value is None:
            numbers = []
            for cell in row.get("table_cells") or [row.get("raw_text")]:
                numbers.extend(_numbers_from_text(cell))
            selected_value = numbers[-1] if numbers else None

        if unit is None:
            warnings.append("단위 미확인")

        parsed_rows.append(_make_unparsed_row(row, selected_value, unit, analysis, warnings + analysis_warnings))

    _apply_selection_rules(parsed_rows)
    return parsed_rows
