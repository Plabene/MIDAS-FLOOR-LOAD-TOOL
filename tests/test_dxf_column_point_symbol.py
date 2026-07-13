from pathlib import Path

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.dxf_story_layout import BBox2D, _compute_story_label_text_height, plan_story_layouts, read_layout_metadata
from app.core.dxf_template_writer import _compute_point_display_size, write_all_story_centerline_dxf, write_story_centerline_dxf
from app.core.mgt_parser import Element, Node, Story


def test_column_marker_is_point_entity(tmp_path: Path):
    out = tmp_path / "column_point.dxf"
    _write_single_story_column_template(out)

    doc = ezdxf.readfile(out)
    column_points = [entity for entity in doc.modelspace() if entity.dxf.layer == "CENTERLINE_COLUMN" and entity.dxftype() == "POINT"]

    assert len(column_points) > 0


def test_column_marker_does_not_create_hatch_interfering_geometry(tmp_path: Path):
    out = tmp_path / "column_point.dxf"
    _write_single_story_column_template(out)

    doc = ezdxf.readfile(out)
    bad_types = {"LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC"}
    bad = [entity for entity in doc.modelspace() if entity.dxf.layer == "CENTERLINE_COLUMN" and entity.dxftype() in bad_types]

    assert bad == []


def test_dxf_sets_point_display_header(tmp_path: Path):
    out = tmp_path / "column_point.dxf"
    _write_single_story_column_template(out)

    doc = ezdxf.readfile(out)

    assert int(doc.header.get("$PDMODE")) == 34
    assert float(doc.header.get("$PDSIZE")) > 0.0


def test_point_display_size_scales_with_bbox():
    small = _compute_point_display_size(BBox2D(0.0, 0.0, 10.0, 10.0))
    large = _compute_point_display_size(BBox2D(0.0, 0.0, 100.0, 100.0))

    assert large > small
    assert large / small == pytest.approx(10.0, rel=0.5)


def test_load_reader_ignores_centerline_column_layer(tmp_path: Path):
    dxf = tmp_path / "column_is_not_load.dxf"
    doc = ezdxf.new("R2010")
    doc.layers.add("CENTERLINE_COLUMN")
    doc.layers.add("LOAD_001_Office_DL_1.2_LL_3.4")
    msp = doc.modelspace()
    msp.add_point((1.0, 1.0), dxfattribs={"layer": "CENTERLINE_COLUMN"})
    hatch = msp.add_hatch(dxfattribs={"layer": "CENTERLINE_COLUMN"})
    hatch.paths.add_polyline_path([(0, 0), (1, 0), (1, 1), (0, 1)], is_closed=True)
    msp.add_lwpolyline([(2, 2), (3, 2), (3, 3), (2, 3)], close=True, dxfattribs={"layer": "CENTERLINE_COLUMN"})
    load_hatch = msp.add_hatch(dxfattribs={"layer": "LOAD_001_Office_DL_1.2_LL_3.4"})
    load_hatch.paths.add_polyline_path([(10, 10), (12, 10), (12, 12), (10, 12)], is_closed=True)
    doc.saveas(dxf)

    regions = read_load_regions(dxf)

    assert len(regions) == 1
    assert all(region.region.layer != "CENTERLINE_COLUMN" for region in regions)
    assert regions[0].region.layer == "LOAD_001_Office_DL_1.2_LL_3.4"


def test_story_label_text_height_still_scales_with_bbox():
    small = _compute_story_label_text_height(BBox2D(0.0, 0.0, 10.0, 10.0))
    large = _compute_story_label_text_height(BBox2D(0.0, 0.0, 100.0, 100.0))

    assert small == pytest.approx(0.90)
    assert large > small
    assert large == pytest.approx(9.0)
    assert large / small == pytest.approx(10.0, rel=0.5)


def test_story_label_is_placed_outside_left_of_building_bbox():
    layout = plan_story_layouts([Story("1F", 0.0)], [BBox2D(10.0, 20.0, 40.0, 60.0)])[0]
    label_gap = layout.placed_bbox.min_x - layout.label_x
    story_short = max(min(layout.placed_bbox.width, layout.placed_bbox.height), 1.0)

    assert layout.label_x < layout.placed_bbox.min_x
    assert label_gap == pytest.approx(max(layout.text_height * 1.5, story_short * 0.04))
    assert layout.label_y == pytest.approx((layout.placed_bbox.min_y + layout.placed_bbox.max_y) / 2.0)


