from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence, TYPE_CHECKING
import csv
import io
import json
import math
import re

try:
    import ezdxf
except ImportError:  # preview DXF 생성 시점에 사용자에게 명확히 안내
    ezdxf = None
import pandas as pd
from shapely.geometry import Polygon

if TYPE_CHECKING:
    from .dxf_load_reader import LoadRegion
from .load_input_policy import (
    ERROR_ONE_WAY_REQUIRES_TRI_OR_QUAD,
    ERROR_TOO_FEW_NODES,
    SNAP_ERROR_EXCEEDED,
    build_load_input_policy,
)
from .mgt_parser import Node, Story, read_text, write_text


@dataclass(frozen=True)
class FloorLoadAssignment:
    load_type_name: str
    dl: float
    ll: float
    node_ids: tuple[int, ...]
    source_layer: str
    source_type: str
    area: float
    status: str
    warnings: tuple[str, ...]
    story_name: str = ""
    source_id: str = ""
    polygon_index: int = 0
    distribution: str = "TWO_WAY"
    distribution_source: str = ""
    effective_idist: int = 2
    allow_polygon_type: bool = True
    one_way_angle_deg: float | None = None
    direction_source: str = ""
    direction_marker_source_id: str = ""
    hatch_pattern_name: str = ""
    hatch_solid_fill: int = 0
    layout_metadata_used: bool = False
    layout_metadata_path: str = ""
    placed_bbox: tuple[float, ...] = ()
    source_bbox: tuple[float, ...] = ()
    transform_applied: bool = False
    snap_before_transform: float | None = None
    snap_after_transform: float | None = None
    snap_max_error: float | None = None

    def to_record(self) -> dict:
        return {
            "하중명": self.load_type_name,
            "DL": self.dl,
            "LL": self.ll,
            "절점수": len(self.node_ids),
            "절점목록": ",".join(str(n) for n in self.node_ids),
            "DXF 레이어": self.source_layer,
            "DXF 객체": self.source_type,
            "면적": self.area,
            "상태": self.status,
            "경고": " | ".join(self.warnings),
            "DXF Story": self.story_name,
            "layout_metadata_used": "YES" if self.layout_metadata_used else "NO",
            "layout_metadata_path": self.layout_metadata_path,
            "placed_bbox": _format_bbox(self.placed_bbox),
            "source_bbox": _format_bbox(self.source_bbox),
            "transform_applied": "YES" if self.transform_applied else "NO",
            "snap_before_transform": _format_optional_float(self.snap_before_transform),
            "snap_after_transform": _format_optional_float(self.snap_after_transform),
            "snap_max_error": _format_optional_float(self.snap_max_error),
        }


@dataclass(frozen=True)
class BuildResult:
    full_mgt_path: Path
    report_xlsx_path: Path
    report_csv_path: Path
    preview_dxf_path: Path
    assignment_count: int
    warning_count: int


