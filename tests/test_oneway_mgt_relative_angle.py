import pytest
from shapely.geometry import Polygon

from app.core.dxf_load_reader import DirectionMarker, HatchRegion, LoadRegion
from app.core.floorload_mgt_builder import (
    FloorLoadAssignment,
    _compute_short_span_global_angle_from_nodes,
    _to_midas_one_way_relative_angle,
    build_assignments_from_regions,
    patch_full_mgt_text,
)
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Node


def _example_nodes() -> list[Node]:
    return [
        Node(1326, 9.7, 14.0, 0.0),
        Node(1325, 9.7, 8.0, 0.0),
        Node(1327, 13.1, 8.0, 0.0),
        Node(1328, 13.1, 14.0, 0.0),
    ]


def _example_node_lookup() -> dict[int, Node]:
    return {node.node_id: node for node in _example_nodes()}


def _example_region(*, direction_markers: list[DirectionMarker] | None = None) -> LoadRegion:
    vertices = [(9.7, 14.0), (9.7, 8.0), (13.1, 8.0), (13.1, 14.0)]
    polygon = Polygon(vertices)
    layer = "LOAD_001_Office_OW_DL_1.2_LL_3.4"
    return LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer=layer,
            handle="AA",
            vertices=vertices,
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(value) for value in polygon.bounds),
            hatch_pattern_name="ANSI31",
            hatch_solid_fill=0,
            direction_markers=list(direction_markers or []),
        ),
        load=LoadLayerInfo(
            layer=layer,
            real_name="Office",
            dl=1.2,
            ll=3.4,
            distribution="ONE_WAY",
        ),
        status="OK",
        warnings=[],
    )


def test_one_way_1326_case_short_span_global_angle_is_x_direction():
    global_angle = _compute_short_span_global_angle_from_nodes(
        (1326, 1325, 1327, 1328),
        _example_node_lookup(),
    )

    assert global_angle == pytest.approx(0.0)


def test_one_way_1326_case_mgt_angle_is_90():
    mgt_angle, first_edge_angle, orientation = _to_midas_one_way_relative_angle(
        global_flow_angle_deg=0.0,
        node_ids=(1326, 1325, 1327, 1328),
        node_lookup=_example_node_lookup(),
    )

    assert first_edge_angle == pytest.approx(270.0)
    assert orientation == "CCW"
    assert mgt_angle == pytest.approx(90.0)


def test_one_way_relative_angle_when_first_edge_is_x_direction():
    nodes = {
        1: Node(1, 0.0, 0.0, 0.0),
        2: Node(2, 5.0, 0.0, 0.0),
        3: Node(3, 5.0, 3.0, 0.0),
        4: Node(4, 0.0, 3.0, 0.0),
    }

    mgt_angle, first_edge_angle, orientation = _to_midas_one_way_relative_angle(
        global_flow_angle_deg=0.0,
        node_ids=(1, 2, 3, 4),
        node_lookup=nodes,
    )

    assert first_edge_angle == pytest.approx(0.0)
    assert orientation == "CCW"
    assert mgt_angle == pytest.approx(0.0)


def test_one_way_relative_angle_for_clockwise_polygon():
    nodes = {
        1: Node(1, 0.0, 0.0, 0.0),
        2: Node(2, 5.0, 0.0, 0.0),
        3: Node(3, 5.0, 3.0, 0.0),
        4: Node(4, 0.0, 3.0, 0.0),
    }

    mgt_angle, first_edge_angle, orientation = _to_midas_one_way_relative_angle(
        global_flow_angle_deg=0.0,
        node_ids=(1, 4, 3, 2),
        node_lookup=nodes,
    )

    assert first_edge_angle == pytest.approx(90.0)
    assert orientation == "CW"
    assert mgt_angle == pytest.approx(90.0)


def test_two_way_floorload_does_not_use_one_way_relative_angle_logic():
    assignment = FloorLoadAssignment(
        "Office",
        1.2,
        3.4,
        (1, 2, 3, 4),
        "LOAD_001_Office_DL_1.2_LL_3.4",
        "HATCH",
        20.0,
        "OK",
        tuple(),
        distribution="TWO_WAY",
        effective_idist=2,
        one_way_angle_deg=0.0,
        one_way_mgt_angle_deg=90.0,
    )

    patched = patch_full_mgt_text("*ENDDATA", assignments=[assignment])

    assert "   Office, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4" in patched
    assert "   Office, 1, 90," not in patched


def test_dxf_direction_marker_global_angle_converted_to_mgt_relative_angle():
    marker = DirectionMarker(
        source_type="LINE",
        layer="ONE WAY SLAB DIRECTION",
        handle="D1",
        start=(10.0, 10.0),
        end=(11.0, 10.0),
        source_id="D1",
    )

    assignment = build_assignments_from_regions(
        regions=[_example_region(direction_markers=[marker])],
        story_nodes=_example_nodes(),
        snap_tolerance=0.01,
        include_zero_load=True,
    )[0]

    assert assignment.direction_source == "DXF_DIRECTION_MARKER"
    assert assignment.one_way_angle_deg == pytest.approx(0.0)
    assert assignment.one_way_first_edge_angle_deg == pytest.approx(270.0)
    assert assignment.one_way_polygon_orientation == "CCW"
    assert assignment.one_way_mgt_angle_deg == pytest.approx(90.0)


def test_one_way_mgt_record_uses_relative_angle_for_1326_case():
    assignment = build_assignments_from_regions(
        regions=[_example_region()],
        story_nodes=_example_nodes(),
        snap_tolerance=0.01,
        include_zero_load=True,
    )[0]

    patched = patch_full_mgt_text("*ENDDATA", assignments=[assignment])

    assert assignment.one_way_angle_deg == pytest.approx(0.0)
    assert assignment.one_way_first_edge_angle_deg == pytest.approx(270.0)
    assert assignment.one_way_polygon_orientation == "CCW"
    assert assignment.one_way_mgt_angle_deg == pytest.approx(90.0)
    assert assignment.to_record()["one_way_global_flow_angle"] == "0"
    assert assignment.to_record()["first_edge_angle"] == "270"
    assert assignment.to_record()["polygon_orientation"] == "CCW"
    assert assignment.to_record()["one_way_mgt_angle"] == "90"
    assert "   Office, 1, 90, 0, 0, 0, GZ, NO, , NO, YES, , 1326, 1325, 1327, 1328" in patched
