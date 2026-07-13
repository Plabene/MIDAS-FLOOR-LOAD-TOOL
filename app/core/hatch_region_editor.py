from __future__ import annotations

from dataclasses import dataclass, replace
import heapq
from math import ceil
from typing import Iterable, Sequence

from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from .closed_region_detector import ClosedCell
from .load_input_policy import DISTRIBUTION_ONE_WAY, infer_short_span_angle


ONE_WAY_MERGE_ANGLE_TOLERANCE_DEG = 5.0
ONE_WAY_DIRECTION_COMPATIBILITY_TOLERANCE_DEG = 0.5
ONE_WAY_EXACT_PARTITION_MAX_CELLS = 10
ONE_WAY_MAX_CANDIDATES = 5000


@dataclass(frozen=True)
class EditableHatchRegion:
    region_key: str
    story_name: str
    cell_ids: tuple[str, ...]
    polygon_xy: tuple[tuple[float, float], ...]
    load_name: str | None
    load_layer: str | None
    dl: float | None
    ll: float | None
    distribution: str
    one_way_angle: float | None = None
    source: str = "INTERNAL"
    is_merged: bool = False
    warning_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class OneWayMergeCandidate:
    region_keys: tuple[str, ...]
    cell_ids: tuple[str, ...]
    polygon_xy: tuple[tuple[float, float], ...]
    area: float
    vertex_count: int
    one_way_angle: float | None


@dataclass
class HatchEditState:
    story_name: str
    cells_by_id: dict[str, ClosedCell]
    regions_by_key: dict[str, EditableHatchRegion]
    selected_region_keys: set[str]
    selected_cell_ids: set[str]


def create_edit_state(story_name: str, cells: Iterable[ClosedCell]) -> HatchEditState:
    cells_by_id = {cell.cell_id: cell for cell in cells if str(cell.story_name) == str(story_name)}
    regions = {}
    for cell in cells_by_id.values():
        region = _region_from_cell(cell)
        regions[region.region_key] = region
    return HatchEditState(
        story_name=str(story_name),
        cells_by_id=dict(cells_by_id),
        regions_by_key=regions,
        selected_region_keys=set(),
        selected_cell_ids=set(),
    )


def apply_load_to_selection(
    state: HatchEditState,
    *,
    load_name: str,
    load_layer: str | None,
    dl: float,
    ll: float,
    distribution: str = "TWO_WAY",
    one_way_angle: float | None = None,
    shape_tolerance: float = 1.0e-8,
) -> HatchEditState:
    return apply_load_to_selection_with_stats(
        state,
        load_name=load_name,
        load_layer=load_layer,
        dl=dl,
        ll=ll,
        distribution=distribution,
        one_way_angle=one_way_angle,
        shape_tolerance=shape_tolerance,
    )[0]


def apply_load_to_selection_with_stats(
    state: HatchEditState,
    *,
    load_name: str,
    load_layer: str | None,
    dl: float,
    ll: float,
    distribution: str = "TWO_WAY",
    one_way_angle: float | None = None,
    shape_tolerance: float = 1.0e-8,
) -> tuple[HatchEditState, dict[str, int]]:
    selected_cells = _selected_cell_ids(state)
    stats = {"selected": len(selected_cells), "applied": 0, "excluded": 0, "merged": 0, "kept_individual": 0}
    if not selected_cells:
        return state, stats
    normalized_distribution = _normal_distribution(distribution)
    one_way = normalized_distribution == DISTRIBUTION_ONE_WAY
    shape_tol = max(abs(float(shape_tolerance)), 1.0e-12)
    target_cells = set(selected_cells)
    if one_way:
        target_cells = {
            cell_id
            for cell_id in selected_cells
            if (cell := state.cells_by_id.get(cell_id)) is not None
            and is_one_way_tri_or_quad(cell.polygon_xy, tolerance=shape_tol)
        }
        stats["excluded"] = len(selected_cells) - len(target_cells)
        if not target_cells:
            return state, stats
    updated = _without_cells(state, target_cells)
    for cell_id in target_cells:
        cell = state.cells_by_id[cell_id]
        angle = _normal_one_way_angle(one_way_angle)
        if one_way and angle is None:
            angle = _short_span_angle(cell.polygon_xy)
        region = _region_from_cell(
            cell,
            load_name=load_name,
            load_layer=load_layer,
            dl=dl,
            ll=ll,
            distribution=normalized_distribution,
            one_way_angle=angle,
        )
        updated[region.region_key] = region
    before_loaded = sum(1 for region in updated.values() if region.load_name)
    merged = merge_compatible_regions(updated.values(), shape_tolerance=shape_tol)
    after_loaded = sum(1 for region in merged.values() if region.load_name)
    stats["applied"] = len(target_cells)
    stats["merged"] = max(0, before_loaded - after_loaded)
    stats["kept_individual"] = sum(
        1
        for region in merged.values()
        if set(region.cell_ids).intersection(target_cells) and region.load_name and len(region.cell_ids) == 1
    )
    selected = {
        key
        for key, region in merged.items()
        if set(region.cell_ids).intersection(target_cells)
    }
    return HatchEditState(state.story_name, dict(state.cells_by_id), merged, selected, set(selected_cells)), stats


