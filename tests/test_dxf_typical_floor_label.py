from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_story_layout import read_layout_metadata
from app.core.dxf_template_writer import write_all_story_centerline_dxf
from app.core.floorload_mgt_builder import FloorLoadAssignment, patch_full_mgt_text
from app.core.mgt_parser import Element, Node, Story


def test_typical_story_label_has_typ_prefix_and_metadata(tmp_path: Path):
    out = tmp_path / "typical_floor_template.dxf"
    stories = [Story("1F", 0.0), Story("2F", 3.0)]
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 10.0, 0.0, 3.0),
        Node(13, 10.0, 10.0, 3.0),
        Node(14, 0.0, 10.0, 3.0),
    ]
    elements = [Element(1, "SLAB", node_ids=(1, 2, 3, 4)), Element(2, "SLAB", node_ids=(11, 12, 13, 14))]

    result = write_all_story_centerline_dxf(
        output_path=out,
        stories=stories,
        nodes=nodes,
        elements=elements,
        typical_story_names=["2F"],
    )

    doc = ezdxf.readfile(result.dxf_path)
    labels = [text.dxf.text for text in doc.modelspace().query("TEXT") if text.dxf.layer == "STORY_LABEL"]
    assert "typ. 2F" in labels
    assert "1F" in labels
    assert "typ. 1F" not in labels

    layouts = read_layout_metadata(result.layout_metadata_path)
    by_story = {layout.story_name: layout for layout in layouts}
    assert by_story["2F"].is_typical is True
    assert by_story["2F"].typical_story_name == "2F"
    assert by_story["1F"].is_typical is False


def test_typical_label_text_is_not_written_to_mgt():
    assignment = FloorLoadAssignment(
        load_type_name="Office",
        dl=1.2,
        ll=3.4,
        node_ids=(1, 2, 3, 4),
        source_layer="LOAD_001_Office_DL_1.2_LL_3.4",
        source_type="HATCH",
        area=100.0,
        status="OK",
        warnings=(),
        story_name="2F",
    )

    patched = patch_full_mgt_text("*ENDDATA", assignments=[assignment])

    assert "typ." not in patched
    assert "Office" in patched
