from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import csv
import importlib
import io
import json
import re
import shutil
import sys
import uuid
from typing import Any, Iterable, Sequence

import yaml

from .mgt_parser import read_text, section_lines, write_text


PDF_GROUP_ACCEPTED = "ACCEPTED"
PDF_GROUP_ACCEPTED_WITH_WARNING = "ACCEPTED_WITH_WARNING"
PDF_GROUP_REVIEW_REQUIRED = "REVIEW_REQUIRED"
PDF_GROUP_REJECTED = "REJECTED"
PDF_GENERAL_NAMES = {"FLT_DL_GENERAL_", "FLT_DL_GENERAL", "LL_GENERAL", "AUTO_REVIEW", "이름 확인 필요"}
PDF_GENERAL_NAME_KEYS = {re.sub(r"[^A-Z0-9가-힣_]", "", name.upper()) for name in PDF_GENERAL_NAMES}
PDF_BASEMENT_REVIEW_USAGES = {
    "저수조",
    "소화수조 및 정화조",
    "기계실, 발전기실",
    "제연팬룸",
    "기계식 주차장",
}


@dataclass(frozen=True)
class PdfLoadTableGroup:
    source_pdf: str
    source_page: int | None
    table_index: int | None
    group_index: int
    usage_name_raw: str
    usage_name_normalized: str
    story_scope_raw: str
    story_names: tuple[str, ...]
    member_scope_raw: str = ""
    member_names: tuple[str, ...] = ()
    detail_rows: tuple[dict[str, Any], ...] = ()
    dead_total: float | None = None
    live_load: float | None = None
    service_load: float | None = None
    factored_load: float | None = None
    formula_type: str = "1.2DL+1.6LL"
    unit: str = "kN/m2"
    confidence: float = 0.0
    warnings: tuple[str, ...] = ()
    status: str = PDF_GROUP_REVIEW_REQUIRED


@dataclass(frozen=True)
class PdfSemanticScore:
    score: float
    usage_group_count: int
    complete_pair_ratio: float
    formula_pass_ratio: float
    numeric_only_usage_ratio: float
    fallback_name_ratio: float
    duplicate_name_collisions: int
    accepted_group_count: int


@dataclass(frozen=True)
class FloorLoadPresence:
    """현재 MGT/MGTX에 FLOOR LOAD가 이미 배정되어 있는지에 대한 요약."""

    has_floorload: bool
    floorload_count: int
    floadtype_count: int
    stldcase_count: int
    message: str


@dataclass(frozen=True)
class PdfLoadImportResult:
    """V3 PDF 하중표 인식 파이프라인 실행 결과."""

    input_pdf_paths: tuple[Path, ...]
    job_dir: Path
    input_dir: Path
    output_dir: Path
    raw_rows: list[dict[str, Any]]
    parsed_rows: list[dict[str, Any]]
    classified_rows: list[dict[str, Any]]
    valid_rows: list[dict[str, Any]]
    error_rows: list[dict[str, Any]]
    mgtx_path: Path | None
    log_xlsx_path: Path
    json_log_path: Path
    error_log_path: Path
    layer_lines: tuple[str, ...]
    table_groups: tuple[PdfLoadTableGroup, ...] = field(default_factory=tuple)
    semantic_score: PdfSemanticScore | None = None


@dataclass(frozen=True)
class PdfMgtMergeResult:
    output_mgt_path: Path
    added_stldcase_count: int
    added_floadtype_count: int
    skipped_stldcase_names: tuple[str, ...]
    skipped_floadtype_names: tuple[str, ...]


def detect_floor_load_presence_from_text(text: str) -> FloorLoadPresence:
    floorload_count = _count_records(text, "*FLOORLOAD")
    floadtype_count = _count_floadtype_records(text)
    stldcase_count = _count_records(text, "*STLDCASE")
    has = floorload_count > 0
    if has:
        message = f"기존 MGT에서 FLOOR LOAD 배정 {floorload_count}개를 확인했습니다. PDF 입력은 선택 사항이며 기존 하중을 유지할 수 있습니다."
    elif floadtype_count > 0:
        message = f"FLOOR LOAD 배정은 없지만 FLOOR LOAD TYPE {floadtype_count}개가 존재합니다. 영역 배정이 필요한 경우 DXF 또는 PDF 기능을 사용하세요."
    else:
        message = "기존 MGT에서 FLOOR LOAD 배정을 찾지 못했습니다. 필요한 경우 'PDF로 하중 입력하기'를 눌러 설계하중표 PDF를 인식하세요."
    return FloorLoadPresence(has, floorload_count, floadtype_count, stldcase_count, message)


