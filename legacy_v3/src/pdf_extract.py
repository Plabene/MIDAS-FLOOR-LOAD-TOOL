import json
import re
from pathlib import Path

import pdfplumber
import yaml
from PIL import Image, ImageDraw

from image_preprocess import crop_margins, preprocess_for_ocr, upscale_image
from ocr_candidate_extractor import candidate_rows_from_ocr_lines, words_to_line_records
from ocr_engine import estimate_ocr_confidence, get_ocr_engine_status, get_page_ocr_text, run_ocr_with_priority
from ocr_screening import run_ocr_screening
from pdf_page_analyzer import analyze_page
from pdf_render import render_pdf_page
from scan_ocr_screening import run_scan_ocr_screening
from table_reconstructor import build_rows_from_ocr_words, reconstruct_table_candidates
from unit_normalizer import UNIT_PATTERN


LOAD_KEYWORDS = [
    "하중", "LOAD", "DL", "D.L", "LL", "L.L", "DEAD", "LIVE",
    "고정하중", "고정", "사하중", "활하중", "적재하중", "합계", "총계", "TOTAL",
    "사용하중", "계수하중", "SLAB", "슬래브", "슬라브", "바닥", "지붕", "옥상", "태양광",
    "kN", "kN/m2", "kN/㎡", "kPa", "kgf/m2", "tf/m2", "t/m2",
]
HEADER_KEYWORDS = [
    "용도", "고정", "사하중", "DEAD", "DL", "D.L", "활하중", "적재", "LIVE", "LL", "L.L",
    "사용", "SERVICE", "계수", "FACTORED", "ULTIMATE", "THK", "두께",
]


DEFAULT_OCR_SETTINGS = {
    "enabled": True,
    "dpi": 300,
    "fallback_dpi": 400,
    "dpi_candidates": [300, 400],
    "default_dpi": 400,
    "save_debug_images": True,
    "debug_dir": "debug",
    "scan_compare_debug_dir": "debug/scan_ocr",
    "engine": "tesseract",
    "engine_priority": ["tesseract", "paddleocr", "easyocr"],
    "min_text_length_for_text_pdf": 50,
    "min_ocr_confidence": 60,
    "include_review_required": False,
    "screening": {
        "enabled": True,
        "max_candidates": 1,
        "ocr_max_candidates": 1,
        "ocr_dpi_candidates": [300],
        "ocr_max_image_side": 1600,
        "reference_similarity_threshold": 0.90,
        "include_low_confidence_as_review": True,
    },
}


def _clean_text(text):
    return " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())


def _contains_any(text, keywords):
    upper_text = str(text or "").upper()
    return any(str(keyword).upper() in upper_text for keyword in keywords)


def _cell_texts(row):
    return [_clean_text(cell) for cell in (row or [])]


def _normalize_floor_usage(value):
    text = _clean_text(value)
    for separator in ["\n", "→", "/", "\\", ";", "|"]:
        text = text.replace(separator, ",")
    parts = []
    for part in text.split(","):
        cleaned = _clean_text(part)
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
    return ",".join(parts)


def _usage_column_indexes(header):
    indexes = []
    for index, value in enumerate(header or []):
        compact = str(value or "").replace(" ", "")
        if "용도" in compact:
            indexes.append(index)
    return indexes


def _extract_floor_usage(cells, header, previous_usage):
    usage_parts = []
    indexes = _usage_column_indexes(header)
    if indexes:
        for index in indexes:
            if index < len(cells):
                usage_parts.extend(part for part in _normalize_floor_usage(cells[index]).split(",") if part)
    elif cells:
        first_cell = _normalize_floor_usage(cells[0])
        if first_cell and not _contains_any(first_cell, HEADER_KEYWORDS):
            usage_parts.extend(part for part in first_cell.split(",") if part)
    if usage_parts:
        unique_parts = []
        for part in usage_parts:
            if part not in unique_parts:
                unique_parts.append(part)
        return ",".join(unique_parts)
    return previous_usage or ""


def _find_project_root(input_path):
    input_path = Path(input_path).resolve()
    for path in [input_path, *input_path.parents]:
        if (path / "config" / "midas_settings.yml").exists():
            return path
    return input_path.parent


