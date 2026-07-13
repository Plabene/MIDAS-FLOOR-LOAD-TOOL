from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence
import json
import math

import ezdxf
from ezdxf.enums import TextEntityAlignment

from .dxf_story_layout import (
    BBox2D,
    annotate_layout_typical_metadata,
    bbox_from_points,
    normalize_dxf_unit_scale as _normalize_dxf_unit_scale,
    plan_story_layouts,
    write_layout_metadata,
)
from .load_parser import add_cad_direction_layer_prefix, add_cad_load_layer_prefix, make_safe_load_layer_name
from .mgt_parser import Element, Node, Story, dxf_insunits_for_output_mm
from .story_view_filter import StoryBelowRange, element_is_in_story_below_range, story_below_range


INTERNAL_HATCH_SCALE = 1.0
DEFAULT_HATCH_SCALE = INTERNAL_HATCH_SCALE
HATCH_GUIDE_LAYER = "FLOAD_HATCH_GUIDE"
CENTERLINE_BEAM_TYPES = {"BEAM", "TRUSS", "TENSTR", "COMPTR"}
CENTERLINE_WALL_EDGE_TYPES = {"WALL", "PLATE", "SHELL", "PLANE", "PLANAR", "QUAD"}
WALL_EDGE_LONGEST_PAIR_FALLBACK = "WALL_EDGE_LONGEST_PAIR_FALLBACK"
LOAD_LAYER_ACI_COLORS = (
    1,
    2,
    3,
    4,
    6,
    30,
    40,
    50,
    70,
    90,
    110,
    130,
    150,
    170,
    190,
    210,
    230,
)


@dataclass(frozen=True)
class LoadLayerSpec:
    real_name: str
    dl: float
    ll: float
    layer: str = ""

    def with_layer(self, index: int) -> "LoadLayerSpec":
        layer = self.layer or make_safe_load_layer_name(index, self.real_name, self.dl, self.ll)
        return LoadLayerSpec(self.real_name, self.dl, self.ll, layer)


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


def normalize_dxf_unit_scale(value) -> float:
    return _normalize_dxf_unit_scale(value)


def write_story_centerline_dxf(
    *,
    output_path: str | Path,
    story: Story,
    stories: Iterable[Story] | None = None,
    nodes: Iterable[Node],
    elements: Iterable[Element],
    load_layers: Iterable[LoadLayerSpec] = (),
    story_tolerance: float = 0.01,
    default_hatch_scale: float = DEFAULT_HATCH_SCALE,
    model_length_unit: str = "",
    dxf_unit_scale_from_model: float = 1.0,
    typical_story_names: Iterable[str] = (),
    typical_floor_groups: Iterable[object] = (),
) -> DxfTemplateResult:
    del default_hatch_scale
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    node_list = list(nodes)
    element_list = list(elements)
    load_layer_list = list(load_layers)
    node_map = {node.node_id: node for node in node_list}
    unit_scale = normalize_dxf_unit_scale(dxf_unit_scale_from_model)
    tol = abs(float(story_tolerance))

    story_list = list(stories or [story])
    story_range = story_below_range(story_list, story, tol)
    primitives, points, element_count, warnings = _story_centerline_primitives(
        story,
        node_map,
        element_list,
        tol,
        story_range=story_range,
    )
    source_bbox = bbox_from_points(_layout_points_for_story(points, node_list, story, tol))
    layouts = plan_story_layouts([story], [source_bbox], dxf_unit_scale_from_model=unit_scale)
    layouts = _apply_typical_layout_metadata(
        layouts,
        typical_story_names=typical_story_names,
        typical_floor_groups=typical_floor_groups,
    )
    layouts = _with_common_story_label_text_height(layouts)

    doc = ezdxf.new("R2010")
    _set_hatch_header_defaults(doc, default_hatch_scale=INTERNAL_HATCH_SCALE)
    _set_mm_document_units(doc)
    korean_text_style = _ensure_korean_text_style(doc)
    msp = doc.modelspace()
    _ensure_template_layers(doc)
    _draw_story_layouts(msp, [(story, primitives)], layouts, korean_text_style)
    _set_point_display_defaults(doc, point_size=_compute_common_point_display_size([layout.placed_bbox for layout in layouts]))
    _add_guide_text_below_geometry(
        msp,
        story,
        _bounds_from_layouts(layouts),
        korean_text_style,
        default_hatch_scale=INTERNAL_HATCH_SCALE,
        model_length_unit=model_length_unit,
        dxf_unit_scale_from_model=unit_scale,
    )
    _write_load_layers(doc, load_layer_list)

    mapping_rows = _load_layer_mapping_rows(load_layer_list)
    mapping_json = out.with_suffix(".layer_mapping.json")
    mapping_csv = out.with_suffix(".layer_mapping.csv")
    layout_metadata = out.with_suffix(".layout_metadata.json")
    _save_template_outputs(
        doc=doc,
        dxf_path=out,
        mapping_json=mapping_json,
        mapping_csv=mapping_csv,
        mapping_rows=mapping_rows,
        layout_metadata=layout_metadata,
        layouts=layouts,
        metadata_mode="SINGLE_STORY",
        model_length_unit=model_length_unit,
        dxf_unit_scale_from_model=unit_scale,
    )
    return DxfTemplateResult(out, mapping_json, mapping_csv, element_count, warnings, layout_metadata, 1)


