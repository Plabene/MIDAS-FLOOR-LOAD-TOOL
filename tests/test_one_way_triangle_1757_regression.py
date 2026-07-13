import math
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from app.core.closed_region_detector import ClosedCell
from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.floorload_mgt_builder import (
    _simplify_collinear_node_ids,
    build_assignments_from_regions,
    run_mgt_build_pipeline,
)
from app.core.hatch_region_editor import (
    EditableHatchRegion,
    apply_one_way_load_to_selection,
    create_edit_state,
    is_one_way_tri_or_quad,
    one_way_vertex_count,
)
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Node, Story


RAW_NODE_IDS = (3900, 1757, 1793, 1796, 1794, 3092, 3091, 1764, 1771, 1773, 1758, 1755)
RAW_POINTS = (
    (8.1075, 4.6480),
    (7.1210, 4.2890),
    (6.4520, 7.3590),
    (11.1480, 7.3590),
    (15.5570, 7.3590),
    (14.5773333333333, 7.00233333333333),
    (13.5976666666667, 6.64566666666667),
    (12.6180, 6.2890),
    (11.4620, 5.8690),
    (10.0340, 5.3490),
    (9.3430, 5.0970),
    (9.0940, 5.0070),
)
MANUAL_NODE_IDS = (1757, 1794, 1793)
PROGRAM_NODE_IDS = (1757, 1793, 1794)
MANUAL_RELATIVE_ANGLE = 90.0
PROGRAM_RELATIVE_ANGLE = 352.296155


def test_real_cell_needs_model_geometry_tolerance_to_be_recognized_as_triangle():
    assert one_way_vertex_count(RAW_POINTS) == 8
    assert not is_one_way_tri_or_quad(RAW_POINTS)
    assert one_way_vertex_count(RAW_POINTS, tolerance=0.001) == 3
    assert is_one_way_tri_or_quad(RAW_POINTS, tolerance=0.001)


def test_hatch_editor_applies_real_one_way_triangle_only_with_shape_tolerance():
    strict_state = _selected_edit_state()
    _strict_result, strict_stats = apply_one_way_load_to_selection(
        strict_state,
        load_name="옥탑지붕층",
        load_layer="LOAD_옥탑지붕층",
        dl=-6.2,
        ll=-1.0,
    )
    assert strict_stats == {
        "selected": 1,
        "applied": 0,
        "excluded": 1,
        "merged": 0,
        "kept_individual": 0,
    }

    state, stats = apply_one_way_load_to_selection(
        _selected_edit_state(),
        load_name="옥탑지붕층",
        load_layer="LOAD_옥탑지붕층",
        dl=-6.2,
        ll=-1.0,
        default_angle=_manual_global_axis(),
        shape_tolerance=0.001,
    )

    assert stats["selected"] == 1
    assert stats["applied"] == 1
    assert stats["excluded"] == 0
    loaded = [region for region in state.regions_by_key.values() if region.load_name]
    assert len(loaded) == 1
    assert loaded[0].distribution == "ONE_WAY"


def test_builder_simplifies_real_one_way_boundary_to_three_nodes_only_for_one_way():
    node_lookup = {node.node_id: node for node in _nodes()}
    assert _simplify_collinear_node_ids(RAW_NODE_IDS, node_lookup, tolerance=0.001) == PROGRAM_NODE_IDS

    one_way = build_assignments_from_regions(
        regions=[_load_region("ONE_WAY")],
        story_nodes=_nodes(),
        snap_tolerance=0.5,
        one_way_shape_tolerance=0.001,
        include_zero_load=True,
    )[0]
    two_way = build_assignments_from_regions(
        regions=[_load_region("TWO_WAY")],
        story_nodes=_nodes(),
        snap_tolerance=0.5,
        one_way_shape_tolerance=0.001,
        include_zero_load=True,
    )[0]

    assert one_way.node_ids == PROGRAM_NODE_IDS
    assert one_way.effective_idist == 1
    assert one_way.status == "OK" or one_way.status.startswith("REVIEW")
    assert two_way.node_ids == _simplify_collinear_node_ids(RAW_NODE_IDS, node_lookup)
    assert len(two_way.node_ids) == 8


