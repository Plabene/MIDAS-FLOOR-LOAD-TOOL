from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence
import csv
import json
import math
import re

from shapely.geometry import Point, Polygon

from .mgt_parser import (
    Element,
    Node,
    ParsedElasticLink,
    Story,
    iter_floorload_records_from_text,
    parse_elastic_links_from_text,
    parse_floadtype_specs_from_text,
    parse_materials_from_text,
    parse_sections_from_text,
    parse_stldcase_names_from_text,
    parse_unit_from_text,
    select_nodes_by_story,
)


LINE_TYPES = {"BEAM", "COLUMN", "TRUSS", "TENSTR", "COMPTR", "WALL"}
CANTILEVER_SOURCE_TYPES = {"BEAM", "WALL"}
LINE_OVERLAP_TYPES = {"BEAM", "TRUSS", "TENSTR", "COMPTR"}
DM_ID_MIN = 9900
READY = "READY"
READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
BLOCKED = "BLOCKED"
NO_TARGET_REGION = "NO_TARGET_REGION"
PLANNED_REGION_OUTSIDE_STORY_BELOW_VIEW = "PLANNED_REGION_OUTSIDE_STORY_BELOW_VIEW"
STORY_BELOW_OUTSIDE_MESSAGE = "해당 해치는 선택 Story의 BELOW 기준 하중입력 가능 영역 밖에 있습니다. MIDAS Story BELOW에서 표시되는 보/벽체 경계 안쪽에만 하중을 입력하세요."
BELOW_ALLOWED_REGION_MISSING = "BELOW_ALLOWED_REGION_MISSING"
STORY_BELOW_ALLOWED_REGION_MISSING_MESSAGE = "선택 Story의 BELOW 기준 하중 허용영역을 확인하지 못해 FLOORLOAD 입력을 차단했습니다. 구조요소 표시/Story metadata를 확인하세요."


@dataclass(frozen=True)
class FloorLoadDiagnosticIssue:
    story_name: str
    severity: str
    issue_type: str
    message: str
    x: float
    y: float
    node_ids: list[int]
    element_ids: list[int]
    suggested_action: str

    def to_record(self) -> dict:
        row = asdict(self)
        row["node_ids"] = ",".join(str(value) for value in self.node_ids)
        row["element_ids"] = ",".join(str(value) for value in self.element_ids)
        return row


@dataclass(frozen=True)
class FloorLoadDiagnosticSummary:
    status: str
    unit_force: str
    unit_length: str
    story_count: int
    node_count: int
    element_count: int
    element_type_counts: dict[str, int]
    floadtype_count: int
    existing_floorload_count: int
    planned_region_count: int
    error_count: int
    warning_count: int
    info_count: int
    elastic_link_count: int = 0
    internal_member_supported_count: int = 0
    internal_member_warning_count: int = 0
    diagnostic_message: str = ""


@dataclass(frozen=True)
class FloorLoadDiagnosticResult:
    summary: FloorLoadDiagnosticSummary
    issues: list[FloorLoadDiagnosticIssue]

    def __iter__(self) -> Iterator[FloorLoadDiagnosticIssue]:
        return iter(self.issues)

    def __len__(self) -> int:
        return len(self.issues)

    def __getitem__(self, index: int) -> FloorLoadDiagnosticIssue:
        return self.issues[index]


def diagnostic_issue_category(issue_type: str) -> str:
    """Classify issue types for display-only UI/DXF styling."""
    text = str(issue_type or "").upper()
    if "DUPLICATE" in text or "OVERLAP" in text:
        return "duplicate"
    if "CANTILEVER" in text or "FREE_END" in text or "INTERNAL_MEMBER" in text:
        return "cantilever"
    if "SNAP" in text:
        return "snap"
    if "BELOW_VIEW" in text:
        return "closure"
    if "CLOSURE" in text or "OPEN_BOUNDARY" in text or "SELF_INTERSECTION" in text or "POLYGON" in text:
        return "closure"
    if "ERROR" in text:
        return "error"
    return "warning_or_info"


def diagnostic_issue_user_text(issue: FloorLoadDiagnosticIssue) -> dict[str, str]:
    """Return Korean display text for UI and diagnostic DXF labels."""
    severity_key = str(issue.severity or "").upper()
    severity_label = {
        "ERROR": "오류",
        "WARNING": "확인 필요",
        "INFO": "참고",
    }.get(severity_key, "전문 확인")
    mapping = {
        "DUPLICATE_ELEMENT": (
            "중복 부재",
            "같은 종류의 부재가 같은 절점 조합으로 중복 입력되었습니다.",
            "MIDAS 모델에서 표시된 중복 보 또는 겹친 보를 삭제하거나, 의도된 분할 보인지 확인한 뒤 하나의 일관된 보 체계로 정리하세요. 수정 후 MGT를 다시 Export하고 입력가능성 분석을 재실행하세요.",
            "중복부재",
        ),
        PLANNED_REGION_OUTSIDE_STORY_BELOW_VIEW: (
            "BELOW 영역 밖 해치",
            STORY_BELOW_OUTSIDE_MESSAGE,
            "HATCH VIEW 또는 DXF에서 MIDAS Story BELOW 기준으로 표시되는 폐합영역 안쪽에만 하중 영역을 다시 작성하세요.",
            "BELOW밖해치",
        ),
        "EXACT_COORD_DUPLICATE_ELEMENT": (
            "동일 좌표 중복 부재",
            "절점 번호는 다르지만 양 끝 좌표가 같은 선형 부재가 중복되어 있습니다.",
            "MIDAS 모델에서 표시된 중복 보 또는 겹친 보를 삭제하거나, 의도된 분할 보인지 확인한 뒤 하나의 일관된 보 체계로 정리하세요. 수정 후 MGT를 다시 Export하고 입력가능성 분석을 재실행하세요.",
            "동일좌표",
        ),
        "OVERLAPPING_LINE_ELEMENT": (
            "겹침 선형부재",
            "같은 층의 보 또는 선형 부재가 같은 선상에서 서로 겹칩니다.",
            "MIDAS 모델에서 표시된 중복 보 또는 겹친 보를 삭제하거나, 의도된 분할 보인지 확인한 뒤 하나의 일관된 보 체계로 정리하세요. 수정 후 MGT를 다시 Export하고 입력가능성 분석을 재실행하세요.",
            "겹침부재",
        ),
        "SPLIT_OVERLAP_DUPLICATE_ELEMENT": (
            "분할 보 위 중복 부재",
            "기존에 분할된 보 위에 다른 보가 겹쳐서 입력되었습니다.",
            "MIDAS 모델에서 표시된 중복 보 또는 겹친 보를 삭제하거나, 의도된 분할 보인지 확인한 뒤 하나의 일관된 보 체계로 정리하세요. 수정 후 MGT를 다시 Export하고 입력가능성 분석을 재실행하세요.",
            "분할중복",
        ),
        "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD": (
            "외팔보 자유단 하중전달 확인 필요",
            "폐합영역 내부 또는 경계 인근에 외팔보 자유단이 있고 ELASTIC LINK 연결이 확인되지 않습니다.",
            "DXF 생성/검증 탭에서 로드 더미 빔 자동생성(LOAD DM dummy BEAM 자동 생성) 옵션을 켠 뒤 다시 MGT 입력을 실행하면 해결할 수 있습니다. 이미 구조적으로 연결된 링크가 있는 경우에는 링크 상태를 확인하세요.",
            "외팔자유단",
        ),
        "CANTILEVER_FREE_END_SUPPORTED_BY_ELASTIC_LINK": (
            "외팔보 자유단 링크 연결 확인",
            "외팔보 자유단이 ELASTIC LINK로 주변 구조와 연결되어 있습니다.",
            "일반적으로 추가 더미는 필요 없지만 하중 전달 방향이 의도와 맞는지 확인하세요.",
            "외팔링크",
        ),
        "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD": (
            "폐합영역 내부 부재 확인 필요",
            "FLOORLOAD 폐합영역 내부에 보, 벽체 또는 기타 부재가 있어 하중 입력 또는 전달이 불안정할 수 있습니다.",
            "DXF 생성/검증 탭에서 로드 더미 빔 자동생성(LOAD DM dummy BEAM 자동 생성) 옵션을 켠 뒤 다시 MGT 입력을 실행하면 해결할 수 있습니다. 이미 구조적으로 연결된 링크가 있는 경우에는 링크 상태를 확인하세요.",
            "내부부재",
        ),
        "INTERNAL_MEMBER_SUPPORTED_BY_ELASTIC_LINK": (
            "내부 부재 링크 연결 확인",
            "내부 부재가 ELASTIC LINK로 연결되어 있습니다.",
            "추가 조치는 보통 필요 없지만 하중 전달 의도가 맞는지 확인하세요.",
            "내부링크",
        ),
        "STORY_NOT_DETECTED": (
            "층 인식 실패",
            "DXF 하중영역 또는 진단 대상 영역의 Story 정보가 확인되지 않습니다.",
            "DXF 생성 때 함께 생성된 layout_metadata 파일을 유지하고, 편집 DXF의 하중 영역이 올바른 층 평면 위에 있는지 확인하세요.",
            "층인식",
        ),
        "SNAP_ERROR_EXCEEDED": (
            "절점 스냅 실패",
            "DXF 하중영역 꼭짓점과 MIDAS 절점 사이 거리가 허용오차보다 큽니다.",
            "DXF 해치 경계점이 MIDAS 절점과 맞지 않습니다. DXF에서 해치 꼭짓점을 가장 가까운 센터라인 교차점 또는 FLOORLOAD 경계 노드에 맞춘 뒤 다시 검증하세요.",
            "스냅실패",
        ),
        "FLOORLOAD_NODE_STORY_MISMATCH": (
            "FLOORLOAD 절점 층 불일치",
            "하나의 FLOORLOAD에 서로 다른 층의 절점이 포함되어 있습니다.",
            "해당 FLOORLOAD 경계 절점이 같은 Story에 있는지 확인하고 잘못 스냅된 절점을 수정하세요.",
            "층불일치",
        ),
        "FLOADTYPE_NOT_DEFINED": (
            "FLOORLOAD TYPE 누락",
            "MGT에서 참조 가능한 FLOADTYPE 정보가 없습니다.",
            "하중명 목록에서 FLOORLOAD TYPE을 먼저 생성하거나 FLOADTYPE 이름을 맞춘 뒤 다시 생성하세요.",
            "TYPE누락",
        ),
        "FLOADTYPE_LOADCASE_NOT_DEFINED": (
            "하중 케이스 누락",
            "FLOADTYPE에서 참조하는 정적 하중 케이스가 MGT에 없습니다.",
            "MIDAS 모델의 Static Load Case와 FLOADTYPE 참조명을 일치시킨 뒤 다시 생성하세요.",
            "하중케이스",
        ),
        "STLDCASE_NOT_DEFINED": (
            "하중 케이스 누락",
            "FLOADTYPE에서 참조하는 정적 하중 케이스가 MGT에 없습니다.",
            "MIDAS 모델의 Static Load Case와 FLOADTYPE 참조명을 일치시킨 뒤 다시 생성하세요.",
            "하중케이스",
        ),
        "INVALID_ONE_WAY_FLOORLOAD_NODE_COUNT": (
            "1방향 FLOORLOAD 절점 수 오류",
            "1방향 하중은 3개 또는 4개의 경계 절점으로 입력되어야 하지만 조건을 만족하지 않습니다.",
            "1방향 하중 해치 경계를 삼각형 또는 사각형으로 정리하거나 TWO WAY/POLYGON 하중으로 전환하세요.",
            "1방향절점",
        ),
        "TOO_FEW_FLOORLOAD_NODES": (
            "폐합영역 절점 부족",
            "FLOORLOAD 경계가 닫힌 영역을 만들기에 절점 수가 부족합니다.",
            "CAD에서 하중 해치 또는 폐합 Polyline이 끊기지 않았는지 확인하고, 하나의 닫힌 영역으로 다시 작성하세요.",
            "폐합불가",
        ),
        "INVALID_FLOORLOAD_POLYGON": (
            "폐합영역 오류",
            "FLOORLOAD 경계 다각형이 유효한 닫힌 영역으로 인식되지 않습니다.",
            "CAD에서 하중 해치 또는 폐합 Polyline이 끊기지 않았는지 확인하고, 하나의 닫힌 영역으로 다시 작성하세요.",
            "영역오류",
        ),
        "SELF_INTERSECTING_FLOORLOAD_POLYGON": (
            "자기교차 영역",
            "FLOORLOAD 경계 다각형이 서로 교차합니다.",
            "CAD에서 하중 해치 또는 폐합 Polyline이 끊기지 않았는지 확인하고, 하나의 닫힌 영역으로 다시 작성하세요.",
            "영역교차",
        ),
        "AMBIGUOUS_ONEWAY_DIRECTION": (
            "1방향 하중 방향선 중복/불명확",
            "하나의 해치에 서로 다른 방향선이 겹쳐 인식되었습니다.",
            "해당 해치에 적용할 방향선 하나만 남기고 다시 DXF 검증을 실행하세요.",
            "방향불명",
        ),
    }
    type_label, cause, action, short_label = mapping.get(
        str(issue.issue_type or ""),
        (
            str(issue.issue_type or ""),
            str(issue.message or ""),
            str(issue.suggested_action or ""),
            str(issue.issue_type or "진단"),
        ),
    )
    return {
        "severity_label": severity_label,
        "type_label": type_label,
        "cause": cause,
        "action": action,
        "short_label": short_label,
    }


