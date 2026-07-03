import re
from pathlib import Path

from load_table_context import evaluate_floor_load_context
from ocr_engine import estimate_ocr_confidence, get_page_ocr_text
from table_reconstructor import group_words_into_lines
from unit_normalizer import NUMBER_PATTERN, UNIT_PATTERN, extract_value_unit_pairs, normalize_load_value


KEYWORD_PATTERN = re.compile(
    r"SLAB|S1AB|5LAB|슬래브|슬라브|바닥|바닥판|고정하중|활하중|적재하중|합계|총계|사용하중|계수하중|지붕|옥상|태양광|화장실|주차장|DEAD|LIVE|LOAD|DL|LL|TOTAL",
    re.IGNORECASE,
)


def _bbox_for_words(words):
    if not words:
        return None
    x1 = min(float(word.get("x", 0)) for word in words)
    y1 = min(float(word.get("y", 0)) for word in words)
    x2 = max(float(word.get("x", 0)) + float(word.get("width", 0)) for word in words)
    y2 = max(float(word.get("y", 0)) + float(word.get("height", 0)) for word in words)
    return [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)]


def words_to_line_records(words_df):
    records = []
    for index, line in enumerate(group_words_into_lines(words_df), start=1):
        text = line.get("text", "")
        words = line.get("words", [])
        confidences = [float(word.get("confidence", 0) or 0) for word in words]
        records.append({
            "line_index": index,
            "line_text": text,
            "normalized_line_text": text,
            "bbox": _bbox_for_words(words),
            "avg_confidence": round(sum(confidences) / len(confidences), 2) if confidences else 0.0,
            "detected_keywords": KEYWORD_PATTERN.findall(text),
            "detected_numbers": NUMBER_PATTERN.findall(text),
            "detected_units": UNIT_PATTERN.findall(text),
        })
    return records


