from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import ezdxf
import pandas as pd

from floorload_area_detector import FloorLoadAreaMatch
from floorload_validation import LOG_COLUMNS
from mgt_model_parser import read_mgt_text


def write_assignment_json(assignments: list[dict[str, Any]], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    api_items = {str(item["ID"]): {key: value for key, value in item.items() if key != "ID"} for item in assignments}
    payload = {
        "assignments": assignments,
        "midas_api": {
            "/db/FBLA": {
                "Assign": api_items,
            }
        },
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_assignment_log(records: list[dict[str, Any]], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = []
    for record in records:
        row = {column: record.get(column) for column in LOG_COLUMNS}
        for key in ("bbox", "nodes", "warnings"):
            row[key] = json.dumps(row.get(key) or [], ensure_ascii=False)
        normalized.append(row)
    pd.DataFrame(normalized, columns=LOG_COLUMNS).to_excel(path, index=False)
    return path


def write_preview_dxf(matches: Iterable[FloorLoadAreaMatch], output_path: str | Path) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    _ensure_layer(doc, "FLOAD_HATCH", 3)
    _ensure_layer(doc, "FLOAD_NODES_OK", 5)
    _ensure_layer(doc, "FLOAD_REVIEW", 1)

    for index, match in enumerate(matches, start=1):
        layer = "FLOAD_NODES_OK" if match.is_valid else "FLOAD_REVIEW"
        if match.mapped_polygon is not None and not match.mapped_polygon.is_empty:
            coords = [(float(x), float(y)) for x, y in match.mapped_polygon.exterior.coords]
            msp.add_lwpolyline(coords, close=True, dxfattribs={"layer": "FLOAD_HATCH"})
        if match.boundary_node_points:
            msp.add_lwpolyline(match.boundary_node_points, close=True, dxfattribs={"layer": layer})
            x, y = match.boundary_node_points[0]
            msp.add_text(f"{index}:{match.status}", dxfattribs={"height": 0.25, "layer": layer}).set_placement((x, y))

    doc.saveas(path)
    return path


def write_mgtx_patch_file(
    source_mgtx_path: str | Path,
    output_path: str | Path,
    assignments: list[dict[str, Any]],
    *,
    mode: str = "append",
    encoding: str = "cp949",
) -> Path:
    source = Path(source_mgtx_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    text = read_mgt_text(source)
    patched = insert_floorload_block(text, assignments, mode=mode)
    output.write_text(patched, encoding=encoding, errors="replace", newline="")
    return output


def insert_floorload_block(text: str, assignments: list[dict[str, Any]], *, mode: str = "append") -> str:
    normalized_mode = (mode or "append").lower()
    lines = text.splitlines()
    if normalized_mode in {"overwrite", "dedupe"}:
        lines = _remove_floorload_blocks(lines)
    if normalized_mode == "dedupe":
        assignments = _dedupe_assignments(assignments)

    block = _floorload_block_lines(assignments)
    if not block:
        return "\r\n".join(lines) + "\r\n"

    insert_at = next((idx for idx, line in enumerate(lines) if line.strip().upper().startswith("*ENDDATA")), len(lines))
    patched = lines[:insert_at] + block + [""] + lines[insert_at:]
    return "\r\n".join(patched) + "\r\n"


def _floorload_block_lines(assignments: list[dict[str, Any]]) -> list[str]:
    if not assignments:
        return []
    lines = [
        "",
        "*FLOORLOAD    ; Assign Floor Loads",
        "; FLOOR_LOAD_TYPE_NAME, FLOOR_DIST_TYPE, DIR, GROUP_NAME, DESC, OPT_PROJECTION, OPT_EXCLUDE_INNER_ELEM_AREA, SUB_BEAM_NUM, SUB_BEAM_ANGLE, UNIT_SELF_WEIGHT",
        "; NODES, node1, node2, node3, ...",
    ]
    for item in assignments:
        fields = [
            _mgtx_field(item.get("FLOOR_LOAD_TYPE_NAME")),
            _mgtx_field(item.get("FLOOR_DIST_TYPE", "AREA")),
            _mgtx_field(item.get("DIR", "GZ")),
            _mgtx_field(item.get("GROUP_NAME", "")),
            _mgtx_field(item.get("DESC", "")),
            _yes_no(item.get("OPT_PROJECTION")),
            _yes_no(item.get("OPT_EXCLUDE_INNER_ELEM_AREA")),
            str(int(item.get("SUB_BEAM_NUM", 0) or 0)),
            _format_float(item.get("SUB_BEAM_ANGLE", 0.0)),
            _yes_no(item.get("UNIT_SELF_WEIGHT")),
        ]
        lines.append("   " + ", ".join(fields))
        lines.append("   NODES, " + ", ".join(str(int(node_id)) for node_id in item.get("NODES", [])))
    return lines


def _remove_floorload_blocks(lines: list[str]) -> list[str]:
    result: list[str] = []
    skipping = False
    for line in lines:
        stripped = line.strip().upper()
        if stripped.startswith("*FLOORLOAD"):
            skipping = True
            continue
        if skipping and stripped.startswith("*"):
            skipping = False
        if not skipping:
            result.append(line)
    return result


def _dedupe_assignments(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, tuple[int, ...]]] = set()
    result: list[dict[str, Any]] = []
    for item in assignments:
        key = (str(item.get("FLOOR_LOAD_TYPE_NAME") or ""), tuple(int(node) for node in item.get("NODES", [])))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _ensure_layer(doc, name: str, color: int) -> None:
    if name not in doc.layers:
        doc.layers.add(name, color=color)


def _mgtx_field(value: Any) -> str:
    text = " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split()).replace('"', "'")
    if "," in text:
        return f'"{text}"'
    return text


def _yes_no(value: Any) -> str:
    if isinstance(value, str):
        return "YES" if value.strip().lower() in {"1", "true", "yes", "y"} else "NO"
    return "YES" if bool(value) else "NO"


def _format_float(value: Any) -> str:
    try:
        text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return "0"
    return "0" if text in {"", "-0"} else text