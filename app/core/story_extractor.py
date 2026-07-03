from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .mgt_parser import Story, Node, Element, infer_story_from_nodes, parse_elements_from_text, parse_nodes_from_text, parse_stories_from_text


def stories_from_api_response(api_stor: Any) -> list[Story]:
    if not api_stor:
        return []
    rows = _as_rows(api_stor)
    stories: list[Story] = []
    for key, row in rows:
        if isinstance(row, Mapping):
            name = str(row.get("NAME") or row.get("Name") or row.get("name") or row.get("STORY") or row.get("story") or key)
            elev = _first_float(row, ["LEVEL", "Level", "level", "ELEV", "ELEVATION", "elevation", "Z", "z"])
            height = _first_float(row, ["HEIGHT", "Height", "height", "H", "h"])
            if elev is not None:
                stories.append(Story(name=name, elevation=elev, height=height, raw=str(row)))
        elif isinstance(row, (list, tuple)) and len(row) >= 2:
            try:
                stories.append(Story(name=str(row[0]), elevation=float(row[1]), raw=str(row)))
            except (TypeError, ValueError):
                continue
    return sorted(stories, key=lambda s: s.elevation)


def nodes_from_api_response(api_nodes: Any) -> list[Node]:
    rows = _as_rows(api_nodes)
    nodes: list[Node] = []
    for key, row in rows:
        if isinstance(row, Mapping):
            node_id = _first_int(row, ["ID", "NO", "iNO", "NODE", "id", "node_id"]) or _safe_int(key)
            x = _first_float(row, ["X", "x"])
            y = _first_float(row, ["Y", "y"])
            z = _first_float(row, ["Z", "z"])
            if node_id is not None and x is not None and y is not None and z is not None:
                nodes.append(Node(node_id, x, y, z))
        elif isinstance(row, (list, tuple)) and len(row) >= 4:
            try:
                nodes.append(Node(int(float(row[0] or key)), float(row[1]), float(row[2]), float(row[3])))
            except (TypeError, ValueError):
                continue
    return nodes


def elements_from_api_response(api_elements: Any) -> list[Element]:
    rows = _as_rows(api_elements)
    elements: list[Element] = []
    for key, row in rows:
        if isinstance(row, Mapping):
            elem_id = _first_int(row, ["ID", "NO", "iEL", "ELEM", "id", "elem_id"]) or _safe_int(key)
            elem_type = str(row.get("TYPE") or row.get("type") or row.get("ELEM_TYPE") or row.get("element_type") or "").upper()
            mat = _first_int(row, ["MATL", "MAT", "iMAT", "mat"])
            prop = _first_int(row, ["SECT", "PROP", "iPRO", "prop"])
            node_ids = []
            for nk in ("NODE", "NODES", "node", "nodes"):
                value = row.get(nk)
                if isinstance(value, (list, tuple)):
                    node_ids = [_safe_int(v) for v in value]
                    node_ids = [v for v in node_ids if v is not None]
                    break
            if not node_ids:
                for nk in ("iN1", "iN2", "iN3", "iN4", "N1", "N2", "N3", "N4", "NODE1", "NODE2", "NODE3", "NODE4"):
                    v = _safe_int(row.get(nk))
                    if v is not None and v > 0:
                        node_ids.append(v)
            if elem_id is not None and elem_type and len(node_ids) >= 2:
                elements.append(Element(elem_id, elem_type, mat, prop, tuple(node_ids), raw=str(row)))
        elif isinstance(row, (list, tuple)) and len(row) >= 6:
            try:
                elem_id = int(float(row[0] or key))
                elem_type = str(row[1]).upper()
                max_nodes = 2 if elem_type in {"BEAM", "COLUMN", "TRUSS"} else 4
                node_ids = [int(float(v)) for v in row[4 : 4 + max_nodes] if str(v).strip()]
                elements.append(Element(elem_id, elem_type, _safe_int(row[2]), _safe_int(row[3]), tuple(node_ids), raw=str(row)))
            except (TypeError, ValueError):
                continue
    return elements


def snapshot_from_mgt_text(text: str) -> tuple[list[Story], list[Node], list[Element]]:
    nodes = parse_nodes_from_text(text)
    stories = parse_stories_from_text(text) or infer_story_from_nodes(nodes)
    elements = parse_elements_from_text(text)
    return stories, nodes, elements


def _as_rows(data: Any) -> list[tuple[Any, Any]]:
    if isinstance(data, Mapping):
        # MIDAS db response is often {"1": {...}, "2": {...}}
        return list(data.items())
    if isinstance(data, list):
        return list(enumerate(data, start=1))
    return []


def _first_float(row: Mapping[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        if key in row:
            try:
                return float(row[key])
            except (TypeError, ValueError):
                continue
    return None


def _first_int(row: Mapping[str, Any], keys: list[str]) -> int | None:
    for key in keys:
        value = _safe_int(row.get(key))
        if value is not None:
            return value
    return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