def _load_settings(input_path):
    root_dir = _find_project_root(input_path)
    config_path = root_dir / "config" / "midas_settings.yml"
    settings = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as file:
            settings = yaml.safe_load(file) or {}
    ocr_settings = DEFAULT_OCR_SETTINGS.copy()
    ocr_settings.update(settings.get("ocr", {}) or {})
    return ocr_settings, root_dir


def _debug_slug(pdf_file):
    stem = Path(pdf_file).stem
    slug = re.sub(r"[^A-Za-z0-9가-힣_-]+", "_", stem).strip("_")
    return slug or "pdf_debug"


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, default=str)


def _draw_ocr_overlay(image_array, words_df, output_path):
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.fromarray(image_array).convert("RGB")
    draw = ImageDraw.Draw(image)
    if words_df is not None and not words_df.empty:
        for word in words_df.to_dict("records"):
            x = float(word.get("x", 0))
            y = float(word.get("y", 0))
            w = float(word.get("width", 0))
            h = float(word.get("height", 0))
            conf = float(word.get("confidence", 0) or 0)
            color = "green" if conf >= 70 else "orange" if conf >= 40 else "red"
            draw.rectangle([x, y, x + w, y + h], outline=color, width=2)
    image.save(output_path)


def _failure_stage(rendered_saved, preprocessed_saved, words, lines, numeric_candidates, candidate_rows, ocr_status):
    if not rendered_saved:
        return "RENDER_FAILED", "PDF page rendering image was not saved."
    if not preprocessed_saved:
        return "PREPROCESS_FAILED", "Preprocessed OCR image was not saved."
    if not (ocr_status or {}).get("tesseract_available") and not words:
        return "OCR_ENGINE_NOT_AVAILABLE", "Tesseract OCR is not available and OCR returned no words."
    if not words:
        return "OCR_NO_WORDS", "OCR returned no words."
    if not lines:
        return "OCR_WORDS_BUT_NO_LINES", "OCR words were extracted but line grouping produced no lines."
    if not numeric_candidates:
        return "LINES_BUT_NO_NUMERIC_CANDIDATES", "OCR lines were extracted but no numeric candidates were detected."
    if candidate_rows and all(row.get("exclude_from_mgtx") or row.get("review_flag") for row in candidate_rows):
        return "CANDIDATES_BUT_NO_MGTX_ROWS", "OCR candidates were retained for review but are not confirmed for MGTX input."
    if not candidate_rows:
        return "LINES_BUT_NO_NUMERIC_CANDIDATES", "OCR produced lines but no final candidate rows were reconstructed."
    return "SUCCESS", ""


def _ocr_fallback_debug_dir(root_dir, pdf_file):
    return Path(root_dir) / "debug" / "ocr_fallback" / Path(pdf_file).stem


