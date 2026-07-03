import re
from pathlib import Path

import fitz


PARSER_TYPE = "BLOCK_SUMMARY_DL_LL_TABLE"
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
UNIT_RE = re.compile(r"kN\s*/\s*(?:m2|m\^2|m²|㎡)", re.IGNORECASE)
BLOCK_START_RE = re.compile(r"^\s*(?P<no>\d{1,2})\s+(?P<name>.+?)\s*$")
SUMMARY_LABEL_RE = re.compile(r"^\s*(D\.L\s*\+\s*L\.L|D\.L|L\.L)\s*$", re.IGNORECASE)
DETAIL_KEYWORDS = [
    "슬래브",
    "SLAB",
    "마감",
    "천장",
    "보호몰탈",
    "방수",
    "콘크리트",
    "바닥재",
    "몰탈",
]
HEADER_KEYWORDS = [
    "실용도",
    "항 목",
    "항목",
    "두께",
    "단위중량",
    "설계 하중",
    "SERVICE",
    "FACTORED",
    "LOAD",
    "비고",
]


def _clean_line(value):
    return " ".join(str(value or "").replace("\r", " ").split())


def _is_number_line(line):
    text = _clean_line(line)
    return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text))


def _numbers(line):
    return [float(item) for item in NUMBER_RE.findall(str(line or ""))]


def _is_header_line(line):
    text = _clean_line(line).upper()
    if not text:
        return True
    return any(keyword.upper() in text for keyword in HEADER_KEYWORDS) or bool(UNIT_RE.search(text))


def _is_summary_label(line):
    return bool(SUMMARY_LABEL_RE.match(_clean_line(line)))


def _normalize_summary_label(line):
    text = re.sub(r"\s+", "", _clean_line(line)).upper()
    if text == "D.L+L.L":
        return "TOTAL"
    if text == "D.L":
        return "DL"
    if text == "L.L":
        return "LL"
    return ""


def _extract_unit(lines):
    joined = " ".join(lines)
    match = UNIT_RE.search(joined)
    if match:
        return "kN/m2", "HEADER_INHERITED"
    return None, ""


def _looks_like_block_start(lines, index):
    line = _clean_line(lines[index])
    match = BLOCK_START_RE.match(line)
    if match and not _is_header_line(match.group("name")):
        return match.group("no"), match.group("name")
    if line.isdigit() and index + 1 < len(lines):
        name = _clean_line(lines[index + 1])
        if name and not _is_number_line(name) and not _is_header_line(name) and not _is_summary_label(name):
            return line, name
    return None, None


def _collect_blocks(lines):
    blocks = []
    current = None
    index = 0
    while index < len(lines):
        number, name = _looks_like_block_start(lines, index)
        if number and name:
            if current:
                blocks.append(current)
            current = {
                "number": int(number),
                "usage_name": name,
                "lines": [str(number), name] if _clean_line(lines[index]).isdigit() else [_clean_line(lines[index])],
                "source_line_start": index + 1,
            }
            index += 2 if _clean_line(lines[index]).isdigit() else 1
            continue
        if current:
            current["lines"].append(_clean_line(lines[index]))
        index += 1
    if current:
        blocks.append(current)
    return blocks


def split_usage_blocks(lines):
    return _collect_blocks([_clean_line(line) for line in lines if _clean_line(line)])


def _merge_continued_usage_name(block):
    lines = block.get("lines") or []
    name = block.get("usage_name") or ""
    start_index = 2 if len(lines) >= 2 and _clean_line(lines[0]).isdigit() else 1
    for candidate in lines[start_index:8]:
        candidate = _clean_line(candidate)
        if _is_summary_label(candidate) or any(keyword in candidate for keyword in DETAIL_KEYWORDS):
            break
        if candidate.startswith("(") and not _is_summary_label(candidate):
            block["usage_name_original"] = name
            block["usage_name_continuation"] = candidate
            block["usage_name"] = f"{name} {candidate}".strip()
            break
    return block


def _summary_values(block_lines):
    summaries = {}
    for index, line in enumerate(block_lines):
        label = _normalize_summary_label(line)
        if not label:
            inline_numbers = _numbers(line)
            compact = re.sub(r"\s+", "", line).upper()
            if compact.startswith("D.L+L.L") and len(inline_numbers) >= 2:
                summaries["TOTAL"] = inline_numbers[:2]
            elif compact.startswith("D.L") and len(inline_numbers) >= 2:
                summaries["DL"] = inline_numbers[:2]
            elif compact.startswith("L.L") and len(inline_numbers) >= 2:
                summaries["LL"] = inline_numbers[:2]
            continue
        values = []
        for next_line in block_lines[index + 1:index + 5]:
            if _is_summary_label(next_line):
                break
            values.extend(_numbers(next_line))
            if len(values) >= 2:
                break
        if len(values) >= 2:
            summaries[label] = values[:2]
    return summaries


