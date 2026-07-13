from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence
import csv
import io
import json
import math
import os
import re
import tempfile

from shapely.geometry import Polygon


DEFAULT_FLOORLOAD_MAX_LOGICAL_FIELDS = 25
DEFAULT_MAX_PHYSICAL_LINE_CHARACTERS = 240
DEFAULT_MAX_PHYSICAL_FIELDS = 25
FLOORLOAD_PREFIX_FIELDS_BY_IDIST = {1: 12, 2: 12, 3: 6, 4: 6}
_MODEL_DATA_SECTIONS = ("UNIT", "NODE", "ELEMENT", "MATERIAL", "SECTION", "STORY")


@dataclass(frozen=True)
class MgtImportCapabilities:
    profile_name: str = "CONSERVATIVE"
    gen_version: str = ""
    max_logical_fields_by_command: Mapping[str, int] = field(
        default_factory=lambda: {"FLOORLOAD": DEFAULT_FLOORLOAD_MAX_LOGICAL_FIELDS}
    )
    max_physical_line_characters: int = DEFAULT_MAX_PHYSICAL_LINE_CHARACTERS
    max_physical_fields: int = DEFAULT_MAX_PHYSICAL_FIELDS
    supports_continuation_commands: frozenset[str] = field(default_factory=lambda: frozenset({"FLOORLOAD"}))
    text_encoding: str = "cp949"
    newline: str = "\r\n"
    strict_import_verification: bool = True

    def logical_field_limit(self, command: str) -> int | None:
        value = self.max_logical_fields_by_command.get(str(command or "").upper())
        return None if value is None else max(0, int(value))

    def floorload_node_limit(self, idist: int) -> int | None:
        logical_limit = self.logical_field_limit("FLOORLOAD")
        prefix_count = FLOORLOAD_PREFIX_FIELDS_BY_IDIST.get(int(idist))
        if logical_limit is None or prefix_count is None:
            return None
        return max(0, logical_limit - prefix_count)


@dataclass(frozen=True)
class MgtTextDocument:
    text: str
    encoding: str
    newline: str
    path: Path | None = None


@dataclass(frozen=True)
class LogicalMgtRecord:
    section_name: str
    logical_record_index: int
    physical_start_line: int
    physical_end_line: int
    raw_physical_lines: tuple[str, ...]
    logical_text: str
    fields: tuple[str, ...]
    continued: bool
    encoding: str = ""


@dataclass(frozen=True)
class ModelImportFingerprint:
    node_count: int = 0
    element_count: int = 0
    story_count: int = 0
    material_count: int = 0
    section_count: int = 0
    thickness_count: int = 0
    load_case_count: int = 0
    floorload_type_count: int = 0
    floorload_count: int = 0
    coordinate_bbox: tuple[float, float, float, float, float, float] | None = None
    node_id_sample: tuple[int, ...] = ()
    element_id_sample: tuple[int, ...] = ()

    def counts(self) -> dict[str, int]:
        return {
            "NODE": self.node_count,
            "ELEM": self.element_count,
            "STOR": self.story_count,
            "MATERIAL": self.material_count,
            "SECTION": self.section_count,
            "THICKNESS": self.thickness_count,
            "STLDCASE": self.load_case_count,
            "FLOADTYPE": self.floorload_type_count,
            "FLOORLOAD": self.floorload_count,
        }


@dataclass(frozen=True)
class MgtValidationIssue:
    status: str
    severity: str
    code: str
    section: str = ""
    logical_record_index: int | None = None
    physical_start_line: int | None = None
    physical_end_line: int | None = None
    load_name: str = ""
    story_name: str = ""
    logical_field_count: int | None = None
    allowed_field_count: int | None = None
    node_count: int | None = None
    allowed_node_count: int | None = None
    source_region_keys: tuple[str, ...] = ()
    message_ko: str = ""
    action_ko: str = ""

    def to_dict(self) -> dict[str, Any]:
        row = asdict(self)
        row["source_region_keys"] = list(self.source_region_keys)
        row["physical_line_range"] = (
            ""
            if self.physical_start_line is None
            else f"{self.physical_start_line}-{self.physical_end_line or self.physical_start_line}"
        )
        return row


@dataclass(frozen=True)
class MgtValidationResult:
    issues: tuple[MgtValidationIssue, ...]
    model_fingerprint: ModelImportFingerprint
    capabilities: MgtImportCapabilities
    source_path: str = ""
    encoding: str = ""
    newline: str = ""

    @property
    def has_errors(self) -> bool:
        return any(issue.severity.upper() == "ERROR" for issue in self.issues)

    @property
    def status(self) -> str:
        return "ERROR" if self.has_errors else "PASS"

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": "MGT_IMPORT_PREFLIGHT",
            "status": self.status,
            "source_path": self.source_path,
            "encoding": self.encoding,
            "newline": _newline_name(self.newline),
            "capabilities": _capabilities_to_dict(self.capabilities),
            "expected_counts": self.model_fingerprint.counts(),
            "model_fingerprint": asdict(self.model_fingerprint),
            "issues": [issue.to_dict() for issue in self.issues],
        }


