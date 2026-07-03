import re

try:
    import fitz
except Exception:  # pragma: no cover - depends on local install
    fitz = None


LOAD_PATTERN = re.compile(
    r"고정하중|활하중|적재하중|풍하중|지진하중|적설하중|토압|수압|온도하중|장비하중|합계|총계|사용하중|계수하중|LOAD|DL|LL|DEAD|LIVE|SLAB|슬래브|바닥|지붕|옥상|태양광",
    re.IGNORECASE,
)
NUMBER_UNIT_PATTERN = re.compile(r"\d+(?:\.\d+)?\s*(?:kN|KN|kPa|kgf|tf|ton|t)(?:\s*/\s*(?:m2|m²|㎡|m))?", re.IGNORECASE)


def _extract_text_with_fitz(pdf_path, page_index):
    if fitz is None:
        return "", 0, 0, 0, 0, "PyMuPDF is not available"
    with fitz.open(pdf_path) as doc:
        page = doc[page_index - 1]
        rect = page.rect
        return (
            page.get_text("text") or "",
            len(page.get_images(full=True)),
            float(rect.width),
            float(rect.height),
            int(page.rotation or 0),
            None,
        )


def analyze_page(pdf_path, page_index, plumber_page=None, min_text_length=50):
    text_parts = []
    text_error = None
    try:
        if plumber_page is not None:
            text_parts.append(plumber_page.extract_text() or "")
    except Exception as exc:
        text_error = f"pdfplumber text extraction failed: {exc}"

    image_count = 0
    page_width = 0
    page_height = 0
    rotation = 0
    try:
        fitz_text, image_count, page_width, page_height, rotation, fitz_error = _extract_text_with_fitz(pdf_path, page_index)
        text_parts.append(fitz_text)
        text_error = text_error or fitz_error
    except Exception as exc:
        text_error = text_error or f"PyMuPDF page analysis failed: {exc}"

    compact_text = " ".join(" ".join(text_parts).split())
    text_len = len(compact_text)
    load_keyword_matches = LOAD_PATTERN.findall(compact_text)
    has_load_keywords = bool(load_keyword_matches)
    unit_matches = NUMBER_UNIT_PATTERN.findall(compact_text)
    has_number_units = len(unit_matches) >= 1
    text_available = text_len >= min_text_length and (has_load_keywords or has_number_units)

    fallback_reasons = []
    if text_len < min_text_length:
        fallback_reasons.append("text_length_below_threshold")
    if not has_load_keywords and len(unit_matches) < 1:
        fallback_reasons.append("missing_load_keywords_and_number_units")
    if text_error:
        fallback_reasons.append("text_extraction_error")
    if image_count > 0 and text_len < min_text_length:
        fallback_reasons.append("image_objects_with_sparse_text")
    if image_count > 0:
        fallback_reasons.append("image_object_present")

    ocr_required = bool(fallback_reasons)
    if not text_available and image_count >= 50:
        page_type = "image_tiled_or_rasterized"
        if "image_tiled_or_rasterized" not in fallback_reasons:
            fallback_reasons.append("image_tiled_or_rasterized")
    elif text_available and image_count:
        page_type = "mixed_pdf"
    elif text_available:
        page_type = "text_pdf"
    elif image_count:
        page_type = "image_based_pdf"
    else:
        page_type = "ocr_required_pdf"

    confidence = 0.0
    if text_len >= min_text_length:
        confidence += 40
    if has_load_keywords:
        confidence += 30
    if has_number_units:
        confidence += 30

    return {
        "pdf_page_type": page_type,
        "text_extraction_available": text_available,
        "ocr_required": ocr_required,
        "ocr_available": None,
        "extraction_method": "text_layer" if text_available else "ocr_fallback",
        "extraction_confidence": min(confidence, 100.0),
        "fallback_reason": "; ".join(fallback_reasons),
        "page_rotation_detected": rotation not in (0, 360),
        "page_deskew_applied": False,
        "page_text": compact_text,
        "extracted_text": compact_text,
        "text_layer_exists": bool(text_len > 0),
        "extracted_text_length": text_len,
        "extracted_text_preview": compact_text[:300],
        "image_object_count": image_count,
        "image_count": image_count,
        "text_length": text_len,
        "page_width": page_width,
        "page_height": page_height,
        "page_rotation": rotation,
        "page_analysis_error": text_error,
        "load_keyword_detected": has_load_keywords,
        "load_table_keywords_found": len(load_keyword_matches),
        "number_unit_pattern_count": len(unit_matches),
    }


analyze_pdf_page = analyze_page
