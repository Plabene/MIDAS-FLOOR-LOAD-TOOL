import json
from pathlib import Path


def _load(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def _rows(data):
    rows = []
    for page in data.get("pages", []):
        rows.extend(page.get("load_rows", []))
    return rows


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compare_reference_and_ocr(reference, ocr, threshold=0.90):
    ref_rows = _rows(reference)
    ocr_rows = _rows(ocr)
    matched = []
    mismatched = []
    used = set()

    for ref in ref_rows:
        ref_value = _num(ref.get("normalized_value") or ref.get("original_value"))
        best = None
        best_diff = None
        for index, cand in enumerate(ocr_rows):
            if index in used:
                continue
            cand_value = _num(cand.get("normalized_value") or cand.get("original_value"))
            if ref_value is not None and cand_value is not None:
                diff = abs(ref_value - cand_value)
            else:
                diff = 0 if (ref.get("load_item") or "") == (cand.get("load_item") or "") else 999
            if best is None or diff < best_diff:
                best = (index, cand)
                best_diff = diff
        if best and best_diff is not None and best_diff <= 0.05:
            used.add(best[0])
            matched.append({"reference": ref, "ocr": best[1], "difference": best_diff})
        elif best:
            mismatched.append({
                "reference": ref,
                "ocr": best[1],
                "difference": best_diff,
                "review_required": True,
                "reason": "OCR 숫자 인식 차이 또는 항목 불일치",
            })
        else:
            mismatched.append({"reference": ref, "ocr": None, "review_required": True, "reason": "OCR에서 대응 항목을 찾지 못했습니다."})

    extra = [row for index, row in enumerate(ocr_rows) if index not in used]
    denominator = max(1, len(ref_rows))
    overall = len(matched) / denominator
    return {
        "summary": {
            "overall_similarity": round(overall, 4),
            "keyword_match_rate": round(overall, 4),
            "number_match_rate": round(overall, 4),
            "unit_match_rate": round(overall, 4),
            "passed_threshold": overall >= threshold,
            "threshold": threshold,
        },
        "matched_items": matched,
        "mismatched_items": mismatched,
        "missing_in_ocr": [item.get("reference") for item in mismatched if item.get("ocr") is None],
        "extra_in_ocr": extra,
    }


def write_diff_report(reference_path, ocr_path, out_path, threshold=0.90):
    report = compare_reference_and_ocr(_load(reference_path), _load(ocr_path), threshold=threshold)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2, default=str)
    return report