def detect_floor_load_presence(path: str | Path) -> FloorLoadPresence:
    return detect_floor_load_presence_from_text(read_text(path))


def run_pdf_load_import(
    *,
    pdf_paths: Sequence[str | Path],
    root_dir: str | Path,
    output_root: str | Path | None = None,
    job_name: str | None = None,
) -> PdfLoadImportResult:
    """
    legacy_v3의 PDF → 하중표 → MIDAS MGTX 생성 로직을 Tkinter V4에서 직접 호출한다.

    Streamlit UI는 호출하지 않고 V3의 core 함수만 재사용한다.
    """

    if not pdf_paths:
        raise ValueError("분석할 구조계산서 PDF를 선택해 주세요.")

    root = Path(root_dir)
    legacy_dir = root / "legacy_v3"
    legacy_src = legacy_dir / "src"
    legacy_config = legacy_dir / "config"
    if not legacy_src.exists() or not legacy_config.exists():
        raise FileNotFoundError(f"V3 legacy 모듈을 찾지 못했습니다: {legacy_dir}")

    _ensure_legacy_path(legacy_src)
    extract_pdf_load_candidates = importlib.import_module("pdf_extract").extract_pdf_load_candidates
    parse_load_rows = importlib.import_module("load_parser").parse_load_rows
    classify_loads = importlib.import_module("load_classifier").classify_loads
    manual_overrides_mod = importlib.import_module("manual_overrides")
    validators_mod = importlib.import_module("validators")
    writer_mod = importlib.import_module("midas_mgtx_writer")

    run_id = job_name or f"pdf_load_{uuid.uuid4().hex[:8]}"
    pdf_jobs_root = Path(output_root) if output_root is not None else root / "DATA" / "pdf_jobs"
    job_dir = pdf_jobs_root / _safe_name(run_id)
    input_dir = job_dir / "source_pdfs"
    output_dir = job_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)

    saved_pdfs: list[Path] = []
    for src in pdf_paths:
        src_path = Path(src)
        if not src_path.exists():
            raise FileNotFoundError(f"PDF 파일을 찾지 못했습니다: {src_path}")
        dst = input_dir / src_path.name
        shutil.copy2(src_path, dst)
        saved_pdfs.append(dst)

    settings_path = legacy_config / "midas_settings.yml"
    mapping_path = legacy_config / "load_mapping.yml"
    settings = _load_yaml(settings_path)
    output_file_name = settings.get("output", {}).get("file_name", "midas_auto_define_floor_load_type.mgtx")
    encoding = settings.get("output", {}).get("encoding", "cp949")
    prefix_auto_desc = settings.get("naming", {}).get("prefix_auto_desc", "PDF_AUTO")
    create_empty_mgtx = bool(settings.get("output", {}).get("create_empty_mgtx_when_no_rows", False))
    mgtx_path = output_dir / output_file_name

    raw_rows = extract_pdf_load_candidates(input_dir)
    if not raw_rows:
        diagnostic_rows = _make_no_pdf_rows(saved_pdfs, legacy_dir)
        writer_mod.write_log_files(diagnostic_rows, diagnostic_rows, output_dir)
        return PdfLoadImportResult(
            input_pdf_paths=tuple(saved_pdfs),
            job_dir=job_dir,
            input_dir=input_dir,
            output_dir=output_dir,
            raw_rows=[],
            parsed_rows=[],
            classified_rows=diagnostic_rows,
            valid_rows=[],
            error_rows=diagnostic_rows,
            mgtx_path=None,
            log_xlsx_path=output_dir / "auto_input_log.xlsx",
            json_log_path=output_dir / "auto_input_log.json",
            error_log_path=output_dir / "error_log.txt",
            layer_lines=tuple(),
        )

    parsed_rows = parse_load_rows(raw_rows)
    classified_rows = classify_loads(parsed_rows, mapping_path=mapping_path, settings_path=settings_path)
    overrides = manual_overrides_mod.load_manual_overrides(legacy_config / "manual_overrides.yml")
    classified_rows = manual_overrides_mod.apply_manual_overrides(classified_rows, overrides)
    checked_rows, validator_valid_rows = validators_mod.validate_rows(classified_rows)
    table_groups = build_pdf_load_table_groups(checked_rows)
    _annotate_rows_with_pdf_groups(checked_rows, table_groups)
    valid_rows = filter_accepted_pdf_rows(validator_valid_rows)
    semantic_score = score_pdf_load_semantics(table_groups)
    for row in checked_rows:
        row["mgtx_row_count"] = len(valid_rows)
    accepted_row_ids = {id(row) for row in valid_rows}
    error_rows = [row for row in checked_rows if id(row) not in accepted_row_ids]

    generated_mgtx: Path | None = None
    if valid_rows or create_empty_mgtx:
        generated_mgtx = writer_mod.write_mgtx_file(
            rows=valid_rows,
            mgtx_path=mgtx_path,
            encoding=encoding,
            prefix_auto_desc=prefix_auto_desc,
        )
    else:
        if mgtx_path.exists():
            mgtx_path.unlink()
        for row in checked_rows:
            if not row.get("is_valid_for_mgtx") and row.get("failure_stage") in {None, "", "SUCCESS"}:
                row["failure_stage"] = "MGTX_WRITE_SKIPPED_NO_VALID_ROWS"
                row["failure_reason"] = "유효한 Floor Load Type이 없어 MGTX 파일을 생성하지 않았습니다."

    writer_mod.write_log_files(checked_rows, error_rows, output_dir)
    layer_lines = tuple(extract_load_layer_lines(valid_rows))
    _write_layer_lines_csv(output_dir / "pdf_load_layers.csv", layer_lines)

    return PdfLoadImportResult(
        input_pdf_paths=tuple(saved_pdfs),
        job_dir=job_dir,
        input_dir=input_dir,
        output_dir=output_dir,
        raw_rows=list(raw_rows or []),
        parsed_rows=list(parsed_rows or []),
        classified_rows=list(checked_rows or []),
        valid_rows=list(valid_rows or []),
        error_rows=list(error_rows or []),
        mgtx_path=Path(generated_mgtx) if generated_mgtx else None,
        log_xlsx_path=output_dir / "auto_input_log.xlsx",
        json_log_path=output_dir / "auto_input_log.json",
        error_log_path=output_dir / "error_log.txt",
        layer_lines=layer_lines,
        table_groups=table_groups,
        semantic_score=semantic_score,
    )