def write_all_story_centerline_dxf(
    *,
    output_path: str | Path,
    stories: Iterable[Story],
    nodes: Iterable[Node],
    elements: Iterable[Element],
    load_layers: Iterable[LoadLayerSpec] = (),
    story_tolerance: float = 0.01,
    default_hatch_scale: float = DEFAULT_HATCH_SCALE,
    model_length_unit: str = "",
    dxf_unit_scale_from_model: float = 1.0,
    typical_story_names: Iterable[str] = (),
    typical_floor_groups: Iterable[object] = (),
) -> DxfTemplateResult:
    del default_hatch_scale
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    story_list = list(stories)
    node_list = list(nodes)
    element_list = list(elements)
    load_layer_list = list(load_layers)
    node_map = {node.node_id: node for node in node_list}
    unit_scale = normalize_dxf_unit_scale(dxf_unit_scale_from_model)
    tol = abs(float(story_tolerance))

    story_drawings: list[tuple[Story, list[tuple]]] = []
    source_bboxes: list[BBox2D] = []
    total_elements = 0
    total_warnings = 0
    for story in story_list:
        story_range = story_below_range(story_list, story, tol)
        primitives, points, element_count, warnings = _story_centerline_primitives(
            story,
            node_map,
            element_list,
            tol,
            story_range=story_range,
        )
        story_drawings.append((story, primitives))
        source_bboxes.append(bbox_from_points(_layout_points_for_story(points, node_list, story, tol)))
        total_elements += element_count
        total_warnings += warnings

    layouts = plan_story_layouts(story_list, source_bboxes, dxf_unit_scale_from_model=unit_scale)
    layouts = _apply_typical_layout_metadata(
        layouts,
        typical_story_names=typical_story_names,
        typical_floor_groups=typical_floor_groups,
    )
    layouts = _with_common_story_label_text_height(layouts)

    doc = ezdxf.new("R2010")
    _set_hatch_header_defaults(doc, default_hatch_scale=INTERNAL_HATCH_SCALE)
    _set_mm_document_units(doc)
    korean_text_style = _ensure_korean_text_style(doc)
    msp = doc.modelspace()
    _ensure_template_layers(doc)
    _draw_story_layouts(msp, story_drawings, layouts, korean_text_style)
    _set_point_display_defaults(doc, point_size=_compute_common_point_display_size([layout.placed_bbox for layout in layouts]))
    _add_guide_text_below_geometry(
        msp,
        Story("ALL_STORIES", 0.0),
        _bounds_from_layouts(layouts),
        korean_text_style,
        default_hatch_scale=INTERNAL_HATCH_SCALE,
        model_length_unit=model_length_unit,
        dxf_unit_scale_from_model=unit_scale,
    )
    _write_load_layers(doc, load_layer_list)

    mapping_rows = _load_layer_mapping_rows(load_layer_list)
    mapping_json = out.with_suffix(".layer_mapping.json")
    mapping_csv = out.with_suffix(".layer_mapping.csv")
    layout_metadata = out.with_suffix(".layout_metadata.json")
    _save_template_outputs(
        doc=doc,
        dxf_path=out,
        mapping_json=mapping_json,
        mapping_csv=mapping_csv,
        mapping_rows=mapping_rows,
        layout_metadata=layout_metadata,
        layouts=layouts,
        metadata_mode="ALL_STORIES",
        model_length_unit=model_length_unit,
        dxf_unit_scale_from_model=unit_scale,
    )
    return DxfTemplateResult(out, mapping_json, mapping_csv, total_elements, total_warnings, layout_metadata, len(story_list))


