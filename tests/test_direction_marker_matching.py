from pathlib import Path

import pytest
from shapely.geometry import Polygon

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import (
    DirectionMarker,
    _direction_marker_matches_polygon,
    _direction_markers_from_entity,
    read_load_regions,
)


def test_long_direction_line_crossing_multiple_hatches_matches_all(tmp_path: Path):
    dxf = tmp_path / "crossing_multiple_hatches.dxf"
    doc = ezdxf.new("R2010")
    load_layer = "LOAD_001_Office_DL_1.2_LL_3.4"
    doc.layers.add(load_layer)
    doc.layers.add("ONE WAY SLAB DIRECTION")
    msp = doc.modelspace()
    for points in (
        [(0, 0), (5, 0), (5, 4), (0, 4)],
        [(5, 0), (10, 0), (10, 4), (5, 4)],
        [(10, 0), (15, 0), (15, 4), (10, 4)],
    ):
        hatch = msp.add_hatch(dxfattribs={"layer": load_layer})
        hatch.set_pattern_fill("ANSI31", scale=1.0)
        hatch.paths.add_polyline_path(points, is_closed=True)
    msp.add_line((-2, 2), (17, 2), dxfattribs={"layer": "ONE WAY SLAB DIRECTION"})
    doc.saveas(dxf)

    regions = read_load_regions(dxf)

    assert len(regions) == 3
    assert all(len(region.region.direction_markers) == 1 for region in regions)
    assert {region.region.direction_markers[0].source_id for region in regions} == {
        regions[0].region.direction_markers[0].source_id
    }
    assert {region.region.direction_markers[0].match_method for region in regions} == {"INTERSECT", "MIDPOINT_INSIDE"}


def test_parallel_outside_direction_line_does_not_match_by_default():
    polygon = Polygon([(0, 0), (5, 0), (5, 4), (0, 4)])
    marker = DirectionMarker(
        source_type="LINE",
        layer="ONE WAY SLAB DIRECTION",
        handle="D1",
        start=(-2, 5),
        end=(7, 5),
        source_id="D1",
    )

    assert not _direction_marker_matches_polygon(marker, polygon)


def test_direction_polyline_is_split_into_segments():
    doc = ezdxf.new("R2010")
    doc.layers.add("ONE WAY SLAB DIRECTION")
    entity = doc.modelspace().add_lwpolyline(
        [(0, 0), (5, 0), (5, 4), (9, 4)],
        dxfattribs={"layer": "ONE WAY SLAB DIRECTION"},
    )

    markers = _direction_markers_from_entity(entity)

    assert len(markers) == 3
    assert [marker.segment_index for marker in markers] == [1, 2, 3]
    assert [marker.start for marker in markers] == [(0.0, 0.0), (5.0, 0.0), (5.0, 4.0)]
    assert [marker.end for marker in markers] == [(5.0, 0.0), (5.0, 4.0), (9.0, 4.0)]
    assert [marker.source_id for marker in markers] == [f"{entity.dxf.handle}:SEG1", f"{entity.dxf.handle}:SEG2", f"{entity.dxf.handle}:SEG3"]
