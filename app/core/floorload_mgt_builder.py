from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, replace
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
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.ops import unary_union

if TYPE_CHECKING:
    from .dxf_load_reader import LoadRegion
    from .hatch_region_editor import EditableHatchRegion
from .load_input_policy import (
    ERROR_ONE_WAY_REQUIRES_TRI_OR_QUAD,
    ERROR_TOO_FEW_NODES,
    SNAP_ERROR_EXCEEDED,
    build_load_input_policy,
    infer_distribution,
)
from .dummy_member_generator import (
    DummyGenerationSummary,
    generate_load_dm_dummy_members,
    write_dummy_member_report,
)
from .floorload_audit_report import FloorloadAuditCollector, write_floorload_pipeline_audit
from .mgt_parser import Node, Story, read_text, write_text
from .mgt_import_validator import (
    MgtImportCapabilities,
    MgtValidationResult,
    floorload_node_limit,
    read_mgt_text_document,
    resolve_mgt_import_capabilities,
    validate_mgt_for_import,
    write_mgt_text_atomic,
    write_validation_report,
)


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
    one_way_mgt_angle_deg: float | None = None
    one_way_first_edge_angle_deg: float | None = None
    one_way_polygon_orientation: str = ""
    direction_source: str = ""
    direction_marker_source_id: str = ""
    direction_marker_count: int = 0
    direction_marker_match_methods: tuple[str, ...] = ()
    hatch_pattern_name: str = ""
    hatch_solid_fill: int = 0
    layout_metadata_used: bool = False
    layout_metadata_path: str = ""
    placed_bbox: tuple[float, ...] = ()
    source_bbox: tuple[float, ...] = ()
    model_bbox: tuple[float, ...] = ()
    transform_applied: bool = False
    snap_before_transform: float | None = None
    snap_after_transform: float | None = None
    snap_max_error: float | None = None
    snap_node_count_raw: int = 0
    snap_node_count_simplified: int = 0
    node_simplified: bool = False
    polygon_vertices: tuple[tuple[float, float], ...] = ()
    merge_group_id: str = ""
    merged_source_count: int = 1
    merged_source_ids: tuple[str, ...] = ()
    audit_id: str = ""
    source_region_key: str = ""
    source_region_keys: tuple[str, ...] = ()
    pipeline_stage: str = ""
    skip_reason_code: str = ""
    skip_reason_ko: str = ""
    final_record_created: bool = False
    final_record_index: int = 0
    final_mgt_record_preview: str = ""
    allowed_region_check_data: dict = field(default_factory=dict)

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
            "model_bbox": _format_bbox(self.model_bbox),
            "transform_applied": "YES" if self.transform_applied else "NO",
            "snap_before_transform": _format_optional_float(self.snap_before_transform),
            "snap_after_transform": _format_optional_float(self.snap_after_transform),
            "snap_max_error": _format_optional_float(self.snap_max_error),
            "snap_node_count_raw": self.snap_node_count_raw,
            "snap_node_count_simplified": self.snap_node_count_simplified,
            "node_simplified": "YES" if self.node_simplified else "NO",
            "one_way_global_flow_angle": _format_optional_float(self.one_way_angle_deg),
            "one_way_mgt_angle": _format_optional_float(self.one_way_mgt_angle_deg),
            "first_edge_angle": _format_optional_float(self.one_way_first_edge_angle_deg),
            "polygon_orientation": self.one_way_polygon_orientation,
            "one_way_direction_source": self.direction_source,
            "direction_marker_count": self.direction_marker_count,
            "direction_marker_match_methods": " | ".join(self.direction_marker_match_methods),
            "merge_group_id": self.merge_group_id,
            "merged_source_count": self.merged_source_count,
            "merged_source_ids": " | ".join(self.merged_source_ids),
        }


@dataclass(frozen=True)
class BuildResult:
    full_mgt_path: Path
    report_xlsx_path: Path
    report_csv_path: Path
    preview_dxf_path: Path
    assignment_count: int
    warning_count: int
    dummy_summary: DummyGenerationSummary | None = None
    dummy_report_csv_path: Path | None = None
    audit_json_path: Path | None = None
    audit_csv_path: Path | None = None
    duplicate_removed_count: int = 0
    import_preflight: MgtValidationResult | None = None
    import_preflight_json_path: Path | None = None
    import_preflight_csv_path: Path | None = None


@dataclass(frozen=True)
class AllowedStoryRegionCheck:
    status: str | None = None
    data: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is None


MERGED_FLOORLOAD_REGIONS = "MERGED_FLOORLOAD_REGIONS"
MERGE_SKIPPED_SNAP_ERROR = "MERGE_SKIPPED_SNAP_ERROR"
MERGE_SKIPPED_TOO_FEW_NODES = "MERGE_SKIPPED_TOO_FEW_NODES"
MERGE_SKIPPED_ONE_WAY_POLYGON_NODE_LIMIT = "MERGE_SKIPPED_ONE_WAY_POLYGON_NODE_LIMIT"
MERGE_PARTITIONED_LOGICAL_FIELD_LIMIT = "MERGE_PARTITIONED_LOGICAL_FIELD_LIMIT"
BELOW_ALLOWED_REGION_MISMATCH = "BELOW_ALLOWED_REGION_MISMATCH"
BELOW_ALLOWED_REGION_WARNING = "선택 Story의 BELOW 기준 하중입력 가능 영역 밖에 있는 해치입니다. 표시되지 않는 영역에는 FLOORLOAD를 입력하지 않습니다."
BELOW_ALLOWED_REGION_MISSING = "BELOW_ALLOWED_REGION_MISSING"
BELOW_ALLOWED_REGION_MISSING_WARNING = "선택 Story의 BELOW 기준 하중 허용영역을 확인하지 못해 FLOORLOAD 입력을 차단했습니다. 구조요소 표시/Story metadata를 확인하세요."
FLOORLOAD_SKIP_REASON_KO = {
    BELOW_ALLOWED_REGION_MISMATCH: BELOW_ALLOWED_REGION_WARNING,
    BELOW_ALLOWED_REGION_MISSING: BELOW_ALLOWED_REGION_MISSING_WARNING,
    "LOAD_PARSE_FAILED": "하중명 또는 하중 타입 정보를 해석하지 못해 FLOORLOAD record를 생성하지 않았습니다.",
    "ZERO_LOAD_SKIPPED": "DL/LL이 모두 0이므로 FLOORLOAD 입력에서 제외되었습니다.",
    "STORY_NODE_SET_MISSING": "해당 Story의 모델 node set을 찾지 못해 FLOORLOAD 경계 절점을 만들지 못했습니다.",
    SNAP_ERROR_EXCEEDED: "해치 경계와 모델 node의 snap 오차가 허용값을 초과했습니다.",
    ERROR_TOO_FEW_NODES: "FLOORLOAD 경계 절점이 3개 미만입니다.",
    ERROR_ONE_WAY_REQUIRES_TRI_OR_QUAD: "ONE-WAY 하중은 3각형 또는 4각형 영역에만 적용 가능합니다.",
    "DUPLICATE_OVERRIDDEN_BY_INTERNAL_REGION": "INTERNAL 직접 입력 영역과 중복되어 DXF 해치가 제외되었습니다.",
    "FINAL_RECORD_SKIPPED": "최종 FLOORLOAD record 생성 조건을 만족하지 못했습니다.",
}


def _compute_short_span_global_angle_from_nodes(
    node_ids: Sequence[int],
    node_lookup: dict[int, Node],
) -> float | None:
    points = _points_from_node_ids(node_ids, node_lookup)
    if len(points) < 3:
        return None
    if len(points) > 1 and _same_xy(points[0], points[-1]):
        points = points[:-1]

    edges: list[tuple[float, float]] = []
    count = len(points)
    for index in range(count):
        start = points[index]
        end = points[(index + 1) % count]
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length <= 1.0e-9:
            continue
        edges.append((length, _angle_deg(start, end) % 180.0))
    if not edges:
        return None

    groups: list[dict[str, object]] = []
    for length, angle in edges:
        matched = False
        for group in groups:
            if _axis_angle_delta(angle, float(group["angle"])) <= 5.0:
                lengths = group["lengths"]
                if isinstance(lengths, list):
                    lengths.append(length)
                matched = True
                break
        if not matched:
            groups.append({"angle": angle, "lengths": [length]})
    if not groups:
        return None

    for group in groups:
        length_values = group["lengths"]
        if not isinstance(length_values, list) or not length_values:
            return None
        lengths = sorted(float(value) for value in length_values)
        mid = len(lengths) // 2
        if len(lengths) % 2:
            representative_length = lengths[mid]
        else:
            representative_length = (lengths[mid - 1] + lengths[mid]) / 2.0
        group["representative_length"] = representative_length

    short_group = min(groups, key=lambda group: float(group["representative_length"]))
    return float(short_group["angle"]) % 180.0


def _to_midas_one_way_relative_angle(
    *,
    global_flow_angle_deg: float,
    node_ids: Sequence[int],
    node_lookup: dict[int, Node],
) -> tuple[float, float, str]:
    points = _points_from_node_ids(node_ids, node_lookup)
    if len(points) < 2:
        return float(global_flow_angle_deg) % 360.0, 0.0, "UNKNOWN"

    first_edge_angle = _angle_deg(points[0], points[1])
    orientation = _polygon_orientation(points)
    global_angle = float(global_flow_angle_deg) % 360.0
    if orientation == "CW":
        mgt_angle = (first_edge_angle - global_angle) % 360.0
    else:
        mgt_angle = (global_angle - first_edge_angle) % 360.0
    return mgt_angle, first_edge_angle, orientation


def _one_way_mgt_debug_fields(
    *,
    effective_idist: int,
    global_flow_angle_deg: float | None,
    node_ids: Sequence[int],
    node_lookup: dict[int, Node],
) -> tuple[float | None, float | None, str]:
    if int(effective_idist or 2) != 1 or global_flow_angle_deg is None:
        return None, None, ""
    if len(node_ids) < 2:
        return None, None, "UNKNOWN"
    mgt_angle, first_edge_angle, orientation = _to_midas_one_way_relative_angle(
        global_flow_angle_deg=global_flow_angle_deg,
        node_ids=node_ids,
        node_lookup=node_lookup,
    )
    return mgt_angle, first_edge_angle, orientation