def _save_ocr_fallback_debug(root_dir, pdf_file, page_index, image=None, preprocessed=None, words_df=None, candidate_rows=None, diagnostics=None):
    debug_dir = _ocr_fallback_debug_dir(root_dir, pdf_file)
    debug_dir.mkdir(parents=True, exist_ok=True)
    rendered_path = debug_dir / f"page_{page_index:03d}_rendered.png"
    preprocessed_path = debug_dir / f"page_{page_index:03d}_preprocessed.png"
    if image is None:
        try:
            image = render_pdf_page(pdf_file, page_index, dpi=300)
        except Exception:
            image = None
    if image is not None:
        Image.fromarray(image).save(rendered_path)
    if preprocessed is None:
        preprocessed = image
    if preprocessed is not None:
        Image.fromarray(preprocessed).save(preprocessed_path)
        try:
            table_crop = upscale_image(crop_margins(preprocessed), scale=2)
            Image.fromarray(table_crop).save(debug_dir / f"page_{page_index:03d}_table_crop_001.png")
        except Exception:
            pass
    words = words_df.to_dict("records") if words_df is not None and not words_df.empty else []
    lines = words_to_line_records(words_df) if words_df is not None and not words_df.empty else []
    text = get_page_ocr_text(words_df) if words_df is not None and not words_df.empty else ""
    numeric_candidates = [
        row for row in (candidate_rows or [])
        if row.get("original_value") is not None or row.get("load_value") is not None
    ]
    if not numeric_candidates:
        for line in lines:
            for number in line.get("detected_numbers", []) or []:
                numeric_candidates.append({
                    "source_pdf": Path(pdf_file).name,
                    "source_page": page_index,
                    "line_index": line.get("line_index"),
                    "raw_text": line.get("line_text"),
                    "candidate_value": number,
                    "detected_units": line.get("detected_units", []),
                    "detected_keywords": line.get("detected_keywords", []),
                    "bbox": line.get("bbox"),
                    "ocr_confidence": line.get("avg_confidence"),
                    "review_flag": True,
                    "exclude_from_mgtx": True,
                    "exclude_reason": "OCR line numeric candidate; unit/column role not confirmed",
                })
    unit_candidates = []
    keyword_candidates = []
    table_blocks = []
    seen_block_ids = set()
    for row in candidate_rows or []:
        debug = row.get("extraction_debug") or {}
        if isinstance(debug, str):
            try:
                debug = json.loads(debug)
            except Exception:
                debug = {}
        for block in debug.get("table_blocks", []) or []:
            block_id = block.get("block_id")
            if block_id and block_id not in seen_block_ids:
                table_blocks.append(block)
                seen_block_ids.add(block_id)
        row_block_id = row.get("table_block_id")
        if row_block_id and row_block_id not in seen_block_ids:
            table_blocks.append({
                "block_id": row_block_id,
                "detected_keywords": row.get("table_block_keywords") or [],
                "numbers": row.get("table_block_numbers") or [],
                "estimated_unit": row.get("estimated_unit") or row.get("inferred_unit"),
                "unit_inferred": row.get("unit_inferred"),
                "avg_confidence": row.get("table_block_confidence"),
                "is_load_table_block": row.get("table_block_is_load_table"),
            })
            seen_block_ids.add(row_block_id)
    for line in lines:
        for unit in line.get("detected_units", []) or []:
            unit_candidates.append({
                "source_pdf": Path(pdf_file).name,
                "source_page": page_index,
                "line_index": line.get("line_index"),
                "raw_text": line.get("line_text"),
                "candidate_unit": unit,
                "bbox": line.get("bbox"),
                "ocr_confidence": line.get("avg_confidence"),
            })
        for keyword in line.get("detected_keywords", []) or []:
            keyword_candidates.append({
                "source_pdf": Path(pdf_file).name,
                "source_page": page_index,
                "line_index": line.get("line_index"),
                "raw_text": line.get("line_text"),
                "candidate_keyword": keyword,
                "bbox": line.get("bbox"),
                "ocr_confidence": line.get("avg_confidence"),
            })
    if not unit_candidates and text:
        for unit in UNIT_PATTERN.findall(text):
            unit_candidates.append({
                "source_pdf": Path(pdf_file).name,
                "source_page": page_index,
                "line_index": None,
                "raw_text": text,
                "candidate_unit": unit,
                "bbox": None,
                "ocr_confidence": estimate_ocr_confidence(words_df),
            })
    ocr_status = get_ocr_engine_status()
    failure_stage, failure_reason = _failure_stage(
        rendered_path.exists(),
        preprocessed_path.exists(),
        words,
        lines,
        numeric_candidates,
        candidate_rows or [],
        ocr_status,
    )
    diagnostics_data = dict(diagnostics or {})
    diagnostics_data.update({
        "source_pdf": Path(pdf_file).name,
        "source_page": page_index,
        "rendered_image_saved": rendered_path.exists(),
        "rendered_image_path": str(rendered_path),
        "preprocessed_image_saved": preprocessed_path.exists(),
        "preprocessed_image_path": str(preprocessed_path),
        "ocr_word_count": len(words),
        "ocr_line_count": len(lines),
        "numeric_candidate_count": len(numeric_candidates),
        "unit_candidate_count": len(unit_candidates),
        "keyword_candidate_count": len(keyword_candidates),
        "table_block_count": len(table_blocks) or max([int(row.get("table_block_count") or 0) for row in (candidate_rows or [])] or [0]),
        "final_candidate_row_count": len(candidate_rows or []),
        "ocr_failed": len(words) == 0,
        "reason": "OCR returned no words" if not words else "",
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "tesseract_status": ocr_status,
    })
    for row in candidate_rows or []:
        row.setdefault("rendered_image_saved", rendered_path.exists())
        row.setdefault("preprocessed_image_saved", preprocessed_path.exists())
        row.setdefault("ocr_word_count", len(words))
        row.setdefault("ocr_line_count", len(lines))
        row.setdefault("numeric_candidate_count", len(numeric_candidates))
        row.setdefault("unit_candidate_count", len(unit_candidates))
        row.setdefault("keyword_candidate_count", len(keyword_candidates))
        row.setdefault("table_block_count", diagnostics_data.get("table_block_count", 0))
        row.setdefault("final_candidate_row_count", len(candidate_rows or []))
        row.setdefault("failure_stage", failure_stage)
        row.setdefault("failure_reason", failure_reason)
        row.setdefault("ocr_engine_available", ocr_status.get("tesseract_available"))
        row.setdefault("tesseract_languages", ocr_status.get("tesseract_languages"))
    _write_json(debug_dir / f"page_{page_index:03d}_ocr_words.json", words)
    _write_json(debug_dir / f"page_{page_index:03d}_ocr_lines.json", lines)
    _write_json(debug_dir / f"page_{page_index:03d}_numeric_candidates.json", numeric_candidates)
    _write_json(debug_dir / f"page_{page_index:03d}_unit_candidates.json", unit_candidates)
    _write_json(debug_dir / f"page_{page_index:03d}_keyword_candidates.json", keyword_candidates)
    _write_json(debug_dir / f"page_{page_index:03d}_table_blocks.json", table_blocks)
    _write_json(debug_dir / f"page_{page_index:03d}_final_candidate_rows.json", candidate_rows or [])
    _write_json(debug_dir / f"page_{page_index:03d}_selected_ocr_result.json", diagnostics_data.get("ocr_meta", {}))
    _write_json(debug_dir / f"page_{page_index:03d}_diagnostics.json", diagnostics_data)
    with open(debug_dir / f"page_{page_index:03d}_ocr_text.txt", "w", encoding="utf-8") as file:
        file.write(text)
    with open(debug_dir / f"page_{page_index:03d}_table_crop_001_ocr_text.txt", "w", encoding="utf-8") as file:
        file.write(text)
    if preprocessed is not None and words_df is not None:
        _draw_ocr_overlay(preprocessed, words_df, debug_dir / f"page_{page_index:03d}_ocr_overlay.png")


