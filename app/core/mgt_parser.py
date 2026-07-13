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
    angle_deg: float = 0.0


@dataclass(frozen=True)
class FloorLoadTypeSpec:
    name: str
    dl: float = 0.0
    ll: float = 0.0
    raw_name_line: str = ""
    raw_value_line: str = ""
    load_case_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParsedFloorLoadRecord:
    ltname: str
    idist: int | None
    node_ids: tuple[int, ...]
    fields: tuple[str, ...]
    raw: str
    line_number: int


@dataclass(frozen=True)
class ParsedElasticLink:
    link_id: int | None
    node_i: int
    node_j: int
    raw: str
    raw_lines: tuple[str, ...] = ()
    line_number: int = 0


@dataclass(frozen=True)
class ParsedMaterial:
    material_id: int
    material_type: str
    name: str
    raw: str
    fields: tuple[str, ...]
    line_number: int


@dataclass(frozen=True)
class ParsedSection:
    section_id: int
    section_type: str
    name: str
    raw: str
    fields: tuple[str, ...]
    line_number: int


@dataclass(frozen=True)
class SectionDisplaySize:
    section_id: int
    name: str = ""
    role: str = "UNKNOWN"
    width: float | None = None
    depth: float | None = None
    plan_width: float | None = None
    raw: str = ""
    reason: str = ""
    shape: str = ""
    offset_code: str = ""
    d1: float | None = None
    d2: float | None = None


@dataclass(frozen=True)
class ParsedFrameRelease:
    element_id: int
    raw_lines: tuple[str, ...]
    line_number: int


@dataclass(frozen=True)
class ExistingLoadDmMember:
    element_id: int
    story_name: str
    node_i: int
    node_j: int
    start_xy: tuple[float, float]
    end_xy: tuple[float, float]
    material_id: int | None
    section_id: int | None
    release: ParsedFrameRelease | None = None
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelUnitInfo:
    force: str = ""
    length: str = ""
    heat: str = ""
    temperature: str = ""
    source_line: str = ""


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
            angle_deg = 0.0
            if elem_type in {"BEAM", "COLUMN", "TRUSS", "TENSTR", "COMPTR"} and len(parts) > 6:
                try:
                    angle_deg = float(parts[6])
                except Exception:
                    angle_deg = 0.0
            elements.append(Element(elem_id, elem_type, mat, prop, tuple(node_ids), raw=line, angle_deg=angle_deg))
    return elements


def parse_mgt_file(path: str | Path) -> tuple[list[Story], list[Node], list[Element], str]:
    text = read_text(path)
    return parse_stories_from_text(text), parse_nodes_from_text(text), parse_elements_from_text(text), text


def parse_unit_from_text(text: str) -> ModelUnitInfo:
    for line in section_lines(text, "*UNIT"):
        payload = _payload(line)
        if not payload or payload.startswith(";") or payload.upper().startswith("*UNIT"):
            continue
        parts = _csv_split(payload)
        if len(parts) >= 2:
            return ModelUnitInfo(
                force=parts[0].strip().upper(),
                length=parts[1].strip().upper(),
                heat=parts[2].strip().upper() if len(parts) > 2 else "",
                temperature=parts[3].strip().upper() if len(parts) > 3 else "",
                source_line=line,
            )
    return ModelUnitInfo()


def dxf_unit_scale_from_model_length_unit(length_unit: str) -> float:
    unit = str(length_unit or "").strip().upper()
    if unit in {"M", "METER", "METERS"}:
        return 1000.0
    if unit in {"MM", "MILLIMETER", "MILLIMETERS"}:
        return 1.0
    if unit in {"CM", "CENTIMETER", "CENTIMETERS"}:
        return 10.0
    return 1.0


def dxf_insunits_for_output_mm() -> int:
    return 4


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
            load_case_names: list[str] = []
            value_parts = _csv_split(_payload(value_line))
            for pos in range(0, len(value_parts), 3):
                if pos + 1 >= len(value_parts):
                    continue
                case_name = value_parts[pos]
                if str(case_name or "").strip():
                    load_case_names.append(str(case_name).strip())
                value = _try_float(value_parts[pos + 1])
                family = _load_case_family(case_name)
                if family == "LL":
                    ll += abs(value)
                else:
                    # 미분류 하중은 DXF 레이어 생성을 위해 DL로 임시 분류한다.
                    dl += abs(value)
            specs.append(
                FloorLoadTypeSpec(
                    name=name,
                    dl=dl,
                    ll=ll,
                    raw_name_line=name_line,
                    raw_value_line=value_line,
                    load_case_names=tuple(load_case_names),
                )
            )
        idx += 2
    return specs