_STORY_SCOPE_PATTERN = re.compile(
    r"(?:\(\s*(?P<paren>B\s*\d+\s*F|\d+\s*F|지하\s*\d+\s*층|지상\s*\d+\s*층)\s*\)"
    r"|(?P<bare>지하\s*\d+\s*층|지상\s*\d+\s*층|B\s*\d+\s*F))",
    re.IGNORECASE,
)


def split_pdf_usage_story_scope(value: object) -> tuple[str, str, tuple[str, ...]]:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())
    match = _STORY_SCOPE_PATTERN.search(text)
    if match is None:
        return text.strip(), "", ()
    raw_scope = str(match.group("paren") or match.group("bare") or "").strip()
    usage = (text[: match.start()] + " " + text[match.end() :]).strip()
    usage = re.sub(r"\s+", " ", usage).strip(" -_,/")
    normalized = re.sub(r"\s+", "", raw_scope.upper())
    basement = re.fullmatch(r"지하(\d+)층", normalized)
    above = re.fullmatch(r"지상(\d+)층", normalized)
    b_floor = re.fullmatch(r"B(\d+)F", normalized)
    floor = re.fullmatch(r"(\d+)F", normalized)
    if basement:
        story_name = f"B{int(basement.group(1))}F"
    elif b_floor:
        story_name = f"B{int(b_floor.group(1))}F"
    elif above:
        story_name = f"{int(above.group(1))}F"
    elif floor:
        story_name = f"{int(floor.group(1))}F"
    else:
        story_name = normalized
    return usage, raw_scope, (story_name,) if story_name else ()


