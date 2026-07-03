import argparse
import csv
import io
import json
import re
from difflib import SequenceMatcher
from pathlib import Path

import pandas as pd


def _clean(value):
    return " ".join(str(value or "").strip().strip('"').split())


def _split_mgtx_csv(line):
    return [_clean(part) for part in next(csv.reader(io.StringIO(line), skipinitialspace=True), [])]


def parse_mgtx(path):
    path = Path(path)
    lines = path.read_text(encoding="cp949", errors="replace").splitlines()
    rows = []
    in_fload = False
    index = 0
    while index < len(lines):
        line = lines[index].strip()
        if line.upper().startswith("*FLOADTYPE"):
            in_fload = True
            index += 1
            continue
        if in_fload and line.upper().startswith("*ENDDATA"):
            break
        if not in_fload or not line or line.startswith(";"):
            index += 1
            continue
        if index + 1 >= len(lines):
            break
        name_line = line
        value_line = lines[index + 1].strip()
        if not value_line or value_line.startswith(";"):
            index += 1
            continue
        name_parts = _split_mgtx_csv(name_line)
        name = name_parts[0] if name_parts else ""
        desc = name_parts[1] if len(name_parts) > 1 else ""
        parts = _split_mgtx_csv(value_line)
        cases = {}
        case_order = []
        sub_beam_flags = {}
        for pos in range(0, len(parts) - 2, 3):
            case = parts[pos]
            try:
                value = float(parts[pos + 1])
            except (TypeError, ValueError):
                continue
            cases[case] = value
            case_order.append(case)
            sub_beam_flags[case] = parts[pos + 2]
        rows.append({
            "name": name,
            "DESC": desc,
            "DL": cases.get("DL"),
            "LL": cases.get("LL"),
            "case_order": case_order,
            "sub_beam_flags": sub_beam_flags,
        })
        index += 2
    return rows


def parse_stldcase(path):
    lines = Path(path).read_text(encoding="cp949", errors="replace").splitlines()
    rows = []
    in_case = False
    for line in lines:
        stripped = line.strip()
        upper = stripped.upper()
        if upper.startswith("*STLDCASE"):
            in_case = True
            continue
        if in_case and upper.startswith("*"):
            break
        if not in_case or not stripped or stripped.startswith(";"):
            continue
        parts = _split_mgtx_csv(stripped)
        rows.append({
            "case": parts[0] if len(parts) > 0 else "",
            "type": parts[1] if len(parts) > 1 else "",
            "DESC": parts[2] if len(parts) > 2 else "",
        })
    return rows


def parse_stldcase_order(path):
    return [row["case"] for row in parse_stldcase(path)]


def _name_similarity(left, right):
    return SequenceMatcher(None, _clean(left), _clean(right)).ratio()


def _bad_name_reason(name):
    if len(re.findall(r"\d+(?:\.\d+)?", name or "")) >= 2:
        return "numeric_name"
    if re.search(r"SLAB|CEILING|단열재|콘크리트|마감|몰탈|방수|0\.30|150", name or "", re.IGNORECASE):
        return "detail_load_name"
    return ""


def _desc_case_name(desc):
    parts = _clean(desc).split()
    return parts[1] if len(parts) >= 2 and parts[0] == "PDF_AUTO" else ""