def _points_from_node_ids(node_ids: Sequence[int], node_lookup: dict[int, Node]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for node_id in node_ids:
        node = node_lookup.get(int(node_id))
        if node is None:
            return []
        points.append((float(node.x), float(node.y)))
    return points


def _polygon_signed_area(points: Sequence[tuple[float, float]]) -> float:
    pts = list(points)
    if len(pts) > 1 and _same_xy(pts[0], pts[-1]):
        pts = pts[:-1]
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for index, start in enumerate(pts):
        end = pts[(index + 1) % len(pts)]
        area += start[0] * end[1] - end[0] * start[1]
    return area / 2.0


def _polygon_orientation(points: Sequence[tuple[float, float]]) -> str:
    signed_area = _polygon_signed_area(points)
    if signed_area > 1.0e-12:
        return "CCW"
    if signed_area < -1.0e-12:
        return "CW"
    return "UNKNOWN"


def _angle_deg(start: tuple[float, float], end: tuple[float, float]) -> float:
    return math.degrees(math.atan2(float(end[1]) - float(start[1]), float(end[0]) - float(start[0]))) % 360.0


def _axis_angle_delta(left: float, right: float) -> float:
    first = float(left) % 180.0
    second = float(right) % 180.0
    diff = abs(first - second)
    return min(diff, 180.0 - diff)


def build_assignments_from_regions(
    *,
    regions: Iterable['LoadRegion'],
    story_nodes: Sequence[Node],
    story_nodes_by_name: dict[str, Sequence[Node]] | None = None,
    snap_tolerance: float = 0.5,
    one_way_shape_tolerance: float = 1.0e-8,
    include_zero_load: bool = False,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None = None,
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
        model_bbox = tuple(getattr(region.region, "model_bbox", ()) or getattr(region.region, "bbox", ()) or ())
        transform_applied = bool(getattr(region.region, "transform_applied", False))
        polygon_vertices = tuple((float(x), float(y)) for x, y in (getattr(region.region, "vertices", ()) or ()))
        direction_markers = tuple(getattr(region.region, "direction_markers", ()) or ())
        direction_marker_count = len(direction_markers)
        direction_marker_match_methods = tuple(
            str(getattr(marker, "match_method", "") or "")
            for marker in direction_markers
            if str(getattr(marker, "match_method", "") or "")
        )
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
                    model_bbox=model_bbox,
                    transform_applied=transform_applied,
                    direction_marker_count=direction_marker_count,
                    direction_marker_match_methods=direction_marker_match_methods,
                    polygon_vertices=polygon_vertices,
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
                    model_bbox=model_bbox,
                    transform_applied=transform_applied,
                    direction_marker_count=direction_marker_count,
                    direction_marker_match_methods=direction_marker_match_methods,
                    polygon_vertices=polygon_vertices,
                )
            )
            continue
        if region_story and story_nodes_by_name is not None:
            nodes_for_region = story_nodes_by_name.get(region_story)
            if not nodes_for_region:
                warnings.append(f"DXF Story '{region_story}'에 해당하는 모델 node set을 찾지 못했습니다.")
                assignments.append(
                    FloorLoadAssignment(
                        load_type_name=region.load.real_name,
                        dl=region.load.dl,
                        ll=region.load.ll,
                        node_ids=tuple(),
                        source_layer=region.region.layer,
                        source_type=region.region.source_type,
                        area=region.area,
                        status="STORY_NODE_SET_MISSING",
                        warnings=tuple(warnings),
                        story_name=region_story,
                        source_id=region_source_id,
                        polygon_index=region_polygon_index,
                        hatch_pattern_name=region_hatch_pattern,
                        hatch_solid_fill=region_hatch_solid,
                        layout_metadata_used=layout_metadata_used,
                        layout_metadata_path=layout_metadata_path,
                        placed_bbox=placed_bbox,
                        source_bbox=source_bbox,
                        model_bbox=model_bbox,
                        transform_applied=transform_applied,
                        snap_max_error=math.inf,
                        direction_marker_count=direction_marker_count,
                        direction_marker_match_methods=direction_marker_match_methods,
                        polygon_vertices=polygon_vertices,
                    )
                )
                continue
        else:
            nodes_for_region = story_nodes
        snap_before_transform = None
        placed_vertices = tuple(getattr(region.region, "placed_vertices", ()) or ())
        if transform_applied and placed_vertices:
            _before_node_ids, snap_before_transform = _snap_polygon_vertices_to_nodes(placed_vertices, nodes_for_region)
        raw_node_ids, max_error = _snap_polygon_vertices_to_nodes(region.region.vertices, nodes_for_region)
        snap_after_transform = max_error
        node_lookup = {node.node_id: node for node in nodes_for_region}
        distribution_hint, _distribution_source = infer_distribution(region.region, region.load)
        simplify_tolerance = (
            max(abs(float(one_way_shape_tolerance)), 1.0e-12)
            if str(distribution_hint or "").upper() == "ONE_WAY"
            else None
        )
        node_ids = _simplify_collinear_node_ids(raw_node_ids, node_lookup, tolerance=simplify_tolerance)
        snapped_points = [(node_lookup[node_id].x, node_lookup[node_id].y) for node_id in node_ids if node_id in node_lookup]
        policy = build_load_input_policy(region=region.region, load=region.load, snapped_points=snapped_points)
        warnings.extend(policy.warnings)
        one_way_global_angle = policy.one_way_angle_deg
        if int(policy.effective_idist or 2) == 1 and str(policy.direction_source or "").startswith("AUTO_SHORT_SPAN"):
            node_short_span_angle = _compute_short_span_global_angle_from_nodes(node_ids, node_lookup)
            if node_short_span_angle is not None:
                one_way_global_angle = node_short_span_angle
        one_way_mgt_angle, one_way_first_edge_angle, one_way_orientation = _one_way_mgt_debug_fields(
            effective_idist=policy.effective_idist,
            global_flow_angle_deg=one_way_global_angle,
            node_ids=node_ids,
            node_lookup=node_lookup,
        )
        allowed_region_check = _allowed_story_region_check(
            region,
            region_story,
            allowed_story_polygons_by_name,
            snapped_points=snapped_points,
            snap_node_ids=node_ids,
            snap_max_error=max_error,
            snap_tolerance=snap_tolerance,
        )
        assignment_node_ids = tuple(node_ids)
        if allowed_region_check.status:
            warnings.append(_allowed_story_region_warning(allowed_region_check.status))
            status = allowed_region_check.status
            assignment_node_ids = tuple()
        elif len(node_ids) < 3:
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
                node_ids=assignment_node_ids,
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
                one_way_angle_deg=one_way_global_angle,
                one_way_mgt_angle_deg=one_way_mgt_angle,
                one_way_first_edge_angle_deg=one_way_first_edge_angle,
                one_way_polygon_orientation=one_way_orientation,
                direction_source=policy.direction_source,
                direction_marker_source_id=policy.direction_marker_source_id,
                direction_marker_count=direction_marker_count,
                direction_marker_match_methods=direction_marker_match_methods,
                hatch_pattern_name=region_hatch_pattern,
                hatch_solid_fill=region_hatch_solid,
                layout_metadata_used=layout_metadata_used,
                layout_metadata_path=layout_metadata_path,
                placed_bbox=placed_bbox,
                source_bbox=source_bbox,
                model_bbox=model_bbox,
                transform_applied=transform_applied,
                snap_before_transform=snap_before_transform,
                snap_after_transform=snap_after_transform,
                snap_max_error=max_error,
                snap_node_count_raw=len(raw_node_ids),
                snap_node_count_simplified=len(node_ids),
                node_simplified=tuple(raw_node_ids) != tuple(node_ids),
                polygon_vertices=polygon_vertices,
                allowed_region_check_data=allowed_region_check.data,
            )
        )
    return assignments


def editable_region_to_load_region(region: "EditableHatchRegion") -> "LoadRegion":
    """Adapt an internally edited Hatch View region to the existing DXF LoadRegion interface."""

    from .dxf_load_reader import HatchRegion, LoadRegion
    from .load_parser import LoadLayerInfo

    points = [(float(x), float(y)) for x, y in tuple(getattr(region, "polygon_xy", ()) or ())]
    polygon = Polygon(points) if len(points) >= 3 else Polygon()
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    bounds = tuple(float(value) for value in polygon.bounds) if not polygon.is_empty else ()
    load_name = str(getattr(region, "load_name", "") or "")
    load_layer = str(getattr(region, "load_layer", "") or load_name or "INTERNAL_LOAD")
    hatch = HatchRegion(
        source_type=str(getattr(region, "source", "") or "INTERNAL"),
        layer=load_layer,
        handle=str(getattr(region, "region_key", "") or ""),
        vertices=points,
        polygon=polygon,
        area=float(polygon.area) if not polygon.is_empty else 0.0,
        bbox=bounds if len(bounds) == 4 else (0.0, 0.0, 0.0, 0.0),
        warnings=list(getattr(region, "warning_codes", ()) or ()),
        story_name=str(getattr(region, "story_name", "") or ""),
        source_id=str(getattr(region, "region_key", "") or ""),
        polygon_index=0,
        hatch_pattern_name="SOLID",
        hatch_solid_fill=1,
        placed_bbox=bounds,
        source_bbox=bounds,
        model_bbox=bounds,
    )
    load = None
    if load_name:
        load = LoadLayerInfo(
            layer=load_layer,
            real_name=load_name,
            dl=float(getattr(region, "dl", 0.0) or 0.0),
            ll=float(getattr(region, "ll", 0.0) or 0.0),
            source="internal",
            distribution=str(getattr(region, "distribution", "") or "TWO_WAY"),
            one_way_angle_deg=getattr(region, "one_way_angle", None),
            distribution_source="HATCH_VIEW_INTERNAL",
        )
    return LoadRegion(region=hatch, load=load, status="OK" if load is not None else "NO_LOAD", warnings=list(getattr(region, "warning_codes", ()) or ()))


def filter_dxf_regions_overridden_by_internal_regions(
    regions: Sequence["LoadRegion"],
    internal_regions: Sequence["EditableHatchRegion"],
    *,
    iou_threshold: float = 0.98,
) -> tuple[list["LoadRegion"], int]:
    """Drop DXF geometry duplicated by authoritative loaded INTERNAL regions."""

    kept, removed = _split_dxf_regions_overridden_by_internal_regions(regions, internal_regions, iou_threshold=iou_threshold)
    return kept, len(removed)


