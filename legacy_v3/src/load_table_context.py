from ocr_text_normalizer import normalize_keyword_text


SLAB_KEYWORDS = ["슬래브", "슬라브", "SLAB", "S1AB", "5LAB", "바닥", "바닥판", "FLOOR", "FLOORSLAB", "FLOOR SLAB", "DECKSLAB"]
FLOOR_KEYWORDS = ["층", "용도", "적용", "부위", "화장실", "주차장", "업무시설", "복도", "계단", "로비", "주거", "사무실"]
ROOF_KEYWORDS = ["지붕", "옥상", "태양광", "PV", "SOLAR", "ROOF"]
FOUNDATION_KEYWORDS = ["기초", "매트", "MAT", "RAFT", "풋팅", "FOOTING", "파일", "PILE", "지중보", "FOUNDATION", "PILECAP", "말뚝", "기초판"]
LOAD_KEYWORDS = ["고정하중", "고정", "사하중", "DEAD", "DL", "활하중", "적재하중", "LIVE", "LL", "합계", "총계", "TOTAL", "사용하중", "계수하중", "kN/m2", "kPa"]


def _hits(text, keywords):
    compact = normalize_keyword_text(text)
    return [keyword for keyword in keywords if normalize_keyword_text(keyword) in compact]


def evaluate_floor_load_context(text, include_review_required=False):
    text = text or ""
    slab_hits = _hits(text, SLAB_KEYWORDS)
    floor_hits = _hits(text, FLOOR_KEYWORDS)
    roof_hits = _hits(text, ROOF_KEYWORDS)
    foundation_hits = _hits(text, FOUNDATION_KEYWORDS)
    load_hits = _hits(text, LOAD_KEYWORDS)

    floor_context_score = len(slab_hits) * 4 + len(roof_hits) * 4 + len(floor_hits) * 2 + len(load_hits)
    foundation_context_score = len(foundation_hits) * 4
    review_flag = False
    warnings = []

    if foundation_hits and not roof_hits:
        decision = "EXCLUDE"
        reason = "EXCLUDE_FOUNDATION"
    elif roof_hits:
        decision = "INCLUDE"
        reason = "INCLUDE_ROOF_EXCEPTION"
        if foundation_hits:
            review_flag = True
            warnings.append("기초 키워드와 지붕/옥상 키워드가 함께 감지되었습니다.")
    elif slab_hits:
        decision = "INCLUDE"
        reason = "INCLUDE_SLAB_CONTEXT"
    elif floor_context_score >= 4:
        decision = "REVIEW_REQUIRED" if include_review_required else "INCLUDE"
        reason = "REVIEW_REQUIRED" if include_review_required else "INCLUDE_CONTEXT_SCORE"
        review_flag = True
        warnings.append("SLAB 키워드는 없지만 하중표 문맥 점수로 후보에 포함했습니다.")
    else:
        decision = "EXCLUDE"
        reason = "EXCLUDE_NO_FLOOR_CONTEXT"

    return {
        "detected_slab_keywords": slab_hits,
        "detected_floor_keywords": floor_hits,
        "detected_roof_keywords": roof_hits,
        "detected_foundation_keywords": foundation_hits,
        "detected_load_keywords": load_hits,
        "floor_context_score": floor_context_score,
        "foundation_context_score": foundation_context_score,
        "floor_load_inclusion_decision": decision,
        "floor_load_inclusion_reason": reason,
        "review_flag": review_flag,
        "warnings": warnings,
    }


def classify_structural_load_type(text):
    compact = normalize_keyword_text(text)
    mappings = [
        ("SNOW_LOAD", ["적설", "SNOW"]),
        ("WIND_LOAD", ["풍하중", "WIND"]),
        ("SEISMIC_LOAD", ["지진", "SEISMIC", "EARTHQUAKE"]),
        ("EARTH_PRESSURE", ["토압", "EARTHPRESSURE"]),
        ("WATER_PRESSURE", ["수압", "WATERPRESSURE"]),
        ("TEMPERATURE_LOAD", ["온도", "TEMPERATURE"]),
        ("EQUIPMENT_LOAD", ["장비", "설비", "EQUIPMENT", "태양광", "PV", "SOLAR"]),
        ("DEAD_LOAD", ["고정하중", "사하중", "마감", "천장", "벽체", "조적", "방수", "설비고정", "SLAB", "자중", "DEAD", "DL"]),
        ("LIVE_LOAD", ["활하중", "적재하중", "LIVE", "LL", "사무실", "주거", "복도", "계단", "주차장", "옥상활하중"]),
    ]
    for load_type, keywords in mappings:
        if any(normalize_keyword_text(keyword) in compact for keyword in keywords):
            return load_type
    return "UNKNOWN"
