from __future__ import annotations

import csv
import json
from pathlib import Path
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence
import math
import time

from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union
from shapely.strtree import STRtree

from .mgt_parser import Element, Node, Story, load_dm_material_section_ids_from_text
from .story_view_filter import StoryBelowRange, element_is_in_story_below_range, story_below_range


BOUNDARY_LINE_TYPES = {"BEAM"}
BOUNDARY_POLYGON_TYPES = {"WALL", "PLATE", "PLANAR", "SHELL", "PLANE", "QUAD"}
EXCLUDED_ELEMENT_TYPES = {
    "COLUMN",
    "ELASTICLINK",
    "ELASTIC_LINK",
    "LINK",
    "ELINK",
    "LOADDM",
    "LOAD_DM",
    "LOAD-DM",
}
INTERSECTION_VERTEX_WITHOUT_MODEL_NODE = "INTERSECTION_VERTEX_WITHOUT_MODEL_NODE"
BOUNDARY_NODE_MAPPING_FAILED = "BOUNDARY_NODE_MAPPING_FAILED"
INCLINED_PLANE_DETECTED = "INCLINED_PLANE_DETECTED"
WALL_EDGE_LONGEST_PAIR_FALLBACK = "WALL_EDGE_LONGEST_PAIR_FALLBACK"

DIAGNOSTIC_FIELDNAMES = (
    "story_name",
    "input_element_count",
    "boundary_segment_count",
    "diagonal_segment_count",
    "polygonize_polygon_count",
    "usable_polygon_count",
    "dropped_polygon_count",
    "dropped_reason",
    "boundary_node_mapping_failed_count",
    "intersection_vertex_without_node_count",
    "invalid_polygon_count",
    "minimum_area_filtered_count",
    "elapsed_ms",
)


@dataclass(frozen=True)
class ClosedCell:
    cell_id: str
    story_name: str
    story_elevation: float
    node_ids: tuple[int, ...]
    polygon_xy: tuple[tuple[float, float], ...]
    area: float
    centroid: tuple[float, float]
    boundary_element_ids: tuple[int, ...]
    warning_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExtraBoundarySegment:
    """A UI-approved boundary edge that has not yet been committed to MGT."""

    story_name: str
    node_i: int
    node_j: int
    start_xy: tuple[float, float]
    end_xy: tuple[float, float]
    source: str = "LOAD_DM_APPROVED"
    issue_key: str = ""


def detect_closed_cells(
    *,
    stories: Sequence[Story],
    nodes: Sequence[Node],
    elements: Sequence[Element],
    story_name: str | None = None,
    story_tolerance: float = 0.01,
    xy_tolerance: float | None = None,
    minimum_cell_area: float = 0.05,
    mgt_text: str | None = None,
    elements_by_story_name: Mapping[str, Sequence[Element]] | None = None,
    diagnostics: list[dict] | None = None,
    extra_boundary_segments_by_story: Mapping[str, Sequence[ExtraBoundarySegment]] | None = None,
) -> tuple[ClosedCell, ...]:
    """Detect model-coordinate closed floor-load candidate cells per story."""

    story_names = {str(story_name)} if story_name else None
    node_by_id = {int(node.node_id): node for node in nodes}
    tol_z = max(abs(float(story_tolerance)), 1.0e-9)
    tol_xy = _effective_xy_tolerance(xy_tolerance)
    min_area = max(float(minimum_cell_area), tol_xy * tol_xy)
    excluded_mats: set[int] = set()
    excluded_props: set[int] = set()
    if mgt_text:
        mats, props = load_dm_material_section_ids_from_text(mgt_text)
        excluded_mats.update(int(value) for value in mats)
        excluded_props.update(int(value) for value in props)

    cells: list[ClosedCell] = []
    story_list = sorted(stories, key=lambda item: float(item.elevation))
    for story in story_list:
        if story_names is not None and str(story.name) not in story_names:
            continue
        below_range = story_below_range(story_list, story, tol_z)
        story_elements = elements
        if elements_by_story_name is not None:
            story_elements = elements_by_story_name.get(str(story.name), elements)
        story_cells = detect_story_closed_cells(
            story=story,
            nodes=nodes,
            elements=story_elements,
            node_by_id=node_by_id,
            excluded_material_ids=excluded_mats,
            excluded_section_ids=excluded_props,
            story_tolerance=tol_z,
            xy_tolerance=tol_xy,
            minimum_cell_area=min_area,
            story_range=below_range,
            diagnostics=diagnostics,
            extra_boundary_segments=(extra_boundary_segments_by_story or {}).get(str(story.name), ()),
        )
        cells.extend(story_cells)
    return tuple(cells)