@dataclass(frozen=True)
class _DiagnosticRegion:
    story_name: str
    vertices: tuple[tuple[float, float], ...]
    source_id: str = ""


@dataclass(frozen=True)
class _LineElementSegment:
    element: Element
    start: Node
    end: Node
    length: float
    ux: float
    uy: float


@dataclass(frozen=True)
class _LineOverlap:
    other: _LineElementSegment
    start: float
    end: float
    midpoint: tuple[float, float]


def analyze_floorload_model(
    *,
    nodes: Sequence[Node],
    elements: Sequence[Element],
    stories: Sequence[Story],
    mgt_text: str = "",
    planned_load_regions: Sequence[object] | None = None,
    existing_floorloads: Sequence[object] | None = None,
    story_tolerance: float = 0.01,
    snap_tolerance: float = 0.5,
    duplicate_node_tolerance: float | None = None,
    include_global_debug_checks: bool = False,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None = None,
) -> FloorLoadDiagnosticResult:
    planned_regions = list(planned_load_regions or [])
    unit_info = parse_unit_from_text(mgt_text) if mgt_text else parse_unit_from_text("")
    floadtype_specs = parse_floadtype_specs_from_text(mgt_text) if mgt_text else []
    floadtypes_by_name = {_name_key(spec.name): spec for spec in floadtype_specs}
    stldcase_names = {_name_key(name) for name in parse_stldcase_names_from_text(mgt_text)} if mgt_text else set()
    parsed_existing_floorloads = list(iter_floorload_records_from_text(mgt_text)) if mgt_text else []
    parsed_elastic_links = list(parse_elastic_links_from_text(mgt_text)) if mgt_text else []
    parsed_materials = list(parse_materials_from_text(mgt_text)) if mgt_text else []
    parsed_sections = list(parse_sections_from_text(mgt_text)) if mgt_text else []
    existing_records = list(existing_floorloads or parsed_existing_floorloads)
    node_by_id = {node.node_id: node for node in nodes}
    elastic_links = [link for link in parsed_elastic_links if link.node_i in node_by_id and link.node_j in node_by_id]
    dummy_element_ids = _dummy_like_element_ids(elements, parsed_materials, parsed_sections)
    element_type_counts = dict(sorted(Counter(element.elem_type for element in elements).items()))
    duplicate_tol = duplicate_node_tolerance
    if duplicate_tol is None:
        duplicate_tol = _default_duplicate_node_tolerance(unit_info.length)
    existing_cantilever_regions = (
        []
        if planned_regions
        else _existing_floorload_regions_for_cantilever(existing_records, node_by_id, stories, story_tolerance)
    )

    issues: list[FloorLoadDiagnosticIssue] = []
    if mgt_text and not unit_info.length:
        issues.append(
            _issue(
                "",
                "WARNING",
                "UNIT_OR_DXF_SCALE_UNKNOWN",
                "MGT *UNIT length unit was not found. DXF scaling and snap tolerance should be checked.",
                0.0,
                0.0,
                [],
                [],
                "Confirm the MGT *UNIT section and DXF layout metadata scale.",
            )
        )

    issues.extend(_validate_floadtype_definitions(floadtype_specs, stldcase_names))
    issues.extend(_validate_existing_floorload_records(existing_records, node_by_id, stories, floadtypes_by_name, story_tolerance))
    issues.extend(
        _validate_planned_load_regions(
            planned_regions,
            nodes,
            stories,
            floadtypes_by_name,
            story_tolerance=story_tolerance,
            snap_tolerance=snap_tolerance,
            require_floadtype=bool(mgt_text),
            allowed_story_polygons_by_name=allowed_story_polygons_by_name,
        )
    )
    if planned_regions:
        issues.extend(
            _validate_internal_members_for_regions(
                planned_regions,
                nodes,
                elements,
                stories,
                elastic_links,
                dummy_element_ids,
                story_tolerance=story_tolerance,
                snap_tolerance=snap_tolerance,
                length_unit=unit_info.length,
            )
        )
    elif existing_cantilever_regions:
        issues.extend(
            _detect_cantilever_free_ends_for_regions(
                existing_cantilever_regions,
                nodes,
                elements,
                stories,
                elastic_links,
                dummy_element_ids,
                story_tolerance=story_tolerance,
                snap_tolerance=snap_tolerance,
                length_unit=unit_info.length,
            )
        )

    for story in stories:
        story_nodes = select_nodes_by_story(nodes, story.elevation, story_tolerance)
        story_node_ids = {node.node_id for node in story_nodes}
        story_elements = [element for element in elements if story_node_ids.intersection(element.node_ids)]
        issues.extend(
            _detect_duplicate_elements(
                story,
                story_elements,
                node_by_id,
                story_tolerance=story_tolerance,
                snap_tolerance=snap_tolerance,
            )
        )
        if include_global_debug_checks:
            issues.extend(_detect_near_duplicate_nodes(story, story_nodes, duplicate_tol))
            issues.extend(_detect_unsplit_members(story, story_nodes, story_elements, node_by_id, snap_tolerance))
            issues.extend(_detect_open_line_edges(story, story_elements, node_by_id))

    summary = _make_summary(
        issues=issues,
        unit_force=unit_info.force,
        unit_length=unit_info.length,
        story_count=len(stories),
        node_count=len(nodes),
        element_count=len(elements),
        element_type_counts=element_type_counts,
        floadtype_count=len(floadtype_specs),
        existing_floorload_count=len(existing_records),
        planned_region_count=len(planned_regions),
        target_region_count=len(planned_regions) + len(existing_cantilever_regions),
        elastic_link_count=len(parsed_elastic_links),
    )
    return FloorLoadDiagnosticResult(summary=summary, issues=issues)


