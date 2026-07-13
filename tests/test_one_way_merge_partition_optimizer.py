from shapely.geometry import Polygon

from app.core.closed_region_detector import ClosedCell
from app.core.hatch_region_editor import (
    EditableHatchRegion,
    apply_one_way_load_to_selection,
    create_edit_state,
    merge_compatible_regions,
    one_way_vertex_count,
)


def test_two_adjacent_quads_merge_to_one_quad():
    loaded = _apply((_cell("A", _quad(0, 0, 1, 1)), _cell("B", _quad(1, 0, 2, 1))))

    assert len(loaded) == 1
    assert loaded[0].cell_ids == ("A", "B")
    assert one_way_vertex_count(loaded[0].polygon_xy) == 4


def test_invalid_full_union_still_uses_valid_partial_merge():
    loaded = _apply(
        (
            _cell("A", _quad(0, 0, 1, 1)),
            _cell("B", _quad(1, 0, 2, 1)),
            _cell("C", _quad(2, 0, 3, 0.5)),
        )
    )

    assert len(loaded) == 2
    assert {region.cell_ids for region in loaded} == {("A", "B"), ("C",)}


def test_equal_two_region_plans_use_deterministic_cell_id_tie_break():
    cells = (
        _cell("A", _quad(0, 0, 1, 1)),
        _cell("B", _quad(1, 0, 2, 1)),
        _cell("C", _quad(1, 1, 2, 2)),
    )

    plans = [tuple(region.cell_ids for region in _apply(cells)) for _index in range(5)]

    assert plans == [(("A", "B"), ("C",))] * 5


def test_two_regions_whose_union_has_more_than_four_vertices_stay_individual():
    loaded = _apply((_cell("A", _quad(0, 0, 1, 1)), _cell("B", _quad(1, 0, 2, 0.5))))

    assert {region.cell_ids for region in loaded} == {("A",), ("B",)}


def test_separated_corner_touching_and_overlapping_regions_do_not_merge():
    cases = (
        (_quad(0, 0, 1, 1), _quad(2, 0, 3, 1)),
        (_quad(0, 0, 1, 1), _quad(1, 1, 2, 2)),
        (_quad(0, 0, 1.2, 1), _quad(1, 0, 2, 1)),
    )

    for first, second in cases:
        loaded = _apply((_cell("A", first), _cell("B", second)))
        assert {region.cell_ids for region in loaded} == {("A",), ("B",)}


def test_ring_component_never_creates_a_polygon_with_a_hole():
    cells = tuple(
        _cell(f"C{index}", _quad(x, y, x + 1, y + 1))
        for index, (x, y) in enumerate(
            ((0, 0), (1, 0), (2, 0), (0, 1), (2, 1), (0, 2), (1, 2), (2, 2))
        )
    )

    loaded = _apply(cells)

    assert len(loaded) > 1
    assert all(len(Polygon(region.polygon_xy).interiors) == 0 for region in loaded)
    assert all(one_way_vertex_count(region.polygon_xy) in {3, 4} for region in loaded)


def test_direction_compatibility_uses_half_degree_axis_tolerance():
    inside = merge_compatible_regions((_region("A", 0, 1, 10.0), _region("B", 1, 2, 10.4)))
    outside = merge_compatible_regions((_region("A", 0, 1, 10.0), _region("B", 1, 2, 10.6)))
    missing = merge_compatible_regions((_region("A", 0, 1, None), _region("B", 1, 2, 10.0)))

    assert len(inside) == 1
    assert next(iter(inside.values())).one_way_angle == 10.0
    assert len(outside) == 2
    assert len(missing) == 2


def test_explicit_user_direction_is_preserved_after_merge():
    loaded = _apply(
        (_cell("A", _quad(0, 0, 1, 1)), _cell("B", _quad(1, 0, 2, 1))),
        angle=27.25,
    )

    assert len(loaded) == 1
    assert loaded[0].one_way_angle == 27.25


def test_large_component_fallback_can_merge_a_seventeen_cell_rectangle():
    cells = tuple(_cell(f"C{index:02d}", _quad(index, 0, index + 1, 1)) for index in range(17))

    loaded = _apply(cells)

    assert len(loaded) == 1
    assert len(loaded[0].cell_ids) == 17
    assert one_way_vertex_count(loaded[0].polygon_xy) == 4


def _apply(cells, *, angle: float | None = 0.0):
    state = create_edit_state("1F", cells)
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = set(state.cells_by_id)
    state, _stats = apply_one_way_load_to_selection(
        state,
        load_name="Office",
        load_layer="LOAD_Office",
        dl=1.0,
        ll=2.0,
        default_angle=angle,
    )
    return sorted(
        (region for region in state.regions_by_key.values() if region.load_name),
        key=lambda region: region.cell_ids,
    )


def _cell(cell_id: str, points) -> ClosedCell:
    polygon = Polygon(points)
    return ClosedCell(
        cell_id=cell_id,
        story_name="1F",
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=tuple(points),
        area=float(polygon.area),
        centroid=(float(polygon.centroid.x), float(polygon.centroid.y)),
        boundary_element_ids=(),
    )


def _region(cell_id: str, x0: float, x1: float, angle: float | None) -> EditableHatchRegion:
    return EditableHatchRegion(
        region_key=f"R|{cell_id}",
        story_name="1F",
        cell_ids=(cell_id,),
        polygon_xy=_quad(x0, 0, x1, 1),
        load_name="Office",
        load_layer="LOAD_Office",
        dl=1.0,
        ll=2.0,
        distribution="ONE_WAY",
        one_way_angle=angle,
    )


def _quad(x1, y1, x2, y2):
    return (
        (float(x1), float(y1)),
        (float(x2), float(y1)),
        (float(x2), float(y2)),
        (float(x1), float(y2)),
    )
