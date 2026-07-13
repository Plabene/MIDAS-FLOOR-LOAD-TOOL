from __future__ import annotations

from dataclasses import dataclass
from math import floor, hypot
from typing import Iterable, Sequence

from shapely.geometry import GeometryCollection, LineString, MultiPolygon, Point, Polygon
from shapely.geometry.polygon import orient
from shapely.ops import polygonize, unary_union

from .mgt_parser import Element, Node, Story, load_dm_material_section_ids_from_text


BOUNDARY_ELEMENT_TYPES = {"BEAM", "WALL", "SLAB", "PLATE", "PLANAR"}
POLYGON_ELEMENT_TYPES = {"SLAB", "PLATE", "PLANAR"}
LINE_ELEMENT_TYPES = {"BEAM", "WALL"}
EXCLUDED_ELEMENT_TYPES = {
    "COLUMN",
    "ELASTICLINK",
    "ELASTIC_LINK",
    "LINK",
    "LOADDM",
    "LOAD_DM",
}


@dataclass(frozen=True)
class ClosedRegionProfile:
    story_name: str
    story_elevation: float
    region_id: str
    outer_ring_node_ids: tuple[int, ...]
    outer_ring_xy: tuple[tuple[float, float], ...]
    area: float
    perimeter: float
    centroid: tuple[float, float]
    bbox: tuple[float, float, float, float]
    warning_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StoryShapeProfile:
    story_name: str
    story_elevation: float
    regions: tuple[ClosedRegionProfile, ...]
    union_area: float
    polygon_count: int
    valid: bool
    warning_codes: tuple[str, ...] = ()
    all_node_xy: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class StorySimilarity:
    story_a: str
    story_b: str
    iou: float
    boundary_coverage: float
    node_match_ratio: float
    area_ratio: float
    score: float
    reason: str = ""


@dataclass(frozen=True)
class TypicalFloorGroup:
    group_id: str
    story_names: tuple[str, ...]
    typical_story_name: str | None
    typical_score: float
    transition_floor_names: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class ContinuousApplyCandidate:
    base_story_name: str
    target_story_name: str
    can_apply: bool
    similarity_score: float
    boundary_node_match_ratio: float
    iou: float
    reason: str


@dataclass(frozen=True)
class HatchLocalMatch:
    ok: bool
    iou: float
    vertex_match_ratio: float
    boundary_coverage: float
    reason: str
    source_coverage: float = 0.0
    target_overreach_ratio: float = 0.0


@dataclass(frozen=True)
class TypicalFloorAnalysis:
    profiles: tuple[StoryShapeProfile, ...]
    similarities: tuple[StorySimilarity, ...]
    groups: tuple[TypicalFloorGroup, ...]


def build_story_shape_profiles(
    *,
    stories: Sequence[Story],
    nodes: Sequence[Node],
    elements: Sequence[Element],
    mgt_text: str | None = None,
    excluded_element_ids: Iterable[int] | None = None,
    excluded_material_ids: Iterable[int] | None = None,
    excluded_section_ids: Iterable[int] | None = None,
    story_tolerance: float = 0.01,
    xy_tolerance: float | None = None,
) -> tuple[StoryShapeProfile, ...]:
    """Build per-story closed-region profiles using only structural boundary geometry."""

    tol_z = abs(float(story_tolerance))
    tol_xy = _effective_xy_tolerance(xy_tolerance)
    node_by_id = {int(node.node_id): node for node in nodes}
    excluded_ids = {int(value) for value in (excluded_element_ids or ())}
    excluded_mats = {int(value) for value in (excluded_material_ids or ())}
    excluded_props = {int(value) for value in (excluded_section_ids or ())}
    if mgt_text:
        load_dm_mats, load_dm_props = load_dm_material_section_ids_from_text(mgt_text)
        excluded_mats.update(load_dm_mats)
        excluded_props.update(load_dm_props)
    profiles: list[StoryShapeProfile] = []
    for story in sorted(stories, key=lambda item: float(item.elevation)):
        profiles.append(
            build_story_shape_profile(
                story=story,
                nodes=nodes,
                elements=elements,
                node_by_id=node_by_id,
                excluded_element_ids=excluded_ids,
                excluded_material_ids=excluded_mats,
                excluded_section_ids=excluded_props,
                story_tolerance=tol_z,
                xy_tolerance=tol_xy,
            )
        )
    return tuple(profiles)