def test_all_story_metadata_contains_scaled_label_position_and_text_height(tmp_path: Path):
    out = tmp_path / "all_story_column_point.dxf"
    result = write_all_story_centerline_dxf(
        output_path=out,
        stories=[Story("1F", 0.0), Story("2F", 3.0)],
        nodes=[
            Node(1, 0.0, 0.0, 0.0),
            Node(2, 10.0, 0.0, 0.0),
            Node(3, 5.0, 5.0, 0.0),
            Node(4, 5.0, 5.0, 3.0),
            Node(11, 0.0, 0.0, 3.0),
            Node(12, 20.0, 0.0, 3.0),
            Node(13, 10.0, 10.0, 3.0),
            Node(14, 10.0, 10.0, 6.0),
        ],
        elements=[
            Element(1, "BEAM", node_ids=(1, 2)),
            Element(2, "COLUMN", node_ids=(3, 4)),
            Element(11, "BEAM", node_ids=(11, 12)),
            Element(12, "COLUMN", node_ids=(13, 14)),
        ],
    )

    layouts = read_layout_metadata(result.layout_metadata_path)
    doc = ezdxf.readfile(out)
    labels = {text.dxf.text: text for text in doc.modelspace().query("TEXT") if text.dxf.layer == "STORY_LABEL"}
    column_points = [entity for entity in doc.modelspace() if entity.dxf.layer == "CENTERLINE_COLUMN" and entity.dxftype() == "POINT"]

    assert len(column_points) >= 1
    for layout in layouts:
        label = labels[layout.story_name]
        assert float(label.dxf.height) == pytest.approx(layout.text_height)
        assert float(label.dxf.insert.x) == pytest.approx(layout.label_x)
        assert float(label.dxf.insert.y) == pytest.approx(layout.label_y)
        assert int(label.dxf.halign) == 2
        assert layout.label_x < layout.placed_bbox.min_x


def test_load_dm_dummy_checkbox_lives_on_dxf_tab_static():
    source = Path("app/main.py").read_text(encoding="utf-8")
    dxf_body = source.split("def _build_dxf_tab", 1)[1].split("def _create_scrollable_checklist", 1)[0]
    build_body = source.split("def _build_build_tab", 1)[1].split("def _build_log_tab", 1)[0]

    assert "auto_load_dm_dummy_var" in dxf_body
    assert "LOAD DM dummy BEAM" in dxf_body
    assert "auto_load_dm_dummy_var" not in build_body
    assert source.count("self.auto_load_dm_dummy_var = tk.BooleanVar") == 1


def test_column_point_change_does_not_change_centerline_coordinates_or_layout_transform(tmp_path: Path):
    out = tmp_path / "all_story_coordinates.dxf"
    result = write_all_story_centerline_dxf(
        output_path=out,
        stories=[Story("2F", 3.0)],
        nodes=[
            Node(1, 0.0, 0.0, 3.0),
            Node(2, 10.0, 0.0, 3.0),
            Node(3, 5.0, 5.0, 0.0),
            Node(4, 5.0, 5.0, 3.0),
        ],
        elements=[
            Element(1, "BEAM", node_ids=(1, 2)),
            Element(2, "COLUMN", node_ids=(3, 4)),
        ],
    )

    layout = read_layout_metadata(result.layout_metadata_path)[0]
    doc = ezdxf.readfile(out)
    beam_lines = [entity for entity in doc.modelspace().query("LINE") if entity.dxf.layer == "CENTERLINE_BEAM"]

    assert layout.source_bbox == BBox2D(0.0, 0.0, 10.0, 5.0)
    assert layout.transform.apply(0.0, 0.0) == pytest.approx((0.0, -5.0))
    assert layout.inverse_transform.apply(*layout.transform.apply(5.0, 5.0)) == pytest.approx((5.0, 5.0))
    assert len(beam_lines) == 1
    assert (float(beam_lines[0].dxf.start.x), float(beam_lines[0].dxf.start.y)) == pytest.approx((0.0, -5.0))
    assert (float(beam_lines[0].dxf.end.x), float(beam_lines[0].dxf.end.y)) == pytest.approx((10.0, -5.0))


def _write_single_story_column_template(out: Path) -> None:
    write_story_centerline_dxf(
        output_path=out,
        story=Story("2F", 3.0),
        stories=[Story("1F", 0.0), Story("2F", 3.0)],
        nodes=[
            Node(1, 5.0, 5.0, 0.0),
            Node(2, 5.0, 5.0, 3.0),
            Node(3, 0.0, 0.0, 3.0),
            Node(4, 20.0, 0.0, 3.0),
        ],
        elements=[
            Element(1, "COLUMN", node_ids=(1, 2)),
            Element(2, "BEAM", node_ids=(3, 4)),
        ],
    )