def parse_floorload_type_names_from_text(text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for record in iter_floorload_records_from_text(text):
        name = record.ltname
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def parse_stldcase_names_from_text(text: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for line in section_lines(text, "*STLDCASE"):
        if not _is_data_line(line, "*STLDCASE"):
            continue
        parts = _csv_split(_payload(line))
        name = parts[0].strip().strip('"') if parts else ""
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def iter_floorload_records_from_text(text: str) -> list[ParsedFloorLoadRecord]:
    records: list[ParsedFloorLoadRecord] = []
    for section_name, lines in split_sections(text):
        if section_name != "*FLOORLOAD":
            continue
        pending: list[str] = []
        pending_line_number = 0
        for index, line in enumerate(lines, start=1):
            if not _is_data_line(line, "*FLOORLOAD"):
                continue
            payload, continued = _floorload_payload_and_continuation(line)
            if not payload and not continued:
                continue
            if not pending:
                pending_line_number = index
            if payload:
                pending.append(payload)
            if continued:
                continue
            record = _parsed_floorload_record_from_payload(", ".join(pending), pending_line_number)
            if record is not None:
                records.append(record)
            pending = []
            pending_line_number = 0
        if pending:
            record = _parsed_floorload_record_from_payload(", ".join(pending), pending_line_number)
            if record is not None:
                records.append(record)
    return records


def parse_elastic_links_from_text(text: str) -> list[ParsedElasticLink]:
    links: list[ParsedElasticLink] = []
    in_elastic_link_section = False
    pending: list[str] = []
    pending_raw: list[str] = []
    pending_line_number = 0

    def flush_pending() -> None:
        nonlocal pending, pending_raw, pending_line_number
        if not pending:
            return
        link = _parsed_elastic_link_from_payload(", ".join(pending), tuple(pending_raw), pending_line_number)
        if link is not None:
            links.append(link)
        pending = []
        pending_raw = []
        pending_line_number = 0

    for line_number, line in enumerate(text.splitlines(), start=1):
        payload = _payload(line)
        if payload.startswith("*"):
            flush_pending()
            in_elastic_link_section = _normalized_section_name(payload) in {"ELASTICLINK", "ELASTICLINKS"}
            continue
        if not in_elastic_link_section or not payload or payload.startswith(";"):
            continue
        row_payload, continued = _floorload_payload_and_continuation(line)
        if not row_payload and not continued:
            continue
        if not pending:
            pending_line_number = line_number
        if row_payload:
            pending.append(row_payload)
            pending_raw.append(line)
        if not continued:
            flush_pending()
    flush_pending()
    return links


def parse_materials_from_text(text: str) -> list[ParsedMaterial]:
    materials: list[ParsedMaterial] = []
    for index, line in enumerate(section_lines(text, "*MATERIAL"), start=1):
        if not _is_data_line(line, "*MATERIAL"):
            continue
        payload = _payload(line)
        parts = _csv_split(payload)
        if len(parts) < 3:
            continue
        material_id = _try_int(parts[0])
        if material_id is None:
            continue
        materials.append(
            ParsedMaterial(
                material_id=material_id,
                material_type=str(parts[1] if len(parts) > 1 else "").strip(),
                name=str(parts[2] if len(parts) > 2 else "").strip().strip('"'),
                raw=payload,
                fields=tuple(parts),
                line_number=index,
            )
        )
    return materials


def parse_sections_from_text(text: str) -> list[ParsedSection]:
    sections: list[ParsedSection] = []
    for index, line in enumerate(section_lines(text, "*SECTION"), start=1):
        if not _is_data_line(line, "*SECTION"):
            continue
        payload = _payload(line)
        parts = _csv_split(payload)
        if len(parts) < 3:
            continue
        section_id = _try_int(parts[0])
        if section_id is None:
            continue
        sections.append(
            ParsedSection(
                section_id=section_id,
                section_type=str(parts[1] if len(parts) > 1 else "").strip(),
                name=str(parts[2] if len(parts) > 2 else "").strip().strip('"'),
                raw=payload,
                fields=tuple(parts),
                line_number=index,
            )
        )
    return sections


def material_name_by_id_from_text(text: str) -> dict[int, str]:
    return {item.material_id: item.name for item in parse_materials_from_text(text)}


def section_name_by_id_from_text(text: str) -> dict[int, str]:
    return {item.section_id: item.name for item in parse_sections_from_text(text)}


def thickness_value_by_id_from_text(text: str) -> dict[int, float]:
    """Return VALUE thicknesses in the model's current length unit."""
    unit_info = parse_unit_from_text(text)
    length_unit = str(getattr(unit_info, "length", "") or "").upper()
    result: dict[int, float] = {}
    for line in section_lines(text, "*THICKNESS"):
        if not _is_data_line(line, "*THICKNESS"):
            continue
        parts = _csv_split(_payload(line))
        if len(parts) < 5:
            continue
        thickness_id = _try_int(parts[0])
        thickness_type = str(parts[1] if len(parts) > 1 else "").strip().upper()
        if thickness_id is None or thickness_type != "VALUE":
            continue
        try:
            physical_thickness = abs(float(str(parts[4]).strip()))
        except (TypeError, ValueError):
            continue
        if physical_thickness <= 1.0e-9:
            continue
        normalized = _normalize_section_dimension_for_model_unit(physical_thickness, length_unit)
        if normalized is not None and normalized > 1.0e-9:
            result[thickness_id] = normalized
    return result


def section_display_size_by_id_from_text(text: str) -> dict[int, SectionDisplaySize]:
    unit_info = parse_unit_from_text(text)
    length_unit = str(getattr(unit_info, "length", "") or "").upper()
    result: dict[int, SectionDisplaySize] = {}
    for section in parse_sections_from_text(text):
        width, depth, reason = _section_dimensions_from_name(section.name)
        field_width, field_depth = _section_dimensions_from_fields(section.fields[3:])
        shape, d1, d2 = _section_shape_and_d_values_from_fields(section.fields[3:])
        d1 = _normalize_section_dimension_for_model_unit(d1, length_unit)
        d2 = _normalize_section_dimension_for_model_unit(d2, length_unit)
        role = _section_name_role(section.name, section.section_type)
        plan_width = None
        if shape == "SB" and d1 is not None and d2 is not None:
            if role == "BEAM":
                width = d2
                depth = d1
                plan_width = d2
                reason = "fields_sb_beam_d1_depth_d2_width"
            elif role == "WALL":
                width = min(d1, d2)
                depth = max(d1, d2)
                plan_width = width
                reason = "fields_sb_wall_thickness"
            elif role == "COLUMN":
                width = d1
                depth = d2
                plan_width = width
                reason = "fields_sb_column"
            else:
                width = min(d1, d2)
                depth = max(d1, d2)
                plan_width = width
                reason = "fields_sb_unknown_min_as_plan_width"
        elif shape in {"H", "BOX"} and d1 is not None and d2 is not None:
            depth = d1
            width = d2
            if role == "BEAM":
                plan_width = width
            reason = f"fields_{shape.lower()}_catalog_pair_d1_depth_d2_width"
        elif width is None or depth is None:
            width = width if width is not None else field_width
            depth = depth if depth is not None else field_depth
            if field_width is not None or field_depth is not None:
                reason = reason or "fields"
        width = _normalize_section_dimension_for_model_unit(width, length_unit)
        depth = _normalize_section_dimension_for_model_unit(depth, length_unit)
        field_width = _normalize_section_dimension_for_model_unit(field_width, length_unit)
        field_depth = _normalize_section_dimension_for_model_unit(field_depth, length_unit)
        if plan_width is None:
            plan_width = _infer_section_plan_width(
                section.name,
                section.section_type,
                width,
                depth,
                field_width=field_width,
                field_depth=field_depth,
            )
        result[section.section_id] = SectionDisplaySize(
            section_id=section.section_id,
            name=section.name,
            role=role,
            width=width,
            depth=depth,
            plan_width=plan_width,
            raw=section.raw,
            reason=reason or ("unknown" if width is None and depth is None else "heuristic"),
            shape=shape,
            offset_code=str(section.fields[3]).strip() if len(section.fields) > 3 else "",
            d1=d1,
            d2=d2,
        )
    return result


def _section_dimensions_from_name(name: str) -> tuple[float | None, float | None, str]:
    text = str(name or "").upper().replace("×", "X")
    match = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*[*X]\s*(\d+(?:\.\d+)?)(?!\d)", text)
    if match:
        return float(match.group(1)), float(match.group(2)), "name_pair"
    match = re.search(r"(?<![A-Z0-9])(?:B|C|W)\s*(\d+(?:\.\d+)?)(?![A-Z0-9])", text)
    if match:
        value = float(match.group(1))
        if value >= 50.0:
            prefix = match.group(0).strip()[0]
            return value, value, "name_wall" if prefix == "W" else "name_square"
    return None, None, ""


def _section_dimensions_from_fields(fields: Iterable[str]) -> tuple[float | None, float | None]:
    field_values = [str(field or "") for field in fields]
    shape_tokens = {"SB", "SR", "SRC", "RC", "S", "C", "B", "W", "H", "BOX", "PIPE", "USER"}
    start_index = 0
    for index, field in enumerate(field_values):
        normalized = re.sub(r"[^A-Z]+", "", field.upper())
        if normalized in shape_tokens:
            start_index = index + 1
            break
    numbers: list[tuple[str, float]] = []
    for field in field_values[start_index:]:
        for token in re.findall(r"-?\d+(?:\.\d+)?", field):
            try:
                value = abs(float(token))
            except ValueError:
                continue
            if value > 1.0e-9:
                numbers.append((token, value))
    if start_index > 0 and len(numbers) >= 3 and numbers[0][1] in {1.0, 2.0} and "." not in numbers[0][0]:
        numbers = numbers[1:]
    values: list[float] = []
    for token, value in numbers:
        if start_index == 0 and value in {1.0, 2.0} and "." not in token:
            continue
        values.append(value)
        if len(values) >= 2:
            break
    if not values:
        return None, None
    if len(values) == 1:
        return values[0], values[0]
    return values[0], values[1]


def _section_shape_and_d_values_from_fields(fields: Iterable[str]) -> tuple[str, float | None, float | None]:
    field_values = [str(field or "") for field in fields]
    shape_tokens = {"SB", "SR", "SRC", "RC", "S", "C", "B", "W", "H", "BOX", "PIPE", "USER"}
    shape = ""
    start_index = 0
    for index, field in enumerate(field_values):
        normalized = re.sub(r"[^A-Z]+", "", field.upper())
        if normalized in shape_tokens:
            shape = normalized
            start_index = index + 1
            break
    if not shape:
        return "", None, None
    for field in field_values[start_index:]:
        catalog_text = str(field or "").upper().replace("×", "X")
        pair = re.search(r"(?<!\d)(\d+(?:\.\d+)?)\s*[*X]\s*(\d+(?:\.\d+)?)(?!\d)", catalog_text)
        if pair:
            return shape, float(pair.group(1)), float(pair.group(2))
    numbers: list[tuple[str, float]] = []
    for field in field_values[start_index:]:
        for token in re.findall(r"-?\d+(?:\.\d+)?", field):
            try:
                value = abs(float(token))
            except ValueError:
                continue
            if value > 1.0e-9:
                numbers.append((token, value))
    if numbers and numbers[0][1] in {1.0, 2.0} and "." not in numbers[0][0]:
        numbers = numbers[1:]
    if len(numbers) < 2:
        return shape, None, None
    return shape, numbers[0][1], numbers[1][1]


def _section_name_role(name: str, section_type: str = "") -> str:
    text = str(name or "").upper()
    type_text = str(section_type or "").upper()
    if (
        "BEAM" in text
        or "GIRDER" in text
        or type_text in {"BEAM", "GIRDER"}
    ):
        return "BEAM"
    member_text = re.sub(
        r"^\s*(?:(?:B?\d+F?|RF)\s*[~～-]\s*(?:B?\d+F?|RF)|(?:B?\d+F|RF))\s+",
        "",
        text,
    )
    member_match = re.search(r"[A-Z][A-Z0-9]*", member_text)
    member_token = member_match.group(0) if member_match else ""
    if member_token.startswith(("CGB", "CG", "WGB", "WG", "SG", "TG", "TB", "GB", "SB", "G", "B")):
        return "BEAM"
    if "COLUMN" in text or member_token.startswith(("SC", "C")):
        return "COLUMN"
    if "WALL" in text or member_token.startswith("W"):
        return "WALL"
    return "UNKNOWN"


def _infer_section_plan_width(
    name: str,
    section_type: str,
    width: float | None,
    depth: float | None,
    *,
    field_width: float | None = None,
    field_depth: float | None = None,
) -> float | None:
    role = _section_name_role(name, section_type)
    field_values = [value for value in (field_width, field_depth) if value is not None and value > 0.0]
    name_values = [value for value in (width, depth) if value is not None and value > 0.0]
    if role == "BEAM":
        if len(field_values) >= 2:
            return min(field_values)
        if len(field_values) == 1:
            return field_values[0]
        if len(name_values) >= 2:
            return min(name_values)
        return name_values[0] if name_values else None
    if role == "WALL":
        if len(field_values) >= 2:
            return min(field_values)
        if len(field_values) == 1:
            return field_values[0]
        if len(name_values) >= 2:
            return min(name_values)
        return name_values[0] if name_values else None
    if role == "COLUMN":
        if field_width is not None:
            return field_width
        if width is not None:
            return width
        return name_values[0] if name_values else None
    if len(field_values) >= 2:
        return min(field_values)
    if len(field_values) == 1:
        return field_values[0]
    if len(name_values) >= 2:
        return min(name_values)
    return name_values[0] if name_values else None


def _normalize_section_dimension_for_model_unit(value: float | None, length_unit: str) -> float | None:
    if value is None:
        return None
    if length_unit in {"M", "METER", "METRE"} and value >= 50.0:
        return value / 1000.0
    if length_unit in {"CM"} and value >= 50.0:
        return value / 10.0
    return value


def load_dm_material_section_ids_from_text(text: str) -> tuple[set[int], set[int]]:
    material_ids = {
        item.material_id
        for item in parse_materials_from_text(text)
        if _looks_like_load_dm_name(item.name)
    }
    section_ids = {
        item.section_id
        for item in parse_sections_from_text(text)
        if _looks_like_load_dm_name(item.name)
    }
    return material_ids, section_ids


def _looks_like_load_dm_name(value: str) -> bool:
    normalized = re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())
    return "LOADDM" in normalized


def _exact_load_dm_name(value: object) -> bool:
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper()) == "LOADDM"


