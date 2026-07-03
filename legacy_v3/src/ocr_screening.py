import difflib
import json
import re
from pathlib import Path

import numpy as np
from PIL import Image

from image_preprocess import detect_table_regions, generate_preprocess_candidates, upscale_image
from ocr_engine import estimate_ocr_confidence, get_page_ocr_text, run_ocr_with_priority
from ocr_text_normalizer import normalize_keyword_text
from pdf_render import render_pdf_page
from table_reconstructor import build_rows_from_ocr_words, reconstruct_table_candidates
from unit_normalizer import UNIT_PATTERN, VALUE_UNIT_PATTERN


LOAD_KEYWORDS = [
    "SLAB", "슬래브", "바닥", "고정하중", "활하중", "적재하중", "합계", "사용하중", "계수하중",
    "지붕층", "태양광", "화장실", "주차장", "로비", "홀", "업무시설", "kN/m2", "kN/㎡", "kN/m²",
]
NUMBER_PATTERN = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")


def _limit_ocr_image_size(image, max_side=2600):
    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_side:
        return image
    scale = max_side / float(longest)
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
    pil_mode = "L" if image.ndim == 2 else "RGB"
    return np.array(Image.fromarray(image).convert(pil_mode).resize(new_size, Image.Resampling.BICUBIC))


def _tokens(text, values):
    compact = normalize_keyword_text(text)
    return [value for value in values if normalize_keyword_text(value) in compact]


def _rate(matches, total):
    return len(matches) / total if total else 0.0


def _reference_text(reference):
    if not reference:
        return ""
    parts = []
    for page in reference.get("pages", []):
        parts.append(page.get("raw_text", ""))
        for row in page.get("load_rows", []):
            parts.append(row.get("source_text") or row.get("raw_text") or "")
    return " ".join(parts)


def _reference_numbers(reference):
    text = _reference_text(reference)
    numbers = NUMBER_PATTERN.findall(text)
    return sorted(set(numbers))


def _reference_keywords(reference):
    text = _reference_text(reference)
    found = _tokens(text, LOAD_KEYWORDS)
    return sorted(set(found or LOAD_KEYWORDS))


def score_ocr_candidate(words_df, reference=None):
    text = get_page_ocr_text(words_df)
    reference_text = _reference_text(reference)
    text_similarity = difflib.SequenceMatcher(None, normalize_keyword_text(reference_text), normalize_keyword_text(text)).ratio() if reference_text else 0.0

    reference_keywords = _reference_keywords(reference)
    keyword_matches = _tokens(text, reference_keywords)
    keyword_match_rate = _rate(keyword_matches, len(reference_keywords))

    reference_numbers = _reference_numbers(reference)
    text_numbers = NUMBER_PATTERN.findall(text)
    number_matches = [num for num in reference_numbers if num in text_numbers]
    number_match_rate = _rate(number_matches, len(reference_numbers))

    reference_units = ["kN", "kN/m2", "kN/m²", "kN/㎡", "kPa", "kgf/m2", "tf/m2"]
    unit_matches = _tokens(text, reference_units)
    unit_match_rate = min(1.0, _rate(unit_matches, 3))

    rows = build_rows_from_ocr_words(words_df)
    value_rows = [row for row in rows if VALUE_UNIT_PATTERN.search(row.get("raw_text", ""))]
    table_structure_score = min(1.0, (len(value_rows) / 5.0) * 0.7 + (len(rows) / 20.0) * 0.3) if rows else 0.0

    ocr_confidence = estimate_ocr_confidence(words_df)
    confidence_score = min(1.0, ocr_confidence / 100.0)

    if reference:
        similarity_score = (
            text_similarity * 0.20
            + keyword_match_rate * 0.25
            + number_match_rate * 0.25
            + unit_match_rate * 0.10
            + table_structure_score * 0.10
            + confidence_score * 0.10
        )
    else:
        similarity_score = (
            keyword_match_rate * 0.35
            + min(1.0, len(text_numbers) / 8.0) * 0.25
            + min(1.0, len(UNIT_PATTERN.findall(text)) / 3.0) * 0.15
            + table_structure_score * 0.10
            + confidence_score * 0.15
        )

    return {
        "similarity_score": round(float(similarity_score), 4),
        "text_similarity": round(float(text_similarity), 4),
        "keyword_match_rate": round(float(keyword_match_rate), 4),
        "number_match_rate": round(float(number_match_rate), 4),
        "unit_match_rate": round(float(unit_match_rate), 4),
        "table_structure_score": round(float(table_structure_score), 4),
        "ocr_confidence": ocr_confidence,
        "keyword_matches": keyword_matches,
        "number_matches": number_matches,
    }


