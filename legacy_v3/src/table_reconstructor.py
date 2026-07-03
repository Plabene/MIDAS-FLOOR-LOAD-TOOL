import re
from pathlib import Path

from load_table_context import evaluate_floor_load_context
from name_normalizer import load_usage_order, normalize_floor_usage_name
from ocr_text_normalizer import normalize_ocr_text
from unit_normalizer import NUMBER_PATTERN, UNIT_PATTERN, VALUE_UNIT_PATTERN, extract_value_unit_pairs


LOAD_TOKEN_PATTERN = re.compile(
    r"고정하중|활하중|적재하중|풍하중|지진하중|적설하중|토압|수압|온도하중|장비하중|합계|총계|사용하중|계수하중|DEAD|LIVE|LOAD|DL|LL|TOTAL|SLAB|S1AB|5LAB|슬래브|슬라브|바닥|바닥판|FLOOR\s*SLAB|지붕|옥상|태양광|화장실|주차장|업무시설",
    re.IGNORECASE,
)
SUMMARY_HEADER_PATTERN = re.compile(r"활하중|적재하중|LIVE|L\.?L|사용하중|SERVICE|계수하중|FACTORED|ULTIMATE", re.IGNORECASE)
SUMMARY_ROLE_PATTERN = re.compile(r"활하중|적재하중|LIVE|L\.?L|사용하중|SERVICE|계수하중|FACTORED|ULTIMATE", re.IGNORECASE)
TOTAL_PATTERN = re.compile(r"최종|합계|총계|소계|TOTAL", re.IGNORECASE)
SLAB_PATTERN = re.compile(r"SLAB|S1AB|5LAB|슬래브|슬라브|바닥|바닥판|FLOOR\s*SLAB", re.IGNORECASE)
LOAD_CONTEXT_PATTERN = re.compile(
    r"고정하중|활하중|적재하중|합계|총계|사용하중|계수하중|SLAB|S1AB|5LAB|슬래브|슬라브|바닥|바닥판|지붕|옥상|태양광|화장실|주차장|업무시설|DEAD|LIVE|LOAD|DL|LL|TOTAL",
    re.IGNORECASE,
)


def _group_words_by_coordinates(words_df, y_tolerance=16):
    rows = words_df.sort_values(["y", "x"]).to_dict("records")
    lines = []
    for word in rows:
        center_y = float(word.get("y", 0)) + float(word.get("height", 0)) / 2
        target = None
        for line in lines:
            tolerance = max(y_tolerance, float(word.get("height", 0)) * 0.9)
            if abs(line["center_y"] - center_y) <= tolerance:
                target = line
                break
        if target is None:
            target = {"center_y": center_y, "words": []}
            lines.append(target)
        target["words"].append(word)
        target["center_y"] = sum(float(item.get("y", 0)) + float(item.get("height", 0)) / 2 for item in target["words"]) / len(target["words"])
    for line in lines:
        line["words"] = sorted(line["words"], key=lambda item: item.get("x", 0))
        line["text"] = normalize_ocr_text(" ".join(str(item.get("normalized_text") or item.get("text") or "") for item in line["words"]))
    return sorted(lines, key=lambda item: item["center_y"])


def group_words_into_lines(words_df, y_tolerance=16):
    if words_df is None or words_df.empty:
        return []
    if {"block_num", "line_num"}.issubset(set(words_df.columns)):
        grouped = []
        sort_cols = [col for col in ["block_num", "line_num", "y", "x"] if col in words_df.columns]
        for _, group in words_df.sort_values(sort_cols).groupby([col for col in ["block_num", "line_num"] if col in words_df.columns], sort=False):
            words = group.sort_values("x").to_dict("records")
            if not words:
                continue
            text = normalize_ocr_text(" ".join(str(item.get("normalized_text") or item.get("text") or "") for item in words))
            center_y = sum(float(item.get("y", 0)) + float(item.get("height", 0)) / 2 for item in words) / len(words)
            grouped.append({"center_y": center_y, "words": words, "text": text})
        if grouped:
            grouped = sorted(grouped, key=lambda item: item["center_y"])
            for index, item in enumerate(grouped, start=1):
                item["line_index"] = index
            avg_words = sum(len(item.get("words") or []) for item in grouped) / max(1, len(grouped))
            if avg_words >= 2.0:
                return grouped
    grouped = _group_words_by_coordinates(words_df, y_tolerance=y_tolerance)
    for index, item in enumerate(grouped, start=1):
        item["line_index"] = index
    return grouped


def infer_columns(lines, x_tolerance=45):
    starts = []
    for line in lines:
        for word in line["words"]:
            starts.append(float(word.get("x", 0)))
    columns = []
    for x in sorted(starts):
        if not columns or abs(columns[-1] - x) > x_tolerance:
            columns.append(x)
        else:
            columns[-1] = (columns[-1] + x) / 2
    return columns


