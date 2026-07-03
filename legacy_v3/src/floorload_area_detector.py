from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from scipy.spatial import KDTree
from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from coordinate_mapper import CoordinateMapper
from dxf_hatch_reader import HatchRegion
from mgt_model_parser import MgtNode

Point2D = tuple[float, float]


@dataclass
class FloorLoadAreaMatch:
    hatch: HatchRegion
    mapped_polygon: Polygon | None
    boundary_node_ids: list[int] = field(default_factory=list)
    inside_node_ids: list[int] = field(default_factory=list)
    boundary_node_points: list[Point2D] = field(default_factory=list)
    max_node_snap_error: float | None = None
    area_error_ratio: float | None = None
    is_valid: bool = False
    status: str = "REVIEW_REQUIRED"
    warnings: list[str] = field(default_factory=list)

    @property
    def matched_node_count(self) -> int:
        return len(self.inside_node_ids)

    @property
    def boundary_node_count(self) -> int:
        return len(self.boundary_node_ids)


def match_hatch_boundary_to_nodes(
    hatch: HatchRegion,
    floor_nodes: Sequence[MgtNode],
    mapper: CoordinateMapper | None = None,
    *,
    boundary_tolerance: float = 1.0e-6,
    snap_tolerance: float = 0.5,
    area_error_limit: float = 0.20,
    min_boundary_nodes: int = 3,
) -> FloorLoadAreaMatch:
    mapper = mapper or CoordinateMapper.identity()
    warnings = list(hatch.warnings)

    if not floor_nodes:
        return FloorLoadAreaMatch(hatch=hatch, mapped_polygon=None, status="NO_FLOOR_NODES", warnings=[*warnings, "No floor nodes were provided."])

    mapped_polygon = mapper.transform_geometry(hatch.polygon)
    if mapped_polygon.is_empty or not isinstance(mapped_polygon, Polygon):
        return FloorLoadAreaMatch(hatch=hatch, mapped_polygon=None, status="INVALID_MAPPED_POLYGON", warnings=[*warnings, "Mapped hatch polygon is empty or not polygonal."])
    if not mapped_polygon.is_valid:
        mapped_polygon = mapped_polygon.buffer(0)
    if mapped_polygon.is_empty or mapped_polygon.area <= 0:
        return FloorLoadAreaMatch(hatch=hatch, mapped_polygon=None, status="INVALID_MAPPED_POLYGON", warnings=[*warnings, "Mapped hatch polygon has zero area."])

    node_points = [(node.x, node.y) for node in floor_nodes]
    node_ids = [node.node_id for node in floor_nodes]
    tree = KDTree(node_points)

    boundary_vertices = mapper.transform_points(hatch.vertices)
    boundary_node_ids: list[int] = []
    boundary_node_points: list[Point2D] = []
    snap_errors: list[float] = []
    seen: set[int] = set()

    for vertex in boundary_vertices:
        distance, index = tree.query(vertex)
        node_id = node_ids[int(index)]
        if node_id in seen:
            continue
        seen.add(node_id)
        boundary_node_ids.append(node_id)
        boundary_node_points.append(node_points[int(index)])
        snap_errors.append(float(distance))

    search_polygon = mapped_polygon.buffer(abs(float(boundary_tolerance)))
    prepared = prep(search_polygon)
    inside_node_ids = [node.node_id for node in floor_nodes if prepared.contains(Point(node.x, node.y))]

    match = FloorLoadAreaMatch(
        hatch=hatch,
        mapped_polygon=mapped_polygon,
        boundary_node_ids=boundary_node_ids,
        inside_node_ids=inside_node_ids,
        boundary_node_points=boundary_node_points,
        max_node_snap_error=max(snap_errors) if snap_errors else None,
        warnings=warnings,
    )

    _validate_match(match, snap_tolerance=snap_tolerance, area_error_limit=area_error_limit, min_boundary_nodes=min_boundary_nodes)
    return match


def _validate_match(
    match: FloorLoadAreaMatch,
    *,
    snap_tolerance: float,
    area_error_limit: float,
    min_boundary_nodes: int,
) -> None:
    warnings = match.warnings

    if match.boundary_node_count < min_boundary_nodes:
        warnings.append("Boundary node count is below the minimum; review required. Interior nodes were not used as a fallback.")
        match.status = "BOUNDARY_NODE_COUNT_TOO_LOW"
        match.is_valid = False
        return

    if match.max_node_snap_error is None:
        warnings.append("Boundary snapping did not produce distances.")
        match.status = "NO_BOUNDARY_SNAP"
        match.is_valid = False
        return

    if match.max_node_snap_error > snap_tolerance:
        warnings.append(f"Max boundary snap error {match.max_node_snap_error:.6g} exceeds tolerance {snap_tolerance:.6g}.")
        match.status = "SNAP_ERROR_EXCEEDED"
        match.is_valid = False
        return

    node_polygon = Polygon(_close_points(match.boundary_node_points))
    if node_polygon.is_empty or node_polygon.area <= 0:
        warnings.append("Boundary node polygon area is zero.")
        match.status = "ZERO_NODE_POLYGON_AREA"
        match.is_valid = False
        return
    if not node_polygon.is_valid:
        warnings.append("Boundary node polygon is self-intersecting or invalid.")
        match.status = "INVALID_NODE_POLYGON"
        match.is_valid = False
        return

    if match.mapped_polygon is None or match.mapped_polygon.area <= 0:
        warnings.append("Mapped hatch polygon has no measurable area.")
        match.status = "INVALID_MAPPED_POLYGON"
        match.is_valid = False
        return

    match.area_error_ratio = abs(node_polygon.area - match.mapped_polygon.area) / match.mapped_polygon.area
    if match.area_error_ratio > area_error_limit:
        warnings.append(f"Area error ratio {match.area_error_ratio:.6g} exceeds limit {area_error_limit:.6g}.")
        match.status = "AREA_ERROR_EXCEEDED"
        match.is_valid = False
        return

    match.status = "OK"
    match.is_valid = True


def _close_points(points: Sequence[Point2D]) -> list[Point2D]:
    closed = list(points)
    if closed and closed[0] != closed[-1]:
        closed.append(closed[0])
    return closed