def build_assignments_from_regions(
    *,
    regions: Iterable['LoadRegion'],
    story_nodes: Sequence[Node],
    story_nodes_by_name: dict[str, Sequence[Node]] | None = None,
    snap_tolerance: float = 0.5,
    include_zero_load: bool = False,
) -> list[FloorLoadAssignment]:
    assignments: list[FloorLoadAssignment] = []
    for region in regions:
        warnings = list(region.warnings)
        region_story = getattr(region.region, "story_name", "")
        region_source_id = getattr(region.region, "source_id", "")
        region_polygon_index = int(getattr(region.region, "polygon_index", 0) or 0)
        region_hatch_pattern = getattr(region.region, "hatch_pattern_name", "")
        region_hatch_solid = int(getattr(region.region, "hatch_solid_fill", 0) or 0)
        layout_metadata_used = bool(getattr(region.region, "layout_metadata_used", False))
        layout_metadata_path = str(getattr(region.region, "layout_metadata_path", "") or "")
        placed_bbox = tuple(getattr(region.region, "placed_bbox", ()) or ())
        source_bbox = tuple(getattr(region.region, "source_bbox", ()) or getattr(region.region, "bbox", ()) or ())
        transform_applied = bool(getattr(region.region, "transform_applied", False))
        if region.load is None:
            assignments.append(
                FloorLoadAssignment(
                    "",
                    0.0,
                    0.0,
                    tuple(),
                    region.region.layer,
                    region.region.source_type,
                    region.area,
                    "LOAD_PARSE_FAILED",
                    tuple(warnings),
                    story_name=region_story,
                    source_id=region_source_id,
                    polygon_index=region_polygon_index,
                    hatch_pattern_name=region_hatch_pattern,
                    hatch_solid_fill=region_hatch_solid,
                    layout_metadata_used=layout_metadata_used,
                    layout_metadata_path=layout_metadata_path,
                    placed_bbox=placed_bbox,
                    source_bbox=source_bbox,
                    transform_applied=transform_applied,
                )
            )
            continue
        if not include_zero_load and abs(region.load.dl) <= 1.0e-12 and abs(region.load.ll) <= 1.0e-12:
            warnings.append("DL/LL이 모두 0이므로 입력 제외되었습니다. 0 값도 명시 입력 옵션을 켜면 기록됩니다.")
            assignments.append(
                FloorLoadAssignment(
                    region.load.real_name,
                    region.load.dl,
                    region.load.ll,
                    tuple(),
                    region.region.layer,
                    region.region.source_type,
                    region.area,
                    "ZERO_LOAD_SKIPPED",
                    tuple(warnings),
                    story_name=region_story,
                    source_id=region_source_id,
                    polygon_index=region_polygon_index,
                    hatch_pattern_name=region_hatch_pattern,
                    hatch_solid_fill=region_hatch_solid,
                    layout_metadata_used=layout_metadata_used,
                    layout_metadata_path=layout_metadata_path,
                    placed_bbox=placed_bbox,
                    source_bbox=source_bbox,
                    transform_applied=transform_applied,
                )
            )
            continue
        nodes_for_region = story_nodes_by_name.get(region_story, story_nodes) if story_nodes_by_name else story_nodes
        snap_before_transform = None
        placed_vertices = tuple(getattr(region.region, "placed_vertices", ()) or ())
        if transform_applied and placed_vertices:
            _before_node_ids, snap_before_transform = _snap_polygon_vertices_to_nodes(placed_vertices, nodes_for_region)
        node_ids, max_error = _snap_polygon_vertices_to_nodes(region.region.vertices, nodes_for_region)
        snap_after_transform = max_error
        node_lookup = {node.node_id: node for node in nodes_for_region}
        snapped_points = [(node_lookup[node_id].x, node_lookup[node_id].y) for node_id in node_ids if node_id in node_lookup]
        policy = build_load_input_policy(region=region.region, load=region.load, snapped_points=snapped_points)
        warnings.extend(policy.warnings)
        if len(node_ids) < 3:
            warnings.append("해치 경계에 대응되는 절점이 3개 미만입니다. Story 선택 또는 CAD 좌표계를 확인하세요.")
            status = ERROR_TOO_FEW_NODES
        elif max_error > snap_tolerance:
            warnings.append(f"최대 snap 오차 {max_error:.6g}이 허용값 {snap_tolerance:.6g}을 초과했습니다.")
            status = SNAP_ERROR_EXCEEDED
        elif policy.errors:
            status = policy.errors[0]
            warnings.extend(_policy_error_messages(policy.errors, len(node_ids)))
        else:
            status = "OK" if not warnings else _review_status(warnings)
        assignments.append(
            FloorLoadAssignment(
                load_type_name=region.load.real_name,
                dl=region.load.dl,
                ll=region.load.ll,
                node_ids=tuple(node_ids),
                source_layer=region.region.layer,
                source_type=region.region.source_type,
                area=region.area,
                status=status,
                warnings=tuple(warnings),
                story_name=region_story,
                source_id=region_source_id,
                polygon_index=region_polygon_index,
                distribution=policy.distribution,
                distribution_source=policy.distribution_source,
                effective_idist=policy.effective_idist,
                allow_polygon_type=policy.allow_polygon_type,
                one_way_angle_deg=policy.one_way_angle_deg,
                direction_source=policy.direction_source,
                direction_marker_source_id=policy.direction_marker_source_id,
                hatch_pattern_name=region_hatch_pattern,
                hatch_solid_fill=region_hatch_solid,
                layout_metadata_used=layout_metadata_used,
                layout_metadata_path=layout_metadata_path,
                placed_bbox=placed_bbox,
                source_bbox=source_bbox,
                transform_applied=transform_applied,
                snap_before_transform=snap_before_transform,
                snap_after_transform=snap_after_transform,
                snap_max_error=max_error,
            )
        )
    return assignments


