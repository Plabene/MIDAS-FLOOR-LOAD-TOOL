from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence
import json

import ezdxf

from .load_parser import make_safe_load_layer_name
from .mgt_parser import Element, Node, Story
from .dxf_story_layout import BBox2D, bbox_from_points, plan_story_layouts, write_layout_metadata
from .load_input_policy import DIRECTION_LAYERS


DEFAULT_HATCH_SCALE = 0.01
HATCH_GUIDE_LAYER = "FLOAD_HATCH_GUIDE"


@dataclass(frozen=True)
class LoadLayerSpec:
    real_name: str
    dl: float
    ll: float
    layer: str = ""

    def with_layer(self, index: int) -> "LoadLayerSpec":
        return LoadLayerSpec(self.real_name, self.dl, self.ll, self.layer or make_safe_load_layer_name(index, self.real_name, self.dl, self.ll))


@dataclass(frozen=True)
class DxfTemplateResult:
    dxf_path: Path
    mapping_json_path: Path
    mapping_csv_path: Path
    element_count: int
    warning_count: int
    layout_metadata_path: Path | None = None
    story_count: int = 1


def normalize_hatch_scale(value, default: float = DEFAULT_HATCH_SCALE) -> float:
    try:
        scale = float(str(value).strip())
    except Exception:
        return default
    if scale <= 0:
        return default
    return scale