def _page_meta(page_info, method=None, confidence=None, deskew=None, render_dpi=None, ocr_available=None, fallback_reason=None):
    meta = dict(page_info or {})
    meta.pop("page_text", None)
    if method:
        meta["extraction_method"] = method
    if confidence is not None:
        meta["extraction_confidence"] = confidence
    if deskew is not None:
        meta["page_deskew_applied"] = deskew
    if render_dpi is not None:
        meta["render_dpi"] = render_dpi
    if ocr_available is not None:
        meta["ocr_available"] = ocr_available
    if fallback_reason:
        current = meta.get("fallback_reason")
        meta["fallback_reason"] = "; ".join(item for item in [current, fallback_reason] if item)
    return meta


def _make_candidate(pdf_file, page_index, source_type, source_index, raw_text, cells=None, header=None, floor_usage=None, errors=None, warnings=None, extra=None):
    candidate = {
        "source_pdf": pdf_file.name if hasattr(pdf_file, "name") else str(pdf_file or ""),
        "source_page": page_index,
        "source_type": source_type,
        "source_index": source_index,
        "raw_text": raw_text,
        "table_cells": cells or [],
        "table_header": header or [],
        "floor_usage_name": floor_usage or "",
        "errors": list(errors or []),
        "warnings": list(warnings or []),
    }
    candidate.update(extra or {})
    return candidate


def _error_candidate(pdf_file, page_index, message, extra=None):
    return _make_candidate(pdf_file, page_index, "error", None, "", errors=[message], extra=extra)


def _merge_header_rows(previous_header, current_header):
    if not previous_header:
        return current_header
    max_len = max(len(previous_header), len(current_header))
    merged = []
    for index in range(max_len):
        previous = previous_header[index] if index < len(previous_header) else ""
        current = current_header[index] if index < len(current_header) else ""
        merged.append(f"{previous} {current}".strip() if previous and current else previous or current)
    return merged


