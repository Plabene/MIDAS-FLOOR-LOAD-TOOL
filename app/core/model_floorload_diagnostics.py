from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence
import csv
import json
import math

from .mgt_parser import Element, Node, Story, select_nodes_by_story


LINE_TYPES = {"BEAM", "COLUMN", "TRUSS", "TENSTR", "COMPTR", "WALL"}


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


def analyze_floorload_model(
    *,
    nodes: Sequence[Node],
    elements: Sequence[Element],
    stories: Sequence[Story],
    planned_load_regions: Sequence[object] | None = None,
    story_tolerance: float = 0.01,
    snap_tolerance: float = 0.5,
) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    node_by_id = {node.node_id: node for node in nodes}
    tol = max(abs(float(snap_tolerance)), 1.0e-9)

    for story in stories:
        story_nodes = select_nodes_by_story(nodes, story.elevation, story_tolerance)
        story_node_ids = {node.node_id for node in story_nodes}
        story_elements = [element for element in elements if story_node_ids.intersection(element.node_ids)]
        issues.extend(_detect_near_duplicate_nodes(story, story_nodes, tol))
        issues.extend(_detect_duplicate_elements(story, story_elements, node_by_id))
        issues.extend(_detect_unsplit_members(story, story_nodes, story_elements, node_by_id, tol))
        issues.extend(_detect_open_line_edges(story, story_elements, node_by_id))

    for load_region in planned_load_regions or []:
        issues.extend(_detect_region_snap_gaps(load_region, nodes, stories, story_tolerance, tol))

    return issues


def write_diagnostic_reports(issues: Sequence[FloorLoadDiagnosticIssue], output_dir: str | Path) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    json_path = out / "floorload_diagnostics.json"
    csv_path = out / "floorload_diagnostics.csv"
    records = [issue.to_record() for issue in issues]
    json_path.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["story_name", "severity", "issue_type", "message", "x", "y", "node_ids", "element_ids", "suggested_action"],
        )
        writer.writeheader()
        writer.writerows(records)
    return json_path, csv_path


def _detect_near_duplicate_nodes(story: Story, nodes: Sequence[Node], tolerance: float) -> list[FloorLoadDiagnosticIssue]:
    issues: list[FloorLoadDiagnosticIssue] = []
    for index, first in enumerate(nodes):
        for second in nodes[index + 1 :]:
            distance = math.hypot(first.x - second.x, first.y - second.y)
            if 0.0 < distance <= tolerance:
                issues.append(
                    FloorLoadDiagnosticIssue(
                        story.name,
                        "WARNING",
                        "NEAR_DUPLICATE_NODE",
                        "거의 같은 위치에 복수 node가 존재합니다.",
                        (first.x + second.x) / 2.0,
                        (first.y + second.y) / 2.0,
                        [first.node_id, second.node_id],
                        [],
                        "node merge 또는 좌표 정리를 검토하세요.",
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
                    "ERROR",
                    "DUPLICATE_ELEMENT",
                    "동일 위치에 중복 부재가 입력되어 FLOOR LOAD 인식에 문제가 생길 수 있습니다.",
                    x,
                    y,
                    list(element.node_ids),
                    [first.elem_id, element.elem_id],
                    "중복 beam/wall/slab element를 확인하세요.",
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
                        "WARNING",
                        "UNSPLIT_MEMBER",
                        "노드는 존재하지만 부재가 해당 위치에서 분할되지 않은 것으로 보입니다.",
                        node.x,
                        node.y,
                        [node.node_id, start.node_id, end.node_id],
                        [element.elem_id],
                        "MIDAS에서 해당 보/벽체를 node 위치 기준으로 divide/split 하세요.",
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
                    "해당 위치 주변에서 폐합된 하중 재하 경계가 형성되지 않았을 가능성이 있습니다.",
                    node.x,
                    node.y,
                    [node_id],
                    [],
                    "보/벽체/슬래브 경계가 끊겨 있는지 확인하세요.",
                )
            )
    return issues


def _detect_region_snap_gaps(load_region, nodes: Sequence[Node], stories: Sequence[Story], story_tolerance: float, tolerance: float) -> list[FloorLoadDiagnosticIssue]:
    region = getattr(load_region, "region", load_region)
    story_name = getattr(region, "story_name", "")
    story = next((item for item in stories if item.name == story_name), None)
    story_nodes = select_nodes_by_story(nodes, story.elevation, story_tolerance) if story else list(nodes)
    issues: list[FloorLoadDiagnosticIssue] = []
    for x, y in getattr(region, "vertices", []) or []:
        if not story_nodes:
            continue
        nearest = min(story_nodes, key=lambda node: (node.x - x) ** 2 + (node.y - y) ** 2)
        distance = math.hypot(nearest.x - x, nearest.y - y)
        if distance > tolerance:
            issues.append(
                FloorLoadDiagnosticIssue(
                    story_name,
                    "WARNING",
                    "SNAP_GAP",
                    "floor load polygon boundary와 모델 node/element 경계가 맞지 않을 수 있습니다.",
                    float(x),
                    float(y),
                    [nearest.node_id],
                    [],
                    "CAD 해치 경계와 MIDAS node 위치, snap tolerance를 확인하세요.",
                )
            )
    return issues


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
