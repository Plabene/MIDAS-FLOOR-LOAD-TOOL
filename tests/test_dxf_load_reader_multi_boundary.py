from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions


LOAD_LAYER = "LOAD_001_Office_DL_1.2_LL_3.4"


def _write_hatch_dxf(path: Path, boundary_paths: list[list[tuple[float, float]]]) -> None:
    doc = ezdxf.new("R2010")
    doc.layers.add(LOAD_LAYER)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": LOAD_LAYER})
    for boundary in boundary_paths:
        hatch.paths.add_polyline_path(boundary, is_closed=True)
    doc.saveas(path)


def test_one_hatch_with_disjoint_boundaries_becomes_multiple_regions(tmp_path: Path):
    dxf = tmp_path / "multi_boundary.dxf"
    _write_hatch_dxf(
        dxf,
        [
            [(0, 0), (1, 0), (1, 1), (0, 1)],
            [(10, 0), (11, 0), (11, 1), (10, 1)],
        ],
    )

    regions = read_load_regions(dxf)

    assert len(regions) == 2
    assert [region.region.polygon_index for region in regions] == [1, 2]
    assert sorted(round(region.area, 6) for region in regions) == [1.0, 1.0]
    assert all(region.status == "OK" for region in regions)
    assert all(region.load and region.load.real_name == "Office" for region in regions)
    assert all(region.region.source_id for region in regions)


def test_nested_hatch_boundary_becomes_polygon_hole(tmp_path: Path):
    dxf = tmp_path / "hole_boundary.dxf"
    _write_hatch_dxf(
        dxf,
        [
            [(0, 0), (4, 0), (4, 4), (0, 4)],
            [(1, 1), (3, 1), (3, 3), (1, 3)],
        ],
    )

    regions = read_load_regions(dxf)

    assert len(regions) == 1
    assert round(regions[0].area, 6) == 12.0
    assert len(regions[0].polygon.interiors) == 1