def detect_story_closed_cells(
    *,
    story: Story,
    nodes: Sequence[Node],
    elements: Sequence[Element],
    node_by_id: dict[int, Node] | None = None,
    excluded_material_ids: Iterable[int] = (),
    excluded_section_ids: Iterable[int] = (),
    story_tolerance: float = 0.01,
    xy_tolerance: float | None = None,
    minimum_cell_area: float = 0.05,
    story_range: StoryBelowRange | None = None,
    diagnostics: list[dict] | None = None,
    extra_boundary_segments: Sequence[ExtraBoundarySegment] = (),
) -> tuple[ClosedCell, ...]:
    elements = tuple(elements or ())
    started_at = time.perf_counter()
    diag = _diagnostic_record(str(getattr(story, "name", "") or ""), len(elements))
    dropped_reasons: dict[str, int] = {}

    def drop(reason: str, count: int = 1) -> None:
        text = str(reason or "")
        if not text:
            return
        dropped_reasons[text] = dropped_reasons.get(text, 0) + max(int(count), 1)

    def finish(cells: Sequence[ClosedCell]) -> tuple[ClosedCell, ...]:
        diag["dropped_polygon_count"] = int(sum(dropped_reasons.values()))
        diag["dropped_reason"] = _format_dropped_reasons(dropped_reasons)
        diag["elapsed_ms"] = round((time.perf_counter() - started_at) * 1000.0, 3)
        if diagnostics is not None:
            diagnostics.append(dict(diag))
        return tuple(cells)

    node_lookup = node_by_id or {int(node.node_id): node for node in nodes}
    tol_z = max(abs(float(story_tolerance)), 1.0e-9)
    tol_xy = _effective_xy_tolerance(xy_tolerance)
    min_area = max(float(minimum_cell_area), tol_xy * tol_xy)
    excluded_mats = {int(value) for value in excluded_material_ids}
    excluded_props = {int(value) for value in excluded_section_ids}
    story_nodes = [node for node in nodes if abs(float(node.z) - float(story.elevation)) <= tol_z]
    story_node_ids = {int(node.node_id) for node in story_nodes}
    if len(story_node_ids) < 3:
        return finish(())
    below_range = story_range or story_below_range([story], story, tol_z)

    segments: list[tuple[int, tuple[float, float], tuple[float, float]]] = []
    snap_points = _EndpointSnapIndex(tol_xy)
    for element in elements:
        elem_type = _normal_type(getattr(element, "elem_type", ""))
        if elem_type in EXCLUDED_ELEMENT_TYPES:
            continue
        if _element_excluded_by_id(element, excluded_mats, excluded_props):
            continue
        element_nodes = [node_lookup[node_id] for node_id in getattr(element, "node_ids", ()) if node_id in node_lookup]
        if not element_is_in_story_below_range(element, node_lookup, below_range, tol_z):
            continue
        if elem_type in BOUNDARY_LINE_TYPES:
            if len(element_nodes) >= 2 and all(int(node.node_id) in story_node_ids for node in element_nodes[:2]):
                _append_segment(segments, int(element.elem_id), element_nodes[0], element_nodes[1], tol_xy, snap_points=snap_points)
            continue
        if elem_type in BOUNDARY_POLYGON_TYPES:
            if _is_inclined_plane(element_nodes, tol_z, tol_xy):
                drop(INCLINED_PLANE_DETECTED)
                continue
            fallback_reasons: list[str] = []
            wall_edge_nodes = _story_wall_edge_nodes(
                element_nodes,
                float(story.elevation),
                tol_z,
                fallback_reasons=fallback_reasons,
            )
            for reason in fallback_reasons:
                drop(reason)
            if len(wall_edge_nodes) < 2:
                continue
            for first, second in zip(wall_edge_nodes, wall_edge_nodes[1:]):
                _append_segment(segments, int(element.elem_id), first, second, tol_xy, snap_points=snap_points)

    # Approved plans participate in polygonization but never mutate the model.
    # Negative deterministic ids keep them distinguishable in diagnostics while
    # _dedupe_segments makes an already committed real member win over its virtual copy.
    for index, extra in enumerate(extra_boundary_segments or (), start=1):
        if str(extra.story_name) != str(story.name):
            continue
        if int(extra.node_i) not in story_node_ids or int(extra.node_j) not in story_node_ids:
            drop("EXTRA_BOUNDARY_NODE_INVALID")
            continue
        start = (float(extra.start_xy[0]), float(extra.start_xy[1]))
        end = (float(extra.end_xy[0]), float(extra.end_xy[1]))
        if math.hypot(end[0] - start[0], end[1] - start[1]) <= tol_xy:
            drop("EXTRA_BOUNDARY_ZERO_LENGTH")
            continue
        segments.append((-index, snap_points.snap(start), snap_points.snap(end)))

    unique_segments = _dedupe_segments(segments)
    diag["boundary_segment_count"] = len(unique_segments)
    diag["diagonal_segment_count"] = sum(
        1
        for _elem_id, start, end in unique_segments
        if abs(float(end[0]) - float(start[0])) > tol_xy and abs(float(end[1]) - float(start[1])) > tol_xy
    )
    if not unique_segments:
        return finish(())
    linework = [LineString([start, end]) for _elem_id, start, end in unique_segments if start != end]
    if not linework:
        return finish(())
    try:
        polygons = list(polygonize(unary_union(linework)))
    except Exception:
        drop("POLYGONIZE_FAILED")
        return finish(())
    diag["polygonize_polygon_count"] = len(polygons)

    usable = []
    for polygon in polygons:
        cleaned = _clean_polygon(polygon)
        if not isinstance(cleaned, Polygon) or cleaned.is_empty:
            diag["invalid_polygon_count"] = int(diag["invalid_polygon_count"]) + 1
            drop("INVALID_POLYGON")
            continue
        if float(cleaned.area) < min_area:
            diag["minimum_area_filtered_count"] = int(diag["minimum_area_filtered_count"]) + 1
            drop("MINIMUM_AREA_FILTERED")
            continue
        usable.append(cleaned)
    diag["usable_polygon_count"] = len(usable)
    usable.sort(key=lambda poly: (round(poly.centroid.y, 6), round(poly.centroid.x, 6), round(poly.area, 6)))

    cells: list[ClosedCell] = []
    seen: set[tuple[int, int, int]] = set()
    node_spatial_index = _NodeSpatialIndex(story_nodes, tol_xy)
    segment_spatial_index = _SegmentSpatialIndex(unique_segments)
    for index, polygon in enumerate(usable, start=1):
        centroid = polygon.centroid
        signature = (round(centroid.x / tol_xy), round(centroid.y / tol_xy), round(float(polygon.area) / max(tol_xy * tol_xy, 1.0e-12)))
        if signature in seen:
            drop("DUPLICATE_POLYGON")
            continue
        seen.add(signature)
        exterior = _polygon_exterior(polygon)
        node_ids, missing_points = _boundary_node_ids_and_missing(
            exterior,
            story_nodes,
            tol_xy,
            spatial_index=node_spatial_index,
        )
        if missing_points:
            diag["boundary_node_mapping_failed_count"] = int(diag["boundary_node_mapping_failed_count"]) + len(missing_points)
            intersection_missing = sum(
                1
                for point in missing_points
                if _point_on_segment_interior(point, unique_segments, tol_xy)
            )
            if intersection_missing:
                diag["intersection_vertex_without_node_count"] = int(diag["intersection_vertex_without_node_count"]) + intersection_missing
                drop(INTERSECTION_VERTEX_WITHOUT_MODEL_NODE, intersection_missing)
            else:
                drop(BOUNDARY_NODE_MAPPING_FAILED, len(missing_points))
            continue
        if len(node_ids) < 3:
            diag["boundary_node_mapping_failed_count"] = int(diag["boundary_node_mapping_failed_count"]) + 1
            drop(BOUNDARY_NODE_MAPPING_FAILED)
            continue
        boundary_element_ids = _boundary_element_ids(
            polygon,
            unique_segments,
            tol_xy,
            spatial_index=segment_spatial_index,
        )
        cells.append(
            ClosedCell(
                cell_id=f"{story.name}:CELL:{len(cells) + 1}",
                story_name=str(story.name),
                story_elevation=float(story.elevation),
                node_ids=tuple(node_ids),
                polygon_xy=tuple(exterior),
                area=float(polygon.area),
                centroid=(float(centroid.x), float(centroid.y)),
                boundary_element_ids=tuple(boundary_element_ids),
                warning_codes=(),
            )
        )
    return finish(cells)


