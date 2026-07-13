from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import atan, atan2, cos, degrees, hypot, pi, radians, sin, sqrt
from pathlib import Path
from typing import Iterable, Sequence

import ezdxf
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import unary_union
from .dxf_story_layout import (
    choose_story_layout_for_polygon,
    find_layer_mapping_path,
    find_layout_metadata_path,
    read_layout_metadata,
    transform_polygon,
)
from .load_input_policy import DIRECTION_LAYERS, is_direction_layer
from .load_parser import normalize_cad_layer_name, strip_cad_work_layer_prefix

Point2D = tuple[float, float]

_TEMPLATE_REFERENCE_LAYERS = {
    "CENTERLINE_COLUMN",
    "CENTERLINE_BEAM",
    "CENTERLINE_WALL",
    "REFERENCE_GRID",
    "FLOAD_GUIDE",
    "FLOAD_HATCH_GUIDE",
    "STORY_LABEL",
    *{normalize_cad_layer_name(layer) for layer in DIRECTION_LAYERS},
    "FLOAD_DIRECTION_GUIDE",
}


@dataclass(frozen=True)
class DirectionMarker:
    source_type: str
    layer: str
    handle: str
    start: Point2D
    end: Point2D
    source_id: str = ""
    segment_index: int = 0
    parent_handle: str = ""
    match_method: str = ""

    @property
    def length(self) -> float:
        return hypot(self.end[0] - self.start[0], self.end[1] - self.start[1])


@dataclass
class HatchRegion:
    source_type: str
    layer: str
    handle: str
    vertices: list[Point2D]
    polygon: Polygon
    area: float
    bbox: tuple[float, float, float, float]
    warnings: list[str] = field(default_factory=list)
    story_name: str = ""
    source_id: str = ""
    polygon_index: int = 0
    hatch_index: int = 0
    hatch_pattern_name: str = ""
    hatch_solid_fill: int = 0
    hatch_pattern_scale: float | None = None
    layer_color: int | None = None
    entity_color: int | None = None
    display_color: str | None = None
    direction_markers: list[DirectionMarker] = field(default_factory=list)
    layout_metadata_used: bool = False
    layout_metadata_path: str = ""
    placed_vertices: list[Point2D] = field(default_factory=list)
    placed_bbox: tuple[float, ...] = field(default_factory=tuple)
    source_bbox: tuple[float, ...] = field(default_factory=tuple)
    model_bbox: tuple[float, ...] = field(default_factory=tuple)
    transform_applied: bool = False

    def to_record(self) -> dict:
        return {
            "source_type": self.source_type,
            "layer": self.layer,
            "handle": self.handle,
            "area": self.area,
            "bbox": self.bbox,
            "vertex_count": len(self.vertices),
            "warnings": list(self.warnings),
            "story_name": self.story_name,
            "source_id": self.source_id,
            "polygon_index": self.polygon_index,
            "hatch_index": self.hatch_index,
            "hatch_pattern_name": self.hatch_pattern_name,
            "hatch_solid_fill": self.hatch_solid_fill,
            "hatch_pattern_scale": self.hatch_pattern_scale,
            "layer_color": self.layer_color,
            "entity_color": self.entity_color,
            "display_color": self.display_color,
            "direction_marker_count": len(self.direction_markers),
            "direction_marker_source_ids": [marker.source_id for marker in self.direction_markers],
            "direction_marker_match_methods": [marker.match_method for marker in self.direction_markers],
            "layout_metadata_used": self.layout_metadata_used,
            "layout_metadata_path": self.layout_metadata_path,
            "placed_bbox": self.placed_bbox,
            "source_bbox": self.source_bbox,
            "model_bbox": self.model_bbox,
            "transform_applied": self.transform_applied,
        }


def read_dxf_hatches(
    dxf_path: str | Path,
    *,
    include_closed_polylines: bool = True,
    tessellation_segments: int = 16,
    min_area: float = 1.0e-9,
) -> list[HatchRegion]:
    doc = ezdxf.readfile(str(dxf_path))
    regions: list[HatchRegion] = []
    direction_markers = _read_direction_markers(doc.modelspace())

    hatch_index = 0
    for entity in doc.modelspace():
        dxftype = entity.dxftype()
        if dxftype == "HATCH":
            if _is_template_reference_layer(entity.dxf.layer):
                continue
            hatch_index += 1
            hatch_regions = _regions_from_hatch(entity, tessellation_segments, min_area, hatch_index)
            for region in hatch_regions:
                _apply_color_info(region, entity, doc)
            regions.extend(hatch_regions)
        elif include_closed_polylines and dxftype in {"LWPOLYLINE", "POLYLINE"}:
            if _is_template_reference_layer(entity.dxf.layer):
                continue
            region = _region_from_closed_polyline(entity, tessellation_segments, min_area)
            if region is not None:
                _apply_color_info(region, entity, doc)
                regions.append(region)

    if direction_markers:
        regions = [_with_direction_markers(region, direction_markers) for region in regions]
    return regions


def _read_direction_markers(msp) -> list[DirectionMarker]:
    markers: list[DirectionMarker] = []
    for entity in msp:
        layer = str(entity.dxf.layer)
        if not is_direction_layer(layer):
            continue
        markers.extend(_direction_markers_from_entity(entity))
    return markers


