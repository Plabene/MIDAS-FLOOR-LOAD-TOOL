from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Sequence
import csv
import json


HATCH_INPUT_STATE_JSON = "hatch_view_input_state.json"
HATCH_INPUT_STATE_CSV = "hatch_view_input_state.csv"
PIPELINE_AUDIT_JSON = "floorload_pipeline_audit.json"
PIPELINE_AUDIT_CSV = "floorload_pipeline_audit.csv"


@dataclass
class FloorloadAuditEvent:
    audit_id: str
    stage: str
    status: str
    reason_code: str = ""
    message_ko: str = ""
    source: str = ""
    region_key: str = ""
    assignment_id: str = ""
    source_region_keys: tuple[str, ...] = ()
    story_name: str = ""
    load_name: str = ""
    dl: float | None = None
    ll: float | None = None
    distribution: str = ""
    one_way_angle: float | None = None
    area: float | None = None
    polygon_vertex_count: int = 0
    node_count_raw: int = 0
    node_count_simplified: int = 0
    node_ids: tuple[int, ...] = ()
    merge_group_id: str = ""
    final_record_index: int | None = None
    final_mgt_record: str = ""
    skip_reason: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "stage": self.stage,
            "status": self.status,
            "reason_code": self.reason_code,
            "message_ko": self.message_ko,
            "source": self.source,
            "region_key": self.region_key,
            "assignment_id": self.assignment_id,
            "source_region_keys": list(self.source_region_keys),
            "story_name": self.story_name,
            "load_name": self.load_name,
            "dl": self.dl,
            "ll": self.ll,
            "distribution": self.distribution,
            "one_way_angle": self.one_way_angle,
            "area": self.area,
            "polygon_vertex_count": self.polygon_vertex_count,
            "node_count_raw": self.node_count_raw,
            "node_count_simplified": self.node_count_simplified,
            "node_ids": list(self.node_ids),
            "merge_group_id": self.merge_group_id,
            "final_record_index": self.final_record_index,
            "final_mgt_record": self.final_mgt_record,
            "skip_reason": self.skip_reason,
            "data": _jsonable(self.data),
        }


class FloorloadAuditCollector:
    def __init__(self) -> None:
        self.events: list[FloorloadAuditEvent] = []
        self._next_id = 1

    def add(
        self,
        stage: str,
        *,
        status: str = "OK",
        audit_id: str | None = None,
        **kwargs,
    ) -> FloorloadAuditEvent:
        event = FloorloadAuditEvent(
            audit_id=str(audit_id or self._allocate_id()),
            stage=str(stage),
            status=str(status),
            **kwargs,
        )
        self.events.append(event)
        return event

    def _allocate_id(self) -> str:
        value = f"FLA-{self._next_id:05d}"
        self._next_id += 1
        return value

    def to_dicts(self) -> list[dict[str, Any]]:
        return [event.to_dict() for event in self.events]

    def write(self, output_dir: str | Path) -> tuple[Path, Path]:
        return write_floorload_pipeline_audit(self, output_dir)


def write_hatch_view_input_state(
    *,
    output_dir: str | Path,
    model_name: str = "",
    source_dxf_path: str = "",
    layout_metadata_path: str = "",
    display_mode: str = "",
    selected_story: str = "",
    dxf_regions: Sequence[object] = (),
    internal_regions: Sequence[object] = (),
    selected_region_keys: Iterable[str] = (),
    selected_edit_region_keys: Iterable[str] = (),
    continuous_apply_targets_by_region: dict[str, Sequence[str]] | None = None,
    continuous_materialized_targets_by_region: dict[str, Sequence[str]] | None = None,
    dxf_region_key_map: dict[Any, str] | None = None,
) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    selected_dxf = {str(value) for value in selected_region_keys or ()}
    selected_internal = {str(value) for value in selected_edit_region_keys or ()}
    target_map = {str(key): tuple(str(value) for value in values or ()) for key, values in (continuous_apply_targets_by_region or {}).items()}
    materialized_map = {
        str(key): tuple(str(value) for value in values or ())
        for key, values in (continuous_materialized_targets_by_region or {}).items()
    }

    regions: list[dict[str, Any]] = []
    for region in dxf_regions or ():
        region_key = _mapped_region_key(region, dxf_region_key_map) or _dxf_region_key(region)
        regions.append(
            _dxf_region_snapshot(
                region,
                region_key=region_key,
                is_selected=region_key in selected_dxf,
                continuous_targets=target_map.get(region_key, ()),
                continuous_materialized_targets=materialized_map.get(region_key, ()),
            )
        )
    for region in internal_regions or ():
        region_key = str(getattr(region, "region_key", "") or "")
        regions.append(
            _internal_region_snapshot(
                region,
                region_key=region_key,
                is_selected=region_key in selected_internal,
                continuous_targets=target_map.get(region_key, ()),
                continuous_materialized_targets=materialized_map.get(region_key, ()),
            )
        )

    payload = {
        "schema_version": 1,
        "model_name": str(model_name or ""),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_dxf_path": str(source_dxf_path or ""),
        "layout_metadata_path": str(layout_metadata_path or ""),
        "display_mode": str(display_mode or ""),
        "selected_story": str(selected_story or ""),
        "region_count": len(regions),
        "regions": regions,
    }
    json_path = _unique_report_path(out / HATCH_INPUT_STATE_JSON)
    csv_path = _unique_report_path(out / HATCH_INPUT_STATE_CSV)
    json_path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    _write_dict_rows_csv(csv_path, [_snapshot_csv_row(row) for row in regions])
    return json_path, csv_path