def _check_sum(a, b, total, tolerance=0.05):
    if a is None or b is None or total is None:
        return None
    return abs((float(a) + float(b)) - float(total)) <= tolerance


def parse_usage_block(block, page_context=None):
    page_context = page_context or {}
    block = _merge_continued_usage_name(dict(block))
    summaries = _summary_values(block.get("lines") or [])
    dl = summaries.get("DL") or []
    ll = summaries.get("LL") or []
    total = summaries.get("TOTAL") or []
    unit = page_context.get("unit") or "kN/m2"
    unit_source = page_context.get("unit_source") or "INFERRED_FROM_TABLE_CONTEXT"
    dl_service = dl[0] if len(dl) >= 1 else None
    dl_factored = dl[1] if len(dl) >= 2 else None
    ll_service = ll[0] if len(ll) >= 1 else None
    ll_factored = ll[1] if len(ll) >= 2 else None
    total_service = total[0] if len(total) >= 1 else None
    total_factored = total[1] if len(total) >= 2 else None
    service_ok = _check_sum(dl_service, ll_service, total_service)
    factored_ok = _check_sum(dl_factored, ll_factored, total_factored)
    return {
        **block,
        "unit": unit,
        "unit_source": unit_source,
        "dl_service": dl_service,
        "ll_service": ll_service,
        "dl_factored": dl_factored,
        "ll_factored": ll_factored,
        "total_service": total_service,
        "total_factored": total_factored,
        "service_total_check_ok": service_ok,
        "factored_total_check_ok": factored_ok,
        "has_detail_slab": any("슬래브" in line.upper() or "SLAB" in line.upper() for line in block.get("lines") or []),
        "has_detail_keywords": any(any(keyword.upper() in line.upper() for keyword in DETAIL_KEYWORDS) for line in block.get("lines") or []),
    }


def detect_block_summary_load_table(lines, page_context=None):
    cleaned = [_clean_line(line) for line in lines if _clean_line(line)]
    text = " ".join(cleaned)
    blocks = split_usage_blocks(cleaned)
    parsed_blocks = [parse_usage_block(block, page_context or {}) for block in blocks]
    complete_blocks = [
        block for block in parsed_blocks
        if block.get("usage_name") and block.get("dl_service") is not None and block.get("ll_service") is not None
    ]
    score = 0
    if UNIT_RE.search(text):
        score += 15
    if "SERVICE" in text.upper() and "FACTORED" in text.upper():
        score += 25
    if re.search(r"D\.L\s*\+\s*L\.L", text, re.IGNORECASE):
        score += 25
    if re.search(r"\bD\.L\b", text, re.IGNORECASE):
        score += 10
    if re.search(r"\bL\.L\b", text, re.IGNORECASE):
        score += 10
    if len(complete_blocks) >= 2:
        score += 30
    elif len(complete_blocks) == 1:
        score += 15
    if any(block.get("has_detail_keywords") for block in parsed_blocks):
        score += 10
    return {
        "parser_type": PARSER_TYPE if score >= 70 and complete_blocks else "",
        "is_detected": score >= 70 and bool(complete_blocks),
        "score": score,
        "block_count": len(blocks),
        "complete_block_count": len(complete_blocks),
        "diagnostics": {
            "has_unit_header": bool(UNIT_RE.search(text)),
            "has_service_factored_header": "SERVICE" in text.upper() and "FACTORED" in text.upper(),
            "has_dl_ll_total_rows": bool(re.search(r"D\.L\s*\+\s*L\.L", text, re.IGNORECASE)),
        },
    }