def _is_template_reference_layer(layer: object) -> bool:
    normalized = normalize_cad_layer_name(str(layer or ""))
    return normalized in _TEMPLATE_REFERENCE_LAYERS or is_direction_layer(str(layer or ""))


def _direction_markers_from_entity(entity) -> list[DirectionMarker]:
    dxftype = entity.dxftype()
    handle = str(entity.dxf.handle)
    layer = str(entity.dxf.layer)
    if dxftype == "LINE":
        return [
            DirectionMarker(
                source_type=dxftype,
                layer=layer,
                handle=handle,
                start=_xy(entity.dxf.start),
                end=_xy(entity.dxf.end),
                source_id=handle,
                parent_handle=handle,
            )
        ]
    if dxftype == "LWPOLYLINE":
        points = [(float(x), float(y)) for x, y, *_rest in entity.get_points("xy")]
    elif dxftype == "POLYLINE":
        points = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
    else:
        return []
    points = _transform_entity_ocs_points(entity, points)

    markers: list[DirectionMarker] = []
    for index in range(len(points) - 1):
        markers.append(
            DirectionMarker(
                source_type=dxftype,
                layer=layer,
                handle=handle,
                start=points[index],
                end=points[index + 1],
                source_id=f"{handle}:SEG{index + 1}",
                segment_index=index + 1,
                parent_handle=handle,
            )
        )
    return markers


def _direction_marker_from_entity(entity) -> DirectionMarker | None:
    markers = _direction_markers_from_entity(entity)
    return markers[0] if markers else None


def _with_direction_markers(region: HatchRegion, markers: Sequence[DirectionMarker]) -> HatchRegion:
    matched = []
    for marker in markers:
        method = _direction_marker_match_method(marker, region.polygon)
        if method:
            matched.append(replace(marker, match_method=method))
    if not matched:
        return region
    return replace(region, direction_markers=matched)


def _direction_marker_matches_polygon(marker: DirectionMarker, polygon: Polygon) -> bool:
    return _direction_marker_match_method(marker, polygon) is not None


def _direction_marker_match_method(marker: DirectionMarker, polygon: Polygon) -> str | None:
    if polygon is None or polygon.is_empty:
        return None
    if marker.length <= 1.0e-12:
        return None
    line = LineString([marker.start, marker.end])
    if line.length <= 1.0e-12:
        return None
    midpoint = Point((marker.start[0] + marker.end[0]) / 2.0, (marker.start[1] + marker.end[1]) / 2.0)
    start = Point(marker.start)
    end = Point(marker.end)
    if polygon.covers(midpoint):
        return "MIDPOINT_INSIDE"
    if polygon.covers(start) or polygon.covers(end):
        return "ENDPOINT_INSIDE"
    if line.crosses(polygon) or line.within(polygon) or line.intersects(polygon):
        return "INTERSECT"
    min_x, min_y, max_x, max_y = polygon.bounds
    diagonal = max(hypot(max_x - min_x, max_y - min_y), 1.0)
    if line.buffer(diagonal * 1.0e-9).intersects(polygon):
        return "BUFFER_INTERSECT"
    return None


def _regions_from_hatch(entity, tessellation_segments: int, min_area: float, hatch_index: int = 0) -> list[HatchRegion]:
    rings: list[list[Point2D]] = []
    warnings: list[str] = []

    for path in entity.paths:
        vertices: list[Point2D] = []
        if hasattr(path, "vertices"):
            vertices = _vertices_from_polyline_path(path, tessellation_segments)
        elif hasattr(path, "edges"):
            vertices = _vertices_from_edge_path(path, tessellation_segments)
        vertices = _transform_entity_ocs_points(entity, vertices)
        if len(vertices) < 3:
            warnings.append("Boundary path could not be polygonized.")
            continue
        rings.append(_close_ring(vertices))

    polygons = _polygons_from_rings(rings, min_area)
    if not polygons:
        return []

    regions: list[HatchRegion] = []
    handle = str(entity.dxf.handle)
    pattern_name = str(getattr(entity.dxf, "pattern_name", "") or "").upper()
    solid_fill = int(getattr(entity.dxf, "solid_fill", 0) or 0)
    pattern_scale = _try_float(getattr(entity.dxf, "pattern_scale", None))
    for polygon_index, polygon in enumerate(polygons, start=1):
        exterior = list(polygon.exterior.coords)[:-1]
        regions.append(
            HatchRegion(
                source_type="HATCH",
                layer=str(entity.dxf.layer),
                handle=handle,
                vertices=[(float(x), float(y)) for x, y in exterior],
                polygon=polygon,
                area=float(polygon.area),
                bbox=tuple(float(v) for v in polygon.bounds),
                warnings=list(warnings),
                source_id=f"{handle}:{polygon_index}",
                polygon_index=polygon_index,
                hatch_index=hatch_index,
                hatch_pattern_name=pattern_name,
                hatch_solid_fill=solid_fill,
                hatch_pattern_scale=pattern_scale,
            )
        )
    return regions