def write_floorload_pipeline_audit(collector: FloorloadAuditCollector, output_dir: str | Path) -> tuple[Path, Path]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = collector.to_dicts()
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "event_count": len(rows),
        "events": rows,
    }
    json_path = _unique_report_path(out / PIPELINE_AUDIT_JSON)
    csv_path = _unique_report_path(out / PIPELINE_AUDIT_CSV)
    json_path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    _write_dict_rows_csv(csv_path, [_audit_csv_row(row) for row in rows])
    return json_path, csv_path


def compare_floorload_mgt_baseline(
    baseline_mgt_path: str | Path,
    generated_mgt_path: str | Path,
    *,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    baseline_records = parse_floorload_records(Path(baseline_mgt_path).read_text(encoding="cp949"))
    generated_records = parse_floorload_records(Path(generated_mgt_path).read_text(encoding="cp949"))
    baseline_by_key = {_floorload_compare_key(record): record for record in baseline_records}
    generated_by_key = {_floorload_compare_key(record): record for record in generated_records}
    missing = [baseline_by_key[key] for key in sorted(set(baseline_by_key) - set(generated_by_key))]
    extra = [generated_by_key[key] for key in sorted(set(generated_by_key) - set(baseline_by_key))]
    common = sorted(set(baseline_by_key).intersection(generated_by_key))
    bal_differences = [
        {
            "load_name": baseline_by_key[key].get("load_name", ""),
            "baseline_bAL": baseline_by_key[key].get("bAL", ""),
            "generated_bAL": generated_by_key[key].get("bAL", ""),
            "baseline": baseline_by_key[key],
            "generated": generated_by_key[key],
        }
        for key in common
        if str(baseline_by_key[key].get("bAL", "")) != str(generated_by_key[key].get("bAL", ""))
    ]
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "baseline_count": len(baseline_records),
        "generated_count": len(generated_records),
        "missing_from_generated": missing,
        "extra_in_generated": extra,
        "bal_differences": bal_differences,
    }
    if output_dir is not None:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        json_path = _unique_report_path(out / "floorload_compare_baseline.json")
        csv_path = _unique_report_path(out / "floorload_compare_baseline.csv")
        json_path.write_text(json.dumps(_jsonable(payload), ensure_ascii=False, indent=2), encoding="utf-8")
        rows = []
        for kind, records in (("missing_from_generated", missing), ("extra_in_generated", extra)):
            rows.extend({"kind": kind, **record} for record in records)
        rows.extend({"kind": "bal_difference", **record} for record in bal_differences)
        _write_dict_rows_csv(csv_path, rows)
        payload["json_path"] = str(json_path)
        payload["csv_path"] = str(csv_path)
    return payload


def parse_floorload_records(mgt_text: str) -> list[dict[str, Any]]:
    logical_records = _floorload_logical_lines(str(mgt_text or "").splitlines())
    records = []
    for index, item in enumerate(logical_records, start=1):
        block_index, line = item
        try:
            fields = next(csv.reader([line], skipinitialspace=True))
        except Exception:
            continue
        fields = [field.strip() for field in fields]
        if len(fields) < 2:
            continue
        load_name = fields[0]
        idist = fields[1]
        node_start = 12 if idist in {"1", "2"} else 6
        node_ids = tuple(_int_or_text(field) for field in fields[node_start:] if str(field).strip())
        records.append(
            {
                "record_index": index,
                "block_index": block_index,
                "load_name": load_name,
                "iDIST": idist,
                "angle": fields[2] if len(fields) > 2 and idist in {"1", "2"} else "",
                "direction": fields[6] if len(fields) > 6 and idist in {"1", "2"} else (fields[2] if len(fields) > 2 else ""),
                "bAL": fields[10] if len(fields) > 10 and idist in {"1", "2"} else "",
                "node_ids": list(node_ids),
                "node_set": sorted({str(value) for value in node_ids}),
                "raw_record": line,
            }
        )
    return records


