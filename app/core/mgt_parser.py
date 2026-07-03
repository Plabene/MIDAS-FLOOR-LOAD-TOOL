from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Iterable
import csv
import io
import re


@dataclass(frozen=True)
class Story:
    name: str
    elevation: float
    height: float | None = None
    raw: str = ""


@dataclass(frozen=True)
class Node:
    node_id: int
    x: float
    y: float
    z: float

    @property
    def xy(self) -> tuple[float, float]:
        return (self.x, self.y)


@dataclass(frozen=True)
class Element:
    elem_id: int
    elem_type: str
    mat: int | None = None
    prop: int | None = None
    node_ids: tuple[int, ...] = field(default_factory=tuple)
    raw: str = ""


@dataclass(frozen=True)
class FloorLoadTypeSpec:
    name: str
    dl: float = 0.0
    ll: float = 0.0
    raw_name_line: str = ""
    raw_value_line: str = ""


def read_text(path: str | Path, encodings: tuple[str, ...] = ("utf-8-sig", "cp949", "euc-kr", "utf-8", "latin1")) -> str:
    data = Path(path).read_bytes()
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode(encodings[-1], errors="replace")


def write_text(path: str | Path, text: str, encoding: str = "cp949") -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding=encoding, errors="replace", newline="")
    return p


def split_sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    current_name = "__HEADER__"
    current_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("*"):
            sections.append((current_name, current_lines))
            current_name = stripped.split(None, 1)[0].upper()
            current_lines = [line]
        else:
            current_lines.append(line)
    sections.append((current_name, current_lines))
    return sections


def section_lines(text: str, section_name: str) -> list[str]:
    target = section_name.upper()
    for name, lines in split_sections(text):
        if name == target:
            return lines
    return []


def parse_stories_from_text(text: str) -> list[Story]:
    stories: list[Story] = []
    for line in section_lines(text, "*STORY"):
        payload = _payload(line)
        if not payload or payload.upper().startswith("*STORY") or payload.startswith(";"):
            continue
        if "NAME=" not in payload.upper():
            continue
        parts = _csv_split(payload)
        first = parts[0].strip()
        match = re.match(r"NAME\s*=\s*(.+)", first, flags=re.IGNORECASE)
        if not match or len(parts) < 2:
            continue
        name = match.group(1).strip().strip('"')
        try:
            elevation = float(parts[1])
        except ValueError:
            continue
        stories.append(Story(name=name, elevation=elevation, raw=line))
    # MGT에는 높이가 직접 없으므로 상위 story elevation 차로 산정한다.
    ordered = sorted(stories, key=lambda s: s.elevation)
    with_heights: list[Story] = []
    for idx, story in enumerate(ordered):
        height = None
        if idx + 1 < len(ordered):
            height = ordered[idx + 1].elevation - story.elevation
        with_heights.append(Story(story.name, story.elevation, height, story.raw))
    return with_heights


def parse_nodes_from_text(text: str) -> list[Node]:
    nodes: list[Node] = []
    for line in section_lines(text, "*NODE"):
        payload = _payload(line)
        if not payload or payload.startswith(";") or payload.upper().startswith("*NODE"):
            continue
        parts = _csv_split(payload)
        if len(parts) < 4:
            continue
        try:
            nodes.append(Node(int(float(parts[0])), float(parts[1]), float(parts[2]), float(parts[3])))
        except ValueError:
            continue
    return nodes


def parse_elements_from_text(text: str) -> list[Element]:
    elements: list[Element] = []
    for line in section_lines(text, "*ELEMENT"):
        payload = _payload(line)
        if not payload or payload.startswith(";") or payload.upper().startswith("*ELEMENT"):
            continue
        parts = _csv_split(payload)
        if len(parts) < 6:
            continue
        try:
            elem_id = int(float(parts[0]))
        except ValueError:
            continue
        elem_type = parts[1].strip().upper()
        mat = _try_int(parts[2]) if len(parts) > 2 else None
        prop = _try_int(parts[3]) if len(parts) > 3 else None
        node_ids: list[int] = []
        # Frame: iEL, TYPE, iMAT, iPRO, iN1, iN2, ...
        # Planar: iEL, TYPE, iMAT, iPRO, iN1, iN2, iN3, iN4, ...
        max_nodes = 2 if elem_type in {"BEAM", "COLUMN", "TRUSS", "TENSTR", "COMPTR"} else 4
        for value in parts[4 : 4 + max_nodes]:
            node = _try_int(value)
            if node is not None and node > 0:
                node_ids.append(node)
        if len(node_ids) >= 2:
            elements.append(Element(elem_id, elem_type, mat, prop, tuple(node_ids), raw=line))
    return elements