def _append_segment(
    segments: list[tuple[int, tuple[float, float], tuple[float, float]]],
    elem_id: int,
    first: Node,
    second: Node,
    tol_xy: float,
    *,
    snap_points: list[tuple[float, float]] | _EndpointSnapIndex | None = None,
) -> None:
    start = _snap_endpoint((first.x, first.y), tol_xy, snap_points)
    end = _snap_endpoint((second.x, second.y), tol_xy, snap_points)
    if math.hypot(end[0] - start[0], end[1] - start[1]) <= tol_xy * 0.25:
        return
    segments.append((elem_id, start, end))


def _is_horizontal_at_story(nodes: Sequence[Node], story_elevation: float, tol_z: float) -> bool:
    if not nodes:
        return False
    story_z = float(story_elevation)
    tolerance = max(abs(float(tol_z)), 1.0e-9)
    return all(abs(float(node.z) - story_z) <= tolerance for node in nodes)


def _story_wall_edge_nodes(
    nodes: Sequence[Node],
    story_elevation: float,
    tol_z: float,
    *,
    fallback_reasons: list[str] | None = None,
) -> list[Node]:
    if _is_horizontal_at_story(nodes, story_elevation, tol_z):
        return []
    story_z = float(story_elevation)
    tolerance = max(abs(float(tol_z)), 1.0e-9)
    candidate_nodes: list[Node] = [
        node
        for node in nodes
        if abs(float(node.z) - story_z) <= tolerance
    ]
    edge_nodes = _unique_nodes_by_xy(candidate_nodes)
    if len(edge_nodes) <= 2:
        return edge_nodes

    ordered_edge = _ordered_story_edge_node_run(nodes, story_z, tolerance)
    if len(ordered_edge) >= 2:
        return ordered_edge

    fallback = _longest_pair_nodes(edge_nodes)
    if len(fallback) >= 2 and fallback_reasons is not None:
        fallback_reasons.append(WALL_EDGE_LONGEST_PAIR_FALLBACK)
    return fallback