def _save_template_outputs(
    *,
    doc,
    dxf_path: Path,
    mapping_json: Path,
    mapping_csv: Path,
    mapping_rows: list[dict],
    layout_metadata: Path,
    layouts,
    metadata_mode: str,
    model_length_unit: str,
    dxf_unit_scale_from_model: float,
) -> None:
    try:
        doc.saveas(dxf_path)
    except PermissionError as exc:
        raise PermissionError(f"DXF file is open or not writable: {dxf_path}") from exc

    try:
        mapping_json.write_text(json.dumps(mapping_rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        mapping_csv.write_text(_mapping_csv(mapping_rows), encoding="utf-8-sig")
        write_layout_metadata(
            layout_metadata,
            layouts,
            mode=metadata_mode,
            model_length_unit=model_length_unit,
            dxf_unit_scale_from_model=dxf_unit_scale_from_model,
        )
    except PermissionError as exc:
        raise PermissionError(f"Template sidecar files are open or not writable near: {dxf_path}") from exc


def _draw_story_layouts(msp, story_drawings: Sequence[tuple[Story, list[tuple]]], layouts, korean_text_style: str) -> None:
    for (story, primitives), layout in zip(story_drawings, layouts):
        _draw_story_primitives(msp, primitives, layout.transform.apply)
        label_text = f"typ. {story.name}" if bool(getattr(layout, "is_typical", False)) else story.name
        msp.add_text(
            label_text,
            dxfattribs={"layer": "STORY_LABEL", "height": layout.text_height, "style": korean_text_style},
        ).set_placement((layout.label_x, layout.label_y), align=TextEntityAlignment.RIGHT)


def _apply_typical_layout_metadata(
    layouts,
    *,
    typical_story_names: Iterable[str] = (),
    typical_floor_groups: Iterable[object] = (),
):
    group_by_story: dict[str, str] = {}
    typical_by_group: dict[str, str] = {}
    typical_names = [str(name) for name in typical_story_names if str(name or "").strip()]
    for index, group in enumerate(typical_floor_groups or (), start=1):
        group_id = str(getattr(group, "group_id", "") or f"G{index:03d}")
        group_typical = str(getattr(group, "typical_story_name", "") or "")
        if group_typical:
            typical_by_group[group_id] = group_typical
            typical_names.append(group_typical)
        for story_name in tuple(getattr(group, "story_names", ()) or ()):
            group_by_story[str(story_name)] = group_id
    return annotate_layout_typical_metadata(
        layouts,
        typical_story_names=typical_names,
        typical_group_by_story=group_by_story,
        typical_story_by_group=typical_by_group,
    )


def _with_common_story_label_text_height(layouts):
    layout_list = list(layouts or ())
    heights = [float(getattr(layout, "text_height", 0.0) or 0.0) for layout in layout_list]
    common_height = max(heights) if heights else 0.0
    if common_height <= 0.0:
        return layout_list
    return [replace(layout, text_height=common_height) for layout in layout_list]


def _ensure_layer(doc, name: str, color: int, *, plot: bool = True) -> None:
    if name not in doc.layers:
        doc.layers.add(name, color=color)
    try:
        doc.layers.get(name).dxf.plot = 1 if plot else 0
    except Exception:
        pass


def _ensure_template_layers(doc) -> None:
    _ensure_layer(doc, "CENTERLINE_COLUMN", color=2, plot=False)
    _ensure_layer(doc, "CENTERLINE_BEAM", color=7, plot=False)
    _ensure_layer(doc, "CENTERLINE_WALL", color=3, plot=False)
    _ensure_layer(doc, "REFERENCE_GRID", color=8, plot=False)
    _ensure_layer(doc, "FLOAD_GUIDE", color=6, plot=False)
    _ensure_layer(doc, HATCH_GUIDE_LAYER, color=2, plot=False)
    _ensure_layer(doc, "STORY_LABEL", color=4, plot=False)
    _ensure_layer(doc, add_cad_direction_layer_prefix("ONE WAY SLAB DIRECTION"), color=1)
    _ensure_layer(doc, "FLOAD_DIRECTION_GUIDE", color=3, plot=False)


def _set_mm_document_units(doc) -> None:
    insunits = dxf_insunits_for_output_mm()
    try:
        doc.header["$INSUNITS"] = insunits
    except Exception:
        pass
    try:
        doc.header["$MEASUREMENT"] = 1
    except Exception:
        pass
    try:
        doc.units = insunits
    except Exception:
        pass


def _set_hatch_header_defaults(doc, *, default_hatch_scale: float = DEFAULT_HATCH_SCALE) -> None:
    scale = normalize_hatch_scale(default_hatch_scale, default=INTERNAL_HATCH_SCALE)
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
    rows: list[dict] = []
    for index, layer_spec in enumerate(load_layers, start=1):
        spec = layer_spec.with_layer(index)
        core_layer = spec.layer
        aci_color = load_layer_aci_color(index)
        rows.append(
            {
                "layer": add_cad_load_layer_prefix(core_layer),
                "core_layer": core_layer,
                "real_name": spec.real_name,
                "DL": spec.dl,
                "LL": spec.ll,
                "aci_color": aci_color,
            }
        )
    if not rows:
        spec = LoadLayerSpec("Default Load", 0.0, 0.0).with_layer(1)
        rows.append(
            {
                "layer": add_cad_load_layer_prefix(spec.layer),
                "core_layer": spec.layer,
                "real_name": spec.real_name,
                "DL": spec.dl,
                "LL": spec.ll,
                "aci_color": load_layer_aci_color(1),
            }
        )
    return rows


def load_layer_aci_color(index: int) -> int:
    palette = LOAD_LAYER_ACI_COLORS
    if not palette:
        return 1
    return int(palette[(max(int(index), 1) - 1) % len(palette)])


def _write_load_layers(doc, load_layers: list[LoadLayerSpec]) -> None:
    for index, row in enumerate(_load_layer_mapping_rows(load_layers), start=1):
        _ensure_layer(doc, str(row["layer"]), color=int(row.get("aci_color") or load_layer_aci_color(index)))


def _story_centerline_primitives(
    story: Story,
    node_map: dict[int, Node],
    elements: list[Element],
    tol: float,
    *,
    story_range: StoryBelowRange | None = None,
) -> tuple[list[tuple], list[tuple[float, float]], int, int]:
    if story_range is None:
        story_range = story_below_range([story], story, tol)
    primitives: list[tuple] = []
    points: list[tuple[float, float]] = []
    element_count = 0
    warnings = 0
    for elem in elements:
        pts = [node_map[nid] for nid in elem.node_ids if nid in node_map]
        if len(pts) < 2:
            continue
        if not element_is_in_story_below_range(elem, node_map, story_range, tol):
            continue
        story_pts = [p for p in pts if abs(p.z - story.elevation) <= tol]
        elem_type = _normal_element_type(elem.elem_type)
        if elem_type in CENTERLINE_BEAM_TYPES:
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
        if elem_type in {"COLUMN"}:
            point = _representative_xy(story_pts)
            if point:
                primitives.append(("column", "CENTERLINE_COLUMN", point))
                points.append(point)
                element_count += 1
            continue
        if elem_type in CENTERLINE_WALL_EDGE_TYPES:
            fallback_reasons: list[str] = []
            edge_xy = _story_wall_edge_xy(pts, story.elevation, tol, fallback_reasons=fallback_reasons)
            if len(edge_xy) >= 2:
                for first, second in zip(edge_xy, edge_xy[1:]):
                    line = (first, second)
                    primitives.append(("line", "CENTERLINE_WALL", line))
                    points.extend(line)
                element_count += 1
                warnings += len(fallback_reasons)
            elif not _is_horizontal_at_story(pts, story.elevation, tol):
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
            msp.add_lwpolyline([transform(*point) for point in points], close=close, dxfattribs={"layer": layer})
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
    model_length_unit: str = "",
    dxf_unit_scale_from_model: float = 1.0,
) -> None:
    hatch_scale = normalize_hatch_scale(default_hatch_scale, default=INTERNAL_HATCH_SCALE)
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
        title_height = max(0.25, min(span / 80.0, 100.0))
        note_height = max(0.18, title_height * 0.65)
        margin = max(title_height * 4.0, span_y * 0.05, 1.0)
        base_x = float(min_x)
        base_y = float(min_y) - margin

    unit = str(model_length_unit or "UNKNOWN").upper()
    scale = normalize_dxf_unit_scale(dxf_unit_scale_from_model)
    msp.add_text(
        f"MIDAS Floor Load Template / Story={story.name} / Elev={story.elevation:g}",
        dxfattribs={"layer": "FLOAD_GUIDE", "height": title_height, "style": korean_text_style},
    ).set_placement((base_x, base_y))
    line_gap = max(title_height * 1.5, note_height * 2.0, 0.5)
    notes = [
        f"DXF unit: millimeters. Model length unit={unit}; model-to-DXF scale={_fmt_float(scale)}.",
        "Layout metadata is required for import; it converts CAD mm coordinates back to model coordinates.",
        f"Draw load areas as HATCH on {add_cad_load_layer_prefix('LOAD_*')} layers. Closed LWPOLYLINE also works.",
        "SOLID HATCH = TWO WAY. Non-SOLID HATCH = ONE WAY.",
        f"Draw one-way direction lines on {add_cad_direction_layer_prefix('ONE WAY SLAB DIRECTION')} from start to end.",
        "A direction line that crosses several HATCH areas applies to each crossed HATCH.",
        "Column locations are POINT entities on CENTERLINE_COLUMN so they do not create HATCH islands.",
        "If column points are hard to see in CAD, adjust PDMODE/PDSIZE display settings.",
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
        hatch.set_pattern_fill("ANSI31", scale=normalize_hatch_scale(hatch_scale, default=INTERNAL_HATCH_SCALE))
        hatch.paths.add_polyline_path(points, is_closed=True)
    except Exception:
        return


def _add_column_point_symbol(msp, xy: tuple[float, float], *, layer: str = "CENTERLINE_COLUMN") -> None:
    x, y = xy
    msp.add_point((float(x), float(y)), dxfattribs={"layer": layer})


def _normal_element_type(value: str) -> str:
    return str(value or "").replace(" ", "").replace("-", "_").upper()


def _is_horizontal_at_story(nodes: Sequence[Node], story_elevation: float, tol: float) -> bool:
    if not nodes:
        return False
    story_z = float(story_elevation)
    tolerance = max(abs(float(tol)), 1.0e-9)
    return all(abs(float(node.z) - story_z) <= tolerance for node in nodes)


def _story_wall_edge_xy(
    nodes: Sequence[Node],
    story_elevation: float,
    tol: float,
    *,
    fallback_reasons: list[str] | None = None,
) -> list[tuple[float, float]]:
    if _is_horizontal_at_story(nodes, story_elevation, tol):
        return []
    story_z = float(story_elevation)
    tolerance = max(abs(float(tol)), 1.0e-9)
    story_nodes = [node for node in nodes if abs(float(node.z) - story_z) <= tolerance]
    edge_nodes = _unique_nodes_by_xy(story_nodes)
    if len(edge_nodes) <= 2:
        return [(float(node.x), float(node.y)) for node in edge_nodes]

    ordered_edge = _ordered_story_edge_node_run(nodes, story_z, tolerance)
    if len(ordered_edge) >= 2:
        return [(float(node.x), float(node.y)) for node in ordered_edge]

    fallback = _longest_pair_nodes(edge_nodes)
    if len(fallback) >= 2 and fallback_reasons is not None:
        fallback_reasons.append(WALL_EDGE_LONGEST_PAIR_FALLBACK)
    return [(float(node.x), float(node.y)) for node in fallback]


def _unique_nodes_by_xy(nodes: Sequence[Node]) -> list[Node]:
    result: list[Node] = []
    seen = set()
    for node in nodes:
        key = (round(float(node.x), 9), round(float(node.y), 9))
        if key in seen:
            continue
        seen.add(key)
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


def _layout_points_for_story(
    primitive_points: Sequence[tuple[float, float]],
    nodes: Sequence[Node],
    story: Story,
    tol: float,
) -> list[tuple[float, float]]:
    if primitive_points:
        return [(float(x), float(y)) for x, y in primitive_points]
    story_z = float(story.elevation)
    tolerance = max(abs(float(tol)), 1.0e-9)
    return [(float(node.x), float(node.y)) for node in nodes if abs(float(node.z) - story_z) <= tolerance]


def _unique_xy(points: list[tuple[float, float]], ndigits: int = 8) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
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
    return (sum(point.x for point in nodes) / len(nodes), sum(point.y for point in nodes) / len(nodes))


def _fmt_float(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _mapping_csv(rows: list[dict]) -> str:
    lines = ["layer,core_layer,real_name,DL,LL,aci_color"]
    for row in rows:
        layer = str(row["layer"]).replace('"', '""')
        core_layer = str(row.get("core_layer") or "").replace('"', '""')
        name = str(row["real_name"]).replace('"', '""')
        lines.append(f'"{layer}","{core_layer}","{name}",{row["DL"]},{row["LL"]},{row.get("aci_color") or ""}')
    return "\n".join(lines) + "\n"
