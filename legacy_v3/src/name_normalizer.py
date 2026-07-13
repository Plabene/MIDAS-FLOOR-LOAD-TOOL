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
STORY_SCOPE_PATTERN = re.compile(
    r"\(\s*(?P<paren>B\s*\d+\s*F|\d+\s*F|지하\s*\d+\s*층|지상\s*\d+\s*층)\s*\)"
    r"|(?P<bare>지하\s*\d+\s*층|지상\s*\d+\s*층|B\s*\d+\s*F)",
    re.IGNORECASE,
)


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


def split_floor_usage_story_scope(value):
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    match = STORY_SCOPE_PATTERN.search(text)
    if not match:
        return text, "", ""
    raw = str(match.group("paren") or match.group("bare") or "").strip()
    usage = (text[:match.start()] + " " + text[match.end():]).strip()
    usage = re.sub(r"\s+", " ", usage).strip(" -_,/")
    compact = re.sub(r"\s+", "", raw.upper())
    basement = re.fullmatch(r"지하(\d+)층", compact)
    above = re.fullmatch(r"지상(\d+)층", compact)
    b_floor = re.fullmatch(r"B(\d+)F", compact)
    floor = re.fullmatch(r"(\d+)F", compact)
    if basement:
        normalized = f"B{int(basement.group(1))}F"
    elif b_floor:
        normalized = f"B{int(b_floor.group(1))}F"
    elif above:
        normalized = f"{int(above.group(1))}F"
    elif floor:
        normalized = f"{int(floor.group(1))}F"
    else:
        normalized = compact
    return usage, raw, normalized


def _with_story_scope(name, story_scope):
    base, _raw, configured_scope = split_floor_usage_story_scope(name)
    scope = story_scope or configured_scope
    if not scope:
        return base
    match = re.fullmatch(r"B(\d+)F", scope.upper())
    display = f"지하{int(match.group(1))}층" if match else scope.upper()
    return f"{base}({display})"


def normalize_floor_usage_name(value, mapping=None):
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    if not text:
        return "", "EMPTY"

    usage_text, _story_scope_raw, story_scope = split_floor_usage_story_scope(text)

    mapping = mapping or load_name_normalization()
    compact_text = _compact(usage_text)
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
        return _with_story_scope(best[1], story_scope), f"alias:{best[2]}"

    number_count = len(re.findall(r"\d+(?:\.\d+)?", usage_text))
    detail_hits = DETAIL_NAME_PATTERN.findall(usage_text)
    if number_count >= 2 or len(detail_hits) >= 2:
        return "", "DETAIL_OR_NUMERIC_NAME"

    cleaned = NOISE_PATTERN.sub(" ", usage_text)
    cleaned = DETAIL_NAME_PATTERN.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split())
    if not cleaned or len(cleaned) < 2:
        return "", "LOW_CONFIDENCE_NAME"
    return _with_story_scope(cleaned[:40], story_scope), "cleaned"


def is_bad_floor_load_type_name(value):
    normalized, reason = normalize_floor_usage_name(value)
    return not normalized, reason
