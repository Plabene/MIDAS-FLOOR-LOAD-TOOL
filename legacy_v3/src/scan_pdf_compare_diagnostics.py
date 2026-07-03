import argparse
import json
import sys
from pathlib import Path

import pdfplumber
import yaml
from PIL import Image, ImageDraw

CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from compare_scan_results import compare_scan_result
from image_preprocess import scan_quality_metrics
from load_parser import parse_load_rows
from ocr_screening import LOAD_KEYWORDS, NUMBER_PATTERN
from ocr_text_normalizer import normalize_keyword_text
from pdf_compare_diagnostics import _diagnose_pdf, _extract_from_text_layer, _rows_to_reference
from pdf_page_analyzer import analyze_pdf_page
from pdf_render import render_pdf_page
from scan_ocr_screening import run_scan_ocr_screening, target_label_from_pdf
from table_reconstructor import build_rows_from_ocr_words
from unit_normalizer import UNIT_PATTERN


DEFAULT_SETTINGS = {
    "min_text_length_for_text_pdf": 50,
    "dpi_candidates": [300, 400, 600],
    "default_dpi": 400,
    "min_ocr_confidence": 55,
    "engine_priority": ["tesseract", "paddleocr", "easyocr"],
    "screening": {"max_candidates": 20, "ocr_max_candidates": 1, "ocr_dpi_candidates": [300], "ocr_max_image_side": 1600, "reference_similarity_threshold": 0.90},
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
    merged["screening"] = {**DEFAULT_SETTINGS["screening"], **(settings.get("ocr", {}).get("screening", {}) if settings else {})}
    return merged


def _keyword_count(text):
    compact = normalize_keyword_text(text)
    return sum(1 for keyword in LOAD_KEYWORDS if normalize_keyword_text(keyword) in compact)


def _draw_overlay(image, words_df, path):
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


def _target_diagnostics(pdf_path, out_dir, settings, label):
    rendered_dir = out_dir / f"rendered_{label}"
    diagnostics = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            info = analyze_pdf_page(pdf_path, page_index, plumber_page=page, min_text_length=settings["min_text_length_for_text_pdf"])
            rendered = None
            for dpi in settings.get("dpi_candidates", [300, 400, 600]):
                rendered = render_pdf_page(pdf_path, page_index, dpi=int(dpi), debug_dir=rendered_dir, output_name=f"page_{page_index:03d}_{int(dpi)}dpi.png")
            metrics = scan_quality_metrics(rendered)
            text = info.get("page_text", "")
            diagnostics.append({
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
                "estimated_dpi": settings.get("default_dpi", 400),
                **metrics,
                "ocr_required": info.get("ocr_required"),
                "ocr_engine_used": None,
                "ocr_confidence": None,
                "extraction_method": "scan_ocr_required" if info.get("ocr_required") else "text_layer",
                "table_candidate_count": 0,
                "load_keyword_count": _keyword_count(text),
                "number_pattern_count": len(NUMBER_PATTERN.findall(text)),
                "unit_pattern_count": len(UNIT_PATTERN.findall(text)),
                "fallback_reason": info.get("fallback_reason"),
            })
    return diagnostics


def _baseline_from_text(pdf_path, settings):
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, page in enumerate(pdf.pages, start=1):
            info = analyze_pdf_page(pdf_path, page_index, plumber_page=page, min_text_length=settings["min_text_length_for_text_pdf"])
            raw_rows = _extract_from_text_layer(pdf_path, page_index, page, info) if info.get("text_extraction_available") else []
            pages.append({
                "page": page_index,
                "raw_rows": raw_rows,
                "parsed_rows": parse_load_rows(raw_rows) if raw_rows else [],
                "diagnostics": {k: v for k, v in info.items() if k != "page_text"},
            })
    return {"source_pdf": Path(pdf_path).name, "pages": pages}


def _ocr_scan_target(pdf_path, out_dir, settings, reference):
    label = target_label_from_pdf(pdf_path)
    screening_settings = dict(settings)
    screening_settings["dpi_candidates"] = (settings.get("screening") or {}).get("ocr_dpi_candidates", [settings.get("default_dpi", 400)])
    screening_settings["screening"] = dict(settings.get("screening") or {})
    screening_settings["screening"]["max_candidates"] = int(screening_settings["screening"].get("ocr_max_candidates", 6))
    pages = []
    report_candidates = []
    with pdfplumber.open(pdf_path) as pdf:
        for page_index, _page in enumerate(pdf.pages, start=1):
            result = run_scan_ocr_screening(pdf_path, page_index, screening_settings, debug_dir=out_dir, reference=reference)
            best = result.get("best") or {}
            words_df = best.get("words_df")
            rows = result.get("rows") or []
            table_rows = build_rows_from_ocr_words(words_df) if words_df is not None and not words_df.empty else []
            _write_json(out_dir / "table_candidates" / f"page_{page_index:03d}_target_{label}_table_candidates.json", table_rows)
            if best.get("image") is not None:
                selected_path = out_dir / "selected_preprocessed" / f"page_{page_index:03d}_target_{label}_{best.get('preprocess')}.png"
                selected_path.parent.mkdir(parents=True, exist_ok=True)
                Image.fromarray(best["image"]).save(selected_path)
                _draw_overlay(best["image"], words_df, out_dir / "ocr_overlay" / f"page_{page_index:03d}_target_{label}_overlay.png")
            pages.append({
                "page": page_index,
                "best_candidate": {k: v for k, v in best.items() if k not in {"words_df", "image"}},
                "load_rows": rows,
                "ocr_words": words_df.to_dict("records") if words_df is not None and not words_df.empty else [],
                "table_rows": table_rows,
            })
            report_candidates.extend((result.get("report") or {}).get("candidates", []))
    return {"source_pdf": Path(pdf_path).name, "pages": pages}, {
        "best_candidate": pages[0].get("best_candidate") if pages else {},
        "candidates": report_candidates,
    }


def run_scan_compare(reference, targets, out):
    reference = Path(reference)
    targets = [Path(target) for target in targets]
    missing = [path for path in [reference, *targets] if not path.exists()]
    if missing:
        message = "비교용 PDF 파일이 없어 yeoksam scan 비교 진단을 건너뜁니다."
        print(message)
        return {"skipped": True, "message": message, "missing": [str(path) for path in missing]}

    settings = _load_settings()
    out = Path(out)
    for folder in [
        "rendered_2", "rendered_4", "rendered_5", "rendered_6",
        "preprocess_candidates_4", "preprocess_candidates_5", "preprocess_candidates_6",
        "selected_preprocessed", "ocr_overlay", "table_candidates", "json", "reports",
    ]:
        (out / folder).mkdir(parents=True, exist_ok=True)

    diag_2 = _diagnose_pdf(reference, out / "rendered_2", settings, "reference_2")
    reference_json = _rows_to_reference(reference, settings)
    _write_json(out / "json" / "page_diagnostics_2.json", diag_2)
    _write_json(out / "json" / "reference_from_2.json", reference_json)

    similarity_report = {"targets": {}}
    diff_reports = {}
    for target in targets:
        label = target_label_from_pdf(target)
        diagnostics = _target_diagnostics(target, out, settings, label)
        baseline = _baseline_from_text(target, settings)
        improved, similarity = _ocr_scan_target(target, out, settings, reference_json)
        diff = compare_scan_result(reference_json, improved, threshold=(settings.get("screening") or {}).get("reference_similarity_threshold", 0.90))
        _write_json(out / "json" / f"page_diagnostics_{label}.json", diagnostics)
        _write_json(out / "json" / f"baseline_from_{label}.json", baseline)
        _write_json(out / "json" / f"improved_from_{label}.json", improved)
        _write_json(out / "json" / f"ocr_from_{label}.json", improved)
        _write_json(out / "reports" / f"diff_report_{label}.json", diff)
        similarity_report["targets"][label] = similarity
        diff_reports[label] = diff
    _write_json(out / "reports" / "similarity_report.json", similarity_report)
    _write_json(out / "reports" / "baseline_vs_improved_summary.json", {
        label: report.get("summary", {}) for label, report in diff_reports.items()
    })
    return {"skipped": False, "similarity_report": similarity_report, "diff_reports": diff_reports}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", default="input_pdfs/구조계산서_역삼동2.pdf")
    parser.add_argument("--targets", nargs="+", default=[
        "input_pdfs/구조계산서_역삼동4.pdf",
        "input_pdfs/구조계산서_역삼동5.pdf",
        "input_pdfs/구조계산서_역삼동6.pdf",
    ])
    parser.add_argument("--out", default="debug/yeoksam_scan_compare")
    args = parser.parse_args()
    result = run_scan_compare(args.reference, args.targets, args.out)
    print(json.dumps(result if result.get("skipped") else {
        "skipped": False,
        "targets": list(result["similarity_report"].get("targets", {}).keys()),
        "summaries": {k: v.get("summary", {}) for k, v in result.get("diff_reports", {}).items()},
    }, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