def _region_from_closed_polyline(entity, tessellation_segments: int, min_area: float) -> HatchRegion | None:
    is_closed_attr = getattr(entity, "is_closed", None)
    if callable(is_closed_attr):
        closed = bool(is_closed_attr())
    else:
        closed = bool(getattr(entity, "closed", False) or is_closed_attr)
    if not closed:
        return None

    if entity.dxftype() == "LWPOLYLINE":
        raw_points = [(float(x), float(y), float(bulge or 0.0)) for x, y, _s, _e, bulge in entity.get_points("xyseb")]
        vertices = _vertices_from_bulged_points(raw_points, tessellation_segments)
    else:
        vertices = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
    vertices = _transform_entity_ocs_points(entity, vertices)

    polygons = _polygons_from_rings([_close_ring(vertices)], min_area)
    if not polygons:
        return None
    polygon = polygons[0]

    return HatchRegion(
        source_type=entity.dxftype(),
        layer=str(entity.dxf.layer),
        handle=str(entity.dxf.handle),
        vertices=list(polygon.exterior.coords)[:-1],
        polygon=polygon,
        area=float(polygon.area),
        bbox=tuple(float(v) for v in polygon.bounds),
        warnings=[],
        source_id=str(entity.dxf.handle),
    )


def _apply_color_info(region: HatchRegion, entity, doc) -> None:
    layer_color = _layer_color_index(doc, getattr(entity.dxf, "layer", ""))
    entity_color = _entity_color_index(entity)
    region.layer_color = layer_color
    region.entity_color = entity_color
    region.display_color = _display_color_for_entity(entity, entity_color, layer_color)


def _layer_color_index(doc, layer_name: object) -> int | None:
    try:
        value = int(doc.layers.get(str(layer_name)).dxf.color)
    except Exception:
        return None
    return value if value > 0 else None


def _entity_color_index(entity) -> int | None:
    try:
        value = int(getattr(entity.dxf, "color", 256))
    except Exception:
        return None
    return value if value not in {0, 256, 257} and value > 0 else None


def _display_color_for_entity(entity, entity_color: int | None, layer_color: int | None) -> str | None:
    true_color = _true_color_to_hex(getattr(entity.dxf, "true_color", None))
    if true_color:
        return true_color
    for value in (entity_color, layer_color):
        color = _aci_to_hex(value)
        if color:
            return color
    return None


def _true_color_to_hex(value) -> str | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return f"#{(number >> 16) & 0xFF:02x}{(number >> 8) & 0xFF:02x}{number & 0xFF:02x}"


def _aci_to_hex(value: int | None) -> str | None:
    if value is None:
        return None
    aci = int(value)
    palette = {
        1: "#d93025",
        2: "#f9ab00",
        3: "#188038",
        4: "#1a73e8",
        5: "#8a3ffc",
        6: "#d01884",
        7: "#5f6368",
        8: "#9aa0a6",
        9: "#202124",
        30: "#ff7f00",
        40: "#ffb000",
        50: "#ffd54f",
        70: "#9ccc65",
        90: "#26a69a",
        110: "#00acc1",
        130: "#42a5f5",
        150: "#5c6bc0",
        170: "#7e57c2",
        190: "#ab47bc",
        210: "#ec407a",
        230: "#ef5350",
    }
    return palette.get(aci)


def _vertices_from_polyline_path(path, tessellation_segments: int) -> list[Point2D]:
    raw_points: list[tuple[float, float, float]] = []
    for item in path.vertices:
        x = float(item[0])
        y = float(item[1])
        bulge = float(item[2]) if len(item) > 2 and item[2] is not None else 0.0
        raw_points.append((x, y, bulge))
    return _vertices_from_bulged_points(raw_points, tessellation_segments)


def _vertices_from_bulged_points(raw_points: Sequence[tuple[float, float, float]], tessellation_segments: int) -> list[Point2D]:
    if len(raw_points) < 2:
        return [(x, y) for x, y, _bulge in raw_points]

    vertices: list[Point2D] = []
    closed_points = list(raw_points)
    if not _same_point((closed_points[0][0], closed_points[0][1]), (closed_points[-1][0], closed_points[-1][1])):
        closed_points.append(closed_points[0])

    for index in range(len(closed_points) - 1):
        x1, y1, bulge = closed_points[index]
        x2, y2, _next_bulge = closed_points[index + 1]
        start = (x1, y1)
        end = (x2, y2)
        if not vertices:
            vertices.append(start)
        if abs(bulge) > 1.0e-12:
            arc_points = _bulge_arc_points(start, end, bulge, tessellation_segments)
            vertices.extend(arc_points[1:])
        else:
            vertices.append(end)
    return _dedupe_consecutive(vertices)


def _vertices_from_edge_path(path, tessellation_segments: int) -> list[Point2D]:
    vertices: list[Point2D] = []
    for edge in path.edges:
        edge_points = _points_from_edge(edge, tessellation_segments)
        if not edge_points:
            continue
        if vertices and _same_point(vertices[-1], edge_points[0]):
            vertices.extend(edge_points[1:])
        else:
            vertices.extend(edge_points)
    return _dedupe_consecutive(vertices)


