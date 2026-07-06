from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.dxf_story_layout import read_layout_metadata
from app.core.dxf_template_writer import (
    HATCH_GUIDE_LAYER,
    LoadLayerSpec,
    normalize_hatch_scale,
    write_all_story_centerline_dxf,
    write_story_centerline_dxf,
)
from app.core.load_input_policy import infer_distribution
from app.core.mgt_parser import Element, Node, Story


def test_normalize_hatch_scale():
    assert normalize_hatch_scale("0.01") == 0.01
    assert normalize_hatch_scale("0.02") == 0.02
    assert normalize_hatch_scale("0") == 1.0
    assert normalize_hatch_scale("-1") == 1.0
    assert normalize_hatch_scale("abc") == 1.0


def test_dxf_template_contains_hatch_scale_guide(tmp_path: Path):
    out = tmp_path / "template.dxf"
    write_story_centerline_dxf(
        output_path=out,
        story=Story("1F", 0.0),
        nodes=[Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0)],
        elements=[Element(1, "BEAM", node_ids=(1, 2))],
        default_hatch_scale=0.01,
    )

    doc = ezdxf.readfile(out)
    if doc.header.get("$HPSCALE") is not None:
        assert abs(float(doc.header.get("$HPSCALE")) - 1.0) < 1.0e-9
    if doc.header.get("$HPNAME") is not None:
        assert str(doc.header.get("$HPNAME")).upper() == "ANSI31"
    guide_hatches = [hatch for hatch in doc.modelspace().query("HATCH") if hatch.dxf.layer == HATCH_GUIDE_LAYER]
    assert len(guide_hatches) == 1
    assert guide_hatches[0].dxf.pattern_name.upper() == "ANSI31"
    assert abs(float(guide_hatches[0].dxf.pattern_scale) - 1.0) < 1.0e-9


def test_hatch_scale_does_not_affect_distribution_detection(tmp_path: Path):
    dxf = tmp_path / "pattern_scale.dxf"
    layer = "LOAD_001_Office_DL_1.2_LL_3.4"
    doc = ezdxf.new("R2010")
    doc.layers.add(layer)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": layer})
    hatch.set_pattern_fill("ANSI31", scale=0.01)
    hatch.paths.add_polyline_path([(0, 0), (4, 0), (4, 3), (0, 3)], is_closed=True)
    doc.saveas(dxf)

    region = read_load_regions(dxf)[0]
    distribution, source = infer_distribution(region.region, region.load)

    assert region.region.hatch_pattern_scale == pytest.approx(0.01)
    assert region.region.hatch_pattern_name == "ANSI31"
    assert distribution == "ONE_WAY"
    assert source == "HATCH_PATTERN_NON_SOLID_ONEWAY"


def test_hatch_scale_setting_does_not_change_geometry_coordinates(tmp_path: Path):
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
    ]
    elements = [
        Element(1, "BEAM", node_ids=(1, 2)),
        Element(2, "BEAM", node_ids=(11, 12)),
    ]
    small = write_all_story_centerline_dxf(
        output_path=tmp_path / "small.dxf",
        stories=stories,
        nodes=nodes,
        elements=elements,
        load_layers=[LoadLayerSpec("Office", 1.2, 3.4)],
        default_hatch_scale=0.01,
    )
    large = write_all_story_centerline_dxf(
        output_path=tmp_path / "large.dxf",
        stories=stories,
        nodes=nodes,
        elements=elements,
        load_layers=[LoadLayerSpec("Office", 1.2, 3.4)],
        default_hatch_scale=1.0,
    )

    assert _centerline_lines(small.dxf_path) == _centerline_lines(large.dxf_path)
    small_layouts = read_layout_metadata(small.layout_metadata_path)
    large_layouts = read_layout_metadata(large.layout_metadata_path)
    assert [(layout.source_bbox, layout.placed_bbox, layout.transform, layout.inverse_transform) for layout in small_layouts] == [
        (layout.source_bbox, layout.placed_bbox, layout.transform, layout.inverse_transform) for layout in large_layouts
    ]


def test_hatch_guide_layer_is_excluded_from_load_reader(tmp_path: Path):
    out = tmp_path / "template.dxf"
    write_story_centerline_dxf(
        output_path=out,
        story=Story("1F", 0.0),
        nodes=[Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0)],
        elements=[Element(1, "BEAM", node_ids=(1, 2))],
        default_hatch_scale=0.01,
    )

    assert read_load_regions(out) == []


def _centerline_lines(path: Path) -> list[tuple[str, tuple[float, float], tuple[float, float]]]:
    doc = ezdxf.readfile(path)
    lines = []
    for entity in doc.modelspace().query("LINE"):
        layer = str(entity.dxf.layer)
        if not layer.startswith("CENTERLINE_"):
            continue
        lines.append((layer, (float(entity.dxf.start.x), float(entity.dxf.start.y)), (float(entity.dxf.end.x), float(entity.dxf.end.y))))
    return sorted(lines)
