import re
from collections import defaultdict


def make_safe_name(text, max_len=40):
    """
    MIDAS Floor Load Type 이름으로 사용하기 좋게 정리합니다.
    """
    text = str(text).strip()
    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w가-힣\-_ ,]", "", text)

    if len(text) > max_len:
        text = text[:max_len]

    return text or "AUTO_FLOAD"


def guess_floor_load_type_name(row):
    """
    PDF 원문에서 Floor Load Type 이름을 추정합니다.

    예:
    '업무시설 마감하중 4.9 kN/m2' → 업무시설
    '업무시설 활하중 3.5 kN/m2' → 업무시설
    '복도 활하중 4.0 kN/m2' → 복도
    """

    text = str(row.get("load_item", ""))

    remove_words = [
        "마감하중", "고정하중", "사하중", "활하중", "적재하중",
        "DEAD", "LIVE", "LOAD", "DL", "LL",
        "하중", "kN/m2", "kN/m²", "kN/㎡", "kN", "KN"
    ]

    name = text

    for word in remove_words:
        name = name.replace(word, "")

    # 숫자 제거
    name = re.sub(r"[-+]?\d+(\.\d+)?", "", name)

    # 괄호, 특수문자 일부 정리
    name = re.sub(r"[\(\)\[\]{}]", "", name)
    name = re.sub(r"\s+", " ", name).strip()

    if not name:
        name = row.get("matched_keyword") or row.get("category") or "AUTO_FLOAD"

    return make_safe_name(name)


def build_floor_load_types(classified_rows, settings):
    """
    분류된 하중 행들을 Floor Load Type 단위로 묶습니다.

    결과 예:
    [
      {
        "floor_load_type_name": "업무시설",
        "loads": [
          {"load_case": "DL", "value": -4.9, "sbu": "YES"},
          {"load_case": "LL", "value": -3.5, "sbu": "NO"}
        ],
        ...
      }
    ]
    """

    grouped = defaultdict(list)

    for row in classified_rows:
        flt_name = guess_floor_load_type_name(row)
        grouped[flt_name].append(row)

    floor_load_types = []

    for flt_name, rows in grouped.items():
        loads = []

        for row in rows:
            category = row.get("category", "review")
            load_case = row.get("load_case", "DL")
            value = row.get("floor_load_value")

            if value is None:
                continue

            if category == "dead":
                sbu = settings["floor_load"]["dead_sub_beam_weight_include"]
            elif category == "live":
                sbu = settings["floor_load"]["live_sub_beam_weight_include"]
            else:
                sbu = settings["floor_load"]["review_sub_beam_weight_include"]

            loads.append({
                "load_case": load_case,
                "value": value,
                "sbu": sbu,
                "category": category,
                "source_pdf": row.get("source_pdf", ""),
                "source_page": row.get("source_page", ""),
                "load_item": row.get("load_item", ""),
                "review_flag": row.get("review_flag", False)
            })

        if not loads:
            continue

        # MIDAS FLOADTYPE은 최대 8개 Load Case까지 허용되는 구조로 주석에 표시되어 있음
        # 8개 초과 시 잘라내고 로그에 남기는 방식 권장
        loads = loads[:8]

        floor_load_types.append({
            "floor_load_type_name": flt_name,
            "loads": loads,
            "source_rows": rows
        })

    return floor_load_types