def candidate_rows_from_ocr_lines(words_df, source_pdf="", source_page=None, extraction_method="ocr_line_candidate"):
    source_name = Path(source_pdf).name if source_pdf else ""
    line_records = words_to_line_records(words_df)
    page_confidence = estimate_ocr_confidence(words_df)
    page_text = get_page_ocr_text(words_df)
    inferred_unit = "kN/m2" if re.search(r"kN\s*/\s*(?:m2|m²|㎡)", page_text, re.IGNORECASE) else None
    rows = []

    for line in line_records:
        text = line["line_text"]
        context = evaluate_floor_load_context(text)
        value_units = extract_value_unit_pairs(text)
        if value_units:
            for pair_index, value_unit in enumerate(value_units, start=1):
                rows.append({
                    "source_pdf": source_name,
                    "source_page": source_page,
                    "source_type": "ocr",
                    "source_index": f"line-{line['line_index']}-num-{pair_index}",
                    "extraction_method": "ocr_numeric_candidate",
                    "raw_text": text,
                    "load_item": text,
                    "load_value": value_unit.get("original_value"),
                    "unit": value_unit.get("original_unit"),
                    **value_unit,
                    "floor_usage_name": "UNKNOWN",
                    "floor_load_group_key": f"OCR_REVIEW_p{source_page}_{line['line_index']:03d}",
                    "row_index": line["line_index"],
                    "col_index": None,
                    "bbox": line["bbox"],
                    "ocr_confidence": line["avg_confidence"] or page_confidence,
                    "extraction_confidence": (line["avg_confidence"] or page_confidence) / 100.0,
                    "review_flag": True,
                    "exclude_from_mgtx": True,
                    "exclude_reason": "OCR numeric candidate; table structure and load role require review",
                    "exclusion_reason": "OCR numeric candidate; table structure and load role require review",
                    "warnings": ["OCR numeric candidate only"],
                    "load_value_role": "UNKNOWN",
                    "column_role": "UNKNOWN",
                    "extraction_debug": {"line": line, "inferred_unit": None},
                    **context,
                })
        elif line["detected_numbers"]:
            value = line["detected_numbers"][0]
            unit_info = normalize_load_value(value, inferred_unit)
            rows.append({
                "source_pdf": source_name,
                "source_page": source_page,
                "source_type": "ocr",
                "source_index": f"line-{line['line_index']}",
                "extraction_method": extraction_method,
                "raw_text": text,
                "load_item": "OCR_CANDIDATE",
                "load_value": value,
                "unit": inferred_unit,
                **unit_info,
                "floor_usage_name": "UNKNOWN",
                "floor_load_group_key": f"OCR_REVIEW_p{source_page}_{line['line_index']:03d}",
                "row_index": line["line_index"],
                "col_index": None,
                "bbox": line["bbox"],
                "ocr_confidence": line["avg_confidence"] or page_confidence,
                "extraction_confidence": (line["avg_confidence"] or page_confidence) / 100.0,
                "review_flag": True,
                "exclude_from_mgtx": True,
                "exclude_reason": "OCR fallback 후보이나 하중값/단위/표 구조 확정 불가",
                "exclusion_reason": "OCR fallback 후보이나 하중값/단위/표 구조 확정 불가",
                "warnings": ["OCR line candidate only", "Unit inferred from page context" if inferred_unit else "Unit missing"],
                "load_value_role": "UNKNOWN",
                "column_role": "UNKNOWN",
                "extraction_debug": {"line": line, "inferred_unit": inferred_unit},
                **context,
            })
        elif line["detected_keywords"]:
            rows.append({
                "source_pdf": source_name,
                "source_page": source_page,
                "source_type": "ocr",
                "source_index": f"line-{line['line_index']}",
                "extraction_method": extraction_method,
                "raw_text": text,
                "load_item": "OCR_CANDIDATE",
                "load_value": None,
                "unit": None,
                "original_value": None,
                "original_unit": None,
                "normalized_value": None,
                "normalized_unit": None,
                "floor_usage_name": "UNKNOWN",
                "floor_load_group_key": f"OCR_REVIEW_p{source_page}_{line['line_index']:03d}",
                "row_index": line["line_index"],
                "col_index": None,
                "bbox": line["bbox"],
                "ocr_confidence": line["avg_confidence"] or page_confidence,
                "extraction_confidence": (line["avg_confidence"] or page_confidence) / 100.0,
                "review_flag": True,
                "exclude_from_mgtx": True,
                "exclude_reason": "OCR keyword candidate; numeric load value not confirmed",
                "exclusion_reason": "OCR keyword candidate; numeric load value not confirmed",
                "warnings": ["OCR keyword candidate only"],
                "load_value_role": "UNKNOWN",
                "column_role": "UNKNOWN",
                "extraction_debug": {"line": line},
                **context,
            })
    if not rows and page_text:
        rows.append({
            "source_pdf": source_name,
            "source_page": source_page,
            "source_type": "ocr",
            "source_index": "page-text",
            "extraction_method": "ocr_raw_text_candidate",
            "raw_text": page_text,
            "load_item": "OCR_CANDIDATE",
            "load_value": None,
            "unit": None,
            "original_value": None,
            "original_unit": None,
            "normalized_value": None,
            "normalized_unit": None,
            "floor_usage_name": "UNKNOWN",
            "floor_load_group_key": f"OCR_REVIEW_p{source_page}_raw",
            "bbox": None,
            "ocr_confidence": page_confidence,
            "extraction_confidence": page_confidence / 100.0,
            "review_flag": True,
            "exclude_from_mgtx": True,
            "exclude_reason": "OCR raw text only; table structure not reconstructed",
            "exclusion_reason": "OCR raw text only; table structure not reconstructed",
            "warnings": ["OCR raw text candidate only"],
            "load_value_role": "UNKNOWN",
            "column_role": "UNKNOWN",
        })
    return rows
