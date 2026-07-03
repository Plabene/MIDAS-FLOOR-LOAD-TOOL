from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence
import re

import yaml

from coordinate_mapper import CoordinateMapper
from dxf_hatch_reader import HatchRegion, read_dxf_hatches
from floorload_area_detector import FloorLoadAreaMatch, match_hatch_boundary_to_nodes
from floorload_assignment_writer import (
    write_assignment_json,
    write_assignment_log,
    write_mgtx_patch_file,
    write_preview_dxf,
)
from floorload_validation import make_log_record, summarize_log_records
from mgt_model_parser import parse_mgt_nodes, select_floor_nodes

Point2D = tuple[float, float]


@dataclass(frozen=True)
class FloorLoadAssignmentOptions:
    floor_dist_type: str = "AREA"
    direction: str = "GZ"
    group_name: str = "DXF_FLOORLOAD"
    desc_prefix: str = "DXF_HATCH"
    opt_projection: bool = False
    opt_exclude_inner_elem_area: bool = False
    sub_beam_num: int = 0
    sub_beam_angle: float = 0.0
    unit_self_weight: bool = False


def load_layer_mapping(path: str | Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    mapping_path = Path(path)
    if not mapping_path.exists():
        return {}
    with mapping_path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file) or {}


def map_layer_to_floor_load_type(layer_name: str, mapping: dict[str, Any]) -> str | None:
    layer = str(layer_name or "").strip()
    if not layer:
        return None
    case_sensitive = bool(mapping.get("case_sensitive", False))

    direct = mapping.get("direct") or mapping.get("layers") or {}
    direct_match = _lookup_direct(layer, direct, case_sensitive)
    if direct_match:
        return direct_match

    for item in mapping.get("regex", []) or []:
        pattern = item.get("pattern") if isinstance(item, dict) else None
        if not pattern:
            continue
        flags = 0 if case_sensitive else re.IGNORECASE
        match = re.match(pattern, layer, flags=flags)
        if not match:
            continue
        replacement = item.get("floor_load_type_name") or item.get("target") or item.get("name")
        if replacement:
            return match.expand(str(replacement))

    for prefix in mapping.get("strip_prefixes", []) or []:
        if _startswith(layer, str(prefix), case_sensitive):
            stripped = layer[len(str(prefix)) :].strip()
            if stripped:
                alias_match = _lookup_direct(stripped, mapping.get("aliases") or {}, case_sensitive)
                return alias_match or stripped

    aliases = mapping.get("aliases") or {}
    return _lookup_direct(layer, aliases, case_sensitive)


def build_floorload_assignment(
    match: FloorLoadAreaMatch,
    floor_load_type_name: str,
    assignment_id: int,
    options: FloorLoadAssignmentOptions | None = None,
) -> dict[str, Any]:
    options = options or FloorLoadAssignmentOptions()
    return {
        "ID": int(assignment_id),
        "FLOOR_LOAD_TYPE_NAME": floor_load_type_name,
        "FLOOR_DIST_TYPE": options.floor_dist_type,
        "DIR": options.direction,
        "NODES": [int(node_id) for node_id in match.boundary_node_ids],
        "GROUP_NAME": options.group_name,
        "DESC": f"{options.desc_prefix} layer={match.hatch.layer} handle={match.hatch.handle}",
        "OPT_PROJECTION": options.opt_projection,
        "OPT_EXCLUDE_INNER_ELEM_AREA": options.opt_exclude_inner_elem_area,
        "SUB_BEAM_NUM": int(options.sub_beam_num),
        "SUB_BEAM_ANGLE": float(options.sub_beam_angle),
        "UNIT_SELF_WEIGHT": options.unit_self_weight,
    }


