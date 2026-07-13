from __future__ import annotations

from collections import Counter, deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Sequence
import csv
import io
import math
import re

from shapely.affinity import rotate, translate
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, Point, Polygon, box

from .mgt_parser import (
    Element,
    Node,
    ParsedMaterial,
    ParsedSection,
    parse_elastic_links_from_text,
    parse_elements_from_text,
    parse_frame_releases_from_text,
    parse_materials_from_text,
    parse_nodes_from_text,
    parse_sections_from_text,
    parse_stories_from_text,
    parse_unit_from_text,
    section_display_size_by_id_from_text,
    select_nodes_by_story,
)


FRAME_TYPES = {"BEAM", "COLUMN", "TRUSS", "TENSTR", "COMPTR"}
LINE_SOURCE_TYPES = {"BEAM", "TRUSS", "TENSTR", "COMPTR"}
SURFACE_SOURCE_TYPES = {"WALL", "PLATE", "PLANE", "PLANAR", "QUAD", "SHELL", "SLAB"}
SOURCE_TYPES = LINE_SOURCE_TYPES | SURFACE_SOURCE_TYPES
LOAD_DM_NAME = "LOAD DM"
EXACT_LOAD_DM_KEY = "LOADDM"
DM_ID_MIN = 9900
DM_ID_MAX = 9999


@dataclass(frozen=True)
class DummyCandidate:
    story_name: str
    region_id: str
    load_type_name: str
    free_node_id: int
    source_element_ids: tuple[int, ...]
    boundary_node_ids: tuple[int, ...]
    reason: str


@dataclass(frozen=True)
class DummyMemberRecord:
    story_name: str
    region_id: str
    load_type_name: str
    free_node_id: int
    boundary_node_id: int | None
    dummy_element_id: int | None
    material_id: int | None
    section_id: int | None
    distance: float | None
    status: str
    skip_reason: str
    interference_reason: str
    source_element_ids: tuple[int, ...]
    release_added: bool


@dataclass(frozen=True)
class DummyGenerationSummary:
    created_count: int
    skipped_count: int
    reused_count: int
    release_added_count: int
    material_id: int | None
    section_id: int | None
    records: tuple[DummyMemberRecord, ...]
    warnings: tuple[str, ...]
    patched_text: str


@dataclass(frozen=True)
class _LoadDmResource:
    resource_id: int | None
    record_line: str
    warning: str


@dataclass(frozen=True)
class _CandidateScore:
    node_id: int
    source_element_ids: tuple[int, ...]
    structural_degree: int
    source_element_count: int
    distance_to_boundary: float
    is_true_leaf: bool
    selectable: bool
    reason: str


@dataclass(frozen=True)
class _TargetRegion:
    story_name: str
    region_id: str
    load_type_name: str
    node_ids: tuple[int, ...]
    polygon_vertices: tuple[tuple[float, float], ...]
    status: str