def apply_one_way_load_to_selection(
    state: HatchEditState,
    *,
    load_name: str,
    load_layer: str | None,
    dl: float,
    ll: float,
    default_angle: float | None = None,
    shape_tolerance: float = 1.0e-8,
) -> tuple[HatchEditState, dict[str, int]]:
    return apply_load_to_selection_with_stats(
        state,
        load_name=load_name,
        load_layer=load_layer,
        dl=dl,
        ll=ll,
        distribution=DISTRIBUTION_ONE_WAY,
        one_way_angle=default_angle,
        shape_tolerance=shape_tolerance,
    )


def remove_load_from_selection(state: HatchEditState) -> HatchEditState:
    selected_cells = _selected_cell_ids(state)
    if not selected_cells:
        return state
    updated = _without_cells(state, selected_cells)
    for cell_id in selected_cells:
        cell = state.cells_by_id[cell_id]
        region = _region_from_cell(cell)
        updated[region.region_key] = region
    selected = {key for key, region in updated.items() if set(region.cell_ids).intersection(selected_cells)}
    return HatchEditState(state.story_name, dict(state.cells_by_id), updated, selected, set(selected_cells))


def split_region(state: HatchEditState, region_key: str) -> HatchEditState:
    region = state.regions_by_key.get(region_key)
    if region is None or len(region.cell_ids) < 2:
        return state
    updated = dict(state.regions_by_key)
    updated.pop(region_key, None)
    selected: set[str] = set()
    for cell_id in region.cell_ids:
        cell = state.cells_by_id.get(cell_id)
        if cell is None:
            continue
        child = _region_from_cell(
            cell,
            load_name=region.load_name,
            load_layer=region.load_layer,
            dl=region.dl if region.dl is not None else 0.0,
            ll=region.ll if region.ll is not None else 0.0,
            distribution=region.distribution,
            one_way_angle=region.one_way_angle,
        )
        updated[child.region_key] = child
        selected.add(child.region_key)
    return HatchEditState(state.story_name, dict(state.cells_by_id), updated, selected, set(region.cell_ids))


def select_regions_by_rect(
    regions: Sequence[EditableHatchRegion],
    rect_xy: tuple[float, float, float, float],
    *,
    selection_rule: str = "crossing",
    mode: str = "replace",
    current: Iterable[str] = (),
) -> set[str]:
    return select_polygon_keys_by_rect(
        ((region.region_key, _polygon(region)) for region in regions),
        rect_xy,
        selection_rule=selection_rule,
        mode=mode,
        current=current,
    )


def select_polygon_keys_by_rect(
    keyed_polygons: Iterable[tuple[str, object]],
    rect_xy: tuple[float, float, float, float],
    *,
    selection_rule: str = "crossing",
    mode: str = "replace",
    current: Iterable[str] = (),
) -> set[str]:
    rule = str(selection_rule or "crossing").strip().lower()
    if rule not in {"window", "crossing"}:
        raise ValueError(f"Unsupported selection_rule: {selection_rule!r}")
    min_x, min_y, max_x, max_y = rect_xy
    rect = box(min(min_x, max_x), min(min_y, max_y), max(min_x, max_x), max(min_y, max_y))
    rect_bounds = rect.bounds
    hits: set[str] = set()
    for key, value in keyed_polygons:
        polygon = _selection_polygon(value)
        if polygon is None or not _bounds_intersect(rect_bounds, polygon.bounds):
            continue
        try:
            matched = rect.covers(polygon) if rule == "window" else rect.intersects(polygon)
        except Exception:
            matched = False
        if matched:
            hits.add(str(key))
    selected = set(current)
    if mode == "add":
        selected.update(hits)
        return selected
    if mode == "remove":
        selected.difference_update(hits)
        return selected
    if mode == "toggle":
        for key in hits:
            if key in selected:
                selected.remove(key)
            else:
                selected.add(key)
        return selected
    return hits


def select_region_at_point(
    regions: Sequence[EditableHatchRegion],
    point_xy: tuple[float, float],
    *,
    mode: str = "replace",
    current: Iterable[str] = (),
) -> set[str]:
    from shapely.geometry import Point

    point = Point(float(point_xy[0]), float(point_xy[1]))
    hits = [
        region
        for region in regions
        if (polygon := _polygon(region)) is not None and (polygon.contains(point) or polygon.touches(point))
    ]
    if not hits:
        return set(current) if mode != "replace" else set()
    smallest = min(hits, key=lambda region: abs(float(_polygon(region).area)))  # type: ignore[union-attr]
    return select_regions_by_keys([smallest.region_key], mode=mode, current=current)


def select_regions_by_keys(keys: Iterable[str], *, mode: str = "replace", current: Iterable[str] = ()) -> set[str]:
    hits = set(keys)
    selected = set(current)
    if mode == "add":
        selected.update(hits)
        return selected
    if mode == "remove":
        selected.difference_update(hits)
        return selected
    if mode == "toggle":
        for key in hits:
            if key in selected:
                selected.remove(key)
            else:
                selected.add(key)
        return selected
    return hits


