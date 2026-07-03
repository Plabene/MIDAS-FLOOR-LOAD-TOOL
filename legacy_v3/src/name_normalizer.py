import re
from pathlib import Path

import yaml

from ocr_text_normalizer import normalize_keyword_text


DETAIL_NAME_PATTERN = re.compile(
    r"SLAB|S1AB|5LAB|CEILING|CELLING|단열재|콘크리트|무근|몰탈|방수|마감|천장|천정|벽체|토피|THK|T\s*=|"
    r"SHEET|PLAN|DESIGN|CHECK|DATE|TEL|FAX|WWW|CGSPLAN|"
    r"\d+(?:\.\d+)?|kN|m2|㎡|사용하중|계수하중|활하중|합\s*계|TOTAL|1\.2|1\.6",
    re.IGNORECASE,
)
NOISE_PATTERN = re.compile(r"[^\w가-힣() ]+", re.UNICODE)


def load_name_normalization(config_dir=None):
    config_dir = Path(config_dir) if config_dir else Path(__file__).resolve().parent.parent / "config"
    path = config_dir / "name_normalization.yml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as file:
        return (yaml.safe_load(file) or {}).get("name_normalization", {}) or {}


def load_usage_order(config_dir=None):
    config_dir = Path(config_dir) if config_dir else Path(__file__).resolve().parent.parent / "config"
    path = config_dir / "name_normalization.yml"
    if not path.exists():
        return []
    with open(path, "r", encoding="utf-8") as file:
        return (yaml.safe_load(file) or {}).get("usage_order", []) or []


def _compact(value):
    return normalize_keyword_text(value)


def normalize_floor_usage_name(value, mapping=None):
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    if not text:
        return "", "EMPTY"

    mapping = mapping or load_name_normalization()
    compact_text = _compact(text)
    best = None
    for canonical, aliases in mapping.items():
        candidates = [canonical, *(aliases or [])]
        for alias in candidates:
            compact_alias = _compact(alias)
            if compact_alias and compact_alias in compact_text:
                score = len(compact_alias)
                if best is None or score > best[0]:
                    best = (score, canonical, alias)
    if best:
        return best[1], f"alias:{best[2]}"

    number_count = len(re.findall(r"\d+(?:\.\d+)?", text))
    detail_hits = DETAIL_NAME_PATTERN.findall(text)
    if number_count >= 2 or len(detail_hits) >= 2:
        return "", "DETAIL_OR_NUMERIC_NAME"

    cleaned = NOISE_PATTERN.sub(" ", text)
    cleaned = DETAIL_NAME_PATTERN.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split())
    if not cleaned or len(cleaned) < 2:
        return "", "LOW_CONFIDENCE_NAME"
    return cleaned[:40], "cleaned"


def is_bad_floor_load_type_name(value):
    normalized, reason = normalize_floor_usage_name(value)
    return not normalized, reason