def build_story_shape_profile(
    *,
    story: Story,
    nodes: Sequence[Node],
    elements: Sequence[Element],
    node_by_id: dict[int, Node] | None = None,
    excluded_element_ids: Iterable[int] | None = None,
    excluded_material_ids: Iterable[int] | None = None,
    excluded_section_ids: Iterable[int] | None = None,
    story_tolerance: float = 0.01,
    xy_tolerance: float | None = None,
) -> StoryShapeProfile:
    node_lookup = node_by_id or {int(node.node_id): node for node in nodes}
    tol_z = abs(float(story_tolerance))
    tol_xy = _effective_xy_tolerance(xy_tolerance)
    excluded_ids = {int(value) for value in (excluded_element_ids or ())}
    excluded_mats = {int(value) for value in (excluded_material_ids or ())}
    excluded_props = {int(value) for value in (excluded_section_ids or ())}
    story_nodes = [node for node in nodes if abs(float(node.z) - float(story.elevation)) <= tol_z]
    story_node_ids = {int(node.node_id) for node in story_nodes}
    warnings: list[str] = []
    if not story_nodes:
        return StoryShapeProfile(
            story_name=story.name,
            story_elevation=float(story.elevation),
            regions=(),
            union_area=0.0,
            polygon_count=0,
            valid=False,
            warning_codes=("NO_STORY_NODES",),
            all_node_xy=(),
        )

    polygons: list[Polygon] = []
    linework: list[LineString] = []
    for element in elements:
        if _is_excluded_profile_element(element, excluded_ids, excluded_mats, excluded_props):
            continue
        elem_type = _normal_element_type(element.elem_type)
        if elem_type in EXCLUDED_ELEMENT_TYPES:
            continue
        if elem_type not in BOUNDARY_ELEMENT_TYPES:
            continue
        element_nodes = [node_lookup[node_id] for node_id in element.node_ids if node_id in node_lookup]
        on_story = [node for node in element_nodes if int(node.node_id) in story_node_ids]
        if elem_type in POLYGON_ELEMENT_TYPES and len(on_story) >= 3:
            polygon = _polygon_from_nodes(on_story)
            if polygon is not None:
                polygons.append(polygon)
                continue
        if elem_type in LINE_ELEMENT_TYPES and len(on_story) >= 2:
            for start, end in zip(on_story, on_story[1:]):
                line = _line_from_nodes(start, end)
                if line is not None:
                    linework.append(line)
            if len(on_story) > 2:
                line = _line_from_nodes(on_story[-1], on_story[0])
                if line is not None:
                    linework.append(line)

    if linework:
        try:
            merged_linework = unary_union(linework)
            polygons.extend(_clean_polygon(poly) for poly in polygonize(merged_linework))
        except Exception:
            warnings.append("POLYGONIZE_FAILED")
    polygons = [poly for poly in (_clean_polygon(poly) for poly in polygons) if _usable_polygon(poly)]

    if not polygons:
        warning_codes = list(dict.fromkeys([*warnings, "NO_CLOSED_REGION"]))
        if linework:
            warning_codes.append("OPEN_BOUNDARY")
        return StoryShapeProfile(
            story_name=story.name,
            story_elevation=float(story.elevation),
            regions=(),
            union_area=0.0,
            polygon_count=0,
            valid=False,
            warning_codes=tuple(warning_codes),
            all_node_xy=tuple(_dedupe_points((node.x, node.y) for node in story_nodes)),
        )

    union = _polygonal_union(polygons)
    region_polygons = _iter_polygons(union)
    regions = tuple(
        _region_profile_from_polygon(
            story=story,
            polygon=polygon,
            region_index=index,
            story_nodes=story_nodes,
            xy_tolerance=tol_xy,
        )
        for index, polygon in enumerate(region_polygons, start=1)
        if _usable_polygon(polygon)
    )
    warning_codes = tuple(dict.fromkeys(warnings))
    return StoryShapeProfile(
        story_name=story.name,
        story_elevation=float(story.elevation),
        regions=regions,
        union_area=float(union.area) if not union.is_empty else 0.0,
        polygon_count=len(regions),
        valid=bool(regions),
        warning_codes=warning_codes,
        all_node_xy=tuple(_dedupe_points((node.x, node.y) for node in story_nodes)),
    )


def analyze_typical_floors(
    *,
    stories: Sequence[Story],
    nodes: Sequence[Node],
    elements: Sequence[Element],
    mgt_text: str | None = None,
    story_penalties: dict[str, float] | None = None,
    excluded_element_ids: Iterable[int] | None = None,
    excluded_material_ids: Iterable[int] | None = None,
    excluded_section_ids: Iterable[int] | None = None,
    story_tolerance: float = 0.01,
    xy_tolerance: float | None = None,
    similarity_threshold: float = 0.82,
    identical_threshold: float = 0.90,
    transition_threshold: float = 0.70,
    soft_transition_threshold: float = 0.82,
) -> TypicalFloorAnalysis:
    profiles = build_story_shape_profiles(
        stories=stories,
        nodes=nodes,
        elements=elements,
        mgt_text=mgt_text,
        excluded_element_ids=excluded_element_ids,
        excluded_material_ids=excluded_material_ids,
        excluded_section_ids=excluded_section_ids,
        story_tolerance=story_tolerance,
        xy_tolerance=xy_tolerance,
    )
    similarities: list[StorySimilarity] = []
    for index, first in enumerate(profiles):
        for second in profiles[index + 1 :]:
            similarities.append(compare_story_profiles(first, second, xy_tolerance=xy_tolerance))
    groups = detect_typical_floor_groups(
        profiles,
        xy_tolerance=xy_tolerance,
        similarity_threshold=similarity_threshold,
        identical_threshold=identical_threshold,
        transition_threshold=transition_threshold,
        soft_transition_threshold=soft_transition_threshold,
        story_penalties=story_penalties,
    )
    return TypicalFloorAnalysis(profiles=profiles, similarities=tuple(similarities), groups=groups)