def _extract_from_text_layer(pdf_file, page_index, page, page_info):
    rows = []
    text_meta = _page_meta(page_info, method="text_layer", confidence=page_info.get("extraction_confidence"))
    try:
        tables = page.extract_tables() or []
    except Exception as exc:
        rows.append(_error_candidate(pdf_file, page_index, f"Table extraction failed: {exc}", extra=text_meta))
        tables = []

    for table_index, table in enumerate(tables, start=1):
        active_header = []
        previous_header = []
        active_floor_usage = ""
        for row_index, row in enumerate(table or [], start=1):
            cells = _cell_texts(row)
            raw_text = _clean_text(" ".join(cells))
            if not raw_text:
                continue
            if _contains_any(raw_text, HEADER_KEYWORDS):
                if any(keyword in raw_text.upper() for keyword in ["KN/", "TF/", "KGF/", "THK", "두께"]):
                    active_header = _merge_header_rows(previous_header, cells)
                else:
                    active_header = cells
                previous_header = active_header
            floor_usage = _extract_floor_usage(cells, active_header, active_floor_usage)
            if floor_usage:
                active_floor_usage = floor_usage
            if _contains_any(raw_text, LOAD_KEYWORDS) or (active_header and any(char.isdigit() for char in raw_text)):
                rows.append(_make_candidate(
                    pdf_file, page_index, "table", f"{table_index}-{row_index}", raw_text,
                    cells=cells, header=active_header, floor_usage=active_floor_usage, extra=text_meta,
                ))

    try:
        page_text = page.extract_text() or ""
    except Exception as exc:
        rows.append(_error_candidate(pdf_file, page_index, f"Text extraction failed: {exc}", extra=text_meta))
        page_text = ""
    for line_index, line in enumerate(page_text.splitlines(), start=1):
        line_text = _clean_text(line)
        if line_text and _contains_any(line_text, LOAD_KEYWORDS):
            rows.append(_make_candidate(pdf_file, page_index, "text", line_index, line_text, extra=text_meta))
    return rows


def _dedupe_rows(rows):
    def row_score(row):
        score = float(row.get("extraction_confidence") or 0)
        if row.get("floor_usage_name_normalization_reason") not in {"", None, "UNKNOWN_NAME"}:
            score += 100
        if row.get("analysis_method") == "ocr_summary_table_block":
            score += 25
        if row.get("analysis_method") == "ocr_summary_line_alias":
            score += 10
        if row.get("floor_usage_name") and str(row.get("floor_usage_name")) != str(row.get("raw_text")):
            score += 10
        return score

    best = {}
    for row in rows:
        key = (
            row.get("source_pdf"),
            row.get("source_page"),
            row.get("load_value_role"),
            row.get("load_value"),
            re.sub(r"\s+", "", str(row.get("raw_text") or ""))[:120],
        )
        if key not in best or row_score(row) > row_score(best[key]):
            best[key] = row
    return list(best.values())


def _has_value_rows(rows):
    return any(
        row.get("original_value") is not None
        or row.get("normalized_value") is not None
        or row.get("load_value") is not None
        for row in rows or []
    )


def _merge_ocr_line_fallback(rows, fallback_rows, meta):
    merged = list(rows or [])
    if not fallback_rows:
        return merged
    if _has_value_rows(merged):
        return merged
    for row in fallback_rows:
        row.update({key: value for key, value in meta.items() if key not in row})
    merged.extend(fallback_rows)
    return _dedupe_rows(merged)