class MgtPreflightError(RuntimeError):
    def __init__(self, result: MgtValidationResult, *, report_path: str | Path | None = None):
        errors = [issue for issue in result.issues if issue.severity.upper() == "ERROR"]
        first = errors[0] if errors else None
        message = "MGT import 사전검증에 실패하여 MIDAS 새 프로젝트 생성과 import를 실행하지 않았습니다."
        if first is not None:
            location = ""
            if first.physical_start_line is not None:
                location = f" (원본 줄 {first.physical_start_line}-{first.physical_end_line or first.physical_start_line})"
            message += f"\n[{first.code}]{location} {first.message_ko}"
            if first.action_ko:
                message += f"\n조치: {first.action_ko}"
        if report_path:
            message += f"\n검증 report: {Path(report_path)}"
        super().__init__(message)
        self.result = result
        self.report_path = Path(report_path) if report_path else None


@dataclass
class MgtModelIndex:
    records_by_section: dict[str, list[LogicalMgtRecord]]
    sections_seen: tuple[str, ...]
    nodes: dict[int, tuple[float, float, float]] = field(default_factory=dict)
    elements: dict[int, tuple[str, int | None, int | None, tuple[int, ...]]] = field(default_factory=dict)
    stories: dict[str, float] = field(default_factory=dict)
    material_ids: set[int] = field(default_factory=set)
    section_ids: set[int] = field(default_factory=set)
    thickness_ids: set[int] = field(default_factory=set)
    load_cases: set[str] = field(default_factory=set)
    floorload_types: dict[str, tuple[str, ...]] = field(default_factory=dict)
    frame_release_element_ids: set[int] = field(default_factory=set)

    @property
    def fingerprint(self) -> ModelImportFingerprint:
        coordinates = list(self.nodes.values())
        bbox = None
        if coordinates:
            xs, ys, zs = zip(*coordinates)
            bbox = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
        return ModelImportFingerprint(
            node_count=len(self.nodes),
            element_count=len(self.elements),
            story_count=len(self.stories),
            material_count=len(self.material_ids),
            section_count=len(self.section_ids),
            thickness_count=len(self.thickness_ids),
            load_case_count=len(self.load_cases),
            floorload_type_count=len(self.floorload_types),
            floorload_count=len(self.records_by_section.get("FLOORLOAD", ())),
            coordinate_bbox=bbox,
            node_id_sample=_id_sample(self.nodes),
            element_id_sample=_id_sample(self.elements),
        )


def resolve_mgt_import_capabilities(
    *,
    profile_name: str = "AUTO",
    gen_version: str = "",
    floorload_max_logical_fields: int | None = None,
    strict_import_verification: bool = True,
    source_text: str = "",
    text_encoding: str = "cp949",
    newline: str = "\r\n",
) -> MgtImportCapabilities:
    requested = str(profile_name or "AUTO").strip().upper()
    if floorload_max_logical_fields is not None:
        limit = max(1, int(floorload_max_logical_fields))
        resolved_name = f"{requested}:USER"
    else:
        profile_limits = {
            "CONSERVATIVE": DEFAULT_FLOORLOAD_MAX_LOGICAL_FIELDS,
            "GEN_LEGACY": 25,
            "GEN_NX": 64,
        }
        if requested in profile_limits:
            limit = profile_limits[requested]
            resolved_name = requested
        else:
            version_key = str(gen_version or "").upper()
            matched = "GEN_NX" if "NX" in version_key else ("GEN_LEGACY" if version_key else "")
            if matched:
                limit = profile_limits[matched]
                resolved_name = matched
            else:
                observed = _observed_floorload_logical_field_limit(source_text)
                limit = max(DEFAULT_FLOORLOAD_MAX_LOGICAL_FIELDS, observed or 0)
                resolved_name = "AUTO:SOURCE" if observed else "CONSERVATIVE"
    return MgtImportCapabilities(
        profile_name=resolved_name,
        gen_version=str(gen_version or ""),
        max_logical_fields_by_command={"FLOORLOAD": limit},
        text_encoding=str(text_encoding or "cp949"),
        newline=newline or "\r\n",
        strict_import_verification=bool(strict_import_verification),
    )


def read_mgt_text_document(path: str | Path, *, preferred_encoding: str | None = None) -> MgtTextDocument:
    source = Path(path).expanduser().resolve()
    data = source.read_bytes()
    encoding = _detect_text_encoding(data, preferred_encoding=preferred_encoding)
    text = data.decode(encoding, errors="strict")
    return MgtTextDocument(text=text, encoding=encoding, newline=_detect_newline(text), path=source)