def _split_dxf_regions_overridden_by_internal_regions(
    regions: Sequence["LoadRegion"],
    internal_regions: Sequence["EditableHatchRegion"],
    *,
    iou_threshold: float = 0.98,
) -> tuple[list["LoadRegion"], list["LoadRegion"]]:
    loaded_internal = [region for region in internal_regions if str(getattr(region, "load_name", "") or "")]
    if not regions or not loaded_internal:
        return list(regions), []
    kept: list["LoadRegion"] = []
    removed: list["LoadRegion"] = []
    for region in regions:
        if any(_dxf_region_is_overridden_by_internal(region, internal, iou_threshold=iou_threshold) for internal in loaded_internal):
            removed.append(region)
            continue
        kept.append(region)
    return kept, removed


def _dxf_region_is_overridden_by_internal(region: "LoadRegion", internal: "EditableHatchRegion", *, iou_threshold: float) -> bool:
    dxf_story = str(getattr(getattr(region, "region", None), "story_name", "") or "")
    internal_story = str(getattr(internal, "story_name", "") or "")
    if not dxf_story or not internal_story or dxf_story != internal_story:
        return False
    dxf_polygon = _load_region_polygon(region)
    internal_polygon = _editable_region_polygon(internal)
    if dxf_polygon is None or internal_polygon is None:
        return False
    return _polygons_are_duplicate(dxf_polygon, internal_polygon, iou_threshold=iou_threshold)


def _load_keys_match(region: "LoadRegion", internal: "EditableHatchRegion") -> bool:
    dxf_load_name = str(getattr(getattr(region, "load", None), "real_name", "") or "").strip()
    internal_load_name = str(getattr(internal, "load_name", "") or "").strip()
    if dxf_load_name and internal_load_name and dxf_load_name == internal_load_name:
        return True
    dxf_layer = _normalized_load_layer(str(getattr(getattr(region, "region", None), "layer", "") or ""))
    internal_layer = _normalized_load_layer(str(getattr(internal, "load_layer", "") or ""))
    return bool(dxf_layer and internal_layer and dxf_layer == internal_layer)


def _normalized_load_layer(layer: str) -> str:
    try:
        from .load_parser import strip_cad_work_layer_prefix

        return strip_cad_work_layer_prefix(layer).strip().upper()
    except Exception:
        return str(layer or "").strip().upper()


def _load_region_polygon(region: "LoadRegion") -> Polygon | None:
    polygon = getattr(region, "polygon", None) or getattr(getattr(region, "region", None), "polygon", None)
    if polygon is None or getattr(polygon, "is_empty", True):
        vertices = tuple(getattr(getattr(region, "region", None), "vertices", ()) or ())
        polygon = Polygon(vertices) if len(vertices) >= 3 else None
    return _valid_polygon_or_none(polygon)


def _editable_region_polygon(region: "EditableHatchRegion") -> Polygon | None:
    points = tuple(getattr(region, "polygon_xy", ()) or ())
    return _valid_polygon_or_none(Polygon(points) if len(points) >= 3 else None)


def _valid_polygon_or_none(polygon) -> Polygon | None:
    if polygon is None:
        return None
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.area <= 1.0e-12 or polygon.geom_type != "Polygon":
        return None
    return polygon


def _region_outside_allowed_story_polygons(
    region: "LoadRegion",
    story_name: str,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None,
    *,
    min_area_ratio: float = 0.98,
) -> bool:
    return _allowed_story_region_problem(
        region,
        story_name,
        allowed_story_polygons_by_name,
        min_area_ratio=min_area_ratio,
    ) is not None


def _allowed_story_region_problem(
    region: "LoadRegion",
    story_name: str,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None,
    *,
    min_area_ratio: float = 0.98,
) -> str | None:
    return _allowed_story_region_check(
        region,
        story_name,
        allowed_story_polygons_by_name,
        min_area_ratio=min_area_ratio,
    ).status


def check_polygon_against_allowed_story_polygons(
    polygon,
    story_name: str,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None,
    *,
    snap_tolerance: float = 0.0,
    min_area_ratio: float = 0.98,
) -> AllowedStoryRegionCheck:
    raw_polygon = _valid_polygon_or_none(polygon)
    return _allowed_story_region_check_for_polygons(
        raw_polygon=raw_polygon,
        snapped_polygon=None,
        story_name=story_name,
        allowed_story_polygons_by_name=allowed_story_polygons_by_name,
        snap_node_ids=(),
        snap_max_error=None,
        snap_tolerance=snap_tolerance,
        min_area_ratio=min_area_ratio,
    )


def _allowed_story_region_check(
    region: "LoadRegion",
    story_name: str,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None,
    *,
    snapped_points: Sequence[tuple[float, float]] = (),
    snap_node_ids: Sequence[int] = (),
    snap_max_error: float | None = None,
    snap_tolerance: float = 0.0,
    min_area_ratio: float = 0.98,
) -> AllowedStoryRegionCheck:
    raw_polygon = _load_region_polygon(region)
    snapped_polygon = _valid_polygon_or_none(Polygon(snapped_points) if len(tuple(snapped_points or ())) >= 3 else None)
    return _allowed_story_region_check_for_polygons(
        raw_polygon=raw_polygon,
        snapped_polygon=snapped_polygon,
        story_name=story_name,
        allowed_story_polygons_by_name=allowed_story_polygons_by_name,
        snap_node_ids=snap_node_ids,
        snap_max_error=snap_max_error,
        snap_tolerance=snap_tolerance,
        min_area_ratio=min_area_ratio,
    )


def _allowed_story_region_check_for_polygons(
    *,
    raw_polygon,
    snapped_polygon,
    story_name: str,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None,
    snap_node_ids: Sequence[int],
    snap_max_error: float | None,
    snap_tolerance: float,
    min_area_ratio: float,
) -> AllowedStoryRegionCheck:
    data = {
        "allowed_check_mode": "NOT_APPLIED",
        "allowed_check_tolerance": 0.0,
        "raw_polygon_bbox": _bbox_for_audit(raw_polygon),
        "snapped_polygon_bbox": _bbox_for_audit(snapped_polygon),
        "allowed_union_bbox": (),
        "outside_area": "",
        "outside_area_ratio": "",
        "intersection_area_ratio": "",
        "matched_allowed_polygon_count": 0,
        "snap_node_ids": tuple(int(value) for value in tuple(snap_node_ids or ())),
        "snap_max_error": snap_max_error,
    }
    if not story_name or allowed_story_polygons_by_name is None:
        return AllowedStoryRegionCheck(None, data)
    story_key = str(story_name)
    if story_key not in allowed_story_polygons_by_name:
        data["allowed_check_mode"] = "MISSING"
        return AllowedStoryRegionCheck(BELOW_ALLOWED_REGION_MISSING, data)
    allowed_polygons = [
        valid
        for polygon in allowed_story_polygons_by_name.get(story_key, ()) or ()
        if (valid := _valid_polygon_or_none(polygon)) is not None
    ]
    if not allowed_polygons:
        data["allowed_check_mode"] = "MISSING"
        return AllowedStoryRegionCheck(BELOW_ALLOWED_REGION_MISSING, data)
    if raw_polygon is None:
        data["allowed_check_mode"] = "RAW"
        return AllowedStoryRegionCheck(BELOW_ALLOWED_REGION_MISMATCH, data)
    allowed_union = _valid_area_geometry_or_none(unary_union(allowed_polygons))
    if allowed_union is None:
        data["allowed_check_mode"] = "MISSING"
        return AllowedStoryRegionCheck(BELOW_ALLOWED_REGION_MISSING, data)
    data["allowed_union_bbox"] = _bbox_for_audit(allowed_union)
    required_ratio = max(0.0, min(float(min_area_ratio), 1.0))

    raw_metrics = _allowed_region_metrics(raw_polygon, allowed_union, allowed_polygons)
    data.update(raw_metrics)
    if _allowed_region_metrics_pass(raw_metrics, required_ratio):
        data["allowed_check_mode"] = "RAW"
        return AllowedStoryRegionCheck(None, data)

    snap_error = float(snap_max_error) if snap_max_error is not None and math.isfinite(float(snap_max_error)) else math.inf
    snap_limit = max(float(snap_tolerance or 0.0), 0.0)
    snap_is_trusted = snapped_polygon is not None and (snap_limit <= 0.0 or snap_error <= snap_limit + 1.0e-9)
    if snap_is_trusted:
        snapped_metrics = _allowed_region_metrics(snapped_polygon, allowed_union, allowed_polygons)
        if _allowed_region_metrics_pass(snapped_metrics, required_ratio):
            data.update(snapped_metrics)
            data["allowed_check_mode"] = "SNAP_TOLERANT"
            return AllowedStoryRegionCheck(None, data)

    tolerance = _allowed_region_buffer_tolerance(raw_polygon, snapped_polygon, snap_error, snap_limit)
    data["allowed_check_tolerance"] = tolerance
    if snap_is_trusted and tolerance > 0.0:
        try:
            buffered_union = allowed_union.buffer(tolerance)
        except Exception:
            buffered_union = None
            buffered_union = _valid_area_geometry_or_none(buffered_union)
        if buffered_union is not None:
            buffered_metrics = _allowed_region_metrics(snapped_polygon or raw_polygon, buffered_union, allowed_polygons)
            if _allowed_region_metrics_pass(buffered_metrics, required_ratio):
                data.update(buffered_metrics)
                data["allowed_union_bbox"] = _bbox_for_audit(allowed_union)
                data["allowed_check_mode"] = "BUFFERED"
                return AllowedStoryRegionCheck(None, data)

    if snap_is_trusted and snapped_polygon is not None:
        data.update(_allowed_region_metrics(snapped_polygon, allowed_union, allowed_polygons))
        data["allowed_check_mode"] = "SNAP_TOLERANT"
    else:
        data["allowed_check_mode"] = "RAW"
    return AllowedStoryRegionCheck(BELOW_ALLOWED_REGION_MISMATCH, data)


def _allowed_region_metrics(subject, allowed_union, allowed_polygons: Sequence[Polygon]) -> dict:
    try:
        intersection_area = float(subject.intersection(allowed_union).area)
        outside_area = max(float(subject.difference(allowed_union).area), 0.0)
        subject_area = max(float(subject.area), 1.0e-12)
        matched = sum(1 for polygon in allowed_polygons if float(subject.intersection(polygon).area) > subject_area * 1.0e-9)
        centroid_covered = bool(allowed_union.covers(subject.centroid))
    except Exception:
        intersection_area = 0.0
        outside_area = float(getattr(subject, "area", 0.0) or 0.0)
        subject_area = max(float(getattr(subject, "area", 0.0) or 0.0), 1.0e-12)
        matched = 0
        centroid_covered = False
    return {
        "outside_area": outside_area,
        "outside_area_ratio": outside_area / subject_area,
        "intersection_area_ratio": intersection_area / subject_area,
        "matched_allowed_polygon_count": matched,
        "allowed_centroid_covered": centroid_covered,
    }