def parse_mgt_file(path: str | Path) -> tuple[list[Story], list[Node], list[Element], str]:
    text = read_text(path)
    return parse_stories_from_text(text), parse_nodes_from_text(text), parse_elements_from_text(text), text


def parse_floadtype_specs_from_text(text: str) -> list[FloorLoadTypeSpec]:
    lines = [
        line
        for line in section_lines(text, "*FLOADTYPE")
        if _is_data_line(line, "*FLOADTYPE")
    ]
    specs: list[FloorLoadTypeSpec] = []
    idx = 0
    while idx < len(lines):
        name_line = lines[idx]
        value_line = lines[idx + 1] if idx + 1 < len(lines) else ""
        name_parts = _csv_split(_payload(name_line))
        name = name_parts[0].strip().strip('"') if name_parts else ""
        if name:
            dl = 0.0
            ll = 0.0
            value_parts = _csv_split(_payload(value_line))
            for pos in range(0, len(value_parts), 3):
                if pos + 1 >= len(value_parts):
                    continue
                case_name = value_parts[pos]
                value = _try_float(value_parts[pos + 1])
                family = _load_case_family(case_name)
                if family == "LL":
                    ll += abs(value)
                else:
                    # 미분류 하중은 DXF 레이어 생성을 위해 DL로 임시 분류한다.
                    dl += abs(value)
            specs.append(FloorLoadTypeSpec(name=name, dl=dl, ll=ll, raw_name_line=name_line, raw_value_line=value_line))
        idx += 2
    return specs


def parse_floorload_type_names_from_text(text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for line in section_lines(text, "*FLOORLOAD"):
        if not _is_data_line(line, "*FLOORLOAD"):
            continue
        parts = _csv_split(_payload(line))
        if not parts:
            continue
        name = parts[0].strip().strip('"')
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def select_nodes_by_story(nodes: Iterable[Node], elevation: float, tolerance: float) -> list[Node]:
    tol = abs(float(tolerance))
    return [n for n in nodes if abs(n.z - float(elevation)) <= tol]


def infer_story_from_nodes(nodes: Iterable[Node]) -> list[Story]:
    grouped: dict[float, int] = {}
    for node in nodes:
        z = round(node.z, 6)
        grouped[z] = grouped.get(z, 0) + 1
    stories: list[Story] = []
    for idx, z in enumerate(sorted(grouped), start=1):
        stories.append(Story(name=f"Z{idx}_{z:g}", elevation=float(z), raw=f"inferred node count={grouped[z]}"))
    return stories


def representative_z(nodes: Iterable[Node]) -> float | None:
    values = [n.z for n in nodes]
    return float(median(values)) if values else None


def _payload(line: str) -> str:
    return line.split(";", 1)[0].strip()


def _is_data_line(line: str, section_name: str) -> bool:
    payload = _payload(line)
    return bool(payload and not payload.startswith(";") and not payload.upper().startswith(section_name.upper()))


def _csv_split(line: str) -> list[str]:
    try:
        return [cell.strip() for cell in next(csv.reader(io.StringIO(line), skipinitialspace=True))]
    except Exception:
        return [cell.strip() for cell in line.split(",")]


def _try_int(value: object) -> int | None:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _try_float(value: object) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _load_case_family(case_name: object) -> str:
    text = str(case_name or "").upper()
    if "LL" in text or "LIVE" in text or "활" in text:
        return "LL"
    if "DL" in text or "DEAD" in text or "고정" in text:
        return "DL"
    return "DL"