def write_mgt_text_atomic(
    path: str | Path,
    text: str,
    *,
    encoding: str,
    newline: str = "\r\n",
    validator=None,
) -> Path:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = _normalize_newlines(text, newline or "\r\n")
    try:
        payload = normalized.encode(encoding, errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(
            f"MGT 파일을 {encoding} 인코딩으로 저장할 수 없는 문자가 있습니다: {exc}"
        ) from exc
    temp_path: Path | None = None
    try:
        fd, raw_temp = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
        temp_path = Path(raw_temp)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        if validator is not None:
            validator(normalized)
        os.replace(temp_path, target)
        temp_path = None
        return target
    except PermissionError as exc:
        raise PermissionError(
            f"MGT 파일 저장 권한이 없습니다: {target}. 파일이 열려 있는지와 폴더 쓰기 권한을 확인하세요."
        ) from exc
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


def iter_mgt_logical_records(text: str, encoding: str = "") -> Iterator[LogicalMgtRecord]:
    section_name = ""
    section_record_index: dict[str, int] = defaultdict(int)
    pending_lines: list[str] = []
    pending_parts: list[str] = []
    pending_start = 0
    pending_continued = False

    def emit(end_line: int) -> LogicalMgtRecord | None:
        nonlocal pending_lines, pending_parts, pending_start, pending_continued
        if not pending_lines:
            return None
        logical_text = _join_continuation_parts(pending_parts)
        section_record_index[section_name] += 1
        record = LogicalMgtRecord(
            section_name=section_name,
            logical_record_index=section_record_index[section_name],
            physical_start_line=pending_start,
            physical_end_line=end_line,
            raw_physical_lines=tuple(pending_lines),
            logical_text=logical_text,
            fields=tuple(_csv_fields(logical_text)),
            continued=pending_continued,
            encoding=encoding,
        )
        pending_lines = []
        pending_parts = []
        pending_start = 0
        pending_continued = False
        return record

    physical_lines = text.splitlines()
    for line_number, raw_line in enumerate(physical_lines, start=1):
        stripped = raw_line.strip()
        section_match = re.match(r"^\s*\*([A-Z0-9_-]+)", raw_line, re.IGNORECASE)
        if section_match:
            pending = emit(line_number - 1)
            if pending is not None:
                yield pending
            section_name = section_match.group(1).upper()
            continue
        if not stripped or stripped.startswith(";"):
            continue
        if not section_name:
            continue
        if not pending_lines:
            pending_start = line_number
        pending_lines.append(raw_line)
        continued = _line_has_continuation(raw_line)
        pending_continued = pending_continued or continued
        part = raw_line.rstrip()
        if continued:
            part = part[:-1].rstrip()
        pending_parts.append(part.strip())
        if not continued:
            record = emit(line_number)
            if record is not None:
                yield record
    pending = emit(len(physical_lines))
    if pending is not None:
        yield pending


def build_mgt_model_index(text: str, *, encoding: str = "") -> MgtModelIndex:
    records_by_section: dict[str, list[LogicalMgtRecord]] = defaultdict(list)
    for record in iter_mgt_logical_records(text, encoding=encoding):
        records_by_section[record.section_name].append(record)
    sections_seen = tuple(
        match.group(1).upper()
        for line in text.splitlines()
        if (match := re.match(r"^\s*\*([A-Z0-9_-]+)", line, re.IGNORECASE))
    )
    index = MgtModelIndex(records_by_section=dict(records_by_section), sections_seen=sections_seen)

    for record in records_by_section.get("NODE", ()):
        if len(record.fields) < 4:
            continue
        node_id = _as_int(record.fields[0])
        xyz = tuple(_as_float(value) for value in record.fields[1:4])
        if node_id is not None and all(value is not None for value in xyz):
            index.nodes[node_id] = (float(xyz[0]), float(xyz[1]), float(xyz[2]))  # type: ignore[arg-type]

    for record in records_by_section.get("ELEMENT", ()):
        fields = record.fields
        if len(fields) < 6:
            continue
        element_id = _as_int(fields[0])
        if element_id is None:
            continue
        element_type = str(fields[1] or "").strip().upper()
        material_id = _as_int(fields[2])
        property_id = _as_int(fields[3])
        node_count = _element_node_count(element_type, len(fields) - 4)
        node_ids = tuple(value for value in (_as_int(field) for field in fields[4 : 4 + node_count]) if value is not None)
        index.elements[element_id] = (element_type, material_id, property_id, node_ids)

    for record in records_by_section.get("STORY", ()):
        if len(record.fields) >= 2:
            elevation = _as_float(record.fields[1])
            if elevation is not None:
                index.stories[_unquote(record.fields[0])] = elevation

    index.material_ids.update(_first_integer_ids(records_by_section.get("MATERIAL", ())))
    index.section_ids.update(_first_integer_ids(records_by_section.get("SECTION", ())))
    index.thickness_ids.update(_first_integer_ids(records_by_section.get("THICKNESS", ())))
    index.frame_release_element_ids.update(_first_integer_ids(records_by_section.get("FRAME-RLS", ())))
    index.load_cases.update(
        _unquote(record.fields[0]) for record in records_by_section.get("STLDCASE", ()) if record.fields and _unquote(record.fields[0])
    )
    index.floorload_types.update(_parse_floorload_types(records_by_section.get("FLOADTYPE", ())))
    return index


def validate_floorload_logical_record(
    record: LogicalMgtRecord,
    capabilities: MgtImportCapabilities,
    model_index: MgtModelIndex,
    *,
    story_tolerance: float = 0.01,
) -> list[MgtValidationIssue]:
    issues: list[MgtValidationIssue] = []
    fields = tuple(record.fields)
    load_name = _unquote(fields[0]) if fields else ""
    base = dict(
        section="FLOORLOAD",
        logical_record_index=record.logical_record_index,
        physical_start_line=record.physical_start_line,
        physical_end_line=record.physical_end_line,
        load_name=load_name,
        logical_field_count=len(fields),
    )
    idist = _as_int(fields[1]) if len(fields) > 1 else None
    if idist not in FLOORLOAD_PREFIX_FIELDS_BY_IDIST:
        issues.append(_issue("FLOORLOAD_INVALID_IDIST", "FLOORLOAD iDIST가 1, 2, 3, 4 중 하나가 아닙니다.", "하중 분배 형식과 prefix field를 확인하세요.", **base))
        return issues
    prefix_count = FLOORLOAD_PREFIX_FIELDS_BY_IDIST[idist]
    allowed_fields = capabilities.logical_field_limit("FLOORLOAD")
    allowed_nodes = capabilities.floorload_node_limit(idist)
    if len(fields) < prefix_count:
        issues.append(_issue("FLOORLOAD_INVALID_PREFIX", f"iDIST={idist} FLOORLOAD의 필수 prefix field가 부족합니다.", "iDIST 형식에 맞는 DESC/GROUP 전 field를 확인하세요.", **base))
        return issues
    if allowed_fields is not None and len(fields) > allowed_fields:
        issues.append(
            _issue(
                "FLOORLOAD_LOGICAL_FIELD_LIMIT_EXCEEDED",
                f"continuation을 합친 FLOORLOAD logical record field 수 {len(fields)}개가 허용값 {allowed_fields}개를 초과합니다.",
                "영역 경계를 단순화하거나 source assignment provenance를 유지한 여러 FLOORLOAD로 나누세요.",
                allowed_field_count=allowed_fields,
                node_count=max(0, len(fields) - prefix_count),
                allowed_node_count=allowed_nodes,
                **base,
            )
        )
    node_fields = fields[prefix_count:]
    if allowed_nodes is not None and len(node_fields) > allowed_nodes:
        issues.append(
            _issue(
                "FLOORLOAD_NODE_LIMIT_EXCEEDED",
                f"iDIST={idist} FLOORLOAD node 수 {len(node_fields)}개가 허용값 {allowed_nodes}개를 초과합니다.",
                "원본 영역을 여러 유효 assignment로 유지하거나 경계의 불필요한 공선 node를 줄이세요.",
                allowed_field_count=allowed_fields,
                node_count=len(node_fields),
                allowed_node_count=allowed_nodes,
                **base,
            )
        )
    if not load_name:
        issues.append(_issue("FLOORLOAD_EMPTY_LOAD_NAME", "FLOORLOAD 하중명이 비어 있습니다.", "유효한 FLOADTYPE 이름을 지정하세요.", **base))
    forbidden = re.search(r"DXF_AUTO|DXF_FLOORLOAD|\bLOAD_\d{3}_", record.logical_text, re.IGNORECASE)
    if forbidden:
        issues.append(_issue("FLOORLOAD_FORBIDDEN_UI_TEXT", f"FLOORLOAD에 CAD/UI 전용 문자열 '{forbidden.group(0)}'이 포함되어 있습니다.", "CAD 추적 정보는 report에만 기록하고 MGT field에서는 제거하세요.", **base))
    group_index = 11 if idist in {1, 2} else 5
    if group_index < len(fields) and _unquote(fields[group_index]):
        issues.append(_issue("FLOORLOAD_GROUP_POLICY", "자동 생성 FLOORLOAD의 GROUP field가 비어 있지 않습니다.", "GROUP은 비우고 provenance는 report에 기록하세요.", **base))

    node_ids: list[int] = []
    invalid_node_tokens: list[str] = []
    for token in node_fields:
        node_id = _as_int(token)
        if node_id is None:
            invalid_node_tokens.append(str(token))
        else:
            node_ids.append(node_id)
    if invalid_node_tokens:
        issues.append(_issue("FLOORLOAD_INVALID_NODE_ID", f"정수로 변환할 수 없는 FLOORLOAD node field가 있습니다: {', '.join(invalid_node_tokens[:3])}", "node field와 continuation comma 위치를 확인하세요.", node_count=len(node_fields), allowed_node_count=allowed_nodes, **base))
    if len(node_ids) < 3:
        issues.append(_issue("FLOORLOAD_INVALID_POLYGON", "FLOORLOAD polygon에는 서로 다른 node가 최소 3개 필요합니다.", "폐합 영역과 node snapping 결과를 확인하세요.", node_count=len(node_ids), allowed_node_count=allowed_nodes, **base))
    if idist == 1 and len(node_ids) not in {3, 4}:
        issues.append(_issue("FLOORLOAD_INVALID_POLYGON", "ONE-WAY FLOORLOAD는 3개 또는 4개 node만 사용할 수 있습니다.", "영역을 삼각형/사각형으로 유지하거나 TWO-WAY로 변경하세요.", node_count=len(node_ids), allowed_node_count=min(4, allowed_nodes or 4), **base))
    if any(left == right for left, right in zip(node_ids, node_ids[1:])):
        issues.append(_issue("FLOORLOAD_INVALID_POLYGON", "FLOORLOAD에 연속 중복 node가 있습니다.", "연속 중복 node를 제거하세요.", node_count=len(node_ids), allowed_node_count=allowed_nodes, **base))
    missing = [node_id for node_id in node_ids if node_id not in model_index.nodes]
    if missing:
        issues.append(_issue("FLOORLOAD_NODE_NOT_FOUND", f"모델 *NODE에 없는 node를 참조합니다: {', '.join(map(str, missing[:8]))}", "source/patched NODE 보존 여부와 story node snapping을 확인하세요.", node_count=len(node_ids), allowed_node_count=allowed_nodes, **base))
    elif len(node_ids) >= 3:
        coords = [model_index.nodes[node_id] for node_id in node_ids]
        polygon = Polygon([(x, y) for x, y, _z in coords])
        if not polygon.is_valid or polygon.area <= 1.0e-12:
            issues.append(_issue("FLOORLOAD_INVALID_POLYGON", "FLOORLOAD polygon 면적이 0이거나 self-intersection이 있습니다.", "node 순서와 경계 geometry를 확인하세요.", node_count=len(node_ids), allowed_node_count=allowed_nodes, **base))
        z_values = [coord[2] for coord in coords]
        if max(z_values) - min(z_values) > abs(float(story_tolerance)):
            issues.append(_issue("FLOORLOAD_NODE_STORY_MISMATCH", "하나의 FLOORLOAD가 서로 다른 elevation의 node를 참조합니다.", "동일 Story node set으로 다시 snapping하세요.", node_count=len(node_ids), allowed_node_count=allowed_nodes, **base))
        elif model_index.stories and not any(abs(sum(z_values) / len(z_values) - elevation) <= abs(float(story_tolerance)) for elevation in model_index.stories.values()):
            issues.append(_issue("FLOORLOAD_NODE_STORY_MISMATCH", "FLOORLOAD node elevation과 일치하는 *STORY가 없습니다.", "Story elevation과 node Z 좌표를 확인하세요.", node_count=len(node_ids), allowed_node_count=allowed_nodes, **base))
    if load_name and load_name not in model_index.floorload_types:
        issues.append(_issue("FLOORLOAD_FLOADTYPE_NOT_FOUND", f"FLOORLOAD가 정의되지 않은 FLOADTYPE '{load_name}'을 참조합니다.", "*FLOADTYPE 정의를 FLOORLOAD 앞에 추가하세요.", **base))
    elif load_name:
        missing_cases = [name for name in model_index.floorload_types.get(load_name, ()) if name not in model_index.load_cases]
        if missing_cases:
            issues.append(_issue("FLOORLOAD_STLDCASE_NOT_FOUND", f"FLOADTYPE '{load_name}'이 정의되지 않은 STLDCASE를 참조합니다: {', '.join(missing_cases)}", "*STLDCASE에 하중 case를 정의하거나 FLOADTYPE 참조를 수정하세요.", **base))
    try:
        record.logical_text.encode(capabilities.text_encoding, errors="strict")
    except UnicodeEncodeError:
        issues.append(_issue("FLOORLOAD_ENCODING_ERROR", f"FLOORLOAD record를 {capabilities.text_encoding}으로 인코딩할 수 없습니다.", "지원 문자를 사용하거나 capability text_encoding을 변경하세요.", **base))
    return issues


def validate_mgt_for_import(
    source_mgt_path: str | Path | None = None,
    *,
    text: str | None = None,
    capabilities: MgtImportCapabilities | None = None,
    original_source_path: str | Path | None = None,
    original_source_text: str | None = None,
    encoding: str | None = None,
    story_tolerance: float = 0.01,
    allowed_changed_sections: Iterable[str] = (),
) -> MgtValidationResult:
    document_path = ""
    detected_newline = "\r\n"
    if text is None:
        if source_mgt_path is None:
            raise ValueError("source_mgt_path 또는 text가 필요합니다.")
        candidate = str(source_mgt_path)
        if "\n" in candidate or "\r" in candidate:
            text = candidate
            detected_encoding = encoding or "utf-8"
            detected_newline = _detect_newline(text)
        else:
            document = read_mgt_text_document(source_mgt_path, preferred_encoding=encoding)
            text = document.text
            detected_encoding = document.encoding
            detected_newline = document.newline
            document_path = str(document.path or "")
    else:
        detected_encoding = encoding or "utf-8"
        detected_newline = _detect_newline(text)
        document_path = str(Path(source_mgt_path).expanduser().resolve()) if source_mgt_path else ""
    caps = capabilities or resolve_mgt_import_capabilities(
        source_text=text,
        text_encoding=detected_encoding,
        newline=detected_newline,
    )
    index = build_mgt_model_index(text, encoding=detected_encoding)
    issues: list[MgtValidationIssue] = []
    seen = set(index.sections_seen)
    for required in ("UNIT", "NODE", "ELEMENT", "MATERIAL", "SECTION", "ENDDATA"):
        if required not in seen:
            issues.append(_issue("MGT_REQUIRED_SECTION_MISSING", f"full MGT import에 필요한 *{required} section이 없습니다.", f"source MGT export에 *{required}가 포함되었는지 확인하세요.", section=required))
    if index.records_by_section.get("FLOORLOAD"):
        for conditional in ("STLDCASE", "FLOADTYPE"):
            if conditional not in seen:
                issues.append(_issue("MGT_REQUIRED_SECTION_MISSING", f"FLOORLOAD가 있으나 *{conditional} section이 없습니다.", f"*{conditional} 정의를 확인하세요.", section=conditional))
    for element_id, (_type, material_id, property_id, node_ids) in index.elements.items():
        missing_nodes = [node_id for node_id in node_ids if node_id not in index.nodes]
        if missing_nodes:
            issues.append(_issue("ELEMENT_NODE_NOT_FOUND", f"ELEMENT {element_id}가 없는 NODE를 참조합니다: {', '.join(map(str, missing_nodes))}", "원본 ELEMENT/NODE 참조 무결성을 확인하세요.", section="ELEMENT"))
        if material_id is not None and index.material_ids and material_id not in index.material_ids:
            issues.append(_issue("ELEMENT_MATERIAL_NOT_FOUND", f"ELEMENT {element_id}가 없는 MATERIAL {material_id}를 참조합니다.", "MATERIAL ID를 확인하세요.", section="ELEMENT"))
        if property_id is not None and index.section_ids and index.thickness_ids and property_id not in index.section_ids and property_id not in index.thickness_ids:
            issues.append(_issue("ELEMENT_PROPERTY_NOT_FOUND", f"ELEMENT {element_id}가 없는 SECTION/THICKNESS {property_id}를 참조합니다.", "요소 형식에 맞는 property ID를 확인하세요.", section="ELEMENT"))
    for element_id in index.frame_release_element_ids:
        if element_id not in index.elements:
            issues.append(_issue("FRAME_RLS_ELEMENT_NOT_FOUND", f"FRAME-RLS가 없는 ELEMENT {element_id}를 참조합니다.", "FRAME-RLS element ID를 확인하세요.", section="FRAME-RLS"))
    for record in index.records_by_section.get("FLOORLOAD", ()):
        issues.extend(validate_floorload_logical_record(record, caps, index, story_tolerance=story_tolerance))
    issues.extend(_validate_physical_lines(text, caps))
    try:
        text.encode(caps.text_encoding, errors="strict")
    except UnicodeEncodeError as exc:
        issues.append(_issue("MGT_ENCODING_ERROR", f"MGT 전체를 {caps.text_encoding}으로 인코딩할 수 없습니다: {exc}", "capability encoding을 바꾸거나 지원되지 않는 문자를 정리하세요."))

    if original_source_text is None and original_source_path is not None:
        original_source_text = read_mgt_text_document(original_source_path).text
    if original_source_text is not None:
        issues.extend(
            compare_source_and_patched_model_sections(
                original_source_text,
                text,
                allowed_changed_sections=allowed_changed_sections,
            )
        )
    return MgtValidationResult(
        issues=tuple(issues),
        model_fingerprint=index.fingerprint,
        capabilities=caps,
        source_path=document_path,
        encoding=detected_encoding,
        newline=detected_newline,
    )


def compare_source_and_patched_model_sections(
    source_text: str,
    patched_text: str,
    *,
    allowed_changed_sections: Iterable[str] = (),
) -> list[MgtValidationIssue]:
    allowed = {str(name or "").strip().upper().lstrip("*") for name in allowed_changed_sections}
    allowed.update({"FLOADTYPE", "FLOORLOAD"})
    source = build_mgt_model_index(source_text)
    patched = build_mgt_model_index(patched_text)
    issues: list[MgtValidationIssue] = []
    for section in dict.fromkeys(source.sections_seen):
        if section in allowed or section == "ENDDATA":
            continue
        before = tuple(_normalized_record_text(record.logical_text) for record in source.records_by_section.get(section, ()))
        after = tuple(_normalized_record_text(record.logical_text) for record in patched.records_by_section.get(section, ()))
        if before != after:
            issues.append(_issue("SOURCE_MODEL_SECTION_CHANGED", f"patched MGT에서 기존 *{section} data record가 변경되었습니다.", "기존 model section은 재정렬하거나 수정하지 말고 계획된 load section만 추가하세요.", section=section))
    for section in _MODEL_DATA_SECTIONS:
        if section in allowed:
            continue
        before_count = len(source.records_by_section.get(section, ()))
        after_count = len(patched.records_by_section.get(section, ()))
        if before_count != after_count and not any(issue.section == section for issue in issues):
            issues.append(_issue("SOURCE_MODEL_COUNT_CHANGED", f"*{section} record 수가 {before_count}개에서 {after_count}개로 변경되었습니다.", "원본 model data count를 보존하세요.", section=section))
    if "NODE" in allowed:
        existing_nodes_changed = any(patched.nodes.get(node_id) != coordinates for node_id, coordinates in source.nodes.items())
    else:
        existing_nodes_changed = source.nodes != patched.nodes
    if existing_nodes_changed:
        issues.append(_issue("SOURCE_NODE_COORDINATES_CHANGED", "patched MGT의 기존 NODE ID 또는 좌표가 source와 다릅니다.", "원본 NODE 좌표를 복원하고 계획된 추가 node만 별도로 생성하세요.", section="NODE"))
    if source.sections_seen.count("ENDDATA") != 1 or patched.sections_seen.count("ENDDATA") != 1:
        issues.append(_issue("MGT_ENDDATA_INVALID", "source/patched MGT에는 *ENDDATA가 정확히 한 번 있어야 합니다.", "ENDDATA 중복 또는 누락을 수정하세요.", section="ENDDATA"))
    elif patched.sections_seen[-1] != "ENDDATA":
        issues.append(_issue("MGT_ENDDATA_INVALID", "patched MGT의 *ENDDATA 뒤에 다른 section이 있습니다.", "새 load section을 *ENDDATA 앞에 삽입하세요.", section="ENDDATA"))
    return _deduplicate_issues(issues)


def write_validation_report(
    result: MgtValidationResult,
    output_dir: str | Path,
    *,
    json_name: str = "mgt_import_preflight.json",
    csv_name: str = "mgt_import_preflight.csv",
) -> tuple[Path, Path]:
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / json_name
    csv_path = directory / csv_name
    _write_json_atomic(json_path, result.to_dict())
    rows = [issue.to_dict() for issue in result.issues]
    if not rows:
        rows = [{
            "status": "PASS",
            "severity": "INFO",
            "code": "MGT_IMPORT_PREFLIGHT_PASS",
            "section": "",
            "logical_record_index": "",
            "physical_start_line": "",
            "physical_end_line": "",
            "load_name": "",
            "story_name": "",
            "logical_field_count": "",
            "allowed_field_count": "",
            "node_count": "",
            "allowed_node_count": "",
            "source_region_keys": [],
            "message_ko": "MGT import 사전검증을 통과했습니다.",
            "action_ko": "",
            "physical_line_range": "",
        }]
    fieldnames = list(rows[0])
    temp = csv_path.with_name(f".{csv_path.name}.tmp")
    try:
        with temp.open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                serialized = dict(row)
                serialized["source_region_keys"] = " | ".join(serialized.get("source_region_keys") or ())
                writer.writerow(serialized)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, csv_path)
    finally:
        temp.unlink(missing_ok=True)
    return json_path, csv_path