def build_rows_from_ocr_words(words_df):
    lines = group_words_into_lines(words_df)
    columns = infer_columns(lines)
    rows = []
    for index, line in enumerate(lines, start=1):
        row = [""] * max(1, len(columns))
        for word in line["words"]:
            x = float(word.get("x", 0))
            column_index = min(range(len(columns)), key=lambda i: abs(columns[i] - x)) if columns else 0
            row[column_index] = (row[column_index] + " " + str(word.get("normalized_text") or word.get("text") or "")).strip()
        rows.append({"line_index": index, "cells": row, "raw_text": line["text"], "words": line["words"], "column_count": len(columns)})
    return rows


def detect_table_regions(words_df):
    if words_df is None or words_df.empty:
        return []
    mask = words_df["normalized_text"].astype(str).str.contains(
        r"kN/m2|kPa|kgf|tf|ton|DL|LL|LOAD|하중|합계|TOTAL|SLAB|슬래브",
        case=False,
        na=False,
    )
    load_like = words_df[mask]
    if load_like.empty:
        return []
    return [{
        "x": int(load_like["x"].min()),
        "y": int(load_like["y"].min()),
        "width": int((load_like["x"] + load_like["width"]).max() - load_like["x"].min()),
        "height": int((load_like["y"] + load_like["height"]).max() - load_like["y"].min()),
    }]


def extract_key_value_load_candidates(text):
    candidates = []
    for value_unit in extract_value_unit_pairs(text):
        candidates.append({
            "load_item": text,
            "load_value": value_unit["original_value"],
            "unit": value_unit["original_unit"],
            **value_unit,
        })
    return candidates


def _contains_number(text):
    return bool(NUMBER_PATTERN.search(str(text or "")))


def _header_has_load_roles(header):
    header_text = normalize_ocr_text(" ".join(str(item or "") for item in header))
    return bool(re.search(r"고정|사하중|DEAD|D\.?L|활하중|적재|LIVE|L\.?L|사용|SERVICE|계수|FACTORED|ULTIMATE", header_text, re.IGNORECASE))


def _infer_unit_from_texts(*texts):
    for text in texts:
        match = UNIT_PATTERN.search(str(text or ""))
        if match:
            return match.group(0)
    return None


def _avg_confidence(words):
    confidences = [float(word.get("confidence", 0) or 0) for word in words or []]
    return round(sum(confidences) / len(confidences), 2) if confidences else 0.0


def _numbers_from_text(text):
    text = re.sub(r"(?<=\d),(?=\d)(?!\d{2}\b)", ".", str(text or ""))
    values = []
    for item in NUMBER_PATTERN.findall(text):
        try:
            value = float(str(item).replace(",", ""))
        except ValueError:
            continue
        if 0.1 <= value <= 30:
            values.append(value)
    return values


def _summary_values_from_numbers(numbers, text=""):
    """Return live/service/factored/dead from a summary value row.

    OCR often leaves detail values such as 0.30 immediately before the
    live/service columns, or drops the factored value. Prefer plausible
    right-side summary triples, and use a nearby total only as a consistency
    check when the factored value is missing.
    """
    if re.search(r"(?<!\d)1\.[26](?!\d)", str(text or "")):
        return None
    numbers = [float(value) for value in numbers or []]
    for start in range(len(numbers) - 3, -1, -1):
        live, service, factored = numbers[start:start + 3]
        if live > 8 and live / 10.0 <= 5 and service > live / 10.0:
            live = round(live / 10.0, 3)
        if not (0.5 <= live <= 8.0):
            continue
        if service <= live or factored < service:
            continue
        dead = round(service - live, 6)
        if 0 < dead <= 30:
            return {
                "live": live,
                "service": service,
                "factored": factored,
                "dead": dead,
                "source": "SUMMARY_TRIPLE",
            }

    if TOTAL_PATTERN.search(str(text or "")) and len(numbers) >= 3:
        live, service = numbers[-2], numbers[-1]
        if 0.5 <= live <= 8.0 and service > live:
            dead = round(service - live, 6)
            for total in numbers[:-2]:
                if 0 < total <= 30 and abs(dead - total) <= 0.08:
                    return {
                        "live": live,
                        "service": service,
                        "factored": None,
                        "dead": round(total, 6),
                        "source": "TOTAL_PLUS_SERVICE_MINUS_LIVE",
                    }
    return None


def _nearby_single_totals(rows, current_index, window=2):
    totals = []
    for offset in range(1, window + 1):
        for pos in (current_index - offset, current_index + offset):
            if pos < 0 or pos >= len(rows):
                continue
            text = rows[pos].get("raw_text") or rows[pos].get("text") or ""
            values = _numbers_from_text(text)
            if len(values) == 1 and 1.0 <= values[0] <= 30:
                totals.append((values[0], text))
    return totals