def merge_compatible_regions(
    regions: Iterable[EditableHatchRegion],
    *,
    shape_tolerance: float = 1.0e-8,
) -> dict[str, EditableHatchRegion]:
    result: dict[str, EditableHatchRegion] = {}
    grouped: dict[tuple, list[EditableHatchRegion]] = {}
    for region in regions:
        if not region.load_name:
            result[region.region_key] = region
            continue
        grouped.setdefault(_base_load_key(region), []).append(region)
    for group in grouped.values():
        remaining = sorted(group, key=_region_sort_key)
        one_way = _normal_distribution(remaining[0].distribution) == DISTRIBUTION_ONE_WAY
        while remaining:
            seed = remaining.pop(0)
            component = [seed]
            changed = True
            while changed:
                changed = False
                for other in list(remaining):
                    if (
                        any(
                            _one_way_directions_compatible(region, other)
                            and _one_way_regions_share_mergeable_edge(
                                region,
                                other,
                                shape_tolerance=shape_tolerance,
                            )
                            for region in component
                        )
                        if one_way
                        else _regions_touch_any(component, other)
                    ):
                        component.append(other)
                        remaining.remove(other)
                        changed = True
            merged_component = (
                _merge_one_way_component_min_regions(component, shape_tolerance=shape_tolerance)
                if one_way
                else _merge_component_to_regions(component, shape_tolerance=shape_tolerance)
            )
            for merged in merged_component:
                result[merged.region_key] = merged
    return result


def loaded_editable_regions(states: Iterable[HatchEditState]) -> tuple[EditableHatchRegion, ...]:
    return tuple(
        region
        for state in states
        for region in state.regions_by_key.values()
        if region.load_name
    )


def _merge_one_way_component_min_regions(
    component: Sequence[EditableHatchRegion],
    *,
    shape_tolerance: float,
    direction_tolerance_deg: float = ONE_WAY_DIRECTION_COMPATIBILITY_TOLERANCE_DEG,
) -> list[EditableHatchRegion]:
    ordered = tuple(sorted(component, key=_region_sort_key))
    if len(ordered) <= 1:
        return list(ordered)
    full_union = _build_valid_one_way_merge_candidate(
        ordered,
        shape_tolerance=shape_tolerance,
        direction_tolerance_deg=direction_tolerance_deg,
        require_connected=False,
        check_pair_overlaps=False,
    )
    if full_union is not None:
        return [_one_way_region_from_candidate(ordered, full_union)]
    cell_count = len({cell_id for region in ordered for cell_id in region.cell_ids})
    candidates: list[OneWayMergeCandidate]
    cap_exceeded = True
    if cell_count <= ONE_WAY_EXACT_PARTITION_MAX_CELLS:
        candidates, cap_exceeded = _enumerate_one_way_candidates(
            ordered,
            shape_tolerance=shape_tolerance,
            direction_tolerance_deg=direction_tolerance_deg,
            max_candidates=ONE_WAY_MAX_CANDIDATES,
        )
        if not cap_exceeded and _one_way_candidates_cover_sources(ordered, candidates):
            plan = _minimum_one_way_partition(ordered, candidates)
            if plan:
                return [_one_way_region_from_candidate(ordered, candidate) for candidate in plan]
    plan = _agglomerative_one_way_partition(
        ordered,
        shape_tolerance=shape_tolerance,
        direction_tolerance_deg=direction_tolerance_deg,
    )
    if not plan:
        return list(ordered)
    return [_one_way_region_from_candidate(ordered, candidate) for candidate in plan]


def _agglomerative_one_way_partition(
    component: Sequence[EditableHatchRegion],
    *,
    shape_tolerance: float,
    direction_tolerance_deg: float = ONE_WAY_DIRECTION_COMPATIBILITY_TOLERANCE_DEG,
) -> tuple[OneWayMergeCandidate, ...]:
    """Deterministically merge only adjacent groups whose union stays a triangle/quad."""
    ordered = tuple(sorted(component, key=_region_sort_key))
    if not ordered:
        return ()
    original_adjacency = _one_way_adjacency_masks(
        ordered,
        shape_tolerance=shape_tolerance,
        direction_tolerance_deg=direction_tolerance_deg,
    )
    groups: dict[int, tuple[int, ...]] = {index: (index,) for index in range(len(ordered))}
    candidate_by_group: dict[int, OneWayMergeCandidate] = {}
    for index, region in enumerate(ordered):
        candidate = _build_valid_one_way_merge_candidate(
            (region,),
            shape_tolerance=shape_tolerance,
            direction_tolerance_deg=direction_tolerance_deg,
        )
        if candidate is None:
            return ()
        candidate_by_group[index] = candidate

    heap: list[tuple[tuple, int, int, tuple[int, ...], tuple[int, ...]]] = []
    queued: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()
    rejected: set[tuple[tuple[int, ...], tuple[int, ...]]] = set()

    def canonical_pair(first: tuple[int, ...], second: tuple[int, ...]):
        return (first, second) if first < second else (second, first)

    def groups_share_original_edge(first: tuple[int, ...], second: tuple[int, ...]) -> bool:
        second_mask = sum(1 << index for index in second)
        return any(original_adjacency[index] & second_mask for index in first)

    def queue_pair(first_id: int, second_id: int) -> None:
        if first_id == second_id or first_id not in groups or second_id not in groups:
            return
        first = groups[first_id]
        second = groups[second_id]
        pair = canonical_pair(first, second)
        if pair in queued or pair in rejected or not groups_share_original_edge(*pair):
            return
        queued.add(pair)
        combined = tuple(sorted((*pair[0], *pair[1])))
        score = (-len(combined), tuple(ordered[index].region_key for index in combined), pair)
        heapq.heappush(heap, (score, first_id, second_id, first, second))

    for first_index, mask in enumerate(original_adjacency):
        for second_index in range(first_index + 1, len(ordered)):
            if mask & (1 << second_index):
                queue_pair(first_index, second_index)

    next_group_id = len(ordered)
    while heap:
        _score, first_id, second_id, queued_first, queued_second = heapq.heappop(heap)
        pair = canonical_pair(queued_first, queued_second)
        queued.discard(pair)
        if first_id not in groups or second_id not in groups:
            continue
        if groups[first_id] != queued_first or groups[second_id] != queued_second:
            continue
        combined_indices = tuple(sorted((*queued_first, *queued_second)))
        combined_regions = tuple(ordered[index] for index in combined_indices)
        candidate = _build_valid_one_way_merge_candidate(
            combined_regions,
            shape_tolerance=shape_tolerance,
            direction_tolerance_deg=direction_tolerance_deg,
            require_connected=False,
            check_pair_overlaps=False,
        )
        if candidate is None:
            rejected.add(pair)
            continue
        del groups[first_id]
        del groups[second_id]
        candidate_by_group.pop(first_id, None)
        candidate_by_group.pop(second_id, None)
        merged_id = next_group_id
        next_group_id += 1
        groups[merged_id] = combined_indices
        candidate_by_group[merged_id] = candidate
        for other_id in sorted(groups):
            if other_id != merged_id:
                queue_pair(merged_id, other_id)

    if set(candidate_by_group) != set(groups):
        return ()
    return tuple(sorted(candidate_by_group.values(), key=_one_way_candidate_sort_key))