def normalize_pdf_usage_name(value: object) -> tuple[str, str, tuple[str, ...]]:
    usage, scope_raw, story_names = split_pdf_usage_story_scope(value)
    compact = re.sub(r"[^0-9A-Z가-힣]", "", usage.upper())
    aliases = (
        ("기계식 주차장", ("기계식주차장", "기계식주차")),
        ("소화수조 및 정화조", ("소화수조및정화조", "소화수조정화조")),
        ("기계실, 발전기실", ("기계실발전기실", "기계실및발전기실")),
        ("주차통로 및 주차장", ("주차통로및주차장", "주차통로주차장", "지하주차장")),
        ("지붕층(태양광)", ("지붕층태양광", "태양광지붕", "태양광")),
        ("옥탑지붕층", ("옥탑지붕층", "옥탑지붕")),
        ("옥상조경", ("옥상조경",)),
        ("업무시설", ("업무시설",)),
        ("로비 및 홀", ("로비및홀", "로비홀")),
        ("화장실", ("화장실",)),
        ("저수조", ("저수조",)),
        ("제연팬룸", ("제연팬룸",)),
        ("후정", ("후정",)),
        ("지붕층", ("지붕층", "지붕")),
    )
    for canonical, candidates in aliases:
        if any(alias in compact for alias in candidates):
            return canonical, scope_raw, story_names
    cleaned = re.sub(r"[^0-9A-Za-z가-힣(), ]+", " ", usage)
    cleaned = " ".join(cleaned.split()).strip(" ,")
    return cleaned, scope_raw, story_names


def pdf_floor_load_type_name(usage_name: str, story_names: Sequence[str]) -> str:
    usage = str(usage_name or "").strip()
    stories = tuple(str(name or "") for name in story_names if str(name or ""))
    if not usage or not stories:
        return usage
    story = stories[0]
    basement = re.fullmatch(r"B(\d+)F", story.upper())
    scope = f"지하{int(basement.group(1))}층" if basement else story
    return f"{usage}({scope})"