def _points_from_edge(edge, tessellation_segments: int) -> list[Point2D]:
    if hasattr(edge, "start") and hasattr(edge, "end"):
        return [_xy(edge.start), _xy(edge.end)]
    if hasattr(edge, "center") and hasattr(edge, "radius"):
        return _arc_points(
            _xy(edge.center),
            float(edge.radius),
            float(edge.start_angle),
            float(edge.end_angle),
            bool(getattr(edge, "ccw", True)),
            tessellation_segments,
        )
    if hasattr(edge, "major_axis") and hasattr(edge, "ratio"):
        return _ellipse_points(edge, tessellation_segments)
    fit_points = list(getattr(edge, "fit_points", []) or [])
    if fit_points:
        return [_xy(point) for point in fit_points]
    control_points = list(getattr(edge, "control_points", []) or [])
    if control_points:
        return [_xy(point) for point in control_points]
    return []


def _arc_points(
    center: Point2D,
    radius: float,
    start_angle: float,
    end_angle: float,
    ccw: bool,
    tessellation_segments: int,
) -> list[Point2D]:
    start = start_angle
    end = end_angle
    if ccw and end < start:
        end += 360.0
    if not ccw and end > start:
        end -= 360.0
    count = max(2, int(tessellation_segments))
    return [
        (
            center[0] + radius * cos(radians(start + (end - start) * i / (count - 1))),
            center[1] + radius * sin(radians(start + (end - start) * i / (count - 1))),
        )
        for i in range(count)
    ]


def _ellipse_points(edge, tessellation_segments: int) -> list[Point2D]:
    center = _xy(edge.center)
    major = _xy(edge.major_axis)
    ratio = float(edge.ratio)
    start = float(edge.start_angle)
    end = float(edge.end_angle)
    if abs(start) > 2 * pi or abs(end) > 2 * pi:
        start = radians(start)
        end = radians(end)
    ccw = bool(getattr(edge, "ccw", True))
    if ccw and end < start:
        end += 2 * pi
    if not ccw and end > start:
        end -= 2 * pi
    minor = (-major[1] * ratio, major[0] * ratio)
    count = max(2, int(tessellation_segments))
    points = []
    for i in range(count):
        t = start + (end - start) * i / (count - 1)
        points.append((center[0] + major[0] * cos(t) + minor[0] * sin(t), center[1] + major[1] * cos(t) + minor[1] * sin(t)))
    return points


def _bulge_arc_points(start: Point2D, end: Point2D, bulge: float, tessellation_segments: int) -> list[Point2D]:
    chord = hypot(end[0] - start[0], end[1] - start[1])
    if chord <= 1.0e-12:
        return [start, end]
    theta = 4.0 * atan(bulge)
    radius = chord / (2.0 * sin(abs(theta) / 2.0))
    midpoint = ((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)
    unit = ((end[0] - start[0]) / chord, (end[1] - start[1]) / chord)
    normal = (-unit[1], unit[0])
    offset = radius * cos(abs(theta) / 2.0)
    if bulge < 0:
        offset *= -1.0
    center = (midpoint[0] + normal[0] * offset, midpoint[1] + normal[1] * offset)
    start_angle = degrees(atan2(start[1] - center[1], start[0] - center[0]))
    end_angle = start_angle + degrees(theta)
    return _arc_points(center, abs(radius), start_angle, end_angle, bulge > 0, max(3, tessellation_segments))


def _polygon_from_rings(rings: Iterable[Sequence[Point2D]], min_area: float) -> Polygon | None:
    polygons = _polygons_from_rings(rings, min_area)
    return polygons[0] if polygons else None


def _polygons_from_rings(rings: Iterable[Sequence[Point2D]], min_area: float) -> list[Polygon]:
    clean_rings = [_close_ring(_dedupe_consecutive(list(ring))) for ring in rings if len(ring) >= 3]
    clean_rings = [ring for ring in clean_rings if len(ring) >= 4]
    if not clean_rings:
        return []

    candidates = []
    for ring in clean_rings:
        poly = Polygon(ring)
        if not poly.is_valid:
            poly = poly.buffer(0)
        if poly.is_empty or abs(poly.area) <= min_area:
            continue
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda geom: geom.area)
        candidates.append({"ring": ring, "poly": poly, "area": abs(poly.area)})
    candidates.sort(key=lambda row: row["area"], reverse=True)
    if not candidates:
        return []

    exteriors = []
    for idx, row in enumerate(candidates):
        point = row["poly"].representative_point()
        containing = [other for j, other in enumerate(candidates) if j != idx and other["area"] > row["area"] and other["poly"].contains(point)]
        if not containing:
            exteriors.append(row)

    polygons: list[Polygon] = []
    for exterior in exteriors:
        exterior_poly = exterior["poly"]
        holes = []
        for candidate in candidates:
            if candidate is exterior:
                continue
            point = candidate["poly"].representative_point()
            if not exterior_poly.contains(point):
                continue
            smaller_container = any(
                other is not exterior
                and other is not candidate
                and other["area"] < exterior["area"]
                and other["area"] > candidate["area"]
                and other["poly"].contains(point)
                for other in candidates
            )
            if not smaller_container:
                holes.append(candidate["ring"])
        polygon = Polygon(exterior["ring"], holes)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if isinstance(polygon, MultiPolygon):
            parts = [part for part in polygon.geoms if part.area > min_area]
            polygons.extend(orient(part, sign=1.0) for part in parts)
        elif not polygon.is_empty and polygon.area > min_area:
            polygons.append(orient(polygon, sign=1.0))
    return polygons