def _unique_nodes_by_xy(nodes: Sequence[Node]) -> list[Node]:
    result: list[Node] = []
    seen_xy: set[tuple[float, float]] = set()
    for node in nodes:
        key = (round(float(node.x), 9), round(float(node.y), 9))
        if key in seen_xy:
            continue
        seen_xy.add(key)
        result.append(node)
    return result


def _ordered_story_edge_node_run(nodes: Sequence[Node], story_z: float, tolerance: float) -> list[Node]:
    ordered_nodes = list(nodes or ())
    count = len(ordered_nodes)
    if count < 2:
        return []
    on_story = [abs(float(node.z) - story_z) <= tolerance for node in ordered_nodes]
    if not any(on_story) or all(on_story):
        return []

    runs: list[list[int]] = []
    current: list[int] = []
    for index, is_on_story in enumerate(on_story):
        if is_on_story:
            current.append(index)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    if len(runs) > 1 and on_story[0] and on_story[-1]:
        runs[0] = runs[-1] + runs[0]
        runs.pop()

    story_node_count = len(_unique_nodes_by_xy([node for node, is_on in zip(ordered_nodes, on_story) if is_on]))
    best_run = max(runs, key=len, default=[])
    best_nodes = _unique_nodes_by_xy([ordered_nodes[index] for index in best_run])
    if len(best_nodes) >= 2 and len(best_nodes) == story_node_count:
        return best_nodes
    return []