def _build_valid_one_way_merge_candidate(
    regions: Sequence[EditableHatchRegion],
    *,
    shape_tolerance: float,
    direction_tolerance_deg: float,
    require_connected: bool = True,
    check_pair_overlaps: bool = True,
) -> OneWayMergeCandidate | None:
    ordered = tuple(sorted(regions, key=_region_sort_key))
    if not ordered:
        return None
    if any(_normal_distribution(region.distribution) != DISTRIBUTION_ONE_WAY for region in ordered):
        return None
    if len({_base_load_key(region) for region in ordered}) != 1:
        return None
    for index, region in enumerate(ordered):
        for other in ordered[index + 1 :]:
            if not _one_way_directions_compatible(region, other, tolerance_deg=direction_tolerance_deg):
                return None
    polygons = [_strict_polygon(region) for region in ordered]
    if any(polygon is None for polygon in polygons):
        return None
    valid_polygons = [polygon for polygon in polygons if polygon is not None]
    shape_tol = max(abs(float(shape_tolerance)), 1.0e-12)
    area_tolerance = max(shape_tol * shape_tol * 10.0, 1.0e-12)
    if check_pair_overlaps:
        for index, polygon in enumerate(valid_polygons):
            for other in valid_polygons[index + 1 :]:
                try:
                    if float(polygon.intersection(other).area) > area_tolerance:
                        return None
                except Exception:
                    return None
    if require_connected and len(ordered) > 1 and not _one_way_subset_is_connected(
        ordered,
        shape_tolerance=shape_tol,
        direction_tolerance_deg=direction_tolerance_deg,
    ):
        return None
    try:
        merged = unary_union(valid_polygons)
    except Exception:
        return None
    if getattr(merged, "geom_type", "") != "Polygon" or merged.is_empty or not merged.is_valid:
        return None
    try:
        if not bool(merged.is_simple) or not bool(merged.exterior.is_simple) or len(merged.interiors) != 0:
            return None
    except Exception:
        return None
    source_area = sum(float(polygon.area) for polygon in valid_polygons)
    preservation_tolerance = max(area_tolerance, abs(source_area) * 1.0e-9)
    if abs(float(merged.area) - source_area) > preservation_tolerance:
        return None
    polygon_xy = _polygon_exterior(merged)
    vertex_count = one_way_vertex_count(polygon_xy, tolerance=shape_tol)
    if vertex_count not in {3, 4}:
        return None
    normalized_angles = [
        _normal_one_way_angle(region.one_way_angle)
        for region in ordered
        if _normal_one_way_angle(region.one_way_angle) is not None
    ]
    one_way_angle = normalized_angles[0] if normalized_angles else _short_span_angle(polygon_xy)
    return OneWayMergeCandidate(
        region_keys=tuple(sorted(region.region_key for region in ordered)),
        cell_ids=tuple(sorted({str(cell_id) for region in ordered for cell_id in region.cell_ids})),
        polygon_xy=polygon_xy,
        area=float(merged.area),
        vertex_count=vertex_count,
        one_way_angle=one_way_angle,
    )


def _minimum_one_way_partition(
    component: Sequence[EditableHatchRegion],
    candidates: Sequence[OneWayMergeCandidate],
) -> tuple[OneWayMergeCandidate, ...]:
    ordered = tuple(sorted(component, key=_region_sort_key))
    index_by_key = {region.region_key: index for index, region in enumerate(ordered)}
    all_mask = (1 << len(ordered)) - 1
    candidate_masks: list[tuple[OneWayMergeCandidate, int]] = []
    for candidate in sorted(candidates, key=_one_way_candidate_sort_key):
        try:
            mask = sum(1 << index_by_key[key] for key in candidate.region_keys)
        except KeyError:
            continue
        if mask:
            candidate_masks.append((candidate, mask))
    by_first: dict[int, list[tuple[OneWayMergeCandidate, int]]] = {index: [] for index in range(len(ordered))}
    for item in candidate_masks:
        _candidate, mask = item
        for index in range(len(ordered)):
            if mask & (1 << index):
                by_first[index].append(item)
    best: tuple[OneWayMergeCandidate, ...] | None = None
    maximum_cover = max((mask.bit_count() for _candidate, mask in candidate_masks), default=1)

    def search(uncovered: int, plan: tuple[OneWayMergeCandidate, ...]) -> None:
        nonlocal best
        if not uncovered:
            canonical = tuple(sorted(plan, key=_one_way_candidate_sort_key))
            if best is None or _one_way_partition_score(canonical) < _one_way_partition_score(best):
                best = canonical
            return
        if best is not None:
            lower_bound = ceil(uncovered.bit_count() / max(maximum_cover, 1))
            if len(plan) + lower_bound > len(best):
                return
        first_bit = uncovered & -uncovered
        first_index = first_bit.bit_length() - 1
        for candidate, mask in by_first.get(first_index, ()):
            if mask & uncovered != mask:
                continue
            search(uncovered ^ mask, plan + (candidate,))

    search(all_mask, ())
    return best or ()