def _xy(point) -> Point2D:
    if hasattr(point, "x") and hasattr(point, "y"):
        return (float(point.x), float(point.y))
    return (float(point[0]), float(point[1]))


def _entity_elevation_z(entity) -> float:
    try:
        elevation = getattr(getattr(entity, "dxf", None), "elevation", 0.0)
    except Exception:
        return 0.0
    if elevation is None:
        return 0.0
    try:
        if hasattr(elevation, "z"):
            return float(elevation.z)
        if isinstance(elevation, (tuple, list)):
            if len(elevation) >= 3:
                return float(elevation[2])
            if len(elevation) == 1:
                return float(elevation[0])
            return 0.0
        return float(elevation)
    except (TypeError, ValueError):
        return 0.0


def _transform_entity_ocs_points(entity, points: Sequence[Point2D]) -> list[Point2D]:
    source = [(float(x), float(y)) for x, y in points]
    try:
        ocs = entity.ocs()
        to_wcs = getattr(ocs, "to_wcs")
    except Exception:
        return source
    elevation_z = _entity_elevation_z(entity)
    transformed: list[Point2D] = []
    for x, y in source:
        try:
            transformed.append(_xy(to_wcs((x, y, elevation_z))))
        except Exception:
            transformed.append((x, y))
    return transformed


def _close_ring(vertices: Sequence[Point2D]) -> list[Point2D]:
    ring = list(vertices)
    if ring and not _same_point(ring[0], ring[-1]):
        ring.append(ring[0])
    return ring


def _dedupe_consecutive(vertices: Sequence[Point2D], tolerance: float = 1.0e-9) -> list[Point2D]:
    result: list[Point2D] = []
    for vertex in vertices:
        point = (float(vertex[0]), float(vertex[1]))
        if not result or not _same_point(result[-1], point, tolerance):
            result.append(point)
    return result


def _same_point(a: Point2D, b: Point2D, tolerance: float = 1.0e-9) -> bool:
    return abs(a[0] - b[0]) <= tolerance and abs(a[1] - b[1]) <= tolerance


def _try_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _try_int(value) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


# ---- v4 load-region wrapper -------------------------------------------------
from dataclasses import dataclass as _dataclass
from typing import Any as _Any
import json as _json
import csv as _csv

from .load_parser import LoadLayerInfo, parse_load_layer
from .validators import validate_polygon


@_dataclass
class LoadRegion:
    region: HatchRegion
    load: LoadLayerInfo | None
    status: str
    warnings: list[str]

    @property
    def polygon(self):
        return self.region.polygon

    @property
    def area(self) -> float:
        return self.region.area

    def to_record(self) -> dict[str, _Any]:
        base = self.region.to_record()
        base.update(
            {
                "status": self.status,
                "load_real_name": self.load.real_name if self.load else "",
                "DL": self.load.dl if self.load else None,
                "LL": self.load.ll if self.load else None,
                "story_name": self.region.story_name,
                "source_id": self.region.source_id,
                "polygon_index": self.region.polygon_index,
                "hatch_pattern_name": self.region.hatch_pattern_name,
                "hatch_solid_fill": self.region.hatch_solid_fill,
                "hatch_pattern_scale": self.region.hatch_pattern_scale,
                "direction_marker_count": len(self.region.direction_markers),
                "direction_marker_source_ids": [marker.source_id for marker in self.region.direction_markers],
                "direction_marker_match_methods": [marker.match_method for marker in self.region.direction_markers],
                "warnings": list(self.warnings),
            }
        )
        return base