def _allowed_region_metrics_pass(metrics: dict, required_ratio: float) -> bool:
    return bool(metrics.get("allowed_centroid_covered")) and float(metrics.get("intersection_area_ratio") or 0.0) >= required_ratio


def _allowed_region_buffer_tolerance(raw_polygon, snapped_polygon, snap_error: float, snap_tolerance: float) -> float:
    polygon = snapped_polygon or raw_polygon
    if polygon is None:
        return 0.0
    min_x, min_y, max_x, max_y = [float(value) for value in polygon.bounds]
    diagonal = max(math.hypot(max_x - min_x, max_y - min_y), 1.0e-9)
    if not math.isfinite(snap_error):
        snap_error = 0.0
    base = max(float(snap_tolerance or 0.0), float(snap_error or 0.0))
    # Keep the buffer tied to snap tolerance and local polygon size so it absorbs node snapping drift
    # without turning clearly outside regions into valid FLOORLOAD input areas.
    return _clamp(base * 1.25, 0.0, diagonal * 0.05)


def _bbox_for_audit(polygon) -> tuple[float, float, float, float]:
    if polygon is None:
        return ()
    try:
        return tuple(float(value) for value in polygon.bounds)
    except Exception:
        return ()


def _valid_area_geometry_or_none(geometry):
    if geometry is None:
        return None
    if not geometry.is_valid:
        geometry = geometry.buffer(0)
    if geometry.is_empty or float(getattr(geometry, "area", 0.0) or 0.0) <= 1.0e-12:
        return None
    return geometry


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(value), float(maximum)))


def _allowed_story_region_warning(status: str) -> str:
    if status == BELOW_ALLOWED_REGION_MISSING:
        return BELOW_ALLOWED_REGION_MISSING_WARNING
    return BELOW_ALLOWED_REGION_WARNING


def _polygons_are_duplicate(left: Polygon, right: Polygon, *, iou_threshold: float) -> bool:
    union_area = float(left.union(right).area)
    if union_area <= 1.0e-12:
        return False
    iou = float(left.intersection(right).area) / union_area
    if iou >= float(iou_threshold):
        return True
    reference_area = max(float(left.area), float(right.area), 1.0e-12)
    return float(left.symmetric_difference(right).area) / reference_area <= 0.02


def expand_floorload_assignment_to_stories(
    assignment: FloorLoadAssignment,
    *,
    target_story_names: Sequence[str],
    story_nodes_by_name: dict[str, Sequence[Node]],
    polygon_xy: Sequence[tuple[float, float]] | None = None,
    snap_tolerance: float = 0.5,
    one_way_shape_tolerance: float = 1.0e-8,
) -> list[FloorLoadAssignment]:
    """Clone one DXF hatch assignment into separate target-story FLOORLOAD assignments."""

    vertices = tuple((float(x), float(y)) for x, y in (polygon_xy or assignment.polygon_vertices or ()))
    expanded: list[FloorLoadAssignment] = []
    for story_name in target_story_names:
        expanded.append(
            expand_floorload_assignment_to_story(
                assignment,
                target_story_name=str(story_name),
                target_story_nodes=story_nodes_by_name.get(str(story_name), ()),
                polygon_xy=vertices,
                snap_tolerance=snap_tolerance,
                one_way_shape_tolerance=one_way_shape_tolerance,
            )
        )
    return expanded


def expand_floorload_assignment_to_story(
    assignment: FloorLoadAssignment,
    *,
    target_story_name: str,
    target_story_nodes: Sequence[Node],
    polygon_xy: Sequence[tuple[float, float]] | None = None,
    snap_tolerance: float = 0.5,
    one_way_shape_tolerance: float = 1.0e-8,
) -> FloorLoadAssignment:
    vertices = tuple((float(x), float(y)) for x, y in (polygon_xy or assignment.polygon_vertices or ()))
    warnings = list(assignment.warnings)
    if not vertices:
        warnings.append("CONTINUOUS_STORY_APPLY_NO_POLYGON")
        return replace(
            assignment,
            story_name=str(target_story_name),
            node_ids=tuple(),
            status="CONTINUOUS_STORY_APPLY_NO_POLYGON",
            warnings=tuple(warnings),
            source_id=_continuous_source_id(assignment, target_story_name),
            snap_max_error=math.inf,
            polygon_vertices=vertices,
        )
    if not target_story_nodes:
        warnings.append("CONTINUOUS_STORY_TARGET_NODES_MISSING")
        return replace(
            assignment,
            story_name=str(target_story_name),
            node_ids=tuple(),
            status="STORY_NODE_SET_MISSING",
            warnings=tuple(warnings),
            source_id=_continuous_source_id(assignment, target_story_name),
            snap_max_error=math.inf,
            polygon_vertices=vertices,
        )

    raw_node_ids, max_error = _snap_polygon_vertices_to_nodes(vertices, target_story_nodes)
    node_lookup = {node.node_id: node for node in target_story_nodes}
    simplify_tolerance = (
        max(abs(float(one_way_shape_tolerance)), 1.0e-12)
        if int(assignment.effective_idist or 2) == 1
        else None
    )
    node_ids = _simplify_collinear_node_ids(raw_node_ids, node_lookup, tolerance=simplify_tolerance)
    status = assignment.status
    if len(node_ids) < 3:
        status = ERROR_TOO_FEW_NODES
        warnings.append("CONTINUOUS_STORY_TOO_FEW_BOUNDARY_NODES")
    elif max_error > float(snap_tolerance):
        status = SNAP_ERROR_EXCEEDED
        warnings.append(f"CONTINUOUS_STORY_SNAP_ERROR={max_error:.6g}>{float(snap_tolerance):.6g}")
    elif status not in {"OK", _review_status(tuple(warnings))} and not _is_assignment_recordable(assignment):
        status = assignment.status
    else:
        status = "OK" if not warnings else _review_status(tuple(warnings))

    one_way_mgt_angle, one_way_first_edge_angle, one_way_orientation = _one_way_mgt_debug_fields(
        effective_idist=assignment.effective_idist,
        global_flow_angle_deg=assignment.one_way_angle_deg,
        node_ids=node_ids,
        node_lookup=node_lookup,
    )
    return replace(
        assignment,
        story_name=str(target_story_name),
        node_ids=tuple(node_ids),
        status=status,
        warnings=tuple(warnings),
        source_id=_continuous_source_id(assignment, target_story_name),
        one_way_mgt_angle_deg=one_way_mgt_angle,
        one_way_first_edge_angle_deg=one_way_first_edge_angle,
        one_way_polygon_orientation=one_way_orientation,
        snap_after_transform=max_error,
        snap_max_error=max_error,
        snap_node_count_raw=len(raw_node_ids),
        snap_node_count_simplified=len(node_ids),
        node_simplified=tuple(raw_node_ids) != tuple(node_ids),
        polygon_vertices=vertices,
    )


def _continuous_source_id(assignment: FloorLoadAssignment, target_story_name: str) -> str:
    base = str(assignment.source_id or f"{assignment.source_layer}:{assignment.polygon_index}" or "continuous")
    return f"{base}@{target_story_name}"


def merge_adjacent_floorload_assignments(
    assignments: Sequence[FloorLoadAssignment],
    *,
    story_nodes: Sequence[Node],
    story_nodes_by_name: dict[str, Sequence[Node]] | None = None,
    snap_tolerance: float = 0.5,
    merge_tolerance: float | None = None,
    one_way_shape_tolerance: float = 1.0e-8,
    capabilities: MgtImportCapabilities | None = None,
) -> list[FloorLoadAssignment]:
    items = list(assignments)
    if len(items) <= 1:
        return items

    groups: dict[tuple, list[tuple[int, FloorLoadAssignment]]] = defaultdict(list)
    replacements: dict[int, list[FloorLoadAssignment]] = {}
    skip_indices: set[int] = set()

    for index, item in enumerate(items):
        if not _is_assignment_recordable(item):
            replacements[index] = [item]
            continue
        groups[_assignment_merge_key(item)].append((index, item))

    merge_index = 1
    for group in groups.values():
        if len(group) == 1:
            index, item = group[0]
            replacements[index] = [item]
            continue

        components = _assignment_connected_components(group, merge_tolerance=merge_tolerance)
        for component in components:
            first_index = min(index for index, _item in component)
            for index, _item in component:
                if index != first_index:
                    skip_indices.add(index)
            if len(component) == 1:
                replacements[first_index] = [component[0][1]]
                continue

            merged = _merge_assignment_component_with_capability_partition(
                component,
                story_nodes=story_nodes,
                story_nodes_by_name=story_nodes_by_name,
                snap_tolerance=snap_tolerance,
                merge_group_id=f"MERGE-{merge_index}",
                one_way_shape_tolerance=one_way_shape_tolerance,
                capabilities=capabilities,
            )
            if len(merged) == 1 and merged[0] is not component[0][1]:
                merge_index += 1
            replacements[first_index] = merged

    result: list[FloorLoadAssignment] = []
    for index, item in enumerate(items):
        if index in skip_indices:
            continue
        result.extend(replacements.get(index, [item]))
    return result