def _summary_values_from_nearby_total(numbers, normalized_usage, nearby_totals):
    if not normalized_usage or len(numbers or []) < 2:
        return None
    values = [float(value) for value in numbers or []]
    best = None
    for total, _text in nearby_totals or []:
        live, service = values[-2], values[-1]
        dead = round(service - live, 6)
        if 0.5 <= live <= 8.0 and abs(dead - total) <= 0.08:
            candidate = {
                "live": live,
                "service": service,
                "factored": None,
                "dead": round(total, 6),
                "source": "NEARBY_TOTAL_PLUS_SERVICE_MINUS_LIVE",
            }
            score = 100.0 - abs(dead - total)
            if best is None or score > best[0]:
                best = (score, candidate)
        if len(values) >= 2:
            service, factored = values[-2], values[-1]
            inferred_live = round(service - total, 6)
            expected_factored = 1.2 * total + 1.6 * inferred_live
            factored_diff = abs(expected_factored - factored)
            if 0.5 <= inferred_live <= 8.0 and factored >= service and factored_diff <= 0.8:
                candidate = {
                    "live": inferred_live,
                    "service": service,
                    "factored": factored,
                    "dead": round(total, 6),
                    "source": "NEARBY_TOTAL_PLUS_SERVICE_FACTORED",
                }
                score = 90.0 - factored_diff
                if best is None or score > best[0]:
                    best = (score, candidate)
    return best[1] if best else None


def _fill_unknown_usage_from_order(rows):
    order = load_usage_order()
    if not order:
        return rows
    def value_key(group):
        live = service = dead = None
        for item in group:
            if item.get("load_value_role") == "LIVE_LOAD":
                live = item.get("load_value")
            elif item.get("load_value_role") == "SERVICE_LOAD":
                service = item.get("load_value")
            elif item.get("load_value_role") == "DEAD_FINAL_TOTAL":
                dead = item.get("load_value")
        try:
            return (round(float(live), 3), round(float(service), 3), round(float(dead), 3))
        except (TypeError, ValueError):
            return None

    used = {
        row.get("floor_usage_name")
        for row in rows
        if row.get("floor_usage_name") in order
        and row.get("floor_usage_name_normalization_reason") != "UNKNOWN_NAME"
    }
    named_value_keys = set()
    for name in used:
        group_rows = [row for row in rows if row.get("floor_usage_name") == name]
        key = value_key(group_rows)
        if key:
            named_value_keys.add(key)
    fallback_names = [name for name in order if name not in used]
    if not fallback_names:
        return rows
    seen_groups = set()
    for row in rows:
        if row.get("analysis_method") != "ocr_summary_line_alias":
            continue
        if row.get("floor_usage_name_normalization_reason") != "UNKNOWN_NAME":
            continue
        key = row.get("floor_load_group_key")
        if key in seen_groups:
            continue
        seen_groups.add(key)
        group = [item for item in rows if item.get("floor_load_group_key") == key]
        group_value_key = value_key(group)
        if group_value_key in named_value_keys:
            continue
        if not fallback_names:
            break
        name = fallback_names.pop(0)
        for item in group:
            item["floor_usage_name"] = name
            item["floor_usage_name_normalization_reason"] = "usage_order_missing_summary_fallback"
    return rows


def _enforce_usage_order_for_fallback_groups(rows):
    order = load_usage_order()
    if not order:
        return rows
    groups = []
    seen = set()
    for row in rows:
        if row.get("analysis_method") not in {"ocr_summary_table_block", "ocr_summary_line_alias"}:
            continue
        key = row.get("floor_load_group_key")
        if not key or key in seen:
            continue
        seen.add(key)
        group = [item for item in rows if item.get("floor_load_group_key") == key]
        min_row = min([int(item.get("row_index") or 999999) for item in group] or [999999])
        reasons = {item.get("floor_usage_name_normalization_reason") for item in group}
        name = next((item.get("floor_usage_name") for item in group if item.get("floor_usage_name") in order), "")
        groups.append({"key": key, "rows": group, "row_index": min_row, "reasons": reasons, "name": name})

    pointer = 0
    for group in sorted(groups, key=lambda item: item["row_index"]):
        name = group["name"]
        has_direct_alias = any(str(reason or "").startswith("alias:") for reason in group["reasons"])
        is_fallback = any(
            reason in {"usage_order_fallback", "usage_order_missing_summary_fallback", "UNKNOWN_NAME", "carry_forward"}
            for reason in group["reasons"]
        )
        if has_direct_alias and name in order:
            pointer = max(pointer, order.index(name) + 1)
            continue
        if not is_fallback:
            continue
        while pointer < len(order) and any(
            other.get("name") == order[pointer]
            and any(str(reason or "").startswith("alias:") for reason in other.get("reasons", set()))
            and other.get("row_index", 999999) < group["row_index"]
            for other in groups
        ):
            pointer += 1
        if pointer >= len(order):
            continue
        assigned = order[pointer]
        pointer += 1
        for row in group["rows"]:
            row["floor_usage_name"] = assigned
            row["floor_usage_name_normalization_reason"] = "usage_order_position_fallback"
    return rows


def _keywords_from_text(text):
    return sorted(set(match.group(0) for match in LOAD_CONTEXT_PATTERN.finditer(str(text or ""))))


def _line_height(line):
    words = line.get("words") or []
    heights = [float(word.get("height", 0) or 0) for word in words]
    return max(heights or [12.0])


def _line_bbox(line):
    return _bbox_for_words(line.get("words") or [])


def _block_bbox(lines):
    boxes = [_line_bbox(line) for line in lines]
    boxes = [box for box in boxes if box]
    if not boxes:
        return None
    return [
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    ]