def _extract_from_ocr_fallback(pdf_file, page_index, page_info, ocr_settings, debug_root):
    project_root = _find_project_root(Path(pdf_file).parent)
    page_type = str(page_info.get("pdf_page_type") or "")
    image_count = int(page_info.get("image_object_count") or page_info.get("image_count") or 0)
    use_scan_pipeline = (
        page_type in {"image_based_pdf", "ocr_required_pdf", "scanned_pdf"}
        or (image_count > 0 and not page_info.get("text_extraction_available"))
    )
    if use_scan_pipeline:
        scan_debug_dir = Path(ocr_settings.get("scan_compare_debug_dir", "debug/scan_ocr"))
        if not scan_debug_dir.is_absolute():
            scan_debug_dir = _find_project_root(Path(pdf_file).parent) / scan_debug_dir
        screening = run_scan_ocr_screening(pdf_file, page_index, ocr_settings, debug_dir=scan_debug_dir)
        rows = screening.get("rows") or []
        best = screening.get("best") or {}
        metrics = best.get("scan_metrics") or {}
        ocr_meta = _page_meta(
            page_info,
            method="scan_ocr_screening",
            confidence=best.get("ocr_confidence", 0),
            render_dpi=best.get("dpi"),
            ocr_available=bool(best.get("words_df") is not None and not best.get("words_df").empty if best else False),
            fallback_reason=page_info.get("fallback_reason") or "scan_pdf_text_layer_insufficient",
        )
        ocr_meta.update({
            "ocr_required": True,
            "ocr_confidence": best.get("ocr_confidence", 0),
            "ocr_engine": best.get("ocr_engine"),
            "preprocess_candidate_name": best.get("preprocess"),
            "dpi": best.get("dpi"),
            "similarity_score": best.get("similarity_score"),
            "estimated_dpi": ocr_settings.get("default_dpi", 400),
            **metrics,
        })
        for row in rows:
            row.update({key: value for key, value in ocr_meta.items() if key not in row})
        fallback_rows = candidate_rows_from_ocr_lines(best.get("words_df"), source_pdf=pdf_file, source_page=page_index, extraction_method="ocr_line_candidate") if best.get("words_df") is not None and not best.get("words_df").empty else []
        rows = _merge_ocr_line_fallback(rows, fallback_rows, ocr_meta)
        _save_ocr_fallback_debug(project_root, pdf_file, page_index, preprocessed=best.get("image"), words_df=best.get("words_df"), candidate_rows=rows, diagnostics={"page_info": page_info, "ocr_meta": ocr_meta})
        if rows:
            return rows, screening.get("report", {}).get("candidates", [])
        if best.get("words_df") is not None and not best.get("words_df").empty:
            return [_make_candidate(
                pdf_file,
                page_index,
                "ocr_text",
                None,
                get_page_ocr_text(best["words_df"]),
                warnings=["Scan OCR screening text was extracted but no load-table row could be reconstructed."],
                extra=ocr_meta,
            )], screening.get("report", {}).get("candidates", [])

    if (ocr_settings.get("screening") or {}).get("enabled", True):
        compare_debug_dir = ocr_settings.get("compare_debug_dir")
        if compare_debug_dir:
            screening_debug = Path(compare_debug_dir)
            if not screening_debug.is_absolute():
                screening_debug = _find_project_root(Path(pdf_file).parent) / screening_debug
        else:
            screening_debug = Path(debug_root) / "ocr_screening"
        screening = run_ocr_screening(pdf_file, page_index, ocr_settings, debug_dir=screening_debug)
        rows = screening.get("rows") or []
        best = screening.get("best") or {}
        ocr_meta = _page_meta(
            page_info,
            method="ocr_screening",
            confidence=best.get("ocr_confidence", 0),
            render_dpi=best.get("dpi"),
            ocr_available=bool(best.get("words_df") is not None and not best.get("words_df").empty if best else False),
            fallback_reason=page_info.get("fallback_reason") or "text_layer_candidate_insufficient",
        )
        ocr_meta.update({
            "ocr_required": True,
            "ocr_confidence": best.get("ocr_confidence", 0),
            "ocr_engine": best.get("ocr_engine"),
            "preprocess_candidate_name": best.get("preprocess"),
            "dpi": best.get("dpi"),
            "similarity_score": best.get("similarity_score"),
        })
        for row in rows:
            row.update({key: value for key, value in ocr_meta.items() if key not in row})
        fallback_rows = candidate_rows_from_ocr_lines(best.get("words_df"), source_pdf=pdf_file, source_page=page_index, extraction_method="ocr_line_candidate") if best.get("words_df") is not None and not best.get("words_df").empty else []
        rows = _merge_ocr_line_fallback(rows, fallback_rows, ocr_meta)
        _save_ocr_fallback_debug(project_root, pdf_file, page_index, preprocessed=best.get("image"), words_df=best.get("words_df"), candidate_rows=rows, diagnostics={"page_info": page_info, "ocr_meta": ocr_meta})
        if rows:
            return rows, screening.get("report", {}).get("candidates", [])
        if best.get("words_df") is not None and not best.get("words_df").empty:
            ocr_text = get_page_ocr_text(best["words_df"])
            return [_make_candidate(
                pdf_file,
                page_index,
                "ocr_text",
                None,
                ocr_text,
                warnings=["OCR screening text was extracted but no load-table row could be reconstructed."],
                extra=ocr_meta,
            )], screening.get("report", {}).get("candidates", [])

    rows = []
    diagnostics = []
    dpi_values = [int(ocr_settings.get("dpi", 300))]
    fallback_dpi = int(ocr_settings.get("fallback_dpi", 400))
    if fallback_dpi not in dpi_values:
        dpi_values.append(fallback_dpi)

    slug = _debug_slug(pdf_file)
    debug_dir = Path(debug_root) / slug
    save_debug = bool(ocr_settings.get("save_debug_images", True))

    best = {"words": None, "confidence": -1, "dpi": None, "preprocessed": {}, "image": None, "error": None, "engine": None}
    for dpi in dpi_values:
        rendered = render_pdf_page(
            pdf_file,
            page_index,
            dpi=dpi,
            debug_dir=(debug_dir / "rendered") if save_debug else None,
            output_name=f"page_{page_index:03d}_rendered_{dpi}dpi.png",
        )
        preprocessed = preprocess_for_ocr(
            rendered,
            debug_dir=(debug_dir / "preprocessed") if save_debug else None,
            page_label=f"page_{page_index:03d}",
        )
        words_df, ocr_error, engine = run_ocr_with_priority(
            preprocessed["image"],
            engine_priority=ocr_settings.get("engine_priority"),
            source_page=page_index,
            psm_candidates=ocr_settings.get("psm_candidates"),
        )
        confidence = estimate_ocr_confidence(words_df)
        diagnostics.append({"dpi": dpi, "ocr_confidence": confidence, "ocr_error": ocr_error, "engine": engine})
        if confidence > best["confidence"]:
            best.update({
                "words": words_df,
                "confidence": confidence,
                "dpi": dpi,
                "preprocessed": preprocessed,
                "image": preprocessed["image"],
                "error": ocr_error,
                "engine": engine,
            })
        if confidence >= float(ocr_settings.get("min_ocr_confidence", 60)):
            break

    words_df = best["words"]
    ocr_text = get_page_ocr_text(words_df)
    ocr_available = words_df is not None and not words_df.empty
    if save_debug:
        if words_df is not None:
            _write_json(debug_dir / "json" / f"page_{page_index:03d}_ocr_words.json", words_df.to_dict("records"))
        if best["image"] is not None:
            _draw_ocr_overlay(best["image"], words_df, debug_dir / "ocr_overlay" / f"page_{page_index:03d}_ocr_overlay.png")

    ocr_meta = _page_meta(
        page_info,
        method="ocr_fallback",
        confidence=max(best["confidence"], 0),
        deskew=best["preprocessed"].get("page_deskew_applied", False),
        render_dpi=best["dpi"],
        ocr_available=ocr_available,
        fallback_reason=page_info.get("fallback_reason") or "text_layer_candidate_insufficient",
    )
    ocr_meta.update({
        "ocr_required": True,
        "ocr_confidence": max(best["confidence"], 0),
        "ocr_engine": best["engine"],
        "ocr_text_length": len(ocr_text),
        "page_rotation_detected": bool(page_info.get("page_rotation_detected") or best["preprocessed"].get("page_rotation_detected")),
    })

    if ocr_available:
        rows = reconstruct_table_candidates(
            words_df,
            source_pdf=pdf_file,
            source_page=page_index,
            ocr_confidence=max(best["confidence"], 0),
            extraction_method="ocr_fallback",
        )
        for row in rows:
            row.update({key: value for key, value in ocr_meta.items() if key not in row})
        fallback_rows = candidate_rows_from_ocr_lines(words_df, source_pdf=pdf_file, source_page=page_index, extraction_method="ocr_line_candidate")
        rows = _merge_ocr_line_fallback(rows, fallback_rows, ocr_meta)
        if not rows:
            rows = [_make_candidate(
                pdf_file, page_index, "ocr_text", None, ocr_text,
                warnings=["OCR text was extracted but no load-table row could be reconstructed."],
                extra=ocr_meta,
            )]
    else:
        rows = [_error_candidate(pdf_file, page_index, best["error"] or "OCR fallback produced no words.", extra=ocr_meta)]

    _save_ocr_fallback_debug(project_root, pdf_file, page_index, image=None, preprocessed=best.get("image"), words_df=words_df, candidate_rows=rows, diagnostics={"page_info": page_info, "ocr_meta": ocr_meta, "diagnostics": diagnostics, "error": best.get("error")})

    if save_debug:
        table_debug = {
            "line_rows": build_rows_from_ocr_words(words_df) if words_df is not None and not words_df.empty else [],
            "diagnostics": diagnostics,
        }
        _write_json(debug_dir / "table_candidates" / f"page_{page_index:03d}_table_candidates.json", table_debug)
        _write_json(debug_dir / "json" / f"page_{page_index:03d}_final_rows.json", rows)
    return rows, diagnostics


