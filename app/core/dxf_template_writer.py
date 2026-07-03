from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
import json

import ezdxf

from .load_parser import make_safe_load_layer_name
from .mgt_parser import Element, Node, Story


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


def write_story_centerline_dxf(
    *,
    output_path: str | Path,
    story: Story,
    nodes: Iterable[Node],
    elements: Iterable[Element],
    load_layers: Iterable[LoadLayerSpec] = (),
    story_tolerance: float = 0.01,
) -> DxfTemplateResult:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    node_map = {n.node_id: n for n in nodes}
    doc = ezdxf.new("R2010")
    doc.header["$INSUNITS"] = 6  # meter, if CAD honors it.
    korean_text_style = _ensure_korean_text_style(doc)
    msp = doc.modelspace()
    _ensure_layer(doc, "CENTERLINE_COLUMN", color=2)
    _ensure_layer(doc, "CENTERLINE_BEAM", color=7)
    _ensure_layer(doc, "CENTERLINE_WALL", color=3)
    _ensure_layer(doc, "REFERENCE_GRID", color=8)
    _ensure_layer(doc, "LOAD_DL_0.0_LL_0.0", color=1)
    _ensure_layer(doc, "FLOAD_GUIDE", color=6)

    element_count = 0
    warnings = 0
    bounds = _empty_bounds()
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
                _add_column_marker(msp, story_pts[0].xy)
                _expand_bounds(bounds, [story_pts[0].xy])
                element_count += 1
            continue
        if elem.elem_type in {"COLUMN"}:
            p = _representative_xy(story_pts or pts)
            if p:
                _add_column_marker(msp, p)
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
                _add_column_marker(msp, story_pts[0].xy)
                _expand_bounds(bounds, [story_pts[0].xy])
                element_count += 1
            else:
                warnings += 1

    _add_guide_text_below_geometry(msp, story, bounds, korean_text_style)

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


def _add_guide_text_below_geometry(msp, story: Story, bounds: list[float | None], korean_text_style: str) -> None:
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
    msp.add_text(
        "하중영역은 LOAD_* 레이어에 HATCH로 작성하세요. HATCH 실패 시 폐합 LWPOLYLINE을 fallback으로 읽습니다.",
        dxfattribs={"layer": "FLOAD_GUIDE", "height": note_height, "style": korean_text_style},
    ).set_placement((base_x, base_y - max(title_height * 1.5, note_height * 2.0, 0.5)))


def _add_column_marker(msp, xy: tuple[float, float], size: float = 0.25) -> None:
    x, y = xy
    msp.add_line((x - size, y), (x + size, y), dxfattribs={"layer": "CENTERLINE_COLUMN"})
    msp.add_line((x, y - size), (x, y + size), dxfattribs={"layer": "CENTERLINE_COLUMN"})


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


def _mapping_csv(rows: list[dict]) -> str:
    lines = ["layer,real_name,DL,LL"]
    for row in rows:
        layer = str(row["layer"]).replace('"', '""')
        name = str(row["real_name"]).replace('"', '""')
        lines.append(f'"{layer}","{name}",{row["DL"]},{row["LL"]}')
    return "\n".join(lines) + "\n"