def _enumerate_one_way_candidates(
    component: Sequence[EditableHatchRegion],
    *,
    shape_tolerance: float,
    direction_tolerance_deg: float,
    max_candidates: int,
) -> tuple[list[OneWayMergeCandidate], bool]:
    adjacency = _one_way_adjacency_masks(
        component,
        shape_tolerance=shape_tolerance,
        direction_tolerance_deg=direction_tolerance_deg,
    )
    candidates: list[OneWayMergeCandidate] = []
    for mask in range(1, 1 << len(component)):
        if not _mask_is_connected(mask, adjacency):
            continue
        subset = [component[index] for index in range(len(component)) if mask & (1 << index)]
        candidate = _build_valid_one_way_merge_candidate(
            subset,
            shape_tolerance=shape_tolerance,
            direction_tolerance_deg=direction_tolerance_deg,
        )
        if candidate is None:
            continue
        if len(candidates) >= max_candidates:
            return candidates, True
        candidates.append(candidate)
    return sorted(candidates, key=_one_way_candidate_sort_key), False


def _fallback_one_way_candidates(
    component: Sequence[EditableHatchRegion],
    *,
    shape_tolerance: float,
    direction_tolerance_deg: float,
    max_candidates: int,
) -> list[OneWayMergeCandidate]:
    adjacency = _one_way_adjacency_masks(
        component,
        shape_tolerance=shape_tolerance,
        direction_tolerance_deg=direction_tolerance_deg,
    )
    candidate_by_regions: dict[tuple[str, ...], OneWayMergeCandidate] = {}
    seen_masks: set[int] = set()
    maximum_states = max(max_candidates * 4, len(component))
    examined_states = 0
    for index, region in enumerate(component):
        candidate = _build_valid_one_way_merge_candidate(
            (region,),
            shape_tolerance=shape_tolerance,
            direction_tolerance_deg=direction_tolerance_deg,
        )
        if candidate is not None:
            candidate_by_regions[candidate.region_keys] = candidate
    for seed in range(len(component)):
        stack = [1 << seed]
        allowed = ~((1 << seed) - 1)
        while stack and examined_states < maximum_states and len(candidate_by_regions) < max_candidates:
            mask = stack.pop()
            if mask in seen_masks:
                continue
            seen_masks.add(mask)
            examined_states += 1
            subset = [component[index] for index in range(len(component)) if mask & (1 << index)]
            candidate = _build_valid_one_way_merge_candidate(
                subset,
                shape_tolerance=shape_tolerance,
                direction_tolerance_deg=direction_tolerance_deg,
            )
            if candidate is not None:
                candidate_by_regions[candidate.region_keys] = candidate
            frontier = 0
            for index in range(len(component)):
                if mask & (1 << index):
                    frontier |= adjacency[index]
            frontier &= ~mask & allowed
            additions = [index for index in range(len(component)) if frontier & (1 << index)]
            for index in reversed(additions):
                stack.append(mask | (1 << index))
        if examined_states >= maximum_states or len(candidate_by_regions) >= max_candidates:
            break
    return sorted(candidate_by_regions.values(), key=_one_way_candidate_sort_key)


def _greedy_one_way_partition(
    component: Sequence[EditableHatchRegion],
    candidates: Sequence[OneWayMergeCandidate],
) -> tuple[OneWayMergeCandidate, ...]:
    index_by_key = {region.region_key: index for index, region in enumerate(component)}
    masked: list[tuple[OneWayMergeCandidate, int]] = []
    for candidate in sorted(candidates, key=_one_way_candidate_sort_key):
        try:
            mask = sum(1 << index_by_key[key] for key in candidate.region_keys)
        except KeyError:
            continue
        masked.append((candidate, mask))
    selected: list[tuple[OneWayMergeCandidate, int]] = []
    used = 0
    for candidate, mask in masked:
        if mask & used:
            continue
        selected.append((candidate, mask))
        used |= mask
    all_mask = (1 << len(component)) - 1
    if used != all_mask:
        return ()
    best_by_mask = {mask: candidate for candidate, mask in reversed(masked)}
    improved = True
    while improved:
        improved = False
        for first_index in range(len(selected)):
            for second_index in range(first_index + 1, len(selected)):
                union_mask = selected[first_index][1] | selected[second_index][1]
                replacement = best_by_mask.get(union_mask)
                if replacement is None:
                    continue
                proposed = [item for index, item in enumerate(selected) if index not in {first_index, second_index}]
                proposed.append((replacement, union_mask))
                current_plan = tuple(item[0] for item in selected)
                proposed_plan = tuple(item[0] for item in proposed)
                if _one_way_partition_score(proposed_plan) < _one_way_partition_score(current_plan):
                    selected = proposed
                    improved = True
                    break
            if improved:
                break
    return tuple(sorted((item[0] for item in selected), key=_one_way_candidate_sort_key))