def _merge_assignment_component_with_capability_partition(
    component: Sequence[tuple[int, FloorLoadAssignment]],
    *,
    story_nodes: Sequence[Node],
    story_nodes_by_name: dict[str, Sequence[Node]] | None,
    snap_tolerance: float,
    merge_group_id: str,
    one_way_shape_tolerance: float,
    capabilities: MgtImportCapabilities | None,
) -> list[FloorLoadAssignment]:
    merged = _merge_assignment_component(
        component,
        story_nodes=story_nodes,
        story_nodes_by_name=story_nodes_by_name,
        snap_tolerance=snap_tolerance,
        merge_group_id=merge_group_id,
        one_way_shape_tolerance=one_way_shape_tolerance,
    )
    if capabilities is None or len(merged) != 1:
        return merged
    merged_item = merged[0]
    node_limit = floorload_node_limit(capabilities, int(merged_item.effective_idist or 2))
    if node_limit is None or len(merged_item.node_ids) <= node_limit:
        return merged

    # A connected component may be too large for one logical MIDAS record even
    # though every physical continuation line is short. Rebuild it from its
    # source assignments and greedily keep only geometry-valid unions that fit.
    remaining = list(component)
    partitions: list[list[tuple[int, FloorLoadAssignment]]] = []
    while remaining:
        group = [remaining.pop(0)]
        while remaining:
            candidates: list[tuple[int, int, FloorLoadAssignment]] = []
            for position, candidate in enumerate(remaining):
                trial_group = [*group, candidate]
                trial = _merge_assignment_component(
                    trial_group,
                    story_nodes=story_nodes,
                    story_nodes_by_name=story_nodes_by_name,
                    snap_tolerance=snap_tolerance,
                    merge_group_id=f"{merge_group_id}-P{len(partitions) + 1}",
                    one_way_shape_tolerance=one_way_shape_tolerance,
                )
                if len(trial) != 1:
                    continue
                trial_limit = floorload_node_limit(capabilities, int(trial[0].effective_idist or 2))
                if trial_limit is not None and len(trial[0].node_ids) > trial_limit:
                    continue
                candidates.append((len(trial[0].node_ids), position, trial[0]))
            if not candidates:
                break
            _node_count, position, _trial_item = min(candidates, key=lambda value: (value[0], value[1]))
            group.append(remaining.pop(position))
        partitions.append(group)

    result: list[FloorLoadAssignment] = []
    for partition_index, partition in enumerate(partitions, start=1):
        if len(partition) == 1:
            result.append(partition[0][1])
            continue
        partition_merged = _merge_assignment_component(
            partition,
            story_nodes=story_nodes,
            story_nodes_by_name=story_nodes_by_name,
            snap_tolerance=snap_tolerance,
            merge_group_id=f"{merge_group_id}-P{partition_index}",
            one_way_shape_tolerance=one_way_shape_tolerance,
        )
        if len(partition_merged) == 1:
            item = partition_merged[0]
            warnings = _unique_strings([*item.warnings, MERGE_PARTITIONED_LOGICAL_FIELD_LIMIT])
            result.append(replace(item, warnings=tuple(warnings)))
        else:
            result.extend(partition_merged)
    return result


def _assignment_merge_key(item: FloorLoadAssignment) -> tuple:
    angle_key = None
    if int(item.effective_idist or 2) == 1:
        angle = item.one_way_angle_deg
        angle_key = None if angle is None else round(float(angle) % 180.0, 6)
    return (
        str(item.story_name or ""),
        str(item.load_type_name or "").strip(),
        round(float(item.dl), 8),
        round(float(item.ll), 8),
        str(item.distribution or ""),
        int(item.effective_idist or 2),
        bool(item.allow_polygon_type),
        angle_key,
    )


def _assignment_connected_components(
    group: Sequence[tuple[int, FloorLoadAssignment]],
    *,
    merge_tolerance: float | None,
) -> list[list[tuple[int, FloorLoadAssignment]]]:
    polygons = [_polygon_from_assignment(item) for _index, item in group]
    count = len(group)
    adjacency = [set() for _ in range(count)]
    for left in range(count):
        poly_left = polygons[left]
        if poly_left is None:
            continue
        for right in range(left + 1, count):
            poly_right = polygons[right]
            if poly_right is None:
                continue
            if _polygons_are_merge_adjacent(poly_left, poly_right, merge_tolerance=merge_tolerance):
                adjacency[left].add(right)
                adjacency[right].add(left)

    components: list[list[tuple[int, FloorLoadAssignment]]] = []
    seen: set[int] = set()
    for start in range(count):
        if start in seen:
            continue
        stack = [start]
        seen.add(start)
        component_indices = []
        while stack:
            current = stack.pop()
            component_indices.append(current)
            for nxt in adjacency[current]:
                if nxt in seen:
                    continue
                seen.add(nxt)
                stack.append(nxt)
        component_indices.sort(key=lambda value: group[value][0])
        components.append([group[index] for index in component_indices])
    components.sort(key=lambda component: min(index for index, _item in component))
    return components


def _merge_assignment_component(
    component: Sequence[tuple[int, FloorLoadAssignment]],
    *,
    story_nodes: Sequence[Node],
    story_nodes_by_name: dict[str, Sequence[Node]] | None,
    snap_tolerance: float,
    merge_group_id: str,
    one_way_shape_tolerance: float = 1.0e-8,
) -> list[FloorLoadAssignment]:
    items = [item for _index, item in component]
    polygons = [_polygon_from_assignment(item) for item in items]
    if any(poly is None for poly in polygons):
        return items

    merged_geom = unary_union([poly for poly in polygons if poly is not None])
    polygons_to_write = _polygons_from_union_geometry(merged_geom)
    if len(polygons_to_write) != 1:
        return items

    merged_polygon = polygons_to_write[0]
    if merged_polygon.is_empty or merged_polygon.area <= 1.0e-12 or len(merged_polygon.interiors) > 0:
        return items

    first = items[0]
    nodes_for_story = _nodes_for_assignment(first, story_nodes=story_nodes, story_nodes_by_name=story_nodes_by_name)
    if not nodes_for_story:
        return items
    node_lookup = {node.node_id: node for node in nodes_for_story}
    raw_node_ids, max_error = _node_ids_from_merged_polygon(merged_polygon, nodes_for_story=nodes_for_story)
    simplify_tolerance = (
        max(abs(float(one_way_shape_tolerance)), 1.0e-12)
        if int(first.effective_idist or 2) == 1
        else None
    )
    node_ids = _simplify_collinear_node_ids(raw_node_ids, node_lookup, tolerance=simplify_tolerance)

    if len(node_ids) < 3:
        return _items_with_merge_warning(items, MERGE_SKIPPED_TOO_FEW_NODES)
    if max_error > snap_tolerance:
        return _items_with_merge_warning(items, MERGE_SKIPPED_SNAP_ERROR)
    if int(first.effective_idist or 2) == 1 and len(node_ids) not in {3, 4}:
        return _items_with_merge_warning(items, MERGE_SKIPPED_ONE_WAY_POLYGON_NODE_LIMIT)

    warnings = _unique_strings([warning for item in items for warning in item.warnings])
    warnings.append(f"{MERGED_FLOORLOAD_REGIONS}: {len(items)} regions")
    source_ids = tuple(str(item.source_id or "") for item in items if str(item.source_id or ""))
    direction_source_ids = _unique_strings(
        [source_id for item in items for source_id in str(item.direction_marker_source_id or "").split(",") if source_id]
    )
    bounds = tuple(float(value) for value in merged_polygon.bounds)
    exterior = _polygon_exterior_vertices(merged_polygon)
    status = "OK" if all(item.status == "OK" for item in items) else _review_status(warnings)
    one_way_mgt_angle = first.one_way_mgt_angle_deg
    one_way_first_edge_angle = first.one_way_first_edge_angle_deg
    one_way_orientation = first.one_way_polygon_orientation
    if int(first.effective_idist or 2) == 1:
        one_way_mgt_angle, one_way_first_edge_angle, one_way_orientation = _one_way_mgt_debug_fields(
            effective_idist=first.effective_idist,
            global_flow_angle_deg=first.one_way_angle_deg,
            node_ids=node_ids,
            node_lookup=node_lookup,
        )

    return [
        replace(
            first,
            node_ids=tuple(node_ids),
            source_layer=first.source_layer,
            source_type="MERGED_HATCH",
            area=float(merged_polygon.area),
            status=status,
            warnings=tuple(warnings),
            one_way_mgt_angle_deg=one_way_mgt_angle,
            one_way_first_edge_angle_deg=one_way_first_edge_angle,
            one_way_polygon_orientation=one_way_orientation,
            source_id=" | ".join(source_ids),
            polygon_index=0,
            direction_marker_source_id=",".join(direction_source_ids),
            direction_marker_count=sum(item.direction_marker_count for item in items),
            direction_marker_match_methods=tuple(
                _unique_strings([method for item in items for method in item.direction_marker_match_methods])
            ),
            source_bbox=bounds,
            model_bbox=bounds,
            snap_max_error=max_error,
            snap_node_count_raw=len(raw_node_ids),
            snap_node_count_simplified=len(node_ids),
            node_simplified=tuple(raw_node_ids) != tuple(node_ids),
            polygon_vertices=exterior,
            merge_group_id=merge_group_id,
            merged_source_count=len(items),
            merged_source_ids=source_ids,
        )
    ]


def _polygon_from_assignment(item: FloorLoadAssignment) -> Polygon | None:
    points = tuple(item.polygon_vertices or ())
    if len(points) < 3:
        return None
    polygon = Polygon(points)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.area <= 1.0e-12:
        return None
    if isinstance(polygon, Polygon):
        return polygon
    if isinstance(polygon, MultiPolygon):
        parts = [part for part in polygon.geoms if part.area > 1.0e-12]
        return max(parts, key=lambda geom: geom.area) if parts else None
    return None


def _polygons_are_merge_adjacent(left: Polygon, right: Polygon, *, merge_tolerance: float | None) -> bool:
    intersection = left.intersection(right)
    if not intersection.is_empty:
        if float(getattr(intersection, "area", 0.0) or 0.0) > 1.0e-12:
            return True
        if float(getattr(intersection, "length", 0.0) or 0.0) > 1.0e-9:
            return True
    if merge_tolerance is not None and merge_tolerance > 0:
        return left.distance(right) <= float(merge_tolerance)
    return False


def _polygons_from_union_geometry(geometry) -> list[Polygon]:
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if part.area > 1.0e-12]
    if isinstance(geometry, GeometryCollection):
        return [part for part in geometry.geoms if isinstance(part, Polygon) and part.area > 1.0e-12]
    return []


def _polygon_exterior_vertices(polygon: Polygon) -> tuple[tuple[float, float], ...]:
    coords = list(polygon.exterior.coords)
    if len(coords) > 1 and _same_xy(coords[0], coords[-1]):
        coords = coords[:-1]
    return tuple((float(x), float(y)) for x, y in coords)


def _node_ids_from_merged_polygon(
    polygon: Polygon,
    *,
    nodes_for_story: Sequence[Node],
) -> tuple[tuple[int, ...], float]:
    coords = _polygon_exterior_vertices(polygon)
    node_ids, max_error = _snap_polygon_vertices_to_nodes(coords, nodes_for_story)
    return tuple(node_ids), max_error