def compare_story_profiles(
    first: StoryShapeProfile,
    second: StoryShapeProfile,
    *,
    xy_tolerance: float | None = None,
) -> StorySimilarity:
    tol_xy = _effective_xy_tolerance(xy_tolerance)
    boundary_buffer = tol_xy * 2.0
    if not first.valid or not second.valid:
        return StorySimilarity(
            first.story_name,
            second.story_name,
            iou=0.0,
            boundary_coverage=0.0,
            node_match_ratio=0.0,
            area_ratio=0.0,
            score=0.0,
            reason="INVALID_PROFILE",
        )

    geom_a = _profile_geometry(first)
    geom_b = _profile_geometry(second)
    if geom_a.is_empty or geom_b.is_empty:
        return StorySimilarity(first.story_name, second.story_name, 0.0, 0.0, 0.0, 0.0, 0.0, "EMPTY_GEOMETRY")

    union_area = geom_a.union(geom_b).area
    iou = 0.0 if union_area <= 1.0e-12 else geom_a.intersection(geom_b).area / union_area
    boundary_coverage = _boundary_coverage(geom_a, geom_b, boundary_buffer)
    node_match_ratio = _symmetric_node_match_ratio(_outer_ring_points(first), _outer_ring_points(second), tol_xy)
    area_ratio = _safe_ratio(min(first.union_area, second.union_area), max(first.union_area, second.union_area))
    score = 0.65 * iou + 0.20 * boundary_coverage + 0.10 * node_match_ratio + 0.05 * area_ratio
    reason = _similarity_reason(score)
    return StorySimilarity(
        story_a=first.story_name,
        story_b=second.story_name,
        iou=_clamp01(iou),
        boundary_coverage=_clamp01(boundary_coverage),
        node_match_ratio=_clamp01(node_match_ratio),
        area_ratio=_clamp01(area_ratio),
        score=_clamp01(score),
        reason=reason,
    )


def detect_typical_floor_groups(
    profiles: Sequence[StoryShapeProfile],
    *,
    xy_tolerance: float | None = None,
    story_penalties: dict[str, float] | None = None,
    similarity_threshold: float = 0.82,
    identical_threshold: float = 0.90,
    transition_threshold: float = 0.70,
    soft_transition_threshold: float = 0.82,
) -> tuple[TypicalFloorGroup, ...]:
    del identical_threshold
    ordered = sorted(profiles, key=lambda item: float(item.story_elevation))
    penalty_by_story = {str(key): max(0.0, float(value)) for key, value in (story_penalties or {}).items()}
    if not ordered:
        return ()

    segments: list[list[StoryShapeProfile]] = []
    transition_names: set[str] = set()
    current: list[StoryShapeProfile] = []
    for profile in ordered:
        if not current:
            current = [profile]
            if not profile.valid:
                transition_names.add(profile.story_name)
            continue
        previous = current[-1]
        similarity = compare_story_profiles(previous, profile, xy_tolerance=xy_tolerance)
        transition_boundary = _is_transition_boundary(
            previous,
            profile,
            similarity,
            transition_threshold=transition_threshold,
        )
        if not previous.valid or not profile.valid:
            segments.append(current)
            current = [profile]
            transition_names.add(profile.story_name)
        elif transition_boundary:
            segments.append(current)
            current = [profile]
        elif similarity.score >= soft_transition_threshold:
            current.append(profile)
        elif similarity.score >= transition_threshold:
            transition_names.add(profile.story_name)
            current.append(profile)
        else:
            segments.append(current)
            current = [profile]
    if current:
        segments.append(current)

    groups: list[TypicalFloorGroup] = []
    for index, segment in enumerate(segments, start=1):
        groups.append(
            _typical_group_from_segment(
                group_index=index,
                segment=segment,
                transition_names=transition_names,
                xy_tolerance=xy_tolerance,
                similarity_threshold=similarity_threshold,
                story_penalties=penalty_by_story,
            )
        )
    return tuple(groups)


