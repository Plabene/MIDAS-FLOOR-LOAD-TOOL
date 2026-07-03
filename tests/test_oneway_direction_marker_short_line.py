from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.floorload_mgt_builder import build_assignments_from_regions
from app.core.load_input_policy import infer_short_span_angle
from app.core.mgt_parser import Node


def _write_oneway_dxf(path: Path, marker_count: int = 1) -> None:
    doc = ezdxf.new("R2010")
    load_layer = "LOAD_001_Office_DL_1.2_LL_3.4"
    doc.layers.add(load_layer)
    doc.layers.add("ONE WAY SLAB DIRECTION")
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": load_layer})
    hatch.set_pattern_fill("ANSI31", scale=1.0)
    hatch.paths.add_polyline_path([(0, 0), (10, 0), (10, 3), (0, 3)], is_closed=True)
    doc.modelspace().add_line((1.0, 1.0), (1.3, 1.0), dxfattribs={"layer": "ONE WAY SLAB DIRECTION"})
    if marker_count > 1:
        doc.modelspace().add_line((2.0, 1.0), (2.0, 1.4), dxfattribs={"layer": "ONE WAY SLAB DIRECTION"})
    doc.saveas(path)


def _nodes() -> list[Node]:
    return [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 3.0, 0.0),
        Node(4, 0.0, 3.0, 0.0),
    ]


def test_short_direction_marker_inside_polygon_is_used(tmp_path: Path):
    dxf = tmp_path / "short_marker.dxf"
    _write_oneway_dxf(dxf)

    region = read_load_regions(dxf)[0]
    assignments = build_assignments_from_regions(regions=[region], story_nodes=_nodes(), snap_tolerance=0.01, include_zero_load=True)

    assert len(region.region.direction_markers) == 1
    assert assignments[0].effective_idist == 1
    assert assignments[0].direction_source == "DXF_DIRECTION_MARKER"
    assert assignments[0].one_way_angle_deg == pytest.approx(0.0)


def test_multiple_direction_markers_inside_polygon_is_ambiguous(tmp_path: Path):
    dxf = tmp_path / "ambiguous_marker.dxf"
    _write_oneway_dxf(dxf, marker_count=2)

    region = read_load_regions(dxf)[0]
    assignments = build_assignments_from_regions(regions=[region], story_nodes=_nodes(), snap_tolerance=0.01, include_zero_load=True)

    assert len(region.region.direction_markers) == 2
    assert assignments[0].status == "AMBIGUOUS_ONEWAY_DIRECTION"


def test_one_way_default_direction_is_short_span_main_direction():
    points = [(0, 0), (10, 0), (10, 3), (0, 3)]

    angle, source, warnings = infer_short_span_angle(points)

    assert source in {"AUTO_SHORT_SPAN", "AUTO_SHORT_SPAN_BBOX"}
    assert abs((angle % 180.0) - 90.0) < 1.0e-6
    assert "REVIEW_AUTO_SHORT_SPAN_USED" in warnings


def test_direction_marker_overrides_short_span_main_direction(tmp_path: Path):
    dxf = tmp_path / "marker_override.dxf"
    _write_oneway_dxf(dxf)

    region = read_load_regions(dxf)[0]
    assignments = build_assignments_from_regions(regions=[region], story_nodes=_nodes(), snap_tolerance=0.01, include_zero_load=True)

    assert assignments[0].direction_source == "DXF_DIRECTION_MARKER"
    assert abs((assignments[0].one_way_angle_deg % 180.0) - 0.0) < 1.0e-6
