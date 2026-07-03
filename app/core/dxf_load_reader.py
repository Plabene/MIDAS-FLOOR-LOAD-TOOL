from __future__ import annotations

from dataclasses import dataclass, field
from math import atan, atan2, cos, degrees, hypot, pi, radians, sin, sqrt
from pathlib import Path
from typing import Iterable, Sequence

import ezdxf
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.polygon import orient

Point2D = tuple[float, float]


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

    def to_record(self) -> dict:
        return {
            "source_type": self.source_type,
            "layer": self.layer,
            "handle": self.handle,
            "area": self.area,
            "bbox": self.bbox,
            "vertex_count": len(self.vertices),
            "warnings": list(self.warnings),
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

    for entity in doc.modelspace():
        dxftype = entity.dxftype()
        if dxftype == "HATCH":
            region = _region_from_hatch(entity, tessellation_segments, min_area)
            if region is not None:
                regions.append(region)
        elif include_closed_polylines and dxftype in {"LWPOLYLINE", "POLYLINE"}:
            region = _region_from_closed_polyline(entity, tessellation_segments, min_area)
            if region is not None:
                regions.append(region)

    return regions


def _region_from_hatch(entity, tessellation_segments: int, min_area: float) -> HatchRegion | None:
    rings: list[list[Point2D]] = []
    warnings: list[str] = []

    for path in entity.paths:
        vertices: list[Point2D] = []
        if hasattr(path, "vertices"):
            vertices = _vertices_from_polyline_path(path, tessellation_segments)
        elif hasattr(path, "edges"):
            vertices = _vertices_from_edge_path(path, tessellation_segments)
        if len(vertices) < 3:
            warnings.append("Boundary path could not be polygonized.")
            continue
        rings.append(_close_ring(vertices))

    polygon = _polygon_from_rings(rings, min_area)
    if polygon is None:
        return None

    exterior = list(polygon.exterior.coords)[:-1]
    return HatchRegion(
        source_type="HATCH",
        layer=str(entity.dxf.layer),
        handle=str(entity.dxf.handle),
        vertices=[(float(x), float(y)) for x, y in exterior],
        polygon=polygon,
        area=float(polygon.area),
        bbox=tuple(float(v) for v in polygon.bounds),
        warnings=warnings,
    )


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

    polygon = _polygon_from_rings([_close_ring(vertices)], min_area)
    if polygon is None:
        return None

    return HatchRegion(
        source_type=entity.dxftype(),
        layer=str(entity.dxf.layer),
        handle=str(entity.dxf.handle),
        vertices=list(polygon.exterior.coords)[:-1],
        polygon=polygon,
        area=float(polygon.area),
        bbox=tuple(float(v) for v in polygon.bounds),
        warnings=[],
    )


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
    clean_rings = [_close_ring(_dedupe_consecutive(list(ring))) for ring in rings if len(ring) >= 3]
    clean_rings = [ring for ring in clean_rings if len(ring) >= 4]
    if not clean_rings:
        return None

    clean_rings.sort(key=lambda ring: abs(Polygon(ring).area), reverse=True)
    exterior = clean_rings[0]
    holes = [ring for ring in clean_rings[1:] if abs(Polygon(ring).area) > min_area]
    polygon = Polygon(exterior, holes)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if isinstance(polygon, MultiPolygon):
        polygon = max(polygon.geoms, key=lambda geom: geom.area)
    if polygon.is_empty or polygon.area <= min_area:
        return None
    return orient(polygon, sign=1.0)


def _xy(point) -> Point2D:
    if hasattr(point, "x") and hasattr(point, "y"):
        return (float(point.x), float(point.y))
    return (float(point[0]), float(point[1]))


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
                "warnings": list(self.warnings),
            }
        )
        return base


def read_load_regions(
    dxf_path: str | Path,
    *,
    mapping_path: str | Path | None = None,
    include_closed_polylines: bool = True,
    tessellation_segments: int = 16,
    min_area: float = 1.0e-9,
) -> list[LoadRegion]:
    mapping = _load_layer_mapping(mapping_path)
    raw_regions = read_dxf_hatches(
        dxf_path,
        include_closed_polylines=include_closed_polylines,
        tessellation_segments=tessellation_segments,
        min_area=min_area,
    )
    regions: list[LoadRegion] = []
    for region in raw_regions:
        warnings = list(region.warnings)
        warnings.extend(validate_polygon(region.polygon, min_area=min_area))
        try:
            if region.layer in mapping:
                info = mapping[region.layer]
                load = LoadLayerInfo(
                    layer=region.layer,
                    real_name=str(info.get("real_name") or info.get("name") or region.layer),
                    dl=float(info.get("DL", info.get("dl", 0.0)) or 0.0),
                    ll=float(info.get("LL", info.get("ll", 0.0)) or 0.0),
                    source="mapping",
                )
            else:
                load = parse_load_layer(region.layer)
            status = "OK" if not warnings else "REVIEW"
        except Exception as exc:  # noqa: BLE001 - layer parse errors should be record-level warnings
            load = None
            status = "LOAD_PARSE_FAILED"
            warnings.append(str(exc))
        regions.append(LoadRegion(region=region, load=load, status=status, warnings=warnings))
    return regions


def _load_layer_mapping(path: str | Path | None) -> dict[str, dict[str, _Any]]:
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    if p.suffix.lower() == ".json":
        data = _json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(row.get("layer")): row for row in data if isinstance(row, dict) and row.get("layer")}
        if isinstance(data, dict):
            return {str(k): v for k, v in data.items() if isinstance(v, dict)}
    if p.suffix.lower() == ".csv":
        with p.open("r", encoding="utf-8-sig", newline="") as f:
            return {str(row.get("layer")): row for row in _csv.DictReader(f) if row.get("layer")}
    return {}