def _nodes_for_assignment(
    item: FloorLoadAssignment,
    *,
    story_nodes: Sequence[Node],
    story_nodes_by_name: dict[str, Sequence[Node]] | None,
) -> Sequence[Node]:
    if item.story_name and story_nodes_by_name is not None:
        return story_nodes_by_name.get(item.story_name, ())
    return story_nodes


def _items_with_merge_warning(items: Sequence[FloorLoadAssignment], warning: str) -> list[FloorLoadAssignment]:
    return [replace(item, warnings=tuple(_unique_strings([*item.warnings, warning]))) for item in items]


def _unique_strings(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "")
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _same_xy(left, right, tolerance: float = 1.0e-9) -> bool:
    return abs(float(left[0]) - float(right[0])) <= tolerance and abs(float(left[1]) - float(right[1])) <= tolerance


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


def _region_key_for_audit(region: object) -> str:
    hatch = getattr(region, "region", None)
    source_id = str(getattr(hatch, "source_id", "") or getattr(hatch, "handle", "") or "")
    story_name = str(getattr(hatch, "story_name", "") or "")
    polygon_index = int(getattr(hatch, "polygon_index", 0) or 0)
    source_type = str(getattr(hatch, "source_type", "") or "DXF")
    if source_id:
        return source_id
    return f"{source_type}|{story_name}|{getattr(hatch, 'layer', '')}|{polygon_index}"


def _assignment_source_region_key(item: FloorLoadAssignment) -> str:
    if item.source_region_key:
        return item.source_region_key
    if item.source_id:
        return str(item.source_id)
    return f"{item.source_type}|{item.story_name}|{item.source_layer}|{item.polygon_index}"


def _assignment_source_region_keys(item: FloorLoadAssignment) -> tuple[str, ...]:
    if item.merged_source_ids:
        return tuple(str(value) for value in item.merged_source_ids if str(value))
    if item.source_region_keys:
        return tuple(str(value) for value in item.source_region_keys if str(value))
    key = _assignment_source_region_key(item)
    return (key,) if key else ()


def _assignment_source_label(item: FloorLoadAssignment) -> str:
    source_type = str(item.source_type or "").upper()
    source_id = str(item.source_id or "")
    if source_type == "INTERNAL":
        return "CONTINUOUS_SYNC" if source_id.startswith("continuous:") or "@" in source_id else "INTERNAL"
    if "CONTINUOUS" in source_type or "@" in source_id:
        return "CONTINUOUS_SYNC"
    if source_type == "MERGED_HATCH":
        return "MERGED"
    return "DXF"


def _status_for_audit(item: FloorLoadAssignment) -> str:
    if _is_assignment_recordable(item):
        return "WARNING" if str(item.status or "").startswith("REVIEW") or item.warnings else "OK"
    status = str(item.status or "")
    if status.startswith("ERROR") or status in {SNAP_ERROR_EXCEEDED, ERROR_TOO_FEW_NODES, ERROR_ONE_WAY_REQUIRES_TRI_OR_QUAD}:
        return "ERROR"
    return "SKIPPED"


def _skip_reason_code(item: FloorLoadAssignment) -> str:
    if _is_assignment_recordable(item):
        return ""
    status = str(item.status or "").strip()
    return status or "FINAL_RECORD_SKIPPED"


def _skip_reason_ko(reason_code: str, warnings: Sequence[str] = ()) -> str:
    if not reason_code:
        return ""
    if reason_code in FLOORLOAD_SKIP_REASON_KO:
        return FLOORLOAD_SKIP_REASON_KO[reason_code]
    for warning in warnings or ():
        text = str(warning or "").strip()
        if text:
            return text
    return "최종 FLOORLOAD record 생성 조건을 만족하지 못했습니다."


def _assignment_pipeline_stage(item: FloorLoadAssignment) -> str:
    if _is_assignment_recordable(item):
        return "FINAL_RECORD_CREATED" if item.final_record_created else "ASSIGNMENT_CREATED"
    status = str(item.status or "")
    if status in {BELOW_ALLOWED_REGION_MISMATCH, BELOW_ALLOWED_REGION_MISSING}:
        return "BELOW_ALLOWED_REGION_CHECK"
    if status in {SNAP_ERROR_EXCEEDED, ERROR_TOO_FEW_NODES}:
        return "SNAP_TO_MODEL_NODES"
    return "FINAL_RECORD_SKIPPED"


def _with_assignment_audit_metadata(assignments: Sequence[FloorLoadAssignment]) -> list[FloorLoadAssignment]:
    result: list[FloorLoadAssignment] = []
    for index, item in enumerate(assignments, start=1):
        source_keys = _assignment_source_region_keys(item)
        source_region_key = source_keys[0] if source_keys else _assignment_source_region_key(item)
        reason_code = _skip_reason_code(item)
        result.append(
            replace(
                item,
                audit_id=item.audit_id or f"ASSIGN-{index:05d}",
                source_region_key=source_region_key,
                source_region_keys=source_keys,
                pipeline_stage=item.pipeline_stage or _assignment_pipeline_stage(item),
                skip_reason_code=reason_code,
                skip_reason_ko=_skip_reason_ko(reason_code, item.warnings),
            )
        )
    return result


def _with_final_record_metadata(assignments: Sequence[FloorLoadAssignment]) -> list[FloorLoadAssignment]:
    result: list[FloorLoadAssignment] = []
    record_index = 1
    for item in assignments:
        if _is_assignment_recordable(item):
            preview = "\n".join(_make_floorload_records([item]))
            result.append(
                replace(
                    item,
                    pipeline_stage="FINAL_RECORD_CREATED",
                    final_record_created=True,
                    final_record_index=record_index,
                    final_mgt_record_preview=preview,
                    skip_reason_code="",
                    skip_reason_ko="",
                )
            )
            record_index += 1
        else:
            reason_code = item.skip_reason_code or _skip_reason_code(item)
            result.append(
                replace(
                    item,
                    pipeline_stage="FINAL_RECORD_SKIPPED",
                    final_record_created=False,
                    final_record_index=0,
                    final_mgt_record_preview="",
                    skip_reason_code=reason_code,
                    skip_reason_ko=item.skip_reason_ko or _skip_reason_ko(reason_code, item.warnings),
                )
            )
    return result


def _assignment_audit_kwargs(item: FloorLoadAssignment) -> dict:
    allowed_data = dict(getattr(item, "allowed_region_check_data", {}) or {})
    return {
        "source": _assignment_source_label(item),
        "region_key": item.source_region_key or _assignment_source_region_key(item),
        "assignment_id": item.audit_id,
        "source_region_keys": item.source_region_keys or _assignment_source_region_keys(item),
        "story_name": item.story_name,
        "load_name": item.load_type_name,
        "dl": float(item.dl),
        "ll": float(item.ll),
        "distribution": item.distribution,
        "one_way_angle": item.one_way_angle_deg,
        "area": float(item.area),
        "polygon_vertex_count": len(tuple(item.polygon_vertices or ())),
        "node_count_raw": int(item.snap_node_count_raw or len(tuple(item.node_ids or ()))),
        "node_count_simplified": int(item.snap_node_count_simplified or len(tuple(item.node_ids or ()))),
        "node_ids": tuple(int(value) for value in tuple(item.node_ids or ())),
        "merge_group_id": item.merge_group_id,
        "final_record_index": item.final_record_index or None,
        "final_mgt_record": item.final_mgt_record_preview,
        "skip_reason": item.skip_reason_ko,
        "data": {
            "status": item.status,
            "warnings": tuple(item.warnings or ()),
            "source_layer": item.source_layer,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "polygon_index": item.polygon_index,
            "snap_max_error": item.snap_max_error,
            "bAL": "YES",
            "bAL_default_applied": True,
            **allowed_data,
        },
    }


def _add_region_input_events(
    collector: FloorloadAuditCollector,
    *,
    regions: Sequence[object],
    internal_regions: Sequence[object],
) -> None:
    for region in regions or ():
        hatch = getattr(region, "region", None)
        load = getattr(region, "load", None)
        polygon_vertices = tuple(getattr(hatch, "vertices", ()) or ())
        collector.add(
            "RAW_REGION_INPUT",
            status="OK" if load is not None else "SKIPPED",
            reason_code="" if load is not None else "LOAD_PARSE_FAILED",
            message_ko="" if load is not None else _skip_reason_ko("LOAD_PARSE_FAILED"),
            source="DXF",
            region_key=_region_key_for_audit(region),
            story_name=str(getattr(hatch, "story_name", "") or ""),
            load_name=str(getattr(load, "real_name", "") or ""),
            dl=getattr(load, "dl", None),
            ll=getattr(load, "ll", None),
            distribution=str(getattr(load, "distribution", "") or ""),
            one_way_angle=getattr(load, "one_way_angle_deg", None),
            area=getattr(region, "area", None),
            polygon_vertex_count=len(polygon_vertices),
            data={"source_layer": str(getattr(hatch, "layer", "") or ""), "source_id": str(getattr(hatch, "source_id", "") or "")},
        )
    for region in internal_regions or ():
        if not str(getattr(region, "load_name", "") or ""):
            continue
        polygon_vertices = tuple(getattr(region, "polygon_xy", ()) or ())
        collector.add(
            "RAW_REGION_INPUT",
            status="OK",
            source=str(getattr(region, "source", "") or "INTERNAL"),
            region_key=str(getattr(region, "region_key", "") or ""),
            story_name=str(getattr(region, "story_name", "") or ""),
            load_name=str(getattr(region, "load_name", "") or ""),
            dl=getattr(region, "dl", None),
            ll=getattr(region, "ll", None),
            distribution=str(getattr(region, "distribution", "") or ""),
            one_way_angle=getattr(region, "one_way_angle", None),
            area=_polygon_area_from_points(polygon_vertices),
            polygon_vertex_count=len(polygon_vertices),
            data={"cell_ids": tuple(getattr(region, "cell_ids", ()) or ())},
        )


