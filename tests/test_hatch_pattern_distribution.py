from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.load_input_policy import infer_distribution


def _write_hatch(path: Path, *, layer: str, pattern: str = "SOLID") -> None:
    doc = ezdxf.new("R2010")
    if layer not in doc.layers:
        doc.layers.add(layer)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": layer})
    if pattern != "SOLID":
        hatch.set_pattern_fill(pattern, scale=1.0)
    hatch.paths.add_polyline_path([(0, 0), (4, 0), (4, 3), (0, 3)], is_closed=True)
    doc.saveas(path)


def test_solid_hatch_defaults_to_two_way(tmp_path: Path):
    dxf = tmp_path / "solid.dxf"
    _write_hatch(dxf, layer="LOAD_001_Office_DL_1.2_LL_3.4", pattern="SOLID")

    region = read_load_regions(dxf)[0]
    distribution, source = infer_distribution(region.region, region.load)

    assert region.region.hatch_solid_fill == 1
    assert distribution == "TWO_WAY"
    assert source == "HATCH_PATTERN_SOLID_TWOWAY"


def test_non_solid_hatch_defaults_to_one_way(tmp_path: Path):
    dxf = tmp_path / "pattern.dxf"
    _write_hatch(dxf, layer="LOAD_001_Office_DL_1.2_LL_3.4", pattern="ANSI31")

    region = read_load_regions(dxf)[0]
    distribution, source = infer_distribution(region.region, region.load)

    assert region.region.hatch_solid_fill == 0
    assert region.region.hatch_pattern_name == "ANSI31"
    assert distribution == "ONE_WAY"
    assert source == "HATCH_PATTERN_NON_SOLID_ONEWAY"


def test_layer_token_overrides_hatch_pattern(tmp_path: Path):
    dxf = tmp_path / "override.dxf"
    _write_hatch(dxf, layer="LOAD_001_Office_OW_90_DL_1.2_LL_3.4", pattern="SOLID")

    region = read_load_regions(dxf)[0]
    distribution, source = infer_distribution(region.region, region.load)

    assert distribution == "ONE_WAY"
    assert source == "LAYER_TOKEN"
    assert region.load.one_way_angle_deg == 90.0