def _dxf_region_snapshot(region: object, *, region_key: str, is_selected: bool, continuous_targets, continuous_materialized_targets) -> dict[str, Any]:
    hatch = getattr(region, "region", None)
    load = getattr(region, "load", None)
    vertices = _point_list(getattr(hatch, "vertices", ()) if hatch is not None else ())
    placed_vertices = _point_list(getattr(hatch, "placed_vertices", ()) if hatch is not None else ())
    source_id = str(getattr(hatch, "source_id", "") or getattr(hatch, "handle", "") or "")
    story_name = str(getattr(hatch, "story_name", "") or "")
    return {
        "region_key": region_key,
        "source": "DXF",
        "story_name": story_name,
        "cell_ids": [],
        "load_name": str(getattr(load, "real_name", "") or ""),
        "load_layer": str(getattr(load, "layer", "") or getattr(hatch, "layer", "") or ""),
        "dl": _float_or_none(getattr(load, "dl", None)),
        "ll": _float_or_none(getattr(load, "ll", None)),
        "distribution": str(getattr(load, "distribution", "") or ""),
        "one_way_angle": _float_or_none(getattr(load, "one_way_angle_deg", None)),
        "polygon_xy": vertices,
        "placed_vertices": placed_vertices,
        "area": _float_or_none(getattr(region, "area", None) if hasattr(region, "area") else getattr(hatch, "area", None)),
        "is_loaded": load is not None,
        "is_selected": bool(is_selected),
        "continuous_targets": list(continuous_targets or ()),
        "continuous_materialized_targets": list(continuous_materialized_targets or ()),
        "continuous_source_key": _continuous_source_key(region_key or source_id),
        "base_region_key": _continuous_source_key(region_key or source_id),
        "target_story_name": _continuous_target_story(region_key or source_id),
        "created_by": "CONTINUOUS_SYNC" if "@" in (region_key or source_id) else "USER_DXF_HATCH",
        "merge_source_region_keys": [],
        "split_source_region_key": "",
        "dxf_layer": str(getattr(hatch, "layer", "") or ""),
        "source_id": source_id,
        "polygon_index": int(getattr(hatch, "polygon_index", 0) or 0),
        "hatch_pattern_name": str(getattr(hatch, "hatch_pattern_name", "") or ""),
        "hatch_solid_fill": int(getattr(hatch, "hatch_solid_fill", 0) or 0),
        "layout_metadata_used": bool(getattr(hatch, "layout_metadata_used", False)),
        "layout_transform_applied": bool(getattr(hatch, "transform_applied", False)),
    }


def _internal_region_snapshot(region: object, *, region_key: str, is_selected: bool, continuous_targets, continuous_materialized_targets) -> dict[str, Any]:
    source = str(getattr(region, "source", "") or "INTERNAL")
    created_by = "CONTINUOUS_SYNC" if source == "CONTINUOUS_SYNC" or region_key.startswith("continuous:") else "USER_DIRECT_INPUT"
    if bool(getattr(region, "is_merged", False)):
        created_by = "INTERNAL_MERGE"
    return {
        "region_key": region_key,
        "source": "INTERNAL",
        "source_detail": source,
        "story_name": str(getattr(region, "story_name", "") or ""),
        "cell_ids": [str(value) for value in tuple(getattr(region, "cell_ids", ()) or ())],
        "load_name": str(getattr(region, "load_name", "") or ""),
        "load_layer": str(getattr(region, "load_layer", "") or ""),
        "dl": _float_or_none(getattr(region, "dl", None)),
        "ll": _float_or_none(getattr(region, "ll", None)),
        "distribution": str(getattr(region, "distribution", "") or ""),
        "one_way_angle": _float_or_none(getattr(region, "one_way_angle", None)),
        "polygon_xy": _point_list(getattr(region, "polygon_xy", ()) or ()),
        "area": _polygon_area_hint(getattr(region, "polygon_xy", ()) or ()),
        "is_loaded": bool(str(getattr(region, "load_name", "") or "")),
        "is_selected": bool(is_selected),
        "continuous_targets": list(continuous_targets or ()),
        "continuous_materialized_targets": list(continuous_materialized_targets or ()),
        "continuous_source_key": _continuous_source_key(region_key),
        "base_region_key": _continuous_source_key(region_key),
        "target_story_name": _continuous_target_story(region_key),
        "created_by": created_by,
        "merge_source_region_keys": [],
        "split_source_region_key": "",
        "warning_codes": [str(value) for value in tuple(getattr(region, "warning_codes", ()) or ())],
    }


def _mapped_region_key(region: object, key_map: dict[Any, str] | None) -> str:
    if not key_map:
        return ""
    value = key_map.get(id(region))
    if value:
        return str(value)
    try:
        value = key_map.get(region)
    except Exception:
        value = None
    return str(value or "")


