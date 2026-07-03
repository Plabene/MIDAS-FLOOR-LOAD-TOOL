import re


NUMBER_PATTERN = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?")
UNIT_PATTERN_TEXT = r"(?:kN\s*/\s*(?:m2|m\^2|m²|㎡)|KN\s*/\s*(?:M2|M\^2|M²|㎡)|kPa|kgf\s*/\s*(?:m2|m\^2|m²|㎡)|kg\s*/\s*(?:m2|m\^2|m²|㎡)|tf\s*/\s*(?:m2|m\^2|m²|㎡)|ton\s*/\s*(?:m2|m\^2|m²|㎡)|t\s*/\s*(?:m2|m\^2|m²|㎡)|N\s*/\s*(?:m2|m\^2|m²|㎡)|kN\s*/\s*m|kN)"
UNIT_PATTERN = re.compile(UNIT_PATTERN_TEXT, re.IGNORECASE)
VALUE_UNIT_PATTERN = re.compile(
    rf"(?P<value>[-+]?\d{{1,3}}(?:,\d{{3}})*(?:\.\d+)?|[-+]?\d+(?:\.\d+)?)\s*(?P<unit>{UNIT_PATTERN_TEXT})",
    re.IGNORECASE,
)


def parse_number(value):
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def normalize_unit_text(unit):
    if not unit:
        return None
    compact = str(unit).strip().replace(" ", "").replace("^2", "2")
    compact = compact.replace("m²", "m2").replace("M²", "M2").replace("㎡", "m2")
    lower = compact.lower()
    if lower in {"kn/m2", "kpa"}:
        return "kN/m2"
    if lower == "kgf/m2":
        return "kgf/m2"
    if lower == "kg/m2":
        return "kg/m2"
    if lower in {"tf/m2", "ton/m2", "t/m2"}:
        return "tf/m2"
    if lower == "n/m2":
        return "N/m2"
    if lower == "kn/m":
        return "kN/m"
    if lower == "kn":
        return "kN"
    return compact


def unit_factor_to_kn_per_m2(unit):
    normalized = normalize_unit_text(unit)
    if normalized == "kN/m2":
        return 1.0
    if normalized in {"kgf/m2", "kg/m2"}:
        return 0.00980665
    if normalized == "tf/m2":
        return 9.80665
    if normalized == "N/m2":
        return 0.001
    return None


def normalize_load_value(value, unit):
    numeric = parse_number(value)
    normalized_unit = normalize_unit_text(unit)
    factor = unit_factor_to_kn_per_m2(normalized_unit)
    warning = ""

    if numeric is None:
        warning = "하중값 숫자를 확인할 수 없습니다."
    elif normalized_unit is None:
        warning = "단위가 없어 검토가 필요합니다."
    elif factor is None:
        warning = f"면하중으로 자동 변환할 수 없는 단위입니다: {unit}"

    normalized_value = numeric * factor if numeric is not None and factor is not None else numeric
    return {
        "original_value": value,
        "original_unit": unit,
        "normalized_value": normalized_value,
        "normalized_unit": "kN/m2" if factor is not None else normalized_unit,
        "unit_conversion_factor": factor,
        "unit_normalization_warning": warning,
    }


def normalize_unit(unit):
    return normalize_unit_text(unit)


def convert_to_kn_per_m2(value, unit):
    return normalize_load_value(value, unit)["normalized_value"]


def extract_value_unit_pairs(text):
    pairs = []
    for match in VALUE_UNIT_PATTERN.finditer(str(text or "")):
        pairs.append(normalize_load_value(match.group("value"), match.group("unit")))
    return pairs