def evaluate_continuous_apply_candidates(
    profiles: Sequence[StoryShapeProfile],
    *,
    base_story_name: str,
    target_story_names: Sequence[str] | None = None,
    hatch_polygon_xy: Sequence[tuple[float, float]] | None = None,
    typical_groups: Sequence[TypicalFloorGroup] | None = None,
    xy_tolerance: float | None = None,
    min_similarity_score: float = 0.90,
    min_iou: float = 0.90,
    min_boundary_node_match_ratio: float = 0.95,
    min_area_ratio: float = 0.95,
    min_source_coverage: float = 0.995,
    max_target_overreach_ratio: float = 0.005,
) -> tuple[ContinuousApplyCandidate, ...]:
    profile_by_name = {profile.story_name: profile for profile in profiles}
    base = profile_by_name.get(base_story_name)
    if base is None:
        return ()
    targets = list(target_story_names) if target_story_names is not None else [profile.story_name for profile in profiles]
    return tuple(
        check_continuous_apply_candidate(
            base,
            profile_by_name[name],
            hatch_polygon_xy=hatch_polygon_xy,
            typical_groups=typical_groups,
            xy_tolerance=xy_tolerance,
            min_similarity_score=min_similarity_score,
            min_iou=min_iou,
            min_boundary_node_match_ratio=min_boundary_node_match_ratio,
            min_area_ratio=min_area_ratio,
            min_source_coverage=min_source_coverage,
            max_target_overreach_ratio=max_target_overreach_ratio,
        )
        for name in targets
        if name in profile_by_name and name != base_story_name
    )


def check_continuous_apply_candidate(
    base_profile: StoryShapeProfile,
    target_profile: StoryShapeProfile,
    *,
    hatch_polygon_xy: Sequence[tuple[float, float]] | None = None,
    typical_groups: Sequence[TypicalFloorGroup] | None = None,
    xy_tolerance: float | None = None,
    min_similarity_score: float = 0.90,
    min_iou: float = 0.90,
    min_boundary_node_match_ratio: float = 0.95,
    min_area_ratio: float = 0.95,
    min_source_coverage: float = 0.995,
    max_target_overreach_ratio: float = 0.005,
) -> ContinuousApplyCandidate:
    tol_xy = _effective_continuous_xy_tolerance(xy_tolerance)
    similarity = compare_story_profiles(base_profile, target_profile, xy_tolerance=tol_xy)
    local_match = (
        compare_hatch_to_target_story(
            hatch_polygon_xy,
            target_profile,
            xy_tolerance=tol_xy,
            min_source_coverage=min_source_coverage,
            max_target_overreach_ratio=max_target_overreach_ratio,
        )
        if hatch_polygon_xy
        else HatchLocalMatch(False, 0.0, 0.0, 0.0, "NO_HATCH_POLYGON")
    )
    if not base_profile.valid or not target_profile.valid:
        if local_match.ok:
            return ContinuousApplyCandidate(
                base_profile.story_name,
                target_profile.story_name,
                True,
                similarity.score,
                local_match.vertex_match_ratio,
                max(similarity.iou, local_match.iou),
                "OK_LOCAL_HATCH_MATCH",
            )
        return ContinuousApplyCandidate(
            base_profile.story_name,
            target_profile.story_name,
            False,
            similarity.score,
            local_match.vertex_match_ratio,
            max(similarity.iou, local_match.iou),
            "INVALID_PROFILE",
        )
    same_group = True if not typical_groups else _same_typical_group(base_profile.story_name, target_profile.story_name, typical_groups)
    boundary_match = (
        _hatch_vertex_boundary_match_ratio(hatch_polygon_xy, target_profile, tol_xy)
        if hatch_polygon_xy
        else similarity.node_match_ratio
    )
    failures: list[str] = []
    if not same_group:
        failures.append("DIFFERENT_TYPICAL_GROUP")
    if similarity.score < min_similarity_score:
        failures.append("SIMILARITY_BELOW_THRESHOLD")
    if similarity.iou < min_iou:
        failures.append("IOU_BELOW_THRESHOLD")
    if boundary_match < min_boundary_node_match_ratio:
        failures.append("BOUNDARY_NODE_MISMATCH")
    if similarity.area_ratio < min_area_ratio:
        failures.append("AREA_RATIO_BELOW_THRESHOLD")
    if local_match.ok and failures:
        return ContinuousApplyCandidate(
            base_story_name=base_profile.story_name,
            target_story_name=target_profile.story_name,
            can_apply=True,
            similarity_score=similarity.score,
            boundary_node_match_ratio=max(boundary_match, local_match.vertex_match_ratio),
            iou=max(similarity.iou, local_match.iou),
            reason="OK_LOCAL_HATCH_MATCH",
        )
    reason = "OK" if not failures else ";".join(failures)
    if similarity.area_ratio < 1.0:
        reason = f"{reason} area_ratio={similarity.area_ratio:.3f}"
    return ContinuousApplyCandidate(
        base_story_name=base_profile.story_name,
        target_story_name=target_profile.story_name,
        can_apply=not failures,
        similarity_score=similarity.score,
        boundary_node_match_ratio=max(boundary_match, local_match.vertex_match_ratio),
        iou=max(similarity.iou, local_match.iou),
        reason=reason,
    )