def _dxf_region_key(region: object) -> str:
    hatch = getattr(region, "region", None)
    story = str(getattr(hatch, "story_name", "") or "")
    source_id = str(getattr(hatch, "source_id", "") or getattr(hatch, "handle", "") or "")
    polygon_index = int(getattr(hatch, "polygon_index", 0) or 0)
    return f"DXF|{story}|{source_id}|{polygon_index}"


def _snapshot_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "region_key",
        "source",
        "source_detail",
        "created_by",
        "story_name",
        "cell_ids",
        "load_name",
        "load_layer",
        "dl",
        "ll",
        "distribution",
        "one_way_angle",
        "area",
        "is_loaded",
        "is_selected",
        "continuous_targets",
        "continuous_materialized_targets",
        "base_region_key",
        "target_story_name",
        "source_id",
        "polygon_index",
        "dxf_layer",
        "hatch_pattern_name",
        "hatch_solid_fill",
        "layout_metadata_used",
        "layout_transform_applied",
    )
    return {field: _csv_value(row.get(field, "")) for field in fields}


def _audit_csv_row(row: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "audit_id",
        "stage",
        "status",
        "reason_code",
        "message_ko",
        "source",
        "region_key",
        "assignment_id",
        "source_region_keys",
        "story_name",
        "load_name",
        "dl",
        "ll",
        "distribution",
        "one_way_angle",
        "area",
        "polygon_vertex_count",
        "node_count_raw",
        "node_count_simplified",
        "node_ids",
        "merge_group_id",
        "final_record_index",
        "final_mgt_record",
        "skip_reason",
        "data",
    )
    return {field: _csv_value(row.get(field, "")) for field in fields}


def _write_dict_rows_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    if not fieldnames:
        fieldnames = ["message"]
        rows = [{"message": ""}]
    with path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key, "")) for key in fieldnames})


def _unique_report_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(1, 10000):
        candidate = path.with_name(f"{path.stem}_{index:03d}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Unable to allocate unique report path: {path}")


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if hasattr(value, "to_dict"):
        try:
            return _jsonable(value.to_dict())
        except Exception:
            return str(value)
    return str(value)


def _csv_value(value: Any) -> str:
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(_jsonable(value), ensure_ascii=False)
    if value is None:
        return ""
    return str(value)


def _point_list(points: Iterable[Any]) -> list[list[float]]:
    result = []
    for point in points or ():
        try:
            x, y = point[:2]
            result.append([float(x), float(y)])
        except Exception:
            continue
    return result


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except Exception:
        return None


def _polygon_area_hint(points: Iterable[Any]) -> float:
    pts = _point_list(points)
    if len(pts) < 3:
        return 0.0
    area = 0.0
    for index, start in enumerate(pts):
        end = pts[(index + 1) % len(pts)]
        area += start[0] * end[1] - end[0] * start[1]
    return abs(area) / 2.0


def _continuous_source_key(key: str) -> str:
    text = str(key or "")
    if text.startswith("continuous:"):
        body = text[len("continuous:") :]
        return body.split("@", 1)[0]
    if "@" in text:
        return text.split("@", 1)[0]
    return ""


def _continuous_target_story(key: str) -> str:
    text = str(key or "")
    if "@" not in text:
        return ""
    suffix = text.split("@", 1)[1]
    return suffix.split(":", 1)[0]


def _floorload_logical_lines(lines: Sequence[str]) -> list[tuple[int, str]]:
    in_floorload = False
    result: list[tuple[int, str]] = []
    block_index = 0
    current = ""
    for raw in lines:
        line = str(raw).strip()
        upper = line.upper()
        if upper.startswith("*"):
            if in_floorload and current:
                result.append((block_index, current.strip()))
                current = ""
            if upper.startswith("*FLOORLOAD"):
                block_index += 1
                in_floorload = True
                current = ""
                continue
            in_floorload = False
            current = ""
            continue
        if not in_floorload or not line or line.startswith(";"):
            continue
        if line.endswith("\\"):
            current += line[:-1].rstrip() + " "
            continue
        result.append((block_index, (current + line).strip()))
        current = ""
    if in_floorload and current:
        result.append((block_index, current.strip()))
    return result


def _int_or_text(value: Any) -> int | str:
    try:
        return int(str(value).strip())
    except Exception:
        return str(value).strip()


def _floorload_compare_key(record: dict[str, Any]) -> tuple[Any, ...]:
    node_set = tuple(sorted(str(value) for value in record.get("node_ids", ()) or ()))
    return (
        str(record.get("load_name", "")).strip(),
        str(record.get("iDIST", "")).strip(),
        str(record.get("angle", "")).strip(),
        node_set,
    )