def read_load_regions(
    dxf_path: str | Path,
    *,
    mapping_path: str | Path | None = None,
    layout_metadata_path: str | Path | None = None,
    project_dxf_templates_dir: str | Path | None = None,
    metadata_search_dirs: Sequence[str | Path] | None = None,
    include_closed_polylines: bool = True,
    tessellation_segments: int = 16,
    min_area: float = 1.0e-9,
) -> list[LoadRegion]:
    dxf = Path(dxf_path)
    search_dirs = tuple([*(metadata_search_dirs or ()), *([project_dxf_templates_dir] if project_dxf_templates_dir else [])])
    mapping_source = Path(mapping_path) if mapping_path else find_layer_mapping_path(dxf, search_dirs=search_dirs)
    metadata_source = (
        Path(layout_metadata_path)
        if layout_metadata_path
        else find_layout_metadata_path(
            dxf,
            mapping_path=mapping_source,
            search_dirs=search_dirs,
            project_dxf_templates_dir=project_dxf_templates_dir,
        )
    )
    mapping = _load_layer_mapping(mapping_source)
    story_layouts = read_layout_metadata(metadata_source) if metadata_source else []
    if _looks_like_all_story_dxf(dxf) and not story_layouts:
        raise RuntimeError(_missing_all_story_metadata_message())
    raw_regions = read_dxf_hatches(
        dxf_path,
        include_closed_polylines=include_closed_polylines,
        tessellation_segments=tessellation_segments,
        min_area=min_area,
    )
    regions: list[LoadRegion] = []
    for region in raw_regions:
        if story_layouts:
            region = _region_with_story_layout(region, story_layouts, metadata_source)
        warnings = list(region.warnings)
        warnings.extend(validate_polygon(region.polygon, min_area=min_area))
        try:
            core_layer = strip_cad_work_layer_prefix(region.layer)
            if region.layer in mapping or core_layer in mapping:
                info = mapping.get(region.layer) or mapping[core_layer]
                aci_color = _try_int(info.get("aci_color"))
                if aci_color is not None:
                    region.layer_color = aci_color
                    region.display_color = _aci_to_hex(aci_color) or region.display_color
                load = LoadLayerInfo(
                    layer=region.layer,
                    real_name=str(info.get("real_name") or info.get("name") or region.layer),
                    dl=float(info.get("DL", info.get("dl", 0.0)) or 0.0),
                    ll=float(info.get("LL", info.get("ll", 0.0)) or 0.0),
                    source="mapping",
                )
            else:
                load = parse_load_layer(region.layer)
            status = _status_from_region_warnings(warnings)
        except Exception as exc:  # noqa: BLE001 - layer parse errors should be record-level warnings
            load = None
            status = "LOAD_PARSE_FAILED"
            warnings.append(str(exc))
        regions.append(LoadRegion(region=region, load=load, status=status, warnings=warnings))
    return merge_adjacent_load_regions(regions)


def merge_adjacent_load_regions(
    regions: list[LoadRegion],
    *,
    touch_tolerance: float = 1.0e-7,
) -> list[LoadRegion]:
    if len(regions) <= 1:
        return list(regions)

    groups: dict[tuple, list[tuple[int, LoadRegion]]] = {}
    passthrough: dict[int, LoadRegion] = {}
    for index, region in enumerate(regions):
        if not _load_region_is_mergeable(region):
            passthrough[index] = region
            continue
        groups.setdefault(_load_region_merge_key(region), []).append((index, region))

    replacements: dict[int, list[LoadRegion]] = dict((index, [region]) for index, region in passthrough.items())
    skip_indices: set[int] = set()
    merge_index = 1
    for group in groups.values():
        if len(group) == 1:
            replacements[group[0][0]] = [group[0][1]]
            continue
        for component in _load_region_connected_components(group, touch_tolerance=touch_tolerance):
            first_index = min(index for index, _region in component)
            for index, _region in component:
                if index != first_index:
                    skip_indices.add(index)
            if len(component) == 1:
                replacements[first_index] = [component[0][1]]
                continue
            merged = _merge_load_region_component(component, merge_index=merge_index)
            if len(merged) == 1 and merged[0] is not component[0][1]:
                merge_index += 1
            replacements[first_index] = merged

    merged_regions: list[LoadRegion] = []
    for index, region in enumerate(regions):
        if index in skip_indices:
            continue
        merged_regions.extend(replacements.get(index, [region]))
    return merged_regions


def _load_region_is_mergeable(region: LoadRegion) -> bool:
    source_type = str(getattr(region.region, "source_type", "") or "").upper()
    return source_type in {"HATCH", "LWPOLYLINE", "POLYLINE"} and getattr(region.region, "polygon", None) is not None


def _load_region_merge_key(region: LoadRegion) -> tuple:
    hatch = region.region
    load = region.load
    return (
        str(getattr(hatch, "story_name", "") or ""),
        normalize_cad_layer_name(strip_cad_work_layer_prefix(str(getattr(hatch, "layer", "") or ""))),
        str(getattr(load, "real_name", "") or "").strip(),
        round(float(getattr(load, "dl", 0.0) if load else 0.0), 8),
        round(float(getattr(load, "ll", 0.0) if load else 0.0), 8),
        str(getattr(hatch, "hatch_pattern_name", "") or "").upper(),
        int(getattr(hatch, "hatch_solid_fill", 0) or 0),
    )


def _load_region_connected_components(
    group: Sequence[tuple[int, LoadRegion]],
    *,
    touch_tolerance: float,
) -> list[list[tuple[int, LoadRegion]]]:
    count = len(group)
    adjacency = [set() for _ in range(count)]
    for left in range(count):
        left_polygon = group[left][1].region.polygon
        for right in range(left + 1, count):
            right_polygon = group[right][1].region.polygon
            if _polygons_touch_or_overlap(left_polygon, right_polygon, touch_tolerance=touch_tolerance):
                adjacency[left].add(right)
                adjacency[right].add(left)

    components: list[list[tuple[int, LoadRegion]]] = []
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
    components.sort(key=lambda component: min(index for index, _region in component))
    return components


def _polygons_touch_or_overlap(left: Polygon, right: Polygon, *, touch_tolerance: float) -> bool:
    if left is None or right is None or left.is_empty or right.is_empty:
        return False
    if left.intersects(right) or left.touches(right) or left.overlaps(right):
        return True
    return left.distance(right) <= float(touch_tolerance)


