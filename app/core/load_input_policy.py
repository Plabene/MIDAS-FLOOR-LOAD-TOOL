from __future__ import annotations

from dataclasses import dataclass, field
from math import atan2, degrees, hypot
from typing import Sequence

from shapely.geometry import Polygon


DISTRIBUTION_ONE_WAY = "ONE_WAY"
DISTRIBUTION_TWO_WAY = "TWO_WAY"
DISTRIBUTION_POLYGON_CENTROID = "POLYGON_CENTROID"
DISTRIBUTION_POLYGON_LENGTH = "POLYGON_LENGTH"

DIRECTION_LAYERS = {
    "FLOAD_DIR",
    "FLOAD_DIRECTION",
    "FLOAD_ONEWAY_DIR",
    "ONE WAY SLAB DIRECTION",
}

ERROR_ONE_WAY_REQUIRES_TRI_OR_QUAD = "ERROR_ONE_WAY_REQUIRES_TRI_OR_QUAD"
ERROR_ONE_WAY_DIRECTION_UNRESOLVED = "ERROR_ONE_WAY_DIRECTION_UNRESOLVED"
ERROR_TOO_FEW_NODES = "ERROR_TOO_FEW_NODES"
ERROR_INVALID_POLYGON = "ERROR_INVALID_POLYGON"
ERROR_INVALID_AREA = "ERROR_INVALID_AREA"
SNAP_ERROR_EXCEEDED = "SNAP_ERROR_EXCEEDED"
REVIEW_COMPLEX_POLYGON = "REVIEW_COMPLEX_POLYGON"
REVIEW_AUTO_SHORT_SPAN_USED = "REVIEW_AUTO_SHORT_SPAN_USED"
REVIEW_SHORT_SPAN_INFERRED_FROM_TRIANGLE = "REVIEW_SHORT_SPAN_INFERRED_FROM_TRIANGLE"
REVIEW_DIRECTION_MARKER_TOO_SHORT_IGNORED = "REVIEW_DIRECTION_MARKER_TOO_SHORT_IGNORED"
AMBIGUOUS_ONEWAY_DIRECTION = "AMBIGUOUS_ONEWAY_DIRECTION"


@dataclass(frozen=True)
class LoadInputPolicy:
    distribution: str
    distribution_source: str
    effective_idist: int
    allow_polygon_type: bool
    one_way_angle_deg: float | None = None
    direction_source: str = ""
    direction_marker_source_id: str = ""
    warnings: tuple[str, ...] = field(default_factory=tuple)
    errors: tuple[str, ...] = field(default_factory=tuple)


def infer_distribution(region, load) -> tuple[str, str]:
    explicit = str(getattr(load, "distribution", "") or "")
    if explicit:
        return explicit, "LAYER_TOKEN"

    if str(getattr(region, "source_type", "") or "").upper() == "HATCH":
        pattern = str(getattr(region, "hatch_pattern_name", "") or "").upper()
        solid_fill = int(getattr(region, "hatch_solid_fill", 0) or 0)
        if solid_fill == 1 or pattern == "SOLID":
            return DISTRIBUTION_TWO_WAY, "HATCH_PATTERN_SOLID_TWOWAY"
        if pattern:
            return DISTRIBUTION_ONE_WAY, "HATCH_PATTERN_NON_SOLID_ONEWAY"
        return DISTRIBUTION_TWO_WAY, "PROJECT_DEFAULT"

    return DISTRIBUTION_TWO_WAY, "PROJECT_DEFAULT"


