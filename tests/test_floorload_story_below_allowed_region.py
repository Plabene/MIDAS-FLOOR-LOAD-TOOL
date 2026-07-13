from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.floorload_mgt_builder import (
    BELOW_ALLOWED_REGION_MISMATCH,
    BELOW_ALLOWED_REGION_MISSING,
    build_assignments_from_regions,
)
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Node, Story
from app.core.model_floorload_diagnostics import (
    BELOW_ALLOWED_REGION_MISSING as DIAGNOSTIC_BELOW_ALLOWED_REGION_MISSING,
    PLANNED_REGION_OUTSIDE_STORY_BELOW_VIEW,
    analyze_floorload_model,
)


def test_build_assignments_excludes_region_outside_story_below_allowed_polygon():
    allowed = Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    inside = _load_region("inside", [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    outside = _load_region("outside", [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)])

    assignments = build_assignments_from_regions(
        regions=[inside, outside],
        story_nodes=[
            Node(1, 0.0, 0.0, 3.0),
            Node(2, 10.0, 0.0, 3.0),
            Node(3, 10.0, 10.0, 3.0),
            Node(4, 0.0, 10.0, 3.0),
        ],
        story_nodes_by_name={
            "2F": [
                Node(1, 0.0, 0.0, 3.0),
                Node(2, 10.0, 0.0, 3.0),
                Node(3, 10.0, 10.0, 3.0),
                Node(4, 0.0, 10.0, 3.0),
            ]
        },
        snap_tolerance=0.01,
        include_zero_load=True,
        allowed_story_polygons_by_name={"2F": [allowed]},
    )

    by_id = {item.source_id: item for item in assignments}
    assert by_id["inside"].status == "OK"
    assert by_id["outside"].status == BELOW_ALLOWED_REGION_MISMATCH
    assert by_id["outside"].node_ids == ()
    assert "표시되지 않는 영역에는 FLOORLOAD를 입력하지 않습니다." in " ".join(by_id["outside"].warnings)


def test_build_assignments_allows_story_below_region_after_snap_tolerant_check():
    allowed = Polygon([(6.585, 0.2), (13.2, 0.2), (13.2, 8.7), (6.585, 8.7)])
    raw_region = _load_region(
        "retail",
        [(6.5, 0.0), (13.0, 0.0), (13.0, 8.5), (6.5, 8.5)],
        story_name="3F",
        load_name="근린생활시설(1F)",
        dl=4.8,
        ll=5.0,
    )
    nodes = [
        Node(1, 6.585, 0.2, 6.0),
        Node(2, 13.2, 0.2, 6.0),
        Node(3, 13.2, 8.7, 6.0),
        Node(4, 6.585, 8.7, 6.0),
    ]

    assignments = build_assignments_from_regions(
        regions=[raw_region],
        story_nodes=nodes,
        story_nodes_by_name={"3F": nodes},
        snap_tolerance=0.5,
        include_zero_load=True,
        allowed_story_polygons_by_name={"3F": [allowed]},
    )

    assignment = assignments[0]
    assert assignment.status == "OK"
    assert assignment.node_ids == (1, 2, 3, 4)
    assert assignment.snap_max_error < 0.5
    assert assignment.allowed_region_check_data["allowed_check_mode"] == "SNAP_TOLERANT"


def test_one_way_distribution_is_preserved_when_story_below_check_skips_region():
    allowed = Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    outside = _load_region(
        "stairs",
        [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)],
        distribution="ONE_WAY",
        one_way_angle=90.0,
    )

    assignments = build_assignments_from_regions(
        regions=[outside],
        story_nodes=[
            Node(1, 20.0, 0.0, 3.0),
            Node(2, 30.0, 0.0, 3.0),
            Node(3, 30.0, 10.0, 3.0),
            Node(4, 20.0, 10.0, 3.0),
        ],
        story_nodes_by_name={
            "2F": [
                Node(1, 20.0, 0.0, 3.0),
                Node(2, 30.0, 0.0, 3.0),
                Node(3, 30.0, 10.0, 3.0),
                Node(4, 20.0, 10.0, 3.0),
            ]
        },
        snap_tolerance=0.01,
        include_zero_load=True,
        allowed_story_polygons_by_name={"2F": [allowed]},
    )

    assignment = assignments[0]
    assert assignment.status == BELOW_ALLOWED_REGION_MISMATCH
    assert assignment.distribution == "ONE_WAY"
    assert assignment.effective_idist == 1
    assert assignment.one_way_angle_deg == 90.0
    assert assignment.node_ids == ()