def _one_way_region_from_candidate(
    component: Sequence[EditableHatchRegion],
    candidate: OneWayMergeCandidate,
) -> EditableHatchRegion:
    source_by_key = {region.region_key: region for region in component}
    sources = sorted((source_by_key[key] for key in candidate.region_keys), key=_region_sort_key)
    first = sources[0]
    warning_codes = tuple(
        dict.fromkeys(
            str(code)
            for source in sources
            for code in tuple(source.warning_codes or ())
            if str(code)
        )
    )
    load_region = replace(first, one_way_angle=candidate.one_way_angle)
    return replace(
        first,
        region_key=_region_key(first.story_name, candidate.cell_ids, load_key=_load_key(load_region)),
        cell_ids=candidate.cell_ids,
        polygon_xy=candidate.polygon_xy,
        one_way_angle=candidate.one_way_angle,
        is_merged=len(candidate.cell_ids) > 1,
        warning_codes=warning_codes,
    )


def _one_way_candidates_cover_sources(
    component: Sequence[EditableHatchRegion],
    candidates: Sequence[OneWayMergeCandidate],
) -> bool:
    singleton_keys = {candidate.region_keys[0] for candidate in candidates if len(candidate.region_keys) == 1}
    return all(region.region_key in singleton_keys for region in component)


def _one_way_candidate_sort_key(candidate: OneWayMergeCandidate) -> tuple:
    return (-len(candidate.cell_ids), -round(float(candidate.area), 12), candidate.cell_ids, candidate.region_keys)


def _one_way_partition_score(candidates: Sequence[OneWayMergeCandidate]) -> tuple:
    ordered = tuple(sorted(candidates, key=_one_way_candidate_sort_key))
    return (
        len(ordered),
        tuple(-len(candidate.cell_ids) for candidate in ordered),
        tuple(-round(float(candidate.area), 12) for candidate in ordered),
        tuple(candidate.cell_ids for candidate in ordered),
        tuple(candidate.region_keys for candidate in ordered),
    )


def _one_way_adjacency_masks(
    component: Sequence[EditableHatchRegion],
    *,
    shape_tolerance: float,
    direction_tolerance_deg: float = ONE_WAY_DIRECTION_COMPATIBILITY_TOLERANCE_DEG,
) -> tuple[int, ...]:
    masks = [0 for _region in component]
    for first_index, first in enumerate(component):
        for second_index in range(first_index + 1, len(component)):
            second = component[second_index]
            if not _one_way_directions_compatible(first, second, tolerance_deg=direction_tolerance_deg):
                continue
            if not _one_way_regions_share_mergeable_edge(first, second, shape_tolerance=shape_tolerance):
                continue
            masks[first_index] |= 1 << second_index
            masks[second_index] |= 1 << first_index
    return tuple(masks)


def _mask_is_connected(mask: int, adjacency: Sequence[int]) -> bool:
    if not mask:
        return False
    reached = mask & -mask
    while True:
        neighbors = 0
        for index in range(len(adjacency)):
            if reached & (1 << index):
                neighbors |= adjacency[index]
        expanded = reached | (neighbors & mask)
        if expanded == reached:
            return reached == mask
        reached = expanded


def _one_way_subset_is_connected(
    regions: Sequence[EditableHatchRegion],
    *,
    shape_tolerance: float,
    direction_tolerance_deg: float = ONE_WAY_DIRECTION_COMPATIBILITY_TOLERANCE_DEG,
) -> bool:
    if len(regions) <= 1:
        return True
    adjacency = _one_way_adjacency_masks(
        regions,
        shape_tolerance=shape_tolerance,
        direction_tolerance_deg=direction_tolerance_deg,
    )
    return _mask_is_connected((1 << len(regions)) - 1, adjacency)


def _merge_component(
    component: Sequence[EditableHatchRegion],
    *,
    shape_tolerance: float = 1.0e-8,
) -> EditableHatchRegion:
    return _merge_component_to_regions(component, shape_tolerance=shape_tolerance)[0]


def _merge_component_to_regions(
    component: Sequence[EditableHatchRegion],
    *,
    shape_tolerance: float = 1.0e-8,
) -> list[EditableHatchRegion]:
    if len(component) == 1:
        return [component[0]]
    polygons = [_polygon(region) for region in component]
    merged = unary_union([polygon for polygon in polygons if polygon is not None])
    if merged.geom_type != "Polygon":
        return list(component)
    first = component[0]
    cell_ids = tuple(sorted({cell_id for region in component for cell_id in region.cell_ids}))
    polygon_xy = _polygon_exterior(merged)
    if _normal_distribution(first.distribution) == DISTRIBUTION_ONE_WAY:
        shape_tol = max(abs(float(shape_tolerance)), 1.0e-12)
        if one_way_vertex_count(polygon_xy, tolerance=shape_tol) not in {3, 4}:
            return list(component)
        one_way_angle = _short_span_angle(polygon_xy)
    else:
        one_way_angle = first.one_way_angle
    key = _region_key(first.story_name, cell_ids, load_key=_load_key(first))
    return [
        replace(
            first,
            region_key=key,
            cell_ids=cell_ids,
            polygon_xy=polygon_xy,
            one_way_angle=one_way_angle,
            is_merged=True,
        )
    ]


