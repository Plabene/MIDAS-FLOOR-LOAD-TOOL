from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.floorload_mgt_builder import _simplify_collinear_node_ids, build_assignments_from_regions
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Node


def test_simplify_collinear_node_ids_removes_intermediate_nodes():
    raw_ids = (1, 2, 3, 4, 5, 6, 7, 8)
    coords = {
        1: (0.0, 0.0),
        2: (1.0, 0.0),
        3: (2.0, 0.0),
        4: (2.0, 1.0),
        5: (2.0, 2.0),
        6: (1.0, 2.0),
        7: (0.0, 2.0),
        8: (0.0, 1.0),
    }
    nodes = {node_id: Node(node_id, x, y, 0.0) for node_id, (x, y) in coords.items()}

    simplified = _simplify_collinear_node_ids(raw_ids, nodes)

    assert simplified == (1, 3, 5, 7)


def test_build_assignments_validates_one_way_after_node_simplification():
    vertices = [
        (0.0, 0.0),
        (1.0, 0.0),
        (2.0, 0.0),
        (2.0, 1.0),
        (2.0, 2.0),
        (1.0, 2.0),
        (0.0, 2.0),
        (0.0, 1.0),
    ]
    polygon = Polygon(vertices)
    layer = "LOAD_001_Office_OW_0_DL_1.2_LL_3.4"
    region = LoadRegion(
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
        ),
        load=LoadLayerInfo(
            layer=layer,
            real_name="Office",
            dl=1.2,
            ll=3.4,
            distribution="ONE_WAY",
            one_way_angle_deg=0.0,
        ),
        status="OK",
        warnings=[],
    )
    nodes = [Node(index + 1, x, y, 0.0) for index, (x, y) in enumerate(vertices)]

    assignments = build_assignments_from_regions(
        regions=[region],
        story_nodes=nodes,
        snap_tolerance=0.01,
        include_zero_load=True,
    )

    assignment = assignments[0]
    assert assignment.status == "OK"
    assert assignment.node_ids == (1, 3, 5, 7)
    assert assignment.snap_node_count_raw == 8
    assert assignment.snap_node_count_simplified == 4
    assert assignment.node_simplified is True
    assert assignment.to_record()["node_simplified"] == "YES"