def build_pdf_load_table_groups(
    rows: Iterable[dict[str, Any]],
    *,
    exclude_basement_special_without_slab: bool = True,
) -> tuple[PdfLoadTableGroup, ...]:
    grouped: dict[tuple, list[dict[str, Any]]] = {}
    for index, source in enumerate(rows or (), start=1):
        row = dict(source or {})
        raw_usage = str(
            row.get("floor_usage_name")
            or row.get("floor_load_type_name")
            or row.get("usage_name_raw")
            or ""
        ).strip()
        usage, scope_raw, story_names = normalize_pdf_usage_name(raw_usage)
        row["usage_name_normalized"] = usage
        row["story_scope_raw"] = scope_raw
        row["story_names"] = story_names
        row["floor_load_type_name"] = pdf_floor_load_type_name(usage, story_names) or row.get("floor_load_type_name")
        group_marker = str(row.get("floor_load_group_key") or row.get("group_key") or f"usage:{usage}|story:{'|'.join(story_names)}")
        key = (
            str(row.get("source_pdf") or ""),
            row.get("source_page"),
            str(row.get("table_index") or str(row.get("source_index") or "").split("-", 1)[0] or ""),
            group_marker,
            usage,
            story_names,
        )
        grouped.setdefault(key, []).append(row)

    result: list[PdfLoadTableGroup] = []
    for group_index, (key, group_rows) in enumerate(grouped.items(), start=1):
        source_pdf, source_page, table_value, _marker, usage, story_names = key
        usable = [row for row in group_rows if not bool(row.get("exclude_from_mgtx"))]
        dead_values = [_pdf_row_value(row) for row in usable if _pdf_row_family(row) == "DL"]
        live_values = [_pdf_row_value(row) for row in usable if _pdf_row_family(row) == "LL"]
        dead_values = [value for value in dead_values if value is not None]
        live_values = [value for value in live_values if value is not None]
        dead_total = round(sum(dead_values), 6) if dead_values else None
        live_load = round(sum(live_values), 6) if live_values else None
        service_load = _first_pdf_value(group_rows, "service_load")
        factored_load = _first_pdf_value(group_rows, "factored_load")
        warnings = [str(item) for row in group_rows for item in tuple(row.get("warnings") or ()) if str(item)]
        display_name = pdf_floor_load_type_name(str(usage), story_names)
        normalized_general = re.sub(r"[^A-Z0-9가-힣_]", "", display_name.upper())
        has_slab = any(bool(row.get("has_slab_context")) for row in group_rows)
        is_basement_special = bool(story_names and str(story_names[0]).upper().startswith("B") and usage in PDF_BASEMENT_REVIEW_USAGES)
        if not usage or display_name in PDF_GENERAL_NAMES or normalized_general in PDF_GENERAL_NAME_KEYS:
            status = PDF_GROUP_REVIEW_REQUIRED
            warnings.append("일반/fallback 이름은 자동 적용하지 않습니다.")
        elif dead_total is None or live_load is None:
            status = PDF_GROUP_REVIEW_REQUIRED
            warnings.append("DL/LL pair를 모두 확정하지 못했습니다.")
        elif exclude_basement_special_without_slab and is_basement_special and not has_slab:
            status = PDF_GROUP_REVIEW_REQUIRED
            warnings.append("SLAB 문맥이 없는 지하 특수실 하중은 정책상 검토 대상으로 분리합니다.")
        elif warnings or any(bool(row.get("review_flag")) for row in group_rows):
            status = PDF_GROUP_ACCEPTED_WITH_WARNING
        else:
            status = PDF_GROUP_ACCEPTED
        confidence_values = [
            float(row.get("confidence_score") or row.get("extraction_confidence") or row.get("ocr_confidence") or 0.0)
            for row in group_rows
        ]
        confidence = sum(confidence_values) / len(confidence_values) if confidence_values else 0.0
        try:
            table_index = int(table_value) if str(table_value).strip() else None
        except (TypeError, ValueError):
            table_index = None
        result.append(
            PdfLoadTableGroup(
                source_pdf=str(source_pdf),
                source_page=int(source_page) if source_page not in (None, "") else None,
                table_index=table_index,
                group_index=group_index,
                usage_name_raw=str(group_rows[0].get("floor_usage_name") or group_rows[0].get("floor_load_type_name") or ""),
                usage_name_normalized=str(usage),
                story_scope_raw=str(group_rows[0].get("story_scope_raw") or normalize_pdf_usage_name(group_rows[0].get("floor_usage_name") or "")[1]),
                story_names=tuple(story_names),
                member_scope_raw=str(group_rows[0].get("member_scope_raw") or ""),
                member_names=tuple(str(name) for row in group_rows for name in tuple(row.get("member_names") or ()) if str(name)),
                detail_rows=tuple(group_rows),
                dead_total=dead_total,
                live_load=live_load,
                service_load=service_load,
                factored_load=factored_load,
                confidence=confidence,
                warnings=tuple(dict.fromkeys(warnings)),
                status=status,
            )
        )
    return tuple(result)


def score_pdf_load_semantics(groups: Sequence[PdfLoadTableGroup]) -> PdfSemanticScore:
    count = len(groups)
    if not count:
        return PdfSemanticScore(0.0, 0, 0.0, 0.0, 1.0, 1.0, 0, 0)
    complete = sum(1 for group in groups if group.dead_total is not None and group.live_load is not None)
    formula_rows = [group for group in groups if group.service_load is not None or group.factored_load is not None]
    formula_pass = 0
    for group in formula_rows:
        service_ok = group.service_load is None or abs(float(group.service_load) - float(group.dead_total or 0) - float(group.live_load or 0)) <= 0.08
        factored_ok = group.factored_load is None or abs(float(group.factored_load) - (1.2 * float(group.dead_total or 0) + 1.6 * float(group.live_load or 0))) <= 0.12
        formula_pass += int(service_ok and factored_ok)
    numeric_only = sum(1 for group in groups if not re.search(r"[A-Za-z가-힣]", group.usage_name_normalized))
    fallback = sum(
        1
        for group in groups
        if re.sub(r"[^A-Z0-9가-힣_]", "", group.usage_name_normalized.upper()) in PDF_GENERAL_NAME_KEYS
        or not group.usage_name_normalized
    )
    name_counts: dict[str, int] = {}
    for group in groups:
        name = pdf_floor_load_type_name(group.usage_name_normalized, group.story_names)
        name_counts[name] = name_counts.get(name, 0) + 1
    collisions = sum(count - 1 for count in name_counts.values() if count > 1)
    accepted = sum(1 for group in groups if group.status in {PDF_GROUP_ACCEPTED, PDF_GROUP_ACCEPTED_WITH_WARNING})
    complete_ratio = complete / count
    formula_ratio = formula_pass / len(formula_rows) if formula_rows else complete_ratio
    numeric_ratio = numeric_only / count
    fallback_ratio = fallback / count
    score = (
        min(count / 6.0, 1.0) * 0.15
        + complete_ratio * 0.35
        + formula_ratio * 0.20
        + (1.0 - numeric_ratio) * 0.10
        + (1.0 - fallback_ratio) * 0.10
        + max(0.0, 1.0 - collisions / count) * 0.05
        + (accepted / count) * 0.05
    )
    return PdfSemanticScore(round(max(0.0, min(score, 1.0)), 6), count, complete_ratio, formula_ratio, numeric_ratio, fallback_ratio, collisions, accepted)