def is_load_dm_material(value: ParsedMaterial | str) -> bool:
    """Return True only for the tool's explicit LOAD DM material marker."""

    name = value.name if isinstance(value, ParsedMaterial) else value
    return _exact_load_dm_name(name)


def is_load_dm_section(value: ParsedSection | str) -> bool:
    """Return True only for the tool's explicit LOAD DM section marker."""

    name = value.name if isinstance(value, ParsedSection) else value
    return _exact_load_dm_name(name)


def is_load_dm_element(
    element: Element,
    *,
    load_dm_material_ids: Iterable[int] = (),
    load_dm_section_ids: Iterable[int] = (),
    report_element_ids: Iterable[int] = (),
) -> bool:
    report_ids = {int(value) for value in report_element_ids}
    if int(element.elem_id) in report_ids:
        return True
    material_ids = {int(value) for value in load_dm_material_ids}
    section_ids = {int(value) for value in load_dm_section_ids}
    # Require both explicit resources whenever both ids are present.  This keeps
    # unrelated materials or sections containing a generic "DM" out.
    return (
        str(element.elem_type).upper() == "BEAM"
        and element.mat is not None
        and element.prop is not None
        and int(element.mat) in material_ids
        and int(element.prop) in section_ids
    )


def parse_frame_releases_from_text(text: str) -> list[ParsedFrameRelease]:
    releases: list[ParsedFrameRelease] = []
    lines = section_lines(text, "*FRAME-RLS")
    index = 0
    while index < len(lines):
        line = lines[index]
        if not _is_data_line(line, "*FRAME-RLS"):
            index += 1
            continue
        payload = _payload(line)
        parts = _csv_split(payload)
        element_id = _try_int(parts[0]) if parts else None
        if element_id is None:
            index += 1
            continue
        raw_lines = [line]
        next_index = index + 1
        if next_index < len(lines) and _payload(lines[next_index]) and not _payload(lines[next_index]).startswith("*"):
            raw_lines.append(lines[next_index])
            next_index += 1
        releases.append(ParsedFrameRelease(element_id=element_id, raw_lines=tuple(raw_lines), line_number=index + 1))
        index = next_index
    return releases