def floorload_prefix_field_count(idist: int) -> int:
    try:
        return FLOORLOAD_PREFIX_FIELDS_BY_IDIST[int(idist)]
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"지원하지 않는 FLOORLOAD iDIST입니다: {idist}") from exc


def floorload_node_limit(capabilities: MgtImportCapabilities, idist: int) -> int | None:
    return capabilities.floorload_node_limit(idist)


def _parse_floorload_types(records: Sequence[LogicalMgtRecord]) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    index = 0
    while index < len(records):
        name_record = records[index]
        name = _unquote(name_record.fields[0]) if name_record.fields else ""
        value_record = records[index + 1] if index + 1 < len(records) else None
        cases: list[str] = []
        if value_record is not None:
            for field_index in range(0, len(value_record.fields), 3):
                case_name = _unquote(value_record.fields[field_index])
                if case_name:
                    cases.append(case_name)
        if name:
            result[name] = tuple(cases)
        index += 2
    return result


def _validate_physical_lines(text: str, capabilities: MgtImportCapabilities) -> list[MgtValidationIssue]:
    issues: list[MgtValidationIssue] = []
    section = ""
    for line_number, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^\s*\*([A-Z0-9_-]+)", line, re.IGNORECASE)
        if match:
            section = match.group(1).upper()
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        if len(line) > capabilities.max_physical_line_characters:
            issues.append(_issue("MGT_PHYSICAL_LINE_TOO_LONG", f"물리 line 길이 {len(line)}자가 허용값 {capabilities.max_physical_line_characters}자를 초과합니다.", "지원 command이면 continuation으로 물리 line을 줄이세요.", section=section, physical_start_line=line_number, physical_end_line=line_number))
        payload = line.rstrip()
        continued = _line_has_continuation(payload)
        if continued:
            payload = payload[:-1].rstrip()
        fields = _csv_fields(payload)
        if len(fields) > capabilities.max_physical_fields:
            issues.append(_issue("MGT_PHYSICAL_FIELD_LIMIT_EXCEEDED", f"물리 line field 수 {len(fields)}개가 허용값 {capabilities.max_physical_fields}개를 초과합니다.", "physical wrapping 설정을 확인하세요.", section=section, physical_start_line=line_number, physical_end_line=line_number, logical_field_count=len(fields), allowed_field_count=capabilities.max_physical_fields))
        if continued and section not in capabilities.supports_continuation_commands:
            issues.append(_issue("MGT_CONTINUATION_NOT_SUPPORTED", f"*{section} command는 현재 capability에서 continuation을 지원하지 않습니다.", "해당 command를 단일 유효 record로 작성하거나 capability profile을 확인하세요.", section=section, physical_start_line=line_number, physical_end_line=line_number))
    return issues