def compare_hatch_to_target_story(
    hatch_polygon_xy: Sequence[tuple[float, float]] | None,
    target_profile: StoryShapeProfile,
    *,
    xy_tolerance: float | None,
    min_iou: float = 0.98,
    min_vertex_match_ratio: float = 0.85,
    min_boundary_coverage: float = 0.85,
    min_source_coverage: float = 0.995,
    max_target_overreach_ratio: float = 0.005,
) -> HatchLocalMatch:
    vertices = [_xy(point) for point in (hatch_polygon_xy or ()) if len(point) >= 2]
    if len(vertices) > 1 and _points_close(vertices[0], vertices[-1], _effective_continuous_xy_tolerance(xy_tolerance)):
        vertices = vertices[:-1]
    hatch_polygon = _clean_polygon(Polygon(vertices)) if len(vertices) >= 3 else Polygon()
    if not _usable_polygon(hatch_polygon):
        return HatchLocalMatch(False, 0.0, 0.0, 0.0, "INVALID_HATCH_POLYGON")

    tol_xy = _effective_continuous_xy_tolerance(xy_tolerance)
    target_polygons = [_polygon_from_region(region) for region in target_profile.regions]
    overlapping_polygons: list[Polygon] = []
    for target_polygon in target_polygons:
        if not _usable_polygon(target_polygon):
            continue
        try:
            if float(hatch_polygon.intersection(target_polygon).area) > 1.0e-12:
                overlapping_polygons.append(target_polygon)
        except Exception:
            continue

    target_union = _polygonal_union(overlapping_polygons)
    if getattr(target_union, "is_empty", True):
        outer_vertex_match = _node_match_ratio(vertices, _outer_ring_points(target_profile), tol_xy)
        story_node_match = _node_match_ratio(vertices, getattr(target_profile, "all_node_xy", ()), tol_xy)
        return HatchLocalMatch(
            False,
            0.0,
            max(outer_vertex_match, story_node_match),
            0.0,
            "LOCAL_PROJECTED_UNION_NOT_FOUND",
        )

    try:
        intersection_area = float(hatch_polygon.intersection(target_union).area)
        union_area = float(hatch_polygon.union(target_union).area)
        source_area = max(float(hatch_polygon.area), 1.0e-12)
        target_area = max(float(target_union.area), 1.0e-12)
        source_coverage = _clamp01(intersection_area / source_area)
        target_overreach_ratio = _clamp01(float(target_union.difference(hatch_polygon.buffer(tol_xy)).area) / target_area)
        iou = _clamp01(0.0 if union_area <= 1.0e-12 else intersection_area / union_area)
        boundary_coverage = _boundary_coverage(hatch_polygon, target_union, tol_xy * 2.0)
        source_missing_beyond_tolerance = float(hatch_polygon.difference(target_union.buffer(tol_xy)).area) / source_area
    except Exception:
        return HatchLocalMatch(False, 0.0, 0.0, 0.0, "LOCAL_PROJECTED_UNION_ERROR")

    outer_vertex_match = _node_match_ratio(vertices, _outer_ring_points(target_profile), tol_xy)
    story_node_match = _node_match_ratio(vertices, getattr(target_profile, "all_node_xy", ()), tol_xy)
    vertex_match = max(outer_vertex_match, story_node_match)
    coverage_ok = source_coverage >= min_source_coverage or source_missing_beyond_tolerance <= max_target_overreach_ratio
    overreach_ok = target_overreach_ratio <= max_target_overreach_ratio
    shape_ok = iou >= min_iou or (
        vertex_match >= min_vertex_match_ratio and boundary_coverage >= min_boundary_coverage
    )
    if coverage_ok and overreach_ok and shape_ok:
        return HatchLocalMatch(
            True,
            iou,
            vertex_match,
            boundary_coverage,
            "LOCAL_PROJECTED_UNION_MATCH",
            source_coverage,
            target_overreach_ratio,
        )
    if not coverage_ok:
        reason = "LOCAL_SOURCE_COVERAGE_MISMATCH"
    elif not overreach_ok:
        reason = "LOCAL_TARGET_OVERREACH"
    else:
        reason = "LOCAL_PROJECTED_UNION_MISMATCH"
    return HatchLocalMatch(
        False,
        iou,
        vertex_match,
        boundary_coverage,
        reason,
        source_coverage,
        target_overreach_ratio,
    )


