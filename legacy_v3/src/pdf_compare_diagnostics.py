import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import pdfplumber
import yaml
from PIL import Image, ImageDraw

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from compare_extraction_results import compare_reference_and_ocr
from load_parser import parse_load_rows
from ocr_screening import LOAD_KEYWORDS, NUMBER_PATTERN, run_ocr_screening
from ocr_text_normalizer import normalize_keyword_text
from pdf_extract import _extract_from_text_layer
from pdf_page_analyzer import analyze_pdf_page
from pdf_render import render_pdf_page
from table_reconstructor import build_rows_from_ocr_words
from unit_normalizer import UNIT_PATTERN


DEFAULT_SETTINGS = {
    "min_text_length_for_text_pdf": 50,
    "dpi_candidates": [300, 400, 600],
    "default_dpi": 400,
    "min_ocr_confidence": 55,
    "engine_priority": ["tesseract", "paddleocr", "easyocr"],
    "screening": {"max_candidates": 12, "reference_similarity_threshold": 0.90},
}


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2, default=str)


def _load_settings():
    config_path = Path(__file__).resolve().parents[1] / "config" / "midas_settings.yml"
    settings = {}
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as file:
            settings = yaml.safe_load(file) or {}
    merged = DEFAULT_SETTINGS.copy()
    merged.update(settings.get("ocr", {}) or {})
    return merged


def _keyword_count(text):
    compact = normalize_keyword_text(text)
    return sum(1 for keyword in LOAD_KEYWORDS if normalize_keyword_text(keyword) in compact)


def _diagnose_pdf(pdf_path, out_render_dir, settings, label):
    diagnostics = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            info = analyze_pdf_page(pdf_path, page_index, plumber_page=page, min_text_length=settings["min_text_length_for_text_pdf"])
            rendered = render_pdf_page(
                pdf_path,
                page_index,
                dpi=300,
                debug_dir=out_render_dir,
                output_name=f"page_{page_index:03d}_300dpi.png",
            )
            text = info.get("page_text", "")
            diag = {
                "source_pdf": Path(pdf_path).name,
                "source_page": page_index,
                "page_count": len(pdf.pages),
                "page_width": info.get("page_width"),
                "page_height": info.get("page_height"),
                "page_rotation": info.get("page_rotation"),
                "text_layer_exists": bool(info.get("extracted_text_length", 0) > 0),
                "extracted_text_length": info.get("extracted_text_length"),
                "extracted_text_preview": info.get("extracted_text_preview"),
                "image_object_count": info.get("image_object_count"),
                "render_dpi": 300,
                "rendered_width": int(rendered.shape[1]),
                "rendered_height": int(rendered.shape[0]),
                "pdf_page_type": info.get("pdf_page_type"),
                "ocr_required": info.get("ocr_required"),
                "ocr_engine_used": None,
                "ocr_confidence": None,
                "extraction_method": "text_layer" if info.get("text_extraction_available") else "ocr_required",
                "table_candidate_count": 0,
                "load_keyword_count": _keyword_count(text),
                "number_pattern_count": len(NUMBER_PATTERN.findall(text)),
                "unit_pattern_count": len(UNIT_PATTERN.findall(text)),
                "fallback_reason": info.get("fallback_reason"),
                "label": label,
            }
            diagnostics.append(diag)
    return diagnostics


def _rows_to_reference(pdf_path, settings):
    pages = []
    all_raw_rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            info = analyze_pdf_page(pdf_path, page_index, plumber_page=page, min_text_length=settings["min_text_length_for_text_pdf"])
            raw_rows = _extract_from_text_layer(pdf_path, page_index, page, info)
            parsed_rows = parse_load_rows(raw_rows)
            all_raw_rows.extend(raw_rows)
            text = info.get("page_text", "")
            pages.append({
                "page": page_index,
                "text_length": info.get("extracted_text_length"),
                "raw_text": text,
                "raw_rows": raw_rows,
                "parsed_rows": parsed_rows,
                "load_rows": [
                    {
                        "floor_usage_name": row.get("floor_usage_name"),
                        "load_item": row.get("load_item") or row.get("raw_text"),
                        "load_type": row.get("structural_load_type") or row.get("load_component_type"),
                        "original_value": row.get("original_value", row.get("load_value")),
                        "original_unit": row.get("original_unit", row.get("unit")),
                        "normalized_value": row.get("normalized_value", row.get("load_value_kn_per_m2")),
                        "normalized_unit": row.get("normalized_unit", row.get("unit")),
                        "row_index": row.get("row_index"),
                        "col_index": row.get("col_index"),
                        "source_text": row.get("raw_text"),
                    }
                    for row in parsed_rows
                ],
                "keywords": [keyword for keyword in LOAD_KEYWORDS if normalize_keyword_text(keyword) in normalize_keyword_text(text)],
            })
    return {"source_pdf": Path(pdf_path).name, "pages": pages, "raw_rows": all_raw_rows}