def _add_after_filter_events(
    collector: FloorloadAuditCollector,
    *,
    kept_regions: Sequence[object],
    removed_regions: Sequence[object],
) -> None:
    for region in kept_regions or ():
        hatch = getattr(region, "region", None)
        load = getattr(region, "load", None)
        polygon_vertices = tuple(getattr(hatch, "vertices", ()) or ())
        collector.add(
            "AFTER_DXF_INTERNAL_FILTER",
            status="OK",
            source="DXF",
            region_key=_region_key_for_audit(region),
            story_name=str(getattr(hatch, "story_name", "") or ""),
            load_name=str(getattr(load, "real_name", "") or ""),
            dl=getattr(load, "dl", None),
            ll=getattr(load, "ll", None),
            distribution=str(getattr(load, "distribution", "") or ""),
            one_way_angle=getattr(load, "one_way_angle_deg", None),
            area=getattr(region, "area", None),
            polygon_vertex_count=len(polygon_vertices),
            data={"result": "KEPT"},
        )
    for region in removed_regions or ():
        hatch = getattr(region, "region", None)
        load = getattr(region, "load", None)
        polygon_vertices = tuple(getattr(hatch, "vertices", ()) or ())
        collector.add(
            "AFTER_DXF_INTERNAL_FILTER",
            status="SKIPPED",
            reason_code="DUPLICATE_OVERRIDDEN_BY_INTERNAL_REGION",
            message_ko=_skip_reason_ko("DUPLICATE_OVERRIDDEN_BY_INTERNAL_REGION"),
            source="DXF",
            region_key=_region_key_for_audit(region),
            story_name=str(getattr(hatch, "story_name", "") or ""),
            load_name=str(getattr(load, "real_name", "") or ""),
            dl=getattr(load, "dl", None),
            ll=getattr(load, "ll", None),
            distribution=str(getattr(load, "distribution", "") or ""),
            one_way_angle=getattr(load, "one_way_angle_deg", None),
            area=getattr(region, "area", None),
            polygon_vertex_count=len(polygon_vertices),
            data={"result": "REMOVED"},
        )


def _audit_kwargs_with_data(item: FloorLoadAssignment, **extra_data) -> dict:
    kwargs = _assignment_audit_kwargs(item)
    data = dict(kwargs.get("data", {}) or {})
    data.update(extra_data)
    kwargs["data"] = data
    return kwargs


def _add_assignment_stage_events(
    collector: FloorloadAuditCollector,
    assignments: Sequence[FloorLoadAssignment],
    *,
    allowed_region_check_applied: bool,
) -> None:
    for item in assignments:
        status = _status_for_audit(item)
        reason_code = item.skip_reason_code or _skip_reason_code(item)
        if item.status in {BELOW_ALLOWED_REGION_MISMATCH, BELOW_ALLOWED_REGION_MISSING}:
            collector.add(
                "BELOW_ALLOWED_REGION_CHECK",
                status="SKIPPED",
                reason_code=reason_code,
                message_ko=item.skip_reason_ko or _skip_reason_ko(reason_code, item.warnings),
                **_audit_kwargs_with_data(item, allowed_region_check="SKIPPED"),
            )
            continue
        collector.add(
            "BELOW_ALLOWED_REGION_CHECK",
            status="OK",
            reason_code="",
            message_ko="",
            **_audit_kwargs_with_data(item, allowed_region_check="PASSED" if allowed_region_check_applied else "NOT_APPLIED"),
        )
        collector.add(
            "SNAP_TO_MODEL_NODES",
            status=status if status in {"ERROR", "SKIPPED"} else "OK",
            reason_code=reason_code if status in {"ERROR", "SKIPPED"} else "",
            message_ko=item.skip_reason_ko if status in {"ERROR", "SKIPPED"} else "",
            **_assignment_audit_kwargs(item),
        )
        collector.add(
            "NODE_SIMPLIFY",
            status=status if status in {"ERROR", "SKIPPED"} else "OK",
            reason_code=reason_code if status in {"ERROR", "SKIPPED"} else "",
            message_ko=item.skip_reason_ko if status in {"ERROR", "SKIPPED"} else "",
            **_assignment_audit_kwargs(item),
        )
        collector.add(
            "ASSIGNMENT_CREATED",
            status=status,
            reason_code=reason_code,
            message_ko=item.skip_reason_ko if reason_code else "",
            **_assignment_audit_kwargs(item),
        )


def _add_merge_events(collector: FloorloadAuditCollector, assignments: Sequence[FloorLoadAssignment]) -> None:
    for item in assignments:
        if not item.merge_group_id:
            continue
        collector.add(
            "MERGE_GROUP_CREATED",
            status="OK" if _is_assignment_recordable(item) else _status_for_audit(item),
            reason_code=item.skip_reason_code,
            message_ko=item.skip_reason_ko,
            **_assignment_audit_kwargs(item),
        )


def _add_final_record_events(collector: FloorloadAuditCollector, assignments: Sequence[FloorLoadAssignment]) -> None:
    for item in assignments:
        if item.final_record_created:
            collector.add(
                "FINAL_RECORD_CREATED",
                status="OK",
                reason_code="",
                message_ko="최종 FLOORLOAD record가 생성되었습니다.",
                **_assignment_audit_kwargs(item),
            )
        else:
            reason_code = item.skip_reason_code or _skip_reason_code(item)
            collector.add(
                "FINAL_RECORD_SKIPPED",
                status=_status_for_audit(item),
                reason_code=reason_code,
                message_ko=item.skip_reason_ko or _skip_reason_ko(reason_code, item.warnings),
                **_assignment_audit_kwargs(item),
            )


def _polygon_area_from_points(points: Sequence[tuple[float, float]]) -> float:
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        area += float(start[0]) * float(end[1]) - float(end[0]) * float(start[1])
    return abs(area) / 2.0


