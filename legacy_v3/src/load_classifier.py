from collections import defaultdict
from pathlib import Path

import yaml

from name_normalizer import load_name_normalization, normalize_floor_usage_name


FORCED_CATEGORY_DEFAULTS = {
    "dead": ("DL_GENERAL", "D", False),
    "live": ("LL_GENERAL", "L", False),
}

LOAD_CASE_NAME_BY_CATEGORY = {
    "dead": "DL",
    "live": "LL",
    "wind": "WIND",
    "seismic": "SEISMIC",
    "snow": "SNOW",
    "review": "RV",
}


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def _match_mapping(text, mappings):
    upper_text = str(text or "").upper()
    for mapping in mappings:
        for keyword in mapping.get("keywords", []):
            if str(keyword).upper() in upper_text:
                return mapping, keyword
    return None, None


def _sub_beam_weight(category, settings):
    floor_load = settings.get("floor_load", {})
    key_by_category = {
        "dead": "dead_sub_beam_weight_include",
        "live": "live_sub_beam_weight_include",
        "review": "review_sub_beam_weight_include",
        "wind": "wind_sub_beam_weight_include",
        "seismic": "seismic_sub_beam_weight_include",
        "snow": "snow_sub_beam_weight_include",
    }
    return floor_load.get(key_by_category.get(category, "review_sub_beam_weight_include"), "NO")


def _limit_name(name, max_length):
    return name[:max_length] if max_length and len(name) > max_length else name


def _clean_floor_load_name(value):
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    text = text.replace("，", ",").replace("、", ",")
    parts = []
    for part in text.split(","):
        cleaned = " ".join(part.split())
        if cleaned and cleaned not in parts:
            parts.append(cleaned)
    return ",".join(parts)


def _resolve_classification(row, mappings):
    load_item = row.get("load_item") or row.get("raw_text") or ""
    forced_category = row.get("forced_category")

    mapping, matched_keyword = _match_mapping(load_item, mappings)
    if forced_category in FORCED_CATEGORY_DEFAULTS:
        default_prefix, default_code, default_review = FORCED_CATEGORY_DEFAULTS[forced_category]
        if mapping and mapping.get("category") == forced_category:
            prefix = mapping.get("load_case_prefix", default_prefix)
            reason = f"table component forced as {forced_category}; keyword matched: {matched_keyword}"
        else:
            prefix = default_prefix
            reason = f"table component forced as {forced_category}; keyword not used for component"
        return {
            "category": forced_category,
            "prefix": prefix,
            "mgtx_code": default_code,
            "review_flag": default_review,
            "matched_keyword": matched_keyword,
            "reason": reason,
        }

    if mapping:
        return {
            "category": mapping.get("category"),
            "prefix": mapping.get("load_case_prefix"),
            "mgtx_code": mapping.get("mgtx_load_type_code"),
            "review_flag": bool(mapping.get("review_flag")),
            "matched_keyword": matched_keyword,
            "reason": f"keyword matched: {matched_keyword}",
        }

    return {
        "category": "review",
        "prefix": "AUTO_REVIEW",
        "mgtx_code": "D",
        "review_flag": True,
        "matched_keyword": None,
        "reason": "no keyword matched; created AUTO_REVIEW case",
    }


def _resolve_load_case_name(category):
    return LOAD_CASE_NAME_BY_CATEGORY.get(category, "RV")


def classify_loads(rows, mapping_path, settings_path):
    mappings = load_yaml(Path(mapping_path)).get("load_mappings", [])
    settings = load_yaml(Path(settings_path))
    name_mapping = load_name_normalization(Path(settings_path).parent)
    gravity_sign = float(settings.get("floor_load", {}).get("gravity_load_sign", -1))
    prefix_floor_load_type = settings.get("naming", {}).get("prefix_floor_load_type", "FLT")
    max_name_length = int(settings.get("naming", {}).get("max_name_length", 40))

    floor_name_by_group = {}
    used_floor_names = defaultdict(int)
    fallback_floor_counter = defaultdict(int)
    classified_rows = []

    for row in rows:
        classified = dict(row)
        resolved = _resolve_classification(classified, mappings)

        prefix = resolved["prefix"]
        category = resolved["category"]
        load_case_name = _resolve_load_case_name(category)

        group_key = classified.get("floor_load_group_key") or load_case_name
        if group_key in floor_name_by_group:
            floor_load_type_name = floor_name_by_group[group_key]
        else:
            raw_name = classified.get("floor_usage_name")
            if classified.get("parser_type") == "BLOCK_SUMMARY_DL_LL_TABLE":
                base_name = _clean_floor_load_name(raw_name)
                name_reason = "preserved_from_block_summary_parser"
            else:
                base_name, name_reason = normalize_floor_usage_name(raw_name, name_mapping)
                if base_name:
                    classified["floor_usage_name"] = base_name
                base_name = _clean_floor_load_name(base_name)
            classified["normalized_floor_usage_name"] = base_name
            classified["floor_usage_name_normalization_reason"] = name_reason
            if not base_name:
                fallback_floor_counter[prefix] += 1
                base_name = f"{prefix_floor_load_type}_{prefix}_{fallback_floor_counter[prefix]:03d}"
                classified["review_flag"] = True
                classified["exclude_from_mgtx"] = True
                classified["exclusion_reason"] = classified.get("exclusion_reason") or "Floor Load Type 이름을 신뢰도 있게 확정하지 못했습니다."
            base_name = _limit_name(base_name, max_name_length)

            used_floor_names[base_name] += 1
            if used_floor_names[base_name] == 1:
                floor_load_type_name = base_name
            else:
                suffix = f"_{used_floor_names[base_name]:03d}"
                floor_load_type_name = _limit_name(base_name, max_name_length - len(suffix)) + suffix
            floor_name_by_group[group_key] = floor_load_type_name

        converted_value = classified.get("load_value_kn_per_m2")
        floor_load_value = converted_value * gravity_sign if converted_value is not None else None

        classified.update({
            "category": category,
            "load_case_prefix": prefix,
            "load_case_name": load_case_name,
            "floor_load_type_name": floor_load_type_name,
            "floor_load_value": floor_load_value,
            "mgtx_load_type_code": resolved["mgtx_code"],
            "sub_beam_weight_include": _sub_beam_weight(resolved["category"], settings),
            "matched_keyword": resolved["matched_keyword"],
            "review_flag": bool(classified.get("review_flag")) or resolved["review_flag"],
            "classification_reason": resolved["reason"],
        })
        classified_rows.append(classified)

    return classified_rows