def _regions_touch_any(component: Sequence[EditableHatchRegion], other: EditableHatchRegion) -> bool:
    other_polygon = _polygon(other)
    if other_polygon is None:
        return False
    for region in component:
        polygon = _polygon(region)
        if polygon is not None and (polygon.touches(other_polygon) or polygon.intersects(other_polygon)):
            return True
    return False


def _one_way_axis_difference_deg(first: float, second: float) -> float:
    delta = abs((float(first) - float(second)) % 180.0)
    return min(delta, 180.0 - delta)


def _one_way_directions_compatible(
    first,
    second,
    tolerance_deg: float = ONE_WAY_DIRECTION_COMPATIBILITY_TOLERANCE_DEG,
) -> bool:
    first_value = getattr(first, "one_way_angle", first)
    second_value = getattr(second, "one_way_angle", second)
    first_angle = _normal_one_way_angle(first_value)
    second_angle = _normal_one_way_angle(second_value)
    if first_angle is None or second_angle is None:
        return first_angle is None and second_angle is None
    return _one_way_axis_difference_deg(first_angle, second_angle) <= max(abs(float(tolerance_deg)), 0.0)


def _one_way_regions_share_mergeable_edge(
    first: EditableHatchRegion,
    second: EditableHatchRegion,
    *,
    shape_tolerance: float,
) -> bool:
    first_polygon = _strict_polygon(first)
    second_polygon = _strict_polygon(second)
    if first_polygon is None or second_polygon is None:
        return False
    shape_tol = max(abs(float(shape_tolerance)), 1.0e-12)
    length_tolerance = max(shape_tol, 1.0e-9)
    area_tolerance = max(shape_tol * shape_tol * 10.0, 1.0e-12)
    try:
        if float(first_polygon.intersection(second_polygon).area) > area_tolerance:
            return False
        shared_length = float(first_polygon.boundary.intersection(second_polygon.boundary).length)
    except Exception:
        return False
    return shared_length > length_tolerance


def _selected_cell_ids(state: HatchEditState) -> set[str]:
    cells = set(state.selected_cell_ids)
    for key in state.selected_region_keys:
        region = state.regions_by_key.get(key)
        if region is not None:
            cells.update(region.cell_ids)
    return cells


def _without_cells(
    state: HatchEditState,
    cell_ids: set[str],
) -> dict[str, EditableHatchRegion]:
    updated: dict[str, EditableHatchRegion] = {}
    for key, region in state.regions_by_key.items():
        region_cell_ids = set(region.cell_ids)
        if region_cell_ids.isdisjoint(cell_ids):
            updated[key] = region
            continue
        remaining_cell_ids = tuple(cell_id for cell_id in region.cell_ids if cell_id not in cell_ids)
        for cell_id in remaining_cell_ids:
            cell = state.cells_by_id.get(cell_id)
            if cell is None:
                continue
            child = _region_from_cell(
                cell,
                load_name=region.load_name,
                load_layer=region.load_layer,
                dl=region.dl,
                ll=region.ll,
                distribution=region.distribution,
                one_way_angle=region.one_way_angle,
            )
            updated[child.region_key] = child
    return updated


def _region_from_cell(
    cell: ClosedCell,
    *,
    load_name: str | None = None,
    load_layer: str | None = None,
    dl: float | None = None,
    ll: float | None = None,
    distribution: str = "TWO_WAY",
    one_way_angle: float | None = None,
) -> EditableHatchRegion:
    normalized_distribution = _normal_distribution(distribution)
    normalized_angle = _normal_one_way_angle(one_way_angle) if normalized_distribution == DISTRIBUTION_ONE_WAY else one_way_angle
    return EditableHatchRegion(
        region_key=_region_key(cell.story_name, (cell.cell_id,), load_key=(load_name, load_layer, dl, ll, normalized_distribution, normalized_angle)),
        story_name=cell.story_name,
        cell_ids=(cell.cell_id,),
        polygon_xy=tuple(cell.polygon_xy),
        load_name=load_name,
        load_layer=load_layer,
        dl=None if dl is None else float(dl),
        ll=None if ll is None else float(ll),
        distribution=normalized_distribution,
        one_way_angle=normalized_angle,
        source="INTERNAL",
        is_merged=False,
        warning_codes=tuple(cell.warning_codes),
    )


def _region_key(story_name: str, cell_ids: Sequence[str], *, load_key: object = None) -> str:
    cells = "+".join(sorted(str(cell_id) for cell_id in cell_ids))
    if load_key is None or (isinstance(load_key, tuple) and not load_key[0]):
        return f"INTERNAL|{story_name}|{cells}|UNLOADED"
    load_text = "_".join(_safe_key_part(value) for value in (load_key if isinstance(load_key, tuple) else (load_key,)))
    return f"INTERNAL|{story_name}|{cells}|LOADED|{load_text}"


def _safe_key_part(value: object) -> str:
    text = "NONE" if value is None else str(value)
    return "".join(ch if ch.isalnum() or ch in {"-", "."} else "_" for ch in text)[:80] or "EMPTY"


def _load_key(region: EditableHatchRegion) -> tuple:
    base = _base_load_key(region)
    distribution = _normal_distribution(region.distribution)
    if distribution == DISTRIBUTION_ONE_WAY and region.one_way_angle is not None:
        normalized_angle = _normal_one_way_angle(region.one_way_angle)
        angle_key = None if normalized_angle is None else round(normalized_angle, 8)
    else:
        angle_key = None if region.one_way_angle is None else round(float(region.one_way_angle), 8)
    return base + (angle_key,)