def filter_accepted_pdf_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted = []
    for row in rows or ():
        name = str(row.get("floor_load_type_name") or row.get("floor_load_group_key") or row.get("floor_usage_name") or "").strip()
        normalized = re.sub(r"[^A-Z0-9가-힣_]", "", name.upper())
        status = str(row.get("pdf_group_status") or row.get("status") or "").upper()
        if name in PDF_GENERAL_NAMES or normalized in PDF_GENERAL_NAME_KEYS:
            continue
        if bool(row.get("exclude_from_mgtx")) or row.get("is_valid_for_mgtx") is False:
            continue
        if status and status not in {PDF_GROUP_ACCEPTED, PDF_GROUP_ACCEPTED_WITH_WARNING, "OK", "VALID"}:
            continue
        accepted.append(row)
    return accepted


def _annotate_rows_with_pdf_groups(
    rows: Sequence[dict[str, Any]],
    groups: Sequence[PdfLoadTableGroup],
) -> None:
    groups_by_key: dict[tuple, PdfLoadTableGroup] = {}
    for group in groups:
        key = (str(group.source_pdf), group.source_page, group.usage_name_normalized, tuple(group.story_names))
        groups_by_key.setdefault(key, group)
    for row in rows:
        raw_usage = row.get("floor_usage_name") or row.get("floor_load_type_name") or ""
        usage, scope_raw, story_names = normalize_pdf_usage_name(raw_usage)
        key = (str(row.get("source_pdf") or ""), row.get("source_page"), usage, tuple(story_names))
        group = groups_by_key.get(key)
        if group is None:
            continue
        row["usage_name_normalized"] = usage
        row["story_scope_raw"] = scope_raw
        row["story_names"] = tuple(story_names)
        row["pdf_group_status"] = group.status
        row["pdf_group_confidence"] = group.confidence
        display_name = pdf_floor_load_type_name(usage, story_names)
        if display_name:
            row["floor_usage_name"] = usage
            row["floor_load_type_name"] = display_name


def _pdf_row_family(row: dict[str, Any]) -> str:
    text = str(row.get("load_case_name") or row.get("category") or row.get("forced_category") or row.get("load_component_type") or "").upper()
    return "LL" if any(token in text for token in ("LL", "LIVE", "활", "LIVE_LOAD")) else "DL"


def _pdf_row_value(row: dict[str, Any]) -> float | None:
    value = row.get("floor_load_value")
    if value is None:
        value = row.get("load_value_kn_per_m2")
    if value is None:
        value = row.get("load_value")
    try:
        return abs(float(value))
    except (TypeError, ValueError):
        return None