def _longest_pair_nodes(nodes: Sequence[Node]) -> list[Node]:
    unique_nodes = _unique_nodes_by_xy(nodes)
    if len(unique_nodes) <= 2:
        return list(unique_nodes)
    best_pair: tuple[Node, Node] | None = None
    best_distance = -1.0
    for index, first in enumerate(unique_nodes[:-1]):
        for second in unique_nodes[index + 1:]:
            distance = math.hypot(float(second.x) - float(first.x), float(second.y) - float(first.y))
            if distance > best_distance:
                best_distance = distance
                best_pair = (first, second)
    return list(best_pair or ())


def _dedupe_segments(segments: Sequence[tuple[int, tuple[float, float], tuple[float, float]]]):
    by_key: dict[tuple[tuple[float, float], tuple[float, float]], tuple[int, tuple[float, float], tuple[float, float]]] = {}
    for elem_id, start, end in segments:
        key = (start, end) if start <= end else (end, start)
        by_key.setdefault(key, (elem_id, start, end))
    return tuple(by_key.values())


def _boundary_node_ids(points: Sequence[tuple[float, float]], nodes: Sequence[Node], tol_xy: float) -> list[int]:
    ids, _missing = _boundary_node_ids_and_missing(points, nodes, tol_xy)
    return ids


class _NodeSpatialIndex:
    def __init__(self, nodes: Sequence[Node], tol_xy: float):
        self.nodes = tuple(nodes or ())
        self.bucket_size = max(abs(float(tol_xy)) * 2.0, 1.0e-9)
        self.buckets: dict[tuple[int, int], list[int]] = {}
        for index, node in enumerate(self.nodes):
            self.buckets.setdefault(self._bucket(float(node.x), float(node.y)), []).append(index)

    def _bucket(self, x: float, y: float) -> tuple[int, int]:
        return (math.floor(float(x) / self.bucket_size), math.floor(float(y) / self.bucket_size))

    def candidate_indices(self, point: tuple[float, float]) -> list[int]:
        bucket_x, bucket_y = self._bucket(*point)
        candidates: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidates.extend(self.buckets.get((bucket_x + dx, bucket_y + dy), ()))
        return sorted(candidates)


def _boundary_node_ids_and_missing(
    points: Sequence[tuple[float, float]],
    nodes: Sequence[Node],
    tol_xy: float,
    *,
    spatial_index: _NodeSpatialIndex | None = None,
) -> tuple[list[int], list[tuple[float, float]]]:
    ids: list[int] = []
    missing: list[tuple[float, float]] = []
    used: set[int] = set()
    index = spatial_index or _NodeSpatialIndex(nodes, tol_xy)
    for point in points:
        best = None
        best_distance = math.inf
        for node_index in index.candidate_indices(point):
            node = index.nodes[node_index]
            if int(node.node_id) in used:
                continue
            distance = math.hypot(float(node.x) - point[0], float(node.y) - point[1])
            if distance < best_distance:
                best = node
                best_distance = distance
        if best is not None and best_distance <= tol_xy * 2.0:
            ids.append(int(best.node_id))
            used.add(int(best.node_id))
        else:
            missing.append((float(point[0]), float(point[1])))
    return ids, missing


class _SegmentSpatialIndex:
    def __init__(self, segments: Sequence[tuple[int, tuple[float, float], tuple[float, float]]]):
        self.segments = tuple(segments or ())
        self.lines = tuple(LineString([start, end]) for _elem_id, start, end in self.segments)
        self.tree = STRtree(self.lines) if self.lines else None

    def query_indices(self, geometry) -> list[int]:
        if self.tree is None:
            return []
        return sorted(int(index) for index in self.tree.query(geometry))