def _base_load_key(region: EditableHatchRegion) -> tuple:
    return (
        region.story_name,
        region.load_name,
        region.load_layer,
        None if region.dl is None else round(float(region.dl), 8),
        None if region.ll is None else round(float(region.ll), 8),
        _normal_distribution(region.distribution),
    )


def _region_sort_key(region: EditableHatchRegion) -> tuple:
    return (tuple(str(cell_id) for cell_id in region.cell_ids), str(region.region_key))


def _polygon(region: EditableHatchRegion) -> Polygon | None:
    if len(region.polygon_xy) < 3:
        return None
    polygon = Polygon(region.polygon_xy)
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.area <= 1.0e-12:
        return None
    if polygon.geom_type != "Polygon":
        return None
    return polygon


def _strict_polygon(region: EditableHatchRegion) -> Polygon | None:
    if len(region.polygon_xy) < 3:
        return None
    try:
        polygon = Polygon(region.polygon_xy)
    except Exception:
        return None
    if polygon.is_empty or not polygon.is_valid or polygon.area <= 1.0e-12:
        return None
    if polygon.geom_type != "Polygon":
        return None
    try:
        if not bool(polygon.is_simple) or not bool(polygon.exterior.is_simple):
            return None
    except Exception:
        return None
    return polygon


def _selection_polygon(value: object) -> Polygon | None:
    if value is None:
        return None
    try:
        polygon = value if getattr(value, "geom_type", "") else Polygon(value)  # type: ignore[arg-type]
    except Exception:
        return None
    try:
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.is_empty or polygon.area <= 1.0e-12 or polygon.geom_type != "Polygon":
            return None
    except Exception:
        return None
    return polygon


def _bounds_intersect(first: Sequence[float], second: Sequence[float]) -> bool:
    return not (
        float(first[2]) < float(second[0])
        or float(second[2]) < float(first[0])
        or float(first[3]) < float(second[1])
        or float(second[3]) < float(first[1])
    )


def _polygon_exterior(polygon) -> tuple[tuple[float, float], ...]:
    coords = list(polygon.exterior.coords)
    if len(coords) > 1 and coords[0] == coords[-1]:
        coords = coords[:-1]
    return tuple((float(x), float(y)) for x, y in coords)


def one_way_vertex_count(points: Sequence[tuple[float, float]], *, tolerance: float = 1.0e-8) -> int:
    cleaned = _clean_polygon_vertices(points, tolerance=tolerance)
    if len(cleaned) < 3:
        return 0
    polygon = Polygon(cleaned)
    if polygon.is_empty or polygon.area <= 1.0e-12:
        return 0
    if not polygon.is_valid:
        polygon = polygon.buffer(0)
    if polygon.is_empty or polygon.geom_type != "Polygon" or polygon.area <= 1.0e-12:
        return 0
    exterior = _clean_polygon_vertices(_polygon_exterior(polygon), tolerance=tolerance)
    return len(exterior) if len(exterior) >= 3 else 0


def is_one_way_tri_or_quad(points: Sequence[tuple[float, float]], *, tolerance: float = 1.0e-8) -> bool:
    return one_way_vertex_count(points, tolerance=tolerance) in {3, 4}


def _clean_polygon_vertices(points: Sequence[tuple[float, float]], *, tolerance: float = 1.0e-8) -> list[tuple[float, float]]:
    tol = max(abs(float(tolerance)), 1.0e-12)
    raw: list[tuple[float, float]] = []
    for point in tuple(points or ()):
        if len(point) < 2:
            continue
        candidate = (float(point[0]), float(point[1]))
        if raw and _point_distance(raw[-1], candidate) <= tol:
            continue
        raw.append(candidate)
    while len(raw) > 1 and _point_distance(raw[0], raw[-1]) <= tol:
        raw.pop()
    changed = True
    while changed and len(raw) >= 3:
        changed = False
        result: list[tuple[float, float]] = []
        for index, current in enumerate(raw):
            previous = raw[index - 1]
            next_point = raw[(index + 1) % len(raw)]
            if _point_distance(previous, current) <= tol or _point_distance(current, next_point) <= tol:
                changed = True
                continue
            if _is_collinear(previous, current, next_point, tolerance=tol):
                changed = True
                continue
            result.append(current)
        raw = result
    return raw


def _is_collinear(
    first: tuple[float, float],
    middle: tuple[float, float],
    last: tuple[float, float],
    *,
    tolerance: float,
) -> bool:
    area2 = abs((middle[0] - first[0]) * (last[1] - first[1]) - (middle[1] - first[1]) * (last[0] - first[0]))
    scale = max(_point_distance(first, middle), _point_distance(middle, last), _point_distance(first, last), 1.0)
    return area2 <= float(tolerance) * scale


def _point_distance(first: tuple[float, float], second: tuple[float, float]) -> float:
    return ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5


def _short_span_angle(points: Sequence[tuple[float, float]]) -> float | None:
    angle, _source, _warnings = infer_short_span_angle(points)
    return _normal_one_way_angle(angle)


def _normal_one_way_angle(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value) % 180.0
    except Exception:
        return None


def _normal_distribution(value: str | None) -> str:
    text = str(value or "TWO_WAY").strip().upper().replace("-", "_").replace(" ", "_")
    return text or "TWO_WAY"