def _issue(code: str, message_ko: str, action_ko: str, *, severity: str = "ERROR", **kwargs: Any) -> MgtValidationIssue:
    return MgtValidationIssue(status="ERROR" if severity.upper() == "ERROR" else "WARNING", severity=severity.upper(), code=code, message_ko=message_ko, action_ko=action_ko, **kwargs)


def _deduplicate_issues(issues: Sequence[MgtValidationIssue]) -> list[MgtValidationIssue]:
    result: list[MgtValidationIssue] = []
    seen: set[tuple[Any, ...]] = set()
    for issue in issues:
        key = (issue.code, issue.section, issue.logical_record_index, issue.physical_start_line, issue.message_ko)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def _observed_floorload_logical_field_limit(text: str) -> int | None:
    if not text:
        return None
    counts = [len(record.fields) for record in iter_mgt_logical_records(text) if record.section_name == "FLOORLOAD"]
    return max(counts) if counts else None


def _detect_text_encoding(data: bytes, *, preferred_encoding: str | None = None) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    # ASCII-only MGT does not carry enough evidence to distinguish UTF-8 from
    # CP949. Keep the established MIDAS import default so newly appended Korean
    # load names do not silently change the file's effective encoding.
    if all(value < 0x80 for value in data):
        return preferred_encoding or "cp949"
    candidates = [preferred_encoding, "utf-8", "cp949"]
    for encoding in candidates:
        if not encoding:
            continue
        try:
            data.decode(encoding, errors="strict")
            return encoding
        except (UnicodeDecodeError, LookupError):
            continue
    raise UnicodeError("MGT/MGTX 파일 인코딩을 UTF-8 또는 CP949로 해석할 수 없습니다.")


