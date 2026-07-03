from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions


def test_two_hatches_with_six_boundary_paths_become_six_regions(tmp_path: Path):
    dxf = tmp_path / "six_paths.dxf"
    doc = ezdxf.new("R2010")
    hatch1 = doc.modelspace().add_hatch(dxfattribs={"layer": "LOAD_005_Hall_DL_5_LL_5"})
    for boundary in [
        [(0, 0), (2, 0), (2, 1), (0, 1)],
        [(3, 0), (5, 0), (5, 1), (3, 1)],
        [(6, 0), (8, 0), (8, 1), (6, 1)],
        [(9, 0), (11, 0), (11, 1), (9, 1)],
    ]:
        hatch1.paths.add_polyline_path(boundary, is_closed=True)
    hatch2 = doc.modelspace().add_hatch(dxfattribs={"layer": "LOAD_003_Restaurant_DL_4.8_LL_4"})
    for boundary in [
        [(0, 3), (2, 3), (2, 4), (0, 4)],
        [(3, 3), (5, 3), (5, 4), (3, 4)],
    ]:
        hatch2.paths.add_polyline_path(boundary, is_closed=True)
    doc.saveas(dxf)

    regions = read_load_regions(dxf)

    assert len(regions) == 6
    assert [region.region.polygon_index for region in regions] == [1, 2, 3, 4, 1, 2]
    assert [region.region.hatch_index for region in regions] == [1, 1, 1, 1, 2, 2]
    assert all(region.status == "OK" for region in regions)