def parse_frame_release_for_element(text: str, element_id: int) -> ParsedFrameRelease | None:
    target = int(element_id)
    return next((item for item in parse_frame_releases_from_text(text) if int(item.element_id) == target), None)


def parse_existing_load_dm_members(
    text: str,
    *,
    report_element_ids: Iterable[int] = (),
) -> tuple[ExistingLoadDmMember, ...]:
    """Reconstruct committed LOAD DM beams for the HATCH VIEW overlay."""

    nodes = parse_nodes_from_text(text)
    stories = parse_stories_from_text(text) or infer_story_from_nodes(nodes)
    node_by_id = {int(node.node_id): node for node in nodes}
    material_ids = {item.material_id for item in parse_materials_from_text(text) if is_load_dm_material(item)}
    section_ids = {item.section_id for item in parse_sections_from_text(text) if is_load_dm_section(item)}
    releases = {item.element_id: item for item in parse_frame_releases_from_text(text)}
    result: list[ExistingLoadDmMember] = []
    for element in parse_elements_from_text(text):
        if not is_load_dm_element(
            element,
            load_dm_material_ids=material_ids,
            load_dm_section_ids=section_ids,
            report_element_ids=report_element_ids,
        ):
            continue
        if len(element.node_ids) < 2:
            continue
        node_i = node_by_id.get(int(element.node_ids[0]))
        node_j = node_by_id.get(int(element.node_ids[1]))
        if node_i is None or node_j is None:
            continue
        mean_z = (float(node_i.z) + float(node_j.z)) / 2.0
        story = min(stories, key=lambda item: (abs(float(item.elevation) - mean_z), str(item.name))) if stories else None
        release = releases.get(int(element.elem_id))
        warnings: list[str] = []
        if abs(float(node_i.z) - float(node_j.z)) > 1.0e-6:
            warnings.append("LOAD_DM_NODES_NOT_SAME_STORY")
        if release is None:
            warnings.append("LOAD_DM_FRAME_RELEASE_MISSING")
        elif sum("000011" in line for line in release.raw_lines) < 2:
            warnings.append("LOAD_DM_BOTH_END_RELEASE_INCOMPLETE")
        result.append(
            ExistingLoadDmMember(
                element_id=int(element.elem_id),
                story_name=str(story.name) if story is not None else "",
                node_i=int(node_i.node_id),
                node_j=int(node_j.node_id),
                start_xy=(float(node_i.x), float(node_i.y)),
                end_xy=(float(node_j.x), float(node_j.y)),
                material_id=element.mat,
                section_id=element.prop,
                release=release,
                warnings=tuple(warnings),
            )
        )
    return tuple(sorted(result, key=lambda item: item.element_id))


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


