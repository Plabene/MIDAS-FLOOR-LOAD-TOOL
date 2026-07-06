from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
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


MERGED_FLOORLOAD_REGIONS = "MERGED_FLOORLOAD_REGIONS"
MERGE_SKIPPED_SNAP_ERROR = "MERGE_SKIPPED_SNAP_ERROR"
MERGE_SKIPPED_TOO_FEW_NODES = "MERGE_SKIPPED_TOO_FEW_NODES"
MERGE_SKIPPED_ONE_WAY_POLYGON_NODE_LIMIT = "MERGE_SKIPPED_ONE_WAY_POLYGON_NODE_LIMIT"


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
        node_ids = _simplify_collinear_node_ids(raw_node_ids, node_lookup)
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
            )
        )
    return assignments


def merge_adjacent_floorload_assignments(
    assignments: Sequence[FloorLoadAssignment],
    *,
    story_nodes: Sequence[Node],
    story_nodes_by_name: dict[str, Sequence[Node]] | None = None,
    snap_tolerance: float = 0.5,
    merge_tolerance: float | None = None,
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

            merged = _merge_assignment_component(
                component,
                story_nodes=story_nodes,
                story_nodes_by_name=story_nodes_by_name,
                snap_tolerance=snap_tolerance,
                merge_group_id=f"MERGE-{merge_index}",
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
    node_ids = _simplify_collinear_node_ids(raw_node_ids, node_lookup)

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
    raw_assignments = build_assignments_from_regions(
        regions=regions,
        story_nodes=story_nodes,
        story_nodes_by_name=story_nodes_by_name,
        snap_tolerance=snap_tolerance,
        include_zero_load=include_zero_load,
    )
    assignments = merge_adjacent_floorload_assignments(
        raw_assignments,
        story_nodes=story_nodes,
        story_nodes_by_name=story_nodes_by_name,
        snap_tolerance=snap_tolerance,
    )
    xlsx, csv_path = write_reports(assignments=assignments, output_dir=report_dir, model_name=model_name, story=story, dxf_name=dxf_name)
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