def split_continuous_apply_ranges(
    candidates: Sequence[ContinuousApplyCandidate],
    story_order: Sequence[str],
) -> tuple[tuple[str, ...], ...]:
    by_name = {candidate.target_story_name: candidate for candidate in candidates}
    ranges: list[list[str]] = []
    current: list[str] = []
    for story_name in story_order:
        candidate = by_name.get(story_name)
        if candidate is not None and candidate.can_apply:
            current.append(story_name)
        elif current:
            ranges.append(current)
            current = []
    if current:
        ranges.append(current)
    return tuple(tuple(item) for item in ranges)


def typical_story_names(groups: Sequence[TypicalFloorGroup]) -> tuple[str, ...]:
    return tuple(group.typical_story_name for group in groups if group.typical_story_name)


def typical_group_for_story(groups: Sequence[TypicalFloorGroup], story_name: str) -> TypicalFloorGroup | None:
    for group in groups:
        if story_name in group.story_names:
            return group
    return None


# Backward-friendly aliases for tests and UI helpers.
profile_stories = build_story_shape_profiles
compare_story_similarity = compare_story_profiles
select_typical_floor_groups = detect_typical_floor_groups
candidate_continuous_apply = check_continuous_apply_candidate


def _typical_group_from_segment(
    *,
    group_index: int,
    segment: Sequence[StoryShapeProfile],
    transition_names: set[str],
    xy_tolerance: float | None,
    similarity_threshold: float,
    story_penalties: dict[str, float] | None = None,
) -> TypicalFloorGroup:
    story_names = tuple(profile.story_name for profile in segment)
    valid_profiles = [profile for profile in segment if profile.valid]
    local_transition_names = {profile.story_name for profile in segment if profile.story_name in transition_names or not profile.valid}
    if len(valid_profiles) < 2:
        return TypicalFloorGroup(
            group_id=f"G{group_index:03d}",
            story_names=story_names,
            typical_story_name=None,
            typical_score=0.0,
            transition_floor_names=tuple(story_names),
            reason="TOO_FEW_VALID_STORIES_FOR_AUTOMATIC_TYPICAL",
        )

    profile_scores: dict[str, float] = {}
    for profile in valid_profiles:
        other_scores = [
            compare_story_profiles(profile, other, xy_tolerance=xy_tolerance).score
            for other in valid_profiles
            if other.story_name != profile.story_name
        ]
        avg_score = sum(other_scores) / len(other_scores) if other_scores else 0.0
        profile_warning_penalty = 0.02 * len(profile.warning_codes)
        transition_penalty = 0.08 if profile.story_name in local_transition_names else 0.0
        diagnostic_penalty = max(0.0, float((story_penalties or {}).get(profile.story_name, 0.0) or 0.0))
        penalty = profile_warning_penalty + transition_penalty + diagnostic_penalty
        profile_scores[profile.story_name] = max(0.0, avg_score - penalty)

    center = (len(segment) - 1) / 2.0
    index_by_name = {profile.story_name: index for index, profile in enumerate(segment)}
    best = max(
        valid_profiles,
        key=lambda profile: (
            profile_scores.get(profile.story_name, 0.0),
            -abs(index_by_name.get(profile.story_name, 0) - center),
            profile.story_elevation,
        ),
    )
    best_score = profile_scores.get(best.story_name, 0.0)
    if best_score < similarity_threshold:
        typical_story_name = None
        reason = "SIMILARITY_BELOW_TYPICAL_THRESHOLD"
    else:
        typical_story_name = best.story_name
        reason = "OK"
    return TypicalFloorGroup(
        group_id=f"G{group_index:03d}",
        story_names=story_names,
        typical_story_name=typical_story_name,
        typical_score=best_score,
        transition_floor_names=tuple(name for name in story_names if name in local_transition_names),
        reason=reason,
    )


def _is_transition_boundary(
    first: StoryShapeProfile,
    second: StoryShapeProfile,
    similarity: StorySimilarity,
    *,
    transition_threshold: float,
) -> bool:
    if similarity.score < transition_threshold:
        return True
    if similarity.area_ratio < 0.85:
        return True
    if abs(first.polygon_count - second.polygon_count) >= 2:
        return True
    return _bbox_size_changed(first, second, ratio=0.10)


def _is_excluded_profile_element(
    element: Element,
    excluded_element_ids: set[int],
    excluded_material_ids: set[int],
    excluded_section_ids: set[int],
) -> bool:
    if int(element.elem_id) in excluded_element_ids:
        return True
    elem_type = _normal_element_type(element.elem_type)
    if elem_type != "BEAM":
        return False
    if element.mat is not None and int(element.mat) in excluded_material_ids:
        return True
    if element.prop is not None and int(element.prop) in excluded_section_ids:
        return True
    return False