def _boundary_element_ids(
    polygon: Polygon,
    segments: Sequence[tuple[int, tuple[float, float], tuple[float, float]]],
    tol_xy: float,
    *,
    spatial_index: _SegmentSpatialIndex | None = None,
) -> list[int]:
    boundary = polygon.boundary.buffer(max(tol_xy * 1.5, 1.0e-9))
    index = spatial_index or _SegmentSpatialIndex(segments)
    try:
        candidate_indices = index.query_indices(boundary)
        candidate_segments = ((index.segments[item], index.lines[item]) for item in candidate_indices)
    except Exception:
        candidate_segments = (
            (segment, LineString([segment[1], segment[2]]))
            for segment in segments
        )
    ids: list[int] = []
    for (elem_id, _start, _end), line in candidate_segments:
        if boundary.intersects(line) and elem_id not in ids:
            ids.append(int(elem_id))
    return ids


def _polygon_exterior(polygon: Polygon) -> list[tuple[float, float]]:
    coords = list(polygon.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return [(float(x), float(y)) for x, y in coords]


def _clean_polygon(polygon) -> Polygon:
    if not isinstance(polygon, Polygon):
        return Polygon()
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or not isinstance(polygon, Polygon):
        return Polygon()
    return polygon


def _is_inclined_plane(nodes: Sequence[Node], tol_z: float, tol_xy: float) -> bool:
    if len(nodes) < 3:
        return False
    z_values = [float(getattr(node, "z", 0.0)) for node in nodes]
    if max(z_values) - min(z_values) <= max(abs(float(tol_z)), 1.0e-9):
        return False
    points = [(float(node.x), float(node.y), float(node.z)) for node in nodes]
    normal = _first_nonzero_normal(points, tol_xy)
    if normal is None:
        return False
    nx, ny, nz = normal
    norm = math.sqrt(nx * nx + ny * ny + nz * nz)
    if norm <= 1.0e-12:
        return False
    # Vertical walls have nearly horizontal normals, so normal z is near zero.
    return abs(nz) / norm > 0.15


def _first_nonzero_normal(points: Sequence[tuple[float, float, float]], tol_xy: float) -> tuple[float, float, float] | None:
    tol = max(float(tol_xy), 1.0e-9)
    for i in range(len(points) - 2):
        ax, ay, az = points[i]
        for j in range(i + 1, len(points) - 1):
            bx, by, bz = points[j]
            ab = (bx - ax, by - ay, bz - az)
            if math.sqrt(ab[0] * ab[0] + ab[1] * ab[1] + ab[2] * ab[2]) <= tol:
                continue
            for k in range(j + 1, len(points)):
                cx, cy, cz = points[k]
                ac = (cx - ax, cy - ay, cz - az)
                normal = (
                    ab[1] * ac[2] - ab[2] * ac[1],
                    ab[2] * ac[0] - ab[0] * ac[2],
                    ab[0] * ac[1] - ab[1] * ac[0],
                )
                if math.sqrt(normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]) > tol * tol:
                    return normal
    return None


def _element_excluded_by_id(element: Element, excluded_mats: set[int], excluded_props: set[int]) -> bool:
    mat = getattr(element, "mat", None)
    prop = getattr(element, "prop", None)
    return (mat is not None and int(mat) in excluded_mats) or (prop is not None and int(prop) in excluded_props)


def _snap_xy(point: tuple[float, float], tolerance: float) -> tuple[float, float]:
    tol = max(float(tolerance), 1.0e-9)
    return (round(float(point[0]) / tol) * tol, round(float(point[1]) / tol) * tol)


class _EndpointSnapIndex:
    def __init__(self, tolerance: float):
        self.tolerance = max(float(tolerance), 1.0e-9)
        self.points: list[tuple[float, float]] = []
        self.buckets: dict[tuple[int, int], list[int]] = {}

    def _bucket(self, point: tuple[float, float]) -> tuple[int, int]:
        return (
            math.floor(float(point[0]) / self.tolerance),
            math.floor(float(point[1]) / self.tolerance),
        )

    def snap(self, point: tuple[float, float]) -> tuple[float, float]:
        px, py = float(point[0]), float(point[1])
        bucket_x, bucket_y = self._bucket((px, py))
        candidate_indices: list[int] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                candidate_indices.extend(self.buckets.get((bucket_x + dx, bucket_y + dy), ()))
        best = None
        best_distance = math.inf
        for index in sorted(candidate_indices):
            existing = self.points[index]
            distance = math.hypot(existing[0] - px, existing[1] - py)
            if distance < best_distance:
                best = existing
                best_distance = distance
        if best is not None and best_distance <= self.tolerance:
            return best
        source_point = (px, py)
        point_index = len(self.points)
        self.points.append(source_point)
        self.buckets.setdefault(self._bucket(source_point), []).append(point_index)
        return source_point