def _merge_load_region_component(
    component: Sequence[tuple[int, LoadRegion]],
    *,
    merge_index: int,
) -> list[LoadRegion]:
    items = [region for _index, region in component]
    if _has_conflicting_direction_markers(items):
        return [_load_region_with_warning(item, "MERGE_SKIPPED_DIRECTION_CONFLICT") for item in items]
    merged_geom = unary_union([item.region.polygon for item in items])
    polygons = _polygons_from_merged_geometry(merged_geom)
    if len(polygons) != 1:
        return items
    polygon = polygons[0]
    if polygon.is_empty or polygon.area <= 1.0e-12:
        return items

    first = items[0]
    hatch = first.region
    vertices = [(float(x), float(y)) for x, y in list(polygon.exterior.coords)[:-1]]
    placed_vertices, placed_bbox = _merged_component_placed_geometry(items)
    warnings = _unique_warning_strings([warning for item in items for warning in item.warnings])
    warnings.append(f"MERGED_ADJACENT_HATCH_REGIONS(n={len(items)})")
    region_warnings = _unique_warning_strings([warning for item in items for warning in item.region.warnings])
    region_warnings.append(f"MERGED_ADJACENT_HATCH_REGIONS(n={len(items)})")
    bbox = tuple(float(value) for value in polygon.bounds)
    story = str(getattr(hatch, "story_name", "") or "NO_STORY")
    layer = normalize_cad_layer_name(strip_cad_work_layer_prefix(str(getattr(hatch, "layer", "") or "LAYER")))
    merged_hatch = replace(
        hatch,
        vertices=vertices,
        polygon=polygon,
        area=float(polygon.area),
        bbox=bbox,
        warnings=region_warnings,
        source_id=f"MERGED:{story}:{layer}:{merge_index}",
        polygon_index=0,
        direction_markers=_merged_direction_markers(items, polygon),
        placed_vertices=placed_vertices,
        placed_bbox=placed_bbox,
        source_bbox=bbox,
        model_bbox=bbox,
    )
    return [
        LoadRegion(
            region=merged_hatch,
            load=first.load,
            status="OK" if all(item.status == "OK" for item in items) else _status_from_region_warnings(warnings),
            warnings=warnings,
        )
    ]


def _polygons_from_merged_geometry(geometry) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [orient(geometry, sign=1.0)]
    if isinstance(geometry, MultiPolygon):
        return [orient(part, sign=1.0) for part in geometry.geoms if not part.is_empty and part.area > 1.0e-12]
    return []


def _merged_component_placed_geometry(items: Sequence[LoadRegion]) -> tuple[list[Point2D], tuple[float, ...]]:
    if not all(getattr(item.region, "placed_vertices", ()) for item in items):
        return (list(getattr(items[0].region, "placed_vertices", ()) or ()), tuple(getattr(items[0].region, "placed_bbox", ()) or ()))
    polygons = []
    for item in items:
        vertices = [(float(x), float(y)) for x, y in getattr(item.region, "placed_vertices", ()) or ()]
        if len(vertices) >= 3:
            polygons.append(Polygon(vertices))
    if not polygons:
        return ([], ())
    merged = _polygons_from_merged_geometry(unary_union(polygons))
    if len(merged) != 1:
        return (list(getattr(items[0].region, "placed_vertices", ()) or ()), tuple(getattr(items[0].region, "placed_bbox", ()) or ()))
    polygon = merged[0]
    return (
        [(float(x), float(y)) for x, y in list(polygon.exterior.coords)[:-1]],
        tuple(float(value) for value in polygon.bounds),
    )


def _merged_direction_markers(items: Sequence[LoadRegion], polygon: Polygon) -> list[DirectionMarker]:
    markers: list[DirectionMarker] = []
    seen: set[tuple[str, int, Point2D, Point2D]] = set()
    for item in items:
        for marker in getattr(item.region, "direction_markers", ()) or ():
            key = (str(marker.source_id or marker.handle), int(marker.segment_index or 0), marker.start, marker.end)
            if key in seen:
                continue
            seen.add(key)
            match_method = _direction_marker_match_method(marker, polygon) or marker.match_method
            markers.append(replace(marker, match_method=match_method))
    return markers


def _load_region_with_warning(region: LoadRegion, warning: str) -> LoadRegion:
    warnings = _unique_warning_strings([*region.warnings, warning])
    hatch_warnings = _unique_warning_strings([*region.region.warnings, warning])
    return LoadRegion(region=replace(region.region, warnings=hatch_warnings), load=region.load, status=region.status, warnings=warnings)


def _has_conflicting_direction_markers(regions: Sequence[LoadRegion]) -> bool:
    angles = []
    for region in regions:
        for marker in getattr(region.region, "direction_markers", ()) or ():
            if marker.length <= 1.0e-12:
                continue
            angles.append(round(degrees(atan2(marker.end[1] - marker.start[1], marker.end[0] - marker.start[0])) % 180.0, 6))
    if len(angles) <= 1:
        return False
    first = angles[0]
    return any(min(abs(first - angle), 180.0 - abs(first - angle)) > 5.0 for angle in angles[1:])