def run_ocr_screening(
    pdf_path,
    page_index,
    ocr_settings,
    debug_dir=None,
    reference=None,
    extraction_method="ocr_screening",
    target_label="ocr",
    color_mode=None,
):
    dpi_candidates = ocr_settings.get("dpi_candidates") or [ocr_settings.get("default_dpi") or ocr_settings.get("dpi") or 400]
    max_candidates = int((ocr_settings.get("screening") or {}).get("max_candidates", 12))
    all_candidates = []
    best = None
    debug_dir = Path(debug_dir) if debug_dir else None

    for dpi in dpi_candidates:
        rendered = render_pdf_page(
            pdf_path,
            page_index,
            dpi=int(dpi),
            debug_dir=(debug_dir / f"rendered_{target_label}") if debug_dir else None,
            output_name=f"page_{page_index:03d}_{int(dpi)}dpi.png",
        )
        preprocess_dir = debug_dir / f"preprocess_candidates_{target_label}" if debug_dir else None
        preprocess_candidates = generate_preprocess_candidates(
            rendered,
            debug_dir=preprocess_dir,
            page_label=f"page_{page_index:03d}",
            max_candidates=max_candidates,
        )
        for preprocessed in preprocess_candidates:
            words_df, error, engine = run_ocr_with_priority(
                _limit_ocr_image_size(preprocessed["image"], max_side=int((ocr_settings.get("screening") or {}).get("ocr_max_image_side", 2600))),
                engine_priority=ocr_settings.get("engine_priority"),
                source_page=page_index,
                extraction_method=extraction_method,
                psm_candidates=ocr_settings.get("psm_candidates"),
            )
            if words_df is not None and not words_df.empty:
                words_df = words_df.copy()
                words_df["engine"] = engine or ""
                words_df["preprocess_candidate_name"] = preprocessed["name"]
                words_df["dpi"] = int(dpi)
                words_df["color_mode"] = color_mode or ""
            score = score_ocr_candidate(words_df, reference=reference)
            item = {
                "pdf": Path(pdf_path).name,
                "page": page_index,
                "dpi": int(dpi),
                "preprocess": preprocessed["name"],
                "ocr_engine": engine,
                "ocr_error": error,
                **score,
                "words_df": words_df,
                "image": preprocessed["image"],
                "preprocess_debug": preprocessed.get("debug", {}),
            }
            all_candidates.append(item)
            if best is None or item["similarity_score"] > best["similarity_score"]:
                best = item

        crop_regions = detect_table_regions(rendered)[:3]
        for crop_index, region in enumerate(crop_regions, start=1):
            x = max(0, int(region.get("x", 0)))
            y = max(0, int(region.get("y", 0)))
            w = max(1, int(region.get("width", 0)))
            h = max(1, int(region.get("height", 0)))
            crop = rendered[y:y + h, x:x + w]
            if crop.size == 0:
                continue
            crop = upscale_image(crop, scale=2)
            if debug_dir:
                crop_dir = debug_dir / f"table_crops_{target_label}"
                crop_dir.mkdir(parents=True, exist_ok=True)
                crop_path = crop_dir / f"page_{page_index:03d}_table_crop_{crop_index:03d}.png"
                Image.fromarray(crop).save(crop_path)
            words_df, error, engine = run_ocr_with_priority(
                _limit_ocr_image_size(crop, max_side=int((ocr_settings.get("screening") or {}).get("ocr_max_image_side", 2600))),
                engine_priority=ocr_settings.get("engine_priority"),
                source_page=page_index,
                extraction_method=extraction_method,
                psm_candidates=ocr_settings.get("psm_candidates"),
            )
            if words_df is not None and not words_df.empty:
                words_df = words_df.copy()
                words_df["engine"] = engine or ""
                words_df["preprocess_candidate_name"] = f"table_crop_{crop_index:03d}"
                words_df["dpi"] = int(dpi)
                words_df["color_mode"] = color_mode or ""
            score = score_ocr_candidate(words_df, reference=reference)
            item = {
                "pdf": Path(pdf_path).name,
                "page": page_index,
                "dpi": int(dpi),
                "preprocess": f"table_crop_{crop_index:03d}",
                "ocr_engine": engine,
                "ocr_error": error,
                "crop_region": region,
                **score,
                "words_df": words_df,
                "image": crop,
                "preprocess_debug": {"crop_region": region},
            }
            all_candidates.append(item)
            if debug_dir:
                crop_text_path = debug_dir / f"table_crops_{target_label}" / f"page_{page_index:03d}_table_crop_{crop_index:03d}_ocr_text.txt"
                crop_text_path.write_text(get_page_ocr_text(words_df), encoding="utf-8")
            if best is None or item["similarity_score"] > best["similarity_score"]:
                best = item

    candidate_reports = [{key: value for key, value in item.items() if key not in {"words_df", "image"}} for item in all_candidates]
    report = {
        "best_candidate": {key: value for key, value in (best or {}).items() if key not in {"words_df", "image"}},
        "candidates": candidate_reports,
    }
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        with open(debug_dir / f"page_{page_index:03d}_selected_ocr_result.json", "w", encoding="utf-8") as file:
            json.dump(report["best_candidate"], file, ensure_ascii=False, indent=2, default=str)
    rows = []
    if best and best.get("words_df") is not None:
        rows = reconstruct_table_candidates(
            best["words_df"],
            source_pdf=pdf_path,
            source_page=page_index,
            ocr_confidence=best["ocr_confidence"],
            extraction_method=extraction_method,
        )
        for row in rows:
            row["preprocess_candidate_name"] = best["preprocess"]
            row["ocr_engine"] = best["ocr_engine"]
            row["dpi"] = best["dpi"]
            row["similarity_score"] = best["similarity_score"]
            row["color_mode"] = color_mode
            row["extraction_method"] = extraction_method
    return {"best": best, "rows": rows, "report": report}