def _first_pdf_value(rows: Sequence[dict[str, Any]], key: str) -> float | None:
    for row in rows:
        value = row.get(key)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def extract_load_layer_lines(rows: Iterable[dict[str, Any]]) -> list[str]:
    """V3 valid_rows를 V4 DXF 레이어 입력 형식으로 변환한다."""
    grouped: dict[str, dict[str, float]] = {}
    for row in filter_accepted_pdf_rows(rows):
        name = str(row.get("floor_load_type_name") or row.get("floor_load_group_key") or row.get("floor_usage_name") or "").strip()
        if not name:
            continue
        case_name = str(row.get("load_case_name") or row.get("category") or "").upper()
        try:
            value = abs(float(row.get("floor_load_value") or row.get("load_value_kn_per_m2") or 0.0))
        except (TypeError, ValueError):
            value = 0.0
        bucket = grouped.setdefault(name, {"DL": 0.0, "LL": 0.0})
        family = _load_case_family(case_name)
        if family == "LL":
            bucket["LL"] += value
        else:
            bucket["DL"] += value
    lines = []
    for name in sorted(grouped):
        vals = grouped[name]
        lines.append(f"{name}, DL:{_fmt(vals['DL'])} LL:{_fmt(vals['LL'])}")
    return lines


def merge_pdf_mgtx_into_full_mgt(
    *,
    source_mgt_path: str | Path,
    pdf_mgtx_path: str | Path,
    output_mgt_path: str | Path,
    collision_mode: str = "skip_existing",
    encoding: str = "cp949",
) -> PdfMgtMergeResult:
    """V3가 생성한 MGTX의 *STLDCASE, *FLOADTYPE를 현재 full MGT에 병합한다."""

    source_text = read_text(source_mgt_path)
    mgtx_text = read_text(pdf_mgtx_path)
    existing_cases = _extract_stldcase_names(source_text)
    existing_types = _extract_floadtype_names(source_text)
    new_cases = _extract_stldcase_lines(mgtx_text)
    new_types = _extract_floadtype_groups(mgtx_text)

    collision_mode = (collision_mode or "skip_existing").lower()
    add_case_lines: list[str] = []
    skip_cases: list[str] = []
    for name, line in new_cases:
        if name in existing_cases:
            skip_cases.append(name)
        else:
            add_case_lines.append(line)
            existing_cases.add(name)

    add_type_pairs: list[tuple[str, str]] = []
    skip_types: list[str] = []
    for name, line1, line2 in new_types:
        if name in existing_types and collision_mode == "skip_existing":
            skip_types.append(name)
            continue
        if name in existing_types and collision_mode == "rename_new":
            renamed = _unique_name(name, existing_types)
            line1 = _replace_first_csv_field(line1, renamed)
            name = renamed
        add_type_pairs.append((line1, line2))
        existing_types.add(name)

    insert_blocks: list[str] = []
    if add_case_lines:
        insert_blocks.extend(["", "*STLDCASE    ; Static Load Cases", "; LCNAME, LCTYPE, DESC"])
        insert_blocks.extend(add_case_lines)
    if add_type_pairs:
        insert_blocks.extend([
            "",
            "*FLOADTYPE    ; Define Floor Load Type",
            "; NAME, DESC                                           ; 1st line",
            "; LCNAME1, FLOAD1, bSBU1, ..., LCNAME8, FLOAD8, bSBU8  ; 2nd line",
        ])
        for line1, line2 in add_type_pairs:
            insert_blocks.extend([line1, line2])

    lines = source_text.splitlines()
    if insert_blocks:
        insert_at = next((i for i, line in enumerate(lines) if line.strip().upper().startswith("*ENDDATA")), len(lines))
        lines = lines[:insert_at] + insert_blocks + [""] + lines[insert_at:]
    merged = "\r\n".join(lines) + "\r\n"
    output = write_text(output_mgt_path, merged, encoding=encoding)
    return PdfMgtMergeResult(
        output_mgt_path=output,
        added_stldcase_count=len(add_case_lines),
        added_floadtype_count=len(add_type_pairs),
        skipped_stldcase_names=tuple(skip_cases),
        skipped_floadtype_names=tuple(skip_types),
    )


