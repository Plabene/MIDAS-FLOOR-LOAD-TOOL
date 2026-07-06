from pathlib import Path
import json

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.dxf_story_layout import read_layout_metadata
from app.core.dxf_template_writer import LoadLayerSpec, write_story_centerline_dxf
from app.core.load_input_policy import is_direction_layer
from app.core.load_parser import add_cad_direction_layer_prefix, add_cad_load_layer_prefix, parse_load_layer
from app.core.mgt_parser import (
    Element,
    Node,
    Story,
    dxf_insunits_for_output_mm,
    dxf_unit_scale_from_model_length_unit,
    parse_unit_from_text,
)


def test_mgt_unit_length_scale_to_dxf_mm():
    assert parse_unit_from_text("*UNIT\n   KN, M, KJ, C\n").length == "M"
    assert dxf_unit_scale_from_model_length_unit("M") == 1000.0
    assert dxf_unit_scale_from_model_length_unit("MM") == 1.0
    assert dxf_unit_scale_from_model_length_unit("CM") == 10.0
    assert dxf_insunits_for_output_mm() == 4


def test_single_story_dxf_metadata_scales_to_mm_and_reads_back_to_model_xy(tmp_path: Path):
    out = tmp_path / "story_template.dxf"
    story = Story("1F", 0.0)
    nodes = [Node(1, 9.7, 14.0, 0.0), Node(2, 11.7, 14.0, 0.0)]
    elements = [Element(1, "BEAM", node_ids=(1, 2))]

    result = write_story_centerline_dxf(
        output_path=out,
        story=story,
        nodes=nodes,
        elements=elements,
        load_layers=[LoadLayerSpec("Office", 1.2, 3.4)],
        model_length_unit="M",
        dxf_unit_scale_from_model=1000.0,
    )

    doc = ezdxf.readfile(out)
    assert int(doc.header["$INSUNITS"]) == 4
    line = next(entity for entity in doc.modelspace().query("LINE") if entity.dxf.layer == "CENTERLINE_BEAM")
    assert float(line.dxf.end.x - line.dxf.start.x) == pytest.approx(2000.0)

    metadata = json.loads(result.layout_metadata_path.read_text(encoding="utf-8"))
    assert metadata["mode"] == "SINGLE_STORY"
    assert metadata["model_length_unit"] == "M"
    assert metadata["dxf_display_unit"] == "MM"
    assert metadata["dxf_unit_scale_from_model"] == pytest.approx(1000.0)

    layout = read_layout_metadata(result.layout_metadata_path)[0]
    assert layout.transform.a == pytest.approx(1000.0)
    placed = layout.transform.apply(9.7, 14.0)
    assert placed == pytest.approx((float(line.dxf.start.x), float(line.dxf.start.y)))
    assert layout.inverse_transform.apply(*placed) == pytest.approx((9.7, 14.0))

    load_layer = add_cad_load_layer_prefix("LOAD_001_Office_DL_1.2_LL_3.4")
    polygon_model = [(9.8, 13.8), (10.8, 13.8), (10.8, 14.2), (9.8, 14.2)]
    polygon_dxf = [layout.transform.apply(x, y) for x, y in polygon_model]
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": load_layer})
    hatch.paths.add_polyline_path(polygon_dxf, is_closed=True)
    doc.saveas(out)

    regions = read_load_regions(out, mapping_path=result.mapping_json_path, layout_metadata_path=result.layout_metadata_path)
    assert len(regions) == 1
    assert regions[0].region.story_name == "1F"
    assert regions[0].region.bbox == pytest.approx((9.8, 13.8, 10.8, 14.2))
    assert regions[0].area == pytest.approx(0.4)


def test_template_user_work_layers_are_prefixed_and_parser_accepts_prefix(tmp_path: Path):
    out = tmp_path / "prefixed_layers.dxf"
    result = write_story_centerline_dxf(
        output_path=out,
        story=Story("1F", 0.0),
        nodes=[Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0)],
        elements=[Element(1, "BEAM", node_ids=(1, 2))],
        load_layers=[LoadLayerSpec("Office", 1.2, 3.4)],
    )

    doc = ezdxf.readfile(out)
    layer_names = {layer.dxf.name for layer in doc.layers}
    load_layer = add_cad_load_layer_prefix("LOAD_001_Office_DL_1.2_LL_3.4")
    direction_layer = add_cad_direction_layer_prefix("ONE WAY SLAB DIRECTION")
    assert load_layer in layer_names
    assert "LOAD_001_Office_DL_1.2_LL_3.4" not in layer_names
    assert direction_layer in layer_names
    assert "ONE WAY SLAB DIRECTION" not in layer_names
    assert "CENTERLINE_BEAM" in layer_names

    mapping = json.loads(result.mapping_json_path.read_text(encoding="utf-8"))
    assert mapping[0]["layer"] == load_layer
    assert mapping[0]["core_layer"] == "LOAD_001_Office_DL_1.2_LL_3.4"

    parsed = parse_load_layer(load_layer)
    assert parsed.layer == load_layer
    assert parsed.real_name == "Office"
    assert parsed.dl == pytest.approx(1.2)
    assert parsed.ll == pytest.approx(3.4)
    assert is_direction_layer(direction_layer)
