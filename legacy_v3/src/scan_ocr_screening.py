from pathlib import Path
import re

from image_preprocess import scan_quality_metrics
from ocr_screening import run_ocr_screening
from pdf_render import render_pdf_page


def target_label_from_pdf(pdf_path):
    stem = Path(pdf_path).stem
    label = re.sub(r"[^A-Za-z0-9가-힣_-]+", "_", stem).strip("_")
    return label or "scan"


def run_scan_ocr_screening(pdf_path, page_index, ocr_settings, debug_dir=None, reference=None):
    screening_settings = dict(ocr_settings)
    screening = dict(ocr_settings.get("screening") or {})
    screening_settings["dpi_candidates"] = screening.get("ocr_dpi_candidates", ocr_settings.get("dpi_candidates", [ocr_settings.get("default_dpi", 400)]))
    screening["max_candidates"] = int(screening.get("ocr_max_candidates", screening.get("max_candidates", 6)))
    screening_settings["screening"] = screening
    default_dpi = int(ocr_settings.get("default_dpi") or 400)
    image = render_pdf_page(pdf_path, page_index, dpi=default_dpi)
    metrics = scan_quality_metrics(image)
    label = target_label_from_pdf(pdf_path)
    result = run_ocr_screening(
        pdf_path,
        page_index,
        screening_settings,
        debug_dir=debug_dir,
        reference=reference,
        extraction_method="scan_ocr_screening",
        target_label=label,
        color_mode=metrics.get("color_mode"),
    )
    best = result.get("best") or {}
    best.setdefault("scan_metrics", metrics)
    for row in result.get("rows") or []:
        row.update(metrics)
        row["estimated_dpi"] = default_dpi
    return result