def compare_mgtx(reference_path, target_path, tolerance=0.01):
    reference = parse_mgtx(reference_path)
    target = parse_mgtx(target_path)
    reference_cases = parse_stldcase(reference_path)
    target_cases = parse_stldcase(target_path)
    reference_case_order = parse_stldcase_order(reference_path)
    target_case_order = parse_stldcase_order(target_path)
    matched = []
    used_target = set()
    missing = []

    for ref in reference:
        best = None
        for idx, candidate in enumerate(target):
            if idx in used_target:
                continue
            score = _name_similarity(ref["name"], candidate["name"])
            if best is None or score > best[0]:
                best = (score, idx, candidate)
        if best and best[0] >= 0.55:
            _, idx, candidate = best
            used_target.add(idx)
            dl_diff = None if ref.get("DL") is None or candidate.get("DL") is None else round(candidate["DL"] - ref["DL"], 6)
            ll_diff = None if ref.get("LL") is None or candidate.get("LL") is None else round(candidate["LL"] - ref["LL"], 6)
            matched.append({
                "reference_name": ref["name"],
                "target_name": candidate["name"],
                "name_similarity": round(best[0], 4),
                "reference_DESC": ref.get("DESC"),
                "target_DESC": candidate.get("DESC"),
                "DESC_match": ref.get("DESC") == candidate.get("DESC"),
                "reference_case_order": ref.get("case_order", []),
                "target_case_order": candidate.get("case_order", []),
                "case_order_match": candidate.get("case_order", []) == ref.get("case_order", []),
                "reference_DL": ref.get("DL"),
                "target_DL": candidate.get("DL"),
                "DL_diff": dl_diff,
                "DL_match": dl_diff is not None and abs(dl_diff) <= tolerance,
                "reference_LL": ref.get("LL"),
                "target_LL": candidate.get("LL"),
                "LL_diff": ll_diff,
                "LL_match": ll_diff is not None and abs(ll_diff) <= tolerance,
                "bad_name_reason": _bad_name_reason(candidate["name"]),
            })
        else:
            missing.append(ref)

    extra = [row for idx, row in enumerate(target) if idx not in used_target]
    reference_order = [row["name"] for row in reference]
    target_order = [row["name"] for row in target]
    matched_target_order = [row["target_name"] for row in sorted(matched, key=lambda item: reference_order.index(item["reference_name"]))]
    order_mismatches = []
    for expected_index, ref_name in enumerate(reference_order):
        target_index = next((index for index, row in enumerate(target) if row["name"] == ref_name), None)
        if target_index is not None and target_index != expected_index:
            order_mismatches.append({
                "name": ref_name,
                "reference_index": expected_index + 1,
                "target_index": target_index + 1,
            })
    stldcase_order_ok = target_case_order[:len(reference_case_order)] == reference_case_order
    reference_case_desc = {row["case"]: row.get("DESC") for row in reference_cases}
    target_case_desc = {row["case"]: row.get("DESC") for row in target_cases}
    stldcase_desc_mismatches = [
        {
            "case": case,
            "reference_DESC": reference_case_desc.get(case),
            "target_DESC": target_case_desc.get(case),
        }
        for case in reference_case_order
        if reference_case_desc.get(case) != target_case_desc.get(case)
    ]
    floadtype_desc_mismatches = [row for row in matched if not row["DESC_match"]]
    floadtype_desc_basis_mismatches = [
        row for row in matched
        if _desc_case_name(row.get("target_DESC")) != "DL"
    ]
    floadtype_order_ok = [name for name in target_order if name in reference_order] == [
        name for name in reference_order if name in target_order
    ]
    summary = {
        "reference_count": len(reference),
        "target_count": len(target),
        "matched_count": len(matched),
        "missing_count": len(missing),
        "extra_count": len(extra),
        "name_match_count": sum(1 for row in matched if row["name_similarity"] >= 0.95),
        "value_match_count": sum(1 for row in matched if row["DL_match"] and row["LL_match"]),
        "desc_match_count": sum(1 for row in matched if row["DESC_match"]),
        "desc_mismatch_count": len(floadtype_desc_mismatches),
        "floadtype_desc_basis_ok": not floadtype_desc_basis_mismatches,
        "bad_name_count": sum(1 for row in matched if row["bad_name_reason"]) + sum(1 for row in extra if _bad_name_reason(row["name"])),
        "stldcase_order_ok": stldcase_order_ok,
        "stldcase_desc_ok": not stldcase_desc_mismatches,
        "floadtype_desc_ok": not floadtype_desc_mismatches,
        "floadtype_order_ok": floadtype_order_ok,
        "order_mismatch_count": len(order_mismatches),
    }
    summary["overall_pass"] = (
        summary["missing_count"] == 0
        and summary["extra_count"] == 0
        and summary["value_match_count"] == summary["reference_count"]
        and summary["bad_name_count"] == 0
        and stldcase_order_ok
        and summary["stldcase_desc_ok"]
        and summary["floadtype_desc_basis_ok"]
        and floadtype_order_ok
    )
    return {
        "summary": summary,
        "stldcase": {
            "reference_order": reference_case_order,
            "target_order": target_case_order,
            "order_ok": stldcase_order_ok,
            "reference": reference_cases,
            "target": target_cases,
            "desc_ok": not stldcase_desc_mismatches,
            "desc_mismatches": stldcase_desc_mismatches,
        },
        "floadtype_order": {
            "reference_order": reference_order,
            "target_order": target_order,
            "matched_target_order": matched_target_order,
            "order_ok": floadtype_order_ok,
            "order_mismatches": order_mismatches,
        },
        "matched": matched,
        "missing": missing,
        "extra": extra,
        "missing_names": [row["name"] for row in missing],
        "extra_names": [row["name"] for row in extra],
        "value_mismatches": [row for row in matched if not (row["DL_match"] and row["LL_match"])],
        "desc_mismatches": floadtype_desc_mismatches,
        "desc_basis_mismatches": floadtype_desc_basis_mismatches,
        "stldcase_desc_mismatches": stldcase_desc_mismatches,
        "order_mismatches": order_mismatches,
        "stldcase_order_ok": stldcase_order_ok,
        "stldcase_desc_ok": not stldcase_desc_mismatches,
        "floadtype_desc_ok": not floadtype_desc_mismatches,
        "floadtype_order_ok": floadtype_order_ok,
        "overall_pass": summary["overall_pass"],
    }


def _report_label(path):
    stem = Path(path).stem
    match = re.search(r"\((\d+)\)", stem)
    if match:
        return match.group(1)
    return re.sub(r"[^\w가-힣.-]+", "_", stem).strip("_")


def write_reports(reference_path, target_paths, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    for target_path in target_paths:
        report = compare_mgtx(reference_path, target_path)
        target_path = Path(target_path)
        report_path = output_dir / f"mgtx_compare_report_{_report_label(target_path)}_vs_{_report_label(reference_path)}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        row = {"target": str(target_path), **report["summary"], "report": str(report_path)}
        summary_rows.append(row)
    xlsx_path = output_dir / "mgtx_compare_summary.xlsx"
    pd.DataFrame(summary_rows).to_excel(xlsx_path, index=False)
    return summary_rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--targets", nargs="+", default=[])
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--out", default="output")
    args = parser.parse_args()
    targets = list(args.targets or []) + list(args.target or [])
    rows = write_reports(args.reference, targets, args.out)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