def _detect_newline(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\n" in text:
        return "\n"
    if "\r" in text:
        return "\r"
    return "\r\n"


def _normalize_newlines(text: str, newline: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", newline)


def _newline_name(value: str) -> str:
    return {"\r\n": "CRLF", "\n": "LF", "\r": "CR"}.get(value, repr(value))


def _line_has_continuation(line: str) -> bool:
    return line.rstrip().endswith("\\")


def _join_continuation_parts(parts: Sequence[str]) -> str:
    joined = ""
    for part in parts:
        value = str(part or "").strip()
        if not joined:
            joined = value
        elif joined.rstrip().endswith(",") or value.startswith(","):
            joined += " " + value
        else:
            joined += ", " + value
    return joined


def _csv_fields(value: str) -> list[str]:
    try:
        return [field.strip() for field in next(csv.reader(io.StringIO(value), skipinitialspace=True))]
    except (csv.Error, StopIteration):
        return [field.strip() for field in value.split(",")]


def _normalized_record_text(value: str) -> str:
    return ",".join(_csv_fields(value))


def _unquote(value: Any) -> str:
    text = str(value or "").strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        return text[1:-1].strip()
    return text


def _as_int(value: Any) -> int | None:
    try:
        text = str(value or "").strip()
        if not re.fullmatch(r"[-+]?\d+", text):
            return None
        return int(text)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    try:
        number = float(str(value or "").strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _first_integer_ids(records: Sequence[LogicalMgtRecord]) -> set[int]:
    return {value for record in records if record.fields and (value := _as_int(record.fields[0])) is not None}


def _element_node_count(element_type: str, available: int) -> int:
    normalized = str(element_type or "").upper()
    if normalized in {"BEAM", "TRUSS", "TENSTR", "COMPTR", "TENSION", "COMPRESSION"}:
        return min(2, available)
    if normalized in {"PLATE", "WALL"}:
        return min(4, available)
    if normalized in {"SOLID", "HEXA"}:
        return min(8, available)
    return min(max(2, available), available)


def _id_sample(values: Mapping[int, Any], limit: int = 12) -> tuple[int, ...]:
    ids = sorted(int(value) for value in values)
    if len(ids) <= limit:
        return tuple(ids)
    half = max(1, limit // 2)
    return tuple(ids[:half] + ids[-half:])


def _capabilities_to_dict(capabilities: MgtImportCapabilities) -> dict[str, Any]:
    return {
        "profile_name": capabilities.profile_name,
        "gen_version": capabilities.gen_version,
        "max_logical_fields_by_command": dict(capabilities.max_logical_fields_by_command),
        "max_physical_line_characters": capabilities.max_physical_line_characters,
        "max_physical_fields": capabilities.max_physical_fields,
        "supports_continuation_commands": sorted(capabilities.supports_continuation_commands),
        "text_encoding": capabilities.text_encoding,
        "newline": _newline_name(capabilities.newline),
        "strict_import_verification": capabilities.strict_import_verification,
    }


def _write_json_atomic(path: Path, payload: Any) -> None:
    temp = path.with_name(f".{path.name}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
