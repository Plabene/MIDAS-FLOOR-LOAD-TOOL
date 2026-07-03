from compare_extraction_results import compare_reference_and_ocr


def compare_scan_result(reference, ocr, threshold=0.90):
    report = compare_reference_and_ocr(reference, ocr, threshold=threshold)
    summary = report.setdefault("summary", {})
    summary.setdefault("table_structure_score", summary.get("overall_similarity", 0))
    summary.setdefault("item_match_rate", summary.get("overall_similarity", 0))
    for item in report.get("mismatched_items", []):
        item.setdefault("reference_value", (item.get("reference") or {}).get("normalized_value"))
        item.setdefault("ocr_value", (item.get("ocr") or {}).get("normalized_value"))
        item.setdefault("original_image_bbox", (item.get("ocr") or {}).get("bbox"))
        item.setdefault("confidence", (item.get("ocr") or {}).get("ocr_confidence"))
        item.setdefault("ocr_candidate_values", [])
        item.setdefault("alternative_candidates", [])
        item.setdefault("review_required", True)
    return report
