from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_template_writer import _empty_bounds, _expand_bounds, _ensure_korean_text_style, write_story_centerline_dxf
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
    assert len(guide_texts) == 2
    assert doc.styles.get("MALGUN_GOTHIC").dxf.font == "malgun.ttf"
    assert {text.dxf.style for text in guide_texts} == {"MALGUN_GOTHIC"}
    assert all(text.dxf.insert.y < 20.0 for text in guide_texts)
