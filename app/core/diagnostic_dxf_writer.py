from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence
import math

import ezdxf

from .mgt_parser import Element, Node, Story, select_nodes_by_story
from .model_floorload_diagnostics import FloorLoadDiagnosticIssue, diagnostic_issue_category


MODEL_LINE_TYPES = {"BEAM", "TRUSS", "TENSTR", "COMPTR"}
WALL_TYPES = {"WALL", "PLATE", "SHELL", "SLAB", "PLANE", "PLANAR", "QUAD"}
DUPLICATE_ISSUES = {
    "DUPLICATE_ELEMENT",
    "EXACT_COORD_DUPLICATE_ELEMENT",
    "OVERLAPPING_LINE_ELEMENT",
    "SPLIT_OVERLAP_DUPLICATE_ELEMENT",
}
CANTILEVER_ISSUES = {
    "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD",
    "CANTILEVER_FREE_END_SUPPORTED_BY_ELASTIC_LINK",
    "INTERNAL_MEMBER_MAY_BLOCK_FLOORLOAD",
}
DIAGNOSTIC_LEGEND_ENTRIES = (
    ("FLOAD_DIAG_DUPLICATE", "중복부재: 같은 위치 또는 같은 선상에 겹친 보/부재"),
    ("FLOAD_DIAG_CANTILEVER", "외팔보/자유단: FLOORLOAD 하중 전달이 끊길 수 있는 자유단"),
    ("FLOAD_DIAG_CLOSURE", "폐합불가/영역오류: FLOORLOAD 경계가 닫히지 않거나 다각형이 잘못됨"),
    ("FLOAD_DIAG_SNAP", "스냅오류: DXF 좌표가 MIDAS 노드와 허용오차 내에서 맞지 않음"),
    ("FLOAD_DIAG_ERROR", "일반 오류: FLOORLOAD 생성 전 수정 필요"),
    ("FLOAD_DIAG_WARN", "일반 경고: 확인 후 필요 시 수정"),
)


