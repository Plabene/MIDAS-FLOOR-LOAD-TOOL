from app.core.floorload_mgt_builder import (
    FloorLoadAssignment,
    _make_floorload_records,
    merge_adjacent_floorload_assignments,
    patch_full_mgt_text,
)
from app.core.mgt_parser import Node


def _nodes() -> list[Node]:
    return [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 5.0, 0.0, 0.0),
        Node(3, 5.0, 4.0, 0.0),
        Node(4, 0.0, 4.0, 0.0),
        Node(5, 10.0, 0.0, 0.0),
        Node(6, 10.0, 4.0, 0.0),
        Node(7, 20.0, 0.0, 0.0),
        Node(8, 25.0, 0.0, 0.0),
        Node(9, 25.0, 4.0, 0.0),
        Node(10, 20.0, 4.0, 0.0),
    ]


def _assignment(
    *,
    name: str = "House",
    node_ids: tuple[int, ...],
    polygon_vertices: tuple[tuple[float, float], ...],
    source_id: str,
    distribution: str = "TWO_WAY",
    effective_idist: int = 2,
    one_way_angle_deg: float | None = None,
) -> FloorLoadAssignment:
    return FloorLoadAssignment(
        load_type_name=name,
        dl=1.2,
        ll=3.4,
        node_ids=node_ids,
        source_layer=f"LOAD_{source_id}",
        source_type="HATCH",
        area=20.0,
        status="OK",
        warnings=tuple(),
        story_name="B1",
        source_id=source_id,
        distribution=distribution,
        effective_idist=effective_idist,
        allow_polygon_type=True,
        one_way_angle_deg=one_way_angle_deg,
        polygon_vertices=polygon_vertices,
    )


def test_merge_adjacent_two_way_same_load_into_single_assignment():
    left = _assignment(
        node_ids=(1, 2, 3, 4),
        polygon_vertices=((0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)),
        source_id="A",
    )
    right = _assignment(
        node_ids=(2, 5, 6, 3),
        polygon_vertices=((5.0, 0.0), (10.0, 0.0), (10.0, 4.0), (5.0, 4.0)),
        source_id="B",
    )

    merged = merge_adjacent_floorload_assignments([left, right], story_nodes=_nodes(), snap_tolerance=0.01)

    assert len(merged) == 1
    assert merged[0].source_type == "MERGED_HATCH"
    assert merged[0].merged_source_count == 2
    assert set(merged[0].node_ids) == {1, 4, 5, 6}
    assert 2 not in merged[0].node_ids
    assert 3 not in merged[0].node_ids


def test_do_not_merge_adjacent_regions_with_different_load_name():
    left = _assignment(
        name="House",
        node_ids=(1, 2, 3, 4),
        polygon_vertices=((0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)),
        source_id="A",
    )
    right = _assignment(
        name="Office",
        node_ids=(2, 5, 6, 3),
        polygon_vertices=((5.0, 0.0), (10.0, 0.0), (10.0, 4.0), (5.0, 4.0)),
        source_id="B",
    )

    merged = merge_adjacent_floorload_assignments([left, right], story_nodes=_nodes(), snap_tolerance=0.01)

    assert len(merged) == 2
    assert [item.source_type for item in merged] == ["HATCH", "HATCH"]


def test_do_not_merge_two_way_and_one_way():
    two_way = _assignment(
        node_ids=(1, 2, 3, 4),
        polygon_vertices=((0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)),
        source_id="A",
    )
    one_way = _assignment(
        node_ids=(2, 5, 6, 3),
        polygon_vertices=((5.0, 0.0), (10.0, 0.0), (10.0, 4.0), (5.0, 4.0)),
        source_id="B",
        distribution="ONE_WAY",
        effective_idist=1,
        one_way_angle_deg=0.0,
    )

    merged = merge_adjacent_floorload_assignments([two_way, one_way], story_nodes=_nodes(), snap_tolerance=0.01)

    assert len(merged) == 2


def test_do_not_merge_disconnected_same_load_regions():
    first = _assignment(
        node_ids=(1, 2, 3, 4),
        polygon_vertices=((0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)),
        source_id="A",
    )
    disconnected = _assignment(
        node_ids=(7, 8, 9, 10),
        polygon_vertices=((20.0, 0.0), (25.0, 0.0), (25.0, 4.0), (20.0, 4.0)),
        source_id="B",
    )

    merged = merge_adjacent_floorload_assignments([first, disconnected], story_nodes=_nodes(), snap_tolerance=0.01)

    assert len(merged) == 2


def test_merge_one_way_only_when_same_angle_and_node_limit_ok():
    lower = _assignment(
        node_ids=(1, 2, 3),
        polygon_vertices=((0.0, 0.0), (5.0, 0.0), (5.0, 4.0)),
        source_id="A",
        distribution="ONE_WAY",
        effective_idist=1,
        one_way_angle_deg=180.0,
    )
    upper = _assignment(
        node_ids=(1, 3, 4),
        polygon_vertices=((0.0, 0.0), (5.0, 4.0), (0.0, 4.0)),
        source_id="B",
        distribution="ONE_WAY",
        effective_idist=1,
        one_way_angle_deg=0.0,
    )

    merged = merge_adjacent_floorload_assignments([lower, upper], story_nodes=_nodes(), snap_tolerance=0.01)

    assert len(merged) == 1
    assert merged[0].effective_idist == 1
    assert len(merged[0].node_ids) == 4


def test_mgt_records_use_merged_assignments():
    left = _assignment(
        node_ids=(1, 2, 3, 4),
        polygon_vertices=((0.0, 0.0), (5.0, 0.0), (5.0, 4.0), (0.0, 4.0)),
        source_id="A",
    )
    right = _assignment(
        node_ids=(2, 5, 6, 3),
        polygon_vertices=((5.0, 0.0), (10.0, 0.0), (10.0, 4.0), (5.0, 4.0)),
        source_id="B",
    )

    merged = merge_adjacent_floorload_assignments([left, right], story_nodes=_nodes(), snap_tolerance=0.01)
    records = _make_floorload_records(merged)
    patched = patch_full_mgt_text("*ENDDATA", assignments=merged)

    assert len([line for line in records if line.startswith("   House")]) == 1
    assert patched.count("   House, 2,") == 1
    assert "LOAD_" not in patched