def _policy_error_messages(errors: Sequence[str], node_count: int) -> list[str]:
    messages: list[str] = []
    if ERROR_ONE_WAY_REQUIRES_TRI_OR_QUAD in errors:
        messages.append(
            "ONE WAY 하중은 3각형 또는 4각형 영역에만 적용 가능합니다. "
            f"현재 영역은 {node_count}개 절점으로 인식되었습니다. "
            "CAD에서 해당 해치 영역을 3각형/4각형 단위로 분할하거나, TWO WAY 하중이면 SOLID 해치 또는 _TW 레이어를 사용하세요."
        )
    if ERROR_TOO_FEW_NODES in errors:
        messages.append("FLOORLOAD 경계 절점이 3개 미만입니다. CAD 해치 경계와 모델 node/snap tolerance를 확인하세요.")
    return messages


def _review_status(warnings: Sequence[str]) -> str:
    for warning in warnings:
        text = str(warning)
        if text.startswith("REVIEW_") or text.startswith("AMBIGUOUS_"):
            return text
    return "REVIEW"


def patch_full_mgt_with_floorloads(
    *,
    source_mgt_path: str | Path,
    output_mgt_path: str | Path,
    assignments: Sequence[FloorLoadAssignment],
    mode: str = "append",
    encoding: str = "cp949",
) -> Path:
    text = read_text(source_mgt_path)
    patched = patch_full_mgt_text(text, assignments=assignments, mode=mode)
    return write_text(output_mgt_path, patched, encoding=encoding)


def patch_full_mgt_text(text: str, *, assignments: Sequence[FloorLoadAssignment], mode: str = "append") -> str:
    valid = [a for a in assignments if _is_assignment_recordable(a)]
    lines = _logical_lines(text.splitlines())
    previous_floorload_count = _count_sections(lines, "*FLOORLOAD")
    if mode.lower() in {"overwrite", "replace"}:
        lines = _remove_sections(lines, {"*FLOADTYPE", "*FLOORLOAD"})

    existing_load_types = _existing_floadtype_names(lines)
    floadtype_records = _make_floadtype_records(valid, existing_load_types)
    floorload_block = _make_floorload_block(valid)

    if floadtype_records:
        lines = _insert_records_into_section(
            lines,
            section_name="*FLOADTYPE",
            header_lines=[
                "*FLOADTYPE    ; Define Floor Load Type",
                "; NAME, DESC",
                "; LCNAME1, FLOAD1, bSBU1, ..., LCNAME8, FLOAD8, bSBU8",
            ],
            records=floadtype_records,
            before_section="*FLOORLOAD",
        )

    if floorload_block:
        insert_at = _find_section_insert_position(lines, "*ENDDATA")
        lines = lines[:insert_at] + [""] + floorload_block + [""] + lines[insert_at:]

    patched = "\r\n".join(lines) + "\r\n"
    _validate_patched_floorload_mgt(patched)
    if valid:
        _validate_appended_floorload_block(patched, previous_floorload_count=previous_floorload_count, require_new_block=mode.lower() not in {"overwrite", "replace"})
    return patched


def write_reports(
    *,
    assignments: Sequence[FloorLoadAssignment],
    output_dir: str | Path,
    model_name: str,
    story: Story,
    dxf_name: str,
) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for item in assignments:
        row = item.to_record()
        row.update(
            {
                "DXF Story": item.story_name,
                "layout_metadata_used": "YES" if item.layout_metadata_used else "NO",
                "layout_metadata_path": item.layout_metadata_path,
                "placed_bbox": _format_bbox(item.placed_bbox),
                "source_bbox": _format_bbox(item.source_bbox),
                "transform_applied": "YES" if item.transform_applied else "NO",
                "snap_before_transform": _format_optional_float(item.snap_before_transform),
                "snap_after_transform": _format_optional_float(item.snap_after_transform),
                "snap_max_error": _format_optional_float(item.snap_max_error),
                "DXF source_id": item.source_id,
                "DXF polygon_index": item.polygon_index,
                "HATCH 패턴": item.hatch_pattern_name,
                "SOLID 여부": "YES" if item.hatch_solid_fill else "NO",
                "입력방식": item.distribution,
                "입력방식 결정근거": item.distribution_source,
                "최종 iDIST": item.effective_idist,
                "Allow Polygon": "YES" if item.allow_polygon_type else "NO",
                "절점수": len(item.node_ids),
                "ONE WAY 주방향": "" if item.one_way_angle_deg is None else item.one_way_angle_deg,
                "방향 산정 방식": item.direction_source,
                "짧은 스팬 자동산정 여부": "YES" if item.direction_source.startswith("AUTO_SHORT_SPAN") else "NO",
                "방향 override 여부": "YES" if item.direction_source in {"DXF_DIRECTION_MARKER", "LAYER_ANGLE_TOKEN", "USER_DEFAULT"} else "NO",
                "방향선 source_id": item.direction_marker_source_id,
            }
        )
        row.update({"모델명": model_name, "Story명": story.name, "Story Elevation": story.elevation, "DXF 파일명": dxf_name})
        rows.append(row)
    df = pd.DataFrame(rows)
    xlsx = out / f"{Path(model_name).stem}_{story.name}_floorload_report.xlsx"
    csv_path = out / f"{Path(model_name).stem}_{story.name}_floorload_report.csv"
    df.to_excel(xlsx, index=False)
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")
    return xlsx, csv_path