def patch_full_mgt_with_floorloads(
    *,
    source_mgt_path: str | Path,
    output_mgt_path: str | Path,
    assignments: Sequence[FloorLoadAssignment],
    mode: str = "append",
    encoding: str | None = None,
) -> Path:
    document = read_mgt_text_document(source_mgt_path, preferred_encoding=encoding)
    patched = patch_full_mgt_text(document.text, assignments=assignments, mode=mode)
    return write_mgt_text_atomic(
        output_mgt_path,
        patched,
        encoding=encoding or document.encoding,
        newline=document.newline,
        validator=_validate_patched_floorload_mgt,
    )


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
                "model_bbox": _format_bbox(item.model_bbox),
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
                "one_way_global_flow_angle": _format_optional_float(item.one_way_angle_deg),
                "one_way_mgt_angle": _format_optional_float(item.one_way_mgt_angle_deg),
                "first_edge_angle": _format_optional_float(item.one_way_first_edge_angle_deg),
                "polygon_orientation": item.one_way_polygon_orientation,
                "one_way_direction_source": item.direction_source,
                "방향 산정 방식": item.direction_source,
                "짧은 스팬 자동산정 여부": "YES" if item.direction_source.startswith("AUTO_SHORT_SPAN") else "NO",
                "방향 override 여부": "YES" if item.direction_source in {"DXF_DIRECTION_MARKER", "LAYER_ANGLE_TOKEN", "USER_DEFAULT"} else "NO",
                "방향선 source_id": item.direction_marker_source_id,
                "방향선 매칭 개수": item.direction_marker_count,
                "방향선 매칭 방식": " | ".join(item.direction_marker_match_methods),
                "audit_id": item.audit_id,
                "source_region_key": item.source_region_key,
                "source_region_keys": " | ".join(item.source_region_keys),
                "pipeline_stage": item.pipeline_stage,
                "skip_reason_code": item.skip_reason_code,
                "skip_reason_ko": item.skip_reason_ko,
                "final_record_created": "YES" if item.final_record_created else "NO",
                "final_record_index": item.final_record_index or "",
                "final_mgt_record_preview": item.final_mgt_record_preview,
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
    one_way_shape_tolerance: float = 1.0e-8,
    story_nodes_by_name: dict[str, Sequence[Node]] | None = None,
    internal_regions: Sequence['EditableHatchRegion'] = (),
    mode: str = "append",
    encoding: str | None = None,
    auto_load_dm_dummy_members: bool = False,
    story_tolerance: float = 1.0e-4,
    allowed_story_polygons_by_name: dict[str, Sequence[Polygon]] | None = None,
    approved_dummy_plans: Sequence[object] | None = None,
    mgt_import_capabilities: MgtImportCapabilities | None = None,
    capability_profile: str = "AUTO",
    gen_version: str = "",
    floorload_max_logical_fields: int | None = None,
    strict_import_verification: bool = True,
) -> BuildResult:
    source_document = read_mgt_text_document(source_mgt_path, preferred_encoding=encoding)
    source_text = source_document.text
    capabilities = mgt_import_capabilities or resolve_mgt_import_capabilities(
        profile_name=capability_profile,
        gen_version=gen_version,
        floorload_max_logical_fields=floorload_max_logical_fields,
        strict_import_verification=strict_import_verification,
        source_text=source_text,
        text_encoding=encoding or source_document.encoding,
        newline=source_document.newline,
    )
    audit_collector = FloorloadAuditCollector()
    _add_region_input_events(audit_collector, regions=tuple(regions or ()), internal_regions=tuple(internal_regions or ()))
    dxf_regions, overridden_regions = _split_dxf_regions_overridden_by_internal_regions(regions, internal_regions)
    _add_after_filter_events(audit_collector, kept_regions=dxf_regions, removed_regions=overridden_regions)
    all_regions = list(dxf_regions)
    all_regions.extend(
        editable_region_to_load_region(region)
        for region in internal_regions
        if str(getattr(region, "load_name", "") or "")
    )
    raw_assignments = build_assignments_from_regions(
        regions=all_regions,
        story_nodes=story_nodes,
        story_nodes_by_name=story_nodes_by_name,
        snap_tolerance=snap_tolerance,
        one_way_shape_tolerance=one_way_shape_tolerance,
        include_zero_load=include_zero_load,
        allowed_story_polygons_by_name=allowed_story_polygons_by_name,
    )
    raw_assignments = _with_assignment_audit_metadata(raw_assignments)
    _add_assignment_stage_events(
        audit_collector,
        raw_assignments,
        allowed_region_check_applied=allowed_story_polygons_by_name is not None,
    )
    assignments = merge_adjacent_floorload_assignments(
        raw_assignments,
        story_nodes=story_nodes,
        story_nodes_by_name=story_nodes_by_name,
        snap_tolerance=snap_tolerance,
        one_way_shape_tolerance=one_way_shape_tolerance,
        capabilities=capabilities,
    )
    assignments = _with_assignment_audit_metadata(assignments)
    _add_merge_events(audit_collector, assignments)
    assignments = _with_final_record_metadata(assignments)
    _add_final_record_events(audit_collector, assignments)
    xlsx, csv_path = write_reports(assignments=assignments, output_dir=report_dir, model_name=model_name, story=story, dxf_name=dxf_name)
    audit_json_path, audit_csv_path = write_floorload_pipeline_audit(audit_collector, report_dir)
    preview_nodes = _preview_nodes(story_nodes, story_nodes_by_name)
    preview = write_assignment_preview_dxf(assignments, preview_nodes, preview_dxf_path)
    valid_assignments = [a for a in assignments if _is_assignment_recordable(a)]
    if not valid_assignments:
        raise RuntimeError(
            "사용자 DXF에서 MGT에 입력 가능한 FLOORLOAD가 0개입니다. "
            "전층 DXF metadata 선택, Story 판정, inverse transform, snap error를 확인하세요.\n"
            f"보고서: {csv_path}\n"
            f"검증 DXF: {preview}"
        )
    dummy_summary: DummyGenerationSummary | None = None
    dummy_report_csv_path: Path | None = None
    patch_source_text = source_text
    if auto_load_dm_dummy_members:
        dummy_summary = generate_load_dm_dummy_members(
            mgt_text=source_text,
            assignments=assignments,
            approved_plans=approved_dummy_plans,
            story_tolerance=story_tolerance,
            snap_tolerance=snap_tolerance,
            enabled=True,
        )
        patch_source_text = dummy_summary.patched_text
        dummy_report_csv_path = write_dummy_member_report(
            dummy_summary,
            report_dir,
            model_name=model_name,
            story_name=story.name,
        )
    patched_text = patch_full_mgt_text(patch_source_text, assignments=assignments, mode=mode)
    allowed_changed_sections = {"NODE", "MATERIAL", "SECTION", "ELEMENT", "FRAME-RLS"} if auto_load_dm_dummy_members else set()
    preflight = validate_mgt_for_import(
        output_mgt_path,
        text=patched_text,
        capabilities=capabilities,
        original_source_text=source_text,
        story_tolerance=story_tolerance,
        allowed_changed_sections=allowed_changed_sections,
    )
    preflight_json_path, preflight_csv_path = write_validation_report(preflight, report_dir)
    full = write_mgt_text_atomic(
        output_mgt_path,
        patched_text,
        encoding=capabilities.text_encoding,
        newline=capabilities.newline,
        validator=_validate_patched_floorload_mgt,
    )
    return BuildResult(
        full_mgt_path=full,
        report_xlsx_path=xlsx,
        report_csv_path=csv_path,
        preview_dxf_path=preview,
        assignment_count=sum(1 for a in assignments if _is_assignment_recordable(a)),
        warning_count=sum(len(a.warnings) + (0 if a.status == "OK" else 1) for a in assignments),
        dummy_summary=dummy_summary,
        dummy_report_csv_path=dummy_report_csv_path,
        audit_json_path=audit_json_path,
        audit_csv_path=audit_csv_path,
        duplicate_removed_count=len(overridden_regions),
        import_preflight=preflight,
        import_preflight_json_path=preflight_json_path,
        import_preflight_csv_path=preflight_csv_path,
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


def _simplify_collinear_node_ids(
    node_ids: Sequence[int],
    node_lookup: dict[int, Node],
    *,
    tolerance: float | None = None,
) -> tuple[int, ...]:
    ids: list[int] = []
    for node_id in node_ids:
        value = int(node_id)
        if not ids or ids[-1] != value:
            ids.append(value)

    if len(ids) > 1 and ids[0] == ids[-1]:
        ids.pop()
    if len(ids) <= 3:
        return tuple(ids)

    points: list[tuple[float, float]] = []
    for node_id in ids:
        node = node_lookup.get(node_id)
        if node is None:
            return tuple(ids)
        points.append((float(node.x), float(node.y)))

    min_x = min(x for x, _y in points)
    max_x = max(x for x, _y in points)
    min_y = min(y for _x, y in points)
    max_y = max(y for _x, y in points)
    diagonal = math.hypot(max_x - min_x, max_y - min_y)
    tol = float(tolerance) if tolerance is not None else max(diagonal * 1.0e-9, 1.0e-8)

    keep_ids = list(ids)
    keep_points = list(points)
    changed = True
    while changed and len(keep_ids) > 3:
        changed = False
        next_ids: list[int] = []
        next_points: list[tuple[float, float]] = []
        count = len(keep_ids)

        for index in range(count):
            prev = keep_points[(index - 1) % count]
            cur = keep_points[index]
            nxt = keep_points[(index + 1) % count]

            prev_to_cur = (cur[0] - prev[0], cur[1] - prev[1])
            cur_to_next = (nxt[0] - cur[0], nxt[1] - cur[1])
            prev_to_next = (nxt[0] - prev[0], nxt[1] - prev[1])
            len_prev_cur = math.hypot(prev_to_cur[0], prev_to_cur[1])
            len_cur_next = math.hypot(cur_to_next[0], cur_to_next[1])
            len_prev_next = math.hypot(prev_to_next[0], prev_to_next[1])

            remove_current = False
            if len_prev_cur <= tol or len_cur_next <= tol:
                remove_current = len(keep_ids) - 1 >= 3
            elif len_prev_next > tol:
                cross = abs(prev_to_cur[0] * prev_to_next[1] - prev_to_cur[1] * prev_to_next[0])
                distance_to_line = cross / len_prev_next
                same_direction = prev_to_cur[0] * cur_to_next[0] + prev_to_cur[1] * cur_to_next[1] >= -tol * max(
                    len_prev_cur,
                    len_cur_next,
                    1.0,
                )
                remove_current = distance_to_line <= tol and same_direction and len(keep_ids) - 1 >= 3

            if remove_current:
                changed = True
                continue

            next_ids.append(keep_ids[index])
            next_points.append(cur)

        if not next_ids:
            break
        keep_ids = next_ids
        keep_points = next_points

    return tuple(keep_ids)


def _preview_nodes(story_nodes: Sequence[Node], story_nodes_by_name: dict[str, Sequence[Node]] | None) -> list[Node]:
    merged: list[Node] = []
    seen: set[int] = set()
    for node in story_nodes:
        if node.node_id in seen:
            continue
        seen.add(node.node_id)
        merged.append(node)
    for nodes in (story_nodes_by_name or {}).values():
        for node in nodes:
            if node.node_id in seen:
                continue
            seen.add(node.node_id)
            merged.append(node)
    return merged


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


def _format_floorload_record_lines(
    *,
    prefix_fields: Sequence[str],
    node_ids: Sequence[int],
    first_line_node_limit: int = 6,
    continuation_node_limit: int = 8,
) -> list[str]:
    return _wrap_mgt_continuation(
        prefix_fields=prefix_fields,
        item_fields=[str(int(node_id)) for node_id in node_ids],
        first_line_item_limit=first_line_node_limit,
        continuation_item_limit=continuation_node_limit,
    )


def _wrap_mgt_continuation(
    *,
    prefix_fields: Sequence[str],
    item_fields: Sequence[str],
    first_line_item_limit: int,
    continuation_item_limit: int,
) -> list[str]:
    items = [str(item) for item in item_fields]
    if len(items) <= first_line_item_limit:
        return ["   " + ", ".join([*prefix_fields, *items])]

    lines: list[str] = []
    first_items = items[:first_line_item_limit]
    remaining = items[first_line_item_limit:]
    lines.append("   " + ", ".join([*prefix_fields, *first_items]) + ", \\")

    while remaining:
        chunk = remaining[:continuation_item_limit]
        remaining = remaining[continuation_item_limit:]
        suffix = ", \\" if remaining else ""
        lines.append("        " + ", ".join(chunk) + suffix)

    return lines


def _make_floorload_records(assignments: Sequence[FloorLoadAssignment]) -> list[str]:
    lines: list[str] = []
    for item in assignments:
        node_ids = tuple(getattr(item, "node_ids", ()) or ())
        if not _is_assignment_recordable(item):
            continue
        ltname = str(getattr(item, "load_type_name", "") or getattr(item, "load_real_name", "") or "").strip()
        if not ltname:
            continue
        # 기존 MGT 샘플과 동일하게 Two Way(iDIST=2), GZ, bPROJ=NO, bAL=YES 형식 사용.
        idist = int(getattr(item, "effective_idist", 2) or 2)
        if idist == 1:
            angle_value = getattr(item, "one_way_mgt_angle_deg", None)
            if angle_value is None:
                angle_value = getattr(item, "one_way_angle_deg", 0.0) or 0.0
            angle = _fmt_angle(angle_value)
            prefix_fields = [_mgt_field(ltname), "1", angle, "0", "0", "0", "GZ", "NO", "", "NO", "YES", ""]
        elif idist == 3:
            prefix_fields = [_mgt_field(ltname), "3", "GZ", "NO", "", ""]
        elif idist == 4:
            prefix_fields = [_mgt_field(ltname), "4", "GZ", "NO", "", ""]
        else:
            prefix_fields = [_mgt_field(ltname), "2", "0", "0", "0", "0", "GZ", "NO", "", "NO", "YES", ""]
        lines.extend(_format_floorload_record_lines(prefix_fields=prefix_fields, node_ids=node_ids))
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
    _validate_floorload_physical_line_field_counts(
        lines,
        previous_floorload_count=previous_floorload_count if require_new_block else 0,
    )


def _validate_floorload_physical_line_field_counts(
    lines: Sequence[str],
    *,
    previous_floorload_count: int,
    max_fields_without_continuation: int = 25,
) -> None:
    for line in _new_floorload_data_lines(lines, previous_floorload_count=previous_floorload_count):
        payload = line.rstrip()
        continued = payload.endswith("\\")
        if continued:
            payload = payload[:-1].rstrip()
        field_count = len(_csv_split(payload))
        if field_count > max_fields_without_continuation and not continued:
            raise RuntimeError(
                "MGT generation error: FLOORLOAD physical line has too many comma fields without continuation."
            )


def _new_floorload_data_lines(lines: Sequence[str], *, previous_floorload_count: int) -> list[str]:
    result: list[str] = []
    floorload_index = 0
    in_new_floorload = False
    for line in lines:
        head = _section_head(line)
        if head == "*FLOORLOAD":
            floorload_index += 1
            in_new_floorload = floorload_index > previous_floorload_count
            continue
        if head:
            in_new_floorload = False
        stripped = line.lstrip()
        if in_new_floorload and stripped and not stripped.startswith(";"):
            result.append(line)
    return result


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
