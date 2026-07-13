from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_template_writer import (
    LOAD_LAYER_ACI_COLORS,
    LoadLayerSpec,
    _empty_bounds,
    _expand_bounds,
    _ensure_korean_text_style,
    load_layer_aci_color,
    write_all_story_centerline_dxf,
    write_story_centerline_dxf,
)
from app.core.mgt_parser import Element, Node, Story


def test_expand_bounds_tracks_min_max():
    bounds = _empty_bounds()

    _expand_bounds(bounds, [(2, 3), (-1, 5), (4, 1)])

    assert bounds == [-1.0, 1.0, 4.0, 5.0]


def test_ensure_korean_text_style_uses_malgun_font():
    doc = ezdxf.new("R2010")

    style_name = _ensure_korean_text_style(doc)

    assert style_name == "MALGUN_GOTHIC"
    assert doc.styles.get(style_name).dxf.font == "malgun.ttf"


def test_write_story_guide_text_below_geometry_with_malgun_style(tmp_path: Path):
    out = tmp_path / "story_template.dxf"
    story = Story("3F", 0.0)
    nodes = [Node(1, 10.0, 20.0, 0.0), Node(2, 30.0, 20.0, 0.0)]
    elements = [Element(1, "BEAM", node_ids=(1, 2))]

    write_story_centerline_dxf(output_path=out, story=story, nodes=nodes, elements=elements)

    doc = ezdxf.readfile(out)
    guide_texts = [text for text in doc.modelspace().query("TEXT") if text.dxf.layer == "FLOAD_GUIDE"]
    assert len(guide_texts) >= 6
    assert doc.styles.get("MALGUN_GOTHIC").dxf.font == "malgun.ttf"
    assert {text.dxf.style for text in guide_texts} == {"MALGUN_GOTHIC"}
    assert all(text.dxf.insert.y < 20.0 for text in guide_texts)
    guide = "\n".join(text.dxf.text for text in guide_texts)
    assert "0.01" not in guide
    assert "millimeters" in guide
    assert "● LOAD" in guide
    assert "◆ ONE WAY SLAB DIRECTION" in guide


def test_load_layer_palette_excludes_white_and_delays_repeats():
    colors = [load_layer_aci_color(index) for index in range(1, len(LOAD_LAYER_ACI_COLORS) + 1)]

    assert 7 not in colors
    assert len(colors) == len(set(colors))


def test_write_story_template_records_load_layer_aci_color(tmp_path: Path):
    out = tmp_path / "story_template.dxf"
    story = Story("3F", 0.0)
    nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0)]
    elements = [Element(1, "BEAM", node_ids=(1, 2))]
    loads = [
        LoadLayerSpec("Office", 1.0, 2.0),
        LoadLayerSpec("Lobby", 3.0, 4.0),
    ]

    result = write_story_centerline_dxf(output_path=out, story=story, nodes=nodes, elements=elements, load_layers=loads)

    doc = ezdxf.readfile(out)
    mapping_text = result.mapping_json_path.read_text(encoding="utf-8")
    csv_text = result.mapping_csv_path.read_text(encoding="utf-8-sig")
    assert '"aci_color": 1' in mapping_text
    assert "aci_color" in csv_text.splitlines()[0]
    assert doc.layers.get("● LOAD_001_Office_DL_1_LL_2").dxf.color == 1
    assert doc.layers.get("● LOAD_002_Lobby_DL_3_LL_4").dxf.color == 2
    assert doc.layers.get("CENTERLINE_BEAM").dxf.color == 7


def test_all_story_dxf_story_label_text_heights_are_common(tmp_path: Path):
    out = tmp_path / "all_story_labels.dxf"
    write_all_story_centerline_dxf(
        output_path=out,
        stories=[Story("1F", 0.0), Story("2F", 3.0)],
        nodes=[
            Node(1, 0.0, 0.0, 0.0),
            Node(2, 10.0, 0.0, 0.0),
            Node(3, 0.0, 0.0, 3.0),
            Node(4, 50.0, 0.0, 3.0),
        ],
        elements=[
            Element(1, "BEAM", node_ids=(1, 2)),
            Element(2, "BEAM", node_ids=(3, 4)),
        ],
    )

    doc = ezdxf.readfile(out)
    heights = {round(float(text.dxf.height), 6) for text in doc.modelspace().query("TEXT") if text.dxf.layer == "STORY_LABEL"}

    assert len(heights) == 1