def _snap_endpoint(
    point: tuple[float, float],
    tolerance: float,
    snap_points: list[tuple[float, float]] | _EndpointSnapIndex | None,
) -> tuple[float, float]:
    if snap_points is None:
        return (float(point[0]), float(point[1]))
    if isinstance(snap_points, _EndpointSnapIndex):
        return snap_points.snap(point)
    tol = max(float(tolerance), 1.0e-9)
    px, py = float(point[0]), float(point[1])
    best = None
    best_distance = math.inf
    for existing in snap_points:
        distance = math.hypot(float(existing[0]) - px, float(existing[1]) - py)
        if distance < best_distance:
            best = existing
            best_distance = distance
    if best is not None and best_distance <= tol:
        return best
    source_point = (px, py)
    snap_points.append(source_point)
    return source_point


def _point_on_segment_interior(
    point: tuple[float, float],
    segments: Sequence[tuple[int, tuple[float, float], tuple[float, float]]],
    tol_xy: float,
) -> bool:
    px, py = float(point[0]), float(point[1])
    tol = max(float(tol_xy), 1.0e-9) * 2.0
    for _elem_id, start, end in segments:
        ax, ay = float(start[0]), float(start[1])
        bx, by = float(end[0]), float(end[1])
        dx = bx - ax
        dy = by - ay
        length_sq = dx * dx + dy * dy
        if length_sq <= 1.0e-18:
            continue
        t = ((px - ax) * dx + (py - ay) * dy) / length_sq
        if t <= tol / max(math.sqrt(length_sq), tol) or t >= 1.0 - tol / max(math.sqrt(length_sq), tol):
            continue
        nearest_x = ax + dx * t
        nearest_y = ay + dy * t
        if math.hypot(px - nearest_x, py - nearest_y) <= tol:
            return True
    return False


def _diagnostic_record(story_name: str, input_element_count: int) -> dict:
    return {
        "story_name": str(story_name or ""),
        "input_element_count": int(input_element_count),
        "boundary_segment_count": 0,
        "diagonal_segment_count": 0,
        "polygonize_polygon_count": 0,
        "usable_polygon_count": 0,
        "dropped_polygon_count": 0,
        "dropped_reason": "",
        "boundary_node_mapping_failed_count": 0,
        "intersection_vertex_without_node_count": 0,
        "invalid_polygon_count": 0,
        "minimum_area_filtered_count": 0,
        "elapsed_ms": 0.0,
    }


def _format_dropped_reasons(reasons: Mapping[str, int]) -> str:
    return ";".join(f"{key}:{count}" for key, count in sorted(reasons.items()) if int(count) > 0)


def write_closed_region_diagnostics(rows: Sequence[Mapping[str, object]], output_dir: str | Path) -> tuple[Path, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    normalized = [dict(row) for row in rows]
    json_path = output / "hatch_closed_region_diagnostics.json"
    csv_path = output / "hatch_closed_region_diagnostics.csv"
    json_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    extra_fields = []
    for row in normalized:
        for key in row:
            if key not in DIAGNOSTIC_FIELDNAMES and key not in extra_fields:
                extra_fields.append(key)
    fieldnames = list(DIAGNOSTIC_FIELDNAMES) + extra_fields
    with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in normalized:
            writer.writerow({name: row.get(name, "") for name in fieldnames})
    return json_path, csv_path


def _normal_type(value: str) -> str:
    return str(value or "").replace(" ", "").replace("-", "_").upper()


def _effective_xy_tolerance(value: float | None) -> float:
    if value is None:
        return 0.005
    try:
        tol = abs(float(value))
    except Exception:
        return 0.005
    if tol <= 0.0:
        return 0.005
    return max(tol, 1.0e-9)
