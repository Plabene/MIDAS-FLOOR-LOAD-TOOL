from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.floorload_mgt_builder import build_assignments_from_regions
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Node


def test_one_way_more_than_four_nodes_is_error():
    vertices = [(0.0, 0.0), (4.0, 0.0), (5.0, 2.0), (2.0, 4.0), (0.0, 2.0)]
    polygon = Polygon(vertices)
    region = LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer="LOAD_001_Office_OW_DL_1.2_LL_3.4",
            handle="AA",
            vertices=vertices,
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(v) for v in polygon.bounds),
            hatch_pattern_name="ANSI31",
            hatch_solid_fill=0,
        ),
        load=LoadLayerInfo("LOAD_001_Office_OW_DL_1.2_LL_3.4", "Office", 1.2, 3.4, distribution="ONE_WAY"),
        status="OK",
        warnings=[],
    )
    nodes = [Node(index + 1, x, y, 0.0) for index, (x, y) in enumerate(vertices)]

    assignments = build_assignments_from_regions(regions=[region], story_nodes=nodes, snap_tolerance=0.01, include_zero_load=True)

    assert assignments[0].status == "ERROR_ONE_WAY_REQUIRES_TRI_OR_QUAD"
    assert "3각형 또는 4각형" in " | ".join(assignments[0].warnings)
