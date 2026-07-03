from pathlib import Path
import pytest
ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions


def test_closed_lwpolyline_fallback(tmp_path: Path):
    dxf = tmp_path / "load.dxf"
    doc = ezdxf.new("R2010")
    if "LOAD_001_사무실_DL_1.2_LL_3.0" not in doc.layers:
        doc.layers.add("LOAD_001_사무실_DL_1.2_LL_3.0")
    msp = doc.modelspace()
    msp.add_lwpolyline([(0, 0), (1, 0), (1, 1), (0, 1)], close=True, dxfattribs={"layer": "LOAD_001_사무실_DL_1.2_LL_3.0"})
    doc.saveas(dxf)
    regions = read_load_regions(dxf)
    assert len(regions) == 1
    assert regions[0].region.source_type == "LWPOLYLINE"
    assert regions[0].load.real_name == "사무실"