def write_diagnostic_reports(
    issues: Sequence[FloorLoadDiagnosticIssue] | FloorLoadDiagnosticResult,
    output_dir: str | Path,
) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "floorload_diagnostics.json"
    csv_path = out / "floorload_diagnostics.csv"
    result = issues if isinstance(issues, FloorLoadDiagnosticResult) else None
    issue_list = result.issues if result else list(issues)
    records = [issue.to_record() for issue in issue_list]
    if result:
        json_payload = {"summary": asdict(result.summary), "issues": records}
    else:
        json_payload = records
    json_path.write_text(json.dumps(json_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["story_name", "severity", "issue_type", "message", "x", "y", "node_ids", "element_ids", "suggested_action"],
        )
        writer.writeheader()
        writer.writerows(records)
    return json_path, csv_path


def _make_summary(
    *,
    issues: Sequence[FloorLoadDiagnosticIssue],
    unit_force: str,
    unit_length: str,
    story_count: int,
    node_count: int,
    element_count: int,
    element_type_counts: dict[str, int],
    floadtype_count: int,
    existing_floorload_count: int,
    planned_region_count: int,
    target_region_count: int | None = None,
    elastic_link_count: int = 0,
) -> FloorLoadDiagnosticSummary:
    error_count = sum(1 for issue in issues if issue.severity == "ERROR")
    warning_count = sum(1 for issue in issues if issue.severity == "WARNING")
    info_count = sum(1 for issue in issues if issue.severity == "INFO")
    internal_member_supported_count = sum(1 for issue in issues if issue.issue_type == "INTERNAL_MEMBER_SUPPORTED_BY_ELASTIC_LINK")
    internal_member_warning_count = sum(1 for issue in issues if issue.issue_type == "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD")
    effective_target_region_count = planned_region_count if target_region_count is None else target_region_count
    if effective_target_region_count <= 0:
        status = NO_TARGET_REGION
    elif error_count:
        status = BLOCKED
    elif warning_count:
        status = READY_WITH_WARNINGS
    else:
        status = READY
    if effective_target_region_count <= 0:
        diagnostic_message = (
            "No planned DXF load regions were supplied; ELASTIC LINK entries were counted, "
            "but internal member influence was not judged."
        )
    elif planned_region_count <= 0:
        diagnostic_message = (
            "No planned DXF load regions were supplied; existing FLOORLOAD regions were used "
            "only for cantilever free-end availability checks."
        )
    else:
        diagnostic_message = (
            "Model-only FLOORLOAD availability check complete. ONE WAY/TWO WAY, hatch pattern, "
            "direction marker, and MGT angle validation run later during DXF validation / MGT generation."
        )
    return FloorLoadDiagnosticSummary(
        status=status,
        unit_force=unit_force,
        unit_length=unit_length,
        story_count=story_count,
        node_count=node_count,
        element_count=element_count,
        element_type_counts=element_type_counts,
        floadtype_count=floadtype_count,
        existing_floorload_count=existing_floorload_count,
        planned_region_count=planned_region_count,
        error_count=error_count,
        warning_count=warning_count,
        info_count=info_count,
        elastic_link_count=elastic_link_count,
        internal_member_supported_count=internal_member_supported_count,
        internal_member_warning_count=internal_member_warning_count,
        diagnostic_message=diagnostic_message,
    )


def _validate_floadtype_definitions(specs, stldcase_names: set[str]) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    if not specs:
        return issues
    for spec in specs:
        for case_name in spec.load_case_names:
            if not stldcase_names or _name_key(case_name) not in stldcase_names:
                issues.append(
                    _issue(
                        "",
                        "ERROR",
                        "FLOADTYPE_LOADCASE_NOT_DEFINED",
                        f"FLOADTYPE '{spec.name}' references load case '{case_name}', but it is not defined in *STLDCASE.",
                        0.0,
                        0.0,
                        [],
                        [],
                        "Add the missing STLDCASE or fix the FLOADTYPE load case name.",
                    )
                )
    return issues


def _validate_existing_floorload_records(
    records: Sequence[object],
    node_by_id: dict[int, Node],
    stories: Sequence[Story],
    floadtypes_by_name: dict[str, object],
    story_tolerance: float,
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    for record in records:
        ltname = str(getattr(record, "ltname", "") or getattr(record, "load_type_name", "") or "")
        node_ids = tuple(getattr(record, "node_ids", ()) or ())
        nodes = [node_by_id[node_id] for node_id in node_ids if node_id in node_by_id]
        missing = [node_id for node_id in node_ids if node_id not in node_by_id]
        x, y = _centroid_xy_from_nodes(nodes)
        if floadtypes_by_name and _name_key(ltname) not in floadtypes_by_name:
            issues.append(
                _issue(
                    "",
                    "ERROR",
                    "FLOADTYPE_NOT_DEFINED",
                    f"Existing FLOORLOAD '{ltname}' does not have a matching *FLOADTYPE definition.",
                    x,
                    y,
                    list(node_ids),
                    [],
                    "Define the missing FLOADTYPE or correct the FLOORLOAD load type name.",
                )
            )
        if missing:
            issues.append(
                _issue(
                    "",
                    "ERROR",
                    "FLOORLOAD_NODE_NOT_FOUND",
                    f"Existing FLOORLOAD '{ltname}' references missing node IDs.",
                    x,
                    y,
                    list(missing),
                    [],
                    "Check the FLOORLOAD node list against the *NODE section.",
                )
            )
            continue
        if len(nodes) >= 2 and max(node.z for node in nodes) - min(node.z for node in nodes) > abs(float(story_tolerance)):
            issues.append(
                _issue(
                    _story_name_for_nodes(nodes, stories, story_tolerance),
                    "ERROR",
                    "FLOORLOAD_NODE_STORY_MISMATCH",
                    f"Existing FLOORLOAD '{ltname}' uses boundary nodes from different story elevations.",
                    x,
                    y,
                    list(node_ids),
                    [],
                    "Use boundary nodes on a single story elevation.",
                )
            )
        issues.extend(_validate_polygon_xy([(node.x, node.y) for node in nodes], _story_name_for_nodes(nodes, stories, story_tolerance), list(node_ids), [], x, y))
    return issues


def _validate_planned_load_regions(
    planned_regions: Sequence[object],
    nodes: Sequence[Node],
    stories: Sequence[Story],
    floadtypes_by_name: dict[str, object],
    *,
    story_tolerance: float,
    snap_tolerance: float,
    require_floadtype: bool,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None = None,
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    for load_region in planned_regions:
        region = getattr(load_region, "region", load_region)
        load = getattr(load_region, "load", None)
        story_name = str(getattr(region, "story_name", "") or "")
        vertices = [(float(x), float(y)) for x, y in (getattr(region, "vertices", ()) or ())]
        x, y = _region_xy(region, vertices)
        load_name = _region_load_name(load_region)
        allowed_region_issue_type = _allowed_story_region_issue_type(region, story_name, allowed_story_polygons_by_name)
        if allowed_region_issue_type:
            message = (
                STORY_BELOW_ALLOWED_REGION_MISSING_MESSAGE
                if allowed_region_issue_type == BELOW_ALLOWED_REGION_MISSING
                else STORY_BELOW_OUTSIDE_MESSAGE
            )
            suggested_action = (
                "구조요소 표시와 Story metadata를 확인한 뒤 HATCH VIEW/DXF를 다시 생성하세요."
                if allowed_region_issue_type == BELOW_ALLOWED_REGION_MISSING
                else "MIDAS Story BELOW 기준으로 표시되는 보/벽체 경계 안쪽에만 하중을 입력하세요."
            )
            issues.append(
                _issue(
                    story_name,
                    "ERROR",
                    allowed_region_issue_type,
                    message,
                    x,
                    y,
                    [],
                    [],
                    suggested_action,
                )
            )
        if require_floadtype and load_name and _name_key(load_name) not in floadtypes_by_name:
            issues.append(
                _issue(
                    story_name,
                    "ERROR",
                    "FLOADTYPE_NOT_DEFINED",
                    f"Planned load region uses load type '{load_name}', but it is not defined in *FLOADTYPE.",
                    x,
                    y,
                    [],
                    [],
                    "Create or select a valid MIDAS FLOADTYPE before generating FLOORLOAD records.",
                )
        )
        issues.extend(_validate_polygon_xy(vertices, story_name, [], [], x, y, load_region=load_region))
        issues.extend(_validate_region_snap_to_story_nodes(region, vertices, nodes, stories, story_tolerance, snap_tolerance))
    return issues


def _region_outside_allowed_story_polygons(
    region: object,
    story_name: str,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None,
    *,
    min_area_ratio: float = 0.98,
) -> bool:
    return _allowed_story_region_issue_type(
        region,
        story_name,
        allowed_story_polygons_by_name,
        min_area_ratio=min_area_ratio,
    ) is not None


def _allowed_story_region_issue_type(
    region: object,
    story_name: str,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None,
    *,
    min_area_ratio: float = 0.98,
) -> str | None:
    if not story_name or allowed_story_polygons_by_name is None:
        return None
    story_key = str(story_name)
    if story_key not in allowed_story_polygons_by_name:
        return BELOW_ALLOWED_REGION_MISSING
    allowed_polygons = tuple(
        polygon
        for polygon in allowed_story_polygons_by_name.get(story_key, ()) or ()
        if _valid_polygon_or_none(polygon) is not None
    )
    if not allowed_polygons:
        return BELOW_ALLOWED_REGION_MISSING
    vertices = tuple((float(x), float(y)) for x, y in (getattr(region, "vertices", ()) or ()))
    region_polygon = _valid_polygon_or_none(Polygon(vertices) if len(vertices) >= 3 else None)
    if region_polygon is None:
        return PLANNED_REGION_OUTSIDE_STORY_BELOW_VIEW
    centroid = region_polygon.centroid
    required_ratio = max(0.0, min(float(min_area_ratio), 1.0))
    for allowed in allowed_polygons:
        allowed_polygon = _valid_polygon_or_none(allowed)
        if allowed_polygon is None or not allowed_polygon.covers(centroid):
            continue
        try:
            ratio = float(region_polygon.intersection(allowed_polygon).area) / max(float(region_polygon.area), 1.0e-12)
        except Exception:
            ratio = 0.0
        if ratio >= required_ratio:
            return None
    return PLANNED_REGION_OUTSIDE_STORY_BELOW_VIEW


def _valid_polygon_or_none(polygon) -> Polygon | None:
    if polygon is None:
        return None
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.area <= 1.0e-12 or polygon.geom_type != "Polygon":
        return None
    return polygon


def _validate_polygon_xy(
    vertices: Sequence[tuple[float, float]],
    story_name: str,
    node_ids: list[int],
    element_ids: list[int],
    x: float,
    y: float,
    *,
    load_region: object | None = None,
    validate_one_way_rules: bool = False,
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    distribution = ""
    if validate_one_way_rules and load_region is not None:
        from .load_input_policy import infer_distribution

        region = getattr(load_region, "region", load_region)
        load = getattr(load_region, "load", None)
        distribution, _source = infer_distribution(region, load)
    min_nodes = 3
    if len(vertices) < min_nodes:
        issues.append(
            _issue(
                story_name,
                "ERROR",
                "TOO_FEW_FLOORLOAD_NODES",
                "FLOORLOAD boundary must have at least 3 nodes.",
                x,
                y,
                node_ids,
                element_ids,
                "Check CAD hatch boundary vertices and model node snapping.",
            )
        )
        return issues
    if distribution == "ONE_WAY" and len(vertices) not in {3, 4}:
        issues.append(
            _issue(
                story_name,
                "ERROR",
                "INVALID_ONE_WAY_FLOORLOAD_NODE_COUNT",
                "ONE WAY FLOORLOAD should be a triangle or quadrilateral.",
                x,
                y,
                node_ids,
                element_ids,
                "Split the region into 3-node or 4-node one-way areas, or use a two-way load.",
            )
        )
    if _has_consecutive_duplicate_points(vertices):
        issues.append(
            _issue(
                story_name,
                "ERROR",
                "INVALID_FLOORLOAD_POLYGON",
                "FLOORLOAD boundary has consecutive duplicate vertices.",
                x,
                y,
                node_ids,
                element_ids,
                "Remove duplicate boundary points before generating MGT.",
            )
        )
    polygon = Polygon(vertices)
    if polygon.is_empty or polygon.area <= 1.0e-12:
        issues.append(
            _issue(
                story_name,
                "ERROR",
                "INVALID_FLOORLOAD_POLYGON",
                "FLOORLOAD polygon area is zero or invalid.",
                x,
                y,
                node_ids,
                element_ids,
                "Check the boundary point order and area.",
            )
        )
    elif not polygon.is_valid:
        issues.append(
            _issue(
                story_name,
                "ERROR",
                "SELF_INTERSECTING_FLOORLOAD_POLYGON",
                "FLOORLOAD polygon is self-intersecting.",
                x,
                y,
                node_ids,
                element_ids,
                "Redraw or split the CAD hatch boundary.",
            )
        )
    return issues


def _validate_region_snap_to_story_nodes(
    region,
    vertices: Sequence[tuple[float, float]],
    nodes: Sequence[Node],
    stories: Sequence[Story],
    story_tolerance: float,
    snap_tolerance: float,
) -> list[FloorLoadDiagnosticIssue]:
    story_name = str(getattr(region, "story_name", "") or "")
    story = next((item for item in stories if item.name == story_name), None)
    story_nodes = select_nodes_by_story(nodes, story.elevation, story_tolerance) if story else list(nodes)
    issues: list[FloorLoadDiagnosticIssue] = []
    if not vertices or not story_nodes:
        return issues
    snapped_nodes: list[Node] = []
    for x, y in vertices:
        nearest = min(story_nodes, key=lambda node: (node.x - x) ** 2 + (node.y - y) ** 2)
        snapped_nodes.append(nearest)
        distance = math.hypot(nearest.x - x, nearest.y - y)
        if distance > abs(float(snap_tolerance)):
            issues.append(
                _issue(
                    story_name,
                    "ERROR",
                    "SNAP_ERROR_EXCEEDED",
                    f"CAD vertex is {distance:g} away from nearest model node, exceeding snap tolerance {snap_tolerance:g}.",
                    float(x),
                    float(y),
                    [nearest.node_id],
                    [],
                    "Move the hatch vertex onto a model node or increase snap tolerance intentionally.",
                )
            )
    if story is None and snapped_nodes and max(node.z for node in snapped_nodes) - min(node.z for node in snapped_nodes) > abs(float(story_tolerance)):
        cx, cy = _centroid_xy_from_nodes(snapped_nodes)
        issues.append(
            _issue(
                story_name,
                "ERROR",
                "FLOORLOAD_NODE_STORY_MISMATCH",
                "Planned load region snaps to nodes from different story elevations.",
                cx,
                cy,
                [node.node_id for node in snapped_nodes],
                [],
                "Use one story's nodes for each FLOORLOAD polygon.",
            )
        )
    return issues


def has_elastic_path_to_boundary(
    start_node_id: int,
    boundary_node_ids: Iterable[int],
    elastic_graph: dict[int, set[int]],
    *,
    max_depth: int = 3,
) -> bool:
    targets = set(boundary_node_ids)
    if start_node_id in targets:
        return True
    if max_depth <= 0:
        return False
    seen = {start_node_id}
    queue: deque[tuple[int, int]] = deque([(start_node_id, 0)])
    while queue:
        current, depth = queue.popleft()
        for next_node in elastic_graph.get(current, set()):
            next_depth = depth + 1
            if next_depth > max_depth or next_node in seen:
                continue
            if next_node in targets:
                return True
            seen.add(next_node)
            queue.append((next_node, next_depth))
    return False


def _validate_internal_members_for_regions(
    planned_regions: Sequence[object],
    nodes: Sequence[Node],
    elements: Sequence[Element],
    stories: Sequence[Story],
    elastic_links: Sequence[ParsedElasticLink],
    dummy_element_ids: set[int],
    *,
    story_tolerance: float,
    snap_tolerance: float,
    length_unit: str,
) -> list[FloorLoadDiagnosticIssue]:
    node_by_id = {node.node_id: node for node in nodes}
    elastic_graph = _build_elastic_graph(elastic_links)
    boundary_tolerance = _boundary_node_tolerance(length_unit, snap_tolerance)
    issues: list[FloorLoadDiagnosticIssue] = []
    for load_region in planned_regions:
        region = getattr(load_region, "region", load_region)
        story_name = str(getattr(region, "story_name", "") or "")
        vertices = [(float(x), float(y)) for x, y in (getattr(region, "vertices", ()) or ())]
        if len(vertices) < 3:
            continue
        polygon = Polygon(vertices)
        if polygon.is_empty or polygon.area <= 1.0e-12 or not polygon.is_valid:
            continue
        story_nodes = _story_nodes_for_region(region, nodes, stories, story_tolerance)
        if not story_nodes:
            point = polygon.representative_point()
            issues.append(
                _issue(
                    story_name,
                    "WARNING",
                    "STORY_NOT_DETECTED",
                    "Planned FLOORLOAD region story was not detected; internal member check was skipped to avoid cross-story node matching.",
                    float(point.x),
                    float(point.y),
                    [],
                    [],
                    "Check DXF layout metadata and STORY_LABEL detection before dummy generation.",
                )
            )
            continue
        story_node_ids = {node.node_id for node in story_nodes}
        boundary_node_ids = _region_boundary_node_ids(polygon, vertices, story_nodes, snap_tolerance, boundary_tolerance)
        if not boundary_node_ids:
            continue
        support_node_ids = _elastic_support_node_ids_for_region(
            polygon,
            story_nodes,
            boundary_node_ids,
            snap_tolerance=snap_tolerance,
            boundary_tolerance=boundary_tolerance,
        )
        hard_boundary_node_ids = _region_vertex_node_ids(vertices, story_nodes, snap_tolerance)
        cantilever_issues, cantilever_free_node_ids = _detect_cantilever_free_ends_for_region(
            region,
            polygon,
            story_nodes,
            node_by_id,
            elements,
            elastic_graph,
            support_node_ids,
            hard_boundary_node_ids,
            dummy_element_ids,
            boundary_tolerance=boundary_tolerance,
        )
        issues.extend(cantilever_issues)
        internal_nodes_by_element: dict[int, set[int]] = {}
        for element in elements:
            if element.elem_id in dummy_element_ids or element.elem_type not in LINE_TYPES or len(element.node_ids) < 2:
                continue
            internal_node_ids: set[int] = set()
            for node_id in element.node_ids:
                node = node_by_id.get(node_id)
                if (
                    node is None
                    or node.node_id not in story_node_ids
                    or node.node_id in boundary_node_ids
                    or node.node_id in cantilever_free_node_ids
                ):
                    continue
                point = Point(node.x, node.y)
                if polygon.contains(point) and point.distance(polygon.boundary) > boundary_tolerance:
                    internal_node_ids.add(node.node_id)
            if internal_node_ids:
                internal_nodes_by_element[element.elem_id] = internal_node_ids
        if not internal_nodes_by_element:
            continue

        all_internal_node_ids = set().union(*internal_nodes_by_element.values())
        supported_node_ids = {
            node_id
            for node_id in all_internal_node_ids
            if has_elastic_path_to_boundary(node_id, support_node_ids, elastic_graph, max_depth=3)
        }
        unsupported_node_ids = all_internal_node_ids - supported_node_ids
        if supported_node_ids:
            element_ids = sorted(
                elem_id for elem_id, node_ids in internal_nodes_by_element.items() if node_ids.intersection(supported_node_ids)
            )
            x, y = _centroid_xy_from_node_ids(supported_node_ids, node_by_id)
            issues.append(
                _issue(
                    story_name,
                    "INFO",
                    "INTERNAL_MEMBER_SUPPORTED_BY_ELASTIC_LINK",
                    "Internal member node is connected to a FLOORLOAD boundary-near node through ELASTIC LINK.",
                    x,
                    y,
                    sorted(supported_node_ids),
                    element_ids,
                    "No blocking action is required for this model-only availability check.",
                )
            )
        if unsupported_node_ids:
            element_ids = sorted(
                elem_id for elem_id, node_ids in internal_nodes_by_element.items() if node_ids.intersection(unsupported_node_ids)
            )
            x, y = _centroid_xy_from_node_ids(unsupported_node_ids, node_by_id)
            issues.append(
                _issue(
                    story_name,
                    "WARNING",
                    "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD",
                    "Internal member node is inside a planned FLOORLOAD region without an ELASTIC LINK path to the boundary.",
                    x,
                    y,
                    sorted(unsupported_node_ids),
                    element_ids,
                    "Review whether an ELASTIC LINK or dummy boundary modeling is needed before generating FLOORLOAD records.",
                )
            )
    return issues


def _detect_cantilever_free_ends_for_regions(
    planned_regions: Sequence[object],
    nodes: Sequence[Node],
    elements: Sequence[Element],
    stories: Sequence[Story],
    elastic_links: Sequence[ParsedElasticLink],
    dummy_element_ids: set[int],
    *,
    story_tolerance: float,
    snap_tolerance: float,
    length_unit: str,
) -> list[FloorLoadDiagnosticIssue]:
    node_by_id = {node.node_id: node for node in nodes}
    elastic_graph = _build_elastic_graph(elastic_links)
    boundary_tolerance = _boundary_node_tolerance(length_unit, snap_tolerance)
    issues: list[FloorLoadDiagnosticIssue] = []
    for load_region in planned_regions:
        region = getattr(load_region, "region", load_region)
        vertices = [(float(x), float(y)) for x, y in (getattr(region, "vertices", ()) or ())]
        if len(vertices) < 3:
            continue
        polygon = Polygon(vertices)
        if polygon.is_empty or polygon.area <= 1.0e-12 or not polygon.is_valid:
            continue
        story_nodes = _story_nodes_for_region(region, nodes, stories, story_tolerance)
        if not story_nodes:
            continue
        boundary_node_ids = _region_boundary_node_ids(polygon, vertices, story_nodes, snap_tolerance, boundary_tolerance)
        if not boundary_node_ids:
            continue
        support_node_ids = _elastic_support_node_ids_for_region(
            polygon,
            story_nodes,
            boundary_node_ids,
            snap_tolerance=snap_tolerance,
            boundary_tolerance=boundary_tolerance,
        )
        hard_boundary_node_ids = _region_vertex_node_ids(vertices, story_nodes, snap_tolerance)
        region_issues, _free_node_ids = _detect_cantilever_free_ends_for_region(
            region,
            polygon,
            story_nodes,
            node_by_id,
            elements,
            elastic_graph,
            support_node_ids,
            hard_boundary_node_ids,
            dummy_element_ids,
            boundary_tolerance=boundary_tolerance,
        )
        issues.extend(region_issues)
    return issues


def _detect_cantilever_free_ends_for_region(
    region,
    polygon: Polygon,
    story_nodes: Sequence[Node],
    node_by_id: dict[int, Node],
    elements: Sequence[Element],
    elastic_graph: dict[int, set[int]],
    support_node_ids: Iterable[int],
    hard_boundary_node_ids: set[int],
    dummy_element_ids: set[int],
    *,
    boundary_tolerance: float,
) -> tuple[list[FloorLoadDiagnosticIssue], set[int]]:
    story_name = str(getattr(region, "story_name", "") or "")
    story_node_ids = {node.node_id for node in story_nodes}
    graph = _build_structural_graph_for_story(elements, story_node_ids, dummy_element_ids)
    source_element_ids_by_node: dict[int, set[int]] = {}
    source_element_by_id = {
        element.elem_id: element
        for element in elements
        if element.elem_id not in dummy_element_ids and element.elem_type in CANTILEVER_SOURCE_TYPES
    }
    for element in source_element_by_id.values():
        for node_id in element.node_ids:
            if node_id in story_node_ids and node_id not in hard_boundary_node_ids:
                source_element_ids_by_node.setdefault(node_id, set()).add(element.elem_id)

    issues: list[FloorLoadDiagnosticIssue] = []
    free_node_ids: set[int] = set()
    support_ids = set(support_node_ids)
    for node_id in sorted(source_element_ids_by_node):
        node = node_by_id.get(node_id)
        if node is None:
            continue
        source_element_ids = tuple(sorted(source_element_ids_by_node[node_id]))
        source_connects_support = _source_connects_support_node(
            node_id,
            source_element_ids,
            source_element_by_id,
            support_ids - {node_id},
        )
        reason = _is_cantilever_free_tip(
            node,
            polygon,
            graph,
            source_element_ids,
            source_connects_support=source_connects_support,
            boundary_tolerance=boundary_tolerance,
        )
        if not reason:
            continue
        free_node_ids.add(node_id)
        element_text = ", ".join(str(element_id) for element_id in source_element_ids)
        if has_elastic_path_to_boundary(node_id, support_ids - {node_id}, elastic_graph, max_depth=3):
            issues.append(
                _issue(
                    story_name,
                    "INFO",
                    "CANTILEVER_FREE_END_SUPPORTED_BY_ELASTIC_LINK",
                    f"Story {story_name}: cantilever free node {node_id} from element {element_text} is {reason} and is supported by an ELASTIC LINK path to a boundary-near node.",
                    node.x,
                    node.y,
                    [node_id],
                    list(source_element_ids),
                    "No blocking action is required for this cantilever tip.",
                )
            )
        else:
            issues.append(
                _issue(
                    story_name,
                    "WARNING",
                    "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD",
                    f"Story {story_name}: cantilever free node {node_id} from element {element_text} is {reason} without an ELASTIC LINK path to a boundary-near node.",
                    node.x,
                    node.y,
                    [node_id],
                    list(source_element_ids),
                    "Review this free tip before generating FLOORLOAD records; add an ELASTIC LINK or LOAD DM dummy only if needed.",
                )
            )
    return issues, free_node_ids


def _is_cantilever_free_tip(
    node: Node,
    polygon: Polygon,
    graph: dict[int, set[int]],
    source_element_ids: Sequence[int],
    *,
    source_connects_support: bool,
    boundary_tolerance: float,
) -> str | None:
    if not source_element_ids:
        return None
    structural_degree = len(graph.get(node.node_id, set()))
    if structural_degree > 1:
        return None
    position = _node_region_position(node, polygon, boundary_tolerance)
    if position == "OUTSIDE":
        return None
    if position != "BOUNDARY_NEAR" and not source_connects_support:
        return None
    if position == "BOUNDARY_NEAR":
        return f"within FLOORLOAD boundary tolerance as a degree-{structural_degree} leaf endpoint"
    return f"inside the FLOORLOAD polygon as a degree-{structural_degree} leaf endpoint"


def _source_connects_support_node(
    node_id: int,
    source_element_ids: Iterable[int],
    element_by_id: dict[int, Element],
    support_node_ids: set[int],
) -> bool:
    for element_id in source_element_ids:
        element = element_by_id.get(element_id)
        if element is None:
            continue
        for other_id in element.node_ids:
            if other_id != node_id and other_id in support_node_ids:
                return True
    return False


def _node_region_position(node: Node, polygon: Polygon, boundary_tolerance: float) -> str:
    point = Point(node.x, node.y)
    if polygon.contains(point):
        return "INSIDE"
    tolerance = max(abs(float(boundary_tolerance)), 1.0e-9)
    if point.distance(polygon.boundary) <= tolerance or polygon.buffer(tolerance).covers(point):
        return "BOUNDARY_NEAR"
    return "OUTSIDE"


def _build_structural_graph_for_story(
    elements: Sequence[Element],
    story_node_ids: set[int],
    dummy_element_ids: set[int],
) -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {}
    for element in elements:
        if element.elem_id in dummy_element_ids or element.elem_type not in LINE_TYPES:
            continue
        for a, b in _element_edges_for_graph(element):
            if a not in story_node_ids and b not in story_node_ids:
                continue
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)
    return graph


def _element_edges_for_graph(element: Element) -> list[tuple[int, int]]:
    ids = tuple(node_id for node_id in element.node_ids if node_id > 0)
    if len(ids) < 2:
        return []
    if element.elem_type in {"BEAM", "COLUMN", "TRUSS", "TENSTR", "COMPTR"}:
        return [(ids[0], ids[1])]
    if len(ids) >= 3:
        return [(ids[index], ids[(index + 1) % len(ids)]) for index in range(len(ids))]
    return [(ids[0], ids[1])]


def _elastic_support_node_ids_for_region(
    polygon: Polygon,
    story_nodes: Sequence[Node],
    boundary_node_ids: Iterable[int],
    *,
    snap_tolerance: float,
    boundary_tolerance: float,
) -> set[int]:
    support = {int(node_id) for node_id in boundary_node_ids}
    support_tolerance = max(abs(float(boundary_tolerance)), min(abs(float(snap_tolerance)), 0.5), 1.0e-9)
    for node in story_nodes:
        if Point(node.x, node.y).distance(polygon.boundary) <= support_tolerance:
            support.add(node.node_id)
    return support


def _build_elastic_graph(links: Sequence[ParsedElasticLink]) -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {}
    for link in links:
        graph.setdefault(link.node_i, set()).add(link.node_j)
        graph.setdefault(link.node_j, set()).add(link.node_i)
    return graph


def _story_nodes_for_region(region, nodes: Sequence[Node], stories: Sequence[Story], story_tolerance: float) -> list[Node]:
    story_name = str(getattr(region, "story_name", "") or "")
    story = next((item for item in stories if item.name == story_name), None)
    if story is None:
        return []
    return select_nodes_by_story(nodes, story.elevation, story_tolerance)


def _region_boundary_node_ids(
    polygon: Polygon,
    vertices: Sequence[tuple[float, float]],
    story_nodes: Sequence[Node],
    snap_tolerance: float,
    boundary_tolerance: float,
) -> set[int]:
    boundary_node_ids: set[int] = set()
    if not story_nodes:
        return boundary_node_ids
    snap_tol = abs(float(snap_tolerance))
    for x, y in vertices:
        nearest = min(story_nodes, key=lambda node: (node.x - x) ** 2 + (node.y - y) ** 2)
        if math.hypot(nearest.x - x, nearest.y - y) <= snap_tol:
            boundary_node_ids.add(nearest.node_id)
    for node in story_nodes:
        if Point(node.x, node.y).distance(polygon.boundary) <= boundary_tolerance:
            boundary_node_ids.add(node.node_id)
    return boundary_node_ids


def _region_vertex_node_ids(
    vertices: Sequence[tuple[float, float]],
    story_nodes: Sequence[Node],
    snap_tolerance: float,
) -> set[int]:
    vertex_node_ids: set[int] = set()
    if not vertices or not story_nodes:
        return vertex_node_ids
    snap_tol = abs(float(snap_tolerance))
    for x, y in vertices:
        nearest = min(story_nodes, key=lambda node: (node.x - x) ** 2 + (node.y - y) ** 2)
        if math.hypot(nearest.x - x, nearest.y - y) <= snap_tol:
            vertex_node_ids.add(nearest.node_id)
    return vertex_node_ids


def _boundary_node_tolerance(length_unit: str, snap_tolerance: float) -> float:
    unit = str(length_unit or "").upper()
    snap_tol = abs(float(snap_tolerance))
    if unit == "MM":
        return max(min(snap_tol, 1.0), 1.0e-3)
    if unit == "CM":
        return max(min(snap_tol, 0.1), 1.0e-4)
    return max(min(snap_tol, 1.0e-3), 1.0e-6)


def _centroid_xy_from_node_ids(node_ids: Iterable[int], node_by_id: dict[int, Node]) -> tuple[float, float]:
    return _centroid_xy_from_nodes([node_by_id[node_id] for node_id in node_ids if node_id in node_by_id])


def _existing_floorload_regions_for_cantilever(
    records: Sequence[object],
    node_by_id: dict[int, Node],
    stories: Sequence[Story],
    story_tolerance: float,
) -> list[_DiagnosticRegion]:
    regions: list[_DiagnosticRegion] = []
    tol = abs(float(story_tolerance))
    for index, record in enumerate(records, start=1):
        node_ids = tuple(int(value) for value in (getattr(record, "node_ids", ()) or ()) if int(value) > 0)
        if len(node_ids) < 3:
            continue
        floorload_nodes = [node_by_id[node_id] for node_id in node_ids if node_id in node_by_id]
        if len(floorload_nodes) != len(node_ids):
            continue
        if max(node.z for node in floorload_nodes) - min(node.z for node in floorload_nodes) > tol:
            continue
        story_name = _story_name_for_nodes(floorload_nodes, stories, story_tolerance)
        if not story_name:
            continue
        vertices = tuple((node.x, node.y) for node in floorload_nodes)
        regions.append(
            _DiagnosticRegion(
                story_name=story_name,
                vertices=vertices,
                source_id=f"existing-floorload-{getattr(record, 'line_number', index)}",
            )
        )
    return regions


def _dummy_like_element_ids(elements: Sequence[Element], materials: Sequence[object], sections: Sequence[object]) -> set[int]:
    dm_material_ids = {
        int(getattr(item, "material_id"))
        for item in materials
        if _is_dummy_element_resource(getattr(item, "name", ""), getattr(item, "material_id", None))
    }
    dm_section_ids = {
        int(getattr(item, "section_id"))
        for item in sections
        if _is_dummy_element_resource(getattr(item, "name", ""), getattr(item, "section_id", None))
    }
    dummy_element_ids: set[int] = set()
    for element in elements:
        raw_key = _resource_name_key(element.raw)
        if (
            (element.mat is not None and element.mat in dm_material_ids)
            or (element.prop is not None and element.prop in dm_section_ids)
            or "LOADDM" in raw_key
            or "DUMMY" in raw_key
        ):
            dummy_element_ids.add(element.elem_id)
    return dummy_element_ids


def _is_dummy_element_resource(name: object, resource_id: int | None) -> bool:
    key = _resource_name_key(name)
    if "LOADDM" in key or "DUMMY" in key:
        return True
    return key == "DM" and resource_id is not None and int(resource_id) >= DM_ID_MIN


def _resource_name_key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _detect_near_duplicate_nodes(story: Story, nodes: Sequence[Node], tolerance: float) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    for index, first in enumerate(nodes):
        for second in nodes[index + 1 :]:
            distance = math.hypot(first.x - second.x, first.y - second.y)
            if 0.0 < distance <= tolerance:
                issues.append(
                    FloorLoadDiagnosticIssue(
                        story.name,
                        "INFO",
                        "NEAR_DUPLICATE_NODE",
                        "Two model nodes are extremely close. This debug check uses duplicate_node_tolerance, not snap_tolerance.",
                        (first.x + second.x) / 2.0,
                        (first.y + second.y) / 2.0,
                        [first.node_id, second.node_id],
                        [],
                        "Review only if these nodes are unintended duplicates.",
                    )
                )
    return issues


def _detect_duplicate_elements(
    story: Story,
    elements: Sequence[Element],
    node_by_id: dict[int, Node],
    *,
    story_tolerance: float = 0.01,
    snap_tolerance: float = 0.5,
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    seen: dict[tuple, Element] = {}
    for element in elements:
        key = (element.elem_type, tuple(sorted(element.node_ids)))
        if key in seen:
            first = seen[key]
            x, y = _element_centroid_xy(element, node_by_id)
            issues.append(
                FloorLoadDiagnosticIssue(
                    story.name,
                    "WARNING",
                    "DUPLICATE_ELEMENT",
                    "Two elements have the same type and node set.",
                    x,
                    y,
                    list(element.node_ids),
                    [first.elem_id, element.elem_id],
                    "Review duplicate beam/wall/slab elements if FLOORLOAD generation behaves unexpectedly.",
                )
            )
        else:
            seen[key] = element
    coordinate_tolerance = _coordinate_duplicate_tolerance(snap_tolerance)
    line_segments = _line_segments_for_duplicate_check(
        story,
        elements,
        node_by_id,
        story_tolerance=story_tolerance,
        coordinate_tolerance=coordinate_tolerance,
    )
    issues.extend(_detect_exact_coordinate_duplicate_line_elements(story, line_segments, coordinate_tolerance))
    pair_overlaps, pair_issues = _detect_overlapping_line_element_pairs(story, line_segments, coordinate_tolerance)
    issues.extend(pair_issues)
    issues.extend(_detect_split_overlap_duplicate_elements(story, line_segments, pair_overlaps))
    return issues


def _line_segments_for_duplicate_check(
    story: Story,
    elements: Sequence[Element],
    node_by_id: dict[int, Node],
    *,
    story_tolerance: float,
    coordinate_tolerance: float,
) -> list[_LineElementSegment]:
    segments: list[_LineElementSegment] = []
    z_tolerance = abs(float(story_tolerance))
    for element in elements:
        if element.elem_type not in LINE_OVERLAP_TYPES or len(element.node_ids) < 2:
            continue
        start = node_by_id.get(element.node_ids[0])
        end = node_by_id.get(element.node_ids[1])
        if start is None or end is None:
            continue
        if abs(start.z - story.elevation) > z_tolerance or abs(end.z - story.elevation) > z_tolerance:
            continue
        dx = end.x - start.x
        dy = end.y - start.y
        length = math.hypot(dx, dy)
        if length <= coordinate_tolerance:
            continue
        segments.append(_LineElementSegment(element=element, start=start, end=end, length=length, ux=dx / length, uy=dy / length))
    return segments


def _detect_exact_coordinate_duplicate_line_elements(
    story: Story,
    segments: Sequence[_LineElementSegment],
    tolerance: float,
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    for index, first in enumerate(segments):
        for second in segments[index + 1 :]:
            if first.element.elem_type != second.element.elem_type:
                continue
            if tuple(sorted(first.element.node_ids)) == tuple(sorted(second.element.node_ids)):
                continue
            if not _line_endpoint_coordinates_match(first, second, tolerance):
                continue
            x, y = _combined_segment_midpoint((first, second))
            issues.append(
                _issue(
                    story.name,
                    "WARNING",
                    "EXACT_COORD_DUPLICATE_ELEMENT",
                    "Two line elements have the same endpoint coordinates on the same story.",
                    x,
                    y,
                    _unique_node_ids(first, second),
                    [first.element.elem_id, second.element.elem_id],
                    "Remove or merge duplicate line members before FLOORLOAD generation.",
                )
            )
    return issues


def _detect_overlapping_line_element_pairs(
    story: Story,
    segments: Sequence[_LineElementSegment],
    tolerance: float,
) -> tuple[dict[int, list[_LineOverlap]], list[FloorLoadDiagnosticIssue]]:
    overlaps_by_target: dict[int, list[_LineOverlap]] = {}
    issues: list[FloorLoadDiagnosticIssue] = []
    for index, first in enumerate(segments):
        for second in segments[index + 1 :]:
            if first.element.elem_type != second.element.elem_type:
                continue
            if tuple(sorted(first.element.node_ids)) == tuple(sorted(second.element.node_ids)):
                continue
            if not _segment_bboxes_may_overlap(first, second, tolerance):
                continue
            first_overlap = _projected_overlap_on_target(first, second, tolerance)
            if first_overlap is None:
                continue
            second_overlap = _projected_overlap_on_target(second, first, tolerance)
            if second_overlap is not None:
                overlaps_by_target.setdefault(first.element.elem_id, []).append(first_overlap)
                overlaps_by_target.setdefault(second.element.elem_id, []).append(second_overlap)
            x, y = first_overlap.midpoint
            issues.append(
                _issue(
                    story.name,
                    "WARNING",
                    "OVERLAPPING_LINE_ELEMENT",
                    "Two line elements overlap on the same story.",
                    x,
                    y,
                    _unique_node_ids(first, second),
                    [first.element.elem_id, second.element.elem_id],
                    "Remove or split duplicate/overlapping line members before FLOORLOAD generation.",
                )
            )
    return overlaps_by_target, issues


def _detect_split_overlap_duplicate_elements(
    story: Story,
    segments: Sequence[_LineElementSegment],
    overlaps_by_target: dict[int, list[_LineOverlap]],
    *,
    coverage_threshold: float = 0.90,
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    segment_by_id = {segment.element.elem_id: segment for segment in segments}
    for element_id, overlaps in sorted(overlaps_by_target.items()):
        if len({overlap.other.element.elem_id for overlap in overlaps}) < 2:
            continue
        target = segment_by_id.get(element_id)
        if target is None:
            continue
        merged = _merge_intervals([(overlap.start, overlap.end) for overlap in overlaps], tolerance=max(1.0e-9, target.length * 1.0e-9))
        covered_length = sum(end - start for start, end in merged)
        if target.length <= 0.0 or covered_length / target.length < coverage_threshold:
            continue
        chain_ids = sorted({overlap.other.element.elem_id for overlap in overlaps})
        node_ids = sorted({node_id for segment in [target, *(overlap.other for overlap in overlaps)] for node_id in segment.element.node_ids})
        x, y = _segment_midpoint(target)
        issues.append(
            _issue(
                story.name,
                "WARNING",
                "SPLIT_OVERLAP_DUPLICATE_ELEMENT",
                "A line element is duplicated over split line elements on the same story.",
                x,
                y,
                node_ids,
                [target.element.elem_id, *chain_ids],
                "Review element overlap. FLOORLOAD boundary/support detection may miss or misread duplicated beams.",
            )
        )
    return issues


def _coordinate_duplicate_tolerance(snap_tolerance: float) -> float:
    return max(1.0e-6, min(abs(float(snap_tolerance)) * 0.01, 1.0e-3))


def _line_endpoint_coordinates_match(first: _LineElementSegment, second: _LineElementSegment, tolerance: float) -> bool:
    direct = _node_xy_distance(first.start, second.start) <= tolerance and _node_xy_distance(first.end, second.end) <= tolerance
    reversed_match = _node_xy_distance(first.start, second.end) <= tolerance and _node_xy_distance(first.end, second.start) <= tolerance
    return direct or reversed_match


def _segment_bboxes_may_overlap(first: _LineElementSegment, second: _LineElementSegment, tolerance: float) -> bool:
    first_min_x = min(first.start.x, first.end.x) - tolerance
    first_max_x = max(first.start.x, first.end.x) + tolerance
    first_min_y = min(first.start.y, first.end.y) - tolerance
    first_max_y = max(first.start.y, first.end.y) + tolerance
    second_min_x = min(second.start.x, second.end.x) - tolerance
    second_max_x = max(second.start.x, second.end.x) + tolerance
    second_min_y = min(second.start.y, second.end.y) - tolerance
    second_max_y = max(second.start.y, second.end.y) + tolerance
    return first_min_x <= second_max_x and second_min_x <= first_max_x and first_min_y <= second_max_y and second_min_y <= first_max_y


def _projected_overlap_on_target(
    target: _LineElementSegment,
    other: _LineElementSegment,
    tolerance: float,
) -> _LineOverlap | None:
    if abs(target.ux * other.uy - target.uy * other.ux) > 1.0e-6:
        return None
    if _point_to_infinite_line_distance(other.start, target) > tolerance:
        return None
    if _point_to_infinite_line_distance(other.end, target) > tolerance:
        return None
    other_start = _projection_on_segment_axis(other.start, target)
    other_end = _projection_on_segment_axis(other.end, target)
    other_min, other_max = sorted((other_start, other_end))
    overlap_start = max(0.0, other_min)
    overlap_end = min(target.length, other_max)
    overlap_length = overlap_end - overlap_start
    if overlap_length <= _overlap_min_length(target):
        return None
    midpoint_projection = (overlap_start + overlap_end) / 2.0
    midpoint = (target.start.x + target.ux * midpoint_projection, target.start.y + target.uy * midpoint_projection)
    return _LineOverlap(other=other, start=overlap_start, end=overlap_end, midpoint=midpoint)


def _point_to_infinite_line_distance(node: Node, segment: _LineElementSegment) -> float:
    dx = node.x - segment.start.x
    dy = node.y - segment.start.y
    return abs(dx * segment.uy - dy * segment.ux)


def _projection_on_segment_axis(node: Node, segment: _LineElementSegment) -> float:
    return (node.x - segment.start.x) * segment.ux + (node.y - segment.start.y) * segment.uy


def _overlap_min_length(segment: _LineElementSegment) -> float:
    return max(1.0e-6, min(0.01, segment.length * 0.01))


def _merge_intervals(intervals: Sequence[tuple[float, float]], *, tolerance: float) -> list[tuple[float, float]]:
    normalized = sorted((min(start, end), max(start, end)) for start, end in intervals if end - start > tolerance)
    if not normalized:
        return []
    merged: list[tuple[float, float]] = [normalized[0]]
    for start, end in normalized[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + tolerance:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _combined_segment_midpoint(segments: Sequence[_LineElementSegment]) -> tuple[float, float]:
    nodes = [node for segment in segments for node in (segment.start, segment.end)]
    return _centroid_xy_from_nodes(nodes)


def _segment_midpoint(segment: _LineElementSegment) -> tuple[float, float]:
    return (segment.start.x + segment.end.x) / 2.0, (segment.start.y + segment.end.y) / 2.0


def _unique_node_ids(*segments: _LineElementSegment) -> list[int]:
    return sorted({node_id for segment in segments for node_id in segment.element.node_ids})


def _node_xy_distance(first: Node, second: Node) -> float:
    return math.hypot(first.x - second.x, first.y - second.y)


def _detect_unsplit_members(
    story: Story,
    nodes: Sequence[Node],
    elements: Sequence[Element],
    node_by_id: dict[int, Node],
    tolerance: float,
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    for element in elements:
        if element.elem_type not in LINE_TYPES or len(element.node_ids) < 2:
            continue
        start = node_by_id.get(element.node_ids[0])
        end = node_by_id.get(element.node_ids[1])
        if start is None or end is None:
            continue
        for node in nodes:
            if node.node_id in element.node_ids:
                continue
            distance, projection = _point_to_segment_distance((node.x, node.y), (start.x, start.y), (end.x, end.y))
            if distance <= tolerance and 1.0e-6 < projection < 1.0 - 1.0e-6:
                issues.append(
                    FloorLoadDiagnosticIssue(
                        story.name,
                        "INFO",
                        "UNSPLIT_MEMBER",
                        "A debug check found a node lying on a member that is not split at that point.",
                        node.x,
                        node.y,
                        [node.node_id, start.node_id, end.node_id],
                        [element.elem_id],
                        "Use this only as an optional modeling review item.",
                    )
                )
    return issues


def _detect_open_line_edges(story: Story, elements: Sequence[Element], node_by_id: dict[int, Node]) -> list[FloorLoadDiagnosticIssue]:
    degree: dict[int, int] = {}
    line_elements = [element for element in elements if element.elem_type in LINE_TYPES and len(element.node_ids) >= 2]
    for element in line_elements:
        a, b = element.node_ids[0], element.node_ids[1]
        degree[a] = degree.get(a, 0) + 1
        degree[b] = degree.get(b, 0) + 1
    issues: list[FloorLoadDiagnosticIssue] = []
    for node_id, count in degree.items():
        if count == 1 and node_id in node_by_id:
            node = node_by_id[node_id]
            issues.append(
                FloorLoadDiagnosticIssue(
                    story.name,
                    "INFO",
                    "OPEN_BOUNDARY",
                    "A debug check found a degree-1 line-element node.",
                    node.x,
                    node.y,
                    [node_id],
                    [],
                    "This is not a default FLOORLOAD blocking condition.",
                )
            )
    return issues


def _default_duplicate_node_tolerance(length_unit: str) -> float:
    unit = str(length_unit or "").upper()
    if unit == "MM":
        return 1.0
    if unit == "CM":
        return 0.1
    return 1.0e-4


def _issue(
    story_name: str,
    severity: str,
    issue_type: str,
    message: str,
    x: float,
    y: float,
    node_ids: list[int],
    element_ids: list[int],
    suggested_action: str,
) -> FloorLoadDiagnosticIssue:
    return FloorLoadDiagnosticIssue(
        str(story_name or ""),
        severity,
        issue_type,
        message,
        float(x),
        float(y),
        list(node_ids),
        list(element_ids),
        suggested_action,
    )


def _region_load_name(load_region) -> str:
    load = getattr(load_region, "load", None)
    if load is None:
        return ""
    return str(getattr(load, "floor_load_type_name", "") or getattr(load, "real_name", "") or "").strip()


def _region_xy(region, vertices: Sequence[tuple[float, float]]) -> tuple[float, float]:
    polygon = getattr(region, "polygon", None)
    if polygon is not None and not getattr(polygon, "is_empty", True):
        point = polygon.representative_point()
        return float(point.x), float(point.y)
    if vertices:
        return sum(x for x, _y in vertices) / len(vertices), sum(y for _x, y in vertices) / len(vertices)
    return 0.0, 0.0


def _centroid_xy_from_nodes(nodes: Sequence[Node]) -> tuple[float, float]:
    if not nodes:
        return 0.0, 0.0
    return sum(node.x for node in nodes) / len(nodes), sum(node.y for node in nodes) / len(nodes)


def _story_name_for_nodes(nodes: Sequence[Node], stories: Sequence[Story], tolerance: float) -> str:
    if not nodes:
        return ""
    z = sum(node.z for node in nodes) / len(nodes)
    story = min(stories, key=lambda item: abs(item.elevation - z), default=None)
    if story and abs(story.elevation - z) <= abs(float(tolerance)):
        return story.name
    return ""


def _has_consecutive_duplicate_points(points: Sequence[tuple[float, float]], tolerance: float = 1.0e-9) -> bool:
    if not points:
        return False
    closed = list(points)
    for first, second in zip(closed, closed[1:] + closed[:1]):
        if math.hypot(first[0] - second[0], first[1] - second[1]) <= tolerance:
            return True
    return False


def _name_key(value: object) -> str:
    return " ".join(str(value or "").strip().split()).casefold()


def _point_to_segment_distance(point: tuple[float, float], start: tuple[float, float], end: tuple[float, float]) -> tuple[float, float]:
    px, py = point
    ax, ay = start
    bx, by = end
    dx = bx - ax
    dy = by - ay
    length_sq = dx * dx + dy * dy
    if length_sq <= 1.0e-18:
        return math.hypot(px - ax, py - ay), 0.0
    projection = ((px - ax) * dx + (py - ay) * dy) / length_sq
    clamped = min(1.0, max(0.0, projection))
    closest = (ax + clamped * dx, ay + clamped * dy)
    return math.hypot(px - closest[0], py - closest[1]), projection


def _element_centroid_xy(element: Element, node_by_id: dict[int, Node]) -> tuple[float, float]:
    pts = [node_by_id[node_id] for node_id in element.node_ids if node_id in node_by_id]
    if not pts:
        return 0.0, 0.0
    return sum(node.x for node in pts) / len(pts), sum(node.y for node in pts) / len(pts)