def write_story_centerline_dxf(
    *,
    output_path: str | Path,
    story: Story,
    nodes: Iterable[Node],
    elements: Iterable[Element],
    load_layers: Iterable[LoadLayerSpec] = (),
    story_tolerance: float = 0.01,
    default_hatch_scale: float = DEFAULT_HATCH_SCALE,
) -> DxfTemplateResult:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    hatch_scale = normalize_hatch_scale(default_hatch_scale)
    node_map = {n.node_id: n for n in nodes}
    doc = ezdxf.new("R2010")
    _set_hatch_header_defaults(doc, default_hatch_scale=hatch_scale)
    doc.header["$INSUNITS"] = 6  # meter, if CAD honors it.
    korean_text_style = _ensure_korean_text_style(doc)
    msp = doc.modelspace()
    _ensure_template_layers(doc)

    element_count = 0
    warnings = 0
    bounds = _empty_bounds()
    column_points: list[tuple[float, float]] = []
    tol = abs(float(story_tolerance))
    for elem in elements:
        pts = [node_map[nid] for nid in elem.node_ids if nid in node_map]
        if len(pts) < 2:
            continue
        story_pts = [p for p in pts if abs(p.z - story.elevation) <= tol]
        if elem.elem_type in {"BEAM", "TRUSS", "TENSTR", "COMPTR"}:
            if len(story_pts) >= 2:
                msp.add_line(story_pts[0].xy, story_pts[1].xy, dxfattribs={"layer": "CENTERLINE_BEAM"})
                _expand_bounds(bounds, [story_pts[0].xy, story_pts[1].xy])
                element_count += 1
            elif len(story_pts) == 1:
                column_points.append(story_pts[0].xy)
                _expand_bounds(bounds, [story_pts[0].xy])
                element_count += 1
            continue
        if elem.elem_type in {"COLUMN"}:
            p = _representative_xy(story_pts or pts)
            if p:
                column_points.append(p)
                _expand_bounds(bounds, [p])
                element_count += 1
            continue
        if elem.elem_type in {"WALL", "PLATE", "SLAB", "PLANAR"} or len(pts) >= 3:
            if len(story_pts) >= 2:
                xy = _unique_xy([p.xy for p in story_pts])
                if len(xy) == 2:
                    msp.add_line(xy[0], xy[1], dxfattribs={"layer": "CENTERLINE_WALL"})
                    _expand_bounds(bounds, [xy[0], xy[1]])
                    element_count += 1
                elif len(xy) > 2:
                    # Center-line template이므로 면 채움은 제외하고 참조 외곽선만 얇게 표시한다.
                    msp.add_lwpolyline(xy, close=True, dxfattribs={"layer": "REFERENCE_GRID"})
                    _expand_bounds(bounds, xy)
                    element_count += 1
            elif len(story_pts) == 1:
                column_points.append(story_pts[0].xy)
                _expand_bounds(bounds, [story_pts[0].xy])
                element_count += 1
            else:
                warnings += 1

    point_display_size = _compute_point_display_size_from_bounds(bounds)
    _set_point_display_defaults(doc, point_size=point_display_size)
    for point in column_points:
        _add_column_point_symbol(msp, point)

    _add_guide_text_below_geometry(msp, story, bounds, korean_text_style, default_hatch_scale=hatch_scale)

    mapping_rows = []
    for index, layer_spec in enumerate(load_layers, start=1):
        spec = layer_spec.with_layer(index)
        _ensure_layer(doc, spec.layer, color=(index % 7) + 1)
        mapping_rows.append({"layer": spec.layer, "real_name": spec.real_name, "DL": spec.dl, "LL": spec.ll})
    if not mapping_rows:
        spec = LoadLayerSpec("기본하중", 0.0, 0.0).with_layer(1)
        _ensure_layer(doc, spec.layer, color=1)
        mapping_rows.append({"layer": spec.layer, "real_name": spec.real_name, "DL": spec.dl, "LL": spec.ll})

    try:
        doc.saveas(out)
    except PermissionError as exc:
        raise PermissionError(
            "DXF 파일 저장 권한이 없습니다. "
            "같은 이름의 DXF 파일이 CAD/ZWCAD/AutoCAD 또는 탐색기 미리보기에서 열려 있으면 닫은 뒤 다시 시도해 주세요. "
            "또는 프로그램이 자동으로 다른 파일명으로 저장되도록 출력 경로 생성 로직을 확인해 주세요.\n"
            f"저장 실패 파일: {out}"
        ) from exc
    mapping_json = out.with_suffix(".layer_mapping.json")
    mapping_csv = out.with_suffix(".layer_mapping.csv")
    try:
        mapping_json.write_text(json.dumps(mapping_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        mapping_csv.write_text(_mapping_csv(mapping_rows), encoding="utf-8-sig")
    except PermissionError as exc:
        raise PermissionError(
            "DXF 레이어 매핑 JSON/CSV 파일을 저장할 수 없습니다. "
            "같은 이름의 매핑 파일이 열려 있거나 DATA\\dxf_templates 폴더 권한이 제한되어 있을 수 있습니다.\n"
            f"저장 실패 파일: {mapping_json} 또는 {mapping_csv}"
        ) from exc
    return DxfTemplateResult(out, mapping_json, mapping_csv, element_count, warnings)


def write_all_story_centerline_dxf(
    *,
    output_path: str | Path,
    stories: Iterable[Story],
    nodes: Iterable[Node],
    elements: Iterable[Element],
    load_layers: Iterable[LoadLayerSpec] = (),
    story_tolerance: float = 0.01,
    default_hatch_scale: float = DEFAULT_HATCH_SCALE,
) -> DxfTemplateResult:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    story_list = list(stories)
    node_list = list(nodes)
    element_list = list(elements)
    load_layer_list = list(load_layers)
    hatch_scale = normalize_hatch_scale(default_hatch_scale)
    node_map = {n.node_id: n for n in node_list}

    doc = ezdxf.new("R2010")
    _set_hatch_header_defaults(doc, default_hatch_scale=hatch_scale)
    doc.header["$INSUNITS"] = 6
    korean_text_style = _ensure_korean_text_style(doc)
    msp = doc.modelspace()
    _ensure_template_layers(doc)
    _ensure_layer(doc, "STORY_LABEL", color=4)

    story_drawings = []
    source_bboxes: list[BBox2D] = []
    total_elements = 0
    total_warnings = 0
    tol = abs(float(story_tolerance))
    for story in story_list:
        primitives, points, element_count, warnings = _story_centerline_primitives(story, node_map, element_list, tol)
        bbox = bbox_from_points(points)
        story_drawings.append((story, primitives, bbox))
        source_bboxes.append(bbox)
        total_elements += element_count
        total_warnings += warnings

    layouts = plan_story_layouts(story_list, source_bboxes)
    point_display_size = _compute_common_point_display_size(source_bboxes)
    _set_point_display_defaults(doc, point_size=point_display_size)
    for (story, primitives, _bbox), layout in zip(story_drawings, layouts):
        _draw_story_primitives(msp, primitives, layout.transform.apply)
        msp.add_text(
            story.name,
            dxfattribs={"layer": "STORY_LABEL", "height": layout.text_height, "style": korean_text_style},
        ).set_placement((layout.label_x, layout.label_y))

    _add_guide_text_below_geometry(
        msp,
        Story("ALL_STORIES", 0.0),
        _bounds_from_layouts(layouts),
        korean_text_style,
        default_hatch_scale=hatch_scale,
    )
    _write_load_layers(doc, load_layer_list)

    try:
        doc.saveas(out)
    except PermissionError as exc:
        raise PermissionError(f"DXF 파일 저장 권한이 없습니다: {out}") from exc

    mapping_json = out.with_suffix(".layer_mapping.json")
    mapping_csv = out.with_suffix(".layer_mapping.csv")
    mapping_rows = _load_layer_mapping_rows(load_layer_list)
    mapping_json.write_text(json.dumps(mapping_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    mapping_csv.write_text(_mapping_csv(mapping_rows), encoding="utf-8-sig")
    layout_metadata = out.with_suffix(".layout_metadata.json")
    write_layout_metadata(layout_metadata, layouts)
    return DxfTemplateResult(out, mapping_json, mapping_csv, total_elements, total_warnings, layout_metadata, len(story_list))


def _ensure_layer(doc, name: str, color: int) -> None:
    if name not in doc.layers:
        doc.layers.add(name, color=color)


def _ensure_template_layers(doc) -> None:
    _ensure_layer(doc, "CENTERLINE_COLUMN", color=2)
    _ensure_layer(doc, "CENTERLINE_BEAM", color=7)
    _ensure_layer(doc, "CENTERLINE_WALL", color=3)
    _ensure_layer(doc, "REFERENCE_GRID", color=8)
    _ensure_layer(doc, "LOAD_DL_0.0_LL_0.0", color=1)
    _ensure_layer(doc, "FLOAD_GUIDE", color=6)
    _ensure_layer(doc, HATCH_GUIDE_LAYER, color=2)
    for layer in DIRECTION_LAYERS:
        _ensure_layer(doc, layer, color=1)
    _ensure_layer(doc, "FLOAD_DIRECTION_GUIDE", color=3)


def _set_hatch_header_defaults(doc, *, default_hatch_scale: float = DEFAULT_HATCH_SCALE) -> None:
    scale = normalize_hatch_scale(default_hatch_scale)
    for name, value in (
        ("$HPSCALE", scale),
        ("$HPANG", 0.0),
        ("$HPNAME", "ANSI31"),
    ):
        try:
            doc.header[name] = value
        except Exception:
            pass


def _set_point_display_defaults(doc, *, point_size: float) -> None:
    for name, value in (
        ("$PDMODE", 34),
        ("$PDSIZE", float(point_size)),
    ):
        try:
            doc.header[name] = value
        except Exception:
            pass


def _bounds_from_layouts(layouts) -> list[float | None]:
    bounds = _empty_bounds()
    for layout in layouts:
        bbox = layout.placed_bbox
        _expand_bounds(bounds, [(bbox.min_x, bbox.min_y), (bbox.max_x, bbox.max_y)])
    return bounds


def _bounds_to_bbox(bounds: Sequence[float | None]) -> BBox2D:
    min_x, min_y, max_x, max_y = bounds
    if min_x is None or min_y is None or max_x is None or max_y is None:
        return BBox2D(-0.5, -0.5, 0.5, 0.5)
    return BBox2D(float(min_x), float(min_y), float(max_x), float(max_y))


def _bbox_reference_dimension(bbox: BBox2D) -> float:
    width = max(float(bbox.width), 0.0)
    height = max(float(bbox.height), 0.0)
    if width > 0.0 and height > 0.0:
        return min(width, height)
    return max(width, height, 1.0)


def _compute_point_display_size(bbox: BBox2D) -> float:
    ref = _bbox_reference_dimension(bbox)
    return _clamp(ref * 0.012, ref * 0.004, ref * 0.025)


def _compute_point_display_size_from_bounds(bounds: Sequence[float | None]) -> float:
    return _compute_point_display_size(_bounds_to_bbox(bounds))


def _compute_common_point_display_size(bboxes: Sequence[BBox2D]) -> float:
    if not bboxes:
        return _compute_point_display_size(BBox2D(-0.5, -0.5, 0.5, 0.5))
    return float(median(_compute_point_display_size(bbox) for bbox in bboxes))


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(value), float(maximum)))


def _load_layer_mapping_rows(load_layers: list[LoadLayerSpec]) -> list[dict]:
    rows = []
    for index, layer_spec in enumerate(load_layers, start=1):
        spec = layer_spec.with_layer(index)
        rows.append({"layer": spec.layer, "real_name": spec.real_name, "DL": spec.dl, "LL": spec.ll})
    if not rows:
        spec = LoadLayerSpec("기본하중", 0.0, 0.0).with_layer(1)
        rows.append({"layer": spec.layer, "real_name": spec.real_name, "DL": spec.dl, "LL": spec.ll})
    return rows


def _write_load_layers(doc, load_layers: list[LoadLayerSpec]) -> None:
    for index, row in enumerate(_load_layer_mapping_rows(load_layers), start=1):
        _ensure_layer(doc, str(row["layer"]), color=(index % 7) + 1)


def _story_centerline_primitives(
    story: Story,
    node_map: dict[int, Node],
    elements: list[Element],
    tol: float,
) -> tuple[list[tuple], list[tuple[float, float]], int, int]:
    primitives: list[tuple] = []
    points: list[tuple[float, float]] = []
    element_count = 0
    warnings = 0
    for elem in elements:
        pts = [node_map[nid] for nid in elem.node_ids if nid in node_map]
        if len(pts) < 2:
            continue
        story_pts = [p for p in pts if abs(p.z - story.elevation) <= tol]
        if elem.elem_type in {"BEAM", "TRUSS", "TENSTR", "COMPTR"}:
            if len(story_pts) >= 2:
                line = (story_pts[0].xy, story_pts[1].xy)
                primitives.append(("line", "CENTERLINE_BEAM", line))
                points.extend(line)
                element_count += 1
            elif len(story_pts) == 1:
                primitives.append(("column", "CENTERLINE_COLUMN", story_pts[0].xy))
                points.append(story_pts[0].xy)
                element_count += 1
            continue
        if elem.elem_type in {"COLUMN"}:
            p = _representative_xy(story_pts or pts)
            if p:
                primitives.append(("column", "CENTERLINE_COLUMN", p))
                points.append(p)
                element_count += 1
            continue
        if elem.elem_type in {"WALL", "PLATE", "SLAB", "PLANAR"} or len(pts) >= 3:
            if len(story_pts) >= 2:
                xy = _unique_xy([p.xy for p in story_pts])
                if len(xy) == 2:
                    primitives.append(("line", "CENTERLINE_WALL", (xy[0], xy[1])))
                    points.extend(xy)
                    element_count += 1
                elif len(xy) > 2:
                    primitives.append(("polyline", "REFERENCE_GRID", xy, True))
                    points.extend(xy)
                    element_count += 1
            elif len(story_pts) == 1:
                primitives.append(("column", "CENTERLINE_COLUMN", story_pts[0].xy))
                points.append(story_pts[0].xy)
                element_count += 1
            else:
                warnings += 1
    return primitives, points, element_count, warnings


def _draw_story_primitives(msp, primitives: list[tuple], transform) -> None:
    for primitive in primitives:
        kind = primitive[0]
        if kind == "line":
            _kind, layer, (p1, p2) = primitive
            msp.add_line(transform(*p1), transform(*p2), dxfattribs={"layer": layer})
        elif kind == "polyline":
            _kind, layer, points, close = primitive
            msp.add_lwpolyline([transform(*p) for p in points], close=close, dxfattribs={"layer": layer})
        elif kind == "column":
            _kind, layer, point = primitive
            _add_column_point_symbol(msp, transform(*point), layer=layer)


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


def _empty_bounds() -> list[float | None]:
    return [None, None, None, None]


def _expand_bounds(bounds: list[float | None], points: Iterable[tuple[float, float]]) -> None:
    for x, y in points:
        fx = float(x)
        fy = float(y)
        if bounds[0] is None or fx < bounds[0]:
            bounds[0] = fx
        if bounds[1] is None or fy < bounds[1]:
            bounds[1] = fy
        if bounds[2] is None or fx > bounds[2]:
            bounds[2] = fx
        if bounds[3] is None or fy > bounds[3]:
            bounds[3] = fy


def _add_guide_text_below_geometry(
    msp,
    story: Story,
    bounds: list[float | None],
    korean_text_style: str,
    *,
    default_hatch_scale: float = DEFAULT_HATCH_SCALE,
) -> None:
    hatch_scale = normalize_hatch_scale(default_hatch_scale)
    min_x, min_y, max_x, max_y = bounds
    if min_x is None or min_y is None or max_x is None or max_y is None:
        base_x = 0.0
        base_y = -3.0
        title_height = 0.4
        note_height = 0.25
    else:
        span_x = max(float(max_x) - float(min_x), 1.0)
        span_y = max(float(max_y) - float(min_y), 1.0)
        span = max(span_x, span_y)
        title_height = max(0.25, min(span / 80.0, 1.0))
        note_height = max(0.18, title_height * 0.65)
        margin = max(title_height * 4.0, span_y * 0.05, 1.0)
        base_x = float(min_x)
        base_y = float(min_y) - margin

    msp.add_text(
        f"MIDAS Floor Load Template / Story={story.name} / Elev={story.elevation:g}",
        dxfattribs={"layer": "FLOAD_GUIDE", "height": title_height, "style": korean_text_style},
    ).set_placement((base_x, base_y))
    line_gap = max(title_height * 1.5, note_height * 2.0, 0.5)
    notes = [
        "하중영역은 LOAD_* 레이어에 HATCH로 작성하세요. HATCH 실패 시 폐합 LWPOLYLINE을 fallback으로 읽습니다.",
        f"권장 HATCH 축척: {_fmt_float(hatch_scale)}",
        f"CAD에서 HATCH 패턴이 너무 크게 보이면 HATCH SCALE을 {_fmt_float(hatch_scale)}로 설정하세요.",
        "SOLID HATCH = TWO WAY. SOLID가 아닌 HATCH = ONE WAY.",
        "ONE WAY 방향선은 ONE WAY SLAB DIRECTION 레이어에 시작점-끝점 방향으로 작성하세요.",
        "방향선은 여러 HATCH를 연속 통과하는 긴 선으로 그릴 수 있으며, 통과한 각 HATCH에 적용됩니다.",
        "HATCH와 교차하지 않는 외부 평행 방향선은 기본적으로 무시됩니다.",
        "기둥 위치는 CENTERLINE_COLUMN 레이어의 POINT로 표시하며, HATCH island가 생기지 않도록 박스/원 객체를 쓰지 않습니다.",
        "CAD에서 점이 작게 보이면 PDMODE/PDSIZE 설정을 확인하세요.",
    ]
    for index, text in enumerate(notes, start=1):
        msp.add_text(
            text,
            dxfattribs={"layer": "FLOAD_GUIDE", "height": note_height, "style": korean_text_style},
        ).set_placement((base_x, base_y - line_gap * index))
    _add_hatch_scale_guide(msp, base_x, base_y - line_gap * (len(notes) + 1.3), note_height, hatch_scale)


def _add_hatch_scale_guide(msp, base_x: float, base_y: float, note_height: float, hatch_scale: float) -> None:
    width = max(note_height * 18.0, 2.0)
    height = max(note_height * 8.0, 1.0)
    points = [
        (base_x, base_y),
        (base_x + width, base_y),
        (base_x + width, base_y - height),
        (base_x, base_y - height),
    ]
    try:
        hatch = msp.add_hatch(dxfattribs={"layer": HATCH_GUIDE_LAYER})
        hatch.set_pattern_fill("ANSI31", scale=normalize_hatch_scale(hatch_scale))
        hatch.paths.add_polyline_path(points, is_closed=True)
    except Exception:
        return


def _add_column_point_symbol(msp, xy: tuple[float, float], *, layer: str = "CENTERLINE_COLUMN") -> None:
    x, y = xy
    msp.add_point((float(x), float(y)), dxfattribs={"layer": layer})


def _unique_xy(points: list[tuple[float, float]], ndigits: int = 8) -> list[tuple[float, float]]:
    result = []
    seen = set()
    for x, y in points:
        key = (round(x, ndigits), round(y, ndigits))
        if key in seen:
            continue
        seen.add(key)
        result.append((float(x), float(y)))
    return result


def _representative_xy(nodes: list[Node]) -> tuple[float, float] | None:
    if not nodes:
        return None
    return (sum(p.x for p in nodes) / len(nodes), sum(p.y for p in nodes) / len(nodes))


def _fmt_float(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _mapping_csv(rows: list[dict]) -> str:
    lines = ["layer,real_name,DL,LL"]
    for row in rows:
        layer = str(row["layer"]).replace('"', '""')
        name = str(row["real_name"]).replace('"', '""')
        lines.append(f'"{layer}","{name}",{row["DL"]},{row["LL"]}')
    return "\n".join(lines) + "\n"