def _strong_load_table_context(text, numbers):
    keywords = _keywords_from_text(text)
    role_keywords = [kw for kw in keywords if SUMMARY_ROLE_PATTERN.search(kw) or SLAB_PATTERN.search(kw) or TOTAL_PATTERN.search(kw)]
    has_slab_or_floor = bool(SLAB_PATTERN.search(str(text or "")) or re.search(r"주차장|화장실|업무시설|로비|옥상|지붕|바닥", str(text or ""), re.IGNORECASE))
    return (len(keywords) >= 2 and len(role_keywords) >= 2 and len(numbers) >= 2) or (has_slab_or_floor and len(numbers) >= 3)


def _infer_table_unit(text, numbers):
    direct = _infer_unit_from_texts(text)
    if direct:
        return direct, False, ""
    if _strong_load_table_context(text, numbers):
        return "kN/m2", True, "OCR에서 단위를 직접 읽지 못해 하중표 문맥상 kN/m2로 추정"
    return None, False, ""


def group_lines_into_table_blocks(lines, y_gap_multiplier=3.2, min_gap=24):
    blocks = []
    current = []
    previous_y = None
    previous_height = None

    for line in lines or []:
        y = float(line.get("center_y", 0) or 0)
        height = _line_height(line)
        if current and previous_y is not None:
            allowed_gap = max(min_gap, (previous_height or height) * y_gap_multiplier)
            if abs(y - previous_y) > allowed_gap:
                blocks.append(current)
                current = []
        current.append(line)
        previous_y = y
        previous_height = height
    if current:
        blocks.append(current)

    result = []
    for index, block_lines in enumerate(blocks, start=1):
        text = normalize_ocr_text(" ".join(line.get("text", "") for line in block_lines))
        numbers = _numbers_from_text(text)
        keywords = _keywords_from_text(text)
        unit, unit_inferred, unit_warning = _infer_table_unit(text, numbers)
        confidences = [_avg_confidence(line.get("words") or []) for line in block_lines]
        confidences = [value for value in confidences if value > 0]
        has_slab_or_floor = bool(SLAB_PATTERN.search(text) or re.search(r"주차장|화장실|업무시설|로비|옥상|지붕|바닥", text, re.IGNORECASE))
        compact_text = re.sub(r"\s+", "", text)
        has_fuzzy_load_header = "하중" in compact_text and ("사용" in compact_text or "계수" in compact_text or "활" in compact_text)
        is_load_table = bool(
            (len(keywords) >= 2 and len(numbers) >= 2)
            or (has_slab_or_floor and len(numbers) >= 3)
            or (has_fuzzy_load_header and len(numbers) >= 5)
        )
        result.append({
            "block_id": f"block_{index:03d}",
            "lines": block_lines,
            "text": text,
            "detected_keywords": keywords,
            "numbers": numbers,
            "estimated_unit": unit,
            "unit_inferred": unit_inferred,
            "unit_inference_warning": unit_warning,
            "avg_confidence": round(sum(confidences) / len(confidences), 2) if confidences else 0.0,
            "bbox": _block_bbox(block_lines),
            "is_load_table_block": is_load_table,
        })
    return result


def _candidate_base(source_pdf, source_page, extraction_method, block, line, suffix, raw_text, unit, unit_inferred, warning):
    context = evaluate_floor_load_context(f"{block.get('text', '')} {raw_text}")
    warnings = list(context.get("warnings") or [])
    if warning and warning not in warnings:
        warnings.append(warning)
    if unit_inferred:
        warnings.append("OCR에서 단위를 직접 읽지 못해 하중표 문맥상 kN/m2로 추정")
    return {
        "source_pdf": Path(source_pdf).name if source_pdf else "",
        "source_page": source_page,
        "source_type": "ocr",
        "source_index": f"{block['block_id']}-{suffix}",
        "row_index": line.get("line_index"),
        "col_index": None,
        "raw_text": raw_text,
        "load_item": raw_text,
        "floor_usage_name": raw_text,
        "floor_load_group_key": f"{Path(source_pdf).name}|{source_page}|ocr|{block['block_id']}|line_{line.get('line_index')}",
        "table_cells": [],
        "table_header": [],
        "bbox": _line_bbox(line),
        "ocr_confidence": _avg_confidence(line.get("words") or []) or block.get("avg_confidence") or 0.0,
        "extraction_method": extraction_method,
        "extraction_confidence": block.get("avg_confidence") or 0.0,
        "estimated_unit": unit,
        "inferred_unit": unit,
        "page_unit": unit,
        "unit_inferred": unit_inferred,
        "table_block_id": block["block_id"],
        "table_block_count": None,
        "table_block_keywords": block.get("detected_keywords") or [],
        "table_block_numbers": block.get("numbers") or [],
        "table_block_confidence": block.get("avg_confidence"),
        "table_block_is_load_table": block.get("is_load_table_block"),
        "warnings": warnings,
        "review_flag": bool(unit_inferred) or bool(context.get("review_flag", False)),
        **context,
    }


