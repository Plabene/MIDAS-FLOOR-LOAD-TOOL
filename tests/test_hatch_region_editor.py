from app.core.closed_region_detector import ClosedCell
from app.core.hatch_region_editor import (
    apply_load_to_selection,
    create_edit_state,
    remove_load_from_selection,
    select_regions_by_rect,
    split_region,
)


def test_hatch_region_editor_merges_same_load_and_splits_to_original_cells():
    state = create_edit_state("1F", [_cell("A", 0.0), _cell("B", 10.0)])
    selected = select_regions_by_rect(tuple(state.regions_by_key.values()), (-1.0, -1.0, 21.0, 11.0))
    state.selected_region_keys = selected

    loaded = apply_load_to_selection(
        state,
        load_name="Office",
        load_layer="LOAD_001_Office_DL_1.2_LL_3.4",
        dl=1.2,
        ll=3.4,
    )

    loaded_regions = tuple(region for region in loaded.regions_by_key.values() if region.load_name)
    assert len(loaded_regions) == 1
    assert loaded_regions[0].is_merged is True
    assert loaded_regions[0].cell_ids == ("A", "B")

    split = split_region(loaded, loaded_regions[0].region_key)
    split_regions = tuple(region for region in split.regions_by_key.values() if region.load_name)
    assert sorted(region.cell_ids for region in split_regions) == [("A",), ("B",)]

    removed = remove_load_from_selection(split)
    assert all(region.load_name is None for region in removed.regions_by_key.values())


def test_apply_load_to_subset_keeps_non_selected_cells_with_existing_load():
    state = create_edit_state("1F", [_cell("A", 0.0), _cell("B", 10.0), _cell("C", 20.0)])
    state.selected_region_keys = set(state.regions_by_key)
    loaded = apply_load_to_selection(
        state,
        load_name="Lobby",
        load_layer="LOAD_Lobby",
        dl=2.0,
        ll=4.0,
    )
    loaded.selected_region_keys = set()
    loaded.selected_cell_ids = {"B"}

    updated = apply_load_to_selection(
        loaded,
        load_name="Office",
        load_layer="LOAD_Office",
        dl=1.2,
        ll=3.4,
    )

    load_by_cell = {
        cell_id: region.load_name
        for region in updated.regions_by_key.values()
        for cell_id in region.cell_ids
    }
    assert load_by_cell == {"A": "Lobby", "B": "Office", "C": "Lobby"}


def test_directional_rectangle_selection_distinguishes_window_and_crossing():
    state = create_edit_state("1F", [_cell("A", 0.0), _cell("B", 10.0)])
    regions = tuple(state.regions_by_key.values())

    window = select_regions_by_rect(regions, (0.0, 0.0, 15.0, 10.0), selection_rule="window")
    crossing = select_regions_by_rect(regions, (0.0, 0.0, 15.0, 10.0), selection_rule="crossing")

    cells_by_key = {region.region_key: region.cell_ids for region in regions}
    assert {cells_by_key[key] for key in window} == {("A",)}
    assert {cells_by_key[key] for key in crossing} == {("A",), ("B",)}


def _cell(cell_id: str, x0: float) -> ClosedCell:
    polygon = ((x0, 0.0), (x0 + 10.0, 0.0), (x0 + 10.0, 10.0), (x0, 10.0))
    return ClosedCell(
        cell_id=cell_id,
        story_name="1F",
        story_elevation=0.0,
        node_ids=(),
        polygon_xy=polygon,
        area=100.0,
        centroid=(x0 + 5.0, 5.0),
        boundary_element_ids=(),
    )