def generate_load_dm_dummy_members(
    *,
    mgt_text: str,
    assignments: Sequence[object] | None = None,
    planned_regions: Sequence[object] | None = None,
    approved_plans: Sequence[object] | None = None,
    story_tolerance: float = 1.0e-4,
    snap_tolerance: float = 0.5,
    geometry_tolerance: float = 1.0e-6,
    min_dummy_length: float = 1.0e-5,
    max_dummy_length: float | None = None,
    clearance: float | None = None,
    require_structural_boundary_support: bool = True,
    enabled: bool = True,
) -> DummyGenerationSummary:
    if not enabled:
        return DummyGenerationSummary(0, 0, 0, 0, None, None, tuple(), ("LOAD_DM_DUMMY_DISABLED",), mgt_text)
    if approved_plans is not None:
        return _generate_approved_load_dm_members(
            mgt_text=mgt_text,
            approved_plans=approved_plans,
            story_tolerance=story_tolerance,
            geometry_tolerance=geometry_tolerance,
            min_dummy_length=min_dummy_length,
            max_dummy_length=max_dummy_length,
            clearance=clearance,
            require_structural_boundary_support=require_structural_boundary_support,
        )

    nodes = parse_nodes_from_text(mgt_text)
    elements = parse_elements_from_text(mgt_text)
    stories = parse_stories_from_text(mgt_text)
    materials = parse_materials_from_text(mgt_text)
    sections = parse_sections_from_text(mgt_text)
    elastic_links = parse_elastic_links_from_text(mgt_text)
    existing_releases = {release.element_id for release in parse_frame_releases_from_text(mgt_text)}
    section_sizes = section_display_size_by_id_from_text(mgt_text)
    unit_info = parse_unit_from_text(mgt_text)
    model_clearance = _model_clearance(clearance, getattr(unit_info, "length", ""))
    effective_max_length = _model_max_dummy_length(max_dummy_length, getattr(unit_info, "length", ""))

    node_by_id = {node.node_id: node for node in nodes}
    story_by_name = {story.name: story for story in stories}
    element_by_id = {element.elem_id: element for element in elements}
    existing_dummy_pairs = _existing_dummy_pairs(elements, materials, sections)
    dummy_element_ids = _dummy_like_element_ids(elements, materials, sections)
    graph = _build_structural_graph(elements, dummy_element_ids)
    elastic_graph = _build_elastic_graph(elastic_links, node_by_id)
    targets = _normalize_targets(assignments=assignments, planned_regions=planned_regions)
    records: list[DummyMemberRecord] = []
    warnings: list[str] = []

    material_resource: _LoadDmResource | None = None
    section_resource: _LoadDmResource | None = None
    next_element_id = _first_available_id((element.elem_id for element in elements), start=max((element.elem_id for element in elements), default=0) + 1)
    used_element_ids = {element.elem_id for element in elements}
    element_records: list[str] = []
    release_records: list[str] = []

    for target in targets:
        if not _target_status_is_valid(target.status):
            records.append(_skipped_record(target, None, "INVALID_ASSIGNMENT_STATUS", "", tuple()))
            continue
        if not target.story_name or target.story_name not in story_by_name:
            records.append(_skipped_record(target, None, "STORY_NOT_DETECTED", "", tuple()))
            continue
        story = story_by_name[target.story_name]
        story_nodes = select_nodes_by_story(nodes, story.elevation, story_tolerance)
        story_node_by_id = {node.node_id: node for node in story_nodes}
        if not story_nodes:
            records.append(_skipped_record(target, None, "STORY_NODE_SET_MISSING", "", tuple()))
            continue

        polygon = _polygon_for_target(target, node_by_id, geometry_tolerance)
        if polygon is None:
            records.append(_skipped_record(target, None, "INVALID_REGION_POLYGON", "", tuple()))
            continue
        boundary_node_ids = _boundary_node_ids_for_target(
            target,
            polygon,
            story_nodes,
            node_by_id,
            snap_tolerance=snap_tolerance,
            geometry_tolerance=geometry_tolerance,
        )
        if len(boundary_node_ids) < 3:
            records.append(_skipped_record(target, None, "TOO_FEW_BOUNDARY_NODES", "", tuple()))
            continue
        support_node_ids = _elastic_support_node_ids(
            polygon,
            story_nodes,
            boundary_node_ids,
            snap_tolerance=snap_tolerance,
            geometry_tolerance=geometry_tolerance,
        )

        candidates = _find_dummy_candidates(
            target=target,
            polygon=polygon,
            story_node_by_id=story_node_by_id,
            elements=elements,
            graph=graph,
            boundary_node_ids=boundary_node_ids,
            dummy_element_ids=dummy_element_ids,
            snap_tolerance=snap_tolerance,
            geometry_tolerance=geometry_tolerance,
        )
        if not candidates:
            records.append(_skipped_record(target, None, "NO_INTERNAL_FREE_NODE", "", tuple()))
            continue

        member_geometries = _member_geometries_for_story(
            elements,
            node_by_id,
            set(story_node_by_id),
            excluded_element_ids=dummy_element_ids,
            section_sizes=section_sizes,
            clearance=model_clearance,
            story_tolerance=story_tolerance,
        )
        for candidate in candidates:
            candidate_support_node_ids = tuple(node_id for node_id in support_node_ids if node_id != candidate.free_node_id)
            if _has_elastic_path(candidate.free_node_id, candidate_support_node_ids, elastic_graph, max_depth=3):
                records.append(
                    _record_for_candidate(
                        candidate,
                        boundary_node_id=None,
                        dummy_element_id=None,
                        material_id=None,
                        section_id=None,
                        distance=None,
                        status="SKIPPED",
                        skip_reason="SUPPORTED_BY_ELASTIC_LINK",
                        interference_reason="",
                        release_added=False,
                    )
                )
                continue

            boundary_choice, distance, interference_reason = _select_clear_boundary_node(
                candidate,
                polygon,
                boundary_node_ids,
                node_by_id,
                member_geometries,
                existing_dummy_pairs,
                graph=graph,
                dummy_element_ids=dummy_element_ids,
                require_structural_boundary_support=require_structural_boundary_support,
                geometry_tolerance=geometry_tolerance,
                min_dummy_length=min_dummy_length,
                max_dummy_length=effective_max_length,
            )
            if boundary_choice is None:
                records.append(
                    _record_for_candidate(
                        candidate,
                        boundary_node_id=None,
                        dummy_element_id=None,
                        material_id=None,
                        section_id=None,
                        distance=None,
                        status="SKIPPED",
                        skip_reason="NO_CLEAR_BOUNDARY_PATH",
                        interference_reason=interference_reason,
                        release_added=False,
                    )
                )
                continue

            pair = frozenset((candidate.free_node_id, boundary_choice))
            if pair in existing_dummy_pairs:
                existing_element_id = existing_dummy_pairs[pair]
                records.append(
                    _record_for_candidate(
                        candidate,
                        boundary_node_id=boundary_choice,
                        dummy_element_id=existing_element_id,
                        material_id=None,
                        section_id=None,
                        distance=distance,
                        status="REUSED",
                        skip_reason="EXISTING_LOAD_DM_DUMMY",
                        interference_reason="",
                        release_added=existing_element_id in existing_releases,
                    )
                )
                continue

            if material_resource is None:
                material_resource = _resolve_load_dm_material(materials)
                if material_resource.warning:
                    warnings.append(material_resource.warning)
            if section_resource is None:
                section_resource = _resolve_load_dm_section(sections)
                if section_resource.warning:
                    warnings.append(section_resource.warning)
            if material_resource.resource_id is None or section_resource.resource_id is None:
                reason = "DM_MATERIAL_NOT_FOUND" if material_resource.resource_id is None else "DM_SECTION_NOT_FOUND"
                records.append(
                    _record_for_candidate(
                        candidate,
                        boundary_node_id=boundary_choice,
                        dummy_element_id=None,
                        material_id=material_resource.resource_id,
                        section_id=section_resource.resource_id,
                        distance=distance,
                        status="SKIPPED",
                        skip_reason=reason,
                        interference_reason="",
                        release_added=False,
                    )
                )
                continue

            dummy_element_id = _first_available_id(used_element_ids, start=next_element_id)
            used_element_ids.add(dummy_element_id)
            next_element_id = dummy_element_id + 1
            element_records.append(
                f"   {dummy_element_id}, BEAM, {material_resource.resource_id}, {section_resource.resource_id}, "
                f"{candidate.free_node_id}, {boundary_choice}, 0, 0"
            )
            release_records.extend(_frame_release_record_lines(dummy_element_id))
            records.append(
                _record_for_candidate(
                    candidate,
                    boundary_node_id=boundary_choice,
                    dummy_element_id=dummy_element_id,
                    material_id=material_resource.resource_id,
                    section_id=section_resource.resource_id,
                    distance=distance,
                    status="CREATED",
                    skip_reason="",
                    interference_reason="",
                    release_added=True,
                )
            )
            member_geometries.append(
                _GeometryRecord(
                    element_id=dummy_element_id,
                    geometry=LineString([node_by_id[candidate.free_node_id].xy, node_by_id[boundary_choice].xy]).buffer(model_clearance),
                    node_ids=(candidate.free_node_id, boundary_choice),
                    endpoint_allowance=model_clearance,
                )
            )

    material_records = [material_resource.record_line] if material_resource and material_resource.record_line and element_records else []
    section_records = [section_resource.record_line] if section_resource and section_resource.record_line and element_records else []
    patched_text = _patch_mgt_text(
        mgt_text,
        material_records=material_records,
        section_records=section_records,
        element_records=element_records,
        frame_release_records=release_records,
    )
    validation_errors = _validate_generated_patch(
        patched_text,
        records,
        material_id=material_resource.resource_id if material_resource else None,
        section_id=section_resource.resource_id if section_resource else None,
    )
    if validation_errors:
        warnings.extend(validation_errors)
        records = [
            replace_record_for_patch_rollback(record, ";".join(validation_errors)) if record.status == "CREATED" else record
            for record in records
        ]
        patched_text = mgt_text
    created_count = sum(1 for record in records if record.status == "CREATED")
    skipped_count = sum(1 for record in records if record.status == "SKIPPED")
    reused_count = sum(1 for record in records if record.status == "REUSED")
    release_added_count = sum(1 for record in records if record.release_added and record.status == "CREATED")
    return DummyGenerationSummary(
        created_count=created_count,
        skipped_count=skipped_count,
        reused_count=reused_count,
        release_added_count=release_added_count,
        material_id=material_resource.resource_id if material_resource else None,
        section_id=section_resource.resource_id if section_resource else None,
        records=tuple(records),
        warnings=tuple(dict.fromkeys(warnings)),
        patched_text=patched_text,
    )