def _unique_warning_strings(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _region_with_story_layout(region: HatchRegion, story_layouts, metadata_path: Path | None) -> HatchRegion:
    layout, warning = choose_story_layout_for_polygon(region.polygon, story_layouts)
    warnings = list(region.warnings)
    if warning:
        warnings.append(warning)
    if layout is None:
        return HatchRegion(
            source_type=region.source_type,
            layer=region.layer,
            handle=region.handle,
            vertices=region.vertices,
            polygon=region.polygon,
            area=region.area,
            bbox=region.bbox,
            warnings=warnings,
            story_name=region.story_name,
            source_id=region.source_id,
            polygon_index=region.polygon_index,
            hatch_index=region.hatch_index,
            hatch_pattern_name=region.hatch_pattern_name,
            hatch_solid_fill=region.hatch_solid_fill,
            hatch_pattern_scale=region.hatch_pattern_scale,
            direction_markers=region.direction_markers,
            layer_color=region.layer_color,
            entity_color=region.entity_color,
            display_color=region.display_color,
            layout_metadata_used=metadata_path is not None,
            layout_metadata_path=str(metadata_path or ""),
            placed_vertices=list(region.vertices),
            placed_bbox=tuple(float(v) for v in region.bbox),
            source_bbox=tuple(float(v) for v in region.bbox),
            model_bbox=tuple(float(v) for v in region.bbox),
            transform_applied=False,
        )
    placed_vertices = list(region.vertices)
    placed_bbox = tuple(float(v) for v in region.bbox)
    polygon = transform_polygon(region.polygon, layout.inverse_transform)
    exterior = [(float(x), float(y)) for x, y in list(polygon.exterior.coords)[:-1]]
    direction_markers = [_transform_direction_marker(marker, layout.inverse_transform) for marker in region.direction_markers]
    return HatchRegion(
        source_type=region.source_type,
        layer=region.layer,
        handle=region.handle,
        vertices=exterior,
        polygon=polygon,
        area=float(polygon.area),
        bbox=tuple(float(v) for v in polygon.bounds),
        warnings=warnings,
        story_name=layout.story_name,
        source_id=region.source_id,
        polygon_index=region.polygon_index,
        hatch_index=region.hatch_index,
        hatch_pattern_name=region.hatch_pattern_name,
        hatch_solid_fill=region.hatch_solid_fill,
        hatch_pattern_scale=region.hatch_pattern_scale,
        direction_markers=direction_markers,
        layer_color=region.layer_color,
        entity_color=region.entity_color,
        display_color=region.display_color,
        layout_metadata_used=metadata_path is not None,
        layout_metadata_path=str(metadata_path or ""),
        placed_vertices=placed_vertices,
        placed_bbox=placed_bbox,
        source_bbox=tuple(float(v) for v in polygon.bounds),
        model_bbox=tuple(float(v) for v in polygon.bounds),
        transform_applied=True,
    )


def _transform_direction_marker(marker: DirectionMarker, transform) -> DirectionMarker:
    return DirectionMarker(
        source_type=marker.source_type,
        layer=marker.layer,
        handle=marker.handle,
        start=transform.apply(*marker.start),
        end=transform.apply(*marker.end),
        source_id=marker.source_id,
        segment_index=marker.segment_index,
        parent_handle=marker.parent_handle,
        match_method=marker.match_method,
    )


def _load_layer_mapping(path: str | Path | None) -> dict[str, dict[str, _Any]]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    if p.suffix.lower() == ".json":
        data = _json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return _mapping_rows_by_layer(row for row in data if isinstance(row, dict))
        if isinstance(data, dict):
            rows = []
            for key, value in data.items():
                if isinstance(value, dict):
                    row = dict(value)
                    row.setdefault("layer", str(key))
                    rows.append(row)
            return _mapping_rows_by_layer(rows)
    if p.suffix.lower() == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            return _mapping_rows_by_layer(row for row in _csv.DictReader(f) if row.get("layer"))
    return {}


def _mapping_rows_by_layer(rows: Iterable[dict[str, _Any]]) -> dict[str, dict[str, _Any]]:
    result: dict[str, dict[str, _Any]] = {}
    for row in rows:
        layer = str(row.get("layer") or "").strip()
        core_layer = str(row.get("core_layer") or strip_cad_work_layer_prefix(layer)).strip()
        for key in (layer, core_layer, strip_cad_work_layer_prefix(layer)):
            if key:
                result[key] = row
    return result


def _status_from_region_warnings(warnings: Sequence[str]) -> str:
    if not warnings:
        return "OK"
    if any(str(warning) == "AMBIGUOUS_STORY" for warning in warnings):
        return "AMBIGUOUS_STORY"
    if any(str(warning) in {"NO_STORY_LAYOUT", "STORY_NOT_DETECTED"} for warning in warnings):
        return "STORY_NOT_DETECTED"
    return "REVIEW"


def _looks_like_all_story_dxf(path: Path) -> bool:
    stem = path.stem.lower()
    return "all_stories" in stem or "all_story" in stem


def _missing_all_story_metadata_message() -> str:
    return (
        "전층 DXF layout metadata를 찾지 못했습니다.\n"
        "전층 DXF는 층별 배치 offset을 제거해야 하므로 원본 template와 함께 생성된 layout_metadata.json이 필요합니다.\n"
        "원본 DATA/OUTPUT/{프로젝트명}/dxf_templates 폴더의 metadata 파일을 확인하세요."
    )
