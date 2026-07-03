from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.floorload_mgt_builder import build_assignments_from_regions
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Node


def test_build_assignments_uses_region_story_nodes_when_available():
    vertices = [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)]
    polygon = Polygon(vertices)
    region = LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer="LOAD_001_Office_DL_1.2_LL_3.4",
            handle="ABCD",
            vertices=vertices,
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(v) for v in polygon.bounds),
            story_name="2F",
            source_id="ABCD:1",
            polygon_index=1,
        ),
        load=LoadLayerInfo("LOAD_001_Office_DL_1.2_LL_3.4", "Office", 1.2, 3.4),
        status="OK",
        warnings=[],
    )
    first_floor_nodes = [
        Node(1, 100.0, 100.0, 0.0),
        Node(2, 105.0, 100.0, 0.0),
        Node(3, 105.0, 105.0, 0.0),
        Node(4, 100.0, 105.0, 0.0),
    ]
    second_floor_nodes = [
        Node(11, 0.0, 0.0, 3.0),
        Node(12, 5.0, 0.0, 3.0),
        Node(13, 5.0, 5.0, 3.0),
        Node(14, 0.0, 5.0, 3.0),
    ]

    assignments = build_assignments_from_regions(
        regions=[region],
        story_nodes=first_floor_nodes,
        story_nodes_by_name={"2F": second_floor_nodes},
        snap_tolerance=0.01,
        include_zero_load=True,
    )

    assert len(assignments) == 1
    assert assignments[0].status == "OK"
    assert assignments[0].node_ids == (11, 12, 13, 14)
    assert assignments[0].story_name == "2F"
    assert assignments[0].source_id == "ABCD:1"
    assert assignments[0].polygon_index == 1


def test_build_assignments_reports_missing_region_story_node_set():
    vertices = [(0.0, 0.0), (5.0, 0.0), (5.0, 5.0), (0.0, 5.0)]
    polygon = Polygon(vertices)
    region = LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer="LOAD_001_Office_DL_1.2_LL_3.4",
            handle="ABCD",
            vertices=vertices,
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(v) for v in polygon.bounds),
            story_name="4F",
        ),
        load=LoadLayerInfo("LOAD_001_Office_DL_1.2_LL_3.4", "Office", 1.2, 3.4),
        status="OK",
        warnings=[],
    )

    assignments = build_assignments_from_regions(
        regions=[region],
        story_nodes=[Node(1, 0.0, 0.0, 0.0), Node(2, 5.0, 0.0, 0.0), Node(3, 5.0, 5.0, 0.0)],
        story_nodes_by_name={"3F": [Node(31, 0.0, 0.0, 6.0)]},
        snap_tolerance=0.01,
        include_zero_load=True,
    )

    assert len(assignments) == 1
    assert assignments[0].status == "STORY_NODE_SET_MISSING"
    assert assignments[0].node_ids == ()
    assert assignments[0].story_name == "4F"