def _make_component_row(pdf_file, page_no, parsed_block, role, value, source_index):
    is_dl = role == "DEAD_FINAL_TOTAL"
    case_label = "DL" if is_dl else "LL"
    group_key = f"{Path(pdf_file).name}|p{page_no}|block_summary|{parsed_block['number']:03d}"
    check_ok = parsed_block.get("service_total_check_ok") is not False and parsed_block.get("factored_total_check_ok") is not False
    return {
        "source_pdf": Path(pdf_file).name,
        "source_page": page_no,
        "source_type": "block_summary",
        "source_index": source_index,
        "raw_text": " ".join(parsed_block.get("lines") or []),
        "table_cells": [],
        "table_header": [],
        "floor_usage_name": parsed_block.get("usage_name"),
        "floor_load_group_key": group_key,
        "table_scope_key": f"{Path(pdf_file).name}|p{page_no}|block_summary",
        "load_component_type": "dead_load" if is_dl else "live_load",
        "forced_category": "dead" if is_dl else "live",
        "load_value_role": role,
        "column_role": role,
        "load_item": f"{parsed_block.get('usage_name')} {case_label}",
        "load_value": value,
        "unit": parsed_block.get("unit") or "kN/m2",
        "load_value_kn_per_m2": value,
        "normalized_value": value,
        "normalized_unit": "kN/m2",
        "original_value": value,
        "original_unit": parsed_block.get("unit") or "kN/m2",
        "unit_conversion_factor": 1.0,
        "unit_inferred": False,
        "unit_source": parsed_block.get("unit_source"),
        "parser_type": PARSER_TYPE,
        "extraction_method": "text_layer_block_summary",
        "analysis_method": "block_summary_dl_ll",
        "table_block_id": f"block_{parsed_block['number']:03d}",
        "table_block_order": parsed_block.get("number"),
        "block_order": parsed_block.get("number"),
        "row_order": parsed_block.get("number") * 10 + (0 if is_dl else 1),
        "dl_factored": parsed_block.get("dl_factored"),
        "ll_factored": parsed_block.get("ll_factored"),
        "total_service": parsed_block.get("total_service"),
        "total_factored": parsed_block.get("total_factored"),
        "service_load": parsed_block.get("total_service"),
        "factored_load": parsed_block.get("total_factored"),
        "service_check_ok": parsed_block.get("service_total_check_ok"),
        "factored_check_ok": parsed_block.get("factored_total_check_ok"),
        "service_total_check_ok": parsed_block.get("service_total_check_ok"),
        "factored_total_check_ok": parsed_block.get("factored_total_check_ok"),
        "has_slab_context": bool(parsed_block.get("has_detail_slab") or parsed_block.get("has_detail_keywords")),
        "detected_slab_keywords": ["슬래브"] if parsed_block.get("has_detail_slab") else [],
        "floor_load_inclusion_decision": "INCLUDE_SLAB_CONTEXT",
        "floor_load_inclusion_status": "INCLUDE",
        "floor_load_inclusion_reason": "BLOCK_SUMMARY_DL_LL_TABLE context",
        "review_flag": not check_ok,
        "warnings": [] if check_ok else ["Block summary DL/LL total check requires review."],
        "errors": [],
        "extraction_confidence": 95.0,
        "exclude_from_mgtx": False,
    }


def build_floor_load_rows_from_blocks(blocks, pdf_file="", page_no=None):
    rows = []
    for parsed in blocks:
        if not parsed.get("usage_name") or parsed.get("dl_service") is None or parsed.get("ll_service") is None:
            continue
        rows.append(_make_component_row(pdf_file, page_no, parsed, "DEAD_FINAL_TOTAL", parsed["dl_service"], f"{parsed['number']}-DL"))
        rows.append(_make_component_row(pdf_file, page_no, parsed, "LIVE_LOAD", parsed["ll_service"], f"{parsed['number']}-LL"))
    return rows


def parse_block_summary_load_table(lines, page_context=None, pdf_file="", page_no=None):
    page_context = dict(page_context or {})
    unit, unit_source = _extract_unit(lines)
    if unit:
        page_context.update({"unit": unit, "unit_source": unit_source})
    blocks = [parse_usage_block(block, page_context) for block in split_usage_blocks(lines)]
    detected = detect_block_summary_load_table(lines, page_context)
    if not detected["is_detected"]:
        return [], detected
    return build_floor_load_rows_from_blocks(blocks, pdf_file=pdf_file, page_no=page_no), detected


def extract_block_summary_candidates_from_pdfs(input_dir):
    input_path = Path(input_dir)
    rows = []
    for pdf_file in sorted(input_path.glob("*.pdf")):
        try:
            with fitz.open(pdf_file) as document:
                for page_index, page in enumerate(document, start=1):
                    text = page.get_text() or ""
                    lines = [_clean_line(line) for line in text.splitlines() if _clean_line(line)]
                    page_rows, detection = parse_block_summary_load_table(lines, pdf_file=pdf_file, page_no=page_index)
                    for row in page_rows:
                        row["block_summary_detection_score"] = detection["score"]
                        row["block_summary_block_count"] = detection["block_count"]
                        row["block_summary_complete_block_count"] = detection["complete_block_count"]
                    rows.extend(page_rows)
        except Exception as exc:
            rows.append({
                "source_pdf": pdf_file.name,
                "source_page": None,
                "source_type": "error",
                "extraction_method": "text_layer_block_summary",
                "parser_type": PARSER_TYPE,
                "errors": [f"Block summary parser failed: {exc}"],
                "warnings": [],
                "exclude_from_mgtx": True,
            })
    return rows