def reconstruct_summary_rows_from_block(block, source_pdf="", source_page=None, extraction_method="ocr_fallback"):
    has_numeric_lines = any(len(_numbers_from_text(line.get("text", ""))) >= 3 for line in block.get("lines") or [])
    if not block.get("is_load_table_block") and not has_numeric_lines:
        return []
    block_text = block.get("text", "")
    compact_block_text = re.sub(r"\s+", "", block_text)
    has_summary_header = bool(SUMMARY_HEADER_PATTERN.search(block_text))
    fuzzy_summary_header = (
        compact_block_text.count("하중") >= 2
        and bool(re.search(r"활|LIVE|L\.?L", compact_block_text, re.IGNORECASE))
        and bool(re.search(r"사용|SERVICE|계수|FACTORED|1\.2|1\.6|계수", compact_block_text, re.IGNORECASE))
    )
    has_slab_or_floor = bool(SLAB_PATTERN.search(block_text) or re.search(r"주차장|화장실|업무시설|로비|옥상|지붕|바닥", block_text, re.IGNORECASE))
    has_usage_alias = any(normalize_floor_usage_name(line.get("text", ""))[0] for line in block.get("lines") or [])
    numeric_summary_context = ((has_slab_or_floor or fuzzy_summary_header) and len(block.get("numbers") or []) >= 5) or (has_usage_alias and has_numeric_lines)
    if not (has_summary_header or fuzzy_summary_header or numeric_summary_context):
        return []
    unit = block.get("estimated_unit")
    unit_inferred = bool(block.get("unit_inferred"))
    unit_warning = block.get("unit_inference_warning") or ""
    rows = []
    current_usage, current_usage_reason = normalize_floor_usage_name(block_text)

    block_lines = block.get("lines") or []
    index = 0
    while index < len(block_lines):
        line = block_lines[index]
        raw_text = line.get("text", "")
        if re.search(r"1\.2|1\.6", raw_text):
            index += 1
            continue
        normalized_usage, usage_reason = normalize_floor_usage_name(raw_text)
        if normalized_usage:
            current_usage = normalized_usage
        numbers = _numbers_from_text(raw_text)
        next_numbers = _numbers_from_text(block_lines[index + 1].get("text", "")) if index + 1 < len(block_lines) else []
        adjacent_total_summary = None
        if len(numbers) == 1 and len(next_numbers) >= 2:
            candidate_live, candidate_service = next_numbers[-2], next_numbers[-1]
            candidate_dead = round(candidate_service - candidate_live, 6)
            if 0.5 <= candidate_live <= 8.0 and abs(candidate_dead - numbers[0]) <= 0.08:
                adjacent_total_summary = {
                    "live": candidate_live,
                    "service": candidate_service,
                    "factored": None,
                    "dead": numbers[0],
                    "source": "ADJACENT_TOTAL_PLUS_SERVICE_MINUS_LIVE",
                }
                raw_text = f"{raw_text} {block_lines[index + 1].get('text', '')}"
                index += 1
        if numbers and len(next_numbers) == 2:
            merged_live = numbers[-1]
            merged_service, merged_factored = next_numbers
            if merged_service > merged_live and merged_factored >= merged_service:
                raw_text = f"{raw_text} {block_lines[index + 1].get('text', '')}"
                numbers = [merged_live, merged_service, merged_factored]
                next_usage, next_reason = normalize_floor_usage_name(raw_text)
                if next_usage:
                    current_usage = next_usage
                    normalized_usage = next_usage
                    usage_reason = next_reason
                index += 1
        summary_values = adjacent_total_summary or _summary_values_from_numbers(numbers, raw_text)
        if not summary_values:
            index += 1
            continue
        usage_name = normalized_usage or current_usage
        if not normalized_usage and current_usage_reason and current_usage:
            usage_reason = current_usage_reason
        live = summary_values["live"]
        service = summary_values["service"]
        factored = summary_values["factored"]
        dead = summary_values["dead"]

        header = ["용도", "활하중", "사용하중", "계수하중"]
        cells = [raw_text, str(live), str(service), "" if factored is None else str(factored)]
        role_specs = [
            ("LIVE_LOAD", live, "live", []),
            ("SERVICE_LOAD", service, "service", ["사용하중은 검산용 값이므로 MGTX 생성 제외"]),
            ("DEAD_FINAL_TOTAL", dead, "dead_from_service_minus_live", ["OCR 요약표의 사용하중-활하중으로 DL을 산정함"]),
        ]
        if factored is not None:
            role_specs.insert(2, ("FACTORED_LOAD", factored, "factored", ["계수하중은 검산용 값이므로 MGTX 생성 제외"]))
        for role, value, suffix, extra_warnings in role_specs:
            base = _candidate_base(source_pdf, source_page, extraction_method, block, line, suffix, raw_text, unit, unit_inferred, unit_warning)
            unit_info = {
                "original_value": value,
                "original_unit": unit,
                "normalized_value": value,
                "normalized_unit": "kN/m2" if unit else None,
                "unit_conversion_factor": 1.0 if unit else None,
                "unit_normalization_warning": "" if unit else "단위가 불명확합니다.",
            }
            base.update({
                "load_value": value,
                "unit": unit,
                **unit_info,
                "table_cells": cells,
                "table_header": header,
                "floor_usage_name": usage_name or raw_text,
                "floor_usage_name_normalization_reason": usage_reason if normalized_usage else "carry_forward" if usage_name else "UNKNOWN_NAME",
                "load_value_role": role,
                "column_role": role,
                "load_component_type": "dead_load" if role == "DEAD_FINAL_TOTAL" else "live_load" if role == "LIVE_LOAD" else role.lower(),
                "forced_category": "dead" if role == "DEAD_FINAL_TOTAL" else "live" if role == "LIVE_LOAD" else None,
                "service_load": service,
                "live_load": live,
                "factored_load": factored,
                "service_expected": service,
                "factored_expected": 1.2 * dead + 1.6 * live,
                "dl_value_used_for_mgtx": dead if role == "DEAD_FINAL_TOTAL" else None,
                "dl_value_source": "SERVICE_MINUS_LIVE_FROM_OCR_SUMMARY" if role == "DEAD_FINAL_TOTAL" else "",
                "generated_dl": dead if role == "DEAD_FINAL_TOTAL" else None,
                "generated_ll": live if role == "LIVE_LOAD" else None,
                "analysis_method": "ocr_summary_table_block",
                "summary_value_source": summary_values["source"],
                "review_flag": True if unit_inferred or role in {"SERVICE_LOAD", "FACTORED_LOAD"} else base.get("review_flag", False),
            })
            for item in extra_warnings:
                if item not in base["warnings"]:
                    base["warnings"].append(item)
            if role in {"SERVICE_LOAD", "FACTORED_LOAD"}:
                base["exclude_from_mgtx"] = True
                base["exclude_reason"] = base["warnings"][-1]
                base["exclusion_reason"] = base["warnings"][-1]
            rows.append(base)
        index += 1
    return rows