def _generate_approved_load_dm_members(
    *,
    mgt_text: str,
    approved_plans: Sequence[object],
    story_tolerance: float,
    geometry_tolerance: float,
    min_dummy_length: float,
    max_dummy_length: float | None,
    clearance: float | None,
    require_structural_boundary_support: bool,
) -> DummyGenerationSummary:
    nodes = parse_nodes_from_text(mgt_text)
    elements = parse_elements_from_text(mgt_text)
    stories = parse_stories_from_text(mgt_text)
    materials = parse_materials_from_text(mgt_text)
    sections = parse_sections_from_text(mgt_text)
    section_sizes = section_display_size_by_id_from_text(mgt_text)
    unit_info = parse_unit_from_text(mgt_text)
    model_clearance = _model_clearance(clearance, getattr(unit_info, "length", ""))
    effective_max_length = _model_max_dummy_length(max_dummy_length, getattr(unit_info, "length", ""))
    node_by_id = {node.node_id: node for node in nodes}
    story_by_name = {story.name: story for story in stories}
    dummy_element_ids = _dummy_like_element_ids(elements, materials, sections)
    existing_dummy_pairs = _existing_dummy_pairs(elements, materials, sections)
    existing_releases = {release.element_id for release in parse_frame_releases_from_text(mgt_text)}
    graph = _build_structural_graph(elements, dummy_element_ids)
    used_element_ids = {element.elem_id for element in elements}
    next_element_id = max(used_element_ids, default=0) + 1
    material_resource: _LoadDmResource | None = None
    section_resource: _LoadDmResource | None = None
    element_records: list[str] = []
    release_records: list[str] = []
    records: list[DummyMemberRecord] = []
    warnings: list[str] = []
    obstacle_by_story: dict[str, list[_GeometryRecord]] = {}

    for index, plan in enumerate(tuple(approved_plans or ()), start=1):
        if not bool(getattr(plan, "approved", True)):
            continue
        story_name = str(getattr(plan, "story_name", "") or "")
        issue_key = str(getattr(plan, "issue_key", "") or f"approved-{index}")
        free_node_id = int(getattr(plan, "free_node_id", 0) or 0)
        boundary_node_id = int(getattr(plan, "boundary_node_id", 0) or 0)
        source_element_ids = tuple(int(value) for value in tuple(getattr(plan, "source_element_ids", ()) or ()))
        candidate = DummyCandidate(story_name, issue_key, "", free_node_id, source_element_ids, (boundary_node_id,), "USER_APPROVED_PLAN")
        if story_name not in story_by_name or free_node_id not in node_by_id or boundary_node_id not in node_by_id:
            records.append(_record_for_candidate(candidate, boundary_node_id=None, dummy_element_id=None, material_id=None, section_id=None, distance=None, status="SKIPPED", skip_reason="APPROVED_PLAN_NODE_OR_STORY_MISSING", interference_reason="", release_added=False))
            continue
        story = story_by_name[story_name]
        first = node_by_id[free_node_id]
        second = node_by_id[boundary_node_id]
        if abs(float(first.z) - float(story.elevation)) > story_tolerance or abs(float(second.z) - float(story.elevation)) > story_tolerance:
            records.append(_record_for_candidate(candidate, boundary_node_id=None, dummy_element_id=None, material_id=None, section_id=None, distance=None, status="SKIPPED", skip_reason="APPROVED_PLAN_NOT_SAME_STORY", interference_reason="", release_added=False))
            continue
        distance = math.hypot(second.x - first.x, second.y - first.y)
        if distance <= min_dummy_length:
            records.append(_record_for_candidate(candidate, boundary_node_id=None, dummy_element_id=None, material_id=None, section_id=None, distance=distance, status="SKIPPED", skip_reason="DUMMY_LENGTH_TOO_SHORT", interference_reason="", release_added=False))
            continue
        if distance > effective_max_length:
            records.append(_record_for_candidate(candidate, boundary_node_id=None, dummy_element_id=None, material_id=None, section_id=None, distance=distance, status="SKIPPED", skip_reason="DUMMY_LENGTH_EXCEEDS_MAXIMUM", interference_reason="", release_added=False))
            continue
        if require_structural_boundary_support and len(graph.get(boundary_node_id, set())) <= 0:
            records.append(_record_for_candidate(candidate, boundary_node_id=None, dummy_element_id=None, material_id=None, section_id=None, distance=distance, status="SKIPPED", skip_reason="BOUNDARY_NODE_NOT_STRUCTURALLY_CONNECTED", interference_reason="", release_added=False))
            continue
        pair = frozenset((free_node_id, boundary_node_id))
        if pair in existing_dummy_pairs:
            element_id = existing_dummy_pairs[pair]
            records.append(_record_for_candidate(candidate, boundary_node_id=boundary_node_id, dummy_element_id=element_id, material_id=None, section_id=None, distance=distance, status="REUSED", skip_reason="EXISTING_LOAD_DM_DUMMY", interference_reason="", release_added=element_id in existing_releases))
            continue
        if story_name not in obstacle_by_story:
            story_node_ids = {node.node_id for node in select_nodes_by_story(nodes, story.elevation, story_tolerance)}
            obstacle_by_story[story_name] = _member_geometries_for_story(
                elements,
                node_by_id,
                story_node_ids,
                excluded_element_ids=dummy_element_ids,
                section_sizes=section_sizes,
                clearance=model_clearance,
                story_tolerance=story_tolerance,
            )
        line = LineString([first.xy, second.xy])
        interference = _line_interference_reason(
            line,
            obstacle_by_story[story_name],
            free_node_id=free_node_id,
            boundary_node_id=boundary_node_id,
            node_by_id=node_by_id,
            geometry_tolerance=geometry_tolerance,
        )
        if interference:
            records.append(_record_for_candidate(candidate, boundary_node_id=None, dummy_element_id=None, material_id=None, section_id=None, distance=distance, status="SKIPPED", skip_reason="NO_CLEAR_BOUNDARY_PATH", interference_reason=interference, release_added=False))
            continue
        if material_resource is None:
            material_resource = _resolve_load_dm_material(materials)
            if material_resource.warning:
                warnings.append(material_resource.warning)
        if section_resource is None:
            section_resource = _resolve_load_dm_section(sections)
            if section_resource.warning:
                warnings.append(section_resource.warning)
        if material_resource.resource_id is None or section_resource.resource_id is None:
            reason = "DM_MATERIAL_NOT_FOUND" if material_resource.resource_id is None else "DM_SECTION_NOT_FOUND"
            records.append(_record_for_candidate(candidate, boundary_node_id=None, dummy_element_id=None, material_id=material_resource.resource_id, section_id=section_resource.resource_id, distance=distance, status="SKIPPED", skip_reason=reason, interference_reason="", release_added=False))
            continue
        element_id = _first_available_id(used_element_ids, start=next_element_id)
        used_element_ids.add(element_id)
        next_element_id = element_id + 1
        element_records.append(f"   {element_id}, BEAM, {material_resource.resource_id}, {section_resource.resource_id}, {free_node_id}, {boundary_node_id}, 0, 0")
        release_records.extend(_frame_release_record_lines(element_id))
        records.append(_record_for_candidate(candidate, boundary_node_id=boundary_node_id, dummy_element_id=element_id, material_id=material_resource.resource_id, section_id=section_resource.resource_id, distance=distance, status="CREATED", skip_reason="", interference_reason="", release_added=True))
        obstacle_by_story[story_name].append(_GeometryRecord(element_id, line.buffer(model_clearance), (free_node_id, boundary_node_id), model_clearance))

    material_records = [material_resource.record_line] if material_resource and material_resource.record_line and element_records else []
    section_records = [section_resource.record_line] if section_resource and section_resource.record_line and element_records else []
    patched_text = _patch_mgt_text(mgt_text, material_records=material_records, section_records=section_records, element_records=element_records, frame_release_records=release_records)
    validation_errors = _validate_generated_patch(patched_text, records, material_id=material_resource.resource_id if material_resource else None, section_id=section_resource.resource_id if section_resource else None)
    if validation_errors:
        warnings.extend(validation_errors)
        records = [replace_record_for_patch_rollback(record, ";".join(validation_errors)) if record.status == "CREATED" else record for record in records]
        patched_text = mgt_text
    return DummyGenerationSummary(
        created_count=sum(record.status == "CREATED" for record in records),
        skipped_count=sum(record.status == "SKIPPED" for record in records),
        reused_count=sum(record.status == "REUSED" for record in records),
        release_added_count=sum(record.status == "CREATED" and record.release_added for record in records),
        material_id=material_resource.resource_id if material_resource else None,
        section_id=section_resource.resource_id if section_resource else None,
        records=tuple(records),
        warnings=tuple(dict.fromkeys(warnings)),
        patched_text=patched_text,
    )