def extract_pdf_load_candidates(input_dir):
    input_path = Path(input_dir)
    candidates = []
    page_diagnostics = []
    ocr_settings, root_dir = _load_settings(input_path)
    debug_root = Path(root_dir) / str(ocr_settings.get("debug_dir", "debug"))

    if not input_path.exists():
        return [_error_candidate("", None, f"Input folder not found: {input_path}")]

    for pdf_file in sorted(input_path.glob("*.pdf")):
        pdf_debug_slug = _debug_slug(pdf_file)
        pdf_debug_dir = debug_root / pdf_debug_slug
        try:
            with pdfplumber.open(pdf_file) as pdf:
                for page_index, page in enumerate(pdf.pages, start=1):
                    page_info = analyze_page(
                        pdf_file,
                        page_index,
                        plumber_page=page,
                        min_text_length=int(ocr_settings.get("min_text_length_for_text_pdf", 50)),
                    )
                    page_rows = []
                    text_rows = []
                    if page_info["text_extraction_available"]:
                        text_rows = _extract_from_text_layer(pdf_file, page_index, page, page_info)
                        if text_rows:
                            page_rows.extend(text_rows)

                    text_rows_sufficient = bool(text_rows) and bool(page_info.get("text_extraction_available")) and page_info.get("extracted_text_length", 0) >= int(ocr_settings.get("min_text_length_for_text_pdf", 50))
                    ocr_diagnostics = []
                    if not text_rows_sufficient:
                        if ocr_settings.get("enabled", True):
                            ocr_rows, ocr_diagnostics = _extract_from_ocr_fallback(pdf_file, page_index, page_info, ocr_settings, debug_root)
                            page_rows.extend(ocr_rows)
                        else:
                            page_rows.append(_error_candidate(
                                pdf_file,
                                page_index,
                                "Text extraction was insufficient and OCR is disabled.",
                                extra=_page_meta(page_info, method="none", fallback_reason="ocr_disabled"),
                            ))

                    page_rows = _dedupe_rows(page_rows)
                    if not page_rows:
                        page_rows.append(_error_candidate(
                            pdf_file,
                            page_index,
                            "No load candidates were extracted from text layer or OCR fallback.",
                            extra=_page_meta(page_info, method="none", fallback_reason="no_candidates"),
                        ))
                    candidates.extend(page_rows)

                    page_diag = dict(page_info)
                    page_diag.pop("page_text", None)
                    page_diag["source_pdf"] = pdf_file.name
                    page_diag["source_page"] = page_index
                    page_diag["render_dpi"] = max([item.get("dpi") or 0 for item in ocr_diagnostics] or [None])
                    page_diag["ocr_available"] = any((item.get("ocr_confidence") or 0) > 0 for item in ocr_diagnostics)
                    page_diag["ocr_diagnostics"] = ocr_diagnostics
                    page_diagnostics.append(page_diag)
        except Exception as exc:
            candidates.append(_error_candidate(pdf_file, None, f"PDF open failed: {exc}"))

        if ocr_settings.get("save_debug_images", True):
            matching_diags = [item for item in page_diagnostics if item.get("source_pdf") == pdf_file.name]
            _write_json(pdf_debug_dir / "page_diagnostics.json", matching_diags)

    return candidates