def _apply_usage_order_fallback(rows):
    order = load_usage_order()
    if not order:
        return rows
    pointer = 0
    groups = []
    seen = set()
    for row in rows:
        if row.get("analysis_method") not in {"ocr_summary_table_block", "ocr_summary_line_alias"}:
            continue
        key = row.get("floor_load_group_key")
        if key and key not in seen:
            seen.add(key)
            groups.append(key)

    for key in groups:
        group = [row for row in rows if row.get("floor_load_group_key") == key]
        current_name = ""
        current_reason = ""
        for row in group:
            name, reason = normalize_floor_usage_name(row.get("floor_usage_name") or row.get("raw_text"))
            if name:
                current_name = name
                current_reason = reason
                break
        group_reason = group[0].get("floor_usage_name_normalization_reason") or ""
        if current_name and current_name in order and group_reason != "carry_forward":
            pointer = max(pointer, order.index(current_name) + 1)
        elif pointer < len(order):
            current_name = order[pointer]
            current_reason = "usage_order_fallback"
            pointer += 1
        if current_name:
            for row in group:
                row["floor_usage_name"] = current_name
                row["floor_usage_name_normalization_reason"] = current_reason
    return rows


def reconstruct_dead_total_from_detail_block(block, source_pdf="", source_page=None, extraction_method="ocr_fallback"):
    if not block.get("is_load_table_block"):
        return []
    unit = block.get("estimated_unit")
    rows = []
    for line in block.get("lines") or []:
        raw_text = line.get("text", "")
        if not TOTAL_PATTERN.search(raw_text) or SUMMARY_ROLE_PATTERN.search(raw_text):
            continue
        numbers = _numbers_from_text(raw_text)
        if not numbers:
            continue
        value = numbers[-1]
        base = _candidate_base(
            source_pdf,
            source_page,
            extraction_method,
            block,
            line,
            "dead_total",
            raw_text,
            unit,
            bool(block.get("unit_inferred")),
            block.get("unit_inference_warning") or "",
        )
        base.update({
            "load_value": value,
            "unit": unit,
            "original_value": value,
            "original_unit": unit,
            "normalized_value": value,
            "normalized_unit": "kN/m2" if unit else None,
            "unit_conversion_factor": 1.0 if unit else None,
            "load_value_role": "DEAD_FINAL_TOTAL",
            "column_role": "DEAD_FINAL_TOTAL",
            "load_component_type": "dead_load",
            "forced_category": "dead",
            "dl_value_used_for_mgtx": value,
            "dl_value_source": "OCR_DETAIL_TOTAL",
            "generated_dl": value,
            "analysis_method": "ocr_detail_total_block",
        })
        rows.append(base)
    return rows


def _bbox_for_words(words):
    if not words:
        return None
    x1 = min(float(word.get("x", 0)) for word in words)
    y1 = min(float(word.get("y", 0)) for word in words)
    x2 = max(float(word.get("x", 0)) + float(word.get("width", 0)) for word in words)
    y2 = max(float(word.get("y", 0)) + float(word.get("height", 0)) for word in words)
    return [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)]