def build_load_input_policy(
    *,
    region,
    load,
    snapped_points: Sequence[tuple[float, float]] | None = None,
    default_one_way_angle: float | None = None,
    max_polygon_nodes: int = 32,
) -> LoadInputPolicy:
    warnings: list[str] = []
    errors: list[str] = []
    distribution, distribution_source = infer_distribution(region, load)
    node_count = len(snapped_points or getattr(region, "vertices", []) or [])
    polygon = getattr(region, "polygon", None)

    if polygon is not None:
        if getattr(polygon, "is_empty", False) or float(getattr(polygon, "area", 0.0) or 0.0) <= 1.0e-12:
            errors.append(ERROR_INVALID_AREA)
        if not getattr(polygon, "is_valid", True):
            errors.append(ERROR_INVALID_POLYGON)

    if distribution == DISTRIBUTION_POLYGON_CENTROID:
        return LoadInputPolicy(distribution, distribution_source, 3, True, warnings=tuple(warnings), errors=tuple(errors))
    if distribution == DISTRIBUTION_POLYGON_LENGTH:
        return LoadInputPolicy(distribution, distribution_source, 4, True, warnings=tuple(warnings), errors=tuple(errors))

    if distribution == DISTRIBUTION_ONE_WAY:
        if node_count < 3:
            errors.append(ERROR_TOO_FEW_NODES)
        elif node_count not in {3, 4}:
            errors.append(ERROR_ONE_WAY_REQUIRES_TRI_OR_QUAD)

        angle, direction_source, marker_source_id, direction_warnings, direction_errors = resolve_one_way_direction(
            region=region,
            load=load,
            snapped_points=snapped_points,
            default_one_way_angle=default_one_way_angle,
        )
        warnings.extend(direction_warnings)
        errors.extend(direction_errors)
        return LoadInputPolicy(
            distribution=distribution,
            distribution_source=distribution_source,
            effective_idist=1,
            allow_polygon_type=True,
            one_way_angle_deg=angle,
            direction_source=direction_source,
            direction_marker_source_id=marker_source_id,
            warnings=tuple(warnings),
            errors=tuple(errors),
        )

    if node_count < 3:
        errors.append(ERROR_TOO_FEW_NODES)
    if node_count > max_polygon_nodes:
        warnings.append(REVIEW_COMPLEX_POLYGON)
    return LoadInputPolicy(
        distribution=DISTRIBUTION_TWO_WAY,
        distribution_source=distribution_source,
        effective_idist=2,
        allow_polygon_type=True,
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def resolve_one_way_direction(
    *,
    region,
    load,
    snapped_points: Sequence[tuple[float, float]] | None = None,
    default_one_way_angle: float | None = None,
) -> tuple[float | None, str, str, list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    markers = list(getattr(region, "direction_markers", []) or [])
    valid_markers = []
    polygon = getattr(region, "polygon", None)
    diagonal = _polygon_diagonal(polygon)
    min_marker_len = max(diagonal * 1.0e-4, 1.0e-9)

    for marker in markers:
        if float(getattr(marker, "length", 0.0) or 0.0) >= min_marker_len:
            valid_markers.append(marker)
        else:
            warnings.append(REVIEW_DIRECTION_MARKER_TOO_SHORT_IGNORED)

    if valid_markers:
        representative = max(valid_markers, key=lambda item: float(getattr(item, "length", 0.0) or 0.0))
        representative_angle = _angle_deg(representative.start, representative.end)
        marker_angles = [_angle_deg(marker.start, marker.end) for marker in valid_markers]
        source_ids = ",".join(str(getattr(marker, "source_id", "") or "") for marker in valid_markers)
        if all(_axis_angle_delta(representative_angle, angle) <= 5.0 for angle in marker_angles):
            return representative_angle, "DXF_DIRECTION_MARKER", source_ids, warnings, errors
        warnings.append(AMBIGUOUS_ONEWAY_DIRECTION)
        return (
            None,
            "AMBIGUOUS_DIRECTION_MARKER",
            source_ids,
            warnings,
            [*errors, AMBIGUOUS_ONEWAY_DIRECTION],
        )

    angle = getattr(load, "one_way_angle_deg", None)
    if angle is not None:
        return float(angle), "LAYER_ANGLE_TOKEN", "", warnings, errors

    if default_one_way_angle is not None:
        return float(default_one_way_angle), "USER_DEFAULT", "", warnings, errors

    points = list(snapped_points or getattr(region, "vertices", []) or [])
    angle, source, span_warnings = infer_short_span_angle(points)
    warnings.extend(span_warnings)
    if angle is None:
        errors.append(ERROR_ONE_WAY_DIRECTION_UNRESOLVED)
    return angle, source, "", warnings, errors


def infer_short_span_angle(points: Sequence[tuple[float, float]]) -> tuple[float | None, str, list[str]]:
    if len(points) < 3:
        return None, "", []
    polygon = Polygon(points)
    if polygon.is_empty or polygon.area <= 1.0e-12:
        return _bbox_short_span_angle(points), "AUTO_SHORT_SPAN_BBOX", [REVIEW_AUTO_SHORT_SPAN_USED]
    rect = polygon.minimum_rotated_rectangle
    coords = list(rect.exterior.coords)[:-1]
    if len(coords) < 4:
        return _bbox_short_span_angle(points), "AUTO_SHORT_SPAN_BBOX", [REVIEW_AUTO_SHORT_SPAN_USED]
    edges = []
    for index, start in enumerate(coords):
        end = coords[(index + 1) % len(coords)]
        length = hypot(end[0] - start[0], end[1] - start[1])
        if length > 1.0e-12:
            edges.append((length, start, end))
    if not edges:
        return _bbox_short_span_angle(points), "AUTO_SHORT_SPAN_BBOX", [REVIEW_AUTO_SHORT_SPAN_USED]
    _length, start, end = min(edges, key=lambda item: item[0])
    warnings = [REVIEW_AUTO_SHORT_SPAN_USED]
    if len(points) == 3:
        warnings.append(REVIEW_SHORT_SPAN_INFERRED_FROM_TRIANGLE)
    return _angle_deg(start, end), "AUTO_SHORT_SPAN", warnings


def _bbox_short_span_angle(points: Sequence[tuple[float, float]]) -> float | None:
    if not points:
        return None
    xs = [float(x) for x, _y in points]
    ys = [float(y) for _x, y in points]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    return 0.0 if width <= height else 90.0


def _angle_deg(start: tuple[float, float], end: tuple[float, float]) -> float:
    return degrees(atan2(float(end[1]) - float(start[1]), float(end[0]) - float(start[0]))) % 360.0


def _axis_angle_delta(a: float, b: float) -> float:
    first = float(a) % 180.0
    second = float(b) % 180.0
    diff = abs(first - second)
    return min(diff, 180.0 - diff)


def _polygon_diagonal(polygon) -> float:
    if polygon is None or getattr(polygon, "is_empty", True):
        return 1.0
    min_x, min_y, max_x, max_y = polygon.bounds
    return max(hypot(max_x - min_x, max_y - min_y), 1.0)
