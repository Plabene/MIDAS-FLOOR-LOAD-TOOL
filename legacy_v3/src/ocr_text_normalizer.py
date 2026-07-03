import re


REPLACEMENTS = {
    "S1AB": "SLAB",
    "5LAB": "SLAB",
    "SIAB": "SLAB",
    "SL4B": "SLAB",
    "S LAB": "SLAB",
    "S-LAB": "SLAB",
    "슬레브": "슬래브",
    "스래브": "슬래브",
    "슬래므": "슬래브",
    "슬래부": "슬래브",
    "슬라부": "슬래브",
    "슬라브": "슬래브",
    "KN/M2": "kN/m2",
    "KN/㎡": "kN/m2",
    "kN/㎡": "kN/m2",
    "kN/m²": "kN/m2",
    "KN/M²": "kN/m2",
    "kgf/㎡": "kgf/m2",
    "tf/㎡": "tf/m2",
    "ton/㎡": "ton/m2",
    "t/㎡": "t/m2",
    "D.L": "DL",
    "L.L": "LL",
}


def normalize_ocr_text(text):
    normalized = str(text or "")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    for source, target in REPLACEMENTS.items():
        normalized = re.sub(re.escape(source), target, normalized, flags=re.IGNORECASE)
    return normalized


def normalize_keyword_text(text):
    return normalize_ocr_text(text).upper().replace(" ", "")
