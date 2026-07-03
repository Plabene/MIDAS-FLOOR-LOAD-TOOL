import importlib.util
import re
import shutil
import subprocess

import pandas as pd
from PIL import Image

from ocr_text_normalizer import normalize_ocr_text

try:
    import pytesseract
    from pytesseract import Output
except Exception:  # pragma: no cover - depends on local install
    pytesseract = None
    Output = None


OCR_COLUMNS = [
    "text", "normalized_text", "x", "y", "width", "height", "confidence",
    "block_num", "line_num", "word_num", "source_page", "extraction_method", "ocr_lang",
]


def tesseract_available():
    if pytesseract is None:
        return False
    try:
        return bool(shutil.which("tesseract") or pytesseract.get_tesseract_version())
    except Exception:
        return False


def check_tesseract_available():
    status = {"available": False, "version": "", "message": ""}
    if pytesseract is None:
        status["message"] = "pytesseract import failed."
        return status
    try:
        version = str(pytesseract.get_tesseract_version())
        status.update({"available": True, "version": version, "message": "Tesseract OCR is available."})
    except Exception as exc:
        status["message"] = f"Tesseract OCR이 설치되지 않아 OCR fallback을 수행할 수 없습니다. {exc}"
    return status


def check_tesseract_languages():
    status = {"languages": [], "has_kor": False, "has_eng": False, "message": ""}
    if pytesseract is None:
        status["message"] = "pytesseract import failed."
        return status
    try:
        langs = [str(item) for item in pytesseract.get_languages(config="")]
    except Exception:
        try:
            result = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10)
            langs = [line.strip() for line in result.stdout.splitlines() if line.strip() and "List of" not in line]
        except Exception as exc:
            status["message"] = f"Tesseract language list failed: {exc}"
            return status
    status["languages"] = langs
    status["has_kor"] = "kor" in langs
    status["has_eng"] = "eng" in langs
    if not status["has_kor"] and status["has_eng"]:
        status["message"] = "kor 언어팩이 없어 eng OCR로 fallback합니다."
    elif not status["has_eng"]:
        status["message"] = "eng 언어팩이 없어 OCR 정확도가 낮거나 실패할 수 있습니다."
    else:
        status["message"] = "kor/eng language packs are available."
    return status


def get_ocr_engine_status():
    tesseract = check_tesseract_available()
    languages = check_tesseract_languages()
    return {
        "tesseract_available": bool(tesseract.get("available")),
        "tesseract_version": tesseract.get("version", ""),
        "tesseract_message": tesseract.get("message", ""),
        "tesseract_languages": languages.get("languages", []),
        "tesseract_has_kor": bool(languages.get("has_kor")),
        "tesseract_has_eng": bool(languages.get("has_eng")),
        "tesseract_language_message": languages.get("message", ""),
        "paddleocr_available": optional_engine_available("paddleocr"),
        "easyocr_available": optional_engine_available("easyocr"),
    }


def optional_engine_available(engine):
    module_by_engine = {"paddleocr": "paddleocr", "easyocr": "easyocr"}
    module = module_by_engine.get(str(engine).lower())
    return bool(module and importlib.util.find_spec(module))


def installation_message(exc=None):
    suffix = f" 상세: {exc}" if exc else ""
    return (
        "Tesseract OCR 실행 파일 또는 언어팩을 찾을 수 없습니다. "
        "Windows에서는 Tesseract OCR과 kor.traineddata(한글 언어팩)를 설치한 뒤 PATH를 확인하세요."
        + suffix
    )


def _empty_words():
    return pd.DataFrame(columns=OCR_COLUMNS)


def _score_words(words_df):
    if words_df is None or words_df.empty:
        return 0.0
    text = get_page_ocr_text(words_df)
    word_count = len(words_df)
    numeric_count = len(re.findall(r"[-+]?\d+(?:\.\d+)?", text))
    load_keyword_count = len(re.findall(r"고정|활하중|사용|계수|합계|SLAB|S1AB|5LAB|LOAD|LIVE|DEAD|TOTAL|LL|DL", text, re.IGNORECASE))
    unit_count = len(re.findall(r"kN\s*/\s*(?:m2|m²|㎡)|kPa|kgf|tf|ton", text, re.IGNORECASE))
    confidence = estimate_ocr_confidence(words_df)
    return word_count * 0.15 + numeric_count * 3.0 + load_keyword_count * 4.0 + unit_count * 5.0 + confidence * 0.25