def write_floorload_diagnostic_dxf(
    *,
    output_path: str | Path,
    issues: Sequence[FloorLoadDiagnosticIssue],
    nodes: Sequence[Node] | None = None,
    elements: Sequence[Element] | None = None,
    stories: Sequence[Story] | None = None,
    story_tolerance: float = 0.01,
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    _ensure_layers(doc)
    style_name = _ensure_korean_text_style(doc)
    msp = doc.modelspace()

    issue_list = list(issues)
    node_list = list(nodes or [])
    element_list = list(elements or [])
    story_list = list(stories or [])
    node_by_id = {node.node_id: node for node in node_list}
    element_by_id = {element.elem_id: element for element in element_list}

    if node_list and element_list and story_list:
        layouts = _story_layouts_for_issues(issue_list, node_list, story_list, story_tolerance)
        for story, story_nodes, bbox, offset in layouts:
            text_height, marker_radius = _text_and_marker_size(bbox)
            _draw_story_label(msp, story.name, bbox, offset, text_height, style_name)
            _draw_story_model(
                msp,
                element_list,
                node_by_id,
                {node.node_id for node in story_nodes},
                offset,
                marker_radius,
            )
        for index, issue in enumerate(issue_list, start=1):
            offset = _offset_for_issue(issue, layouts)
            bbox = _bbox_for_issue(issue, layouts)
            text_height, marker_radius = _text_and_marker_size(bbox)
            _draw_issue_highlights(
                msp,
                index,
                issue,
                element_by_id,
                node_by_id,
                offset,
                marker_radius,
                text_height,
                style_name,
            )
        if issue_list:
            _draw_legend(msp, issue_list, _overall_layout_bbox(layouts, issue_list), style_name)
    else:
        for index, issue in enumerate(issue_list, start=1):
            category = diagnostic_issue_category(issue.issue_type)
            layer = _layer_for_issue(issue)
            radius = 0.35 if str(issue.severity).upper() == "ERROR" else 0.25
            _draw_issue_marker(msp, issue.x, issue.y, radius, layer, category)
            _draw_marker_index(msp, index, issue.x, issue.y, radius, layer, 0.25, style_name)
        if issue_list:
            _draw_legend(msp, issue_list, _bbox_from_issue_points(issue_list), style_name)

    doc.saveas(out)
    return out


def _ensure_layers(doc) -> None:
    for name, color in (
        ("FLOAD_DIAG_MODEL_BEAM", 8),
        ("FLOAD_DIAG_MODEL_WALL", 9),
        ("FLOAD_DIAG_MODEL_COLUMN", 3),
        ("FLOAD_DIAG_DUPLICATE", 1),
        ("FLOAD_DIAG_CANTILEVER", 6),
        ("FLOAD_DIAG_CLOSURE", 30),
        ("FLOAD_DIAG_SNAP", 3),
        ("FLOAD_DIAG_ERROR", 1),
        ("FLOAD_DIAG_WARN", 2),
        ("FLOAD_DIAG_INFO", 5),
        ("FLOAD_DIAG_LEGEND", 7),
        ("FLOAD_DIAG_ERROR_MARK", 1),
        ("FLOAD_DIAG_WARN_MARK", 30),
        ("FLOAD_DIAG_INFO_MARK", 5),
        ("FLOAD_DIAG_TEXT", 7),
        ("FLOAD_DIAG_STORY_LABEL", 4),
    ):
        _ensure_layer(doc, name, color)


def _story_layouts_for_issues(
    issues: Sequence[FloorLoadDiagnosticIssue],
    nodes: Sequence[Node],
    stories: Sequence[Story],
    story_tolerance: float,
) -> list[tuple[Story, list[Node], tuple[float, float, float, float], tuple[float, float]]]:
    story_by_name = {story.name: story for story in stories}
    error_warning_names = [issue.story_name for issue in issues if str(issue.severity).upper() in {"ERROR", "WARNING"} and issue.story_name]
    info_names = [issue.story_name for issue in issues if issue.story_name]
    ordered_names = _unique_preserve_order(error_warning_names or info_names)
    if not ordered_names:
        ordered_names = [story.name for story in stories]
    layouts = []
    cursor_x = 0.0
    previous_width = 0.0
    for story_name in ordered_names:
        story = story_by_name.get(story_name)
        if story is None:
            continue
        story_nodes = select_nodes_by_story(nodes, story.elevation, story_tolerance)
        if not story_nodes:
            continue
        bbox = _bbox_from_nodes(story_nodes)
        width = max(bbox[2] - bbox[0], 1.0)
        height = max(bbox[3] - bbox[1], 1.0)
        gap = max(width, height) * 0.25 if layouts else 0.0
        cursor_x += previous_width + gap
        offset = (cursor_x - bbox[0], -bbox[1])
        layouts.append((story, story_nodes, bbox, offset))
        previous_width = width
    if not layouts and ordered_names != [story.name for story in stories]:
        return _story_layouts_for_issues([], nodes, stories, story_tolerance)
    return layouts


def _draw_story_model(
    msp,
    elements: Sequence[Element],
    node_by_id: dict[int, Node],
    story_node_ids: set[int],
    offset: tuple[float, float],
    marker_radius: float,
) -> None:
    for element in elements:
        if not story_node_ids.intersection(element.node_ids):
            continue
        _draw_element_geometry(msp, element, node_by_id, offset, marker_radius, _model_layer_for_element(element), lineweight=13)


def _draw_issue_highlights(
    msp,
    index: int,
    issue: FloorLoadDiagnosticIssue,
    element_by_id: dict[int, Element],
    node_by_id: dict[int, Node],
    offset: tuple[float, float],
    marker_radius: float,
    text_height: float,
    style_name: str,
) -> None:
    category = diagnostic_issue_category(issue.issue_type)
    highlight_layer = _layer_for_issue(issue)
    for element_id in issue.element_ids:
        element = element_by_id.get(element_id)
        if element is None:
            continue
        lineweight = 80 if category == "duplicate" else 60
        _draw_element_geometry(msp, element, node_by_id, offset, marker_radius, highlight_layer, lineweight=lineweight)
    for node_id in issue.node_ids:
        node = node_by_id.get(node_id)
        if node is None:
            continue
        x, y = _transform_xy(node.x, node.y, offset)
        _draw_issue_marker(msp, x, y, marker_radius * 0.75, highlight_layer, category)

    x, y = _transform_xy(issue.x, issue.y, offset)
    _draw_issue_marker(msp, x, y, marker_radius, highlight_layer, category)
    _draw_marker_index(msp, index, x, y, marker_radius, highlight_layer, text_height * 0.85, style_name)


def _draw_element_geometry(
    msp,
    element: Element,
    node_by_id: dict[int, Node],
    offset: tuple[float, float],
    marker_radius: float,
    layer: str,
    *,
    lineweight: int,
) -> None:
    points = [_transform_xy(node_by_id[node_id].x, node_by_id[node_id].y, offset) for node_id in element.node_ids if node_id in node_by_id]
    if not points:
        return
    elem_type = str(element.elem_type or "").upper()
    if elem_type == "COLUMN":
        first = points[0]
        if len(points) == 1 or _distance_xy(first, points[-1]) <= marker_radius * 0.2:
            msp.add_circle(first, marker_radius * 0.45, dxfattribs={"layer": layer, "lineweight": lineweight})
        elif len(points) >= 2:
            msp.add_line(points[0], points[1], dxfattribs={"layer": layer, "lineweight": lineweight})
        return
    if elem_type in MODEL_LINE_TYPES and len(points) >= 2:
        msp.add_line(points[0], points[1], dxfattribs={"layer": layer, "lineweight": lineweight})
        return
    if elem_type in WALL_TYPES and len(points) >= 3:
        msp.add_lwpolyline(points, close=True, dxfattribs={"layer": layer, "lineweight": lineweight})
        return
    if len(points) >= 2:
        for first, second in zip(points, points[1:]):
            msp.add_line(first, second, dxfattribs={"layer": layer, "lineweight": lineweight})


def _draw_story_label(msp, story_name: str, bbox: tuple[float, float, float, float], offset: tuple[float, float], text_height: float, style_name: str) -> None:
    x, y = _transform_xy(bbox[0], bbox[3], offset)
    msp.add_text(
        story_name,
        dxfattribs={"layer": "FLOAD_DIAG_STORY_LABEL", "height": text_height * 1.2, "style": style_name},
    ).set_placement((x, y + text_height * 1.5))


def _draw_cross_marker(msp, x: float, y: float, radius: float, layer: str) -> None:
    msp.add_circle((x, y), radius, dxfattribs={"layer": layer})
    msp.add_line((x - radius, y), (x + radius, y), dxfattribs={"layer": layer})
    msp.add_line((x, y - radius), (x, y + radius), dxfattribs={"layer": layer})


def _draw_issue_marker(msp, x: float, y: float, radius: float, layer: str, category: str) -> None:
    if category == "cantilever":
        points = [
            (x, y + radius),
            (x - radius * 0.9, y - radius * 0.7),
            (x + radius * 0.9, y - radius * 0.7),
        ]
        msp.add_lwpolyline(points, close=True, dxfattribs={"layer": layer})
        return
    if category == "snap":
        msp.add_line((x - radius, y - radius), (x + radius, y + radius), dxfattribs={"layer": layer})
        msp.add_line((x - radius, y + radius), (x + radius, y - radius), dxfattribs={"layer": layer})
        msp.add_circle((x, y), radius * 0.65, dxfattribs={"layer": layer})
        return
    if category == "closure":
        points = [
            (x - radius, y - radius),
            (x + radius, y - radius),
            (x + radius, y + radius),
            (x - radius, y + radius),
        ]
        msp.add_lwpolyline(points, close=True, dxfattribs={"layer": layer})
        return
    _draw_cross_marker(msp, x, y, radius, layer)


def _draw_marker_index(msp, index: int, x: float, y: float, radius: float, layer: str, text_height: float, style_name: str) -> None:
    msp.add_text(
        str(index),
        dxfattribs={"layer": layer, "height": text_height, "style": style_name},
    ).set_placement((x + radius * 1.3, y + radius * 1.3))


def _draw_legend(
    msp,
    issues: Sequence[FloorLoadDiagnosticIssue],
    bbox: tuple[float, float, float, float],
    style_name: str,
) -> None:
    min_x, min_y, max_x, max_y = bbox
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    text_height = _clamp(max(min(width, height) * 0.025, 0.2), 0.2, 1.2)
    line_gap = text_height * 1.65
    legend_x = max_x + max(width * 0.08, text_height * 8.0, 2.0)
    legend_y = max_y
    marker_radius = text_height * 0.45

    msp.add_text(
        "진단 범례",
        dxfattribs={"layer": "FLOAD_DIAG_LEGEND", "height": text_height * 1.2, "style": style_name},
    ).set_placement((legend_x, legend_y))
    cursor_y = legend_y - line_gap * 1.35
    for layer, label in DIAGNOSTIC_LEGEND_ENTRIES:
        category = _category_for_layer(layer)
        _draw_issue_marker(msp, legend_x + marker_radius, cursor_y + marker_radius * 0.25, marker_radius, layer, category)
        msp.add_text(
            label,
            dxfattribs={"layer": "FLOAD_DIAG_LEGEND", "height": text_height, "style": style_name},
        ).set_placement((legend_x + text_height * 2.2, cursor_y))
        cursor_y -= line_gap

    summary_lines = _legend_issue_summary_lines(issues)
    if summary_lines:
        cursor_y -= line_gap * 0.35
        msp.add_text(
            "검출 요약",
            dxfattribs={"layer": "FLOAD_DIAG_LEGEND", "height": text_height * 1.05, "style": style_name},
        ).set_placement((legend_x, cursor_y))
        cursor_y -= line_gap
        for line in summary_lines:
            msp.add_text(
                line,
                dxfattribs={"layer": "FLOAD_DIAG_LEGEND", "height": text_height * 0.9, "style": style_name},
            ).set_placement((legend_x, cursor_y))
            cursor_y -= line_gap * 0.95


def _legend_issue_summary_lines(issues: Sequence[FloorLoadDiagnosticIssue]) -> list[str]:
    duplicate_elements: list[int] = []
    cantilever_elements: list[int] = []
    cantilever_nodes: list[int] = []
    counts = {"closure": 0, "snap": 0, "error": 0, "warning_or_info": 0}
    for issue in issues:
        category = diagnostic_issue_category(issue.issue_type)
        if category == "duplicate":
            duplicate_elements.extend(issue.element_ids)
        elif category == "cantilever":
            cantilever_elements.extend(issue.element_ids)
            cantilever_nodes.extend(issue.node_ids)
        elif category in counts:
            counts[category] += 1

    lines: list[str] = []
    duplicate_label = _format_id_summary("E", duplicate_elements)
    if duplicate_label:
        lines.append(f"중복부재: {duplicate_label}")
    cantilever_parts = [
        value
        for value in (
            _format_id_summary("N", cantilever_nodes),
            _format_id_summary("E", cantilever_elements),
        )
        if value
    ]
    if cantilever_parts:
        lines.append(f"외팔보/자유단: {', '.join(cantilever_parts)}")
    if counts["closure"]:
        lines.append(f"폐합불가/영역오류: {counts['closure']}건")
    if counts["snap"]:
        lines.append(f"스냅오류: {counts['snap']}건")
    if counts["error"]:
        lines.append(f"일반 오류: {counts['error']}건")
    if counts["warning_or_info"]:
        lines.append(f"일반 경고/참고: {counts['warning_or_info']}건")
    return lines[:8]


def _format_id_summary(prefix: str, values: Sequence[int], *, limit: int = 8) -> str:
    unique_values = _unique_preserve_order(str(value) for value in values)
    if not unique_values:
        return ""
    shown = unique_values[:limit]
    suffix = "" if len(unique_values) <= limit else f" 외 {len(unique_values) - limit}개"
    return "/".join(f"{prefix}{value}" for value in shown) + suffix


def _category_for_layer(layer: str) -> str:
    if layer == "FLOAD_DIAG_DUPLICATE":
        return "duplicate"
    if layer == "FLOAD_DIAG_CANTILEVER":
        return "cantilever"
    if layer == "FLOAD_DIAG_CLOSURE":
        return "closure"
    if layer == "FLOAD_DIAG_SNAP":
        return "snap"
    if layer == "FLOAD_DIAG_ERROR":
        return "error"
    return "warning_or_info"


def _offset_for_issue(issue: FloorLoadDiagnosticIssue, layouts) -> tuple[float, float]:
    for story, _nodes, _bbox, offset in layouts:
        if story.name == issue.story_name:
            return offset
    return (0.0, 0.0)


def _bbox_for_issue(issue: FloorLoadDiagnosticIssue, layouts) -> tuple[float, float, float, float]:
    for story, _nodes, bbox, _offset in layouts:
        if story.name == issue.story_name:
            return bbox
    return (issue.x - 1.0, issue.y - 1.0, issue.x + 1.0, issue.y + 1.0)


def _text_and_marker_size(bbox: tuple[float, float, float, float]) -> tuple[float, float]:
    width = max(abs(bbox[2] - bbox[0]), 1.0e-9)
    height = max(abs(bbox[3] - bbox[1]), 1.0e-9)
    text_height = _clamp(max(width, height) / 80.0, 0.15, 1.20)
    return text_height, text_height * 0.8


def _overall_layout_bbox(layouts, issues: Sequence[FloorLoadDiagnosticIssue]) -> tuple[float, float, float, float]:
    points: list[tuple[float, float]] = []
    for _story, _nodes, bbox, offset in layouts:
        points.append(_transform_xy(bbox[0], bbox[1], offset))
        points.append(_transform_xy(bbox[2], bbox[3], offset))
    for issue in issues:
        offset = _offset_for_issue(issue, layouts)
        points.append(_transform_xy(issue.x, issue.y, offset))
    return _bbox_from_xy_points(points)


def _bbox_from_issue_points(issues: Sequence[FloorLoadDiagnosticIssue]) -> tuple[float, float, float, float]:
    points: list[tuple[float, float]] = []
    for issue in issues:
        try:
            x = float(issue.x)
            y = float(issue.y)
        except Exception:
            continue
        if math.isfinite(x) and math.isfinite(y):
            points.append((x, y))
    return _bbox_from_xy_points(points)


def _bbox_from_xy_points(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    valid_points = [(float(x), float(y)) for x, y in points if math.isfinite(float(x)) and math.isfinite(float(y))]
    if not valid_points:
        return (0.0, 0.0, 1.0, 1.0)
    min_x = min(x for x, _y in valid_points)
    max_x = max(x for x, _y in valid_points)
    min_y = min(y for _x, y in valid_points)
    max_y = max(y for _x, y in valid_points)
    width = max(max_x - min_x, 1.0)
    height = max(max_y - min_y, 1.0)
    pad = max(width, height) * 0.08
    return (min_x - pad, min_y - pad, max_x + pad, max_y + pad)


def _model_layer_for_element(element: Element) -> str:
    elem_type = str(element.elem_type or "").upper()
    if elem_type in MODEL_LINE_TYPES:
        return "FLOAD_DIAG_MODEL_BEAM"
    if elem_type == "COLUMN":
        return "FLOAD_DIAG_MODEL_COLUMN"
    return "FLOAD_DIAG_MODEL_WALL"


def _layer_for_issue(issue: FloorLoadDiagnosticIssue) -> str:
    category = diagnostic_issue_category(issue.issue_type)
    if category == "duplicate":
        return "FLOAD_DIAG_DUPLICATE"
    if category == "cantilever":
        return "FLOAD_DIAG_CANTILEVER"
    if category == "closure":
        return "FLOAD_DIAG_CLOSURE"
    if category == "snap":
        return "FLOAD_DIAG_SNAP"
    if category == "error":
        return "FLOAD_DIAG_ERROR"
    severity = str(issue.severity or "").upper()
    if severity == "ERROR":
        return "FLOAD_DIAG_ERROR"
    if severity == "WARNING":
        return "FLOAD_DIAG_WARN"
    return "FLOAD_DIAG_INFO"


def _highlight_layer_for_issue(issue_type: str) -> str:
    category = diagnostic_issue_category(issue_type)
    if category == "duplicate" or issue_type in DUPLICATE_ISSUES:
        return "FLOAD_DIAG_DUPLICATE"
    if category == "cantilever" or issue_type in CANTILEVER_ISSUES:
        return "FLOAD_DIAG_CANTILEVER"
    if category == "closure":
        return "FLOAD_DIAG_CLOSURE"
    if category == "snap":
        return "FLOAD_DIAG_SNAP"
    return "FLOAD_DIAG_WARN"


def _marker_layer_for_severity(severity: str) -> str:
    value = str(severity or "").upper()
    if value == "ERROR":
        return "FLOAD_DIAG_ERROR"
    if value == "WARNING":
        return "FLOAD_DIAG_WARN"
    return "FLOAD_DIAG_INFO"


def _issue_id_label(issue: FloorLoadDiagnosticIssue) -> str:
    element_label = "/".join(f"E{value}" for value in issue.element_ids)
    node_label = "/".join(f"N{value}" for value in issue.node_ids)
    if element_label and node_label:
        return f"{element_label} {node_label}"
    return element_label or node_label


def _element_center(element: Element, node_by_id: dict[int, Node], offset: tuple[float, float]) -> tuple[float, float] | None:
    points = [_transform_xy(node_by_id[node_id].x, node_by_id[node_id].y, offset) for node_id in element.node_ids if node_id in node_by_id]
    if not points:
        return None
    return sum(x for x, _y in points) / len(points), sum(y for _x, y in points) / len(points)


def _bbox_from_nodes(nodes: Sequence[Node]) -> tuple[float, float, float, float]:
    return min(node.x for node in nodes), min(node.y for node in nodes), max(node.x for node in nodes), max(node.y for node in nodes)


def _unique_preserve_order(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _transform_xy(x: float, y: float, offset: tuple[float, float]) -> tuple[float, float]:
    return float(x) + offset[0], float(y) + offset[1]


def _distance_xy(first: tuple[float, float], second: tuple[float, float]) -> float:
    return math.hypot(first[0] - second[0], first[1] - second[1])


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(value), float(maximum)))


def _ensure_layer(doc, name: str, color: int) -> None:
    if name not in doc.layers:
        doc.layers.add(name, color=color)


def _ensure_korean_text_style(doc) -> str:
    style_name = "MALGUN_GOTHIC"
    try:
        style = doc.styles.get(style_name)
    except Exception:
        style = doc.styles.new(style_name)
    try:
        style.dxf.font = "malgun.ttf"
    except Exception:
        pass
    return style_name