def test_pipeline_writes_missing_floorload_record(tmp_path: Path):
    pytest.importorskip("ezdxf")
    source_mgt = tmp_path / "source.mgt"
    output_mgt = tmp_path / "floorload_full.mgt"
    report_dir = tmp_path / "reports"
    source_mgt.write_text("*ENDDATA\n", encoding="cp949")

    result = run_mgt_build_pipeline(
        source_mgt_path=source_mgt,
        output_mgt_path=output_mgt,
        report_dir=report_dir,
        preview_dxf_path=report_dir / "preview.dxf",
        model_name="영원무역.mgb",
        story=Story("7F", 27.3),
        dxf_name="HATCH_VIEW_INTERNAL",
        regions=[],
        internal_regions=[_editable_region()],
        story_nodes=_nodes(),
        story_nodes_by_name={"7F": _nodes()},
        snap_tolerance=0.5,
        one_way_shape_tolerance=0.001,
        include_zero_load=True,
    )

    patched = output_mgt.read_text(encoding="cp949")
    assert result.assignment_count == 1
    assert "*FLOORLOAD" in patched
    floorload_line = next(line for line in patched.splitlines() if line.strip().startswith("옥탑지붕층, 1,"))
    fields = [field.strip() for field in floorload_line.strip().split(",")]
    assert int(fields[1]) == 1
    assert float(fields[2]) == pytest.approx(PROGRAM_RELATIVE_ANGLE, abs=1.0e-5)
    assert fields[10] == "YES"  # 기존 bAL 정책은 이번 수정 범위에서 유지한다.
    assert tuple(int(node_id) for node_id in fields[12:]) == PROGRAM_NODE_IDS


def test_manual_and_program_node_orders_encode_the_same_global_one_way_axis():
    points = {node_id: point for node_id, point in zip(RAW_NODE_IDS, RAW_POINTS)}
    manual_axis = (_edge_angle(points, MANUAL_NODE_IDS) + MANUAL_RELATIVE_ANGLE) % 180.0
    program_axis = (_edge_angle(points, PROGRAM_NODE_IDS) - PROGRAM_RELATIVE_ANGLE) % 180.0

    assert _orientation(points, MANUAL_NODE_IDS) == "CCW"
    assert _orientation(points, PROGRAM_NODE_IDS) == "CW"
    assert _axis_delta(manual_axis, program_axis) < 1.0e-6


def test_normal_quad_stays_allowed_and_true_pentagon_stays_rejected():
    quad = ((0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0))
    pentagon = ((0.0, 0.0), (4.0, 0.0), (5.0, 2.0), (2.5, 4.0), (0.0, 2.0))
    assert is_one_way_tri_or_quad(quad, tolerance=0.001)
    assert not is_one_way_tri_or_quad(pentagon, tolerance=0.001)


def _selected_edit_state():
    cell = ClosedCell(
        cell_id="7F:CELL:3",
        story_name="7F",
        story_elevation=27.3,
        node_ids=RAW_NODE_IDS,
        polygon_xy=RAW_POINTS,
        area=float(Polygon(RAW_POINTS).area),
        centroid=tuple(float(value) for value in Polygon(RAW_POINTS).centroid.coords[0]),
        boundary_element_ids=(),
    )
    state = create_edit_state("7F", [cell])
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = {cell.cell_id}
    return state


def _nodes():
    return [Node(node_id, x, y, 27.3) for node_id, (x, y) in zip(RAW_NODE_IDS, RAW_POINTS)]


def _load_region(distribution: str):
    polygon = Polygon(RAW_POINTS)
    one_way = str(distribution).upper() == "ONE_WAY"
    layer = "LOAD_옥탑지붕층"
    return LoadRegion(
        region=HatchRegion(
            source_type="HATCH_VIEW_INTERNAL",
            layer=layer,
            handle="7F:CELL:3",
            vertices=list(RAW_POINTS),
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(value) for value in polygon.bounds),
            story_name="7F",
            source_id="7F:CELL:3",
        ),
        load=LoadLayerInfo(
            layer=layer,
            real_name="옥탑지붕층",
            dl=-6.2,
            ll=-1.0,
            distribution="ONE_WAY" if one_way else "TWO_WAY",
            one_way_angle_deg=_manual_global_axis() if one_way else None,
        ),
        status="OK",
        warnings=[],
    )


def _editable_region():
    return EditableHatchRegion(
        region_key="INTERNAL|7F|7F:CELL:3|LOADED|옥탑지붕층",
        story_name="7F",
        cell_ids=("7F:CELL:3",),
        polygon_xy=RAW_POINTS,
        load_name="옥탑지붕층",
        load_layer="LOAD_옥탑지붕층",
        dl=-6.2,
        ll=-1.0,
        distribution="ONE_WAY",
        one_way_angle=_manual_global_axis(),
    )


def _manual_global_axis():
    points = {node_id: point for node_id, point in zip(RAW_NODE_IDS, RAW_POINTS)}
    return (_edge_angle(points, MANUAL_NODE_IDS) + MANUAL_RELATIVE_ANGLE) % 180.0


def _edge_angle(points, node_ids):
    start = points[node_ids[0]]
    end = points[node_ids[1]]
    return math.degrees(math.atan2(end[1] - start[1], end[0] - start[0])) % 360.0


def _orientation(points, node_ids):
    coords = [points[node_id] for node_id in node_ids]
    signed_twice_area = sum(
        coords[index][0] * coords[(index + 1) % len(coords)][1]
        - coords[(index + 1) % len(coords)][0] * coords[index][1]
        for index in range(len(coords))
    )
    return "CCW" if signed_twice_area > 0.0 else "CW"


def _axis_delta(left, right):
    diff = abs((float(left) % 180.0) - (float(right) % 180.0))
    return min(diff, 180.0 - diff)
