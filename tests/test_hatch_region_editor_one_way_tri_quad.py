from app.core.closed_region_detector import ClosedCell
from app.core.hatch_region_editor import (
    apply_load_to_selection,
    apply_one_way_load_to_selection,
    create_edit_state,
    is_one_way_tri_or_quad,
    one_way_vertex_count,
)


def test_one_way_vertex_count_accepts_cleaned_triangles_and_quads():
    assert one_way_vertex_count([(0, 0), (5, 0), (0, 4), (0, 0)]) == 3
    assert one_way_vertex_count([(0, 0), (5, 0), (10, 0), (10, 4), (0, 4)]) == 4
    assert is_one_way_tri_or_quad([(0, 0), (5, 0), (10, 0), (10, 4), (0, 4)])


def test_one_way_apply_excludes_pentagon_and_preserves_existing_load():
    state = create_edit_state("1F", [_cell("Q", _quad(0, 0, 10, 10)), _cell("P", _pentagon(20, 0))])
    pentagon_key = [key for key, region in state.regions_by_key.items() if region.cell_ids == ("P",)][0]
    state.selected_region_keys = {pentagon_key}
    state.selected_cell_ids = {"P"}
    state = apply_load_to_selection(
        state,
        load_name="Old",
        load_layer="LOAD_Old",
        dl=1.0,
        ll=1.0,
    )
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = {"Q", "P"}

    state, stats = apply_one_way_load_to_selection(
        state,
        load_name="New",
        load_layer="LOAD_New",
        dl=2.0,
        ll=3.0,
    )

    loaded = {region.cell_ids: region for region in state.regions_by_key.values() if region.load_name}
    assert stats["selected"] == 2
    assert stats["applied"] == 1
    assert stats["excluded"] == 1
    assert loaded[("Q",)].distribution == "ONE_WAY"
    assert loaded[("Q",)].one_way_angle is not None
    assert loaded[("P",)].load_name == "Old"


def test_one_way_adjacent_quads_merge_when_union_is_quad():
    state = create_edit_state("1F", [_cell("A", _quad(0, 0, 10, 10)), _cell("B", _quad(10, 0, 20, 10))])
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = {"A", "B"}

    state, stats = apply_one_way_load_to_selection(
        state,
        load_name="Office",
        load_layer="LOAD_Office",
        dl=1.0,
        ll=2.0,
    )

    loaded = [region for region in state.regions_by_key.values() if region.load_name]
    assert len(loaded) == 1
    assert set(loaded[0].cell_ids) == {"A", "B"}
    assert one_way_vertex_count(loaded[0].polygon_xy) == 4
    assert stats["merged"] == 1


def test_one_way_l_shaped_union_keeps_all_individual_regions():
    state = create_edit_state("1F", [_cell("A", _quad(0, 0, 10, 10)), _cell("B", _quad(10, 0, 20, 5))])
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = {"A", "B"}

    state, stats = apply_one_way_load_to_selection(
        state,
        load_name="Office",
        load_layer="LOAD_Office",
        dl=1.0,
        ll=2.0,
    )

    loaded = [region for region in state.regions_by_key.values() if region.load_name]
    assert len(loaded) == 2
    assert {region.cell_ids for region in loaded} == {("A",), ("B",)}
    assert stats["kept_individual"] == 2


def test_one_way_invalid_full_component_still_merges_valid_subset():
    state = create_edit_state(
        "1F",
        [
            _cell("A", _quad(0, 0, 10, 10)),
            _cell("B", _quad(10, 0, 20, 10)),
            _cell("C", _quad(20, 0, 30, 5)),
        ],
    )
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = {"A", "B", "C"}

    state, stats = apply_one_way_load_to_selection(
        state,
        load_name="Office",
        load_layer="LOAD_Office",
        dl=1.0,
        ll=2.0,
        default_angle=0.0,
    )

    loaded = [region for region in state.regions_by_key.values() if region.load_name]
    assert len(loaded) == 2
    assert {region.cell_ids for region in loaded} == {("A", "B"), ("C",)}
    assert stats["merged"] == 1


def test_two_way_existing_merge_still_merges_l_shaped_component():
    state = create_edit_state("1F", [_cell("A", _quad(0, 0, 10, 10)), _cell("B", _quad(10, 0, 20, 5))])
    state.selected_region_keys = set(state.regions_by_key)
    state.selected_cell_ids = {"A", "B"}

    state = apply_load_to_selection(
        state,
        load_name="Office",
        load_layer="LOAD_Office",
        dl=1.0,
        ll=2.0,
    )

    loaded = [region for region in state.regions_by_key.values() if region.load_name]
    assert len(loaded) == 1
    assert set(loaded[0].cell_ids) == {"A", "B"}
    assert one_way_vertex_count(loaded[0].polygon_xy) == 6


def _cell(cell_id: str, points):
    return ClosedCell(
        cell_id=cell_id,
        story_name="1F",
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=tuple(points),
        area=1.0,
        centroid=(0.0, 0.0),
        boundary_element_ids=(),
    )


def _quad(x1, y1, x2, y2):
    return ((float(x1), float(y1)), (float(x2), float(y1)), (float(x2), float(y2)), (float(x1), float(y2)))


def _pentagon(x, y):
    return ((x, y), (x + 4, y), (x + 6, y + 3), (x + 3, y + 6), (x, y + 4))