def _floorload_payload_and_continuation(line: str) -> tuple[str, bool]:
    payload = _payload(line).rstrip()
    continued = payload.endswith("\\")
    if continued:
        payload = payload[:-1].rstrip()
        if payload.endswith(","):
            payload = payload[:-1].rstrip()
    return payload, continued


def _parsed_floorload_record_from_payload(payload: str, line_number: int) -> ParsedFloorLoadRecord | None:
    parts = _csv_split(payload)
    if not parts:
        return None
    ltname = parts[0].strip().strip('"')
    idist = _try_int(parts[1]) if len(parts) > 1 else None
    node_start = 12 if idist in {1, 2} else 6 if idist in {3, 4} else 2
    node_ids: list[int] = []
    for value in parts[node_start:]:
        node_id = _try_int(value)
        if node_id is not None and node_id > 0:
            node_ids.append(node_id)
    return ParsedFloorLoadRecord(
        ltname=ltname,
        idist=idist,
        node_ids=tuple(node_ids),
        fields=tuple(parts),
        raw=payload,
        line_number=int(line_number),
    )


def _parsed_elastic_link_from_payload(payload: str, raw_lines: tuple[str, ...], line_number: int) -> ParsedElasticLink | None:
    parts = _csv_split(payload)
    if not parts:
        return None
    integer_tokens: list[int] = []
    for value in parts:
        integer_value = _try_int(value)
        if integer_value is not None:
            integer_tokens.append(integer_value)
    if len(integer_tokens) >= 3:
        link_id = integer_tokens[0]
        node_i = integer_tokens[1]
        node_j = integer_tokens[2]
    elif len(integer_tokens) == 2:
        link_id = None
        node_i = integer_tokens[0]
        node_j = integer_tokens[1]
    else:
        return None
    if node_i <= 0 or node_j <= 0 or node_i == node_j:
        return None
    return ParsedElasticLink(
        link_id=link_id,
        node_i=node_i,
        node_j=node_j,
        raw=payload,
        raw_lines=raw_lines,
        line_number=int(line_number),
    )


def _normalized_section_name(line: str) -> str:
    payload = _payload(line).strip()
    if not payload.startswith("*"):
        return ""
    return re.sub(r"[^A-Z0-9]", "", payload.lstrip("*").upper())


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
