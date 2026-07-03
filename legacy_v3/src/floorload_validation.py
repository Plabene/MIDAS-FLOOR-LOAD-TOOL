from __future__ import annotations

from typing import Any

from dxf_hatch_reader import HatchRegion
from floorload_area_detector import FloorLoadAreaMatch

LOG_COLUMNS = [
    "handle",
    "source_type",
    "layer",
    "mapped_floor_load_type",
    "status",
    "hatch_area",
    "bbox",
    "matched_node_count",
    "boundary_node_count",
    "area_error_ratio",
    "max_node_snap_error",
    "nodes",
    "warnings",
]


def make_log_record(
    hatch: HatchRegion,
    *,
    mapped_floor_load_type: str | None,
    status: str,
    match: FloorLoadAreaMatch | None = None,
    assignment: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    combined_warnings: list[str] = []
    combined_warnings.extend(hatch.warnings or [])
    if match is not None:
        combined_warnings.extend(match.warnings or [])
    combined_warnings.extend(warnings or [])

    nodes = []
    if assignment is not None:
        nodes = list(assignment.get("NODES") or [])
    elif match is not None:
        nodes = list(match.boundary_node_ids)

    return {
        "handle": hatch.handle,
        "source_type": hatch.source_type,
        "layer": hatch.layer,
        "mapped_floor_load_type": mapped_floor_load_type,
        "status": status,
        "hatch_area": hatch.area,
        "bbox": list(hatch.bbox),
        "matched_node_count": match.matched_node_count if match is not None else 0,
        "boundary_node_count": match.boundary_node_count if match is not None else 0,
        "area_error_ratio": match.area_error_ratio if match is not None else None,
        "max_node_snap_error": match.max_node_snap_error if match is not None else None,
        "nodes": nodes,
        "warnings": _unique(combined_warnings),
    }


def summarize_log_records(records: list[dict[str, Any]]) -> dict[str, int]:
    ok = sum(1 for record in records if record.get("status") == "OK")
    skipped = sum(1 for record in records if record.get("status") != "OK")
    return {"total_hatches": len(records), "created_assignments": ok, "skipped_or_review": skipped}


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result