def test_diagnostics_reports_region_outside_story_below_allowed_polygon():
    allowed = Polygon([(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])
    outside = _load_region("outside", [(20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)])

    result = analyze_floorload_model(
        nodes=[
            Node(1, 20.0, 0.0, 3.0),
            Node(2, 30.0, 0.0, 3.0),
            Node(3, 30.0, 10.0, 3.0),
            Node(4, 20.0, 10.0, 3.0),
        ],
        elements=[],
        stories=[Story("2F", 3.0)],
        planned_load_regions=[outside],
        allowed_story_polygons_by_name={"2F": [allowed]},
        snap_tolerance=0.01,
    )

    assert any(issue.issue_type == PLANNED_REGION_OUTSIDE_STORY_BELOW_VIEW for issue in result.issues)


def test_build_assignments_blocks_when_story_below_allowed_polygon_is_explicitly_empty():
    region = _load_region("missing", [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])

    assignments = build_assignments_from_regions(
        regions=[region],
        story_nodes=[
            Node(1, 0.0, 0.0, 3.0),
            Node(2, 10.0, 0.0, 3.0),
            Node(3, 10.0, 10.0, 3.0),
            Node(4, 0.0, 10.0, 3.0),
        ],
        story_nodes_by_name={
            "2F": [
                Node(1, 0.0, 0.0, 3.0),
                Node(2, 10.0, 0.0, 3.0),
                Node(3, 10.0, 10.0, 3.0),
                Node(4, 0.0, 10.0, 3.0),
            ]
        },
        snap_tolerance=0.01,
        include_zero_load=True,
        allowed_story_polygons_by_name={"2F": []},
    )

    assert assignments[0].status == BELOW_ALLOWED_REGION_MISSING
    assert assignments[0].node_ids == ()
    assert "허용영역을 확인하지 못해" in " ".join(assignments[0].warnings)


def test_diagnostics_reports_error_when_story_below_allowed_polygon_is_explicitly_empty():
    region = _load_region("missing", [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)])

    result = analyze_floorload_model(
        nodes=[
            Node(1, 0.0, 0.0, 3.0),
            Node(2, 10.0, 0.0, 3.0),
            Node(3, 10.0, 10.0, 3.0),
            Node(4, 0.0, 10.0, 3.0),
        ],
        elements=[],
        stories=[Story("2F", 3.0)],
        planned_load_regions=[region],
        allowed_story_polygons_by_name={"2F": []},
        snap_tolerance=0.01,
    )

    assert any(
        issue.severity == "ERROR" and issue.issue_type == DIAGNOSTIC_BELOW_ALLOWED_REGION_MISSING
        for issue in result.issues
    )


def _load_region(
    source_id: str,
    vertices: list[tuple[float, float]],
    *,
    story_name: str = "2F",
    load_name: str = "Office",
    dl: float = 1.0,
    ll: float = 1.0,
    distribution: str = "TWO_WAY",
    one_way_angle: float | None = None,
) -> LoadRegion:
    polygon = Polygon(vertices)
    hatch = HatchRegion(
        source_type="HATCH",
        layer=f"LOAD_001_{load_name}_DL_{dl}_LL_{ll}",
        handle=source_id,
        vertices=vertices,
        polygon=polygon,
        area=float(polygon.area),
        bbox=tuple(float(value) for value in polygon.bounds),
        story_name=story_name,
        source_id=source_id,
    )
    load = LoadLayerInfo(
        layer=hatch.layer,
        real_name=load_name,
        dl=dl,
        ll=ll,
        source="test",
        distribution=distribution,
        one_way_angle_deg=one_way_angle,
    )
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])