def write_assignment_preview_dxf(assignments: Sequence[FloorLoadAssignment], nodes: Sequence[Node], output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if ezdxf is None:
        raise RuntimeError("ezdxf가 설치되어 있지 않아 검증용 DXF를 생성할 수 없습니다. pip install ezdxf를 실행해 주세요.")
    node_map = {n.node_id: n for n in nodes}
    doc = ezdxf.new("R2010")
    for layer, color in (("FLOAD_OK", 3), ("FLOAD_REVIEW", 1), ("FLOAD_SKIPPED", 8)):
        if layer not in doc.layers:
            doc.layers.add(layer, color=color)
    msp = doc.modelspace()
    for idx, item in enumerate(assignments, start=1):
        pts = [(node_map[n].x, node_map[n].y) for n in item.node_ids if n in node_map]
        if len(pts) >= 3:
            layer = "FLOAD_OK" if item.status == "OK" else "FLOAD_REVIEW"
            msp.add_lwpolyline(pts, close=True, dxfattribs={"layer": layer})
            msp.add_text(f"{idx}:{item.load_type_name}:{item.status}", dxfattribs={"layer": layer, "height": 0.25}).set_placement(pts[0])
        else:
            layer = "FLOAD_SKIPPED"
            msp.add_text(f"{idx}:{item.load_type_name}:{item.status}", dxfattribs={"layer": layer, "height": 0.25}).set_placement((0, -idx * 0.4))
    doc.saveas(out)
    return out


def run_mgt_build_pipeline(
    *,
    source_mgt_path: str | Path,
    output_mgt_path: str | Path,
    report_dir: str | Path,
    preview_dxf_path: str | Path,
    model_name: str,
    story: Story,
    dxf_name: str,
    regions: Sequence['LoadRegion'],
    story_nodes: Sequence[Node],
    snap_tolerance: float,
    include_zero_load: bool,
    story_nodes_by_name: dict[str, Sequence[Node]] | None = None,
    mode: str = "append",
    encoding: str = "cp949",
) -> BuildResult:
    assignments = build_assignments_from_regions(
        regions=regions,
        story_nodes=story_nodes,
        story_nodes_by_name=story_nodes_by_name,
        snap_tolerance=snap_tolerance,
        include_zero_load=include_zero_load,
    )
    xlsx, csv_path = write_reports(assignments=assignments, output_dir=report_dir, model_name=model_name, story=story, dxf_name=dxf_name)
    preview = write_assignment_preview_dxf(assignments, story_nodes, preview_dxf_path)
    valid_assignments = [a for a in assignments if _is_assignment_recordable(a)]
    if not valid_assignments:
        raise RuntimeError(
            "사용자 DXF에서 MGT에 입력 가능한 FLOORLOAD가 0개입니다. "
            "보고서의 Story 판정, inverse transform, snap error를 확인하세요.\n"
            f"보고서: {csv_path}\n"
            f"검증 DXF: {preview}"
        )
    full = patch_full_mgt_with_floorloads(source_mgt_path=source_mgt_path, output_mgt_path=output_mgt_path, assignments=assignments, mode=mode, encoding=encoding)
    return BuildResult(
        full_mgt_path=full,
        report_xlsx_path=xlsx,
        report_csv_path=csv_path,
        preview_dxf_path=preview,
        assignment_count=sum(1 for a in assignments if _is_assignment_recordable(a)),
        warning_count=sum(len(a.warnings) + (0 if a.status == "OK" else 1) for a in assignments),
    )


def _snap_polygon_vertices_to_nodes(vertices: Sequence[tuple[float, float]], story_nodes: Sequence[Node]) -> tuple[list[int], float]:
    if not story_nodes:
        return [], math.inf
    node_ids: list[int] = []
    max_error = 0.0
    seen = set()
    for x, y in vertices:
        best = min(story_nodes, key=lambda n: (n.x - x) ** 2 + (n.y - y) ** 2)
        dist = math.hypot(best.x - x, best.y - y)
        max_error = max(max_error, dist)
        if best.node_id not in seen:
            seen.add(best.node_id)
            node_ids.append(best.node_id)
    return node_ids, max_error


def _logical_lines(lines: list[str]) -> list[str]:
    # MGT line continuation '\\'를 여기서는 해석하지 않고 원문 보존한다.
    return list(lines)


def _remove_sections(lines: list[str], section_names: set[str]) -> list[str]:
    result: list[str] = []
    skip = False
    for line in lines:
        head = _section_head(line)
        if head:
            skip = head in section_names
        if not skip:
            result.append(line)
    return result


def _section_head(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("*"):
        return ""
    return stripped.split(None, 1)[0].upper()


def _count_sections(lines: Sequence[str], section_name: str) -> int:
    target = section_name.upper()
    return sum(1 for line in lines if _section_head(line) == target)


def _find_section_range(lines: Sequence[str], section_name: str) -> tuple[int | None, int | None]:
    target = section_name.upper()
    start = None
    for index, line in enumerate(lines):
        if _section_head(line) == target:
            start = index
            break
    if start is None:
        return None, None

    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _section_head(lines[index]):
            end = index
            break
    return start, end


def _find_section_insert_position(lines: Sequence[str], before_section: str = "*ENDDATA") -> int:
    target = before_section.upper()
    for index, line in enumerate(lines):
        if _section_head(line) == target:
            return index
    if target != "*ENDDATA":
        for index, line in enumerate(lines):
            if _section_head(line) == "*ENDDATA":
                return index
    return len(lines)


def _insert_records_into_section(
    lines: list[str],
    *,
    section_name: str,
    header_lines: Sequence[str],
    records: Sequence[str],
    before_section: str = "*ENDDATA",
) -> list[str]:
    if not records:
        return lines

    start, end = _find_section_range(lines, section_name)
    if start is not None and end is not None:
        insert_at = end
        while insert_at > start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        return lines[:insert_at] + list(records) + lines[insert_at:]

    insert_at = _find_section_insert_position(lines, before_section)
    new_block = [""] + list(header_lines) + list(records) + [""]
    return lines[:insert_at] + new_block + lines[insert_at:]


def _existing_floadtype_names(lines: list[str]) -> set[str]:
    names = set()
    in_block = False
    expect_name_line = False
    for line in lines:
        stripped = line.strip()
        head = _section_head(line)
        if head == "*FLOADTYPE":
            in_block = True
            expect_name_line = True
            continue
        if in_block and head:
            break
        if not in_block or not stripped or stripped.startswith(";"):
            continue
        if expect_name_line:
            parts = _csv_split(stripped)
            if parts:
                names.add(parts[0].strip().strip('"'))
            expect_name_line = False
        else:
            expect_name_line = True
    return names


def _make_floadtype_records(assignments: Sequence[FloorLoadAssignment], existing_names: set[str]) -> list[str]:
    unique: dict[str, FloorLoadAssignment] = {}
    for a in assignments:
        if a.load_type_name and a.load_type_name not in unique:
            unique[a.load_type_name] = a
    lines: list[str] = []
    for name, item in unique.items():
        if name in existing_names:
            continue
        fields = []
        if abs(item.dl) > 1.0e-12:
            fields.extend(["DL", _fmt_load(-abs(item.dl)), "YES"])
        if abs(item.ll) > 1.0e-12:
            fields.extend(["LL", _fmt_load(-abs(item.ll)), "NO"])
        if not fields:
            continue
        lines.append(f"   {_mgt_field(name)},")
        lines.append("   " + ", ".join(fields))
    return lines


def _make_floorload_block(assignments: Sequence[FloorLoadAssignment]) -> list[str]:
    records = _make_floorload_records(assignments)
    if not records:
        return []

    return [
        "*FLOORLOAD    ; Floor Loads",
        "; LTNAME, iDIST, ANGLE, iSBEAM, SBANG, SBUW, DIR, bPROJ, DESC, bEX, bAL, GROUP, NODE1, ..., NODEn  ; iDIST=1,2",
        "; LTNAME, iDIST, DIR, bPROJ, DESC, GROUP, NODE1, ..., NODEn                                        ; iDIST=3,4",
        "; [iDIST] 1=One Way, 2=Two Way, 3=Polygon-Centroid, 4=Polygon-Length",
        *records,
    ]


def _make_floorload_records(assignments: Sequence[FloorLoadAssignment]) -> list[str]:
    lines: list[str] = []
    for item in assignments:
        node_ids = tuple(getattr(item, "node_ids", ()) or ())
        if not _is_assignment_recordable(item):
            continue
        ltname = str(getattr(item, "load_type_name", "") or getattr(item, "load_real_name", "") or "").strip()
        if not ltname:
            continue
        node_text = ", ".join(str(int(n)) for n in node_ids)
        # 기존 MGT 샘플과 동일하게 Two Way(iDIST=2), GZ, bPROJ=NO, bAL=YES 형식 사용.
        idist = int(getattr(item, "effective_idist", 2) or 2)
        if idist == 1:
            angle = _fmt_angle(getattr(item, "one_way_angle_deg", 0.0) or 0.0)
            lines.append(f"   {_mgt_field(ltname)}, 1, {angle}, 0, 0, 0, GZ, NO, , NO, YES, , {node_text}")
        elif idist == 3:
            lines.append(f"   {_mgt_field(ltname)}, 3, GZ, NO, , , {node_text}")
        elif idist == 4:
            lines.append(f"   {_mgt_field(ltname)}, 4, GZ, NO, , , {node_text}")
        else:
            lines.append(f"   {_mgt_field(ltname)}, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , {node_text}")
    _validate_floorload_records_do_not_reference_dxf(lines)
    return lines


def _is_assignment_recordable(item: FloorLoadAssignment) -> bool:
    status = str(getattr(item, "status", "") or "")
    return (
        (status == "OK" or status == "REVIEW" or status.startswith("REVIEW_"))
        and len(tuple(getattr(item, "node_ids", ()) or ())) >= 3
        and bool(str(getattr(item, "load_type_name", "") or "").strip())
    )


def _fmt_angle(value: float) -> str:
    text = f"{float(value) % 360.0:.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _validate_patched_floorload_mgt(text: str) -> None:
    if "DXF_AUTO layer=" in text:
        raise ValueError(
            "MGT generation error: DXF_AUTO layer text was written to the MGT. "
            "Keep CAD layer tracing in reports only."
        )
    if "DXF_FLOORLOAD" in text:
        raise ValueError(
            "MGT generation error: DXF_FLOORLOAD group was written to the MGT. "
            "Leave the FLOORLOAD GROUP field blank."
        )
    if re.search(r"\bLOAD_\d{3}_", text):
        raise ValueError(
            "MGT generation error: CAD DXF layer names were written to the MGT. "
            "Use MIDAS floor load type names only."
        )


def _validate_appended_floorload_block(text: str, *, previous_floorload_count: int, require_new_block: bool) -> None:
    lines = text.splitlines()
    floorload_count = _count_sections(lines, "*FLOORLOAD")
    if floorload_count <= 0:
        raise RuntimeError("MGT generation error: valid FLOORLOAD assignments exist but no *FLOORLOAD block was written.")
    if require_new_block and floorload_count <= previous_floorload_count:
        raise RuntimeError("MGT generation error: valid FLOORLOAD assignments exist but no new *FLOORLOAD block was appended.")
    enddata_index = _find_section_insert_position(lines, "*ENDDATA")
    floorload_indices = [index for index, line in enumerate(lines) if _section_head(line) == "*FLOORLOAD"]
    if enddata_index < len(lines) and floorload_indices and max(floorload_indices) > enddata_index:
        raise RuntimeError("MGT generation error: *FLOORLOAD block must be placed before *ENDDATA.")


def _validate_floorload_records_do_not_reference_dxf(records: Sequence[str]) -> None:
    for record in records:
        if "DXF_AUTO layer=" in record or "DXF_FLOORLOAD" in record or re.search(r"\bLOAD_\d{3}_", record):
            raise ValueError(
                "MGT generation error: FLOORLOAD records must not include CAD DXF layer names. "
                "Keep DXF layer tracing in reports only."
            )


def _csv_split(line: str) -> list[str]:
    try:
        return [c.strip() for c in next(csv.reader(io.StringIO(line), skipinitialspace=True))]
    except Exception:
        return [c.strip() for c in line.split(",")]


def _mgt_field(value: object) -> str:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split()).replace('"', "'")
    return f'"{text}"' if "," in text else text


def _fmt_load(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _format_bbox(values: Sequence[float] | None) -> str:
    if not values:
        return ""
    return ",".join(_format_optional_float(float(value)) for value in values)


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text
