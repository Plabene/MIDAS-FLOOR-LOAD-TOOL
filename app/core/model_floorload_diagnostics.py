from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence
import csv
import json
import math

from shapely.geometry import Polygon

from .load_input_policy import build_load_input_policy, infer_distribution
from .mgt_parser import (
    Element,
    Node,
    Story,
    iter_floorload_records_from_text,
    parse_floadtype_specs_from_text,
    parse_stldcase_names_from_text,
    parse_unit_from_text,
    select_nodes_by_story,
)


LINE_TYPES = {"BEAM", "COLUMN", "TRUSS", "TENSTR", "COMPTR", "WALL"}
READY = "READY"
READY_WITH_WARNINGS = "READY_WITH_WARNINGS"
BLOCKED = "BLOCKED"
NO_TARGET_REGION = "NO_TARGET_REGION"


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
) -> FloorLoadDiagnosticResult:
    planned_regions = list(planned_load_regions or [])
    unit_info = parse_unit_from_text(mgt_text) if mgt_text else parse_unit_from_text("")
    floadtype_specs = parse_floadtype_specs_from_text(mgt_text) if mgt_text else []
    floadtypes_by_name = {_name_key(spec.name): spec for spec in floadtype_specs}
    stldcase_names = {_name_key(name) for name in parse_stldcase_names_from_text(mgt_text)} if mgt_text else set()
    parsed_existing_floorloads = list(iter_floorload_records_from_text(mgt_text)) if mgt_text else []
    existing_records = list(existing_floorloads or parsed_existing_floorloads)
    node_by_id = {node.node_id: node for node in nodes}
    element_type_counts = dict(sorted(Counter(element.elem_type for element in elements).items()))
    duplicate_tol = duplicate_node_tolerance
    if duplicate_tol is None:
        duplicate_tol = _default_duplicate_node_tolerance(unit_info.length)

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
        )
    )

    for story in stories:
        story_nodes = select_nodes_by_story(nodes, story.elevation, story_tolerance)
        story_node_ids = {node.node_id for node in story_nodes}
        story_elements = [element for element in elements if story_node_ids.intersection(element.node_ids)]
        issues.extend(_detect_duplicate_elements(story, story_elements, node_by_id))
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
) -> FloorLoadDiagnosticSummary:
    error_count = sum(1 for issue in issues if issue.severity == "ERROR")
    warning_count = sum(1 for issue in issues if issue.severity == "WARNING")
    info_count = sum(1 for issue in issues if issue.severity == "INFO")
    if planned_region_count <= 0:
        status = NO_TARGET_REGION
    elif error_count:
        status = BLOCKED
    elif warning_count:
        status = READY_WITH_WARNINGS
    else:
        status = READY
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
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    for load_region in planned_regions:
        region = getattr(load_region, "region", load_region)
        load = getattr(load_region, "load", None)
        story_name = str(getattr(region, "story_name", "") or "")
        vertices = [(float(x), float(y)) for x, y in (getattr(region, "vertices", ()) or ())]
        x, y = _region_xy(region, vertices)
        load_name = _region_load_name(load_region)
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
        issues.extend(_validate_one_way_direction(load_region, vertices, story_name, x, y))
    return issues


def _validate_polygon_xy(
    vertices: Sequence[tuple[float, float]],
    story_name: str,
    node_ids: list[int],
    element_ids: list[int],
    x: float,
    y: float,
    *,
    load_region: object | None = None,
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    distribution = ""
    if load_region is not None:
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
                "INVALID_FLOORLOAD_POLYGON",
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


def _validate_one_way_direction(load_region, vertices: Sequence[tuple[float, float]], story_name: str, x: float, y: float) -> list[FloorLoadDiagnosticIssue]:
    region = getattr(load_region, "region", load_region)
    load = getattr(load_region, "load", None)
    policy = build_load_input_policy(region=region, load=load, snapped_points=vertices)
    issues: list[FloorLoadDiagnosticIssue] = []
    for error in policy.errors:
        issue_type = "TOO_FEW_FLOORLOAD_NODES" if error == "ERROR_TOO_FEW_NODES" else error
        severity = "ERROR"
        issues.append(
            _issue(
                story_name,
                severity,
                issue_type,
                f"One-way/two-way load input policy failed: {error}.",
                x,
                y,
                [],
                [],
                "Check polygon node count and one-way direction markers.",
            )
        )
    return issues


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


def _detect_duplicate_elements(story: Story, elements: Sequence[Element], node_by_id: dict[int, Node]) -> list[FloorLoadDiagnosticIssue]:
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
    return issues


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
