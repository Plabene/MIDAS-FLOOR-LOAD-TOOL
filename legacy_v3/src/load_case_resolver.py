from pathlib import Path
import re


DL_ALIASES = {
    "DL",
    "D.L",
    "DEAD",
    "DEAD LOAD",
    "DEADLOAD",
    "고정하중",
    "고정 하중",
    "사하중",
    "사 하중",
}

LL_ALIASES = {
    "LL",
    "L.L",
    "LIVE",
    "LIVE LOAD",
    "LIVELOAD",
    "활하중",
    "활 하중",
}


def normalize_load_case_name(name):
    text = str(name or "").strip().upper()
    text = re.sub(r"[\s_\-]+", "", text)
    text = text.replace(".", "")
    return text


def load_case_family(name, load_type_code=None):
    normalized = normalize_load_case_name(name)
    dl_aliases = {normalize_load_case_name(alias) for alias in DL_ALIASES}
    ll_aliases = {normalize_load_case_name(alias) for alias in LL_ALIASES}

    if normalized in dl_aliases:
        return "DL"
    if normalized in ll_aliases:
        return "LL"

    code = str(load_type_code or "").strip().upper()
    if code == "D":
        return "DL"
    if code == "L":
        return "LL"
    return None


def _read_text(path):
    for encoding in ("cp949", "utf-8-sig", "utf-8"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="cp949", errors="replace")


def _parse_stldcase_lines(text, source_file):
    cases = []
    in_block = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue

        upper = line.upper()
        if upper.startswith("*STLDCASE"):
            in_block = True
            continue
        if in_block and upper.startswith("*"):
            in_block = False
            continue
        if not in_block:
            continue

        parts = [part.strip().strip('"') for part in line.split(",")]
        if not parts or not parts[0]:
            continue

        load_type_code = parts[1].strip() if len(parts) > 1 else ""
        family = load_case_family(parts[0], load_type_code)
        cases.append({
            "name": parts[0],
            "load_type_code": load_type_code,
            "family": family,
            "source_file": source_file,
        })

    return cases


def detect_existing_load_cases(reference_dir):
    reference_path = Path(reference_dir)
    detected_cases = []

    if reference_path.exists():
        for path in sorted(reference_path.glob("*")):
            if path.suffix.lower() not in {".mgtx", ".mgt"} or not path.is_file():
                continue
            detected_cases.extend(_parse_stldcase_lines(_read_text(path), path.name))

    mapped_cases = {}
    for family in ("DL", "LL"):
        for case in detected_cases:
            if case.get("family") == family:
                mapped_cases[family] = case
                break

    return {
        "detected_cases": detected_cases,
        "mapped_cases": mapped_cases,
    }