def _profile_geometry(profile: StoryShapeProfile):
    polygons = [_polygon_from_region(region) for region in profile.regions]
    polygons = [polygon for polygon in polygons if _usable_polygon(polygon)]
    return _polygonal_union(polygons)


def _profile_bbox(profile: StoryShapeProfile) -> tuple[float, float, float, float] | None:
    geom = _profile_geometry(profile)
    if geom.is_empty:
        return None
    min_x, min_y, max_x, max_y = geom.bounds
    return (float(min_x), float(min_y), float(max_x), float(max_y))


def _bbox_size_changed(first: StoryShapeProfile, second: StoryShapeProfile, *, ratio: float) -> bool:
    bbox_a = _profile_bbox(first)
    bbox_b = _profile_bbox(second)
    if bbox_a is None or bbox_b is None:
        return True
    width_a = max(bbox_a[2] - bbox_a[0], 0.0)
    depth_a = max(bbox_a[3] - bbox_a[1], 0.0)
    width_b = max(bbox_b[2] - bbox_b[0], 0.0)
    depth_b = max(bbox_b[3] - bbox_b[1], 0.0)
    return _relative_delta(width_a, width_b) >= ratio or _relative_delta(depth_a, depth_b) >= ratio


def _relative_delta(first: float, second: float) -> float:
    denominator = max(abs(first), abs(second), 1.0e-12)
    return abs(first - second) / denominator


def _boundary_coverage(first, second, boundary_buffer: float) -> float:
    try:
        first_boundary = first.boundary
        second_boundary = second.boundary
        min_length = min(float(first_boundary.length), float(second_boundary.length))
        if min_length <= 1.0e-12:
            return 0.0
        first_coverage = first_boundary.intersection(second_boundary.buffer(boundary_buffer)).length / min_length
        second_coverage = second_boundary.intersection(first_boundary.buffer(boundary_buffer)).length / min_length
        return _clamp01(min(first_coverage, second_coverage))
    except Exception:
        return 0.0


def _symmetric_node_match_ratio(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
    tolerance: float,
) -> float:
    return min(_node_match_ratio(first, second, tolerance), _node_match_ratio(second, first, tolerance))


def _node_match_ratio(
    first: Sequence[tuple[float, float]],
    second: Sequence[tuple[float, float]],
    tolerance: float,
) -> float:
    if not first or not second:
        return 0.0
    tol = abs(float(tolerance))
    if tol <= 1.0e-12:
        exact_points = {(float(x), float(y)) for x, y in second}
        if tol == 0.0:
            return sum((float(x), float(y)) in exact_points for x, y in first) / len(first)
        matched = sum(
            (float(x), float(y)) in exact_points
            or any(hypot(float(x) - float(sx), float(y) - float(sy)) <= tol for sx, sy in second)
            for x, y in first
        )
        return matched / len(first)

    buckets: dict[tuple[int, int], list[tuple[float, float]]] = {}
    for sx, sy in second:
        point = (float(sx), float(sy))
        key = (floor(point[0] / tol), floor(point[1] / tol))
        buckets.setdefault(key, []).append(point)

    matched = 0
    for x, y in first:
        px, py = float(x), float(y)
        bucket_x, bucket_y = floor(px / tol), floor(py / tol)
        found = False
        for dx in (-1, 0, 1):
            if found:
                break
            for dy in (-1, 0, 1):
                if any(hypot(px - sx, py - sy) <= tol for sx, sy in buckets.get((bucket_x + dx, bucket_y + dy), ())):
                    found = True
                    break
        if found:
            matched += 1
    return matched / len(first)


def _hatch_vertex_boundary_match_ratio(
    hatch_polygon_xy: Sequence[tuple[float, float]] | None,
    target_profile: StoryShapeProfile,
    tolerance: float,
) -> float:
    vertices = [_xy(point) for point in (hatch_polygon_xy or ()) if len(point) >= 2]
    if len(vertices) > 1 and _points_close(vertices[0], vertices[-1], tolerance):
        vertices = vertices[:-1]
    target_points = _outer_ring_points(target_profile)
    return _node_match_ratio(vertices, target_points, tolerance)


def _outer_ring_points(profile: StoryShapeProfile) -> tuple[tuple[float, float], ...]:
    points: list[tuple[float, float]] = []
    for region in profile.regions:
        points.extend(region.outer_ring_xy)
    return tuple(_dedupe_points(points))