def _ensure_legacy_path(legacy_src: Path) -> None:
    text = str(legacy_src)
    if text in sys.path:
        sys.path.remove(text)
    sys.path.insert(0, text)


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _make_no_pdf_rows(pdf_paths: Sequence[Path], legacy_dir: Path) -> list[dict[str, Any]]:
    rows = []
    for pdf_path in pdf_paths:
        rows.append({
            "source_pdf": pdf_path.name,
            "source_page": None,
            "extraction_method": "scan_ocr_fallback",
            "pdf_page_type": "UNKNOWN",
            "ocr_required": True,
            "mgtx_row_count": 0,
            "review_flag": True,
            "exclude_from_mgtx": True,
            "is_valid_for_mgtx": False,
            "failure_stage": "OCR_NOT_TRIGGERED",
            "failure_reason": "No candidate rows were returned by PDF extraction.",
            "exclude_reason": "스캔 PDF에서 유효한 하중표 row를 생성하지 못함",
            "debug_dir": str(legacy_dir / "debug" / "ocr_fallback" / pdf_path.stem),
        })
    if not rows:
        rows.append({
            "source_pdf": "",
            "source_page": None,
            "extraction_method": "none",
            "pdf_page_type": "UNKNOWN",
            "ocr_required": True,
            "mgtx_row_count": 0,
            "review_flag": True,
            "exclude_from_mgtx": True,
            "is_valid_for_mgtx": False,
            "failure_stage": "OCR_NOT_TRIGGERED",
            "failure_reason": "No PDF files or candidate rows were found.",
            "exclude_reason": "유효한 하중표 row를 생성하지 못함",
        })
    return rows


def _write_layer_lines_csv(path: Path, lines: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["layer_input_text"])
        for line in lines:
            writer.writerow([line])


def _count_records(text: str, section_name: str) -> int:
    return sum(1 for line in section_lines(text, section_name) if _is_data_line(line, section_name))


def _count_floadtype_records(text: str) -> int:
    return len(_extract_floadtype_names(text))


def _is_data_line(line: str, section_name: str) -> bool:
    stripped = line.strip()
    if not stripped or stripped.startswith(";") or stripped.upper().startswith(section_name.upper()):
        return False
    return bool(stripped.split(";", 1)[0].strip())


def _extract_stldcase_lines(text: str) -> list[tuple[str, str]]:
    result = []
    for line in section_lines(text, "*STLDCASE"):
        if not _is_data_line(line, "*STLDCASE"):
            continue
        fields = _csv_split(line.split(";", 1)[0].strip())
        if fields:
            result.append((fields[0].strip().strip('"'), line.rstrip()))
    return result


def _extract_stldcase_names(text: str) -> set[str]:
    return {name for name, _line in _extract_stldcase_lines(text)}


def _extract_floadtype_groups(text: str) -> list[tuple[str, str, str]]:
    data_lines = [line.rstrip() for line in section_lines(text, "*FLOADTYPE") if _is_data_line(line, "*FLOADTYPE")]
    groups: list[tuple[str, str, str]] = []
    i = 0
    while i < len(data_lines):
        line1 = data_lines[i]
        line2 = data_lines[i + 1] if i + 1 < len(data_lines) else ""
        fields = _csv_split(line1.split(";", 1)[0].strip())
        name = fields[0].strip().strip('"') if fields else ""
        if name:
            groups.append((name, line1, line2))
        i += 2
    return groups


def _extract_floadtype_names(text: str) -> set[str]:
    return {name for name, _line1, _line2 in _extract_floadtype_groups(text)}


def _csv_split(line: str) -> list[str]:
    try:
        return [cell.strip() for cell in next(csv.reader(io.StringIO(line), skipinitialspace=True))]
    except Exception:
        return [cell.strip() for cell in line.split(",")]


def _replace_first_csv_field(line: str, new_value: str) -> str:
    indent = re.match(r"^\s*", line).group(0)
    parts = _csv_split(line.strip())
    if not parts:
        return line
    parts[0] = new_value
    escaped = []
    for value in parts:
        text = str(value).replace('"', "'")
        escaped.append(f'"{text}"' if "," in text else text)
    return indent + ", ".join(escaped)


def _unique_name(base: str, used: set[str]) -> str:
    for idx in range(2, 1000):
        candidate = f"{base}_PDF{idx}"
        if candidate not in used:
            return candidate
    return f"{base}_PDF_{uuid.uuid4().hex[:6]}"


def _load_case_family(case_name: str) -> str:
    text = str(case_name or "").upper()
    if "LL" in text or "LIVE" in text or "활" in text:
        return "LL"
    return "DL"


def _fmt(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _safe_name(value: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "_", str(value or "job")).strip()
    return text or "job"