def run_floorload_assignment_workflow(
    *,
    dxf_path: str | Path,
    model_path: str | Path,
    output_dir: str | Path,
    mapping_path: str | Path | None,
    z_level: float | None = None,
    floor_name: str | None = None,
    z_tolerance: float = 1.0e-3,
    cad_control_points: Sequence[Point2D] | None = None,
    midas_control_points: Sequence[Point2D] | None = None,
    transform_error_limit: float = 1.0e-3,
    boundary_tolerance: float = 1.0e-6,
    snap_tolerance: float = 0.5,
    area_error_limit: float = 0.20,
    overwrite_mode: str = "append",
    encoding: str = "cp949",
    options: FloorLoadAssignmentOptions | None = None,
) -> dict[str, Any]:
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    mapping = load_layer_mapping(mapping_path)
    hatches = read_dxf_hatches(dxf_path)
    nodes = parse_mgt_nodes(model_path)
    floor_nodes = select_floor_nodes(nodes, z_level=z_level, floor_name=floor_name, z_tolerance=z_tolerance)
    mapper = CoordinateMapper.from_control_points(cad_control_points, midas_control_points)

    transform_blocked = mapper.report.max_error > transform_error_limit
    assignments: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    matches: list[FloorLoadAreaMatch] = []

    for hatch in hatches:
        mapped_name = map_layer_to_floor_load_type(hatch.layer, mapping)
        if not mapped_name:
            records.append(
                make_log_record(
                    hatch,
                    mapped_floor_load_type=None,
                    status="UNMAPPED_LAYER",
                    warnings=["Layer is not mapped to a Floor Load Type; assignment skipped."],
                )
            )
            continue

        if transform_blocked:
            records.append(
                make_log_record(
                    hatch,
                    mapped_floor_load_type=mapped_name,
                    status="TRANSFORM_ERROR_EXCEEDED",
                    warnings=[f"Control-point transform max error {mapper.report.max_error:.6g} exceeds limit {transform_error_limit:.6g}."],
                )
            )
            continue

        match = match_hatch_boundary_to_nodes(
            hatch,
            floor_nodes,
            mapper,
            boundary_tolerance=boundary_tolerance,
            snap_tolerance=snap_tolerance,
            area_error_limit=area_error_limit,
        )
        matches.append(match)
        if not match.is_valid:
            records.append(make_log_record(hatch, mapped_floor_load_type=mapped_name, status=match.status, match=match))
            continue

        assignment = build_floorload_assignment(match, mapped_name, len(assignments) + 1, options=options)
        assignments.append(assignment)
        records.append(make_log_record(hatch, mapped_floor_load_type=mapped_name, status="OK", match=match, assignment=assignment))

    json_path = write_assignment_json(assignments, out_dir / "floorload_assignments.json")
    log_path = write_assignment_log(records, out_dir / "floorload_assignment_log.xlsx")
    preview_path = write_preview_dxf(matches, out_dir / "floorload_assignment_preview.dxf")
    patch_path = write_mgtx_patch_file(
        model_path,
        out_dir / f"{Path(model_path).stem}_floorload_patch.mgtx",
        assignments,
        mode=overwrite_mode,
        encoding=encoding,
    )

    return {
        "assignments": assignments,
        "records": records,
        "summary": summarize_log_records(records),
        "transform_report": mapper.report.to_record(),
        "json_path": json_path,
        "log_path": log_path,
        "preview_path": preview_path,
        "patch_path": patch_path,
        "hatch_count": len(hatches),
        "floor_node_count": len(floor_nodes),
    }


def _lookup_direct(layer: str, mapping: dict[str, Any], case_sensitive: bool) -> str | None:
    if layer in mapping:
        return str(mapping[layer])
    if case_sensitive:
        return None
    lowered = layer.lower()
    for key, value in mapping.items():
        if str(key).lower() == lowered:
            return str(value)
    return None


def _startswith(value: str, prefix: str, case_sensitive: bool) -> bool:
    if case_sensitive:
        return value.startswith(prefix)
    return value.lower().startswith(prefix.lower())