def _row_value_unit(raw_text):
    pairs = extract_value_unit_pairs(raw_text)
    return pairs[0] if pairs else {
        "original_value": None,
        "original_unit": None,
        "normalized_value": None,
        "normalized_unit": None,
        "unit_conversion_factor": None,
        "unit_normalization_warning": "OCR 행에서 값/단위 쌍을 확정하지 못했습니다.",
    }


def reconstruct_table_candidates(words_df, source_pdf="", source_page=None, ocr_confidence=0.0, extraction_method="ocr_fallback"):
    lines = group_words_into_lines(words_df)
    blocks = group_lines_into_table_blocks(lines)
    block_rows = []
    for block in blocks:
        block_rows.extend(reconstruct_summary_rows_from_block(block, source_pdf=source_pdf, source_page=source_page, extraction_method=extraction_method))
        block_rows.extend(reconstruct_dead_total_from_detail_block(block, source_pdf=source_pdf, source_page=source_page, extraction_method=extraction_method))
    for row in block_rows:
        row["table_block_count"] = len(blocks)
    block_rows = _apply_usage_order_fallback(block_rows)

    rows = build_rows_from_ocr_words(words_df)
    table_regions = detect_table_regions(words_df)
    candidates = list(block_rows)
    active_header = []
    active_usage = ""
    page_text = normalize_ocr_text(" ".join(str(item.get("normalized_text") or item.get("text") or "") for item in words_df.to_dict("records"))) if words_df is not None and not words_df.empty else ""
    page_unit = _infer_unit_from_texts(page_text)

    for row in rows:
        raw_text = row["raw_text"]
        context = evaluate_floor_load_context(raw_text)
        has_value_unit = bool(VALUE_UNIT_PATTERN.search(raw_text))
        has_number = _contains_number(raw_text)
        row_numbers = _numbers_from_text(raw_text)
        row_unit = _infer_unit_from_texts(raw_text, " ".join(row["cells"]), " ".join(active_header), page_unit)
        if not row_unit:
            row_unit, row_unit_inferred, row_unit_warning = _infer_table_unit(f"{page_text} {raw_text}", row_numbers)
        else:
            row_unit_inferred, row_unit_warning = False, ""
        if LOAD_TOKEN_PATTERN.search(raw_text) and (not has_number or _header_has_load_roles(row["cells"])):
            active_header = row["cells"]
            if row_unit:
                page_unit = row_unit
        elif not active_header and _header_has_load_roles(row["cells"]):
            active_header = row["cells"]
        if context["detected_floor_keywords"] or context["detected_slab_keywords"] or context["detected_roof_keywords"]:
            active_usage = raw_text
        structured_numeric_row = bool(active_header and has_number and _header_has_load_roles(active_header))
        normalized_usage, usage_reason = normalize_floor_usage_name(raw_text)
        current_row_pos = max(0, int(row.get("line_index") or 1) - 1)
        summary_values = _summary_values_from_numbers(row_numbers, raw_text)
        if not summary_values:
            summary_values = _summary_values_from_nearby_total(
                row_numbers,
                normalized_usage,
                _nearby_single_totals(rows, current_row_pos),
            )
        if not summary_values and len(row_numbers) == 1 and row.get("line_index", 0) < len(rows):
            start = int(row.get("line_index"))
            for next_row in rows[start:min(start + 3, len(rows))]:
                next_text = next_row.get("raw_text", "")
                next_numbers = _numbers_from_text(next_text)
                if len(next_numbers) < 2:
                    continue
                candidate_live, candidate_service = next_numbers[-2], next_numbers[-1]
                candidate_dead = round(candidate_service - candidate_live, 6)
                if 0.5 <= candidate_live <= 8.0 and abs(candidate_dead - row_numbers[0]) <= 0.08:
                    raw_text = f"{raw_text} {next_text}"
                    row_numbers = [row_numbers[0], candidate_live, candidate_service]
                    summary_values = {
                        "live": candidate_live,
                        "service": candidate_service,
                        "factored": None,
                        "dead": row_numbers[0],
                        "source": "ADJACENT_TOTAL_PLUS_SERVICE_MINUS_LIVE",
                    }
                    break
        if not (has_value_unit or LOAD_TOKEN_PATTERN.search(raw_text) or context["detected_load_keywords"] or structured_numeric_row or summary_values):
            continue
        has_summary_numeric_tail = bool(summary_values and len(row_numbers) >= 3 and (context.get("detected_load_keywords") or row["line_index"] > 1))
        should_build_summary_alias = bool(normalized_usage and summary_values) or (
            bool(summary_values)
            and not normalized_usage
            and not VALUE_UNIT_PATTERN.search(raw_text)
            and len(row_numbers) >= 3
        )
        if should_build_summary_alias:
            live = summary_values["live"]
            service = summary_values["service"]
            factored = summary_values["factored"]
            dead = summary_values["dead"]
            if has_summary_numeric_tail or normalized_usage:
                pseudo_block = {
                    "block_id": f"line_{row['line_index']:03d}",
                    "text": f"{page_text} {raw_text}",
                    "detected_keywords": _keywords_from_text(raw_text),
                    "numbers": row_numbers,
                    "estimated_unit": row_unit or "kN/m2",
                    "unit_inferred": not bool(row_unit),
                    "unit_inference_warning": "OCR에서 단위를 직접 읽지 못해 하중표 문맥상 kN/m2로 추정" if not row_unit else "",
                    "avg_confidence": _avg_confidence(row["words"]) or ocr_confidence,
                    "is_load_table_block": True,
                }
                pseudo_line = {"line_index": row["line_index"], "text": raw_text, "words": row["words"], "center_y": 0}
                role_specs = [
                    ("LIVE_LOAD", live, "live"),
                    ("SERVICE_LOAD", service, "service"),
                    ("DEAD_FINAL_TOTAL", dead, "dead_from_service_minus_live"),
                ]
                if factored is not None:
                    role_specs.insert(2, ("FACTORED_LOAD", factored, "factored"))
                for role, value, suffix in role_specs:
                    base = _candidate_base(source_pdf, source_page, extraction_method, pseudo_block, pseudo_line, suffix, raw_text, pseudo_block["estimated_unit"], pseudo_block["unit_inferred"], pseudo_block["unit_inference_warning"])
                    base.update({
                        "floor_usage_name": normalized_usage or raw_text,
                        "floor_usage_name_normalization_reason": usage_reason if normalized_usage else "UNKNOWN_NAME",
                        "load_value": value,
                        "unit": pseudo_block["estimated_unit"],
                        "original_value": value,
                        "original_unit": pseudo_block["estimated_unit"],
                        "normalized_value": value,
                        "normalized_unit": "kN/m2",
                        "unit_conversion_factor": 1.0,
                        "load_value_role": role,
                        "column_role": role,
                        "load_component_type": "dead_load" if role == "DEAD_FINAL_TOTAL" else "live_load" if role == "LIVE_LOAD" else role.lower(),
                        "forced_category": "dead" if role == "DEAD_FINAL_TOTAL" else "live" if role == "LIVE_LOAD" else None,
                        "service_load": service,
                        "live_load": live,
                        "factored_load": factored,
                        "dl_value_source": "SERVICE_MINUS_LIVE_FROM_OCR_SUMMARY" if role == "DEAD_FINAL_TOTAL" else "",
                        "generated_dl": dead if role == "DEAD_FINAL_TOTAL" else None,
                        "generated_ll": live if role == "LIVE_LOAD" else None,
                        "analysis_method": "ocr_summary_line_alias",
                        "summary_value_source": summary_values["source"],
                    })
                    if role in {"SERVICE_LOAD", "FACTORED_LOAD"}:
                        base["exclude_from_mgtx"] = True
                        base["exclude_reason"] = "사용하중/계수하중은 검산용 값이므로 MGTX 생성 제외"
                        base["exclusion_reason"] = base["exclude_reason"]
                    candidates.append(base)

        unit_info = _row_value_unit(raw_text)
        warnings = []
        review_flag = False
        if unit_info.get("unit_normalization_warning") and structured_numeric_row and row_unit:
            unit_info.update({
                "original_unit": row_unit,
                "normalized_unit": None,
                "unit_normalization_warning": "",
            })
        if unit_info.get("unit_normalization_warning"):
            warnings.append(unit_info["unit_normalization_warning"])
            review_flag = True
        if ocr_confidence < 60:
            warnings.append("OCR 평균 confidence가 낮아 검토가 필요합니다.")
            review_flag = True
        if structured_numeric_row and not row_unit:
            warnings.append("숫자행은 감지되었지만 단위가 불명확합니다.")
            review_flag = True
        if row_unit_inferred:
            warnings.append(row_unit_warning)
            review_flag = True

        candidates.append({
            "source_pdf": Path(source_pdf).name if source_pdf else "",
            "source_page": source_page,
            "source_type": "ocr",
            "source_index": row["line_index"],
            "row_index": row["line_index"],
            "col_index": None,
            "raw_text": raw_text,
            "load_item": raw_text,
            "load_value": unit_info.get("original_value"),
            "unit": unit_info.get("original_unit") or row_unit,
            **unit_info,
            "inferred_unit": row_unit,
            "page_unit": page_unit,
            "unit_inferred": row_unit_inferred,
            "floor_usage_name": active_usage,
            "floor_load_group_key": f"{Path(source_pdf).name}|{source_page}|ocr|{active_usage or row['line_index']}",
            "table_cells": row["cells"],
            "table_header": active_header,
            "bbox": _bbox_for_words(row["words"]),
            "ocr_confidence": _avg_confidence(row["words"]) or ocr_confidence,
            "extraction_method": extraction_method,
            "extraction_confidence": ocr_confidence,
            "extraction_debug": {
                "line_index": row["line_index"],
                "column_count": row["column_count"],
                "table_regions": table_regions,
                "table_blocks": [{key: value for key, value in block.items() if key != "lines"} for block in blocks],
                "merged_cell_inferred": len(row["cells"]) < max([item.get("column_count", 1) for item in rows] or [1]),
            },
            "table_block_count": len(blocks),
            "review_flag": review_flag or context.get("review_flag", False),
            "warnings": warnings + context.get("warnings", []),
            **context,
        })
    candidates = _fill_unknown_usage_from_order(candidates)
    return candidates