def _draw_best_overlay(image, words_df, path):
    image = Image.fromarray(image).convert("RGB")
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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def _ocr_target(pdf_path, out_dir, settings, reference):
    pages = []
    similarity_candidates = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, _page in enumerate(pdf.pages, start=1):
            screening = run_ocr_screening(pdf_path, page_index, settings, debug_dir=out_dir, reference=reference)
            best = screening.get("best") or {}
            words_df = best.get("words_df")
            rows = screening.get("rows") or []
            line_rows = build_rows_from_ocr_words(words_df) if words_df is not None and not words_df.empty else []
            _write_json(out_dir / "table_candidates_3" / f"page_{page_index:03d}_table_candidates.json", line_rows)
            if best.get("image") is not None:
                _draw_best_overlay(best["image"], words_df, out_dir / "ocr_overlay_3" / f"page_{page_index:03d}_best_overlay.png")
            pages.append({
                "page": page_index,
                "best_candidate": {key: value for key, value in best.items() if key not in {"words_df", "image"}},
                "load_rows": rows,
                "ocr_words": words_df.to_dict("records") if words_df is not None and not words_df.empty else [],
                "table_rows": line_rows,
            })
            similarity_candidates.extend(screening.get("report", {}).get("candidates", []))
    return {"source_pdf": Path(pdf_path).name, "pages": pages}, {"best_candidate": pages[0].get("best_candidate") if pages else {}, "candidates": similarity_candidates}


def run_compare(reference_pdf, target_pdf, out_dir):
    reference_pdf = Path(reference_pdf)
    target_pdf = Path(target_pdf)
    out_dir = Path(out_dir)
    settings = _load_settings()

    for folder in ["rendered_2", "rendered_3", "preprocess_candidates_3", "ocr_overlay_3", "table_candidates_3", "json", "reports"]:
        (out_dir / folder).mkdir(parents=True, exist_ok=True)

    diag_2 = _diagnose_pdf(reference_pdf, out_dir / "rendered_2", settings, "reference_2")
    diag_3 = _diagnose_pdf(target_pdf, out_dir / "rendered_3", settings, "target_3")
    reference = _rows_to_reference(reference_pdf, settings)
    ocr, similarity = _ocr_target(target_pdf, out_dir, settings, reference)
    diff = compare_reference_and_ocr(reference, ocr, threshold=(settings.get("screening") or {}).get("reference_similarity_threshold", 0.90))

    _write_json(out_dir / "json" / "page_diagnostics_2.json", diag_2)
    _write_json(out_dir / "json" / "page_diagnostics_3.json", diag_3)
    _write_json(out_dir / "json" / "reference_from_2.json", reference)
    _write_json(out_dir / "json" / "ocr_from_3.json", ocr)
    _write_json(out_dir / "reports" / "similarity_report.json", similarity)
    _write_json(out_dir / "reports" / "diff_report.json", diff)
    return {"diagnostics_2": diag_2, "diagnostics_3": diag_3, "similarity": similarity, "diff": diff}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--out", default="debug/yeoksam_compare")
    args = parser.parse_args()
    result = run_compare(args.reference, args.target, args.out)
    print(json.dumps({
        "reference_pages": len(result["diagnostics_2"]),
        "target_pages": len(result["diagnostics_3"]),
        "best_candidate": result["similarity"].get("best_candidate"),
        "diff_summary": result["diff"].get("summary"),
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