def _dedupe_points(points: Iterable[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for x, y in points:
        key = (round(float(x), 9), round(float(y), 9))
        if key in seen:
            continue
        seen.add(key)
        result.append((float(x), float(y)))
    return result


def _same_typical_group(first: str, second: str, groups: Sequence[TypicalFloorGroup]) -> bool:
    first_group = typical_group_for_story(groups, first)
    second_group = typical_group_for_story(groups, second)
    return first_group is not None and first_group == second_group


def _region_profile_from_polygon(
    *,
    story: Story,
    polygon: Polygon,
    region_index: int,
    story_nodes: Sequence[Node],
    xy_tolerance: float,
) -> ClosedRegionProfile:
    clean = orient(_clean_polygon(polygon), sign=1.0)
    coords = tuple((float(x), float(y)) for x, y in list(clean.exterior.coords)[:-1])
    node_ids = tuple(_nearest_node_ids(coords, story_nodes, xy_tolerance))
    centroid = clean.centroid
    return ClosedRegionProfile(
        story_name=story.name,
        story_elevation=float(story.elevation),
        region_id=f"{story.name}:{region_index}",
        outer_ring_node_ids=node_ids,
        outer_ring_xy=coords,
        area=float(clean.area),
        perimeter=float(clean.exterior.length),
        centroid=(float(centroid.x), float(centroid.y)),
        bbox=tuple(float(value) for value in clean.bounds),
        warning_codes=() if len(node_ids) == len(coords) else ("BOUNDARY_NODE_SNAP_INCOMPLETE",),
    )


def _nearest_node_ids(
    coords: Sequence[tuple[float, float]],
    story_nodes: Sequence[Node],
    xy_tolerance: float,
) -> list[int]:
    ids: list[int] = []
    seen: set[int] = set()
    for x, y in coords:
        if not story_nodes:
            continue
        best = min(story_nodes, key=lambda node: (float(node.x) - x) ** 2 + (float(node.y) - y) ** 2)
        if hypot(float(best.x) - x, float(best.y) - y) > xy_tolerance:
            continue
        if int(best.node_id) in seen:
            continue
        seen.add(int(best.node_id))
        ids.append(int(best.node_id))
    return ids


def _polygon_from_nodes(nodes: Sequence[Node]) -> Polygon | None:
    coords = _dedupe_points((float(node.x), float(node.y)) for node in nodes)
    if len(coords) < 3:
        return None
    polygon = _clean_polygon(Polygon(coords))
    return polygon if _usable_polygon(polygon) else None


def _polygon_from_region(region: ClosedRegionProfile) -> Polygon:
    return _clean_polygon(Polygon(region.outer_ring_xy))


def _line_from_nodes(start: Node, end: Node) -> LineString | None:
    if hypot(float(end.x) - float(start.x), float(end.y) - float(start.y)) <= 1.0e-12:
        return None
    return LineString([(float(start.x), float(start.y)), (float(end.x), float(end.y))])


def _polygonal_union(polygons: Sequence[Polygon]):
    if not polygons:
        return GeometryCollection()
    try:
        return unary_union(polygons)
    except Exception:
        cleaned = [_clean_polygon(polygon) for polygon in polygons]
        cleaned = [polygon for polygon in cleaned if _usable_polygon(polygon)]
        return unary_union(cleaned) if cleaned else GeometryCollection()


def _iter_polygons(geometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        return [item for item in geometry.geoms if isinstance(item, Polygon)]
    return []


def _clean_polygon(polygon: Polygon) -> Polygon:
    if polygon.is_empty:
        return polygon
    if polygon.is_valid:
        return polygon
    cleaned = polygon.buffer(0)
    if isinstance(cleaned, Polygon):
        return cleaned
    polygons = _iter_polygons(cleaned)
    if not polygons:
        return Polygon()
    return max(polygons, key=lambda item: item.area)


def _usable_polygon(polygon) -> bool:
    return isinstance(polygon, Polygon) and not polygon.is_empty and polygon.area > 1.0e-12 and polygon.is_valid


def _normal_element_type(value: str) -> str:
    return "".join(str(value or "").upper().replace("-", "_").split())


def _similarity_reason(score: float) -> str:
    if score >= 0.90:
        return "IDENTICAL_OR_NEAR_IDENTICAL"
    if score >= 0.82:
        return "SIMILAR_REPEATED_FLOOR"
    if score >= 0.70:
        return "PARTIAL_SIMILARITY_REVIEW"
    return "DIFFERENT_OR_TRANSITION"


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 1.0e-12:
        return 0.0
    return float(numerator) / float(denominator)


def _clamp01(value: float) -> float:
    return max(0.0, min(float(value), 1.0))


def _effective_xy_tolerance(value: float | None) -> float:
    if value is None:
        return 0.005
    return max(abs(float(value)), 1.0e-9)


def _effective_continuous_xy_tolerance(value: float | None) -> float:
    return max(_effective_xy_tolerance(value), 0.02)


def _xy(point) -> tuple[float, float]:
    return (float(point[0]), float(point[1]))


def _points_close(first: tuple[float, float], second: tuple[float, float], tolerance: float) -> bool:
    return hypot(first[0] - second[0], first[1] - second[1]) <= abs(float(tolerance))
