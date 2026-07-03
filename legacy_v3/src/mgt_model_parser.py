from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import median


@dataclass(frozen=True)
class MgtNode:
    node_id: int
    x: float
    y: float
    z: float

    @property
    def xy(self) -> tuple[float, float]:
        return (self.x, self.y)

    def to_record(self) -> dict:
        return {"node_id": self.node_id, "x": self.x, "y": self.y, "z": self.z}


def read_mgt_text(path: str | Path, encodings: tuple[str, ...] = ("utf-8", "cp949", "euc-kr", "latin1")) -> str:
    data = Path(path).read_bytes()
    last_error: Exception | None = None
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    if last_error is not None:
        return data.decode(encodings[-1], errors="replace")
    return data.decode("utf-8", errors="replace")


def parse_mgt_nodes(path: str | Path) -> list[MgtNode]:
    return parse_mgt_nodes_from_text(read_mgt_text(path))


def parse_mgt_nodes_from_text(text: str) -> list[MgtNode]:
    nodes: list[MgtNode] = []
    in_node_block = False

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";"):
            continue
        upper = line.upper()
        if upper.startswith("*"):
            in_node_block = upper.startswith("*NODE")
            continue
        if not in_node_block:
            continue

        payload = line.split(";", 1)[0].strip()
        if not payload:
            continue
        parts = [part.strip() for part in payload.split(",")]
        if len(parts) < 4:
            parts = payload.split()
        if len(parts) < 4:
            continue
        try:
            nodes.append(MgtNode(int(float(parts[0])), float(parts[1]), float(parts[2]), float(parts[3])))
        except ValueError:
            continue

    return nodes


def filter_nodes_by_z(nodes: list[MgtNode], z_level: float | None, z_tolerance: float = 1.0e-3) -> list[MgtNode]:
    if z_level is None:
        return list(nodes)
    tolerance = abs(float(z_tolerance))
    return [node for node in nodes if abs(node.z - float(z_level)) <= tolerance]


def select_floor_nodes(
    nodes: list[MgtNode],
    *,
    z_level: float | None = None,
    floor_name: str | None = None,
    z_tolerance: float = 1.0e-3,
) -> list[MgtNode]:
    # MGT/MGTX node blocks usually do not carry floor names. The floor_name is
    # accepted for UI/log compatibility; z_level is the authoritative filter.
    _ = floor_name
    selected = filter_nodes_by_z(nodes, z_level, z_tolerance)
    if not selected:
        raise ValueError(f"No MGT nodes found for z_level={z_level} within tolerance={z_tolerance}.")
    return selected


def infer_representative_z(nodes: list[MgtNode]) -> float | None:
    if not nodes:
        return None
    return float(median(node.z for node in nodes))