def write_dummy_member_report(
    summary: DummyGenerationSummary,
    output_dir: str | Path,
    *,
    model_name: str,
    story_name: str,
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{Path(model_name).stem}_{story_name}_load_dm_dummy_report.csv"
    rows = [asdict(record) for record in summary.records]
    for row in rows:
        row["source_element_ids"] = ",".join(str(value) for value in row["source_element_ids"])
    if rows:
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    else:
        path.write_text("status,skip_reason\n", encoding="utf-8-sig")
    return path


def format_dummy_generation_summary(summary: DummyGenerationSummary) -> str:
    reasons = Counter(record.skip_reason for record in summary.records if record.status == "SKIPPED" and record.skip_reason)
    reason_text = ", ".join(f"{name}={count}" for name, count in reasons.most_common(5)) or "none"
    return (
        f"LOAD DM dummy created={summary.created_count}, reused={summary.reused_count}, skipped={summary.skipped_count}, "
        f"material={summary.material_id or '-'}, section={summary.section_id or '-'}, "
        f"frame_release={summary.release_added_count}, skip_reasons={reason_text}"
    )


def replace_record_for_patch_rollback(record: DummyMemberRecord, reason: str) -> DummyMemberRecord:
    return DummyMemberRecord(
        story_name=record.story_name,
        region_id=record.region_id,
        load_type_name=record.load_type_name,
        free_node_id=record.free_node_id,
        boundary_node_id=record.boundary_node_id,
        dummy_element_id=None,
        material_id=None,
        section_id=None,
        distance=record.distance,
        status="SKIPPED",
        skip_reason="POST_PATCH_VALIDATION_FAILED",
        interference_reason=str(reason or ""),
        source_element_ids=record.source_element_ids,
        release_added=False,
    )


def _validate_generated_patch(
    patched_text: str,
    records: Sequence[DummyMemberRecord],
    *,
    material_id: int | None,
    section_id: int | None,
) -> tuple[str, ...]:
    created = [record for record in records if record.status == "CREATED" and record.dummy_element_id is not None]
    if not created:
        return ()
    errors: list[str] = []
    material_ids = {item.material_id for item in parse_materials_from_text(patched_text)}
    section_ids = {item.section_id for item in parse_sections_from_text(patched_text)}
    elements = {item.elem_id: item for item in parse_elements_from_text(patched_text)}
    releases = {item.element_id: item for item in parse_frame_releases_from_text(patched_text)}
    if material_id is None or int(material_id) not in material_ids:
        errors.append("POST_PATCH_LOAD_DM_MATERIAL_MISSING")
    if section_id is None or int(section_id) not in section_ids:
        errors.append("POST_PATCH_LOAD_DM_SECTION_MISSING")
    for record in created:
        element = elements.get(int(record.dummy_element_id))
        if element is None:
            errors.append(f"POST_PATCH_ELEMENT_MISSING:{record.dummy_element_id}")
            continue
        if tuple(element.node_ids[:2]) != (record.free_node_id, record.boundary_node_id):
            errors.append(f"POST_PATCH_ELEMENT_NODE_MISMATCH:{record.dummy_element_id}")
        release = releases.get(int(record.dummy_element_id))
        if release is None or sum("000011" in line for line in release.raw_lines) < 2:
            errors.append(f"POST_PATCH_FRAME_RELEASE_INVALID:{record.dummy_element_id}")
    return tuple(dict.fromkeys(errors))


def _model_clearance(value: float | None, length_unit: str) -> float:
    if value is not None:
        return max(float(value), 0.0)
    unit = str(length_unit or "").upper()
    if unit in {"MM", "MILLIMETER", "MILLIMETRE"}:
        return 15.0
    if unit == "CM":
        return 1.5
    return 0.015


def _model_max_dummy_length(value: float | None, length_unit: str) -> float:
    if value is not None:
        return max(float(value), 0.0)
    unit = str(length_unit or "").upper()
    if unit in {"MM", "MILLIMETER", "MILLIMETRE"}:
        return 30000.0
    if unit == "CM":
        return 3000.0
    return 30.0


@dataclass(frozen=True)
class _GeometryRecord:
    element_id: int
    geometry: object
    node_ids: tuple[int, ...] = ()
    endpoint_allowance: float = 0.0


def _normalize_targets(
    *,
    assignments: Sequence[object] | None,
    planned_regions: Sequence[object] | None,
) -> list[_TargetRegion]:
    targets: list[_TargetRegion] = []
    for index, item in enumerate(assignments or (), start=1):
        node_ids = tuple(int(value) for value in (getattr(item, "node_ids", ()) or ()) if int(value) > 0)
        vertices = tuple((float(x), float(y)) for x, y in (getattr(item, "polygon_vertices", ()) or ()))
        region_id = str(getattr(item, "source_id", "") or getattr(item, "merge_group_id", "") or f"assignment-{index}")
        targets.append(
            _TargetRegion(
                story_name=str(getattr(item, "story_name", "") or ""),
                region_id=region_id,
                load_type_name=str(getattr(item, "load_type_name", "") or ""),
                node_ids=node_ids,
                polygon_vertices=vertices,
                status=str(getattr(item, "status", "") or "OK"),
            )
        )
    for index, item in enumerate(planned_regions or (), start=1):
        region = getattr(item, "region", item)
        load = getattr(item, "load", None)
        vertices = tuple((float(x), float(y)) for x, y in (getattr(region, "vertices", ()) or ()))
        load_name = str(
            getattr(load, "floor_load_type_name", "")
            or getattr(load, "real_name", "")
            or getattr(load, "name", "")
            or ""
        )
        targets.append(
            _TargetRegion(
                story_name=str(getattr(region, "story_name", "") or ""),
                region_id=str(getattr(region, "source_id", "") or f"region-{index}"),
                load_type_name=load_name,
                node_ids=tuple(),
                polygon_vertices=vertices,
                status=str(getattr(item, "status", "") or "OK"),
            )
        )
    return targets


def _target_status_is_valid(status: str) -> bool:
    value = str(status or "").upper()
    return value in {"", "OK", "READY", "VALID", "REVIEW"} or value.startswith("REVIEW_")


def _polygon_for_target(target: _TargetRegion, node_by_id: dict[int, Node], geometry_tolerance: float) -> Polygon | None:
    vertices = list(target.polygon_vertices)
    if not vertices and target.node_ids:
        vertices = [node_by_id[node_id].xy for node_id in target.node_ids if node_id in node_by_id]
    if len(vertices) < 3:
        return None
    polygon = Polygon(vertices)
    if polygon.is_empty or polygon.area <= geometry_tolerance * geometry_tolerance or not polygon.is_valid:
        return None
    return polygon


def _boundary_node_ids_for_target(
    target: _TargetRegion,
    polygon: Polygon,
    story_nodes: Sequence[Node],
    node_by_id: dict[int, Node],
    *,
    snap_tolerance: float,
    geometry_tolerance: float,
) -> tuple[int, ...]:
    ordered: list[int] = []
    seen: set[int] = set()
    for node_id in target.node_ids:
        node = node_by_id.get(node_id)
        if node is None:
            continue
        if Point(node.x, node.y).distance(polygon.boundary) <= max(abs(snap_tolerance), geometry_tolerance):
            ordered.append(node_id)
            seen.add(node_id)
    for x, y in target.polygon_vertices:
        nearest = min(story_nodes, key=lambda node: (node.x - x) ** 2 + (node.y - y) ** 2)
        if nearest.node_id not in seen and math.hypot(nearest.x - x, nearest.y - y) <= abs(float(snap_tolerance)):
            ordered.append(nearest.node_id)
            seen.add(nearest.node_id)
    boundary_tol = max(min(abs(float(snap_tolerance)), 1.0e-3), geometry_tolerance)
    for node in story_nodes:
        if node.node_id not in seen and Point(node.x, node.y).distance(polygon.boundary) <= boundary_tol:
            ordered.append(node.node_id)
            seen.add(node.node_id)
    return tuple(ordered)


def _elastic_support_node_ids(
    polygon: Polygon,
    story_nodes: Sequence[Node],
    boundary_node_ids: Sequence[int],
    *,
    snap_tolerance: float,
    geometry_tolerance: float,
) -> tuple[int, ...]:
    support = set(int(node_id) for node_id in boundary_node_ids)
    boundary_near_tolerance = max(min(abs(float(snap_tolerance)), 0.5), geometry_tolerance)
    for node in story_nodes:
        if Point(node.x, node.y).distance(polygon.boundary) <= boundary_near_tolerance:
            support.add(node.node_id)
    return tuple(sorted(support))


def _find_dummy_candidates(
    *,
    target: _TargetRegion,
    polygon: Polygon,
    story_node_by_id: dict[int, Node],
    elements: Sequence[Element],
    graph: dict[int, set[int]],
    boundary_node_ids: Sequence[int],
    dummy_element_ids: set[int],
    snap_tolerance: float,
    geometry_tolerance: float,
) -> list[DummyCandidate]:
    boundary_set = set(boundary_node_ids)
    hard_boundary_set = _hard_boundary_node_ids_for_target(
        target,
        story_node_by_id,
        snap_tolerance=snap_tolerance,
        geometry_tolerance=geometry_tolerance,
    )
    boundary_near_tolerance = max(min(abs(float(snap_tolerance)), 0.5), geometry_tolerance)
    source_element_ids_by_node: dict[int, set[int]] = {}
    element_by_id = {element.elem_id: element for element in elements}
    for element in elements:
        if element.elem_id in dummy_element_ids or element.elem_type not in SOURCE_TYPES:
            continue
        for node_id in element.node_ids:
            node = story_node_by_id.get(node_id)
            if node is None or node_id in hard_boundary_set:
                continue
            point = Point(node.x, node.y)
            position = _node_region_position(node, polygon, boundary_near_tolerance)
            if position == "OUTSIDE":
                continue
            if node_id in boundary_set and position != "BOUNDARY_NEAR":
                continue
            source_element_ids_by_node.setdefault(node_id, set()).add(element.elem_id)

    scores_by_node: dict[int, _CandidateScore] = {}
    for node_id, source_element_ids in source_element_ids_by_node.items():
        source_types = {element_by_id[elem_id].elem_type for elem_id in source_element_ids if elem_id in element_by_id}
        if not source_types.intersection(SOURCE_TYPES):
            continue
        if source_types and source_types.issubset({"COLUMN"}):
            continue
        structural_degree = len(graph.get(node_id, set()))
        source_element_count = len(source_element_ids)
        is_true_leaf = structural_degree <= 1 and bool(source_types.intersection({"BEAM", "WALL"}))
        node = story_node_by_id[node_id]
        distance_to_boundary = Point(node.x, node.y).distance(polygon.boundary)
        is_boundary_near = distance_to_boundary <= boundary_near_tolerance
        source_connects_boundary = _source_connects_boundary_near(
            node_id,
            source_element_ids,
            element_by_id,
            story_node_by_id,
            polygon,
            hard_boundary_set,
            boundary_near_tolerance,
        )
        allow_surface_review = (
            structural_degree <= 2
            and bool(source_types.intersection(SURFACE_SOURCE_TYPES))
            and not bool(source_types.intersection(LINE_SOURCE_TYPES))
        )
        allow_line_connector = structural_degree <= 2 and source_element_count <= 2 and source_connects_boundary
        if not is_true_leaf and not allow_surface_review and not allow_line_connector:
            continue
        selectable = is_true_leaf or allow_surface_review or allow_line_connector
        reason = "INTERNAL_SURFACE_ENDPOINT_REVIEW"
        if is_true_leaf or allow_line_connector:
            reason = "BOUNDARY_NEAR_CANTILEVER_TIP" if is_boundary_near or source_connects_boundary else "CANTILEVER_FREE_TIP"
        scores_by_node[node_id] = _CandidateScore(
            node_id=node_id,
            source_element_ids=tuple(sorted(source_element_ids)),
            structural_degree=structural_degree,
            source_element_count=source_element_count,
            distance_to_boundary=distance_to_boundary,
            is_true_leaf=is_true_leaf,
            selectable=selectable,
            reason=reason,
        )

    if not scores_by_node:
        return []
    representatives: list[int] = []
    visited: set[int] = set()
    for node_id in sorted(scores_by_node):
        if node_id in visited:
            continue
        component: set[int] = set()
        queue: deque[int] = deque([node_id])
        visited.add(node_id)
        while queue:
            current = queue.popleft()
            component.add(current)
            for next_node in graph.get(current, set()):
                if next_node in scores_by_node and next_node not in visited:
                    visited.add(next_node)
                    queue.append(next_node)
        selectable_component = [value for value in component if scores_by_node[value].selectable]
        if selectable_component:
            representatives.append(min(selectable_component, key=lambda value: _candidate_sort_key(scores_by_node[value])))

    return [
        DummyCandidate(
            story_name=target.story_name,
            region_id=target.region_id,
            load_type_name=target.load_type_name,
            free_node_id=node_id,
            source_element_ids=scores_by_node[node_id].source_element_ids,
            boundary_node_ids=tuple(boundary_node_ids),
            reason=scores_by_node[node_id].reason,
        )
        for node_id in representatives
    ]


def _candidate_sort_key(score: _CandidateScore) -> tuple[bool, int, int, float, int]:
    return (
        not score.is_true_leaf,
        score.structural_degree,
        score.source_element_count,
        -score.distance_to_boundary,
        score.node_id,
    )


def _hard_boundary_node_ids_for_target(
    target: _TargetRegion,
    story_node_by_id: dict[int, Node],
    *,
    snap_tolerance: float,
    geometry_tolerance: float,
) -> set[int]:
    hard_boundary = {node_id for node_id in target.node_ids if node_id in story_node_by_id}
    tolerance = max(abs(float(snap_tolerance)), geometry_tolerance)
    story_nodes = list(story_node_by_id.values())
    if not story_nodes:
        return hard_boundary
    for x, y in target.polygon_vertices:
        nearest = min(story_nodes, key=lambda node: (node.x - x) ** 2 + (node.y - y) ** 2)
        if math.hypot(nearest.x - x, nearest.y - y) <= tolerance:
            hard_boundary.add(nearest.node_id)
    return hard_boundary


def _node_region_position(node: Node, polygon: Polygon, boundary_near_tolerance: float) -> str:
    point = Point(node.x, node.y)
    if polygon.contains(point):
        return "INSIDE"
    tolerance = max(abs(float(boundary_near_tolerance)), 1.0e-9)
    if point.distance(polygon.boundary) <= tolerance or polygon.buffer(tolerance).covers(point):
        return "BOUNDARY_NEAR"
    return "OUTSIDE"


def _is_leaf_endpoint(node_id: int, graph: dict[int, set[int]]) -> bool:
    return len(graph.get(node_id, set())) <= 1


def _source_connects_boundary_near(
    node_id: int,
    source_element_ids: Iterable[int],
    element_by_id: dict[int, Element],
    story_node_by_id: dict[int, Node],
    polygon: Polygon,
    hard_boundary_node_ids: set[int],
    boundary_near_tolerance: float,
) -> bool:
    for element_id in source_element_ids:
        element = element_by_id.get(element_id)
        if element is None:
            continue
        for other_id in element.node_ids:
            if other_id == node_id:
                continue
            if other_id in hard_boundary_node_ids:
                return True
            other = story_node_by_id.get(other_id)
            if other is not None and Point(other.x, other.y).distance(polygon.boundary) <= boundary_near_tolerance:
                return True
    return False


def _build_structural_graph(elements: Sequence[Element], excluded_element_ids: set[int] | None = None) -> dict[int, set[int]]:
    excluded = set(excluded_element_ids or set())
    graph: dict[int, set[int]] = {}
    for element in elements:
        if element.elem_id in excluded:
            continue
        for a, b in _element_edges(element):
            graph.setdefault(a, set()).add(b)
            graph.setdefault(b, set()).add(a)
    return graph


def _element_edges(element: Element) -> list[tuple[int, int]]:
    ids = tuple(node_id for node_id in element.node_ids if node_id > 0)
    if len(ids) < 2:
        return []
    if element.elem_type in FRAME_TYPES:
        return [(ids[0], ids[1])]
    if element.elem_type in SURFACE_SOURCE_TYPES and len(ids) >= 3:
        return [(ids[index], ids[(index + 1) % len(ids)]) for index in range(len(ids))]
    return []


def _build_elastic_graph(elastic_links, node_by_id: dict[int, Node]) -> dict[int, set[int]]:
    graph: dict[int, set[int]] = {}
    for link in elastic_links:
        if link.node_i not in node_by_id or link.node_j not in node_by_id:
            continue
        graph.setdefault(link.node_i, set()).add(link.node_j)
        graph.setdefault(link.node_j, set()).add(link.node_i)
    return graph


def _has_elastic_path(start_node_id: int, boundary_node_ids: Iterable[int], elastic_graph: dict[int, set[int]], *, max_depth: int) -> bool:
    targets = set(boundary_node_ids)
    if start_node_id in targets:
        return True
    queue: deque[tuple[int, int]] = deque([(start_node_id, 0)])
    visited = {start_node_id}
    while queue:
        current, depth = queue.popleft()
        for next_node in elastic_graph.get(current, set()):
            next_depth = depth + 1
            if next_depth > max_depth or next_node in visited:
                continue
            if next_node in targets:
                return True
            visited.add(next_node)
            queue.append((next_node, next_depth))
    return False


def _member_geometries_for_story(
    elements: Sequence[Element],
    node_by_id: dict[int, Node],
    story_node_ids: set[int],
    *,
    excluded_element_ids: set[int] | None = None,
    section_sizes: dict[int, object] | None = None,
    clearance: float = 0.0,
    story_tolerance: float = 1.0e-4,
) -> list[_GeometryRecord]:
    geometries: list[_GeometryRecord] = []
    dummy_ids = set(excluded_element_ids or set())
    sizes = section_sizes or {}
    clear = max(float(clearance), 0.0)
    for element in elements:
        if not set(element.node_ids).intersection(story_node_ids):
            continue
        element_nodes = [node_by_id[node_id] for node_id in element.node_ids if node_id in node_by_id]
        points = [node.xy for node in element_nodes]
        size = sizes.get(int(element.prop)) if element.prop is not None else None
        plan_width = float(getattr(size, "plan_width", 0.0) or 0.0)
        depth = float(getattr(size, "depth", 0.0) or 0.0)
        width = float(getattr(size, "width", 0.0) or 0.0)
        node_ids = tuple(int(value) for value in element.node_ids)
        if element.elem_id in dummy_ids and len(points) >= 2:
            geometries.append(_GeometryRecord(element.elem_id, LineString(points[:2]).buffer(clear), node_ids, clear))
            continue
        if element.elem_type == "COLUMN" and element_nodes:
            anchor = next((node for node in element_nodes if node.node_id in story_node_ids), element_nodes[0])
            footprint_width = max(width, plan_width, clear * 2.0)
            footprint_depth = max(depth, footprint_width, clear * 2.0)
            if len(points) >= 2 and math.hypot(points[1][0] - points[0][0], points[1][1] - points[0][1]) > max(clear, 1.0e-9):
                footprint = LineString(points[:2]).buffer(max(footprint_width, footprint_depth) / 2.0 + clear)
            else:
                footprint = box(-footprint_width / 2.0, -footprint_depth / 2.0, footprint_width / 2.0, footprint_depth / 2.0)
                footprint = rotate(footprint, float(getattr(element, "angle_deg", 0.0) or 0.0), origin=(0.0, 0.0), use_radians=False)
                footprint = translate(footprint, xoff=float(anchor.x), yoff=float(anchor.y)).buffer(clear)
            geometries.append(_GeometryRecord(element.elem_id, footprint, node_ids, max(footprint_width, footprint_depth) / 2.0 + clear))
            continue
        if element.elem_type in FRAME_TYPES and len(points) >= 2:
            radius = max(plan_width / 2.0, clear)
            geometries.append(_GeometryRecord(element.elem_id, LineString(points[:2]).buffer(radius), node_ids, radius * math.sqrt(2.0)))
        elif element.elem_type in SURFACE_SOURCE_TYPES and len(points) >= 2:
            z_values = [float(node.z) for node in element_nodes]
            is_horizontal = max(z_values) - min(z_values) <= max(abs(float(story_tolerance)), 1.0e-9)
            if is_horizontal and element.elem_type != "WALL":
                # A horizontal slab/plate face is a load surface, not an obstacle.
                continue
            unique_points: list[tuple[float, float]] = []
            for point in points:
                if point not in unique_points:
                    unique_points.append(point)
            if len(unique_points) < 2:
                continue
            wall_line = LineString(unique_points)
            radius = max(plan_width / 2.0, clear)
            geometries.append(_GeometryRecord(element.elem_id, wall_line.buffer(radius), node_ids, radius * math.sqrt(2.0)))
    return geometries


def _select_clear_boundary_node(
    candidate: DummyCandidate,
    polygon: Polygon,
    boundary_node_ids: Sequence[int],
    node_by_id: dict[int, Node],
    member_geometries: Sequence[_GeometryRecord],
    existing_dummy_pairs: dict[frozenset[int], int],
    *,
    graph: dict[int, set[int]],
    dummy_element_ids: set[int],
    require_structural_boundary_support: bool,
    geometry_tolerance: float,
    min_dummy_length: float,
    max_dummy_length: float,
) -> tuple[int | None, float | None, str]:
    free_node = node_by_id[candidate.free_node_id]
    ordered = sorted(
        (node_id for node_id in boundary_node_ids if node_id in node_by_id and node_id != candidate.free_node_id),
        key=lambda node_id: (math.hypot(node_by_id[node_id].x - free_node.x, node_by_id[node_id].y - free_node.y), node_id),
    )
    last_reason = ""
    for boundary_node_id in ordered:
        if require_structural_boundary_support and len(graph.get(boundary_node_id, set())) <= 0:
            last_reason = "BOUNDARY_NODE_NOT_STRUCTURALLY_CONNECTED"
            continue
        boundary_node = node_by_id[boundary_node_id]
        distance = math.hypot(boundary_node.x - free_node.x, boundary_node.y - free_node.y)
        if distance <= min_dummy_length:
            last_reason = "DUMMY_LENGTH_TOO_SHORT"
            continue
        if distance > max_dummy_length:
            last_reason = "DUMMY_LENGTH_EXCEEDS_MAXIMUM"
            continue
        pair = frozenset((candidate.free_node_id, boundary_node_id))
        if pair in existing_dummy_pairs:
            return boundary_node_id, distance, ""
        line = LineString([free_node.xy, boundary_node.xy])
        if not polygon.buffer(geometry_tolerance).covers(line):
            last_reason = "LINE_OUTSIDE_REGION"
            continue
        interference = _line_interference_reason(
            line,
            member_geometries,
            free_node_id=candidate.free_node_id,
            boundary_node_id=boundary_node_id,
            node_by_id=node_by_id,
            geometry_tolerance=geometry_tolerance,
        )
        if interference:
            last_reason = interference
            continue
        return boundary_node_id, distance, ""
    return None, None, last_reason or "NO_BOUNDARY_NODE"


def _line_interference_reason(
    line: LineString,
    member_geometries: Sequence[_GeometryRecord],
    *,
    free_node_id: int,
    boundary_node_id: int,
    node_by_id: dict[int, Node],
    geometry_tolerance: float,
) -> str:
    endpoint_points = [Point(node_by_id[free_node_id].xy), Point(node_by_id[boundary_node_id].xy)]
    for record in member_geometries:
        intersection = line.intersection(record.geometry)
        if intersection.is_empty:
            continue
        if free_node_id in record.node_ids and boundary_node_id in record.node_ids:
            return f"COINCIDENT_WITH_SOURCE_MEMBER:{record.element_id}"
        if _intersection_is_endpoint_only(intersection, endpoint_points, geometry_tolerance):
            continue
        allowed_contacts = []
        if free_node_id in record.node_ids:
            allowed_contacts.append(Point(node_by_id[free_node_id].xy).buffer(record.endpoint_allowance + geometry_tolerance))
        if boundary_node_id in record.node_ids:
            allowed_contacts.append(Point(node_by_id[boundary_node_id].xy).buffer(record.endpoint_allowance + geometry_tolerance))
        if allowed_contacts and all(contact.buffer(geometry_tolerance).covers(intersection) for contact in allowed_contacts[:1]):
            continue
        if allowed_contacts and any(contact.buffer(geometry_tolerance).covers(intersection) for contact in allowed_contacts):
            continue
        if allowed_contacts and float(getattr(intersection, "length", 0.0) or 0.0) <= max(record.endpoint_allowance * 4.0, geometry_tolerance * 10.0):
            continue
        if _intersection_has_line_overlap(intersection, geometry_tolerance):
            return f"COINCIDENT_WITH_SOURCE_MEMBER:{record.element_id}"
        return f"INTERSECTS_EXISTING_MEMBER:{record.element_id}"
    return ""


def _intersection_is_endpoint_only(intersection, endpoints: Sequence[Point], tolerance: float) -> bool:
    if isinstance(intersection, Point):
        return any(intersection.distance(endpoint) <= tolerance for endpoint in endpoints)
    if isinstance(intersection, MultiPoint):
        return all(any(point.distance(endpoint) <= tolerance for endpoint in endpoints) for point in intersection.geoms)
    if isinstance(intersection, (LineString, MultiLineString)):
        return intersection.length <= tolerance
    if isinstance(intersection, GeometryCollection):
        return all(_intersection_is_endpoint_only(geom, endpoints, tolerance) for geom in intersection.geoms)
    return False


def _intersection_has_line_overlap(intersection, tolerance: float) -> bool:
    if isinstance(intersection, LineString):
        return intersection.length > tolerance
    if isinstance(intersection, MultiLineString):
        return any(geom.length > tolerance for geom in intersection.geoms)
    if isinstance(intersection, GeometryCollection):
        return any(_intersection_has_line_overlap(geom, tolerance) for geom in intersection.geoms)
    return False


def _existing_dummy_pairs(elements: Sequence[Element], materials: Sequence[ParsedMaterial], sections: Sequence[ParsedSection]) -> dict[frozenset[int], int]:
    dummy_element_ids = _dummy_like_element_ids(elements, materials, sections)
    pairs: dict[frozenset[int], int] = {}
    for element in elements:
        if element.elem_type != "BEAM" or len(element.node_ids) < 2:
            continue
        if element.elem_id in dummy_element_ids:
            pairs[frozenset((element.node_ids[0], element.node_ids[1]))] = element.elem_id
    return pairs


def _dummy_like_element_ids(elements: Sequence[Element], materials: Sequence[ParsedMaterial], sections: Sequence[ParsedSection]) -> set[int]:
    dm_material_ids = {item.material_id for item in materials if _is_dummy_element_resource(item.name, item.material_id)}
    dm_section_ids = {item.section_id for item in sections if _is_dummy_element_resource(item.name, item.section_id)}
    dummy_element_ids: set[int] = set()
    for element in elements:
        raw_key = _name_key(element.raw)
        if (
            (element.mat is not None and element.mat in dm_material_ids)
            or (element.prop is not None and element.prop in dm_section_ids)
            or "LOADDM" in raw_key
            or "DUMMY" in raw_key
        ):
            dummy_element_ids.add(element.elem_id)
    return dummy_element_ids


def _is_dummy_element_resource(name: object, resource_id: int | None) -> bool:
    key = _name_key(name)
    if "LOADDM" in key or "DUMMY" in key:
        return True
    return key == "DM" and resource_id is not None and int(resource_id) >= DM_ID_MIN


def _resolve_load_dm_material(materials: Sequence[ParsedMaterial]) -> _LoadDmResource:
    exact = next((item for item in materials if _name_key(item.name) == EXACT_LOAD_DM_KEY), None)
    source = _select_dm_source_material(materials)
    if exact is not None and source is not None:
        if _same_resource_payload_except_id_name(exact.fields, source.fields):
            return _LoadDmResource(exact.material_id, "", "")
        return _copied_load_dm_resource(
            source.fields,
            used_ids=(item.material_id for item in materials),
            warning="LOAD_DM_MATERIAL_NAME_CONFLICT_CREATED_NEW_ID",
        )
    if exact is not None and len(exact.fields) >= 3:
        return _LoadDmResource(exact.material_id, "", "")
    if source is None:
        return _LoadDmResource(None, "", "DM_MATERIAL_NOT_FOUND")
    return _copied_load_dm_resource(source.fields, used_ids=(item.material_id for item in materials), warning="")


def _resolve_load_dm_section(sections: Sequence[ParsedSection]) -> _LoadDmResource:
    exact = next((item for item in sections if _name_key(item.name) == EXACT_LOAD_DM_KEY), None)
    source = _select_dm_source_section(sections)
    if exact is not None and source is not None:
        if _same_resource_payload_except_id_name(exact.fields, source.fields):
            return _LoadDmResource(exact.section_id, "", "")
        return _copied_load_dm_resource(
            source.fields,
            used_ids=(item.section_id for item in sections),
            warning="LOAD_DM_SECTION_NAME_CONFLICT_CREATED_NEW_ID",
        )
    if exact is not None and len(exact.fields) >= 3:
        return _LoadDmResource(exact.section_id, "", "")
    if source is None:
        return _LoadDmResource(None, "", "DM_SECTION_NOT_FOUND")
    return _copied_load_dm_resource(source.fields, used_ids=(item.section_id for item in sections), warning="")


def _select_dm_source_material(materials: Sequence[ParsedMaterial]) -> ParsedMaterial | None:
    return _select_dm_source(materials, lambda item: item.name)


def _select_dm_source_section(sections: Sequence[ParsedSection]) -> ParsedSection | None:
    return _select_dm_source(sections, lambda item: item.name)


def _select_dm_source(items: Sequence[object], name_getter) -> object | None:
    candidates = [item for item in items if _is_dm_source_name(name_getter(item))]
    if not candidates:
        return None
    return min(candidates, key=lambda item: (_dm_name_rank(name_getter(item)), getattr(item, "line_number", 0)))


def _is_dm_like_name(name: str) -> bool:
    key = _name_key(name)
    return "LOADDM" in key or "DUMMY" in key or key == "DM" or "DM" in key


def _is_dm_source_name(name: str) -> bool:
    key = _name_key(name)
    if key == EXACT_LOAD_DM_KEY:
        return False
    return "DUMMY" in key or key == "DM" or "DM" in key


def _dm_name_rank(name: str) -> int:
    key = _name_key(name)
    if key == "DM":
        return 0
    if key == "DUMMY":
        return 1
    if "DM" in key:
        return 2
    return 3


def _same_resource_payload_except_id_name(left_fields: Sequence[object], right_fields: Sequence[object]) -> bool:
    if len(left_fields) != len(right_fields):
        return False
    for index, (left, right) in enumerate(zip(left_fields, right_fields)):
        if index in {0, 2}:
            continue
        if str(left).strip() != str(right).strip():
            return False
    return True


def _copied_load_dm_resource(fields: Sequence[object], *, used_ids: Iterable[int], warning: str) -> _LoadDmResource:
    if len(fields) < 3:
        return _LoadDmResource(None, "", warning or "DM_SOURCE_INVALID")
    new_id = _descending_available_id(used_ids)
    copied = list(fields)
    copied[0] = str(new_id)
    copied[2] = LOAD_DM_NAME
    return _LoadDmResource(new_id, "   " + ", ".join(_mgt_field(value) for value in copied), warning)


def _name_key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _descending_available_id(used_ids: Iterable[int]) -> int:
    used = {int(value) for value in used_ids}
    for value in range(DM_ID_MAX, DM_ID_MIN - 1, -1):
        if value not in used:
            return value
    raise RuntimeError("No available LOAD DM material/section id from 9999 down to 9900.")


def _first_available_id(used_ids: Iterable[int], *, start: int) -> int:
    used = {int(value) for value in used_ids}
    value = max(1, int(start))
    while value in used:
        value += 1
    return value


def _frame_release_record_lines(element_id: int) -> list[str]:
    return [
        f"   {element_id}, NO, 000011, 0, 0, 0, 0, 0, 0",
        "        000011, 0, 0, 0, 0, 0, 0,",
    ]


def _patch_mgt_text(
    text: str,
    *,
    material_records: Sequence[str],
    section_records: Sequence[str],
    element_records: Sequence[str],
    frame_release_records: Sequence[str],
) -> str:
    if not material_records and not section_records and not element_records and not frame_release_records:
        return text
    lines = text.splitlines()
    lines = _insert_records_into_section(
        lines,
        section_name="*MATERIAL",
        header_lines=["*MATERIAL    ; Material", "; iMAT, TYPE, MNAME, ..."],
        records=material_records,
        before_section="*SECTION",
    )
    lines = _insert_records_into_section(
        lines,
        section_name="*SECTION",
        header_lines=["*SECTION    ; Section", "; iSEC, TYPE, SNAME, ..."],
        records=section_records,
        before_section="*ELEMENT",
    )
    lines = _insert_records_into_section(
        lines,
        section_name="*ELEMENT",
        header_lines=["*ELEMENT    ; Elements", "; iEL, TYPE, iMAT, iPRO, iN1, iN2, ANGLE, iSUB"],
        records=element_records,
        before_section="*FRAME-RLS",
    )
    lines = _insert_records_into_section(
        lines,
        section_name="*FRAME-RLS",
        header_lines=[
            "*FRAME-RLS    ; Beam End Release",
            "; ELEM_LIST, bVALUE, FLAG-i, Fxi, Fyi, Fzi, Mxi, Myi, Mzi",
            ";           FLAG-j, Fxj, Fyj, Fzj, Mxj, Myj, Mzj, GROUP",
        ],
        records=frame_release_records,
        before_section="*ENDDATA",
    )
    return "\r\n".join(lines) + "\r\n"


def _insert_records_into_section(
    lines: list[str],
    *,
    section_name: str,
    header_lines: Sequence[str],
    records: Sequence[str],
    before_section: str = "*ENDDATA",
) -> list[str]:
    if not records:
        return lines
    start, end = _find_section_range(lines, section_name)
    if start is not None and end is not None:
        insert_at = end
        while insert_at > start + 1 and not lines[insert_at - 1].strip():
            insert_at -= 1
        return lines[:insert_at] + list(records) + lines[insert_at:]
    insert_at = _find_section_insert_position(lines, before_section)
    block = ["", *header_lines, *records, ""]
    return lines[:insert_at] + block + lines[insert_at:]


def _find_section_range(lines: Sequence[str], section_name: str) -> tuple[int | None, int | None]:
    target = section_name.upper()
    start = None
    for index, line in enumerate(lines):
        if _section_head(line) == target:
            start = index
            break
    if start is None:
        return None, None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if _section_head(lines[index]):
            end = index
            break
    return start, end


def _find_section_insert_position(lines: Sequence[str], before_section: str) -> int:
    target = before_section.upper()
    for index, line in enumerate(lines):
        if _section_head(line) == target:
            return index
    if target != "*ENDDATA":
        for index, line in enumerate(lines):
            if _section_head(line) == "*ENDDATA":
                return index
    return len(lines)


def _section_head(line: str) -> str:
    stripped = line.strip()
    if not stripped.startswith("*"):
        return ""
    return stripped.split(None, 1)[0].upper()


def _record_for_candidate(
    candidate: DummyCandidate,
    *,
    boundary_node_id: int | None,
    dummy_element_id: int | None,
    material_id: int | None,
    section_id: int | None,
    distance: float | None,
    status: str,
    skip_reason: str,
    interference_reason: str,
    release_added: bool,
) -> DummyMemberRecord:
    return DummyMemberRecord(
        story_name=candidate.story_name,
        region_id=candidate.region_id,
        load_type_name=candidate.load_type_name,
        free_node_id=candidate.free_node_id,
        boundary_node_id=boundary_node_id,
        dummy_element_id=dummy_element_id,
        material_id=material_id,
        section_id=section_id,
        distance=distance,
        status=status,
        skip_reason=skip_reason,
        interference_reason=interference_reason,
        source_element_ids=candidate.source_element_ids,
        release_added=release_added,
    )


def _skipped_record(
    target: _TargetRegion,
    free_node_id: int | None,
    skip_reason: str,
    interference_reason: str,
    source_element_ids: tuple[int, ...],
) -> DummyMemberRecord:
    return DummyMemberRecord(
        story_name=target.story_name,
        region_id=target.region_id,
        load_type_name=target.load_type_name,
        free_node_id=int(free_node_id or 0),
        boundary_node_id=None,
        dummy_element_id=None,
        material_id=None,
        section_id=None,
        distance=None,
        status="SKIPPED",
        skip_reason=skip_reason,
        interference_reason=interference_reason,
        source_element_ids=source_element_ids,
        release_added=False,
    )


def _mgt_field(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ")
    if "," in text:
        escaped = text.replace('"', '""')
        return f'"{escaped}"'
    return text


def _csv_split(line: str) -> list[str]:
    try:
        return [cell.strip() for cell in next(csv.reader(io.StringIO(line), skipinitialspace=True))]
    except Exception:
        return [cell.strip() for cell in line.split(",")]