def run_tesseract_ocr(image, lang="kor+eng", source_page=None, extraction_method="ocr_fallback", psm_candidates=None):
    if pytesseract is None:
        return _empty_words(), installation_message("pytesseract import 실패")
    pil_image = Image.fromarray(image) if not isinstance(image, Image.Image) else image
    errors = []
    psm_candidates = psm_candidates or [6, 11, 12, 4]
    psm_configs = [f"--psm {int(psm)}" for psm in psm_candidates]
    best_words = _empty_words()
    best_score = -1.0
    best_error = None
    for candidate_lang in [lang, "eng"]:
        for config in psm_configs:
            try:
                data = pytesseract.image_to_data(pil_image, lang=candidate_lang, config=config, output_type=Output.DATAFRAME)
                data["ocr_lang"] = candidate_lang
                words = ocr_words_to_dataframe(data, source_page=source_page, extraction_method=extraction_method)
                if not words.empty:
                    words = words.copy()
                    words["tesseract_psm"] = config
                score = _score_words(words)
                if score > best_score:
                    best_words = words
                    best_score = score
                    best_error = None
            except Exception as exc:
                errors.append(f"{candidate_lang} {config}: {exc}")
                best_error = str(exc)
        if not best_words.empty:
            return best_words, None
    return best_words, installation_message("; ".join(errors) or best_error)


def run_ocr_with_priority(image, engine_priority=None, source_page=None, extraction_method="ocr_fallback", psm_candidates=None):
    engine_priority = engine_priority or ["tesseract", "paddleocr", "easyocr"]
    skipped = []
    for engine in engine_priority:
        engine = str(engine).lower()
        if engine == "tesseract":
            words, error = run_tesseract_ocr(
                image,
                source_page=source_page,
                extraction_method=extraction_method,
                psm_candidates=psm_candidates,
            )
            if error is None or not words.empty:
                return words, error, "tesseract"
            skipped.append(error)
        elif engine in {"paddleocr", "easyocr"}:
            if optional_engine_available(engine):
                skipped.append(f"{engine} is installed but not enabled in this lightweight local fallback implementation.")
            else:
                skipped.append(f"{engine} is not installed; skipped.")
    return _empty_words(), "; ".join(str(item) for item in skipped if item), None


def ocr_words_to_dataframe(dataframe, source_page=None, extraction_method="ocr_fallback"):
    if dataframe is None or dataframe.empty:
        return _empty_words()
    df = dataframe.copy()
    df = df.rename(columns={"left": "x", "top": "y", "conf": "confidence"})
    df["text"] = df["text"].fillna("").astype(str).str.strip()
    df = df[df["text"] != ""].copy()
    df["confidence"] = pd.to_numeric(df["confidence"], errors="coerce").fillna(-1)
    df = df[df["confidence"] >= 0].copy()
    df["normalized_text"] = df["text"].map(normalize_ocr_text)
    df["source_page"] = source_page
    df["extraction_method"] = extraction_method
    for column in ["block_num", "line_num", "word_num", "width", "height", "x", "y"]:
        if column not in df.columns:
            df[column] = 0
    if "ocr_lang" not in df.columns:
        df["ocr_lang"] = ""
    columns = list(OCR_COLUMNS)
    if "tesseract_psm" in df.columns:
        columns.append("tesseract_psm")
    return df[[column for column in columns if column in df.columns]].reset_index(drop=True)


def get_page_ocr_text(words_df):
    if words_df is None or words_df.empty:
        return ""
    ordered = words_df.sort_values(["y", "x"])
    return " ".join(ordered["normalized_text"].astype(str).tolist())


def estimate_ocr_confidence(words_df):
    if words_df is None or words_df.empty or "confidence" not in words_df:
        return 0.0
    valid = pd.to_numeric(words_df["confidence"], errors="coerce")
    valid = valid[valid >= 0]
    return round(float(valid.mean()), 2) if not valid.empty else 0.0
