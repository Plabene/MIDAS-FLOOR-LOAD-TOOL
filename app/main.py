from __future__ import annotations

import copy
import csv
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, replace
import hashlib
import inspect
import json
import math
import os
from datetime import datetime
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
import time
from types import SimpleNamespace
from typing import Iterable, Sequence
from tkinter import filedialog, messagebox, simpledialog, ttk

from shapely.geometry import LineString, Point, Polygon

try:
    # package 실행: python -m app.main
    from .core.dxf_load_reader import read_load_regions
    from .core.closed_region_detector import ExtraBoundarySegment, detect_closed_cells, write_closed_region_diagnostics
    from .core.diagnostic_dxf_writer import write_floorload_diagnostic_dxf
    from .core.dxf_template_writer import LoadLayerSpec, write_all_story_centerline_dxf, write_story_centerline_dxf
    from .core.dxf_story_layout import LayoutMetadataSelection, read_layout_metadata, select_layout_metadata
    from .core.dummy_member_generator import format_dummy_generation_summary, generate_load_dm_dummy_members
    from .core.floorload_mgt_builder import check_polygon_against_allowed_story_polygons, run_mgt_build_pipeline
    from .core.floorload_audit_report import write_hatch_view_input_state
    from .core.hatch_region_editor import (
        EditableHatchRegion,
        HatchEditState,
        apply_load_to_selection,
        apply_load_to_selection_with_stats,
        create_edit_state,
        is_one_way_tri_or_quad,
        loaded_editable_regions,
        one_way_vertex_count,
        remove_load_from_selection,
        select_polygon_keys_by_rect,
        select_regions_by_keys,
        split_region,
    )
    from .core.load_selection import apply_load_display_names
    from .core.pdf_load_importer import (
        PdfLoadImportResult,
        detect_floor_load_presence_from_text,
        merge_pdf_mgtx_into_full_mgt,
        run_pdf_load_import,
    )
    from .core.mgt_parser import (
        FloorLoadTypeSpec,
        Story,
        dxf_unit_scale_from_model_length_unit,
        parse_floorload_type_names_from_text,
        parse_floadtype_specs_from_text,
        parse_existing_load_dm_members,
        parse_mgt_file,
        parse_unit_from_text,
        read_text,
        section_display_size_by_id_from_text,
        select_nodes_by_story,
        thickness_value_by_id_from_text,
    )
    from .core.midas_api_client import MidasApiError, MidasGenApiClient
    from .core.midas_api_client import write_import_verification_report
    from .core.mgt_import_validator import MgtPreflightError, validate_mgt_for_import, write_validation_report
    from .core.load_parser import LoadLayerInfo, make_safe_load_layer_name, parse_load_layer
    from .core.load_input_policy import DISTRIBUTION_ONE_WAY, infer_distribution, infer_short_span_angle
    from .core.model_floorload_diagnostics import analyze_floorload_model, diagnostic_issue_category, diagnostic_issue_user_text, write_diagnostic_reports
    from .core.typical_floor_detector import (
        analyze_typical_floors,
        evaluate_continuous_apply_candidates,
        split_continuous_apply_ranges,
        typical_story_names,
    )
    from .core.story_view_filter import element_is_in_story_below_range, story_below_range
    from .core.progress import ProgressReporter
    from .utils.config import AppConfig, load_config, save_config
    from .utils.logger import setup_logger
    from .utils.path_utils import (
        ensure_project_output_subdirs,
        output_root_dir,
        project_output_dir,
        project_root,
        safe_filename,
        unique_numbered_path,
        unique_output_path,
    )
except ImportError:  # 직접 실행: python app/main.py
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.core.dxf_load_reader import read_load_regions
    from app.core.closed_region_detector import ExtraBoundarySegment, detect_closed_cells, write_closed_region_diagnostics
    from app.core.diagnostic_dxf_writer import write_floorload_diagnostic_dxf
    from app.core.dxf_template_writer import LoadLayerSpec, write_all_story_centerline_dxf, write_story_centerline_dxf
    from app.core.dxf_story_layout import LayoutMetadataSelection, read_layout_metadata, select_layout_metadata
    from app.core.dummy_member_generator import format_dummy_generation_summary, generate_load_dm_dummy_members
    from app.core.floorload_mgt_builder import check_polygon_against_allowed_story_polygons, run_mgt_build_pipeline
    from app.core.floorload_audit_report import write_hatch_view_input_state
    from app.core.hatch_region_editor import (
        EditableHatchRegion,
        HatchEditState,
        apply_load_to_selection,
        apply_load_to_selection_with_stats,
        create_edit_state,
        is_one_way_tri_or_quad,
        loaded_editable_regions,
        one_way_vertex_count,
        remove_load_from_selection,
        select_polygon_keys_by_rect,
        select_regions_by_keys,
        split_region,
    )
    from app.core.load_selection import apply_load_display_names
    from app.core.pdf_load_importer import (
        PdfLoadImportResult,
        detect_floor_load_presence_from_text,
        merge_pdf_mgtx_into_full_mgt,
        run_pdf_load_import,
    )
    from app.core.mgt_parser import (
        FloorLoadTypeSpec,
        Story,
        dxf_unit_scale_from_model_length_unit,
        parse_floorload_type_names_from_text,
        parse_floadtype_specs_from_text,
        parse_existing_load_dm_members,
        parse_mgt_file,
        parse_unit_from_text,
        read_text,
        section_display_size_by_id_from_text,
        select_nodes_by_story,
        thickness_value_by_id_from_text,
    )
    from app.core.midas_api_client import MidasApiError, MidasGenApiClient
    from app.core.midas_api_client import write_import_verification_report
    from app.core.mgt_import_validator import MgtPreflightError, validate_mgt_for_import, write_validation_report
    from app.core.load_parser import LoadLayerInfo, make_safe_load_layer_name, parse_load_layer
    from app.core.load_input_policy import DISTRIBUTION_ONE_WAY, infer_distribution, infer_short_span_angle
    from app.core.model_floorload_diagnostics import analyze_floorload_model, diagnostic_issue_category, diagnostic_issue_user_text, write_diagnostic_reports
    from app.core.typical_floor_detector import (
        analyze_typical_floors,
        evaluate_continuous_apply_candidates,
        split_continuous_apply_ranges,
        typical_story_names,
    )
    from app.core.story_view_filter import element_is_in_story_below_range, story_below_range
    from app.core.progress import ProgressReporter
    from app.utils.config import AppConfig, load_config, save_config
    from app.utils.logger import setup_logger
    from app.utils.path_utils import (
        ensure_project_output_subdirs,
        output_root_dir,
        project_output_dir,
        project_root,
        safe_filename,
        unique_numbered_path,
        unique_output_path,
    )


def _mgbx_path(path: str | Path) -> Path:
    target = Path(path)
    if target.suffix.lower() != ".mgbx":
        target = target.with_suffix(".mgbx")
    return target


def _load_build_info(root: Path) -> dict[str, object]:
    path = Path(root) / "build_info.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _build_version_text(build_info: dict[str, object]) -> str:
    version = str(build_info.get("version") or "v4")
    timestamp = str(build_info.get("build_timestamp") or "source")
    git_commit = str(build_info.get("git_commit") or "unknown")
    source_hash = str(build_info.get("source_hash") or "unknown")
    dirty = " dirty" if bool(build_info.get("git_dirty")) else ""
    return f"{version} | build {timestamp} | git {git_commit}{dirty} | source {source_hash}"


ALL_STORIES_VALUE = "__ALL_STORIES__"
ALL_STORIES_LABEL = "전층"
DXF_NEXT_ACTION_BG = "#FFD966"
DXF_NEXT_ACTION_ACTIVE_BG = "#FFE699"
MODEL_NEXT_ACTION_BG = "#A9D18E"
MODEL_NEXT_ACTION_ACTIVE_BG = "#C6E0B4"
CONTINUOUS_TARGET_OUTSIDE_BELOW_ALLOWED_REGION = "CONTINUOUS_TARGET_OUTSIDE_BELOW_ALLOWED_REGION"
CONTINUOUS_TARGET_CELL_NOT_FOUND = "CONTINUOUS_TARGET_CELL_NOT_FOUND"
CONTINUOUS_TARGET_SNAP_FAILED = "CONTINUOUS_TARGET_SNAP_FAILED"
DIAGNOSTIC_PREVIEW_LINE_TYPES = {"BEAM", "TRUSS", "TENSTR", "COMPTR"}
DIAGNOSTIC_PREVIEW_WALL_TYPES = {"WALL", "PLATE", "SHELL", "SLAB", "PLANE", "PLANAR", "QUAD"}
HATCH_VIEW_STRUCTURE_LINE_TYPES = {"BEAM", "TRUSS", "TENSTR", "COMPTR"}
HATCH_VIEW_STRUCTURE_WALL_TYPES = {"WALL", "PLATE", "SHELL", "PLANE", "PLANAR", "QUAD"}
HATCH_VIEW_STRUCTURE_PLANAR_WALL_TYPES = {"PLATE", "SHELL", "PLANE", "PLANAR", "QUAD"}
HATCH_VIEW_STRUCTURE_EXCLUDED_TYPES = {
    "ELASTICLINK",
    "ELASTIC_LINK",
    "LINK",
    "ELINK",
    "LOADDM",
    "LOAD_DM",
    "LOAD-DM",
    "SLAB",
}
HATCH_VIEW_STRUCTURE_STYLE = {
    "WALL": {"outline": "#be185d", "fill": "#f9a8d4", "stipple": "gray25", "stroke_width": 2},
    "BEAM": {"outline": "#1d4ed8", "fill": "#93c5fd", "stipple": "gray25", "stroke_width": 2},
    "COLUMN": {
        "outline": "#064e3b",
        "fill": "#22c55e",
        "stipple": "gray12",
        "stroke_width": 3,
        "marker_outline": "#052e16",
        "marker_fill": "#16a34a",
    },
}


@dataclass(frozen=True)
class HatchDisplayTransform:
    story_name: str = ""
    source: str = "identity"
    scale_x: float = 1.0
    scale_y: float = 1.0
    dx: float = 0.0
    dy: float = 0.0
    layout_transform: object | None = None

    def apply(self, x: float, y: float) -> tuple[float, float]:
        if self.layout_transform is not None and hasattr(self.layout_transform, "apply"):
            return self.layout_transform.apply(float(x), float(y))
        return (float(x) * self.scale_x + self.dx, float(y) * self.scale_y + self.dy)

    @property
    def dimension_scale(self) -> float:
        scale = (abs(float(self.scale_x)) + abs(float(self.scale_y))) / 2.0
        return scale if math.isfinite(scale) and scale > 0.0 else 1.0

    def as_tuple(self) -> tuple[float, float, float, float]:
        return (float(self.scale_x), float(self.scale_y), float(self.dx), float(self.dy))


@dataclass(frozen=True)
class HatchViewEditSnapshot:
    history_session_id: int
    loaded_regions: tuple[object, ...]
    loaded_region_loads: tuple[tuple[str, object | None, str], ...]
    hatch_edit_states_by_story: dict[str, HatchEditState]
    continuous_apply_targets_by_region: dict[str, tuple[str, ...]]
    continuous_materialized_targets_by_region: dict[str, tuple[str, ...]]
    selected_region_key: str
    selected_region_keys: tuple[str, ...]
    selected_edit_region_keys: tuple[str, ...]
    continuous_active_visible_targets: tuple[str, ...]
    continuous_active_region_key: str
    continuous_active_region_keys: tuple[str, ...]
    continuous_base_story: str
    selected_dummy_issue_key: str
    dummy_preview_plan: object | None
    approved_dummy_plans: dict[str, object]
    dummy_issue_status_by_key: dict[str, str]


@dataclass(frozen=True)
class ContinuousTargetCellMatch:
    cell_ids: tuple[str, ...]
    polygon_xy: tuple[tuple[float, float], ...]
    status: str
    source_coverage: float
    target_overreach_ratio: float
    iou: float

    @property
    def ok(self) -> bool:
        return self.status == "MATCH" and bool(self.cell_ids)


@dataclass(frozen=True)
class DummyIssueViewModel:
    issue_key: str
    story_name: str
    issue_type: str
    free_node_id: int | None
    source_element_ids: tuple[int, ...]
    region_id: str
    xy: tuple[float, float]
    candidate_boundary_nodes: tuple[int, ...] = ()
    recommended_boundary_node: int | None = None
    status: str = "OPEN"
    reason_ko: str = ""
    can_generate: bool = False


@dataclass(frozen=True)
class DummyConnectionPlan:
    issue_key: str
    story_name: str
    free_node_id: int
    boundary_node_id: int
    start_xy: tuple[float, float]
    end_xy: tuple[float, float]
    length: float
    source_element_ids: tuple[int, ...] = ()
    collision_checked: bool = False
    collision_reason: str = ""
    approved: bool = False
    temporary_plan_id: str = ""
    final_element_id: int | None = None
    material_id: int | None = None
    section_id: int | None = None
    release_added: bool = False


@dataclass(frozen=True)
class DummyDisplayMember:
    display_key: str
    story_name: str
    node_i: int
    node_j: int
    start_xy: tuple[float, float]
    end_xy: tuple[float, float]
    element_id: int | None = None
    state: str = "PREVIEW"
    source: str = "USER_APPROVED_PLAN"
    issue_key: str = ""
    material_id: int | None = None
    section_id: int | None = None
    release_added: bool = False
    invalid_reason: str = ""


def _should_show_diagnostic_preview(issues) -> bool:
    return any(str(getattr(issue, "severity", "")).upper() in {"ERROR", "WARNING"} for issue in issues or [])


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(value), float(maximum)))


@dataclass(frozen=True)
class BuildPipelineUiResult:
    message: str
    generated_model_path: Path | None = None

    def __str__(self) -> str:
        return self.message


def _format_dxf_validation_summary(regions) -> str:
    total = len(regions or [])
    ok_count = sum(1 for region in regions if region.status in {"OK", "REVIEW"} or str(region.status).startswith("REVIEW_"))
    story_counts = Counter(str(getattr(region.region, "story_name", "") or "") for region in regions)
    recognized_story_count = total - story_counts.get("", 0)
    metadata_used_count = sum(1 for region in regions if bool(getattr(region.region, "layout_metadata_used", False)))
    transform_count = sum(1 for region in regions if bool(getattr(region.region, "transform_applied", False)))
    lines = [
        "DXF 검증 완료:",
        f"- 하중영역: {total}개",
        f"- 입력 가능 후보: {ok_count}개",
        f"- Story 인식: {recognized_story_count}개",
    ]
    for story_name, count in sorted((name, count) for name, count in story_counts.items() if name):
        lines.append(f"- {story_name}: {count}개")
    lines.append(f"- metadata: {'사용됨' if metadata_used_count else '미사용'}")
    if metadata_used_count:
        lines.append(f"- transform_applied: {transform_count}개")
        metadata_paths = sorted(
            {
                str(getattr(region.region, "layout_metadata_path", "") or "")
                for region in regions
                if getattr(region.region, "layout_metadata_path", "")
            }
        )
        if metadata_paths:
            lines.append(f"- metadata 경로: {metadata_paths[0]}")
    return "\n".join(lines)


def _format_region_bbox_for_ui(values) -> str:
    if not values:
        return ""
    return ",".join(f"{float(value):.3f}".rstrip("0").rstrip(".") for value in values)


def _format_scale_for_ui(value: float) -> str:
    text = f"{float(value):.6f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def update_story_check_selection(
    ordered_iids: list[str],
    candidate_by_iid: dict[str, object],
    current_selection: set[str],
    clicked_iid: str,
    anchor_iid: str | None,
    *,
    shift: bool = False,
    ctrl: bool = False,
) -> tuple[set[str], str | None]:
    if clicked_iid not in ordered_iids:
        return set(current_selection), anchor_iid
    if not _continuous_candidate_can_apply(candidate_by_iid.get(clicked_iid)):
        return set(current_selection), anchor_iid

    if shift and anchor_iid in ordered_iids:
        start = ordered_iids.index(anchor_iid)
        end = ordered_iids.index(clicked_iid)
        if start > end:
            start, end = end, start
        selected = set(current_selection)
        selected.update(
            iid
            for iid in ordered_iids[start : end + 1]
            if _continuous_candidate_can_apply(candidate_by_iid.get(iid))
        )
        return selected, anchor_iid

    selected = set(current_selection)
    if clicked_iid in selected:
        selected.remove(clicked_iid)
    else:
        selected.add(clicked_iid)
    if ctrl:
        return selected, anchor_iid or clicked_iid
    return selected, clicked_iid


def update_story_range_selection(
    ordered_iids: list[str],
    candidate_by_iid: dict[str, object],
    current_selection: set[str],
    clicked_iid: str,
    anchor_iid: str | None,
    *,
    shift: bool = False,
    ctrl: bool = False,
) -> tuple[set[str], str | None]:
    return update_story_check_selection(
        ordered_iids,
        candidate_by_iid,
        current_selection,
        clicked_iid,
        anchor_iid,
        shift=shift,
        ctrl=ctrl,
    )


CONTINUOUS_TREE_DRAG_THRESHOLD_PX = 4
CONTINUOUS_TREE_AUTOSCROLL_EDGE_PX = 24
CONTINUOUS_TREE_AUTOSCROLL_INTERVAL_MS = 80


def compute_continuous_drag_selection(
    ordered_iids: Sequence[str],
    candidate_by_iid: dict[str, object],
    initial_selection: Iterable[str],
    start_iid: str,
    current_iid: str,
    *,
    mode: str = "plain",
    anchor_iid: str | None = None,
    visible_target_names: Iterable[str] | None = None,
) -> set[str]:
    ordered = [str(iid) for iid in ordered_iids]
    initial = {str(iid) for iid in initial_selection if str(iid) in ordered}
    range_start = anchor_iid if mode == "shift" and anchor_iid in ordered else start_iid
    if range_start not in ordered or current_iid not in ordered:
        return initial
    visible = None if visible_target_names is None else {str(name or "") for name in visible_target_names}

    def can_apply(iid: str) -> bool:
        candidate = candidate_by_iid.get(iid)
        if not _continuous_candidate_can_apply(candidate):
            return False
        if visible is None:
            return True
        return str(getattr(candidate, "target_story_name", "") or "") in visible

    start_index = ordered.index(range_start)
    current_index = ordered.index(current_iid)
    direction = 1 if current_index >= start_index else -1
    drag_range: list[str] = []
    for index in range(start_index, current_index + direction, direction):
        iid = ordered[index]
        if not can_apply(iid):
            break
        drag_range.append(iid)
    ranged = set(drag_range)
    if mode == "ctrl_add":
        return initial | ranged
    if mode == "ctrl_remove":
        return initial - ranged
    if mode == "shift":
        return initial | ranged
    return ranged


def _continuous_candidate_can_apply(candidate: object | None) -> bool:
    return bool(candidate is not None and getattr(candidate, "can_apply", False))


def _continuous_targets_are_single_range(targets: list[str] | tuple[str, ...], story_order: list[str] | tuple[str, ...]) -> bool:
    if len(targets) <= 1:
        return True
    indexes = sorted(int(story_order.index(name)) for name in targets if name in story_order)
    return len(indexes) == len(targets) and indexes == list(range(indexes[0], indexes[-1] + 1))


def _diagnostic_penalty_by_story(issues) -> dict[str, float]:
    issue_type_penalties = {
        "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD": 0.08,
        "DUPLICATE_ELEMENT": 0.08,
        "OVERLAPPING_LINE_ELEMENT": 0.08,
        "SPLIT_OVERLAP_DUPLICATE_ELEMENT": 0.08,
        "NO_CLOSED_REGION": 0.15,
        "OPEN_BOUNDARY": 0.15,
        "SNAP_ERROR_EXCEEDED": 0.15,
    }
    severity_by_story: dict[str, set[str]] = {}
    type_penalty_by_story: dict[str, float] = {}
    for issue in issues or []:
        story_name = str(getattr(issue, "story_name", "") or "")
        if not story_name:
            continue
        severity = str(getattr(issue, "severity", "") or "").upper()
        issue_type = str(getattr(issue, "issue_type", "") or "").upper()
        severity_by_story.setdefault(story_name, set()).add(severity)
        type_penalty_by_story[story_name] = type_penalty_by_story.get(story_name, 0.0) + issue_type_penalties.get(issue_type, 0.0)
    penalties: dict[str, float] = {}
    for story_name, severities in severity_by_story.items():
        severity_penalty = 0.20 if "ERROR" in severities else 0.05 if "WARNING" in severities else 0.0
        penalties[story_name] = severity_penalty + type_penalty_by_story.get(story_name, 0.0)
    return penalties


class FloorLoadAutoApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.root_dir = project_root()
        self.build_info = _load_build_info(self.root_dir)
        self.build_version_text = _build_version_text(self.build_info)
        self.title(f"MIDAS Floor Load Auto {self.build_version_text}")
        self.geometry("1120x780")
        self.minsize(980, 650)
        self.logger = setup_logger()
        self.config_data = load_config()
        self.data_dir = self.root_dir / "DATA"
        self.data_root = self.data_dir
        self.output_root = output_root_dir(self.data_root)
        self.current_project_dir: Path | None = None
        self.current_project_subdirs: dict[str, Path] = {}
        self._ensure_data_dirs()
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.notebook: ttk.Notebook | None = None
        self.pdf_tab_visible = False

        self.model_path = tk.StringVar()
        self.exported_mgt_path = tk.StringVar()
        self.user_dxf_path = tk.StringVar()
        self.target_model_path = tk.StringVar()
        self.mapping_path = tk.StringVar()
        self.layout_metadata_path = tk.StringVar()
        self.selected_story_name = tk.StringVar()
        self.stories: list[Story] = []
        self.nodes = []
        self.elements = []
        self.current_mgt_text = ""
        self.loaded_regions = []
        self.dxf_region_by_tree_iid: dict[str, object] = {}
        self.dxf_region_key_by_tree_iid: dict[str, str] = {}
        self.dxf_tree_iid_by_region_key: dict[str, str] = {}
        self.typical_floor_analysis = None
        self.typical_floor_groups = ()
        self.story_shape_profiles = ()
        self.continuous_apply_targets: dict[str, tuple[str, ...]] = {}
        self.continuous_apply_targets_by_region: dict[str, tuple[str, ...]] = {}
        self.continuous_materialized_targets_by_region: dict[str, tuple[str, ...]] = {}
        self.continuous_hatch_checks: dict[str, dict[str, object]] = {}
        self._story_below_allowed_polygon_cached_token = None
        self._story_below_allowed_polygon_cache = None
        self._continuous_below_allowed_reason_cache: dict[tuple[object, ...], str] = {}
        self._continuous_load_conflict_reason_cache: dict[tuple[object, ...], str] = {}
        self._continuous_target_load_conflict_reason_cache: dict[tuple[object, ...], str] = {}
        self._matching_target_cell_geometry_cache: dict[tuple[object, ...], ContinuousTargetCellMatch] = {}
        self._visible_targets_cache: dict[tuple[object, ...], tuple[str, ...]] = {}
        self._story_below_element_index_cached_token = None
        self._story_below_element_ids_cache: dict[str, tuple[int, ...]] = {}
        self._story_below_element_by_id_cache: dict[int, object] = {}
        self._hatch_state_version = 0
        self._continuous_tree_render_fingerprint = None
        self._continuous_below_allowed_reason_cache_hits = 0
        self._continuous_below_allowed_reason_cache_misses = 0
        self._continuous_load_conflict_reason_cache_hits = 0
        self._continuous_load_conflict_reason_cache_misses = 0
        self._continuous_target_load_conflict_reason_cache_hits = 0
        self._continuous_target_load_conflict_reason_cache_misses = 0
        self._matching_target_cell_geometry_cache_hits = 0
        self._matching_target_cell_geometry_cache_misses = 0
        self._story_below_element_index_cache_hits = 0
        self._story_below_element_index_cache_misses = 0
        self._story_below_allowed_polygon_cache_hits = 0
        self._story_below_allowed_polygon_cache_misses = 0
        self.hatch_view_region_items: dict[str, int] = {}
        self.hatch_view_checkbox_items: dict[str, tuple[int, ...]] = {}
        self.hatch_view_region_by_key: dict[str, object] = {}
        self.hatch_view_selected_region_key: str | None = None
        self.hatch_view_selected_region_keys: set[str] = set()
        self.hatch_view_edit_region_items: dict[str, int] = {}
        self.hatch_view_edit_checkbox_items: dict[str, tuple[int, ...]] = {}
        self.hatch_view_edit_region_by_key: dict[str, object] = {}
        self.hatch_view_selected_edit_region_keys: set[str] = set()
        self.hatch_edit_states_by_story: dict[str, HatchEditState] = {}
        self._hatch_edit_state_geometry_token_by_story: dict[str, tuple[object, ...]] = {}
        self.hatch_view_drag_start: tuple[float, float] | None = None
        self.hatch_view_drag_item: int | None = None
        self.hatch_view_drag_moved = False
        self.hatch_load_drag_item = None
        self.hatch_load_drag_start: tuple[float, float] | None = None
        self.hatch_load_drag_active = False
        self.hatch_load_drag_hover_key = None
        self.hatch_load_drag_ghost_window = None
        self.hatch_load_drag_ghost_label = None
        self.hatch_load_drag_last_status = ""
        self.hatch_one_way_click_after_id = None
        self._hatch_preview_render_after_id = None
        self._hatch_continuous_refresh_after_id = None
        self.hatch_view_middle_pan_active = False
        self.hatch_view_middle_pan_last: tuple[float, float] | None = None
        self.hatch_view_display_mode_var = tk.StringVar(value="ALL")
        self.hatch_view_selected_story_var = tk.StringVar(value="")
        self.continuous_candidate_by_iid: dict[str, object] = {}
        self.continuous_ordered_iids: list[str] = []
        self.continuous_story_anchor_iid: str | None = None
        self.continuous_drag_active = False
        self.continuous_drag_start_iid: str | None = None
        self.continuous_drag_current_iid: str | None = None
        self.continuous_drag_initial_selection: set[str] = set()
        self.continuous_drag_preview_selection: set[str] = set()
        self.continuous_drag_mode = "plain"
        self.continuous_drag_start_xy: tuple[int, int] | None = None
        self.continuous_drag_moved = False
        self.continuous_drag_autoscroll_after_id = None
        self._continuous_drag_last_y = 0
        self._continuous_drag_candidate_token: tuple[object, ...] = ()
        self.continuous_active_region_key: str | None = None
        self.continuous_active_region_keys: tuple[str, ...] = ()
        self.continuous_base_story_name = tk.StringVar()
        self.hatch_edit_undo_stack: list[tuple[str, HatchViewEditSnapshot]] = []
        self.hatch_edit_redo_stack: list[tuple[str, HatchViewEditSnapshot]] = []
        self._hatch_edit_history_session_id = 1
        self._hatch_edit_transaction_depth = 0
        self._hatch_edit_transaction_before = None
        self._hatch_edit_transaction_label = ""
        self.selected_hatch_story_var = tk.StringVar(value="기준 STORY: 선택 해치층 자동")
        self.typical_analysis_summary_var = tk.StringVar(value="층 형상 분석 전입니다.")
        self.hatch_preview_info_var = tk.StringVar(value="DXF 검증 후 해치 위치 미리보기가 표시됩니다.")
        self.hatch_preview_legend_var = tk.StringVar(value="")
        self.continuous_apply_status_var = tk.StringVar(value="연속층 적용 전입니다.")
        self.dxf_validation_status_var = tk.StringVar(value="DXF 검증 전입니다.")
        self.hatch_view_show_all_var = tk.BooleanVar(value=True)
        self.hatch_view_focus_selected_var = tk.BooleanVar(value=True)
        self.hatch_view_show_full_plan_var = tk.BooleanVar(value=False)
        self.hatch_view_highlight_continuous_var = tk.BooleanVar(value=False)
        self.hatch_view_show_legend_var = tk.BooleanVar(value=True)
        self.hatch_view_show_structure_var = tk.BooleanVar(value=True)
        self.hatch_one_way_mode_var = tk.BooleanVar(value=False)
        self.hatch_view_fit_bbox: tuple[float, float, float, float] | None = None
        self.hatch_view_view_bbox: tuple[float, float, float, float] | None = None
        self.hatch_view_manual_zoom = False
        self.diagnostic_issues = []
        self.diagnostic_issue_by_tree_iid: dict[str, object] = {}
        self.diagnostic_preview_info_var = tk.StringVar(value="진단 항목을 선택하면 위치 미리보기가 표시됩니다.")
        self.diagnostic_preview_selected_issue = None
        self.diagnostic_preview_visible = False
        self.diagnostic_preview_zoom = 1.0
        self.diagnostic_preview_last_transform = None
        self.dummy_issue_by_key: dict[str, DummyIssueViewModel] = {}
        self.dummy_issue_canvas_items: dict[str, tuple[int, ...]] = {}
        self.selected_dummy_issue_key: str | None = None
        self.dummy_preview_plan: DummyConnectionPlan | None = None
        self.approved_dummy_plans: dict[str, DummyConnectionPlan] = {}
        self.committed_dummy_members: dict[int, DummyDisplayMember] = {}
        self.dummy_member_canvas_items: dict[str, tuple[int, ...]] = {}
        self.dummy_overlay_geometry_token = None
        self.dummy_overlay_render_fingerprint = None
        self.dummy_overlay_member_fingerprint_by_key: dict[str, tuple[object, ...]] = {}
        self.dummy_status_var = tk.StringVar(value="LOAD DM 문제영역을 선택하세요.")
        self.last_diagnostic_dxf_path: Path | None = None
        self.last_diagnostic_report_path: Path | None = None
        self.selected_pdf_paths: list[Path] = []
        self.pdf_import_result: PdfLoadImportResult | None = None
        self.model_load_items: list[dict] = []
        self.pdf_load_items: list[dict] = []
        self.model_load_vars: dict[str, tk.BooleanVar] = {}
        self.pdf_load_vars: dict[str, tk.BooleanVar] = {}
        self.model_load_all_var = tk.BooleanVar(value=False)
        self.pdf_load_all_var = tk.BooleanVar(value=False)
        self.load_selection_user_dirty = False
        self.load_selection_source_signature = ""
        self.load_selection_default_mode = "MODEL_ONLY_AUTO_SELECTED"
        self.final_load_items: list[dict] = []
        self.last_generated_dxf_path: Path | None = None
        self.generated_dxf_metadata_path: Path | None = None
        self.generated_dxf_layout_metadata = None
        self.generated_dxf_mode: str | None = None
        self.generated_dxf_story_names: tuple[str, ...] = ()
        self.last_generated_model_path: Path | None = None
        self.generated_dxf_path = tk.StringVar(value="")
        self.generated_model_path = tk.StringVar(value="")
        self.dxf_next_action_text_var = tk.StringVar(value="DXF 생성 전에는 열 수 있는 파일이 없습니다.")
        self.model_next_action_text_var = tk.StringVar(value="모델링 파일 생성 전에는 열 수 있는 파일이 없습니다.")
        self.floorload_status_var = tk.StringVar(value="모델/MGT를 먼저 읽어 FLOOR LOAD 존재 여부를 분석하세요.")
        self.diagnostic_summary_var = tk.StringVar(value="FLOORLOAD 진단 전입니다.")
        self.model_unit_info = None
        self.model_length_unit_var = tk.StringVar(value="")
        self.dxf_unit_scale_var = tk.DoubleVar(value=1.0)
        self.dxf_unit_status_var = tk.StringVar(value="DXF output unit: mm. Load an MGT file to detect model length unit.")
        self.auto_load_dm_dummy_var = tk.BooleanVar(value=self.config_data.auto_load_dm_dummy_members)
        self.pdf_mgtx_path = tk.StringVar()
        self.pdf_merge_output_path = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text_var = tk.StringVar(value="대기 중")
        self.progress_percent_var = tk.StringVar(value="0%")
        self.build_version_var = tk.StringVar(value=self.build_version_text)
        self._busy = False
        self._busy_buttons: list[tk.Widget] = []
        self.last_auto_floorload_diag_signature: str | None = None

        self._build_ui()
        self._poll_queue()

    def _ensure_data_dirs(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.output_root = output_root_dir(self.data_root)

    def _guess_project_name(self) -> str:
        candidates = []

        for attr in ("model_path", "exported_mgt_path", "mgt_path", "selected_mgt_path"):
            var = getattr(self, attr, None)
            try:
                value = var.get() if hasattr(var, "get") else str(var or "")
            except Exception:
                value = ""
            if value:
                candidates.append(value)

        for attr in ("selected_pdf_paths", "pdf_files", "pdf_paths"):
            pdf_files = getattr(self, attr, None)
            if pdf_files:
                try:
                    candidates.append(str(pdf_files[0]))
                    break
                except Exception:
                    pass

        for value in candidates:
            try:
                stem = Path(value).stem
                if stem:
                    return stem
            except Exception:
                continue

        return "untitled_project_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    def _ensure_current_project_workspace(self, project_name: str | None = None) -> Path:
        if project_name is None and self.current_project_dir:
            self.current_project_subdirs = ensure_project_output_subdirs(self.current_project_dir)
            return self.current_project_dir

        if project_name is None:
            project_name = self._guess_project_name()

        project_dir = project_output_dir(self.data_root, project_name)
        self.current_project_dir = project_dir
        self.current_project_subdirs = ensure_project_output_subdirs(project_dir)

        if hasattr(self, "project_data_dir_var"):
            try:
                self.project_data_dir_var.set(str(project_dir))
            except Exception:
                pass

        return project_dir

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        notebook = ttk.Notebook(self)
        self.notebook = notebook
        notebook.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.tab_api = ttk.Frame(notebook)
        self.tab_model = ttk.Frame(notebook)
        self.tab_pdf = ttk.Frame(notebook)
        self.tab_dxf = ttk.Frame(notebook)
        self.tab_hatch_work = ttk.Frame(notebook)
        self.tab_build = ttk.Frame(notebook)
        self.tab_log = ttk.Frame(notebook)
        notebook.add(self.tab_api, text="1 API 설정")
        notebook.add(self.tab_model, text="2 모델/Story")
        # PDF 하중 입력 탭은 선택 기능이므로 초기에는 표시하지 않는다.
        notebook.add(self.tab_dxf, text="3 DXF 생성/검증")
        notebook.add(self.tab_hatch_work, text="4 기준층 하중/연속층 적용")
        notebook.add(self.tab_build, text="5 MGT 입력/저장")
        notebook.add(self.tab_log, text="로그")
        notebook.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

        self._build_api_tab()
        self._build_model_tab()
        self._build_pdf_tab()
        self._build_dxf_tab()
        self._build_hatch_work_tab()
        self._build_build_tab()
        self._build_log_tab()
        self._build_progress_status_bar()

    def _build_api_tab(self) -> None:
        f = self.tab_api
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Base URL").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.base_url_var = tk.StringVar(value=self.config_data.base_url)
        ttk.Entry(f, textvariable=self.base_url_var).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Label(f, text="Port(선택)").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        self.port_var = tk.StringVar(value=self.config_data.port)
        ttk.Entry(f, textvariable=self.port_var, width=16).grid(row=1, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(f, text="MAPI Key").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        self.mapi_key_var = tk.StringVar(value=self.config_data.mapi_key)
        ttk.Entry(f, textvariable=self.mapi_key_var, show="*", width=60).grid(row=2, column=1, sticky="ew", padx=8, pady=8)
        ttk.Label(f, text="Timeout(sec)").grid(row=3, column=0, sticky="w", padx=8, pady=8)
        self.timeout_var = tk.IntVar(value=self.config_data.timeout_seconds)
        ttk.Spinbox(f, from_=10, to=600, textvariable=self.timeout_var, width=10).grid(row=3, column=1, sticky="w", padx=8, pady=8)
        self.verify_ssl_var = tk.BooleanVar(value=self.config_data.verify_ssl)
        ttk.Checkbutton(f, text="SSL 인증서 검증", variable=self.verify_ssl_var).grid(row=4, column=1, sticky="w", padx=8, pady=8)
        button_frame = ttk.Frame(f)
        button_frame.grid(row=5, column=1, sticky="w", padx=8, pady=12)
        self._busy_button(button_frame, text="연결 테스트", command=self.test_api).pack(side="left", padx=4)
        ttk.Button(button_frame, text="설정 저장", command=self.save_current_config).pack(side="left", padx=4)
        ttk.Button(button_frame, text="기존 v3 Streamlit 실행", command=self.launch_legacy_v3).pack(side="left", padx=4)
        ttk.Label(
            f,
            text="주의: 원본 .mgb는 직접 덮어쓰지 않습니다. 새 full MGT를 만든 뒤 doc/NEW → IMPORTMXT → SAVEAS 방식으로 저장합니다.",
            foreground="blue",
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=8)

    def _build_model_tab(self) -> None:
        f = self.tab_model
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="모델 파일(.mgb/.mgbx/.mcb)").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.model_path).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(f, text="찾기", command=self.select_model_file).grid(row=0, column=2, padx=8, pady=8)
        self._busy_button(f, text="API로 열기 + MGT Export + Story 읽기", command=self.open_model_and_export).grid(row=1, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(f, text="디버그/오프라인용 MGT 직접 읽기").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.exported_mgt_path).grid(row=2, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(f, text="MGT 찾기", command=self.select_mgt_file).grid(row=2, column=2, padx=8, pady=8)
        self._busy_button(f, text="선택 MGT에서 Story 읽기", command=self.load_mgt_snapshot).grid(row=3, column=1, sticky="w", padx=8, pady=8)

        ttk.Separator(f).grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text="FLOOR LOAD 자동 분석").grid(row=5, column=0, sticky="nw", padx=8, pady=8)
        self.floorload_status_label = ttk.Label(f, textvariable=self.floorload_status_var, wraplength=820, foreground="blue")
        self.floorload_status_label.grid(row=5, column=1, columnspan=2, sticky="w", padx=8, pady=8)
        floor_button_frame = ttk.Frame(f)
        floor_button_frame.grid(row=6, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        self._busy_button(floor_button_frame, text="FLOOR LOAD 존재 여부 재분석", command=self.recheck_floorload_presence).pack(side="left", padx=4)
        self.open_pdf_tab_button = ttk.Button(floor_button_frame, text="PDF로 하중 입력하기", command=self.open_pdf_tab)
        self.open_pdf_tab_button.pack(side="left", padx=4)
        self.open_pdf_tab_button.state(["disabled"])
        ttk.Label(
            f,
            text="기존 모델에 FLOOR LOAD가 있으면 현재 흐름을 그대로 유지합니다. FLOOR LOAD가 없거나 사용자가 원할 때만 PDF 입력 탭을 열어 사용합니다.",
            foreground="gray",
            wraplength=900,
        ).grid(row=7, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        ttk.Label(f, text="Story 목록").grid(row=8, column=0, sticky="nw", padx=8, pady=8)
        self.story_tree = ttk.Treeview(f, columns=("name", "elevation", "height"), show="headings", height=13)
        self.story_tree.heading("name", text="Story")
        self.story_tree.heading("elevation", text="Elevation")
        self.story_tree.heading("height", text="Height")
        self.story_tree.column("name", width=140, anchor="center")
        self.story_tree.column("elevation", width=120, anchor="e")
        self.story_tree.column("height", width=120, anchor="e")
        self.story_tree.grid(row=8, column=1, sticky="nsew", padx=8, pady=8)
        f.rowconfigure(8, weight=1)
        self.story_tree.bind("<<TreeviewSelect>>", self.on_story_select)
        diag_button_frame = ttk.Frame(f)
        diag_button_frame.grid(row=9, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        self.open_diag_dxf_button = ttk.Button(diag_button_frame, text="진단 DXF 열기", command=self.open_last_diagnostic_dxf)
        self.open_diag_dxf_button.pack(side="left", padx=4)
        self.open_diag_dxf_button.state(["disabled"])
        self.open_diag_report_button = ttk.Button(diag_button_frame, text="진단 보고서 열기", command=self.open_last_diagnostic_report)
        self.open_diag_report_button.pack(side="left", padx=4)
        self.open_diag_report_button.state(["disabled"])
        ttk.Label(f, textvariable=self.diagnostic_summary_var, foreground="blue", wraplength=980).grid(row=10, column=0, columnspan=3, sticky="w", padx=8, pady=(4, 0))
        diagnostic_pane = ttk.PanedWindow(f, orient="horizontal")
        diagnostic_pane.grid(row=11, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        diagnostic_list_frame = ttk.Frame(diagnostic_pane)
        diagnostic_preview_frame = ttk.Frame(diagnostic_pane)
        self.diagnostic_pane = diagnostic_pane
        self.diagnostic_preview_panel = diagnostic_preview_frame
        diagnostic_list_frame.columnconfigure(0, weight=1)
        diagnostic_list_frame.rowconfigure(0, weight=1)
        diagnostic_preview_frame.columnconfigure(0, weight=1)
        diagnostic_preview_frame.rowconfigure(1, weight=1)
        diagnostic_pane.add(diagnostic_list_frame, weight=3)
        self.diagnostic_tree = ttk.Treeview(
            diagnostic_list_frame,
            columns=("story", "severity", "type", "xy", "nodes", "elements", "message", "action"),
            show="headings",
            height=8,
        )
        for col, txt, width in (
            ("story", "Story", 90),
            ("severity", "심각도", 80),
            ("type", "문제유형", 140),
            ("xy", "위치 X,Y", 130),
            ("nodes", "Node", 120),
            ("elements", "Element", 120),
            ("message", "추정 원인", 260),
            ("action", "수정 안내", 260),
        ):
            self.diagnostic_tree.heading(col, text=txt)
            self.diagnostic_tree.column(col, width=width)
        self.diagnostic_tree.grid(row=0, column=0, sticky="nsew")
        diagnostic_scroll = ttk.Scrollbar(diagnostic_list_frame, orient="vertical", command=self.diagnostic_tree.yview)
        diagnostic_scroll.grid(row=0, column=1, sticky="ns")
        self.diagnostic_tree.configure(yscrollcommand=diagnostic_scroll.set)
        self.diagnostic_tree.bind("<<TreeviewSelect>>", self._on_diagnostic_issue_selected)
        preview_header = ttk.Frame(diagnostic_preview_frame)
        preview_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        preview_header.columnconfigure(0, weight=1)
        ttk.Label(preview_header, text="진단 위치 미리보기").grid(row=0, column=0, sticky="w")
        ttk.Button(preview_header, text="전체보기", command=self._fit_diagnostic_preview).grid(row=0, column=1, padx=(4, 0), sticky="e")
        ttk.Button(preview_header, text="확대", command=lambda: self._zoom_diagnostic_preview(1.25)).grid(row=0, column=2, padx=(4, 0), sticky="e")
        ttk.Button(preview_header, text="축소", command=lambda: self._zoom_diagnostic_preview(1 / 1.25)).grid(row=0, column=3, padx=(4, 0), sticky="e")
        ttk.Button(preview_header, text="패널 닫기", command=self._hide_diagnostic_preview_panel).grid(row=0, column=4, padx=(4, 0), sticky="e")
        self.diagnostic_preview_canvas = tk.Canvas(
            diagnostic_preview_frame,
            height=360,
            background="white",
            highlightthickness=1,
            highlightbackground="#c8c8c8",
        )
        self.diagnostic_preview_canvas.grid(row=1, column=0, sticky="nsew")
        diagnostic_preview_vbar = ttk.Scrollbar(diagnostic_preview_frame, orient="vertical", command=self.diagnostic_preview_canvas.yview)
        diagnostic_preview_vbar.grid(row=1, column=1, sticky="ns")
        diagnostic_preview_hbar = ttk.Scrollbar(diagnostic_preview_frame, orient="horizontal", command=self.diagnostic_preview_canvas.xview)
        diagnostic_preview_hbar.grid(row=2, column=0, sticky="ew")
        self.diagnostic_preview_canvas.configure(
            xscrollcommand=diagnostic_preview_hbar.set,
            yscrollcommand=diagnostic_preview_vbar.set,
        )
        self.diagnostic_preview_canvas.bind("<Configure>", lambda _event: self._render_diagnostic_preview(self.diagnostic_preview_selected_issue))
        self.diagnostic_preview_canvas.bind("<MouseWheel>", self._on_diagnostic_preview_mousewheel)
        self.diagnostic_preview_canvas.bind("<Button-4>", self._on_diagnostic_preview_mousewheel)
        self.diagnostic_preview_canvas.bind("<Button-5>", self._on_diagnostic_preview_mousewheel)
        ttk.Label(
            diagnostic_preview_frame,
            textvariable=self.diagnostic_preview_info_var,
            wraplength=420,
            foreground="#444444",
        ).grid(row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        f.rowconfigure(11, weight=1)

    def _build_pdf_tab(self) -> None:
        f = self.tab_pdf
        f.columnconfigure(1, weight=1)
        ttk.Label(
            f,
            text="이 탭은 선택 기능입니다. 2번 탭에서 FLOOR LOAD가 없다고 판단되거나 사용자가 PDF 기반 하중 타입을 새로 만들고 싶을 때만 사용하세요.",
            foreground="blue",
            wraplength=940,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=8)

        ttk.Label(f, text="구조계산서 PDF").grid(row=1, column=0, sticky="nw", padx=8, pady=8)
        self.pdf_listbox = tk.Listbox(f, height=5)
        self.pdf_listbox.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
        pdf_button_frame = ttk.Frame(f)
        pdf_button_frame.grid(row=1, column=2, sticky="n", padx=8, pady=8)
        ttk.Button(pdf_button_frame, text="PDF 추가", command=self.select_pdf_files).pack(fill="x", pady=2)
        ttk.Button(pdf_button_frame, text="목록 비우기", command=self.clear_pdf_files).pack(fill="x", pady=2)
        f.rowconfigure(1, weight=0)

        self._busy_button(f, text="PDF 분석 및 MGTX 생성", command=self.run_pdf_analysis).grid(row=2, column=1, sticky="w", padx=8, pady=8)
        ttk.Button(f, text="PDF 하중목록 전체 선택", command=self.apply_pdf_loads_to_dxf_layers).grid(row=2, column=1, sticky="e", padx=8, pady=8)

        ttk.Label(f, text="생성 MGTX").grid(row=3, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.pdf_mgtx_path).grid(row=3, column=1, sticky="ew", padx=8, pady=8)
        self._busy_button(f, text="PDF MGTX를 현재 MGT에 병합", command=self.merge_pdf_mgtx_to_current_mgt).grid(row=3, column=2, sticky="ew", padx=8, pady=8)

        ttk.Label(f, text="병합 출력 MGT").grid(row=4, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.pdf_merge_output_path).grid(row=4, column=1, sticky="ew", padx=8, pady=8)

        self.pdf_summary_label = ttk.Label(f, text="PDF 분석 결과: -", foreground="blue", wraplength=940)
        self.pdf_summary_label.grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=8)

        ttk.Label(f, text="PDF 하중목록").grid(row=6, column=0, sticky="nw", padx=8, pady=(0, 4))
        self.pdf_load_lines_listbox = tk.Listbox(f, height=4)
        self.pdf_load_lines_listbox.grid(row=6, column=1, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        self.pdf_tree = ttk.Treeview(f, columns=("status", "type", "case", "value", "source", "reason"), show="headings", height=13)
        for col, txt, width in (
            ("status", "상태", 90),
            ("type", "Floor Load Type", 210),
            ("case", "Load Case", 120),
            ("value", "하중값", 90),
            ("source", "PDF/Page", 180),
            ("reason", "검토/제외 사유", 340),
        ):
            self.pdf_tree.heading(col, text=txt)
            self.pdf_tree.column(col, width=width)
        self.pdf_tree.grid(row=7, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        f.rowconfigure(7, weight=1)

    def _build_dxf_tab(self) -> None:
        f = self.tab_dxf
        for col in range(3):
            f.columnconfigure(col, weight=1)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Story tolerance").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.story_tol_var = tk.DoubleVar(value=self.config_data.story_tolerance)
        self.story_tol_var.trace_add("write", lambda *_args: self._reset_typical_floor_state(reason="Story tolerance 변경"))
        ttk.Entry(f, textvariable=self.story_tol_var, width=12).grid(row=0, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(
            f,
            textvariable=self.dxf_unit_status_var,
            foreground="blue",
            wraplength=360,
        ).grid(row=0, column=2, sticky="e", padx=8, pady=8)

        ttk.Label(
            f,
            text="모델링 입력 하중목록과 PDF 하중목록에서 사용할 하중을 체크하면 오른쪽 최종 적용 하중목록에 실시간 반영됩니다. 최종 적용 하중목록이 DXF 템플릿의 LOAD 레이어로 생성됩니다.",
            foreground="blue",
            wraplength=1000,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0))

        load_select_frame = ttk.Frame(f)
        load_select_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        for col in range(3):
            load_select_frame.columnconfigure(col, weight=1)
        load_select_frame.rowconfigure(0, weight=1)

        self.model_load_check_frame = self._create_scrollable_checklist(
            load_select_frame,
            "모델링 입력 하중목록",
            0,
            self.model_load_all_var,
            self._toggle_all_model_loads,
        )
        self.pdf_load_check_frame = self._create_scrollable_checklist(
            load_select_frame,
            "PDF 하중목록",
            1,
            self.pdf_load_all_var,
            self._toggle_all_pdf_loads,
        )

        final_frame = ttk.LabelFrame(load_select_frame, text="최종 적용 하중목록")
        final_frame.grid(row=0, column=2, sticky="nsew", padx=4, pady=2)
        final_frame.columnconfigure(0, weight=1)
        final_frame.rowconfigure(0, weight=1)
        self.final_load_tree = ttk.Treeview(final_frame, columns=("display", "source", "dl", "ll"), show="headings", height=12)
        self.final_load_tree.heading("display", text="적용명")
        self.final_load_tree.heading("source", text="출처")
        self.final_load_tree.heading("dl", text="DL")
        self.final_load_tree.heading("ll", text="LL")
        self.final_load_tree.column("display", width=150, minwidth=100, anchor="w", stretch=True)
        self.final_load_tree.column("source", width=55, minwidth=50, anchor="center", stretch=False)
        self.final_load_tree.column("dl", width=55, minwidth=50, anchor="e", stretch=False)
        self.final_load_tree.column("ll", width=55, minwidth=50, anchor="e", stretch=False)
        self.final_load_tree.grid(row=0, column=0, sticky="nsew")
        final_scroll = ttk.Scrollbar(final_frame, orient="vertical", command=self.final_load_tree.yview)
        final_scroll.grid(row=0, column=1, sticky="ns")
        self.final_load_tree.configure(yscrollcommand=final_scroll.set)
        self.final_load_tree.bind("<Configure>", self._resize_final_load_columns)

        dxf_button_frame = ttk.Frame(f)
        dxf_button_frame.grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=8)
        ttk.Label(dxf_button_frame, text="DXF 생성 Story").pack(side="left", padx=(0, 4))
        self.dxf_story_combo = ttk.Combobox(
            dxf_button_frame,
            textvariable=self.selected_story_name,
            state="readonly",
            width=22,
        )
        self.dxf_story_combo.pack(side="left", padx=(0, 8))
        self.dxf_story_combo.bind("<<ComboboxSelected>>", self._on_dxf_story_combo_selected)
        self._busy_button(dxf_button_frame, text="선택 Story center line DXF 생성", command=self.create_dxf_template).pack(side="left", padx=(0, 8))
        self._busy_button(dxf_button_frame, text="전층 DXF 생성", command=self.create_all_story_dxf_template).pack(side="left", padx=(0, 8))
        self.open_generated_dxf_button = tk.Button(
            dxf_button_frame,
            text="생성 DXF 파일 열기",
            command=self.open_last_generated_dxf,
            state="disabled",
            padx=8,
            pady=2,
        )
        self.open_generated_dxf_button.pack(side="left")
        self._dxf_open_button_defaults = self._capture_button_visual_defaults(self.open_generated_dxf_button)
        ttk.Label(
            dxf_button_frame,
            textvariable=self.dxf_next_action_text_var,
            foreground="#805000",
            wraplength=440,
        ).pack(side="left", padx=(8, 0))
        ttk.Separator(f).grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text="사용자 작성 DXF").grid(row=5, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.user_dxf_path).grid(row=5, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(f, text="찾기", command=self.select_user_dxf).grid(row=5, column=2, padx=8, pady=8)
        ttk.Label(f, text="전층 DXF layout metadata").grid(row=6, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.layout_metadata_path).grid(row=6, column=1, sticky="ew", padx=8, pady=8)
        metadata_button_frame = ttk.Frame(f)
        metadata_button_frame.grid(row=6, column=2, sticky="ew", padx=8, pady=8)
        ttk.Button(metadata_button_frame, text="선택", command=self.select_layout_metadata_file).pack(side="left", padx=(0, 4))
        ttk.Button(metadata_button_frame, text="자동 찾기", command=self.auto_find_layout_metadata).pack(side="left")
        dxf_validation_frame = ttk.Frame(f)
        dxf_validation_frame.grid(row=7, column=0, columnspan=3, sticky="w", padx=8, pady=8)
        self._busy_button(dxf_validation_frame, text="DXF 검증", command=self.validate_user_dxf).pack(side="left")
        ttk.Checkbutton(
            dxf_validation_frame,
            text="LOAD DM dummy BEAM 자동 생성",
            variable=self.auto_load_dm_dummy_var,
        ).pack(side="left", padx=(12, 0))

        validation_status_frame = ttk.Frame(f)
        validation_status_frame.grid(row=8, column=0, columnspan=3, sticky="ew", padx=8, pady=(0, 6))
        validation_status_frame.columnconfigure(0, weight=1)
        ttk.Label(
            validation_status_frame,
            textvariable=self.dxf_validation_status_var,
            foreground="#2d4b73",
            wraplength=860,
        ).grid(row=0, column=0, sticky="w")
        self.open_hatch_work_tab_button = ttk.Button(
            validation_status_frame,
            text="기준층 하중/연속층 적용 탭으로 이동",
            command=self.open_hatch_work_tab,
        )
        self.open_hatch_work_tab_button.grid(row=0, column=1, sticky="e", padx=(8, 0))
        self.open_hatch_work_tab_button.state(["disabled"])

        dxf_result_frame = ttk.Frame(f)
        dxf_result_frame.grid(row=9, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        dxf_result_frame.columnconfigure(0, weight=1)
        dxf_result_frame.rowconfigure(0, weight=1)

        self.dxf_tree = ttk.Treeview(
            dxf_result_frame,
            columns=(
                "status",
                "story",
                "continuous",
                "metadata",
                "transform",
                "source",
                "layer",
                "pattern",
                "solid",
                "mode",
                "mode_source",
                "dir",
                "load",
                "dl",
                "ll",
                "area",
                "placed_bbox",
                "model_bbox",
                "source_id",
                "warnings",
            ),
            show="headings",
            height=12,
        )
        for col, txt, width in (
            ("status", "상태", 120), ("source", "객체", 80), ("layer", "레이어", 220), ("load", "하중명", 140),
            ("dl", "DL", 80), ("ll", "LL", 80), ("area", "면적", 100), ("warnings", "경고", 300),
        ):
            self.dxf_tree.heading(col, text=txt)
            self.dxf_tree.column(col, width=width)
        self.dxf_tree.heading("story", text="Story")
        self.dxf_tree.column("story", width=90)
        self.dxf_tree.heading("continuous", text="연속층")
        self.dxf_tree.column("continuous", width=110, anchor="center")
        self.dxf_tree.heading("metadata", text="metadata")
        self.dxf_tree.column("metadata", width=85, anchor="center")
        self.dxf_tree.heading("transform", text="transform")
        self.dxf_tree.column("transform", width=85, anchor="center")
        for col, txt, width in (
            ("pattern", "HATCH", 95),
            ("solid", "SOLID", 60),
            ("mode", "입력방식", 110),
            ("mode_source", "판정근거", 150),
            ("dir", "방향선", 70),
        ):
            self.dxf_tree.heading(col, text=txt)
            self.dxf_tree.column(col, width=width)
        self.dxf_tree.heading("placed_bbox", text="placed_bbox")
        self.dxf_tree.column("placed_bbox", width=165)
        self.dxf_tree.heading("model_bbox", text="model_bbox")
        self.dxf_tree.column("model_bbox", width=165)
        self.dxf_tree.heading("source_id", text="source_id")
        self.dxf_tree.column("source_id", width=110)
        self.dxf_tree.grid(row=0, column=0, sticky="nsew")
        dxf_scroll = ttk.Scrollbar(dxf_result_frame, orient="vertical", command=self.dxf_tree.yview)
        dxf_scroll.grid(row=0, column=1, sticky="ns")
        self.dxf_tree.configure(yscrollcommand=dxf_scroll.set)
        self.dxf_tree.bind("<<TreeviewSelect>>", self._on_dxf_region_selected)
        f.rowconfigure(2, weight=2)
        f.rowconfigure(9, weight=4)
        self._refresh_model_load_checklist()
        self._refresh_pdf_load_checklist()
        self._refresh_final_load_tree()

    def _build_hatch_work_tab(self) -> None:
        f = self.tab_hatch_work
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        header = ttk.Frame(f)
        header.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        header.columnconfigure(1, weight=1)
        ttk.Label(header, text="작업 상태").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(
            header,
            textvariable=self.dxf_validation_status_var,
            foreground="#2d4b73",
            wraplength=820,
        ).grid(row=0, column=1, sticky="w")
        ttk.Button(header, text="전체 해치 보기", command=self._show_all_hatches).grid(row=0, column=2, sticky="e", padx=(8, 0))
        ttk.Button(header, text="적용 결과 초기화", command=self.clear_continuous_apply_results).grid(row=0, column=3, sticky="e", padx=(6, 0))
        ttk.Button(header, text="MGT 입력/저장 탭으로 이동", command=self.open_build_tab).grid(row=0, column=4, sticky="e", padx=(6, 0))

        main_area = ttk.Frame(f)
        main_area.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 8))
        main_area.columnconfigure(0, weight=2, minsize=900)
        main_area.columnconfigure(1, weight=1, minsize=420)
        main_area.rowconfigure(0, weight=1)
        hatch_left = ttk.Frame(main_area)
        hatch_right = ttk.Frame(main_area)
        hatch_left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        hatch_right.grid(row=0, column=1, sticky="nsew")
        hatch_left.columnconfigure(0, weight=1)
        hatch_left.rowconfigure(0, weight=1)
        hatch_right.columnconfigure(0, weight=1)
        hatch_right.rowconfigure(0, weight=1)

        self._build_hatch_view_panel(hatch_left)
        self._build_hatch_control_panel(hatch_right)

    def _build_hatch_control_panel(self, parent: tk.Widget) -> None:
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        info_frame = ttk.LabelFrame(parent, text="선택 해치 정보")
        info_frame.grid(row=0, column=0, sticky="ew", padx=(4, 0), pady=(0, 6))
        info_frame.columnconfigure(0, weight=1)
        ttk.Label(
            info_frame,
            textvariable=self.hatch_preview_info_var,
            foreground="#2d4b73",
            wraplength=360,
        ).grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))
        ttk.Label(
            info_frame,
            textvariable=self.selected_hatch_story_var,
            foreground="#555555",
            wraplength=360,
        ).grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 6))

        self._build_typical_floor_workbench(parent, row=1)

    def _build_typical_floor_workbench(self, parent: tk.Widget, *, row: int) -> None:
        workbench = ttk.Frame(parent)
        workbench.grid(row=row, column=0, sticky="nsew", padx=(0, 4), pady=(0, 0))
        workbench.columnconfigure(0, weight=1)
        workbench.rowconfigure(0, weight=4)
        workbench.rowconfigure(1, weight=4)
        workbench.rowconfigure(2, weight=2)

        # Kept for internal/test compatibility; the user-facing analysis tab is hidden.
        analysis_tab = ttk.Frame(parent)
        direct_load_tab = ttk.LabelFrame(workbench, text="직접 하중 입력")
        continuous_tab = ttk.LabelFrame(workbench, text="연속층 적용")
        guide_tab = ttk.LabelFrame(workbench, text="검증결과/수정안내")
        direct_load_tab.grid(row=0, column=0, sticky="nsew", padx=0, pady=(0, 6))
        continuous_tab.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 6))
        guide_tab.grid(row=2, column=0, sticky="nsew", padx=0, pady=(0, 0))

        analysis_tab.columnconfigure(0, weight=1)
        analysis_tab.columnconfigure(1, weight=1)
        analysis_tab.rowconfigure(1, weight=1)
        ttk.Label(analysis_tab, textvariable=self.typical_analysis_summary_var, foreground="#2d4b73").grid(
            row=0,
            column=0,
            columnspan=2,
            sticky="w",
            padx=6,
            pady=(6, 2),
        )
        self.typical_group_tree = ttk.Treeview(
            analysis_tab,
            columns=("group", "range", "typical", "score", "transition", "status", "note"),
            show="headings",
            height=7,
        )
        for col, title, width in (
            ("group", "Group", 80),
            ("range", "Story 구간", 150),
            ("typical", "typ.", 90),
            ("score", "점수", 80),
            ("transition", "전이층", 140),
            ("status", "상태", 120),
            ("note", "비고", 220),
        ):
            self.typical_group_tree.heading(col, text=title)
            self.typical_group_tree.column(col, width=width)
        self.typical_group_tree.grid(row=1, column=0, sticky="nsew", padx=(6, 3), pady=6)
        self.typical_story_tree = ttk.Treeview(
            analysis_tab,
            columns=("story", "elevation", "group", "is_typical", "score", "transition"),
            show="headings",
            height=7,
        )
        for col, title, width in (
            ("story", "Story", 90),
            ("elevation", "Elevation", 90),
            ("group", "Group", 80),
            ("is_typical", "typ.", 60),
            ("score", "유사도", 90),
            ("transition", "전이층", 100),
        ):
            self.typical_story_tree.heading(col, text=title)
            self.typical_story_tree.column(col, width=width)
        self.typical_story_tree.grid(row=1, column=1, sticky="nsew", padx=(3, 6), pady=6)

        self._build_hatch_direct_load_tab(direct_load_tab)

        continuous_tab.columnconfigure(0, weight=1)
        continuous_tab.rowconfigure(2, weight=1)
        continuous_controls = ttk.Frame(continuous_tab)
        continuous_controls.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ttk.Label(continuous_controls, textvariable=self.selected_hatch_story_var, foreground="#2d4b73").pack(side="left", padx=(0, 8))
        ttk.Button(continuous_controls, text="적용 가능층 자동 선택", command=self.select_applicable_continuous_stories).pack(side="left", padx=(0, 6))
        self.continuous_apply_status_label = tk.Label(
            continuous_tab,
            textvariable=self.continuous_apply_status_var,
            foreground="#2d4b73",
            anchor="w",
            justify="left",
        )
        self.continuous_apply_status_label.grid(
            row=1,
            column=0,
            sticky="w",
            padx=6,
            pady=(0, 2),
        )
        self.continuous_tree = ttk.Treeview(
            continuous_tab,
            columns=("selected", "story", "similarity", "boundary", "area", "can_apply", "reason"),
            show="headings",
            height=8,
        )
        for col, title, width in (
            ("selected", "선택", 44),
            ("story", "Story", 72),
            ("similarity", "유사도", 68),
            ("boundary", "매칭", 68),
            ("area", "IoU", 54),
            ("can_apply", "가능", 58),
            ("reason", "사유", 180),
        ):
            self.continuous_tree.heading(col, text=title)
            self.continuous_tree.column(col, width=width)
        self.continuous_tree.tag_configure("can_apply", foreground="#1f7a1f")
        self.continuous_tree.tag_configure("cannot_apply", foreground="#888888")
        self.continuous_tree.tag_configure("selected_apply", background="#d7ebff")
        self.continuous_tree.tag_configure("load_conflict", foreground="#be185d")
        self.continuous_tree.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        continuous_hbar = ttk.Scrollbar(continuous_tab, orient="horizontal", command=self.continuous_tree.xview)
        continuous_hbar.grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 6))
        self.continuous_tree.configure(xscrollcommand=continuous_hbar.set)
        self.continuous_tree.bind("<ButtonPress-1>", self._on_continuous_tree_button_press)
        self.continuous_tree.bind("<B1-Motion>", self._on_continuous_tree_drag_motion)
        self.continuous_tree.bind("<ButtonRelease-1>", self._on_continuous_tree_button_release)
        self.continuous_tree.bind("<Leave>", self._on_continuous_tree_leave)
        self.continuous_tree.bind("<Escape>", self._on_continuous_tree_drag_cancel)
        self.continuous_tree.bind("<Destroy>", self._on_continuous_tree_destroy, add="+")

        guide_tab.columnconfigure(0, weight=1)
        guide_tab.rowconfigure(0, weight=1)
        guide_text = tk.Text(guide_tab, height=5, wrap="word")
        guide_text.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        guide_vbar = ttk.Scrollbar(guide_tab, orient="vertical", command=guide_text.yview)
        guide_vbar.grid(row=0, column=1, sticky="ns", pady=6)
        guide_text.configure(yscrollcommand=guide_vbar.set)
        guide_text.insert(
            "1.0",
            "중복 부재: 겹친 보/벽 부재는 FLOORLOAD 입력을 막을 수 있으므로 모델에서 정리한 뒤 다시 Export하세요.\n"
            "캔틸레버/자유단: 진단에서 자유단을 표시하면 MGT 생성 전 LOAD DM dummy BEAM 자동 생성을 켜세요.\n"
            "개방 경계: 바닥 외곽이 닫힌 영역을 만들지 못한 상태입니다. 누락 보, 벽, snap 절점을 확인하세요.\n"
            "전이층: 전이층 또는 외곽 불일치층은 typ. 표시와 연속층 자동 적용을 끊습니다.",
        )
        guide_text.configure(state="disabled")

    def _build_hatch_direct_load_tab(self, tab: tk.Widget) -> None:
        tab.columnconfigure(0, weight=1)
        tab.rowconfigure(2, weight=1)
        ttk.Label(
            tab,
            textvariable=self.hatch_preview_info_var,
            foreground="#2d4b73",
            wraplength=360,
        ).grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 4))
        self.hatch_load_tree = ttk.Treeview(
            tab,
            columns=("name", "dl", "ll", "distribution"),
            show="headings",
            height=8,
        )
        for col, title, width in (
            ("name", "하중명", 150),
            ("dl", "DL", 55),
            ("ll", "LL", 55),
            ("distribution", "방식", 86),
        ):
            self.hatch_load_tree.heading(col, text=title)
            self.hatch_load_tree.column(col, width=width)
        self.hatch_load_tree.grid(row=2, column=0, sticky="nsew", padx=6, pady=(0, 6))
        self.hatch_load_tree.bind("<Double-1>", self._on_hatch_load_tree_activate)
        self.hatch_load_tree.bind("<Return>", self._on_hatch_load_tree_activate)
        self.hatch_load_tree.bind("<<TreeviewSelect>>", self._on_hatch_load_tree_select)
        self.hatch_load_tree.bind("<ButtonPress-1>", self._on_hatch_load_drag_start, add="+")
        self.hatch_load_tree.bind("<B1-Motion>", self._on_hatch_load_drag_motion, add="+")
        self.hatch_load_tree.bind("<ButtonRelease-1>", self._on_hatch_load_drag_release, add="+")
        self.hatch_load_item_by_iid = {}
        buttons = ttk.Frame(tab)
        buttons.grid(row=3, column=0, sticky="ew", padx=6, pady=(0, 6))
        buttons.columnconfigure(0, weight=1)
        buttons.columnconfigure(1, weight=1)
        self.hatch_one_way_button = tk.Button(
            buttons,
            command=self._toggle_hatch_one_way_mode,
            relief="raised",
            borderwidth=1,
            activebackground="#fca5a5",
            activeforeground="#7f1d1d",
        )
        self.hatch_one_way_button.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self._refresh_hatch_one_way_button_style()
        ttk.Button(buttons, text="선택 영역에 하중 적용", command=self.apply_selected_hatch_load).grid(row=1, column=0, sticky="ew", padx=(0, 3), pady=(0, 3))
        ttk.Button(buttons, text="선택 영역 하중 변경", command=self.apply_selected_hatch_load).grid(row=1, column=1, sticky="ew", padx=(3, 0), pady=(0, 3))
        ttk.Button(buttons, text="선택 영역 하중 제거", command=self.remove_selected_hatch_load).grid(row=2, column=0, sticky="ew", padx=(0, 3), pady=(3, 0))
        ttk.Button(buttons, text="해치 영역 구분하기", command=self.split_selected_hatch_region).grid(row=2, column=1, sticky="ew", padx=(3, 0), pady=(3, 0))
        self._refresh_hatch_load_tree()

    def _toggle_hatch_one_way_mode(self) -> None:
        var = self.__dict__.get("hatch_one_way_mode_var")
        if var is None:
            self.hatch_one_way_mode_var = tk.BooleanVar(value=False)
            var = self.hatch_one_way_mode_var
        try:
            var.set(not bool(var.get()))
        except Exception:
            self.hatch_one_way_mode_var = tk.BooleanVar(value=True)
        self._refresh_hatch_one_way_button_style()

    def _refresh_hatch_one_way_button_style(self) -> None:
        button = self.__dict__.get("hatch_one_way_button")
        if button is None:
            return
        enabled = self._hatch_one_way_mode_enabled()
        try:
            button.configure(
                text="ONE-WAY ON" if enabled else "ONE-WAY OFF",
                bg="#fca5a5" if enabled else "#fee2e2",
                fg="#7f1d1d",
            )
        except Exception:
            pass

    def _hatch_one_way_mode_enabled(self) -> bool:
        var = self.__dict__.get("hatch_one_way_mode_var")
        if var is None:
            return False
        try:
            return bool(var.get())
        except Exception:
            return bool(var)

    def _hatch_load_item_for_current_mode(self, item: dict) -> dict:
        current = dict(item or {})
        if self._hatch_one_way_mode_enabled():
            current["distribution"] = DISTRIBUTION_ONE_WAY
        elif "distribution" not in current or not current.get("distribution"):
            current["distribution"] = str(current.get("distribution") or "TWO_WAY")
        return current

    def _build_hatch_view_panel(self, parent: tk.Widget) -> None:
        panel = ttk.Frame(parent)
        panel.grid(row=0, column=0, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)

        header = ttk.Frame(panel)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(header, text="해치 보기", font=("TkDefaultFont", 10, "bold")).pack(side="left", padx=(0, 8))
        ttk.Button(header, text="전체 평면 보기", command=self._show_all_hatches).pack(side="left", padx=(6, 0))
        self.hatch_undo_button = ttk.Button(header, text="↶ Undo", command=self.undo_hatch_view_edit)
        self.hatch_undo_button.pack(side="left", padx=(8, 0))
        self.hatch_redo_button = ttk.Button(header, text="↷ Redo", command=self.redo_hatch_view_edit)
        self.hatch_redo_button.pack(side="left", padx=(4, 0))
        self.dummy_create_button = ttk.Button(header, text="LOAD DM 승인", command=self._approve_selected_dummy_plan, state="disabled")
        self.dummy_create_button.pack(side="left", padx=(8, 0))
        self.dummy_cancel_button = ttk.Button(header, text="승인 취소", command=self._cancel_selected_dummy_plan, state="disabled")
        self.dummy_cancel_button.pack(side="left", padx=(4, 0))
        self._update_hatch_undo_redo_buttons()
        ttk.Radiobutton(header, text="전체 DXF 보기", variable=self.hatch_view_display_mode_var, value="ALL", command=self._on_hatch_view_display_mode_changed).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(header, text="층별 DXF 보기", variable=self.hatch_view_display_mode_var, value="STORY", command=self._on_hatch_view_display_mode_changed).pack(side="left", padx=(4, 0))
        self.hatch_view_story_combo = ttk.Combobox(
            header,
            textvariable=self.hatch_view_selected_story_var,
            state="readonly",
            width=12,
        )
        self.hatch_view_story_combo.pack(side="left", padx=(4, 0))
        self.hatch_view_story_combo.bind("<<ComboboxSelected>>", self._on_hatch_view_story_changed)
        ttk.Checkbutton(header, text="구조요소 표시", variable=self.hatch_view_show_structure_var, command=self._render_hatch_preview).pack(side="left", padx=(6, 0))
        ttk.Checkbutton(header, text="연속층 가능 강조", variable=self.hatch_view_highlight_continuous_var, command=self._render_hatch_preview).pack(side="left", padx=(6, 0))

        self.hatch_preview_canvas = tk.Canvas(panel, height=640, bg="#fbfbfb", highlightthickness=1, highlightbackground="#d0d0d0")
        self.hatch_preview_canvas.grid(row=1, column=0, sticky="nsew")
        hatch_vbar = ttk.Scrollbar(panel, orient="vertical", command=self.hatch_preview_canvas.yview)
        hatch_vbar.grid(row=1, column=1, sticky="ns")
        hatch_hbar = ttk.Scrollbar(panel, orient="horizontal", command=self.hatch_preview_canvas.xview)
        hatch_hbar.grid(row=2, column=0, sticky="ew")
        self.hatch_preview_canvas.configure(xscrollcommand=hatch_hbar.set, yscrollcommand=hatch_vbar.set)
        self.hatch_preview_canvas.bind("<Configure>", lambda _event: self._render_hatch_preview())
        self.hatch_preview_canvas.bind("<ButtonPress-1>", self._on_hatch_view_button_press)
        self.hatch_preview_canvas.bind("<B1-Motion>", self._on_hatch_view_drag)
        self.hatch_preview_canvas.bind("<ButtonRelease-1>", self._on_hatch_view_button_release)
        self.hatch_preview_canvas.bind("<Button-3>", self._on_hatch_view_context_menu)
        self.hatch_preview_canvas.bind("<ButtonPress-2>", self._on_hatch_view_middle_pan_start)
        self.hatch_preview_canvas.bind("<B2-Motion>", self._on_hatch_view_middle_pan_drag)
        self.hatch_preview_canvas.bind("<ButtonRelease-2>", self._on_hatch_view_middle_pan_end)
        self.hatch_preview_canvas.bind("<MouseWheel>", self._on_hatch_view_mousewheel)
        self.hatch_preview_canvas.bind("<Button-4>", self._on_hatch_view_mousewheel)
        self.hatch_preview_canvas.bind("<Button-5>", self._on_hatch_view_mousewheel)
        self.hatch_preview_canvas.bind("<Delete>", self._on_hatch_view_delete_key)
        self.hatch_preview_canvas.bind("<BackSpace>", self._on_hatch_view_delete_key)
        self.hatch_preview_canvas.bind("<Control-z>", self._on_hatch_view_undo_key)
        self.hatch_preview_canvas.bind("<Control-Z>", self._on_hatch_view_undo_key)
        self.hatch_preview_canvas.bind("<Control-y>", self._on_hatch_view_redo_key)
        self.hatch_preview_canvas.bind("<Control-Y>", self._on_hatch_view_redo_key)
        self.hatch_preview_canvas.bind("<Control-Shift-Z>", self._on_hatch_view_redo_key)
        self.bind_all("<Control-z>", self._on_hatch_view_undo_key, add="+")
        self.bind_all("<Control-Z>", self._on_hatch_view_undo_key, add="+")
        self.bind_all("<Control-y>", self._on_hatch_view_redo_key, add="+")
        self.bind_all("<Control-Y>", self._on_hatch_view_redo_key, add="+")
        self.bind_all("<Control-Shift-Z>", self._on_hatch_view_redo_key, add="+")
        self.bind_all("<Delete>", self._on_hatch_view_delete_key, add="+")

        ttk.Label(panel, textvariable=self.hatch_preview_info_var, foreground="#2d4b73", wraplength=560).grid(
            row=3,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(6, 0),
        )
        ttk.Label(panel, textvariable=self.hatch_preview_legend_var, foreground="#555555", wraplength=560).grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(2, 0),
        )
        ttk.Label(panel, textvariable=self.dummy_status_var, foreground="#6d28d9", wraplength=560).grid(
            row=5,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(2, 0),
        )

    def _show_all_hatches(self) -> None:
        try:
            self.hatch_view_show_full_plan_var.set(True)
        except Exception:
            pass
        self._reset_hatch_view_zoom()
        self._render_hatch_preview(focus_region_key=None)

    def open_hatch_work_tab(self) -> None:
        if self.notebook is None or not hasattr(self, "tab_hatch_work"):
            return
        self.notebook.select(self.tab_hatch_work)
        if self.loaded_regions and not self.story_shape_profiles:
            self._ensure_typical_floor_analysis(reason="DXF 검증 후 HATCH VIEW 이동")
        if self.loaded_regions and not self.continuous_hatch_checks:
            self._recompute_hatch_continuous_checks()
        self._render_hatch_preview()

    def open_build_tab(self) -> None:
        if self.notebook is not None:
            self.notebook.select(self.tab_build)

    def _on_main_tab_changed(self, _event=None) -> None:
        if self.notebook is None or not hasattr(self, "tab_hatch_work"):
            return
        if self.notebook.select() != str(self.tab_hatch_work):
            return
        if self.loaded_regions and not self.story_shape_profiles:
            self._ensure_typical_floor_analysis(reason="HATCH VIEW 탭 표시")
        if self.loaded_regions and not self.continuous_hatch_checks:
            self._recompute_hatch_continuous_checks()
        self._render_hatch_preview()

    def _create_scrollable_checklist(
        self,
        parent: tk.Widget,
        title: str,
        column: int,
        all_var: tk.BooleanVar | None = None,
        all_command=None,
    ) -> ttk.Frame:
        panel = ttk.LabelFrame(parent, text=title)
        panel.grid(row=0, column=column, sticky="nsew", padx=4, pady=2)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        if all_var is not None and all_command is not None:
            tk.Checkbutton(
                panel,
                text="전체선택",
                variable=all_var,
                command=all_command,
                anchor="w",
                padx=1,
                pady=0,
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=3, pady=(2, 1))
        canvas = tk.Canvas(panel, height=260, highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        return inner

    def _build_build_tab(self) -> None:
        f = self.tab_build
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Snap tolerance").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.snap_tol_var = tk.DoubleVar(value=self.config_data.snap_tolerance)
        self.snap_tol_var.trace_add("write", lambda *_args: self._reset_typical_floor_state(reason="snap tolerance 변경"))
        ttk.Entry(f, textvariable=self.snap_tol_var, width=12).grid(row=0, column=1, sticky="w", padx=8, pady=8)
        self.include_zero_var = tk.BooleanVar(value=self.config_data.include_zero_load)
        ttk.Checkbutton(f, text="0 값도 명시 입력", variable=self.include_zero_var).grid(row=1, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(f, text="결과 .mgbx 저장 경로").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.target_model_path).grid(row=2, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(f, text="저장 위치", command=self.select_target_model).grid(row=2, column=2, padx=8, pady=8)
        build_button_frame = ttk.Frame(f)
        build_button_frame.grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=12)
        self._busy_button(build_button_frame, text="full MGT 생성 + 새 모델 import/save as", command=self.build_and_import).pack(side="left", padx=(0, 8))
        self._busy_button(build_button_frame, text="API import 없이 full MGT만 생성", command=self.build_mgt_only).pack(side="left", padx=(0, 8))
        self.open_generated_model_button = tk.Button(
            build_button_frame,
            text="생성 모델링 파일 열기",
            command=self.open_generated_model_file,
            state="disabled",
            padx=8,
            pady=2,
        )
        self.open_generated_model_button.pack(side="left")
        self._model_open_button_defaults = self._capture_button_visual_defaults(self.open_generated_model_button)
        ttk.Label(f, textvariable=self.model_next_action_text_var, foreground="#2f6b2f", wraplength=900).grid(
            row=4,
            column=0,
            columnspan=3,
            sticky="w",
            padx=8,
            pady=(0, 4),
        )
        self.result_label = ttk.Label(f, text="결과 파일: -", foreground="blue", wraplength=900)
        self.result_label.grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=8)

    def _build_log_tab(self) -> None:
        self.log_text = tk.Text(self.tab_log, height=25)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_progress_status_bar(self) -> None:
        frame = ttk.Frame(self)
        frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        frame.columnconfigure(2, weight=1)
        ttk.Label(frame, text="상태:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(frame, textvariable=self.progress_text_var, width=28).grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.progress_bar = ttk.Progressbar(
            frame,
            variable=self.progress_var,
            maximum=100.0,
            mode="determinate",
        )
        self.progress_bar.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Label(frame, textvariable=self.progress_percent_var, width=6, anchor="e").grid(row=0, column=3, sticky="e")
        ttk.Label(frame, textvariable=self.build_version_var, anchor="e").grid(row=0, column=4, sticky="e", padx=(8, 0))

    def _busy_button(self, parent, **kwargs):
        button = ttk.Button(parent, **kwargs)
        self._register_busy_button(button)
        return button

    def _register_busy_button(self, button):
        self._busy_buttons.append(button)
        return button

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = bool(busy)
        for button in self._busy_buttons:
            try:
                button.state(["disabled"] if busy else ["!disabled"])
            except Exception:
                try:
                    button.configure(state="disabled" if busy else "normal")
                except Exception:
                    pass
        if message:
            self.progress_text_var.set(message)

    def _capture_button_visual_defaults(self, button) -> dict[str, object]:
        defaults: dict[str, object] = {}
        for option in ("background", "activebackground", "foreground", "relief"):
            try:
                defaults[option] = button.cget(option)
            except Exception:
                pass
        return defaults

    def _set_button_enabled(self, button, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        try:
            state_method = getattr(button, "state")
        except Exception:
            state_method = None
        if callable(state_method):
            try:
                state_method(["!disabled"] if enabled else ["disabled"])
                return
            except Exception:
                pass
        try:
            button.configure(state=state)
        except Exception:
            pass

    def _configure_next_action_button(
        self,
        button,
        *,
        enabled: bool,
        text: str,
        defaults: dict[str, object] | None = None,
        background: str | None = None,
        activebackground: str | None = None,
    ) -> None:
        try:
            button.configure(text=text)
        except Exception:
            pass
        self._set_button_enabled(button, enabled)
        if background:
            for option, value in (("background", background), ("activebackground", activebackground or background), ("relief", "raised")):
                try:
                    button.configure(**{option: value})
                except Exception:
                    pass
            return
        for option, value in (defaults or {}).items():
            try:
                button.configure(**{option: value})
            except Exception:
                pass

    def _short_ui_message(self, message: str, *, limit: int = 220) -> str:
        text = " ".join(str(message or "").split())
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _reset_dxf_next_action_state(self, message: str = "DXF 생성 중입니다. 완료 후 파일 열기 버튼이 활성화됩니다.") -> None:
        self.last_generated_dxf_path = None
        self.generated_dxf_metadata_path = None
        self.generated_dxf_layout_metadata = None
        self.generated_dxf_mode = None
        self.generated_dxf_story_names = ()
        self._invalidate_continuous_below_allowed_reason_cache("DXF 생성 상태 초기화")
        if hasattr(self, "generated_dxf_path"):
            self.generated_dxf_path.set("")
        if hasattr(self, "open_generated_dxf_button"):
            self._configure_next_action_button(
                self.open_generated_dxf_button,
                enabled=False,
                text="생성 DXF 파일 열기",
                defaults=getattr(self, "_dxf_open_button_defaults", None),
            )
        if hasattr(self, "dxf_next_action_text_var"):
            self.dxf_next_action_text_var.set(message)

    def _mark_dxf_generated_success(self, path: str | Path) -> None:
        generated_path = Path(path)
        self.last_generated_dxf_path = generated_path
        if hasattr(self, "generated_dxf_path"):
            self.generated_dxf_path.set(str(generated_path))
        if hasattr(self, "open_generated_dxf_button"):
            self._configure_next_action_button(
                self.open_generated_dxf_button,
                enabled=True,
                text="생성 DXF 파일 열기 >>",
                defaults=getattr(self, "_dxf_open_button_defaults", None),
                background=DXF_NEXT_ACTION_BG,
                activebackground=DXF_NEXT_ACTION_ACTIVE_BG,
            )
        if hasattr(self, "dxf_next_action_text_var"):
            self.dxf_next_action_text_var.set(
                "DXF 생성 완료. 4번 [기준층 하중/연속층 적용] 탭에서 생성 DXF를 기준으로 하중을 직접 입력할 수 있습니다."
            )
        self._configure_hatch_work_direct_input_button()

    def _configure_hatch_work_direct_input_button(self) -> None:
        button = self.__dict__.get("open_hatch_work_tab_button")
        if button is None:
            return
        try:
            button.configure(text="4번 탭에서 하중 직접 입력하기 >>")
        except Exception:
            pass
        try:
            button.state(["!disabled"])
        except Exception:
            try:
                button.configure(state="normal")
            except Exception:
                pass

    def _mark_dxf_generated_failed(self, message: str = "") -> None:
        text = "DXF 생성 실패. 로그를 확인하세요."
        if message:
            text = f"DXF 생성 실패: {self._short_ui_message(message)}"
        self._reset_dxf_next_action_state(text)

    def _reset_model_next_action_state(self, message: str = "모델링 파일 생성 중입니다. 완료 후 파일 열기 버튼이 활성화됩니다.") -> None:
        self.last_generated_model_path = None
        if hasattr(self, "generated_model_path"):
            self.generated_model_path.set("")
        if hasattr(self, "open_generated_model_button"):
            self._configure_next_action_button(
                self.open_generated_model_button,
                enabled=False,
                text="생성 모델링 파일 열기",
                defaults=getattr(self, "_model_open_button_defaults", None),
            )
        if hasattr(self, "model_next_action_text_var"):
            self.model_next_action_text_var.set(message)

    def _mark_model_generated_success(self, path: str | Path) -> None:
        generated_path = Path(path)
        self.last_generated_model_path = generated_path
        if hasattr(self, "generated_model_path"):
            self.generated_model_path.set(str(generated_path))
        if hasattr(self, "target_model_path"):
            self.target_model_path.set(str(generated_path))
        if hasattr(self, "open_generated_model_button"):
            self._configure_next_action_button(
                self.open_generated_model_button,
                enabled=True,
                text="생성 모델링 파일 열기 >>",
                defaults=getattr(self, "_model_open_button_defaults", None),
                background=MODEL_NEXT_ACTION_BG,
                activebackground=MODEL_NEXT_ACTION_ACTIVE_BG,
            )
        if hasattr(self, "model_next_action_text_var"):
            self.model_next_action_text_var.set("모델링 파일 생성 완료. 생성 모델링 파일 열기를 눌러 결과 모델을 확인하세요.")

    def _mark_model_generated_failed(self, message: str = "") -> None:
        text = "모델링 파일 생성 실패. 로그를 확인하세요."
        if message:
            text = f"모델링 파일 생성 실패: {self._short_ui_message(message)}"
        self._reset_model_next_action_state(text)

    def _mark_model_not_generated(self, message: str = "모델링 파일은 생성되지 않았습니다.") -> None:
        self._reset_model_next_action_state(message)

    def _set_progress(self, percent: float, message: str = "") -> None:
        try:
            value = max(0.0, min(100.0, float(percent)))
        except Exception:
            value = 0.0
        self.progress_var.set(value)
        self.progress_percent_var.set(f"{value:.0f}%")
        if message:
            self.progress_text_var.set(message)
        try:
            self.update_idletasks()
        except Exception:
            pass

    def _start_progress(self, message: str) -> None:
        self._set_progress(0.0, message)

    def _finish_progress(self, message: str = "완료") -> None:
        self._set_progress(100.0, message)

    def _error_progress(self, message: str = "오류") -> None:
        self.progress_text_var.set(message)
        try:
            self.update_idletasks()
        except Exception:
            pass

    # ---------------------------------------------------------------- actions
    def _client(self) -> MidasGenApiClient:
        cfg = self._current_config()
        return MidasGenApiClient(cfg.resolved_base_url, cfg.mapi_key, timeout_seconds=cfg.timeout_seconds, verify_ssl=cfg.verify_ssl, logger=self.logger)

    def _current_config(self) -> AppConfig:
        return AppConfig(
            base_url=self.base_url_var.get(),
            port=self.port_var.get(),
            mapi_key=self.mapi_key_var.get(),
            timeout_seconds=int(self.timeout_var.get()),
            verify_ssl=bool(self.verify_ssl_var.get()),
            story_tolerance=float(self.story_tol_var.get() if hasattr(self, "story_tol_var") else self.config_data.story_tolerance),
            default_hatch_scale=1.0,
            snap_tolerance=float(self.snap_tol_var.get() if hasattr(self, "snap_tol_var") else self.config_data.snap_tolerance),
            continuous_projection_min_coverage=float(
                getattr(self.config_data, "continuous_projection_min_coverage", 0.995)
            ),
            continuous_projection_max_overreach_ratio=float(
                getattr(self.config_data, "continuous_projection_max_overreach_ratio", 0.005)
            ),
            include_zero_load=bool(self.include_zero_var.get() if hasattr(self, "include_zero_var") else self.config_data.include_zero_load),
            auto_load_dm_dummy_members=bool(
                self.auto_load_dm_dummy_var.get()
                if hasattr(self, "auto_load_dm_dummy_var")
                else self.config_data.auto_load_dm_dummy_members
            ),
            mgt_import_capability_profile=self.config_data.mgt_import_capability_profile,
            floorload_max_logical_fields=self.config_data.floorload_max_logical_fields,
            strict_post_import_verification=self.config_data.strict_post_import_verification,
            remove_failed_model_file=self.config_data.remove_failed_model_file,
        )

    def _update_model_unit_state(self, mgt_text: str) -> None:
        unit_info = parse_unit_from_text(mgt_text)
        model_length_unit = unit_info.length or "UNKNOWN"
        scale = dxf_unit_scale_from_model_length_unit(unit_info.length)
        self.model_unit_info = unit_info
        self.model_length_unit_var.set(model_length_unit)
        self.dxf_unit_scale_var.set(scale)
        self.dxf_unit_status_var.set(
            f"Model unit {model_length_unit} -> DXF mm scale {_format_scale_for_ui(scale)}. Metadata converts back on import."
        )

    def save_current_config(self) -> None:
        path = save_config(self._current_config())
        self.log(f"설정을 저장했습니다: {path}")

    def test_api(self) -> None:
        self.run_worker("API 연결 테스트", lambda: self._client().health_check())

    def select_model_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("MIDAS model", "*.mgb *.mgbx *.mcb"), ("All files", "*.*")])
        if path:
            self.model_path.set(path)
            self._ensure_current_project_workspace(Path(path).stem)
            default = self.current_project_subdirs["models"] / f"{Path(path).stem}_floorload_added.mgbx"
            self.target_model_path.set(str(default))

    def select_mgt_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("MIDAS text", "*.mgt *.mgtx *.mct"), ("All files", "*.*")])
        if path:
            self.exported_mgt_path.set(path)
            self._ensure_current_project_workspace(Path(path).stem)

    def select_pdf_files(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf"), ("All files", "*.*")])
        if not paths:
            return
        had_pdf_source = bool(self.selected_pdf_paths or self.pdf_load_items)
        for path in paths:
            p = Path(path)
            if p not in self.selected_pdf_paths:
                self.selected_pdf_paths.append(p)
        if not self.current_project_dir:
            self._ensure_current_project_workspace()
        if not had_pdf_source:
            self._apply_pdf_present_default_selection()
        self._refresh_pdf_listbox()

    def clear_pdf_files(self) -> None:
        self.selected_pdf_paths.clear()
        self.pdf_import_result = None
        self.pdf_mgtx_path.set("")
        self.pdf_load_items = []
        self.pdf_load_vars = {}
        if not self.load_selection_user_dirty:
            self._set_all_load_vars(self.model_load_items, self.model_load_vars, True)
            self.load_selection_default_mode = "MODEL_ONLY_AUTO_SELECTED"
        else:
            self.load_selection_default_mode = "USER_MANUAL"
        self.load_selection_source_signature = self._load_selection_signature()
        self._refresh_pdf_listbox()
        self._refresh_pdf_tree([])
        self._refresh_pdf_load_lines_listbox()
        self._refresh_pdf_load_checklist()
        self._sync_final_load_list()
        self.pdf_summary_label.configure(text="PDF 분석 결과: -")

    def open_pdf_tab(self) -> None:
        self._ensure_pdf_tab_visible(select=True)

    def recheck_floorload_presence(self) -> None:
        path = self.exported_mgt_path.get().strip()
        if not path:
            messagebox.showwarning("MGT 없음", "먼저 모델을 API로 열어 MGT를 export하거나 MGT 파일을 직접 읽어 주세요.")
            return

        def job(progress):
            progress.update(15.0, "MGT 파일 읽는 중")
            _stories, _nodes, _elements, text = parse_mgt_file(path)
            self.current_mgt_text = text
            self._invalidate_story_below_allowed_polygon_cache("MGT 재분석")
            self._update_model_unit_state(text)
            progress.update(55.0, "FLOOR LOAD 존재 여부 분석 중")
            presence = detect_floor_load_presence_from_text(text)
            progress.update(80.0, "하중 목록 갱신 중")
            self.queue.put(("floorload_status", presence))
            self.queue.put(("model_load_items", self._model_specs_from_mgt_text(text)))
            return presence.message

        self.run_worker("FLOOR LOAD 재분석", job)

    def run_pdf_analysis(self) -> None:
        if not self.selected_pdf_paths:
            messagebox.showwarning("PDF 없음", "분석할 구조계산서 PDF를 먼저 추가해 주세요.")
            return

        def job(progress):
            progress.update(10.0, "PDF 분석 작업 폴더 준비 중")
            project_dir = self._ensure_current_project_workspace()
            model_stem = safe_filename(project_dir.name)
            pdf_jobs_dir = self.current_project_subdirs["pdf_jobs"]
            progress.update(25.0, "PDF 하중 분석 중")
            result = run_pdf_load_import(
                pdf_paths=self.selected_pdf_paths,
                root_dir=self.root_dir,
                output_root=pdf_jobs_dir,
                job_name=f"{model_stem}_pdf_load",
            )
            progress.update(80.0, "PDF 분석 결과 정리 중")
            self.pdf_import_result = result
            if result.mgtx_path:
                self.pdf_mgtx_path.set(str(result.mgtx_path))
                default_merge = self.current_project_subdirs["mgt"] / f"{model_stem}_pdf_load_types_merged.mgt"
                self.pdf_merge_output_path.set(str(default_merge))
            self.queue.put(("pdf_rows", result))
            progress.update(90.0, "PDF 결과 UI 반영 중")
            valid_count = len(result.valid_rows)
            error_count = len(result.error_rows)
            return f"PDF 분석 완료: 유효 {valid_count}개, 검토/제외 {error_count}개, MGTX={result.mgtx_path or '생성 안 됨'}"

        self.run_worker("PDF 하중 분석", job)

    def apply_pdf_loads_to_dxf_layers(self) -> None:
        if not self.pdf_load_items:
            messagebox.showwarning("적용 대상 없음", "먼저 PDF 분석을 실행하고 유효한 Floor Load Type을 생성해 주세요.")
            return
        self.pdf_load_all_var.set(True)
        self._toggle_all_pdf_loads()
        messagebox.showinfo("PDF 하중목록 선택", "PDF 하중목록을 최종 적용 하중목록에 선택했습니다.")
        self._ensure_pdf_tab_visible(select=False)

    def merge_pdf_mgtx_to_current_mgt(self) -> None:
        source_mgt = self.exported_mgt_path.get().strip()
        pdf_mgtx = self.pdf_mgtx_path.get().strip()
        output_mgt = self.pdf_merge_output_path.get().strip()
        if not output_mgt:
            project_dir = self._ensure_current_project_workspace()
            model_stem = safe_filename(project_dir.name)
            output_mgt = str(self.current_project_subdirs["mgt"] / f"{model_stem}_pdf_load_types_merged.mgt")
            self.pdf_merge_output_path.set(output_mgt)
        if not source_mgt:
            messagebox.showwarning("MGT 없음", "먼저 모델 MGT를 export하거나 직접 읽어 주세요.")
            return
        if not pdf_mgtx:
            messagebox.showwarning("PDF MGTX 없음", "먼저 PDF 분석 및 MGTX 생성을 실행해 주세요.")
            return
        if not output_mgt:
            messagebox.showwarning("출력 경로 없음", "병합 출력 MGT 경로가 비어 있습니다.")
            return

        def job(progress):
            progress.update(15.0, "PDF MGTX 병합 중")
            result = merge_pdf_mgtx_into_full_mgt(
                source_mgt_path=source_mgt,
                pdf_mgtx_path=pdf_mgtx,
                output_mgt_path=output_mgt,
                collision_mode="skip_existing",
            )
            progress.update(60.0, "병합 MGT 다시 읽는 중")
            self.exported_mgt_path.set(str(result.output_mgt_path))
            _stories, _nodes, _elements, text = parse_mgt_file(result.output_mgt_path)
            self.current_mgt_text = text
            self._invalidate_story_below_allowed_polygon_cache("PDF MGTX 병합")
            self._update_model_unit_state(text)
            progress.update(80.0, "병합 결과 분석 중")
            presence = detect_floor_load_presence_from_text(text)
            self.queue.put(("floorload_status", presence))
            self.queue.put(("model_load_items", self._model_specs_from_mgt_text(text)))
            self.queue.put(("auto_floorload_diagnostics", {"reason": "PDF MGTX 병합 완료"}))
            return (
                f"PDF 하중 타입 병합 완료: {result.output_mgt_path}\n"
                f"추가 STLDCASE {result.added_stldcase_count}개, 추가 FLOADTYPE {result.added_floadtype_count}개, "
                f"중복 skip FLOADTYPE {len(result.skipped_floadtype_names)}개"
            )

        self.run_worker("PDF MGTX 병합", job)

    def select_user_dxf(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("DXF", "*.dxf"), ("All files", "*.*")])
        if path:
            self._reset_hatch_edit_history("사용자 DXF 새 선택")
            self.user_dxf_path.set(path)
            self.loaded_regions = []
            self._reset_continuous_apply_state(reason="DXF 새로 선택")
            if hasattr(self, "dxf_validation_status_var"):
                self.dxf_validation_status_var.set("DXF 파일이 선택되었습니다. DXF 검증을 실행해 주세요.")
            if hasattr(self, "open_hatch_work_tab_button"):
                self.open_hatch_work_tab_button.state(["disabled"])
            self._render_hatch_preview()

    def select_mapping_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Mapping", "*.json *.csv"), ("All files", "*.*")])
        if path:
            self.mapping_path.set(path)

    def select_layout_metadata_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Layout metadata", "*.layout_metadata.json *.json"), ("All files", "*.*")])
        if path:
            self.layout_metadata_path.set(path)

    def auto_find_layout_metadata(self) -> None:
        dxf = self.user_dxf_path.get().strip()
        if not dxf:
            messagebox.showwarning("DXF 선택", "먼저 사용자 작성 DXF 파일을 선택해 주세요.")
            return
        selected = self._resolve_layout_metadata_for_dxf(dxf, allow_prompt=True)
        if selected:
            messagebox.showinfo("layout metadata", f"layout metadata를 선택했습니다.\n\n{selected}")
        else:
            messagebox.showinfo("layout metadata", "자동으로 선택할 layout metadata가 없습니다. 단일층 DXF라면 그대로 진행해도 됩니다.")

    def select_target_model(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".mgbx",
            filetypes=[("MIDAS Gen NX Binary", "*.mgbx"), ("MIDAS Gen Binary", "*.mgb"), ("All files", "*.*")],
        )
        if path:
            self.target_model_path.set(str(_mgbx_path(path)))

    def open_model_and_export(self) -> None:
        model = self.model_path.get().strip()
        if not model:
            messagebox.showwarning("모델 선택", "모델 파일을 먼저 선택해 주세요.")
            return

        def job(progress):
            progress.update(10.0, "MIDAS API 클라이언트 준비 중")
            client = self._client()
            progress.update(25.0, "모델 열기 중")
            client.open_project(model)
            progress.update(45.0, "MGT Export 준비 중")
            self._ensure_current_project_workspace(Path(model).stem)
            out = self.current_project_subdirs["mgt"] / f"{Path(model).stem}_exported.mgt"
            progress.update(60.0, "MGT Export 요청 중")
            client.export_mgt(out)
            progress.update(75.0, "MGT 파일 파싱 중")
            self.exported_mgt_path.set(str(out))
            self._load_mgt_snapshot_impl(out, progress=progress)
            return f"모델 열기 및 MGT export 완료: {out}"

        self.run_worker("모델 열기/MGT Export", job)

    def load_mgt_snapshot(self) -> None:
        path = self.exported_mgt_path.get().strip()
        if not path:
            messagebox.showwarning("MGT 선택", "MGT/MGTX 파일을 선택해 주세요.")
            return
        self.run_worker("MGT 읽기", lambda progress: self._load_mgt_snapshot_impl(Path(path), progress=progress))

    def _load_mgt_snapshot_impl(self, path: str | Path, progress: ProgressReporter | None = None):
        if progress:
            progress.update(15.0, "작업 폴더 준비 중")
        if self.current_project_dir:
            self._ensure_current_project_workspace()
        else:
            self._ensure_current_project_workspace(Path(path).stem)
        if progress:
            progress.update(35.0, "MGT 파일 읽는 중")
        stories, nodes, elements, mgt_text = parse_mgt_file(path)
        self.current_mgt_text = mgt_text
        parsed_dummy_members = parse_existing_load_dm_members(mgt_text)
        self.committed_dummy_members = {
            member.element_id: DummyDisplayMember(
                display_key=f"element:{member.element_id}",
                story_name=member.story_name,
                node_i=member.node_i,
                node_j=member.node_j,
                start_xy=member.start_xy,
                end_xy=member.end_xy,
                element_id=member.element_id,
                state="INVALID" if member.warnings else "COMMITTED_EXISTING",
                source="CURRENT_MGT",
                material_id=member.material_id,
                section_id=member.section_id,
                release_added=member.release is not None,
                invalid_reason="; ".join(member.warnings),
            )
            for member in parsed_dummy_members
        }
        self.approved_dummy_plans = {}
        self.dummy_preview_plan = None
        self.selected_dummy_issue_key = None
        self.dummy_overlay_render_fingerprint = None
        self._update_model_unit_state(mgt_text)
        if not stories:
            raise RuntimeError("Story 정보가 없습니다. MGT의 *STORY 블록 또는 API STOR 데이터를 확인해 주세요.")
        if progress:
            progress.update(70.0, "Story/Node/Element 반영 중")
        self._reset_hatch_edit_history("MGT/model reload")
        self.stories = stories
        self.nodes = nodes
        self.elements = elements
        self.hatch_edit_states_by_story = {}
        self.hatch_view_edit_region_by_key = {}
        self.hatch_view_selected_edit_region_keys = set()
        self._hatch_edit_state_geometry_token_by_story = {}
        self._invalidate_story_below_allowed_polygon_cache("MGT 모델 로드")
        self.queue.put(("stories", stories))
        if progress:
            progress.update(85.0, "FLOOR LOAD 존재 여부 분석 중")
        self.queue.put(("floorload_status", detect_floor_load_presence_from_text(mgt_text)))
        self.queue.put(("model_load_items", self._model_specs_from_mgt_text(mgt_text)))
        self.queue.put(("auto_floorload_diagnostics", {"reason": "MGT 로드 완료"}))
        return f"Story {len(stories)}개, Node {len(nodes)}개, Element {len(elements)}개를 읽었습니다."

    def _floorload_diag_signature(self) -> str:
        text = str(getattr(self, "current_mgt_text", "") or "")
        return f"{len(self.stories)}:{len(self.nodes)}:{len(self.elements)}:{hash(text[:10000])}"

    def _start_auto_floorload_diagnostics(self, *, reason: str = "") -> None:
        if getattr(self, "_busy", False):
            self.after(500, lambda: self._start_auto_floorload_diagnostics(reason=reason))
            return
        if not self.nodes or not self.elements or not self.stories:
            return
        signature = self._floorload_diag_signature()
        if signature == getattr(self, "last_auto_floorload_diag_signature", None):
            return
        self.last_auto_floorload_diag_signature = signature
        self.log(f"FLOORLOAD 자동 진단 시작: {reason or '모델 데이터 갱신'}")
        self.run_floorload_diagnostics(auto=True)

    def on_story_select(self, _event=None) -> None:
        sel = self.story_tree.selection()
        if not sel:
            return
        values = self.story_tree.item(sel[0], "values")
        if values:
            self.selected_story_name.set(str(values[0]))
            self.log(f"Story 선택: {values[0]}")

    def _reset_typical_floor_state(self, *, reason: str = "") -> None:
        self.typical_floor_analysis = None
        self.typical_floor_groups = ()
        self.story_shape_profiles = ()
        self._reset_continuous_apply_state(reason=reason or "기준층 분석 초기화")
        if hasattr(self, "typical_analysis_summary_var"):
            self.typical_analysis_summary_var.set("층 형상 분석 전입니다.")

    def _reset_continuous_apply_state(self, *, reason: str = "") -> None:
        if hasattr(self, "_cancel_continuous_tree_drag"):
            self._cancel_continuous_tree_drag(restore_initial=False)
        self.continuous_apply_targets = {}
        self.continuous_apply_targets_by_region = {}
        self.continuous_materialized_targets_by_region = {}
        self.continuous_hatch_checks = {}
        self._invalidate_continuous_below_allowed_reason_cache(reason or "연속층 상태 초기화")
        self.hatch_view_region_items = {}
        self.hatch_view_checkbox_items = {}
        self.hatch_view_region_by_key = {}
        self.hatch_view_selected_region_key = None
        self.dxf_tree_iid_by_region_key = {}
        self.continuous_candidate_by_iid = {}
        self.continuous_ordered_iids = []
        self.continuous_story_anchor_iid = None
        self.continuous_active_region_key = None
        if hasattr(self, "continuous_apply_status_var"):
            self._set_continuous_status("연속층 적용 전입니다." if not reason else f"연속층 적용 상태 초기화: {reason}")

    def _ensure_typical_floor_analysis(
        self,
        *,
        reason: str = "",
        story_penalties: dict[str, float] | None = None,
        force: bool = False,
    ) -> bool:
        if not force and self.typical_floor_analysis is not None and self.story_shape_profiles:
            return True
        if not self.stories or not self.nodes or not self.elements:
            self.logger.warning("typical floor analysis skipped: model data missing (%s)", reason)
            return False
        try:
            xy_tolerance = float(self.snap_tol_var.get() if hasattr(self, "snap_tol_var") else self.config_data.snap_tolerance)
            result = analyze_typical_floors(
                stories=self.stories,
                nodes=self.nodes,
                elements=self.elements,
                mgt_text=self.current_mgt_text or None,
                story_penalties=story_penalties,
                story_tolerance=float(self.story_tol_var.get() if hasattr(self, "story_tol_var") else self.config_data.story_tolerance),
                xy_tolerance=xy_tolerance,
            )
        except Exception as exc:  # noqa: BLE001 - auto helper must not block parent workflow
            self.logger.warning("typical floor auto analysis failed (%s): %s", reason, exc)
            try:
                self.queue.put(("log", f"층 형상 분석 실패({reason or '자동'}): {exc}"))
            except Exception:
                pass
            return False
        self.typical_floor_analysis = result
        self.typical_floor_groups = tuple(getattr(result, "groups", ()) or ())
        self.story_shape_profiles = tuple(getattr(result, "profiles", ()) or ())
        try:
            self.queue.put(("typical_analysis", result))
        except Exception:
            self._refresh_typical_floor_analysis(result)
        return True

    def run_typical_floor_analysis(self) -> None:
        # Kept for internal/test compatibility; the user workflow runs this analysis automatically.
        if not self.stories or not self.nodes or not self.elements:
            messagebox.showwarning("Model data missing", "Load MGT/API model data before typical floor analysis.")
            return

        def job(progress):
            progress.update(20.0, "Building story shape profiles")
            ok = self._ensure_typical_floor_analysis(reason="수동 실행", force=True)
            if not ok or self.typical_floor_analysis is None:
                raise RuntimeError("층 형상 분석을 완료하지 못했습니다. 로그를 확인하세요.")
            typical_names = ", ".join(typical_story_names(self.typical_floor_groups)) or "none"
            transition_count = sum(len(group.transition_floor_names) for group in self.typical_floor_groups)
            return f"Typical floor analysis complete: groups={len(self.typical_floor_groups)}, typ={typical_names}, transitions={transition_count}"

        self.run_worker("Typical floor analysis", job)

    def create_all_story_dxf_template(self) -> None:
        self.selected_story_name.set(ALL_STORIES_LABEL)
        self.create_dxf_template()

    def create_dxf_template(self) -> None:
        story_mode, story = self._selected_dxf_story_mode()
        if story_mode != ALL_STORIES_VALUE and not story:
            messagebox.showwarning("Story 선택", "Story를 먼저 선택해 주세요.")
            return
        if not self.nodes or not self.elements:
            messagebox.showwarning("모델 데이터 없음", "MGT export 또는 MGT 직접 읽기를 먼저 실행해 주세요.")
            return
        specs = self._load_layer_specs()
        if not specs:
            messagebox.showwarning(
                "최종 적용 하중목록 없음",
                "최종 적용 하중목록이 비어 있습니다. 모델링 입력 하중목록 또는 PDF 하중목록에서 적용할 하중을 체크해 주세요.",
            )
            return
        self._reset_dxf_next_action_state()
        model_length_unit = self.model_length_unit_var.get()
        dxf_unit_scale = float(self.dxf_unit_scale_var.get() or 1.0)

        def job(progress):
            progress.update(10.0, "DXF 생성 작업 폴더 준비 중")
            model_name = Path(self.model_path.get() or self.exported_mgt_path.get() or "model").stem
            self._ensure_current_project_workspace()
            out_dir = self.current_project_subdirs["dxf_templates"]
            test_path = out_dir / ".write_test.tmp"
            try:
                progress.update(20.0, "DXF 출력 권한 확인 중")
                test_path.write_text("test", encoding="utf-8")
                if test_path.exists():
                    test_path.unlink()
            except PermissionError as exc:
                raise PermissionError(
                    "DXF 출력 폴더에 쓰기 권한이 없습니다. "
                    "프로그램 폴더를 관리자 권한이 필요한 위치가 아닌 바탕화면/문서/일반 작업 폴더로 옮긴 뒤 다시 실행해 주세요.\n"
                    f"출력 폴더: {out_dir}"
                ) from exc

            story_part = "ALL_STORIES" if story_mode == ALL_STORIES_VALUE else story.name
            base_out = out_dir / f"{safe_filename(model_name)}_{safe_filename(story_part)}_floorload_template.dxf"
            out = unique_output_path(base_out)
            if not self.typical_floor_groups:
                progress.update(30.0, "층 형상 분석 확인 중")
                if not self._ensure_typical_floor_analysis(reason="DXF 생성 전 typ. 보장"):
                    self.queue.put(("log", "층 형상 분석을 완료하지 못해 typ. 표시 없이 DXF를 생성합니다."))
            if story_mode == ALL_STORIES_VALUE:
                progress.update(35.0, "전체 Story DXF geometry 생성 중")
                result = write_all_story_centerline_dxf(
                    output_path=out,
                    stories=self.stories,
                    nodes=self.nodes,
                    elements=self.elements,
                    load_layers=specs,
                    story_tolerance=float(self.story_tol_var.get()),
                    model_length_unit=model_length_unit,
                    dxf_unit_scale_from_model=dxf_unit_scale,
                    typical_floor_groups=self.typical_floor_groups,
                )
            else:
                progress.update(35.0, "Story center line DXF geometry 생성 중")
                result = write_story_centerline_dxf(
                    output_path=out,
                    story=story,
                    stories=self.stories,
                    nodes=self.nodes,
                    elements=self.elements,
                    load_layers=specs,
                    story_tolerance=float(self.story_tol_var.get()),
                    model_length_unit=model_length_unit,
                    dxf_unit_scale_from_model=dxf_unit_scale,
                    typical_floor_groups=self.typical_floor_groups,
                )
            progress.update(90.0, "DXF 템플릿 결과 정리 중")
            return result

        self.run_worker("DXF 템플릿 생성", job)

    def validate_user_dxf(self) -> None:
        dxf = self.user_dxf_path.get().strip()
        if not dxf:
            messagebox.showwarning("DXF 선택", "사용자가 작성한 DXF 파일을 선택해 주세요.")
            return
        if self._loaded_internal_hatch_regions():
            keep_internal = self._confirm_keep_internal_regions_for_dxf_validation()
            if keep_internal:
                self.log("사용자 DXF 재검증: 기존 HATCH VIEW 직접 입력 영역을 유지합니다.")
            else:
                self.hatch_edit_states_by_story = {}
                self.hatch_view_selected_edit_region_keys = set()
                self._hatch_edit_state_geometry_token_by_story = {}
                self.log("사용자 DXF 재검증: 기존 HATCH VIEW 직접 입력 영역을 초기화했습니다.")
                self._render_hatch_preview()
        layout_metadata = self._resolve_layout_metadata_for_dxf(dxf, allow_prompt=True)

        def job(progress):
            progress.update(15.0, "DXF 검증 작업 폴더 준비 중")
            self._ensure_current_project_workspace()
            progress.update(30.0, "DXF HATCH/Polyline 읽는 중")
            regions = read_load_regions(
                dxf,
                mapping_path=self.mapping_path.get().strip() or None,
                layout_metadata_path=layout_metadata,
                project_dxf_templates_dir=self.current_project_subdirs["dxf_templates"],
            )
            progress.update(80.0, "DXF 검증 결과 반영 중")
            self.loaded_regions = regions
            self.queue.put(("regions", regions))
            if not regions:
                raise RuntimeError("선택한 DXF에서 하중 해치를 찾지 못했습니다. 하중 영역을 HATCH로 작성하거나 폐합 Polyline을 사용해 주세요.")
            progress.update(90.0, "DXF 검증 요약 생성 중")
            return _format_dxf_validation_summary(regions)

        self.run_worker("DXF 검증", job)

    def _confirm_keep_internal_regions_for_dxf_validation(self) -> bool:
        try:
            return bool(
                messagebox.askyesno(
                    "HATCH VIEW 직접 입력 영역",
                    (
                        "새 사용자 DXF를 검증하면 기존 HATCH VIEW 직접 입력 영역과 중복될 수 있습니다.\n"
                        "기존 직접 입력 영역을 유지하시겠습니까?\n\n"
                        "[예] 유지\n[아니오] 초기화"
                    ),
                    default="yes",
                )
            )
        except Exception:
            return True

    def run_floorload_diagnostics(self, *, auto: bool = False) -> None:
        if not self.nodes or not self.elements or not self.stories:
            if auto:
                self.log("FLOORLOAD 자동 진단 생략: 모델 데이터가 아직 없습니다.")
            else:
                messagebox.showwarning("모델 데이터 없음", "먼저 API로 모델을 열거나 MGT/MGTX에서 Story, Node, Element를 읽어 주세요.")
            return

        def job(progress):
            try:
                progress.update(15.0, "진단 작업 폴더 준비 중")
                self._ensure_current_project_workspace()
                reports_dir = self.current_project_subdirs["reports"]
                progress.update(30.0, "FLOORLOAD 모델링 진단 중")
                mgt_text = self.current_mgt_text
                if not mgt_text and self.exported_mgt_path.get().strip():
                    try:
                        mgt_text = read_text(self.exported_mgt_path.get().strip())
                    except Exception:
                        mgt_text = ""
                result = analyze_floorload_model(
                    nodes=self.nodes,
                    elements=self.elements,
                    stories=self.stories,
                    mgt_text=mgt_text,
                    planned_load_regions=self.loaded_regions,
                    story_tolerance=float(self.story_tol_var.get()),
                    snap_tolerance=float(self.snap_tol_var.get() if hasattr(self, "snap_tol_var") else self.config_data.snap_tolerance),
                    allowed_story_polygons_by_name=self._story_below_allowed_polygons_by_name(
                        self._planned_region_story_names(self.loaded_regions, ())
                    ),
                )
                issues = result.issues
                penalties = _diagnostic_penalty_by_story(issues)
                if penalties:
                    progress.update(62.0, "진단 penalty 기반 기준층 분석 갱신 중")
                    self._ensure_typical_floor_analysis(reason="FLOORLOAD 진단 penalty 반영", story_penalties=penalties, force=True)
                elif not self.story_shape_profiles:
                    progress.update(62.0, "층 형상 분석 확인 중")
                    self._ensure_typical_floor_analysis(reason="FLOORLOAD 진단 실행")
                progress.update(70.0, "진단 보고서 저장 중")
                json_path, csv_path = write_diagnostic_reports(result, reports_dir)
                progress.update(85.0, "진단 DXF 생성 중")
                dxf_path = write_floorload_diagnostic_dxf(
                    output_path=reports_dir / "floorload_diagnostics_all.dxf",
                    issues=issues,
                    nodes=self.nodes,
                    elements=self.elements,
                    stories=self.stories,
                    story_tolerance=float(self.story_tol_var.get()),
                )
                self.last_diagnostic_dxf_path = dxf_path
                self.last_diagnostic_report_path = csv_path
                self.queue.put(("diagnostics", result))
                progress.update(92.0, "진단 결과 UI 반영 중")
                return f"FLOORLOAD 모델링 진단 완료: {len(issues)}개 이슈\nDXF: {dxf_path}\nCSV: {csv_path}\nJSON: {json_path}"
            except Exception as exc:
                if auto:
                    self.queue.put(("log", f"FLOORLOAD 자동 진단 실패(모델 로드는 유지): {exc}"))
                    return f"FLOORLOAD 자동 진단 실패(모델 로드는 유지): {exc}"
                raise

        title = "FLOORLOAD 모델링 진단(자동)" if auto else "FLOORLOAD 모델링 진단"
        self.run_worker(title, job)

    def build_mgt_only(self) -> None:
        self._build_pipeline(import_to_midas=False)

    def build_and_import(self) -> None:
        self._build_pipeline(import_to_midas=True)

    def _build_pipeline(self, *, import_to_midas: bool) -> None:
        story_mode, story = self._selected_dxf_story_mode()
        if story_mode == ALL_STORIES_VALUE:
            story = Story("ALL_STORIES", 0.0)
        if not story:
            messagebox.showwarning("Story 선택", "Story를 먼저 선택해 주세요.")
            return
        mgt = self.exported_mgt_path.get().strip()
        dxf = self.user_dxf_path.get().strip()
        generated_dxf = str(self.generated_dxf_path.get()).strip() if hasattr(self, "generated_dxf_path") else ""
        internal_regions = self._loaded_internal_hatch_regions()
        if not mgt:
            messagebox.showwarning("MGT 없음", "기존 모델 MGT export 또는 MGT 직접 읽기를 먼저 실행해 주세요.")
            return
        if not dxf and not internal_regions:
            messagebox.showwarning("DXF 없음", "DXF HATCH를 검증하거나 HATCH VIEW에서 폐합 영역을 선택해 하중을 적용해 주세요.")
            return
        layout_metadata = self.layout_metadata_path.get().strip() or None
        if dxf and not self.loaded_regions:
            layout_metadata = self._resolve_layout_metadata_for_dxf(dxf, allow_prompt=True)
        if import_to_midas:
            self._reset_model_next_action_state()
        else:
            self._mark_model_not_generated("API import 없이 full MGT만 생성하는 작업입니다. 모델링 파일 열기 버튼은 비활성화됩니다.")

        def job(progress):
            import_config = self.__dict__.get("config_data") or AppConfig()
            progress.update(10.0, "MGT 생성 작업 폴더 준비 중")
            self._ensure_current_project_workspace()
            progress.update(20.0, "DXF 하중 영역 확인 중")
            regions = list(self.loaded_regions or [])
            if not regions and dxf:
                regions = read_load_regions(
                    dxf,
                    mapping_path=self.mapping_path.get().strip() or None,
                    layout_metadata_path=layout_metadata,
                    project_dxf_templates_dir=self.current_project_subdirs["dxf_templates"],
                )
            progress.update(35.0, "Story node set 준비 중")
            regions = self._regions_with_continuous_apply(regions)
            reports_dir = self.current_project_subdirs["reports"]
            self._write_hatch_view_input_state_snapshot(
                reports_dir,
                dxf_regions=regions,
                internal_regions=internal_regions,
                model_name=Path(self.model_path.get() or mgt).name,
                source_dxf_path=dxf or generated_dxf,
                layout_metadata_path=layout_metadata or "",
            )
            story_nodes_by_name = None
            has_story_regions = any(getattr(region.region, "story_name", "") for region in regions) or any(
                getattr(region, "story_name", "") for region in internal_regions
            )
            if has_story_regions:
                story_nodes_by_name = {
                    item.name: select_nodes_by_story(self.nodes, item.elevation, float(self.story_tol_var.get()))
                    for item in self.stories
                }
                story_nodes = list(self.nodes)
            else:
                story_nodes = select_nodes_by_story(self.nodes, story.elevation, float(self.story_tol_var.get()))
            if not story_nodes:
                raise RuntimeError("선택 Story Level의 노드가 없습니다. Story tolerance 또는 선택 Story를 확인해 주세요.")
            allowed_story_polygons_by_name = self._story_below_allowed_polygons_by_name(
                self._planned_region_story_names(regions, internal_regions)
            )
            model_stem = Path(self.model_path.get() or mgt).stem
            mgt_dir = self.current_project_subdirs["mgt"]
            model_dir = self.current_project_subdirs["models"]
            out_mgt = mgt_dir / f"{safe_filename(model_stem)}_{safe_filename(story.name)}_floorload_full.mgt"
            preview = reports_dir / f"{safe_filename(model_stem)}_{safe_filename(story.name)}_floorload_preview.dxf"
            progress.update(50.0, "FLOORLOAD assignment 및 full MGT 생성 중")
            result = run_mgt_build_pipeline(
                source_mgt_path=mgt,
                output_mgt_path=out_mgt,
                report_dir=reports_dir,
                preview_dxf_path=preview,
                model_name=Path(self.model_path.get() or mgt).name,
                story=story,
                dxf_name=Path(dxf or generated_dxf or "HATCH_VIEW_INTERNAL").name,
                regions=regions,
                story_nodes=story_nodes,
                snap_tolerance=float(self.snap_tol_var.get()),
                one_way_shape_tolerance=self._one_way_shape_tolerance(),
                include_zero_load=bool(self.include_zero_var.get()),
                story_nodes_by_name=story_nodes_by_name,
                internal_regions=internal_regions,
                mode="append",
                auto_load_dm_dummy_members=bool(self.auto_load_dm_dummy_var.get()),
                story_tolerance=float(self.story_tol_var.get()),
                allowed_story_polygons_by_name=allowed_story_polygons_by_name,
                approved_dummy_plans=tuple((self.__dict__.get("approved_dummy_plans", {}) or {}).values()),
                capability_profile=import_config.mgt_import_capability_profile,
                floorload_max_logical_fields=import_config.floorload_max_logical_fields,
                strict_import_verification=import_config.strict_post_import_verification,
            )
            progress.update(75.0, "MGT/보고서/검증 DXF 저장 확인 중")
            if getattr(result, "duplicate_removed_count", 0):
                duplicate_message = (
                    f"INTERNAL 직접 입력 영역과 중복되는 DXF 하중 영역 {result.duplicate_removed_count}개를 제외했습니다. "
                    "MGT 생성에는 INTERNAL 영역을 우선 사용합니다."
                )
                self.queue.put(("log", duplicate_message))
                self.queue.put(("dxf_status", duplicate_message))
            dummy_message = ""
            if result.dummy_summary is not None:
                self._commit_dummy_generation_summary(result.dummy_summary)
                dummy_message = "\n" + format_dummy_generation_summary(result.dummy_summary)
                if result.dummy_report_csv_path:
                    dummy_message += f"\nLOAD DM dummy report: {result.dummy_report_csv_path}"
                self.queue.put(("log", dummy_message.strip()))
            if import_to_midas:
                preflight = getattr(result, "import_preflight", None)
                preflight_json_path = getattr(result, "import_preflight_json_path", None)
                if preflight is None:
                    preflight = validate_mgt_for_import(result.full_mgt_path)
                    preflight_json_path, _preflight_csv_path = write_validation_report(preflight, reports_dir)
                if preflight.has_errors:
                    raise MgtPreflightError(preflight, report_path=preflight_json_path)
                target = self.target_model_path.get().strip()
                if not target:
                    target_path = model_dir / f"{safe_filename(model_stem)}_{safe_filename(story.name)}_floorload_added.mgbx"
                else:
                    target_path = _mgbx_path(target)
                target_path = unique_numbered_path(target_path, start=2)
                self.target_model_path.set(str(target_path))
                if not target_path:
                    raise RuntimeError("결과 .mgbx 저장 경로가 비어 있습니다.")
                progress.update(82.0, "MIDAS 새 프로젝트 생성 중")
                client = self._client()
                verification_report_path = reports_dir / "midas_import_verification.json"
                import_verification = None
                saved = None
                try:
                    client.new_project()
                    progress.update(88.0, "MIDAS MGT import 및 DB fingerprint 검증 중")
                    import_verification = client.import_mgt_verified(
                        result.full_mgt_path,
                        preflight.model_fingerprint,
                        poll_timeout_seconds=max(2.0, min(30.0, float(import_config.timeout_seconds))),
                    )
                    if preflight.capabilities.strict_import_verification:
                        progress.update(92.0, "import 모델 임시 MGT export 검증 중")
                        verification_export = reports_dir / f"{safe_filename(model_stem)}_{safe_filename(story.name)}_import_verified.mgt"
                        client.verify_import_by_export(
                            verification_export,
                            preflight.model_fingerprint,
                            capabilities=preflight.capabilities,
                        )
                    progress.update(96.0, "검증된 모델 MGBX 저장 중")
                    saved = client.save_as_project_verified(
                        target_path,
                        expected_fingerprint=preflight.model_fingerprint,
                        remove_failed_file=import_config.remove_failed_model_file,
                    )
                    write_import_verification_report(
                        verification_report_path,
                        status="PASS",
                        source_path=result.full_mgt_path,
                        target_path=target_path,
                        expected_fingerprint=preflight.model_fingerprint,
                        actual_fingerprint=import_verification.actual_fingerprint,
                        api_response=import_verification.import_response,
                        message_ko="MGT import DB fingerprint와 MGBX 저장 파일 검증을 통과했습니다.",
                        saved_file=saved,
                    )
                except Exception as exc:
                    if import_config.remove_failed_model_file and target_path.exists():
                        try:
                            if target_path.stat().st_size <= 0:
                                target_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                    write_import_verification_report(
                        verification_report_path,
                        status="ERROR",
                        source_path=result.full_mgt_path,
                        target_path=target_path,
                        expected_fingerprint=preflight.model_fingerprint,
                        actual_fingerprint=(
                            getattr(import_verification, "actual_fingerprint", None)
                            or getattr(exc, "actual_fingerprint", None)
                        ),
                        api_response=(
                            getattr(import_verification, "import_response", None)
                            or getattr(exc, "import_response", None)
                        ),
                        message_ko=str(exc),
                        action_ko="preflight/DB/export/save 단계별 오류를 확인한 뒤 다시 실행하세요. 실패한 빈 모델은 성공 결과로 사용하지 않습니다.",
                        saved_file=target_path,
                    )
                    raise
                return BuildPipelineUiResult(
                    f"full MGT 생성, MIDAS import 검증 및 새 모델 저장 완료\nMGT: {result.full_mgt_path}\n모델: {saved}\n보고서: {result.report_xlsx_path}\nMGT preflight: {preflight_json_path}\nMIDAS 검증: {verification_report_path}\n검증 DXF: {result.preview_dxf_path}",
                    generated_model_path=saved,
                )
            return BuildPipelineUiResult(
                f"full MGT 생성 완료(API import 미실행)\nMGT: {result.full_mgt_path}\n보고서: {result.report_xlsx_path}\n검증 DXF: {result.preview_dxf_path}"
            )

        self.run_worker("MGT 생성/import" if import_to_midas else "MGT 생성", job)

    def launch_legacy_v3(self) -> None:
        app_path = self.root_dir / "legacy_v3" / "streamlit_app.py"
        if not app_path.exists():
            messagebox.showerror("v3 없음", f"기존 v3 Streamlit 앱을 찾지 못했습니다: {app_path}")
            return
        try:
            subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(app_path)], cwd=str(self.root_dir))
            self.log("기존 v3 Streamlit 앱 실행을 요청했습니다.")
        except Exception as exc:
            messagebox.showerror("실행 실패", str(exc))

    # -------------------------------------------------------------- helpers
    def _model_specs_from_mgt_text(self, text: str) -> list[FloorLoadTypeSpec]:
        specs = parse_floadtype_specs_from_text(text)
        if specs:
            return specs
        return [FloorLoadTypeSpec(name=name) for name in parse_floorload_type_names_from_text(text)]

    def _make_load_item(self, source: str, name: str, dl: float, ll: float, index: int | None = None) -> dict:
        source_text = str(source or "").upper()
        clean_name = str(name or "").strip() or "이름없음"
        dl_value = float(dl or 0.0)
        ll_value = float(ll or 0.0)
        index_part = "" if index is None else f"::{index}"
        return {
            "key": f"{source_text}::{clean_name}::{dl_value:g}::{ll_value:g}{index_part}",
            "source": source_text,
            "name": clean_name,
            "dl": dl_value,
            "ll": ll_value,
            "line": self._format_load_line(clean_name, dl_value, ll_value),
        }

    def _format_load_line(self, name: str, dl: float, ll: float) -> str:
        return f"{name}, DL:{float(dl):.2f} LL:{float(ll):.2f}"

    def _toggle_all_model_loads(self) -> None:
        self._mark_load_selection_user_dirty()
        checked = bool(self.model_load_all_var.get())
        for item in self.model_load_items:
            key = str(item["key"])
            if key not in self.model_load_vars:
                self.model_load_vars[key] = tk.BooleanVar(value=checked)
            self.model_load_vars[key].set(checked)
        self._refresh_model_load_checklist()
        self._sync_final_load_list()

    def _toggle_all_pdf_loads(self) -> None:
        self._mark_load_selection_user_dirty()
        checked = bool(self.pdf_load_all_var.get())
        for item in self.pdf_load_items:
            key = str(item["key"])
            if key not in self.pdf_load_vars:
                self.pdf_load_vars[key] = tk.BooleanVar(value=checked)
            self.pdf_load_vars[key].set(checked)
        self._refresh_pdf_load_checklist()
        self._sync_final_load_list()

    def _update_all_select_vars(self) -> None:
        if self.model_load_items:
            self.model_load_all_var.set(
                all(
                    self.model_load_vars.get(str(item["key"])) is not None
                    and bool(self.model_load_vars[str(item["key"])].get())
                    for item in self.model_load_items
                )
            )
        else:
            self.model_load_all_var.set(False)

        if self.pdf_load_items:
            self.pdf_load_all_var.set(
                all(
                    self.pdf_load_vars.get(str(item["key"])) is not None
                    and bool(self.pdf_load_vars[str(item["key"])].get())
                    for item in self.pdf_load_items
                )
            )
        else:
            self.pdf_load_all_var.set(False)

    def _refresh_model_load_checklist(self) -> None:
        if not hasattr(self, "model_load_check_frame"):
            return
        self._refresh_load_checklist(
            self.model_load_check_frame,
            self.model_load_items,
            self.model_load_vars,
            "모델링에 입력된 Floor Load Type이 없습니다.",
        )

    def _refresh_pdf_load_checklist(self) -> None:
        if not hasattr(self, "pdf_load_check_frame"):
            return
        self._refresh_load_checklist(
            self.pdf_load_check_frame,
            self.pdf_load_items,
            self.pdf_load_vars,
            "PDF에서 분석된 하중목록이 없습니다.",
        )

    def _refresh_load_checklist(self, parent: tk.Widget, items: list[dict], vars_by_key: dict[str, tk.BooleanVar], empty_text: str) -> None:
        for child in parent.winfo_children():
            child.destroy()
        if not items:
            ttk.Label(parent, text=empty_text, foreground="gray", wraplength=320).pack(anchor="w", padx=3, pady=3)
            return
        valid_keys = {str(item["key"]) for item in items}
        for key in list(vars_by_key):
            if key not in valid_keys:
                vars_by_key.pop(key, None)
        for item in items:
            key = str(item["key"])
            var = vars_by_key.get(key)
            if var is None:
                var = tk.BooleanVar(value=False)
                vars_by_key[key] = var
            tk.Checkbutton(
                parent,
                text=str(item["line"]),
                variable=var,
                command=self._on_load_selection_changed,
                anchor="w",
                justify="left",
                wraplength=320,
                padx=1,
                pady=0,
            ).pack(fill="x", anchor="w", padx=2, pady=0)

    def _sync_final_load_list(self) -> None:
        self._update_all_select_vars()
        self.final_load_items = apply_load_display_names(self._get_selected_load_items())
        self._refresh_final_load_tree()

    def _mark_load_selection_user_dirty(self) -> None:
        self.load_selection_user_dirty = True
        self.load_selection_default_mode = "USER_MANUAL"
        self.load_selection_source_signature = self._load_selection_signature()

    def _on_load_selection_changed(self) -> None:
        self._mark_load_selection_user_dirty()
        self._sync_final_load_list()

    def _load_selection_signature(self) -> str:
        model_keys = tuple(str(item.get("key") or "") for item in self.model_load_items)
        pdf_keys = tuple(str(item.get("key") or "") for item in self.pdf_load_items)
        pdf_sources = tuple(str(path) for path in self.__dict__.get("selected_pdf_paths", ()) or ())
        return repr((model_keys, pdf_keys, pdf_sources))

    def _set_all_load_vars(self, items: list[dict], vars_by_key: dict[str, tk.BooleanVar], value: bool) -> None:
        for item in items:
            key = str(item["key"])
            var = vars_by_key.get(key)
            if var is None:
                var = tk.BooleanVar(value=bool(value))
                vars_by_key[key] = var
            else:
                var.set(bool(value))

    def _apply_pdf_present_default_selection(self) -> None:
        if self.load_selection_user_dirty:
            self.load_selection_default_mode = "USER_MANUAL"
            return
        self._set_all_load_vars(self.model_load_items, self.model_load_vars, False)
        self._set_all_load_vars(self.pdf_load_items, self.pdf_load_vars, False)
        self.model_load_all_var.set(False)
        self.pdf_load_all_var.set(False)
        self.load_selection_default_mode = "PDF_PRESENT_AUTO_CLEARED"
        self.load_selection_source_signature = self._load_selection_signature()
        self._sync_final_load_list()

    def _resize_final_load_columns(self, _event=None) -> None:
        if not hasattr(self, "final_load_tree"):
            return
        total_width = max(self.final_load_tree.winfo_width(), 320)
        fixed_width = 55 + 55 + 55 + 28
        display_width = max(100, total_width - fixed_width)
        self.final_load_tree.column("display", width=display_width, minwidth=100, stretch=True)
        self.final_load_tree.column("source", width=55, minwidth=50, stretch=False)
        self.final_load_tree.column("dl", width=55, minwidth=50, stretch=False)
        self.final_load_tree.column("ll", width=55, minwidth=50, stretch=False)

    def _refresh_final_load_tree(self) -> None:
        if not hasattr(self, "final_load_tree"):
            self._refresh_hatch_load_tree()
            return
        for item_id in self.final_load_tree.get_children():
            self.final_load_tree.delete(item_id)
        for item in self.final_load_items:
            self.final_load_tree.insert(
                "",
                "end",
                values=(
                    item.get("display_name") or item.get("name") or "",
                    item.get("source") or "",
                    f"{float(item.get('dl', 0.0)):.2f}",
                    f"{float(item.get('ll', 0.0)):.2f}",
                ),
            )
        self._refresh_hatch_load_tree()
        self.after_idle(self._resize_final_load_columns)

    def _refresh_hatch_load_tree(self) -> None:
        tree = self.__dict__.get("hatch_load_tree")
        if tree is None:
            return
        for item_id in tree.get_children():
            tree.delete(item_id)
        self.hatch_load_item_by_iid = {}
        for index, item in enumerate(getattr(self, "final_load_items", []) or [], start=1):
            iid = f"hatch_load_{index}"
            name = str(item.get("display_name") or item.get("name") or "")
            distribution = str(item.get("distribution") or "TWO_WAY")
            self.hatch_load_item_by_iid[iid] = {**item, "display_name": name, "distribution": distribution}
            tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    name,
                    f"{float(item.get('dl', 0.0)):.2f}",
                    f"{float(item.get('ll', 0.0)):.2f}",
                    distribution,
                ),
            )

    def _selected_hatch_load_item(self) -> dict | None:
        tree = self.__dict__.get("hatch_load_tree")
        if tree is None:
            return None
        selected = tuple(tree.selection() or ())
        if not selected:
            children = tuple(tree.get_children() or ())
            if len(children) == 1:
                selected = (children[0],)
        if not selected:
            return None
        item = self.__dict__.get("hatch_load_item_by_iid", {}).get(str(selected[0]))
        return dict(item) if item else None

    def _hatch_load_layer_for_item(self, item: dict) -> str:
        explicit = str(item.get("layer") or "").strip()
        if explicit:
            return explicit
        key = str(item.get("key") or "")
        index = 1
        for candidate_index, candidate in enumerate(getattr(self, "final_load_items", []) or [], start=1):
            if str(candidate.get("key") or "") == key:
                index = candidate_index
                break
        name = str(item.get("display_name") or item.get("name") or "LOAD")
        return make_safe_load_layer_name(index, name, float(item.get("dl", 0.0) or 0.0), float(item.get("ll", 0.0) or 0.0))

    def _set_hatch_direct_status(self, message: str) -> None:
        if hasattr(self, "hatch_preview_info_var"):
            self.hatch_preview_info_var.set(message)
        self._set_continuous_status(message)

    def _set_continuous_status(self, message: str, *, warning: bool = False) -> None:
        if hasattr(self, "continuous_apply_status_var"):
            self.continuous_apply_status_var.set(message)
        label = self.__dict__.get("continuous_apply_status_label")
        if label is not None:
            try:
                label.configure(foreground="#be185d" if warning else "#2d4b73")
            except Exception:
                pass

    def _hatch_var_text(self, name: str) -> str:
        value = self.__dict__.get(name)
        if hasattr(value, "get"):
            try:
                return str(value.get() or "")
            except Exception:
                return ""
        return str(value or "")

    def _set_hatch_var_text(self, name: str, text: str) -> None:
        value = self.__dict__.get(name)
        if hasattr(value, "set"):
            try:
                value.set(str(text or ""))
                return
            except Exception:
                pass
        self.__dict__[name] = str(text or "")

    def _ensure_hatch_edit_history(self) -> None:
        if not isinstance(self.__dict__.get("hatch_edit_undo_stack"), list):
            self.hatch_edit_undo_stack = []
        if not isinstance(self.__dict__.get("hatch_edit_redo_stack"), list):
            self.hatch_edit_redo_stack = []
        if not isinstance(self.__dict__.get("_hatch_edit_history_session_id"), int):
            self._hatch_edit_history_session_id = 0
        if not isinstance(self.__dict__.get("_hatch_edit_transaction_depth"), int):
            self._hatch_edit_transaction_depth = 0
        if "_hatch_edit_transaction_before" not in self.__dict__:
            self._hatch_edit_transaction_before = None
        if "_hatch_edit_transaction_label" not in self.__dict__:
            self._hatch_edit_transaction_label = ""

    def _reset_hatch_edit_history(self, reason: str) -> None:
        self._ensure_hatch_edit_history()
        self.hatch_edit_undo_stack.clear()
        self.hatch_edit_redo_stack.clear()
        self._hatch_edit_transaction_depth = 0
        self._hatch_edit_transaction_before = None
        self._hatch_edit_transaction_label = ""
        self._hatch_edit_history_session_id += 1
        logger = self.__dict__.get("logger")
        if logger is not None:
            logger.debug(
                "HATCH VIEW edit history reset session=%d reason=%s",
                self._hatch_edit_history_session_id,
                str(reason or ""),
            )
        self._update_hatch_undo_redo_buttons()

    def _capture_hatch_edit_snapshot(self) -> HatchViewEditSnapshot:
        self._ensure_hatch_edit_history()
        loaded_region_loads = []
        for index, region in enumerate(tuple(self.__dict__.get("loaded_regions", ()) or ()), start=1):
            try:
                key = self._region_key(region, index=index)
            except Exception:
                key = f"loaded:{index}"
            loaded_region_loads.append(
                (
                    str(key),
                    copy.deepcopy(getattr(region, "load", None)),
                    str(getattr(region, "status", "") or ""),
                )
            )

        def tuple_map(name: str) -> dict[str, tuple[str, ...]]:
            source = self.__dict__.get(name, {}) or {}
            if not isinstance(source, dict):
                return {}
            return {
                str(key): tuple(str(value or "") for value in tuple(values or ()) if str(value or ""))
                for key, values in source.items()
            }

        return HatchViewEditSnapshot(
            history_session_id=int(self._hatch_edit_history_session_id),
            loaded_regions=copy.deepcopy(tuple(self.__dict__.get("loaded_regions", ()) or ())),
            loaded_region_loads=tuple(loaded_region_loads),
            hatch_edit_states_by_story=copy.deepcopy(self.__dict__.get("hatch_edit_states_by_story", {}) or {}),
            continuous_apply_targets_by_region=tuple_map("continuous_apply_targets_by_region"),
            continuous_materialized_targets_by_region=tuple_map("continuous_materialized_targets_by_region"),
            selected_region_key=str(self.__dict__.get("hatch_view_selected_region_key") or ""),
            selected_region_keys=tuple(sorted(str(key or "") for key in self.__dict__.get("hatch_view_selected_region_keys", set()) or set() if str(key or ""))),
            selected_edit_region_keys=tuple(sorted(str(key or "") for key in self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set() if str(key or ""))),
            continuous_active_visible_targets=tuple(str(name or "") for name in tuple(self.__dict__.get("continuous_active_visible_targets", ()) or ()) if str(name or "")),
            continuous_active_region_key=str(self.__dict__.get("continuous_active_region_key") or ""),
            continuous_active_region_keys=tuple(str(key or "") for key in tuple(self.__dict__.get("continuous_active_region_keys", ()) or ()) if str(key or "")),
            continuous_base_story=self._hatch_var_text("continuous_base_story_name"),
            selected_dummy_issue_key=str(self.__dict__.get("selected_dummy_issue_key") or ""),
            dummy_preview_plan=copy.deepcopy(self.__dict__.get("dummy_preview_plan")),
            approved_dummy_plans=copy.deepcopy(self.__dict__.get("approved_dummy_plans", {}) or {}),
            dummy_issue_status_by_key={
                str(key): str(getattr(issue, "status", "") or "")
                for key, issue in (self.__dict__.get("dummy_issue_by_key", {}) or {}).items()
            },
        )

    def _restore_hatch_edit_snapshot(self, snapshot: HatchViewEditSnapshot) -> bool:
        self._ensure_hatch_edit_history()
        if int(getattr(snapshot, "history_session_id", -1)) != int(self._hatch_edit_history_session_id):
            self.hatch_edit_undo_stack.clear()
            self.hatch_edit_redo_stack.clear()
            self._hatch_edit_transaction_depth = 0
            self._hatch_edit_transaction_before = None
            self._hatch_edit_transaction_label = ""
            self._set_hatch_direct_status(
                "이전 모델/DXF 세션의 편집 기록은 현재 HATCH VIEW에 복원할 수 없어 초기화했습니다."
            )
            self._update_hatch_undo_redo_buttons()
            return False
        self.loaded_regions = list(copy.deepcopy(snapshot.loaded_regions))
        rebuilt_region_by_key = {}
        for index, region in enumerate(tuple(self.__dict__.get("loaded_regions", ()) or ()), start=1):
            try:
                rebuilt_region_by_key[self._region_key(region, index=index)] = region
            except Exception:
                rebuilt_region_by_key[f"loaded:{index}"] = region
        self.hatch_view_region_by_key = dict(rebuilt_region_by_key)
        region_by_key = {}
        for index, region in enumerate(tuple(self.__dict__.get("loaded_regions", ()) or ()), start=1):
            try:
                region_by_key[self._region_key(region, index=index)] = region
            except Exception:
                region_by_key[f"loaded:{index}"] = region
        region_by_key.update(rebuilt_region_by_key)
        for key, load, status in snapshot.loaded_region_loads:
            region = region_by_key.get(str(key))
            if region is None:
                continue
            region.load = copy.deepcopy(load)
            region.status = str(status or "")
        self.hatch_edit_states_by_story = copy.deepcopy(snapshot.hatch_edit_states_by_story)
        self._invalidate_continuous_below_allowed_reason_cache("HATCH VIEW snapshot 복원")
        self.continuous_apply_targets_by_region = {
            str(key): tuple(values)
            for key, values in snapshot.continuous_apply_targets_by_region.items()
        }
        self.continuous_materialized_targets_by_region = {
            str(key): tuple(values)
            for key, values in snapshot.continuous_materialized_targets_by_region.items()
        }
        self.hatch_view_selected_region_key = snapshot.selected_region_key or None
        self.hatch_view_selected_region_keys = set(snapshot.selected_region_keys)
        self.hatch_view_selected_edit_region_keys = set(snapshot.selected_edit_region_keys)
        self.continuous_active_visible_targets = tuple(snapshot.continuous_active_visible_targets)
        self.continuous_active_region_key = snapshot.continuous_active_region_key or None
        self.continuous_active_region_keys = tuple(snapshot.continuous_active_region_keys)
        self._set_hatch_var_text("continuous_base_story_name", snapshot.continuous_base_story)
        self.selected_dummy_issue_key = snapshot.selected_dummy_issue_key or None
        self.dummy_preview_plan = copy.deepcopy(snapshot.dummy_preview_plan)
        self.approved_dummy_plans = copy.deepcopy(snapshot.approved_dummy_plans)
        for key, status in snapshot.dummy_issue_status_by_key.items():
            issue = (self.__dict__.get("dummy_issue_by_key", {}) or {}).get(key)
            if issue is not None:
                self.dummy_issue_by_key[key] = replace(issue, status=status)
        self._invalidate_dummy_virtual_boundaries("HATCH VIEW snapshot 복원")
        self._update_dummy_action_buttons()
        try:
            self._refresh_hatch_edit_region_index()
        except Exception:
            pass
        try:
            self._render_hatch_preview()
        except Exception:
            pass
        try:
            self._refresh_selected_hatch_continuous_info()
        except Exception:
            pass
        self._update_hatch_undo_redo_buttons()
        return True

    def _safe_capture_hatch_edit_snapshot(self):
        try:
            return self._capture_hatch_edit_snapshot()
        except Exception as exc:  # noqa: BLE001 - history failure must not block editing
            logger = self.__dict__.get("logger")
            if logger is not None:
                logger.warning("hatch edit snapshot failed: %s", exc)
            return None

    def _record_hatch_edit_change(self, label: str, before) -> None:
        self._ensure_hatch_edit_history()
        if self._hatch_edit_transaction_depth > 0:
            return
        if before is None:
            self._update_hatch_undo_redo_buttons()
            return
        after = self._safe_capture_hatch_edit_snapshot()
        if after is not None and before != after:
            self._ensure_hatch_edit_history()
            self.hatch_edit_undo_stack.append((str(label or "편집"), before))
            self.hatch_edit_redo_stack.clear()
            if len(self.hatch_edit_undo_stack) > 50:
                self.hatch_edit_undo_stack = self.hatch_edit_undo_stack[-50:]
        self._update_hatch_undo_redo_buttons()

    @contextmanager
    def _hatch_edit_command(self, label: str):
        self._ensure_hatch_edit_history()
        outermost = self._hatch_edit_transaction_depth == 0
        if outermost:
            self._hatch_edit_transaction_before = self._safe_capture_hatch_edit_snapshot()
            self._hatch_edit_transaction_label = str(label or "편집")
        self._hatch_edit_transaction_depth += 1
        failed = False
        try:
            yield
        except Exception:
            failed = True
            raise
        finally:
            self._hatch_edit_transaction_depth = max(0, self._hatch_edit_transaction_depth - 1)
            if outermost:
                before = self._hatch_edit_transaction_before
                transaction_label = self._hatch_edit_transaction_label
                self._hatch_edit_transaction_before = None
                self._hatch_edit_transaction_label = ""
                if failed or before is None:
                    self._update_hatch_undo_redo_buttons()
                else:
                    self._record_hatch_edit_change(transaction_label, before)

    def _discard_stale_hatch_history_entries(self, stack) -> bool:
        self._ensure_hatch_edit_history()
        discarded = False
        while stack:
            _label, snapshot = stack[-1]
            if int(getattr(snapshot, "history_session_id", -1)) == int(self._hatch_edit_history_session_id):
                break
            stack.pop()
            discarded = True
        return discarded

    def undo_hatch_view_edit(self) -> None:
        self._ensure_hatch_edit_history()
        stale = self._discard_stale_hatch_history_entries(self.hatch_edit_undo_stack)
        if not self.hatch_edit_undo_stack:
            if stale:
                self.hatch_edit_redo_stack.clear()
                self._set_hatch_direct_status("이전 모델/DXF 세션의 Undo 기록을 폐기했습니다.")
            self._update_hatch_undo_redo_buttons()
            return
        current = self._safe_capture_hatch_edit_snapshot()
        label, snapshot = self.hatch_edit_undo_stack.pop()
        restored = self._restore_hatch_edit_snapshot(snapshot)
        if current is not None and restored:
            self.hatch_edit_redo_stack.append((label, current))
        self._update_hatch_undo_redo_buttons()

    def redo_hatch_view_edit(self) -> None:
        self._ensure_hatch_edit_history()
        stale = self._discard_stale_hatch_history_entries(self.hatch_edit_redo_stack)
        if not self.hatch_edit_redo_stack:
            if stale:
                self.hatch_edit_undo_stack.clear()
                self._set_hatch_direct_status("이전 모델/DXF 세션의 Redo 기록을 폐기했습니다.")
            self._update_hatch_undo_redo_buttons()
            return
        current = self._safe_capture_hatch_edit_snapshot()
        label, snapshot = self.hatch_edit_redo_stack.pop()
        restored = self._restore_hatch_edit_snapshot(snapshot)
        if current is not None and restored:
            self.hatch_edit_undo_stack.append((label, current))
        self._update_hatch_undo_redo_buttons()

    def _update_hatch_undo_redo_buttons(self) -> None:
        self._ensure_hatch_edit_history()
        undo_button = self.__dict__.get("hatch_undo_button")
        redo_button = self.__dict__.get("hatch_redo_button")
        if undo_button is not None:
            try:
                undo_button.configure(state="normal" if self.hatch_edit_undo_stack else "disabled")
            except Exception:
                pass
        if redo_button is not None:
            try:
                redo_button.configure(state="normal" if self.hatch_edit_redo_stack else "disabled")
            except Exception:
                pass

    def _event_from_text_input(self, event) -> bool:
        widget = getattr(event, "widget", None)
        class_name = ""
        try:
            class_name = str(widget.winfo_class())
        except Exception:
            pass
        return class_name in {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox", "TCombobox"}

    def _on_hatch_view_delete_key(self, event=None):
        if event is not None and self._event_from_text_input(event):
            return None
        self.remove_selected_hatch_load()
        return "break"

    def _on_hatch_view_undo_key(self, event=None):
        if event is not None and self._event_from_text_input(event):
            return None
        self.undo_hatch_view_edit()
        return "break"

    def _on_hatch_view_redo_key(self, event=None):
        if event is not None and self._event_from_text_input(event):
            return None
        self.redo_hatch_view_edit()
        return "break"

    def _has_hatch_edit_selection(self) -> bool:
        if self.__dict__.get("hatch_view_selected_edit_region_keys"):
            return True
        return any(
            bool(state.selected_region_keys or state.selected_cell_ids)
            for state in self.__dict__.get("hatch_edit_states_by_story", {}).values()
        )

    def _on_hatch_load_tree_select(self, _event=None) -> None:
        if self._selected_hatch_load_item() is None:
            return
        if not self._has_hatch_edit_selection():
            self._set_hatch_direct_status(
                "하중을 선택했습니다. HATCH VIEW에서 적용할 폐합영역을 선택한 뒤 더블클릭 또는 적용 버튼을 누르세요."
            )

    def _on_hatch_load_tree_activate(self, _event=None):
        if self._has_any_hatch_view_selection():
            self.apply_selected_hatch_load()
        else:
            self._set_hatch_direct_status(
                "하중을 선택했습니다. HATCH VIEW에서 적용할 폐합영역을 선택해 주세요."
            )
        return "break"

    def _on_hatch_load_drag_start(self, event) -> None:
        self._destroy_hatch_load_drag_ghost()
        tree = getattr(event, "widget", None) or self.__dict__.get("hatch_load_tree")
        if tree is None:
            return
        try:
            row = tree.identify_row(event.y)
            if row:
                tree.selection_set(row)
        except Exception:
            pass
        self.hatch_load_drag_item = self._selected_hatch_load_item()
        self.hatch_load_drag_start = (float(getattr(event, "x_root", getattr(event, "x", 0))), float(getattr(event, "y_root", getattr(event, "y", 0))))
        self.hatch_load_drag_active = False
        self.hatch_load_drag_hover_key = None
        self.hatch_load_drag_last_status = ""

    def _on_hatch_load_drag_motion(self, event) -> None:
        item = self.__dict__.get("hatch_load_drag_item")
        if not item:
            return
        start = self.__dict__.get("hatch_load_drag_start")
        x_root = float(getattr(event, "x_root", getattr(event, "x", 0)))
        y_root = float(getattr(event, "y_root", getattr(event, "y", 0)))
        if start and (abs(x_root - start[0]) > 4.0 or abs(y_root - start[1]) > 4.0):
            self.hatch_load_drag_active = True
        canvas_point = self._root_point_to_hatch_canvas_point(x_root, y_root)
        previous_hover = self.__dict__.get("hatch_load_drag_hover_key")
        hover_key = None
        if canvas_point is None:
            if previous_hover is not None:
                self.hatch_load_drag_hover_key = None
                if not self._update_hatch_load_drag_hover_visuals(previous_hover, None):
                    self._render_hatch_preview()
        else:
            hover_key = self._hatch_region_key_at_canvas_point(*canvas_point)
            if hover_key != previous_hover:
                self.hatch_load_drag_hover_key = hover_key
                if not self._update_hatch_load_drag_hover_visuals(previous_hover, hover_key):
                    self._render_hatch_preview()
        target_type, keys = self._drag_drop_target_region_keys(hover_key, update_selection=False)
        target_count = len(keys) if keys else None
        if self.__dict__.get("hatch_load_drag_active"):
            self._show_or_update_hatch_load_drag_ghost(item, x_root, y_root, target_count=target_count)
        status = self._drag_drop_apply_status_text(target_type, keys, hover_key=hover_key)
        if status and status != self.__dict__.get("hatch_load_drag_last_status"):
            self.hatch_load_drag_last_status = status
            self._set_hatch_direct_status(status)

    def _on_hatch_load_drag_release(self, event) -> None:
        item = self.__dict__.get("hatch_load_drag_item")
        active = bool(self.__dict__.get("hatch_load_drag_active", False))
        x_root = float(getattr(event, "x_root", getattr(event, "x", 0)))
        y_root = float(getattr(event, "y_root", getattr(event, "y", 0)))
        canvas_point = self._root_point_to_hatch_canvas_point(x_root, y_root)
        target_key = self._hatch_region_key_at_canvas_point(*canvas_point) if canvas_point is not None else None
        previous_hover = self.__dict__.get("hatch_load_drag_hover_key")
        self.hatch_load_drag_item = None
        self.hatch_load_drag_start = None
        self.hatch_load_drag_active = False
        self.hatch_load_drag_hover_key = None
        self.hatch_load_drag_last_status = ""
        self._destroy_hatch_load_drag_ghost()
        if previous_hover is not None:
            if not self._update_hatch_load_drag_hover_visuals(previous_hover, None):
                self._render_hatch_preview()
        if not item or not active:
            return
        if canvas_point is None:
            self._set_hatch_direct_status("HATCH VIEW Canvas 밖에서는 하중 Drop을 적용하지 않습니다.")
            return
        self._apply_dragged_load_to_hatch_region(item, target_key)

    def _update_hatch_load_drag_hover_visuals(self, previous_key, current_key) -> bool:
        canvas = self.__dict__.get("hatch_preview_canvas")
        if canvas is None:
            return False
        dxf_items = self.__dict__.get("hatch_view_region_items", {}) or {}
        edit_items = self.__dict__.get("hatch_view_edit_region_items", {}) or {}
        dxf_regions = self.__dict__.get("hatch_view_region_by_key", {}) or {}
        edit_regions = self.__dict__.get("hatch_view_edit_region_by_key", {}) or {}
        selected_dxf = set(self.__dict__.get("hatch_view_selected_region_keys", set()) or set())
        selected_single = str(self.__dict__.get("hatch_view_selected_region_key") or "")
        if selected_single:
            selected_dxf.add(selected_single)
        selected_edit = set(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set())
        keys = []
        for value in (previous_key, current_key):
            key = str(value or "")
            if key and key not in keys:
                keys.append(key)
        for key in keys:
            if key in dxf_items or key in dxf_regions:
                item_id = dxf_items.get(key)
                if item_id is None:
                    return False
                selected = key in selected_dxf
                is_hover = key == str(current_key or "") and not selected
                outline = "#1a73e8" if selected else ("#fbbc04" if is_hover else "#374151")
                if not self._canvas_itemconfig(
                    canvas,
                    item_id,
                    outline=outline,
                    width=4 if selected or is_hover else 2,
                    dash=(4, 2) if is_hover else "",
                ):
                    return False
            elif key in edit_items or key in edit_regions:
                item_id = edit_items.get(key)
                if item_id is None:
                    return False
                selected = key in selected_edit
                is_hover = key == str(current_key or "") and not selected
                region = edit_regions.get(key) or self._editable_hatch_region_by_key(key)
                has_load = bool(getattr(region, "load_name", None))
                outline = "#1a73e8" if selected else ("#fbbc04" if is_hover else ("#b45309" if not has_load else "#374151"))
                if not self._canvas_itemconfig(
                    canvas,
                    item_id,
                    outline=outline,
                    width=4 if selected or is_hover else 2,
                    dash=(4, 2) if is_hover else "",
                ):
                    return False
            else:
                return False
        return bool(keys)

    def _root_point_to_hatch_canvas_point(self, x_root: float, y_root: float) -> tuple[float, float] | None:
        canvas = self.__dict__.get("hatch_preview_canvas")
        if canvas is None:
            return None
        try:
            left = float(canvas.winfo_rootx())
            top = float(canvas.winfo_rooty())
            width = float(canvas.winfo_width())
            height = float(canvas.winfo_height())
        except Exception:
            return None
        x = float(x_root) - left
        y = float(y_root) - top
        if x < 0 or y < 0 or x > width or y > height:
            return None
        return (x, y)

    def _hatch_region_key_at_canvas_point(self, x: float, y: float) -> str | None:
        return self._hatch_region_key_containing_canvas_point(x, y)

    def _hatch_region_key_containing_canvas_point(self, x: float, y: float) -> str | None:
        world_x, world_y = self._canvas_point_to_hatch_world(float(x), float(y))
        point = Point(float(world_x), float(world_y))
        edit_candidates, dxf_candidates = self._hatch_drag_selection_candidates()
        selected = set(self._selected_edit_region_keys())
        selected.update(self._selected_dxf_region_keys())
        hits: list[tuple[int, int, float, str]] = []
        for source_priority, candidates in ((0, edit_candidates), (1, dxf_candidates)):
            for key, vertices in tuple(candidates or ()):
                text_key = str(key or "")
                if not text_key:
                    continue
                try:
                    polygon = Polygon(tuple(vertices or ()))
                    if polygon.is_empty:
                        continue
                    if not polygon.is_valid:
                        polygon = polygon.buffer(0)
                    if getattr(polygon, "geom_type", "") != "Polygon" or polygon.is_empty:
                        continue
                    if not polygon.covers(point):
                        continue
                    hits.append(
                        (
                            0 if text_key in selected else 1,
                            source_priority,
                            abs(float(polygon.area)),
                            text_key,
                        )
                    )
                except Exception:
                    continue
        if not hits:
            return None
        return min(hits)[3]

    def _apply_dragged_load_to_hatch_region(self, load_item: dict, region_key: str | None) -> None:
        load_item = self._hatch_load_item_for_current_mode(load_item)
        target_type, keys = self._drag_drop_target_region_keys(region_key)
        if target_type == "edit" and keys:
            self._sync_edit_region_selection_from_keys(keys)
            self._apply_hatch_load_item_to_selected_regions(load_item)
            if str(load_item.get("distribution") or "").upper() != DISTRIBUTION_ONE_WAY:
                self._set_hatch_direct_status(f"자동 저장됨: 선택 해치 {len(keys)}개에 하중 적용")
            return
        if target_type == "dxf" and keys:
            self._apply_load_item_to_dxf_regions(load_item, keys)
            return
        self._set_hatch_direct_status("하중을 적용할 HATCH VIEW 영역이 없습니다. 영역 위에 놓거나 폐합영역을 먼저 선택해 주세요.")

    def _selected_edit_region_keys(self) -> tuple[str, ...]:
        region_by_key = self.__dict__.get("hatch_view_edit_region_by_key", {}) or {}
        keys: list[str] = []
        for key in tuple(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set()):
            text = str(key or "")
            if text and text in region_by_key and text not in keys:
                keys.append(text)
        for state in tuple((self.__dict__.get("hatch_edit_states_by_story", {}) or {}).values()):
            for key in tuple(getattr(state, "selected_region_keys", set()) or set()):
                text = str(key or "")
                if text and text in region_by_key and text not in keys:
                    keys.append(text)
        return tuple(keys)

    def _sync_edit_region_selection_from_keys(self, keys) -> None:
        selected = {
            str(key or "")
            for key in tuple(keys or ())
            if str(key or "") in (self.__dict__.get("hatch_view_edit_region_by_key", {}) or {})
        }
        self.hatch_view_selected_edit_region_keys = set(selected)
        if selected:
            self.hatch_view_selected_region_key = None
            self.hatch_view_selected_region_keys = set()
        for state in (self.__dict__.get("hatch_edit_states_by_story", {}) or {}).values():
            state.selected_region_keys = set(key for key in selected if key in getattr(state, "regions_by_key", {}))
            state.selected_cell_ids = {
                cell_id
                for key in state.selected_region_keys
                for cell_id in state.regions_by_key[key].cell_ids
            }

    def _drag_drop_target_region_keys(self, target_key: str | None, *, update_selection: bool = True) -> tuple[str, tuple[str, ...]]:
        key = str(target_key or "")
        edit_regions = self.__dict__.get("hatch_view_edit_region_by_key", {}) or {}
        dxf_regions = self.__dict__.get("hatch_view_region_by_key", {}) or {}
        selected_edit_keys = self._selected_edit_region_keys()
        selected_dxf_keys = self._selected_dxf_region_keys()
        if key and key in edit_regions:
            if key in selected_edit_keys and selected_edit_keys:
                return "edit", selected_edit_keys
            if update_selection:
                self._select_hatch_edit_regions([key], mode="replace")
            return "edit", (key,)
        if key and key in dxf_regions:
            if key in selected_dxf_keys and selected_dxf_keys:
                return "dxf", selected_dxf_keys
            if update_selection:
                self._select_dxf_hatch_regions([key], mode="replace")
            return "dxf", (key,)
        if selected_edit_keys:
            return "edit", selected_edit_keys
        if selected_dxf_keys:
            return "dxf", selected_dxf_keys
        return "none", ()

    def _drag_drop_apply_status_text(self, target_type: str, keys, *, hover_key: str | None = None) -> str:
        count = len(tuple(keys or ()))
        if count <= 0:
            return "하중을 적용할 해치 위로 이동하거나 먼저 해치를 선택하세요."
        if count > 1:
            return f"하중을 놓으면 선택된 해치 {count}개에 적용됩니다."
        if hover_key:
            return "하중을 놓으면 현재 위치의 해치 1개에 적용됩니다."
        label = "DXF 해치" if target_type == "dxf" else "해치"
        return f"하중을 놓으면 선택된 {label} 1개에 적용됩니다."

    def _hatch_load_drag_label_text(self, item: dict, target_count: int | None = None) -> str:
        name = str(item.get("display_name") or item.get("name") or "LOAD")
        dl = float(item.get("dl", 0.0) or 0.0)
        ll = float(item.get("ll", 0.0) or 0.0)
        lines = ["하중 이동 중", name, f"DL {dl:.2f} / LL {ll:.2f}"]
        if target_count is not None:
            if int(target_count) > 1:
                lines.append(f"선택 {int(target_count)}개에 적용")
            elif int(target_count) == 1:
                lines.append("현재 위치 1개에 적용")
        return "\n".join(lines)

    def _show_or_update_hatch_load_drag_ghost(self, item: dict, x_root: float, y_root: float, target_count: int | None = None) -> None:
        text = self._hatch_load_drag_label_text(item, target_count=target_count)
        try:
            window = self.__dict__.get("hatch_load_drag_ghost_window")
            label = self.__dict__.get("hatch_load_drag_ghost_label")
            if window is None or label is None:
                window = tk.Toplevel(self)
                window.overrideredirect(True)
                try:
                    window.attributes("-alpha", 0.88)
                except Exception:
                    pass
                try:
                    window.wm_attributes("-topmost", True)
                except Exception:
                    pass
                label = tk.Label(
                    window,
                    text=text,
                    justify="left",
                    bg="#fef3c7",
                    fg="#111827",
                    relief="solid",
                    borderwidth=1,
                    padx=8,
                    pady=5,
                )
                label.pack()
                self.hatch_load_drag_ghost_window = window
                self.hatch_load_drag_ghost_label = label
            else:
                label.configure(text=text)
            window.geometry(f"+{int(float(x_root) + 14)}+{int(float(y_root) + 16)}")
        except Exception:
            self.hatch_load_drag_ghost_window = None
            self.hatch_load_drag_ghost_label = None

    def _destroy_hatch_load_drag_ghost(self) -> None:
        window = self.__dict__.get("hatch_load_drag_ghost_window")
        self.hatch_load_drag_ghost_window = None
        self.hatch_load_drag_ghost_label = None
        if window is None:
            return
        try:
            window.destroy()
        except Exception:
            pass

    def _on_hatch_view_context_menu(self, event) -> str:
        region_key = self._hatch_region_key_at_canvas_point(float(getattr(event, "x", 0)), float(getattr(event, "y", 0)))
        if region_key:
            if self._is_hatch_region_selected(region_key):
                pass
            elif region_key in self.__dict__.get("hatch_view_edit_region_by_key", {}):
                self._select_hatch_edit_regions([region_key], mode="replace")
                self._render_hatch_preview()
            elif region_key in self.__dict__.get("hatch_view_region_by_key", {}):
                self._select_dxf_hatch_regions([region_key], mode="replace")
                self._select_dxf_tree_region(region_key)
                self._load_selected_hatch_as_base_story(region_key)
                self._render_hatch_preview(focus_region_key=region_key)
        has_selection = self._has_any_hatch_view_selection()
        menu = tk.Menu(self, tearoff=0)
        state = "normal" if has_selection else "disabled"
        menu.add_command(label="선택영역 하중 제거", command=self.remove_selected_hatch_load, state=state)
        menu.add_command(label="해치영역 구분하기", command=self.split_selected_hatch_region, state=state)
        load_menu = tk.Menu(menu, tearoff=0)
        items = list(getattr(self, "final_load_items", []) or [])[:30]
        if items:
            for item in items:
                label = str(item.get("display_name") or item.get("name") or "LOAD")
                dl = float(item.get("dl", 0.0) or 0.0)
                ll = float(item.get("ll", 0.0) or 0.0)
                load_menu.add_command(
                    label=f"{label} DL {dl:g} LL {ll:g}",
                    command=lambda value=dict(item): self._apply_context_load_item(value),
                    state=state,
                )
        else:
            load_menu.add_command(label="사용 가능한 하중 없음", state="disabled")
        menu.add_cascade(label="선택영역에 하중 적용", menu=load_menu, state=state)
        self.hatch_context_menu = menu
        try:
            menu.tk_popup(int(getattr(event, "x_root", getattr(event, "x", 0))), int(getattr(event, "y_root", getattr(event, "y", 0))))
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        return "break"

    def _is_hatch_region_selected(self, region_key: str) -> bool:
        key = str(region_key or "")
        if not key:
            return False
        if key in set(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set()):
            return True
        if key in set(self.__dict__.get("hatch_view_selected_region_keys", set()) or set()):
            return True
        return key == str(self.__dict__.get("hatch_view_selected_region_key") or "")

    def _has_any_hatch_view_selection(self) -> bool:
        return (
            bool(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set())
            or bool(self.__dict__.get("hatch_view_selected_region_keys", set()) or set())
            or bool(self.__dict__.get("hatch_view_selected_region_key"))
            or self._has_hatch_edit_selection()
        )

    def _apply_context_load_item(self, item: dict) -> None:
        item = self._hatch_load_item_for_current_mode(item)
        if self._has_hatch_edit_selection():
            self._apply_hatch_load_item_to_selected_regions(item)
            return
        region_keys = self._selected_dxf_region_keys()
        if region_keys:
            self._apply_load_item_to_dxf_regions(item, region_keys)
            return
        self._set_hatch_direct_status("하중을 적용할 폐합영역을 먼저 선택해 주세요.")

    def _selected_dxf_region_keys(self) -> tuple[str, ...]:
        region_by_key = self.__dict__.get("hatch_view_region_by_key", {}) or {}
        selected = {
            str(key or "")
            for key in tuple(self.__dict__.get("hatch_view_selected_region_keys", set()) or set())
            if str(key or "")
        }
        single = str(self.__dict__.get("hatch_view_selected_region_key") or "")
        if single:
            selected.add(single)
        keys = [str(key) for key in region_by_key.keys() if str(key) in selected]
        for key in selected:
            if key in region_by_key and key not in keys:
                keys.append(key)
        return tuple(keys)

    def _hatch_edit_states_with_selection(self) -> list[HatchEditState]:
        if "hatch_edit_states_by_story" not in self.__dict__:
            self.hatch_edit_states_by_story = {}
        self._ensure_hatch_edit_states(self._hatch_view_story_filter() or None)
        selected_keys = set(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set())
        states: list[HatchEditState] = []
        for state in self.hatch_edit_states_by_story.values():
            if selected_keys:
                state.selected_region_keys.update(key for key in selected_keys if key in state.regions_by_key)
                state.selected_cell_ids.update(
                    cell_id
                    for key in state.selected_region_keys
                    for region in (state.regions_by_key.get(key),)
                    if region is not None
                    for cell_id in region.cell_ids
                )
            if state.selected_region_keys or state.selected_cell_ids:
                states.append(state)
        return states

    def _store_hatch_edit_states(self, states: list[HatchEditState]) -> None:
        selected: set[str] = set()
        for state in states:
            self.hatch_edit_states_by_story[state.story_name] = state
            selected.update(state.selected_region_keys)
        self.hatch_view_selected_edit_region_keys = selected
        if selected:
            self.hatch_view_selected_region_key = None
        self._invalidate_continuous_below_allowed_reason_cache("HATCH VIEW editable geometry 변경")

    def _selected_edit_region_keys_from_states(self, states) -> tuple[str, ...]:
        keys: list[str] = []
        explicit = set(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set())
        for key in sorted(explicit):
            text = str(key or "")
            if text and text not in keys:
                keys.append(text)
        for state in tuple(states or ()):
            for key in tuple(getattr(state, "selected_region_keys", set()) or set()):
                text = str(key or "")
                if text and text not in keys:
                    keys.append(text)
        return tuple(keys)

    def _carry_continuous_targets_between_region_keys(self, old_keys, new_keys) -> None:
        target_map = self.__dict__.setdefault("continuous_apply_targets_by_region", {})
        if not isinstance(target_map, dict):
            return
        old_key_tuple = tuple(str(key or "") for key in tuple(old_keys or ()) if str(key or ""))
        new_key_tuple = tuple(str(key or "") for key in tuple(new_keys or ()) if str(key or ""))
        if not old_key_tuple or not new_key_tuple:
            return
        carried: tuple[str, ...] = ()
        for key in old_key_tuple:
            values = tuple(str(name or "") for name in tuple(target_map.get(key, ()) or ()) if str(name or ""))
            if values:
                carried = values
                break
        if not carried:
            return
        for key in new_key_tuple:
            if not tuple(target_map.get(key, ()) or ()):
                target_map[key] = carried

    def _capture_continuous_targets_by_selected_cell(self, states, region_keys):
        target_map = self.__dict__.get("continuous_apply_targets_by_region", {}) or {}
        if not isinstance(target_map, dict):
            return {}
        region_key_set = {str(key or "") for key in tuple(region_keys or ()) if str(key or "")}
        targets_by_cell: dict[tuple[str, str], tuple[str, ...]] = {}
        for state in tuple(states or ()):
            story_name = str(getattr(state, "story_name", "") or "")
            for region_key, region in (getattr(state, "regions_by_key", {}) or {}).items():
                key = str(region_key or "")
                if key not in region_key_set:
                    continue
                targets = tuple(
                    str(name or "")
                    for name in tuple(target_map.get(key, ()) or ())
                    if str(name or "")
                )
                for cell_id in tuple(getattr(region, "cell_ids", ()) or ()):
                    cell_key = (story_name, str(cell_id))
                    if cell_key not in targets_by_cell:
                        targets_by_cell[cell_key] = targets
                        continue
                    common = set(targets_by_cell[cell_key]).intersection(targets)
                    targets_by_cell[cell_key] = tuple(
                        name for name in targets_by_cell[cell_key] if name in common
                    )
        return targets_by_cell

    def _remap_continuous_targets_after_edit(
        self,
        states,
        previous_keys,
        current_keys,
        targets_by_cell,
    ) -> None:
        target_map = self.__dict__.setdefault("continuous_apply_targets_by_region", {})
        if not isinstance(target_map, dict):
            return
        previous = tuple(str(key or "") for key in tuple(previous_keys or ()) if str(key or ""))
        current = tuple(str(key or "") for key in tuple(current_keys or ()) if str(key or ""))
        cell_map = dict(targets_by_cell or {})
        if not cell_map:
            self._carry_continuous_targets_between_region_keys(previous, current)
        else:
            current_set = set(current)
            for state in tuple(states or ()):
                story_name = str(getattr(state, "story_name", "") or "")
                for key, region in (getattr(state, "regions_by_key", {}) or {}).items():
                    text_key = str(key or "")
                    if text_key not in current_set:
                        continue
                    source_targets = [
                        tuple(cell_map[(story_name, str(cell_id))])
                        for cell_id in tuple(getattr(region, "cell_ids", ()) or ())
                        if (story_name, str(cell_id)) in cell_map
                    ]
                    if not source_targets:
                        continue
                    common = set(source_targets[0])
                    for values in source_targets[1:]:
                        common.intersection_update(values)
                    target_map[text_key] = tuple(name for name in source_targets[0] if name in common)
        current_set = set(current)
        for key in previous:
            if key not in current_set:
                target_map.pop(key, None)

    def apply_selected_hatch_load(self) -> None:
        item = self._selected_hatch_load_item()
        if item is None:
            self._set_hatch_direct_status("적용할 하중을 먼저 선택해 주세요.")
            return
        item = self._hatch_load_item_for_current_mode(item)
        if self._has_hatch_edit_selection() and self._apply_hatch_load_item_to_selected_regions(item):
            return
        if self._apply_load_item_to_dxf_regions(item, self._selected_dxf_region_keys()):
            return
        self._set_hatch_direct_status("하중을 적용할 폐합영역을 먼저 선택해 주세요.")

    def _apply_hatch_load_item_to_selected_regions(self, item: dict) -> bool:
        item = self._hatch_load_item_for_current_mode(item)
        with self._hatch_edit_command("하중 적용"):
            started = time.perf_counter()
            states = self._hatch_edit_states_with_selection()
            if not states:
                self._set_hatch_direct_status("하중을 적용할 폐합 영역을 HATCH VIEW에서 선택해 주세요.")
                return False
            previous_keys = self._selected_edit_region_keys_from_states(states)
            targets_by_cell = self._capture_continuous_targets_by_selected_cell(states, previous_keys)
            name = str(item.get("display_name") or item.get("name") or "LOAD")
            layer = self._hatch_load_layer_for_item(item)
            distribution = str(item.get("distribution") or "TWO_WAY")
            one_way_angle = item.get("one_way_angle")
            updated = []
            stats_total = {"selected": 0, "applied": 0, "excluded": 0, "merged": 0, "kept_individual": 0}
            for state in states:
                new_state, stats = apply_load_to_selection_with_stats(
                    state,
                    load_name=name,
                    load_layer=layer,
                    dl=float(item.get("dl", 0.0) or 0.0),
                    ll=float(item.get("ll", 0.0) or 0.0),
                distribution=distribution,
                one_way_angle=None if one_way_angle in (None, "") else float(one_way_angle),
                shape_tolerance=self._one_way_shape_tolerance(),
                )
                updated.append(new_state)
                for key in stats_total:
                    stats_total[key] += int(stats.get(key, 0) or 0)
            if str(distribution).upper() == DISTRIBUTION_ONE_WAY and stats_total["applied"] <= 0:
                self._set_hatch_direct_status("ONE-WAY 하중은 3각형 또는 4각형 해치 영역에만 적용할 수 있습니다. 적용 가능한 선택 영역이 없습니다.")
                elapsed_ms = (time.perf_counter() - started) * 1000.0
                logger = self.__dict__.get("logger")
                if logger is not None and elapsed_ms >= 100.0:
                    logger.debug(
                        "HATCH load apply distribution=%s selected=%d applied=%d merged=%d elapsed_ms=%.1f",
                        distribution,
                        stats_total["selected"],
                        stats_total["applied"],
                        stats_total["merged"],
                        elapsed_ms,
                    )
                return True
            self._store_hatch_edit_states(updated)
            self._refresh_hatch_edit_region_index()
            current_keys = tuple(str(key or "") for key in tuple(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or ()) if str(key or ""))
            self._remap_continuous_targets_after_edit(
                updated,
                previous_keys,
                current_keys,
                targets_by_cell,
            )
            self._sync_load_to_continuous_targets_for_region_keys(
                current_keys or previous_keys,
                refresh_ui=False,
            )
            loaded_count = len(self._loaded_internal_hatch_regions())
            if str(distribution).upper() == DISTRIBUTION_ONE_WAY:
                self._set_hatch_direct_status(
                    "자동 저장됨: ONE-WAY 하중 적용 완료 - "
                    f"선택 {stats_total['selected']}개 중 {stats_total['applied']}개 적용, "
                    f"{stats_total['excluded']}개 제외(3각형/4각형 조건 불만족)"
                )
            else:
                self._set_hatch_direct_status(f"자동 저장됨: {name} -> 내부 폐합영역 {loaded_count}개")
            self._render_hatch_preview()
            self._refresh_selected_hatch_continuous_info()
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            logger = self.__dict__.get("logger")
            if logger is not None and elapsed_ms >= 100.0:
                logger.debug(
                    "HATCH load apply distribution=%s selected=%d applied=%d merged=%d elapsed_ms=%.1f",
                    distribution,
                    stats_total["selected"],
                    stats_total["applied"],
                    stats_total["merged"],
                    elapsed_ms,
                )
            return True

    def _apply_load_item_to_dxf_region(self, item: dict, region_key: str) -> bool:
        return self._apply_load_item_to_dxf_regions(item, (region_key,))

    def _dxf_region_polygon_vertices_for_one_way(self, region_key: str) -> tuple[tuple[float, float], ...]:
        region = self.__dict__.get("hatch_view_region_by_key", {}).get(str(region_key or ""))
        hatch = getattr(region, "region", None)
        vertices = tuple((float(x), float(y)) for x, y in tuple(getattr(hatch, "vertices", ()) or ()))
        if len(vertices) >= 3:
            return vertices
        polygon = getattr(hatch, "polygon", None)
        if polygon is not None and not getattr(polygon, "is_empty", True):
            try:
                coords = list(polygon.exterior.coords)
                if len(coords) > 1 and coords[0] == coords[-1]:
                    coords = coords[:-1]
                return tuple((float(x), float(y)) for x, y in coords)
            except Exception:
                return ()
        return ()

    def _payload_is_one_way(self, payload_or_item: dict | None) -> bool:
        return self._is_one_way_distribution((payload_or_item or {}).get("distribution"))

    def _one_way_item_for_vertices(self, item: dict, vertices) -> dict | None:
        if not self._payload_is_one_way(item):
            return dict(item or {})
        points = tuple((float(x), float(y)) for x, y in tuple(vertices or ()))
        if not is_one_way_tri_or_quad(points, tolerance=self._one_way_shape_tolerance()):
            return None
        angle = item.get("one_way_angle")
        if angle in (None, ""):
            angle = item.get("one_way_angle_deg")
        if angle in (None, ""):
            angle, _source, _warnings = infer_short_span_angle(points)
        try:
            normalized_angle = None if angle in (None, "") else float(angle) % 180.0
        except Exception:
            normalized_angle = None
        if normalized_angle is None:
            return None
        updated = dict(item or {})
        updated["distribution"] = DISTRIBUTION_ONE_WAY
        updated["one_way_angle"] = normalized_angle
        if "one_way_angle_deg" in updated:
            updated["one_way_angle_deg"] = normalized_angle
        return updated

    def _apply_load_item_to_dxf_regions(self, item: dict, region_keys) -> bool:
        item = self._hatch_load_item_for_current_mode(item)
        region_by_key = self.__dict__.get("hatch_view_region_by_key", {}) or {}
        keys = []
        for key in tuple(region_keys or ()):
            text = str(key or "")
            if text and text in region_by_key and text not in keys:
                keys.append(text)
        if not keys:
            return False
        with self._hatch_edit_command("DXF 해치 하중 적용"):
            applied = []
            excluded = 0
            one_way = str(item.get("distribution") or "").upper() == DISTRIBUTION_ONE_WAY
            for key in keys:
                item_for_key = item
                if one_way:
                    vertices = self._dxf_region_polygon_vertices_for_one_way(key)
                    item_for_key = self._one_way_item_for_vertices(item, vertices)
                    if item_for_key is None:
                        excluded += 1
                        continue
                if self._apply_load_item_to_dxf_region_no_history(item_for_key, key):
                    applied.append(key)
            if not applied:
                if one_way:
                    self._set_hatch_direct_status("ONE-WAY 하중은 3각형 또는 4각형 해치 영역에만 적용할 수 있습니다. 적용 가능한 선택 영역이 없습니다.")
                    return True
                return False
            self._select_dxf_hatch_regions(applied, mode="replace")
            self._sync_load_to_continuous_targets_for_region_keys(tuple(applied))
            name = str(item.get("display_name") or item.get("name") or "LOAD")
            if one_way:
                self._set_hatch_direct_status(
                    "자동 저장됨: ONE-WAY 하중 적용 완료 - "
                    f"선택 {len(keys)}개 중 {len(applied)}개 적용, "
                    f"{excluded}개 제외(3각형/4각형 조건 불만족)"
                )
            else:
                self._set_hatch_direct_status(f"자동 저장됨: 선택 DXF 해치 {len(applied)}개에 하중 적용")
            self._render_hatch_preview(focus_region_key=applied[0])
            self._refresh_selected_hatch_continuous_info()
            return True

    def _apply_load_item_to_dxf_region_no_history(self, item: dict, region_key: str) -> bool:
        region = self.__dict__.get("hatch_view_region_by_key", {}).get(str(region_key or ""))
        if region is None:
            return False
        if str(item.get("distribution") or "").upper() == DISTRIBUTION_ONE_WAY:
            item = self._one_way_item_for_vertices(item, self._dxf_region_polygon_vertices_for_one_way(region_key))
            if item is None:
                return False
        name = str(item.get("display_name") or item.get("name") or "LOAD")
        layer = self._hatch_load_layer_for_item(item)
        one_way_angle = item.get("one_way_angle")
        region.load = LoadLayerInfo(
            layer=layer,
            real_name=name,
            dl=float(item.get("dl", 0.0) or 0.0),
            ll=float(item.get("ll", 0.0) or 0.0),
            source="hatch_view_direct",
            distribution=str(item.get("distribution") or "TWO_WAY"),
            one_way_angle_deg=None if one_way_angle in (None, "") else float(one_way_angle),
            distribution_source="HATCH_VIEW_DIRECT",
        )
        region.status = "OK"
        return True

    def remove_selected_hatch_load(self) -> None:
        with self._hatch_edit_command("하중 제거"):
            states = self._hatch_edit_states_with_selection()
            if not states:
                region_keys = self._selected_dxf_region_keys()
                if region_keys:
                    for region_key in region_keys:
                        region = self.hatch_view_region_by_key[region_key]
                        region.load = None
                        region.status = "NO_LOAD"
                    self._sync_load_to_continuous_targets_for_region_keys(region_keys, remove=True)
                    self._set_hatch_direct_status(f"자동 저장됨: 선택 DXF 해치 {len(region_keys)}개 하중 제거")
                    self._render_hatch_preview(focus_region_key=region_keys[0])
                    self._refresh_selected_hatch_continuous_info()
                    return
                region_key = str(self.__dict__.get("hatch_view_selected_region_key") or "")
                if region_key and region_key in self.__dict__.get("hatch_view_region_by_key", {}):
                    region = self.hatch_view_region_by_key[region_key]
                    region.load = None
                    region.status = "NO_LOAD"
                    self._sync_load_to_continuous_targets_for_region_keys((region_key,), remove=True)
                    self._set_hatch_direct_status("자동 저장됨: 선택 DXF 해치 하중 제거")
                    self._render_hatch_preview(focus_region_key=region_key)
                    self._refresh_selected_hatch_continuous_info()
                    return
                self._set_hatch_direct_status("하중을 제거할 폐합 영역을 HATCH VIEW에서 선택해 주세요.")
                return
            previous_keys = self._selected_edit_region_keys_from_states(states)
            self._sync_load_to_continuous_targets_for_region_keys(previous_keys, remove=True)
            updated = [remove_load_from_selection(state) for state in states]
            self._store_hatch_edit_states(updated)
            current_keys = tuple(str(key or "") for key in tuple(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or ()) if str(key or ""))
            self._carry_continuous_targets_between_region_keys(previous_keys, current_keys)
            self._set_hatch_direct_status("자동 저장됨: 선택 폐합영역 하중 제거")
            self._render_hatch_preview()
            self._refresh_selected_hatch_continuous_info()

    def split_selected_hatch_region(self) -> None:
        with self._hatch_edit_command("해치분리"):
            states = self._hatch_edit_states_with_selection()
            if not states:
                self._set_hatch_direct_status("구분할 해치 영역을 HATCH VIEW에서 선택해 주세요.")
                return
            updated_states: list[HatchEditState] = []
            split_count = 0
            for state in states:
                updated = state
                for key in tuple(state.selected_region_keys):
                    before = len(updated.regions_by_key)
                    updated = split_region(updated, key)
                    if len(updated.regions_by_key) > before:
                        split_count += 1
                updated_states.append(updated)
            self._store_hatch_edit_states(updated_states)
            self._set_hatch_direct_status(f"자동 저장됨: 해치 영역 {split_count}개 구분")
            self._render_hatch_preview()
            self._refresh_selected_hatch_continuous_info()

    def _get_selected_load_items(self) -> list[dict]:
        selected: list[dict] = []
        for item in self.model_load_items:
            var = self.model_load_vars.get(str(item["key"]))
            if var and var.get():
                selected.append(item)
        for item in self.pdf_load_items:
            var = self.pdf_load_vars.get(str(item["key"]))
            if var and var.get():
                selected.append(item)
        return selected

    def _update_model_load_items(self, specs: list[FloorLoadTypeSpec]) -> None:
        previous = {key: bool(var.get()) for key, var in self.model_load_vars.items()}
        self.model_load_items = [
            self._make_load_item("MODEL", spec.name, spec.dl, spec.ll, index)
            for index, spec in enumerate(specs, start=1)
        ]
        self.model_load_vars = {
            str(item["key"]): tk.BooleanVar(value=previous.get(str(item["key"]), False))
            for item in self.model_load_items
        }
        if not self.load_selection_user_dirty:
            pdf_present = bool(self.__dict__.get("selected_pdf_paths", ()) or self.pdf_load_items)
            self._set_all_load_vars(self.model_load_items, self.model_load_vars, not pdf_present)
            self.load_selection_default_mode = "PDF_PRESENT_AUTO_CLEARED" if pdf_present else "MODEL_ONLY_AUTO_SELECTED"
        else:
            self.load_selection_default_mode = "USER_MANUAL"
        self.load_selection_source_signature = self._load_selection_signature()
        self._refresh_model_load_checklist()
        self._sync_final_load_list()

    def _update_pdf_load_items_from_lines(self, lines) -> None:
        previous = {key: bool(var.get()) for key, var in self.pdf_load_vars.items()}
        had_pdf_items = bool(self.pdf_load_items)
        items: list[dict] = []
        for line in lines or []:
            try:
                info = parse_load_layer(str(line))
            except Exception as exc:  # noqa: BLE001 - bad PDF candidates should not stop the GUI
                self.log(f"[PDF 하중목록] 해석 실패: {line} ({exc})")
                continue
            items.append(self._make_load_item("PDF", info.real_name, info.dl, info.ll, len(items) + 1))
        self.pdf_load_items = items
        self.pdf_load_vars = {
            str(item["key"]): tk.BooleanVar(value=previous.get(str(item["key"]), False))
            for item in self.pdf_load_items
        }
        if self.pdf_load_items and not self.load_selection_user_dirty:
            self._apply_pdf_present_default_selection()
        elif not self.pdf_load_items and not self.__dict__.get("selected_pdf_paths", ()) and not self.load_selection_user_dirty:
            self._set_all_load_vars(self.model_load_items, self.model_load_vars, True)
            self.load_selection_default_mode = "MODEL_ONLY_AUTO_SELECTED"
        elif self.load_selection_user_dirty:
            self.load_selection_default_mode = "USER_MANUAL"
        if had_pdf_items or self.pdf_load_items:
            self.load_selection_source_signature = self._load_selection_signature()
        self._refresh_pdf_load_lines_listbox()
        self._refresh_pdf_load_checklist()
        self._sync_final_load_list()

    def _refresh_pdf_load_lines_listbox(self) -> None:
        if not hasattr(self, "pdf_load_lines_listbox"):
            return
        self.pdf_load_lines_listbox.delete(0, "end")
        for item in self.pdf_load_items:
            self.pdf_load_lines_listbox.insert("end", str(item["line"]))

    def _handle_dxf_template_result(self, result) -> None:
        self._mark_dxf_generated_success(result.dxf_path)
        self._register_generated_dxf_result(result)
        self.mapping_path.set(str(result.mapping_json_path))
        if getattr(result, "layout_metadata_path", None):
            self.layout_metadata_path.set(str(result.layout_metadata_path))
            self.log(f"DXF layout metadata: {result.layout_metadata_path}")
        messagebox.showinfo(
            "DXF 템플릿 생성 완료",
            (
                "DXF 템플릿 생성이 완료되었습니다.\n\n"
                f"생성 파일:\n{result.dxf_path}\n\n"
                "이제 4번 [기준층 하중/연속층 적용] 탭에서 생성된 DXF와 모델 폐합영역을 기준으로 하중을 직접 입력할 수 있습니다.\n\n"
                "CAD에서 직접 HATCH를 작성할 경우에는 기존처럼 사용자 DXF를 선택하여 DXF 검증을 실행해도 됩니다."
            ),
            detail=(f"layout metadata: {result.layout_metadata_path}" if getattr(result, "layout_metadata_path", None) else ""),
        )

    def _register_generated_dxf_result(self, result) -> None:
        self.generated_dxf_metadata_warning = ""
        self.generated_dxf_metadata_path = Path(result.layout_metadata_path) if getattr(result, "layout_metadata_path", None) else None
        layouts = ()
        if self.generated_dxf_metadata_path:
            try:
                layouts = tuple(read_layout_metadata(self.generated_dxf_metadata_path))
            except Exception as exc:  # noqa: BLE001 - generated DXF remains usable without preview metadata
                self.log(f"DXF layout metadata read failed: {exc}")
                layouts = ()
        self.generated_dxf_layout_metadata = layouts
        self.generated_dxf_mode = "ALL_STORIES" if int(getattr(result, "story_count", 1) or 1) > 1 else "SINGLE_STORY"
        story_names = tuple(str(getattr(layout, "story_name", "") or "") for layout in layouts if str(getattr(layout, "story_name", "") or ""))
        if not story_names:
            story_names = self._generated_dxf_story_names_from_result(result)
        if not story_names:
            story_names = tuple(story.name for story in getattr(self, "stories", []) or () if str(getattr(story, "name", "") or ""))
            if story_names:
                self.generated_dxf_metadata_warning = (
                    "생성 DXF의 Story metadata를 찾지 못했습니다. 전체 Story 후보가 표시될 수 있으므로 층 선택을 확인해 주세요."
                )
        self.generated_dxf_story_names = story_names
        if hasattr(self, "hatch_view_display_mode_var"):
            self.hatch_view_display_mode_var.set("ALL" if self.generated_dxf_mode == "ALL_STORIES" else "STORY")
        if story_names and hasattr(self, "hatch_view_selected_story_var"):
            self.hatch_view_selected_story_var.set(story_names[0])
        self._refresh_hatch_work_tab_from_generated_dxf()

    def _register_hatch_view_layout_context_from_regions(self, regions, layout_metadata_path: str | None = None) -> None:
        region_list = tuple(regions or ())
        layouts = ()
        metadata_path = str(layout_metadata_path or "")
        if not metadata_path:
            for region in region_list:
                candidate = str(getattr(getattr(region, "region", None), "layout_metadata_path", "") or "")
                if candidate:
                    metadata_path = candidate
                    break
        if metadata_path:
            try:
                layouts = tuple(read_layout_metadata(metadata_path))
            except Exception as exc:  # noqa: BLE001 - loaded DXF remains previewable with placed geometry
                try:
                    self.log(f"HATCH VIEW layout metadata read failed: {exc}")
                except Exception:
                    pass
                layouts = ()

        story_names = tuple(str(getattr(layout, "story_name", "") or "") for layout in layouts if str(getattr(layout, "story_name", "") or ""))
        if not story_names:
            story_names = self._loaded_region_story_names(region_list)

        if layouts:
            self.generated_dxf_layout_metadata = layouts
            self.generated_dxf_metadata_path = Path(metadata_path)
        if story_names:
            self.generated_dxf_story_names = story_names

        region_story_names = self._loaded_region_story_names(region_list)
        has_all_story_context = len(story_names) > 1 or len(layouts) > 1 or (
            len(region_story_names) > 1 and self._loaded_regions_have_placed_coordinates(region_list)
        )
        self.generated_dxf_mode = "ALL_STORIES" if has_all_story_context else "SINGLE_STORY"

        display_mode_var = self.__dict__.get("hatch_view_display_mode_var")
        if display_mode_var is not None:
            try:
                display_mode_var.set("ALL" if has_all_story_context else "STORY")
            except Exception:
                pass

        selected_var = self.__dict__.get("hatch_view_selected_story_var")
        if story_names and selected_var is not None:
            try:
                current = str(selected_var.get() or "")
                if current not in story_names:
                    selected_var.set(story_names[0])
            except Exception:
                pass

        self._refresh_hatch_view_story_controls()

    def _generated_dxf_story_names_from_result(self, result) -> tuple[str, ...]:
        candidates: list[str] = []
        for attr in ("story_name", "selected_story_name"):
            value = str(getattr(result, attr, "") or "").strip()
            if value:
                candidates.append(value)
        for attr in ("story_names", "stories"):
            value = getattr(result, attr, None)
            if value is None:
                continue
            if isinstance(value, str):
                values = [value]
            else:
                try:
                    values = list(value)
                except TypeError:
                    values = [value]
            for item in values:
                name = str(getattr(item, "name", item) or "").strip()
                if name:
                    candidates.append(name)
        if int(getattr(result, "story_count", 0) or 0) == 1 and candidates:
            return (candidates[0],)
        unique: list[str] = []
        for name in candidates:
            if name not in unique:
                unique.append(name)
        return tuple(unique)

    def _refresh_hatch_work_tab_from_generated_dxf(self) -> None:
        self._refresh_hatch_view_story_controls()
        self._ensure_hatch_edit_states()
        self._configure_hatch_work_direct_input_button()
        if hasattr(self, "dxf_validation_status_var"):
            warning = str(self.__dict__.get("generated_dxf_metadata_warning") or "")
            self.dxf_validation_status_var.set(
                warning
                or "생성 DXF 기반 내부 입력 가능: 4번 탭에서 폐합영역을 선택해 하중을 직접 입력할 수 있습니다."
            )

    def _handle_mgt_build_result(self, result) -> None:
        self.result_label.configure(text=f"결과 파일: {result}")
        generated_model_path = getattr(result, "generated_model_path", None)
        if generated_model_path:
            self._mark_model_generated_success(generated_model_path)
        else:
            self._mark_model_not_generated("full MGT 생성 완료. API import/save as를 실행하지 않아 모델링 파일은 생성되지 않았습니다.")

    def _launch_file_with_default_app(self, path: Path) -> None:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
            return
        subprocess.Popen(["xdg-open", str(path)])

    def _open_file_with_default_app(self, path: str | Path, *, title: str = "파일 열기") -> bool:
        target = Path(path)
        if not target.exists():
            messagebox.showerror("파일 없음", f"파일을 찾을 수 없습니다:\n{target}")
            return False
        try:
            self._launch_file_with_default_app(target)
            return True
        except Exception as exc:  # noqa: BLE001 - OS shell open failures should be visible
            if hasattr(self, "logger"):
                self.logger.exception("failed to open file with default app")
            messagebox.showerror(f"{title} 실패", str(exc))
            return False

    def _open_path_with_default_app(self, path: Path) -> None:
        self._open_file_with_default_app(path)

    def open_last_generated_dxf(self) -> None:
        path_text = self.generated_dxf_path.get().strip() if hasattr(self, "generated_dxf_path") else ""
        path = Path(path_text) if path_text else self.last_generated_dxf_path
        if not path:
            messagebox.showwarning("DXF 파일 없음", "열 수 있는 DXF 파일이 없습니다. 먼저 DXF를 생성해 주세요.")
            return
        self._open_file_with_default_app(path, title="DXF 열기")

    def open_generated_model_file(self) -> None:
        path_text = self.generated_model_path.get().strip() if hasattr(self, "generated_model_path") else ""
        path = Path(path_text) if path_text else self.last_generated_model_path
        if not path:
            messagebox.showwarning("모델링 파일 없음", "열 수 있는 모델링 파일이 없습니다. 먼저 full MGT 생성 + 새 모델 import/save as를 실행해 주세요.")
            return
        self._open_file_with_default_app(path, title="모델링 파일 열기")

    def open_last_diagnostic_dxf(self) -> None:
        path = self.last_diagnostic_dxf_path
        if not path or not path.exists():
            messagebox.showwarning("진단 DXF 없음", "먼저 모델링 FLOORLOAD 입력 가능성 분석을 실행해 주세요.")
            return
        self._open_path_with_default_app(path)

    def open_last_diagnostic_report(self) -> None:
        path = self.last_diagnostic_report_path
        if not path or not path.exists():
            messagebox.showwarning("진단 보고서 없음", "먼저 모델링 FLOORLOAD 입력 가능성 분석을 실행해 주세요.")
            return
        self._open_path_with_default_app(path)

    def _resolve_layout_metadata_for_dxf(self, dxf: str | Path, *, allow_prompt: bool) -> str | None:
        self._ensure_current_project_workspace()
        explicit_text = self.layout_metadata_path.get().strip() if hasattr(self, "layout_metadata_path") else ""
        explicit = Path(explicit_text) if explicit_text else None
        selection = select_layout_metadata(
            dxf_path=Path(dxf),
            explicit_path=explicit,
            project_dxf_templates_dir=self.current_project_subdirs.get("dxf_templates"),
            project_root=self.current_project_dir,
        )
        if selection.selected_path:
            selected = str(selection.selected_path)
            self.layout_metadata_path.set(selected)
            self.log(
                "layout metadata 선택: "
                f"{selection.reason}, {selected}"
            )
            return selected
        if selection.selection_required and allow_prompt:
            selected_path = self._prompt_layout_metadata_candidate(selection)
            if selected_path:
                self.layout_metadata_path.set(str(selected_path))
                self.log(f"layout metadata 사용자 선택: {selected_path}")
                return str(selected_path)
        return None

    def _prompt_layout_metadata_candidate(self, selection: LayoutMetadataSelection) -> Path | None:
        if not selection.candidates:
            path = filedialog.askopenfilename(filetypes=[("Layout metadata", "*.layout_metadata.json *.json"), ("All files", "*.*")])
            return Path(path) if path else None

        dialog = tk.Toplevel(self)
        dialog.title("layout metadata 선택")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("920x360")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(
            dialog,
            text="전층 DXF layout metadata 후보가 여러 개입니다. 사용할 metadata를 선택해 주세요.",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        tree = ttk.Treeview(
            dialog,
            columns=("file", "folder", "stories", "score", "matches", "mtime"),
            show="headings",
            height=10,
        )
        for col, text, width in (
            ("file", "파일명", 220),
            ("folder", "폴더", 330),
            ("stories", "Story", 70),
            ("score", "Score", 80),
            ("matches", "Label 일치", 90),
            ("mtime", "수정시간", 150),
        ):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="w")
        by_item: dict[str, Path] = {}
        for item in selection.candidates:
            path = Path(item.path)
            details = item.details
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                modified = ""
            item_id = tree.insert(
                "",
                "end",
                values=(
                    path.name,
                    str(path.parent),
                    details.get("story_count", ""),
                    f"{item.score:.1f}",
                    details.get("label_match_count", ""),
                    modified,
                ),
            )
            by_item[item_id] = path
        first = tree.get_children()
        if first:
            tree.selection_set(first[0])
            tree.focus(first[0])
        tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)

        selected: dict[str, Path | None] = {"path": None}

        def choose_current() -> None:
            focus = tree.focus() or (tree.selection()[0] if tree.selection() else "")
            selected["path"] = by_item.get(focus)
            dialog.destroy()

        def choose_file() -> None:
            path_text = filedialog.askopenfilename(
                parent=dialog,
                filetypes=[("Layout metadata", "*.layout_metadata.json *.json"), ("All files", "*.*")],
            )
            selected["path"] = Path(path_text) if path_text else None
            dialog.destroy()

        def cancel() -> None:
            selected["path"] = None
            dialog.destroy()

        tree.bind("<Double-1>", lambda _event: choose_current())
        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="e", padx=10, pady=(4, 10))
        ttk.Button(buttons, text="파일에서 선택", command=choose_file).pack(side="left", padx=4)
        ttk.Button(buttons, text="선택", command=choose_current).pack(side="left", padx=4)
        ttk.Button(buttons, text="취소", command=cancel).pack(side="left", padx=4)
        self.wait_window(dialog)
        return selected["path"]

    def _selected_story(self) -> Story | None:
        name = self.selected_story_name.get()
        for story in self.stories:
            if story.name == name:
                return story
        return self.stories[0] if self.stories else None

    def _selected_dxf_story_mode(self) -> tuple[str, Story | None]:
        selected = self.selected_story_name.get()
        if selected in {ALL_STORIES_LABEL, ALL_STORIES_VALUE}:
            return ALL_STORIES_VALUE, None
        return "SINGLE", self._selected_story()

    def _load_layer_specs(self) -> list[LoadLayerSpec]:
        self._sync_final_load_list()
        return [
            LoadLayerSpec(
                real_name=str(item.get("display_name") or item["name"]),
                dl=float(item.get("dl", 0.0)),
                ll=float(item.get("ll", 0.0)),
            )
            for item in self.final_load_items
        ]

    def run_worker(self, title: str, fn) -> None:
        if self._busy:
            messagebox.showinfo("작업 진행 중", "현재 작업이 진행 중입니다. 완료 후 다시 실행해 주세요.")
            return
        self._set_busy(True, title)
        self._start_progress(title)
        self.log(f"[{title}] 시작")
        reporter = ProgressReporter(callback=lambda percent, message="": self.queue.put(("progress", (percent, message or title))))

        def wrapper():
            try:
                reporter.update(3.0, f"{title} 준비 중")
                try:
                    accepts_progress = bool(inspect.signature(fn).parameters)
                except (TypeError, ValueError):
                    accepts_progress = False
                result = fn(reporter) if accepts_progress else fn()
                reporter.update(95.0, f"{title} 마무리 중")
                self.queue.put(("done", (title, result)))
            except PermissionError as exc:
                self.logger.exception("%s failed", title)
                if title == "DXF 템플릿 생성":
                    message = (
                        "DXF 파일을 저장할 수 없습니다.\n\n"
                        "가능한 원인:\n"
                        "1. 같은 이름의 DXF 파일이 CAD/ZWCAD/AutoCAD에서 열려 있습니다.\n"
                        "2. DATA\\OUTPUT\\{project}\\dxf_templates 폴더에 쓰기 권한이 없습니다.\n"
                        "3. OneDrive/백신/권한 정책이 파일 생성을 막고 있습니다.\n\n"
                        "해결 방법:\n"
                        "- 열려 있는 DXF 파일을 닫고 다시 시도하세요.\n"
                        "- 또는 프로그램 폴더를 바탕화면이나 문서 폴더처럼 쓰기 가능한 위치로 옮겨 실행하세요.\n\n"
                        f"상세 오류:\n{exc}"
                    )
                    self.queue.put(("error", (title, message)))
                else:
                    self.queue.put(("error", (title, str(exc))))
            except Exception as exc:  # noqa: BLE001 - GUI must surface all errors
                self.logger.exception("%s failed", title)
                detail = getattr(exc, "detail", "")
                self.queue.put(("error", (title, f"{exc}\n{detail}" if detail else str(exc))))

        threading.Thread(target=wrapper, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "done":
                    title, result = payload
                    self.log(f"[{title}] 완료: {result}")
                    if title == "DXF 템플릿 생성":
                        self._handle_dxf_template_result(result)
                    elif title.startswith("MGT"):
                        self._handle_mgt_build_result(result)
                    self._finish_progress("완료")
                    self._set_busy(False)
                elif kind == "error":
                    title, message = payload
                    self.log(f"[{title}] 오류: {message}")
                    if title == "DXF 템플릿 생성":
                        self._mark_dxf_generated_failed(str(message))
                    elif title == "MGT 생성/import":
                        self._mark_model_generated_failed(str(message))
                    elif title == "MGT 생성":
                        self._mark_model_not_generated("full MGT 생성에 실패했습니다. 모델링 파일은 생성되지 않았습니다.")
                    self._error_progress("오류")
                    self._set_busy(False)
                    messagebox.showerror(title, message)
                elif kind == "progress":
                    percent, message = payload
                    self._set_progress(percent, message)
                elif kind == "log":
                    self.log(str(payload))
                elif kind == "dxf_status":
                    if hasattr(self, "dxf_validation_status_var"):
                        self.dxf_validation_status_var.set(str(payload))
                elif kind == "stories":
                    self._refresh_story_tree(payload)
                elif kind == "regions":
                    self._refresh_region_tree(payload)
                elif kind == "typical_analysis":
                    self._refresh_typical_floor_analysis(payload)
                elif kind == "diagnostics":
                    self._refresh_diagnostic_tree(payload)
                elif kind == "floorload_status":
                    self._update_floorload_status(payload)
                elif kind == "model_load_items":
                    self._update_model_load_items(payload)
                elif kind == "pdf_rows":
                    self._update_pdf_result(payload)
                elif kind == "auto_floorload_diagnostics":
                    data = payload if isinstance(payload, dict) else {}
                    self._start_auto_floorload_diagnostics(reason=str(data.get("reason", "") or ""))
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _refresh_story_tree(self, stories: list[Story]) -> None:
        self._reset_typical_floor_state(reason="Story 목록 갱신")
        for item in self.story_tree.get_children():
            self.story_tree.delete(item)
        for story in stories:
            self.story_tree.insert("", "end", values=(story.name, f"{story.elevation:g}", "" if story.height is None else f"{story.height:g}"))
        if stories:
            first = self.story_tree.get_children()[0]
            self.story_tree.selection_set(first)
            self.selected_story_name.set(stories[0].name)
        if hasattr(self, "dxf_story_combo"):
            story_names = [story.name for story in stories]
            display_values = [ALL_STORIES_LABEL] + story_names if story_names else []
            self.dxf_story_combo.configure(values=display_values)
            if story_names and self.selected_story_name.get() not in display_values:
                self.selected_story_name.set(story_names[0])
            if not story_names:
                self.dxf_story_combo.configure(values=[])
                self.selected_story_name.set("")
        self._refresh_continuous_base_story_values()

    def _on_dxf_story_combo_selected(self, _event=None) -> None:
        selected = self.selected_story_name.get()
        if not selected or not hasattr(self, "story_tree"):
            return
        if selected in {ALL_STORIES_LABEL, ALL_STORIES_VALUE}:
            try:
                self.story_tree.selection_remove(self.story_tree.selection())
            except Exception:
                pass
            return
        try:
            for item_id in self.story_tree.get_children():
                values = self.story_tree.item(item_id, "values")
                if values and str(values[0]) == selected:
                    self.story_tree.selection_set(item_id)
                    self.story_tree.see(item_id)
                    break
        except Exception as exc:  # noqa: BLE001 - selection sync should never stop DXF flow
            self.logger.warning("failed to sync DXF story combo selection: %s", exc)

    def _refresh_region_tree(self, regions) -> None:
        self._reset_hatch_edit_history("DXF validation 결과 교체")
        self._reset_continuous_apply_state(reason="DXF 재검증")
        self.loaded_regions = list(regions or [])
        self._register_hatch_view_layout_context_from_regions(self.loaded_regions)
        self._recompute_hatch_continuous_checks(regions=self.loaded_regions)
        for item in self.dxf_tree.get_children():
            self.dxf_tree.delete(item)
        self.dxf_region_by_tree_iid = {}
        self.dxf_region_key_by_tree_iid = {}
        self.dxf_tree_iid_by_region_key = {}
        for index, region in enumerate(self.loaded_regions, start=1):
            region_key = self._region_key(region, index=index)
            load = region.load
            mode, mode_source = infer_distribution(region.region, load) if load else ("", "")
            direction_markers = list(getattr(region.region, "direction_markers", []) or [])
            direction_summary = str(len(direction_markers))
            if direction_markers:
                marker_ids = ",".join(str(getattr(marker, "source_id", "") or "") for marker in direction_markers)
                match_methods = ",".join(str(getattr(marker, "match_method", "") or "") for marker in direction_markers)
                direction_summary = f"{len(direction_markers)} / {match_methods} / {marker_ids}"
            iid = f"dxf_region_{index}"
            self.dxf_region_by_tree_iid[iid] = region
            self.dxf_region_key_by_tree_iid[iid] = region_key
            self.dxf_tree_iid_by_region_key[region_key] = iid
            continuous_label = self._continuous_check_label(self.continuous_hatch_checks.get(region_key))
            self.dxf_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    region.status,
                    region.region.story_name,
                    continuous_label,
                    "YES" if getattr(region.region, "layout_metadata_used", False) else "NO",
                    "YES" if getattr(region.region, "transform_applied", False) else "NO",
                    region.region.source_type,
                    region.region.layer,
                    region.region.hatch_pattern_name,
                    "YES" if region.region.hatch_solid_fill else "NO",
                    mode,
                    mode_source,
                    direction_summary,
                    load.real_name if load else "",
                    "" if not load else f"{load.dl:.2f}",
                    "" if not load else f"{load.ll:.2f}",
                    f"{region.area:.6g}",
                    _format_region_bbox_for_ui(getattr(region.region, "placed_bbox", ()) or ()),
                    _format_region_bbox_for_ui(getattr(region.region, "model_bbox", ()) or getattr(region.region, "bbox", ()) or ()),
                    region.region.source_id,
                    " | ".join(region.warnings),
                ),
            )
        self._refresh_continuous_base_story_values()
        self._render_hatch_preview()
        self._update_dxf_validation_status()

    def _update_dxf_validation_status(self) -> None:
        total = len(getattr(self, "loaded_regions", []) or [])
        can_apply = sum(1 for check in getattr(self, "continuous_hatch_checks", {}).values() if check.get("can_select"))
        if total:
            message = (
                f"DXF 검증 완료: 하중 해치 {total}개, 연속층 적용 가능 {can_apply}개. "
                "다음 단계는 [기준층 하중/연속층 적용] 탭에서 HATCH VIEW로 확인하세요."
            )
            if hasattr(self, "open_hatch_work_tab_button"):
                self.open_hatch_work_tab_button.state(["!disabled"])
        else:
            message = "DXF 검증 결과가 없습니다. 사용자 작성 DXF를 선택하고 검증해 주세요."
            if hasattr(self, "open_hatch_work_tab_button"):
                self.open_hatch_work_tab_button.state(["disabled"])
        if hasattr(self, "dxf_validation_status_var"):
            self.dxf_validation_status_var.set(message)

    def _refresh_typical_floor_analysis(self, analysis) -> None:
        self.typical_floor_analysis = analysis
        self.typical_floor_groups = tuple(getattr(analysis, "groups", ()) or ())
        self.story_shape_profiles = tuple(getattr(analysis, "profiles", ()) or ())
        typical_names = typical_story_names(self.typical_floor_groups)
        transition_count = sum(len(group.transition_floor_names) for group in self.typical_floor_groups)
        if hasattr(self, "typical_analysis_summary_var"):
            self.typical_analysis_summary_var.set(
                f"기준층 그룹 {len(self.typical_floor_groups)}개 | typ. {', '.join(typical_names) or '없음'} | 전이층 {transition_count}개"
            )
        if hasattr(self, "typical_group_tree"):
            for item in self.typical_group_tree.get_children():
                self.typical_group_tree.delete(item)
            for group in self.typical_floor_groups:
                stories = list(group.story_names)
                story_range = f"{stories[0]} ~ {stories[-1]}" if stories else ""
                self.typical_group_tree.insert(
                    "",
                    "end",
                    values=(
                        group.group_id,
                        story_range,
                        group.typical_story_name or "",
                        f"{group.typical_score:.3f}",
                        ", ".join(group.transition_floor_names),
                        "OK" if group.typical_story_name else "Review",
                        group.reason,
                    ),
                )
        if hasattr(self, "typical_story_tree"):
            for item in self.typical_story_tree.get_children():
                self.typical_story_tree.delete(item)
            for profile in self.story_shape_profiles:
                group = self._typical_group_for_story(profile.story_name)
                score = self._story_typical_similarity_score(profile, group)
                is_typical = bool(group and group.typical_story_name == profile.story_name)
                is_transition = bool(group and profile.story_name in group.transition_floor_names)
                self.typical_story_tree.insert(
                    "",
                    "end",
                    values=(
                        profile.story_name,
                        f"{profile.story_elevation:g}",
                        "" if group is None else group.group_id,
                        "YES" if is_typical else "",
                        "" if score is None else f"{score:.3f}",
                        "YES" if is_transition else "",
                    ),
                )
        self._refresh_continuous_base_story_values()
        if self.loaded_regions:
            self._recompute_hatch_continuous_checks()
            self._render_hatch_preview()

    def _typical_group_for_story(self, story_name: str):
        for group in self.typical_floor_groups:
            if story_name in group.story_names:
                return group
        return None

    def _story_typical_similarity_score(self, profile, group) -> float | None:
        if group is None or not group.typical_story_name:
            return None
        if profile.story_name == group.typical_story_name:
            return group.typical_score
        analysis = getattr(self, "typical_floor_analysis", None)
        for similarity in tuple(getattr(analysis, "similarities", ()) or ()):
            if {similarity.story_a, similarity.story_b} == {profile.story_name, group.typical_story_name}:
                return similarity.score
        return None

    def _on_dxf_region_selected(self, _event=None) -> None:
        selection = self.dxf_tree.selection() if hasattr(self, "dxf_tree") else ()
        continuous_refreshed = False
        if selection:
            region_key = self.dxf_region_key_by_tree_iid.get(selection[0])
            if region_key:
                self._select_dxf_hatch_regions([region_key], mode="replace")
                self._load_selected_hatch_as_base_story(region_key)
                self._load_continuous_candidates_for_region(region_key, silent=True, allow_unavailable=True)
                continuous_refreshed = True
        self._render_hatch_preview()
        if not continuous_refreshed:
            self._refresh_selected_hatch_continuous_info()

    def _selected_dxf_load_region(self):
        selected_key = getattr(self, "hatch_view_selected_region_key", None)
        if selected_key and selected_key in getattr(self, "hatch_view_region_by_key", {}):
            return self.hatch_view_region_by_key[selected_key]
        if not hasattr(self, "dxf_tree"):
            return None
        selection = self.dxf_tree.selection()
        if selection:
            return self.dxf_region_by_tree_iid.get(selection[0])
        if self.loaded_regions:
            return self.loaded_regions[0]
        return None

    def _region_key(self, region, index: int | None = None) -> str:
        hatch = getattr(region, "region", region)
        source_id = getattr(hatch, "source_id", "") or getattr(hatch, "handle", "") or ""
        story_name = getattr(hatch, "story_name", "") or ""
        layer = getattr(hatch, "layer", "") or ""
        if source_id:
            return f"{story_name}|{source_id}"
        if index is not None:
            return f"{story_name}|{layer}|{index}"
        return f"{story_name}|{layer}|{id(region)}"

    def _continuous_check_label(self, check: dict[str, object] | None) -> str:
        if not check:
            return "기준층 분석 필요"
        if check.get("needs_analysis"):
            return "기준층 분석 필요"
        if check.get("can_select"):
            count = len(tuple(check.get("applicable_targets", ()) or ()))
            return f"가능({count}개층)"
        return "불가"

    def _recompute_hatch_continuous_checks(self, regions=None) -> None:
        region_list = list(self.loaded_regions if regions is None else (regions or []))
        self.continuous_hatch_checks = {}
        self.hatch_view_region_by_key = {}
        self._invalidate_visible_targets_cache("연속층 후보 재계산")
        if not region_list:
            return
        if not self.story_shape_profiles:
            self._ensure_typical_floor_analysis(reason="DXF 검증 후 연속층 가능 여부 계산")
        ordered_story_names = [profile.story_name for profile in (self.story_shape_profiles or ())]
        for index, region in enumerate(region_list, start=1):
            region_key = self._region_key(region, index=index)
            self.hatch_view_region_by_key[region_key] = region
            base_story = str(getattr(region.region, "story_name", "") or "")
            if not self.story_shape_profiles:
                self.continuous_hatch_checks[region_key] = {
                    "region": region,
                    "base_story": base_story,
                    "can_select": False,
                    "needs_analysis": True,
                    "reason": "기준층 분석 필요",
                    "candidates": (),
                    "applicable_targets": (),
                    "recommended_targets": (),
                    "ranges": (),
                }
                continue
            if not base_story:
                self.continuous_hatch_checks[region_key] = {
                    "region": region,
                    "base_story": "",
                    "can_select": False,
                    "reason": "Story 인식 필요",
                    "candidates": (),
                    "applicable_targets": (),
                    "recommended_targets": (),
                    "ranges": (),
                }
                continue
            candidates = evaluate_continuous_apply_candidates(
                self.story_shape_profiles,
                base_story_name=base_story,
                target_story_names=ordered_story_names,
                hatch_polygon_xy=self._region_vertices(region),
                typical_groups=self.typical_floor_groups,
                xy_tolerance=float(self.snap_tol_var.get() if hasattr(self, "snap_tol_var") else self.config_data.snap_tolerance),
            )
            story_order_without_base = [name for name in ordered_story_names if name != base_story]
            ranges = split_continuous_apply_ranges(candidates, story_order_without_base)
            raw_applicable = tuple(candidate.target_story_name for candidate in candidates if candidate.can_apply)
            base_centered = self._base_centered_applicable_story_names(
                base_story=base_story,
                candidates=candidates,
                story_order=ordered_story_names,
            )
            blocked = tuple(
                (candidate.target_story_name, candidate.reason)
                for candidate in candidates
                if not candidate.can_apply
            )
            self.continuous_hatch_checks[region_key] = {
                "region": region,
                "base_story": base_story,
                "can_select": bool(base_centered),
                "reason": "OK" if base_centered else "적용 가능한 연속층 없음",
                "candidates": candidates,
                "applicable_targets": tuple(base_centered),
                "all_applicable_targets": raw_applicable,
                "recommended_targets": tuple(base_centered),
                "base_centered_targets": tuple(base_centered),
                "ranges": ranges,
                "blocked_targets": blocked,
            }

    def _nearest_continuous_range(self, base_story: str, ranges, story_order: list[str]) -> tuple[str, ...]:
        if not ranges:
            return ()
        try:
            base_index = story_order.index(base_story)
        except ValueError:
            return tuple(ranges[0])
        return tuple(
            min(
                ranges,
                key=lambda items: min(abs(story_order.index(name) - base_index) for name in items if name in story_order),
            )
        )

    def _base_centered_applicable_story_names(self, *, base_story: str, candidates, story_order) -> tuple[str, ...]:
        order = [str(name or "") for name in tuple(story_order or ()) if str(name or "")]
        can_apply = {
            str(getattr(candidate, "target_story_name", "") or "")
            for candidate in tuple(candidates or ())
            if _continuous_candidate_can_apply(candidate)
        }
        base = str(base_story or "")
        if not order:
            return tuple(sorted(name for name in can_apply if name != base))
        ordered = [name for name in order if name in can_apply and name != base]
        ordered.extend(sorted(name for name in can_apply if name not in set(ordered) and name != base))
        return tuple(ordered)

    def _story_order_names(self) -> list[str]:
        names: list[str] = []
        for profile in tuple(self.__dict__.get("story_shape_profiles", ()) or ()):
            name = str(getattr(profile, "story_name", "") or "")
            if name and name not in names:
                names.append(name)
        for name in tuple(self.__dict__.get("generated_dxf_story_names") or ()):
            text = str(name or "")
            if text and text not in names:
                names.append(text)
        for story in tuple(self.__dict__.get("stories", ()) or ()):
            name = str(getattr(story, "name", "") or "")
            if name and name not in names:
                names.append(name)
        for region in tuple(self.__dict__.get("loaded_regions", ()) or ()):
            name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
            if name and name not in names:
                names.append(name)
        return names

    def _float_setting_value(self, attr_name: str, default: float) -> float:
        value = self.__dict__.get(attr_name)
        try:
            return float(value.get()) if value is not None and hasattr(value, "get") else float(default)
        except Exception:
            return float(default)

    def _hatch_perf_enabled(self) -> bool:
        value = os.environ.get("MIDAS_HATCH_PERF", "1").strip().lower()
        if value in {"0", "false", "off", "no"}:
            return False
        return self.__dict__.get("logger") is not None

    def _hatch_perf_start(self, label: str):
        if not self._hatch_perf_enabled():
            return None
        return (str(label or ""), time.perf_counter())

    def _hatch_perf_end(self, token, **data) -> float:
        if not token:
            return 0.0
        label, started_at = token
        elapsed_ms = (time.perf_counter() - float(started_at)) * 1000.0
        threshold_ms = float(data.pop("threshold_ms", 100.0))
        self._hatch_perf_log_if_slow(str(label), elapsed_ms, threshold_ms=threshold_ms, **data)
        return elapsed_ms

    def _hatch_perf_log_if_slow(self, label: str, elapsed_ms: float, threshold_ms: float = 100, **data) -> None:
        if not self._hatch_perf_enabled():
            return
        if float(elapsed_ms) < float(threshold_ms):
            return
        logger = self.__dict__.get("logger")
        if logger is None:
            return
        try:
            details = " ".join(f"{key}={value}" for key, value in sorted(data.items()))
            suffix = f" {details}" if details else ""
            logger.debug("HATCH VIEW perf: %s elapsed_ms=%.1f%s", str(label or ""), float(elapsed_ms), suffix)
        except Exception:
            pass

    def _current_mgt_text_signature(self) -> tuple[int, str]:
        text = str(self.__dict__.get("current_mgt_text", "") or "")
        state = (id(text), len(text))
        cached = self.__dict__.get("_current_mgt_text_signature_cache")
        if cached and cached[0] == state:
            return cached[1]
        digest = hashlib.blake2b(text.encode("utf-8", errors="ignore"), digest_size=8).hexdigest() if text else ""
        signature = (len(text), digest)
        self._current_mgt_text_signature_cache = (state, signature)
        return signature

    def _story_below_allowed_polygon_cache_token(self) -> tuple[object, ...]:
        stories = self.__dict__.get("stories", ()) or ()
        nodes = self.__dict__.get("nodes", ()) or ()
        elements = self.__dict__.get("elements", ()) or ()
        story_tolerance = self._float_setting_value("story_tol_var", self._model_story_tolerance())
        geometry_tolerance = self._closed_region_geometry_tolerance()
        return (
            id(stories),
            len(stories),
            id(nodes),
            len(nodes),
            id(elements),
            len(elements),
            round(float(story_tolerance), 12),
            round(float(geometry_tolerance), 12),
            self._current_mgt_text_signature(),
        )

    def _hatch_edit_state_geometry_token(self, story_name: str) -> tuple[object, ...]:
        approved = tuple(
            sorted(
                (
                    str(plan.issue_key),
                    int(plan.free_node_id),
                    int(plan.boundary_node_id),
                    tuple(round(float(value), 9) for value in (*plan.start_xy, *plan.end_xy)),
                )
                for plan in (self.__dict__.get("approved_dummy_plans", {}) or {}).values()
                if str(plan.story_name) == str(story_name) and bool(plan.approved) and not str(plan.collision_reason or "")
            )
        )
        base = (str(story_name or ""), *self._story_below_allowed_polygon_cache_token())
        return (*base, ("APPROVED_LOAD_DM", approved)) if approved else base

    def _approved_dummy_segments_by_story(self) -> dict[str, tuple[ExtraBoundarySegment, ...]]:
        by_story: dict[str, list[ExtraBoundarySegment]] = {}
        for plan in (self.__dict__.get("approved_dummy_plans", {}) or {}).values():
            if not bool(getattr(plan, "approved", False)) or str(getattr(plan, "collision_reason", "") or ""):
                continue
            segment = ExtraBoundarySegment(
                story_name=str(plan.story_name),
                node_i=int(plan.free_node_id),
                node_j=int(plan.boundary_node_id),
                start_xy=tuple(plan.start_xy),
                end_xy=tuple(plan.end_xy),
                issue_key=str(plan.issue_key),
            )
            by_story.setdefault(str(plan.story_name), []).append(segment)
        return {name: tuple(values) for name, values in by_story.items()}

    def _invalidate_dummy_virtual_boundaries(self, reason: str = "") -> None:
        _ = reason
        tokens = self.__dict__.setdefault("_hatch_edit_state_geometry_token_by_story", {})
        for name in tuple((self.__dict__.get("hatch_edit_states_by_story", {}) or {}).keys()):
            tokens[str(name)] = ("__LOAD_DM_VIRTUAL_BOUNDARY_STALE__",)
        self.dummy_overlay_render_fingerprint = None
        self._invalidate_continuous_below_allowed_reason_cache(reason or "LOAD DM 가상 경계 변경")

    def _update_dummy_action_buttons(self) -> None:
        selected = str(self.__dict__.get("selected_dummy_issue_key") or "")
        issue = (self.__dict__.get("dummy_issue_by_key", {}) or {}).get(selected)
        preview = self.__dict__.get("dummy_preview_plan")
        approved = selected in (self.__dict__.get("approved_dummy_plans", {}) or {})
        create_enabled = bool(
            issue is not None
            and getattr(issue, "can_generate", False)
            and preview is not None
            and not str(getattr(preview, "collision_reason", "") or "")
            and not approved
        )
        create_button = self.__dict__.get("dummy_create_button")
        cancel_button = self.__dict__.get("dummy_cancel_button")
        if create_button is not None:
            create_button.configure(state="normal" if create_enabled else "disabled")
        if cancel_button is not None:
            cancel_button.configure(state="normal" if approved else "disabled")

    def _clear_dummy_issue_selection(self, *, update_overlay: bool = True) -> None:
        self.selected_dummy_issue_key = None
        self.dummy_preview_plan = None
        self._update_dummy_action_buttons()
        if update_overlay:
            self._update_dummy_member_overlay()

    def _select_dummy_issue(self, issue_key: str) -> bool:
        issue = (self.__dict__.get("dummy_issue_by_key", {}) or {}).get(str(issue_key or ""))
        if issue is None:
            self._clear_dummy_issue_selection()
            return False
        self.selected_dummy_issue_key = issue.issue_key
        self.dummy_preview_plan = self._dummy_preview_plan_for_issue(issue)
        if self.dummy_preview_plan is None:
            self.dummy_status_var.set(issue.reason_ko or "이 문제는 자동 LOAD DM 후보를 만들 수 없습니다.")
        elif self.dummy_preview_plan.collision_reason:
            self.dummy_status_var.set(f"LOAD DM 후보 무효: {self.dummy_preview_plan.collision_reason}")
        else:
            self.dummy_status_var.set(
                f"LOAD DM 후보: node {self.dummy_preview_plan.free_node_id} → {self.dummy_preview_plan.boundary_node_id}, "
                f"길이 {self.dummy_preview_plan.length:.3f}"
            )
        self._update_dummy_action_buttons()
        self._update_dummy_member_overlay()
        return self.dummy_preview_plan is not None

    def _dummy_preview_plan_for_issue(self, issue: DummyIssueViewModel) -> DummyConnectionPlan | None:
        if not issue.can_generate or issue.free_node_id is None or not issue.candidate_boundary_nodes:
            return None
        node_by_id = {int(node.node_id): node for node in tuple(self.__dict__.get("nodes", ()) or ())}
        start = node_by_id.get(int(issue.free_node_id))
        if start is None:
            return None
        mgt_text = str(self.__dict__.get("current_mgt_text", "") or "")
        first_invalid: DummyConnectionPlan | None = None
        for boundary_node_id in issue.candidate_boundary_nodes:
            end = node_by_id.get(int(boundary_node_id))
            if end is None:
                continue
            length = math.hypot(float(end.x) - float(start.x), float(end.y) - float(start.y))
            plan = DummyConnectionPlan(
                issue_key=issue.issue_key,
                story_name=issue.story_name,
                free_node_id=int(start.node_id),
                boundary_node_id=int(end.node_id),
                start_xy=(float(start.x), float(start.y)),
                end_xy=(float(end.x), float(end.y)),
                length=length,
                source_element_ids=tuple(issue.source_element_ids),
                collision_checked=bool(mgt_text),
                collision_reason="",
                approved=False,
                temporary_plan_id=f"LOAD_DM_PLAN:{issue.issue_key}",
            )
            if not mgt_text:
                return plan
            probe = generate_load_dm_dummy_members(
                mgt_text=mgt_text,
                approved_plans=(replace(plan, approved=True),),
                story_tolerance=self._model_story_tolerance(),
                enabled=True,
            )
            record = next((item for item in probe.records if str(item.region_id) == str(issue.issue_key)), None)
            if record is not None and record.status in {"CREATED", "REUSED"}:
                return replace(plan, final_element_id=record.dummy_element_id, release_added=record.release_added)
            reason = ""
            if record is not None:
                reason = str(record.interference_reason or record.skip_reason or "")
            first_invalid = first_invalid or replace(plan, collision_reason=reason or "LOAD_DM_CANDIDATE_INVALID")
        return first_invalid

    def _approve_selected_dummy_plan(self, *, confirm: bool = True) -> bool:
        plan = self.__dict__.get("dummy_preview_plan")
        if plan is None or str(plan.collision_reason or ""):
            return False
        if confirm:
            message = (
                f"free node: {plan.free_node_id}\n"
                f"target node: {plan.boundary_node_id}\n"
                f"distance: {plan.length:.3f}\n"
                f"source element: {', '.join(map(str, plan.source_element_ids)) or '-'}\n"
                "충돌 검사: 통과\n\n생성 예정 LOAD DM으로 승인하시겠습니까?"
            )
            if not messagebox.askyesno("LOAD DM 승인", message):
                return False
        with self._hatch_edit_command("LOAD DM 승인"):
            approved = replace(plan, approved=True)
            self.approved_dummy_plans[str(plan.issue_key)] = approved
            issue = (self.__dict__.get("dummy_issue_by_key", {}) or {}).get(str(plan.issue_key))
            if issue is not None:
                self.dummy_issue_by_key[str(plan.issue_key)] = replace(issue, status="RESOLVED_PENDING")
            self.dummy_preview_plan = None
            self._invalidate_dummy_virtual_boundaries("LOAD DM 승인")
        self.dummy_status_var.set("생성 예정 LOAD DM을 가상 경계로 반영했습니다.")
        self._update_dummy_action_buttons()
        self._ensure_hatch_edit_states(str(plan.story_name))
        self._update_dummy_member_overlay()
        return True

    def _cancel_selected_dummy_plan(self) -> bool:
        key = str(self.__dict__.get("selected_dummy_issue_key") or "")
        if not key or key not in (self.__dict__.get("approved_dummy_plans", {}) or {}):
            return False
        plan = self.approved_dummy_plans[key]
        with self._hatch_edit_command("LOAD DM 승인 취소"):
            self.approved_dummy_plans.pop(key, None)
            issue = (self.__dict__.get("dummy_issue_by_key", {}) or {}).get(key)
            if issue is not None:
                self.dummy_issue_by_key[key] = replace(issue, status="OPEN")
            self.dummy_preview_plan = self._dummy_preview_plan_for_issue(self.dummy_issue_by_key[key]) if key in self.dummy_issue_by_key else None
            self._invalidate_dummy_virtual_boundaries("LOAD DM 승인 취소")
        self.dummy_status_var.set("LOAD DM 승인을 취소하고 원래 경계를 복원했습니다.")
        self._update_dummy_action_buttons()
        self._ensure_hatch_edit_states(str(plan.story_name))
        self._update_dummy_member_overlay()
        return True

    def _story_below_element_index_cache_token(self) -> tuple[object, ...]:
        stories = self.__dict__.get("stories", ()) or ()
        nodes = self.__dict__.get("nodes", ()) or ()
        elements = self.__dict__.get("elements", ()) or ()
        story_tolerance = self._float_setting_value("story_tol_var", self._model_story_tolerance())
        return (
            id(stories),
            len(stories),
            id(nodes),
            len(nodes),
            id(elements),
            len(elements),
            round(float(story_tolerance), 12),
        )

    def _story_below_element_ids_by_story(self) -> dict[str, tuple[int, ...]]:
        try:
            token = self._story_below_element_index_cache_token()
        except Exception:
            token = None
        cached_token = self.__dict__.get("_story_below_element_index_cached_token")
        cached = self.__dict__.get("_story_below_element_ids_cache")
        if token is not None and cached_token == token and isinstance(cached, dict):
            self._story_below_element_index_cache_hits = int(self.__dict__.get("_story_below_element_index_cache_hits", 0) or 0) + 1
            return {str(name): tuple(ids) for name, ids in cached.items()}

        self._story_below_element_index_cache_misses = int(self.__dict__.get("_story_below_element_index_cache_misses", 0) or 0) + 1
        stories = list(self.__dict__.get("stories", ()) or ())
        nodes = list(self.__dict__.get("nodes", ()) or ())
        elements = list(self.__dict__.get("elements", ()) or ())
        node_by_id = {int(getattr(node, "node_id")): node for node in nodes if getattr(node, "node_id", None) is not None}
        tolerance = self._float_setting_value("story_tol_var", self._model_story_tolerance())
        element_by_id = {
            int(getattr(element, "elem_id")): element
            for element in elements
            if getattr(element, "elem_id", None) is not None
        }
        by_story: dict[str, tuple[int, ...]] = {}
        for story in stories:
            story_name = str(getattr(story, "name", "") or "")
            if not story_name:
                continue
            story_range = story_below_range(stories, story, tolerance)
            ids = [
                int(getattr(element, "elem_id"))
                for element in elements
                if getattr(element, "elem_id", None) is not None
                and element_is_in_story_below_range(element, node_by_id, story_range, tolerance)
            ]
            by_story[story_name] = tuple(ids)
        if token is not None:
            self._story_below_element_index_cached_token = token
            self._story_below_element_ids_cache = by_story
            self._story_below_element_by_id_cache = element_by_id
        return {str(name): tuple(ids) for name, ids in by_story.items()}

    def _invalidate_story_element_index_cache(self, reason: str = "") -> None:
        _ = reason
        self._story_below_element_index_cached_token = None
        self._story_below_element_ids_cache = {}
        self._story_below_element_by_id_cache = {}
        self._hatch_section_display_sizes_cache = None
        self._hatch_wall_thicknesses_cache = None
        self._hatch_structure_preview_cache_token = None
        self._hatch_structure_preview_cache = {}

    def _story_below_elements_for_story(self, story_name: str) -> tuple[object, ...]:
        name = str(story_name or "")
        if not name:
            return ()
        ids_by_story = self._story_below_element_ids_by_story()
        element_by_id = self.__dict__.get("_story_below_element_by_id_cache") or {
            int(getattr(element, "elem_id")): element
            for element in list(self.__dict__.get("elements", ()) or ())
            if getattr(element, "elem_id", None) is not None
        }
        return tuple(element_by_id[elem_id] for elem_id in tuple(ids_by_story.get(name, ()) or ()) if elem_id in element_by_id)

    def _story_below_elements_by_story_for_detector(self, story_names: Sequence[str] | None = None) -> dict[str, tuple[object, ...]]:
        requested = {str(name) for name in tuple(story_names or ()) if str(name or "")}
        ids_by_story = self._story_below_element_ids_by_story()
        element_by_id = self.__dict__.get("_story_below_element_by_id_cache") or {}
        result: dict[str, tuple[object, ...]] = {}
        for story_name, ids in ids_by_story.items():
            if requested and story_name not in requested:
                continue
            result[story_name] = tuple(element_by_id[elem_id] for elem_id in ids if elem_id in element_by_id)
        return result

    def _invalidate_story_below_allowed_polygon_cache(self, reason: str = "") -> None:
        self._story_below_allowed_polygon_cached_token = None
        self._story_below_allowed_polygon_cache = None
        self._invalidate_story_element_index_cache(reason or "BELOW element index cache reset")
        self._invalidate_continuous_below_allowed_reason_cache(reason or "BELOW 허용영역 캐시 초기화")

    def _invalidate_continuous_below_allowed_reason_cache(self, reason: str = "") -> None:
        self._continuous_below_allowed_reason_cache = {}
        self._invalidate_continuous_conflict_caches(reason or "연속층 conflict cache reset")
        self._invalidate_visible_targets_cache(reason or "BELOW target 검증 캐시 초기화")

    def _invalidate_visible_targets_cache(self, reason: str = "") -> None:
        self._visible_targets_cache = {}
        self._continuous_tree_render_fingerprint = None

    def _hatch_state_version_value(self) -> int:
        try:
            return int(self.__dict__.get("_hatch_state_version", 0) or 0)
        except Exception:
            return 0

    def _bump_hatch_state_version(self, reason: str = "") -> int:
        _ = reason
        version = self._hatch_state_version_value() + 1
        self._hatch_state_version = version
        return version

    def _invalidate_continuous_conflict_caches(self, reason: str = "") -> None:
        self._continuous_load_conflict_reason_cache = {}
        self._continuous_target_load_conflict_reason_cache = {}
        self._matching_target_cell_geometry_cache = {}
        self._bump_hatch_state_version(reason)

    def _layout_metadata_cache_token(self) -> tuple[object, ...]:
        layouts = self.__dict__.get("generated_dxf_layout_metadata")
        layout_tuple = tuple(layouts or ())
        return (
            id(layouts),
            len(layout_tuple),
            tuple(str(getattr(layout, "story_name", "") or "") for layout in layout_tuple),
        )

    def _continuous_geometry_context_token(self) -> tuple[object, ...]:
        loaded_regions = self.__dict__.get("loaded_regions", ()) or ()
        edit_states = self.__dict__.get("hatch_edit_states_by_story", {}) or {}
        edit_counts = tuple(
            sorted(
                (
                    str(story_name),
                    len(getattr(state, "cells_by_id", {}) or {}),
                    len(getattr(state, "regions_by_key", {}) or {}),
                )
                for story_name, state in edit_states.items()
            )
        )
        return (
            id(loaded_regions),
            len(loaded_regions),
            id(edit_states),
            edit_counts,
            self._layout_metadata_cache_token(),
        )

    def _polygon_xy_fingerprint(self, points) -> tuple[tuple[float, float], ...]:
        result: list[tuple[float, float]] = []
        for point in tuple(points or ()):
            try:
                x, y = point
                result.append((round(float(x), 9), round(float(y), 9)))
            except Exception:
                continue
        return tuple(result)

    def _continuous_region_geometry_fingerprint(self, region_key: str) -> tuple[object, ...]:
        key = str(region_key or "")
        edit_region = self._editable_hatch_region_by_key(key)
        if edit_region is not None:
            return (
                "edit",
                str(getattr(edit_region, "story_name", "") or ""),
                self._polygon_xy_fingerprint(getattr(edit_region, "polygon_xy", ()) or ()),
            )
        dxf_region = self._dxf_region_by_key(key)
        hatch = getattr(dxf_region, "region", dxf_region)
        if dxf_region is not None:
            vertices = tuple(getattr(hatch, "vertices", ()) or ())
            if not vertices:
                polygon = getattr(dxf_region, "polygon", None) or getattr(hatch, "polygon", None)
                vertices = self._polygon_exterior_xy(polygon)
            return (
                "dxf",
                str(getattr(hatch, "story_name", "") or ""),
                self._polygon_xy_fingerprint(vertices),
            )
        return ("missing", key)

    def _continuous_below_allowed_reason_cache_key(self, region_key: str, target_story: str, polygon_xy=None) -> tuple[object, ...]:
        if polygon_xy is None:
            target_fingerprint: tuple[object, ...] = ("none",)
        else:
            target_points = tuple(polygon_xy or ())
            target_fingerprint = ("empty",) if not target_points else ("polygon", self._polygon_xy_fingerprint(target_points))
        return (
            str(region_key or ""),
            str(target_story or ""),
            self._continuous_region_geometry_fingerprint(str(region_key or "")),
            target_fingerprint,
            self._story_below_allowed_polygon_cache_token(),
            self._layout_metadata_cache_token(),
        )

    def _payload_fingerprint(self, payload: dict | None) -> tuple[object, ...]:
        if payload is None:
            return ("none",)
        result = []
        for key in ("load_name", "load_layer", "dl", "ll", "distribution", "one_way_angle"):
            value = payload.get(key)
            if key in {"load_name", "load_layer", "distribution"}:
                result.append((key, str(value or "")))
                continue
            try:
                result.append((key, round(float(value or 0.0), 9)))
            except Exception:
                result.append((key, str(value or "")))
        return tuple(result)

    def _continuous_load_conflict_reason_cache_key(self, region_keys, target_story: str) -> tuple[object, ...]:
        keys = tuple(str(key or "") for key in tuple(region_keys or ()) if str(key or ""))
        return (
            keys,
            str(target_story or ""),
            self._hatch_state_version_value(),
        )

    def _continuous_target_load_conflict_reason_cache_key(self, base_region_key: str, target_story: str, payload: dict | None) -> tuple[object, ...]:
        return (
            str(base_region_key or ""),
            str(target_story or ""),
            self._payload_fingerprint(payload),
            self._hatch_state_version_value(),
        )

    def _matching_target_cell_geometry_cache_key(self, source_region, target_state) -> tuple[object, ...]:
        cell_geometry = tuple(
            sorted(
                (
                    str(cell_id),
                    self._polygon_xy_fingerprint(getattr(cell, "polygon_xy", ()) or ()),
                )
                for cell_id, cell in (getattr(target_state, "cells_by_id", {}) or {}).items()
            )
        )
        return (
            str(getattr(source_region, "region_key", "") or ""),
            self._polygon_xy_fingerprint(getattr(source_region, "polygon_xy", ()) or ()),
            str(getattr(target_state, "story_name", "") or ""),
            id(target_state),
            cell_geometry,
            self._hatch_state_version_value(),
        )

    def _visible_targets_cache_key(self, region_key: str, check: dict[str, object]) -> tuple[object, ...]:
        candidate_signature = tuple(
            (
                str(getattr(candidate, "target_story_name", "") or ""),
                bool(_continuous_candidate_can_apply(candidate)),
                str(getattr(candidate, "reason", "") or ""),
            )
            for candidate in tuple(check.get("candidates", ()) or ())
        )
        target_fields = tuple(
            tuple(str(name or "") for name in tuple(check.get(field, ()) or ()) if str(name or ""))
            for field in ("base_centered_targets", "recommended_targets", "applicable_targets")
        )
        return (
            str(region_key or ""),
            id(check),
            str(check.get("base_story") or ""),
            candidate_signature,
            target_fields,
            self._story_below_allowed_polygon_cache_token(),
            self._continuous_geometry_context_token(),
        )

    def _selected_hatch_region_keys_for_continuous_info(self) -> tuple[str, ...]:
        keys: list[str] = []
        for key in tuple(self.__dict__.get("hatch_view_selected_region_keys") or ()):
            text = str(key or "")
            if text and text not in keys:
                keys.append(text)
        selected_key = str(self.__dict__.get("hatch_view_selected_region_key") or "")
        if selected_key and selected_key not in keys:
            keys.append(selected_key)
        for key in sorted(set(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set())):
            text = str(key or "")
            if text and text not in keys:
                keys.append(text)
        return tuple(keys)

    def _continuous_check_for_region_key(self, region_key: str) -> dict[str, object] | None:
        key = str(region_key or "")
        if not key:
            return None
        checks = self.__dict__.get("continuous_hatch_checks", {}) or {}
        check = checks.get(key)
        if check is not None:
            return check
        if key in (self.__dict__.get("hatch_view_region_by_key", {}) or {}):
            try:
                self._recompute_hatch_continuous_checks()
            except Exception:
                return None
            return (self.__dict__.get("continuous_hatch_checks", {}) or {}).get(key)
        editable_check = self._continuous_check_for_editable_region_key(key)
        if editable_check is not None:
            return editable_check
        if self.__dict__.get("loaded_regions"):
            try:
                self._recompute_hatch_continuous_checks()
            except Exception:
                return None
        return (self.__dict__.get("continuous_hatch_checks", {}) or {}).get(key)

    def _continuous_check_for_editable_region_key(self, region_key: str) -> dict[str, object] | None:
        key = str(region_key or "")
        if not key:
            return None
        region = self._editable_hatch_region_by_key(key)
        if region is None:
            return None
        if "continuous_hatch_checks" not in self.__dict__:
            self.continuous_hatch_checks = {}
        base_story = str(getattr(region, "story_name", "") or "")
        if not self.__dict__.get("story_shape_profiles"):
            try:
                self._ensure_typical_floor_analysis(reason="INTERNAL 폐합영역 연속층 가능 여부 계산")
            except Exception:
                pass
        if not self.__dict__.get("story_shape_profiles"):
            check = {
                "region_key": key,
                "region": region,
                "base_story": base_story,
                "can_select": False,
                "needs_analysis": True,
                "reason": "기준층 분석 필요",
                "candidates": (),
                "applicable_targets": (),
                "recommended_targets": (),
                "ranges": (),
                "blocked_targets": (),
            }
            self.continuous_hatch_checks[key] = check
            return check
        if not base_story:
            check = {
                "region_key": key,
                "region": region,
                "base_story": "",
                "can_select": False,
                "reason": "Story 인식 필요",
                "candidates": (),
                "applicable_targets": (),
                "recommended_targets": (),
                "ranges": (),
                "blocked_targets": (),
            }
            self.continuous_hatch_checks[key] = check
            return check
        ordered_story_names = [str(getattr(profile, "story_name", "") or "") for profile in tuple(self.__dict__.get("story_shape_profiles", ()) or ())]
        ordered_story_names = [name for name in ordered_story_names if name]
        polygon_xy = tuple((float(x), float(y)) for x, y in tuple(getattr(region, "polygon_xy", ()) or ()))
        try:
            xy_tolerance = float(self.snap_tol_var.get())
        except Exception:
            xy_tolerance = float(getattr(self.__dict__.get("config_data"), "snap_tolerance", 0.01))
        candidates = evaluate_continuous_apply_candidates(
            self.__dict__.get("story_shape_profiles", ()),
            base_story_name=base_story,
            target_story_names=ordered_story_names,
            hatch_polygon_xy=polygon_xy,
            typical_groups=self.__dict__.get("typical_floor_groups", ()) or (),
            xy_tolerance=xy_tolerance,
            min_source_coverage=self._continuous_projection_policy()[0],
            max_target_overreach_ratio=self._continuous_projection_policy()[1],
        )
        story_order_without_base = [name for name in ordered_story_names if name != base_story]
        ranges = split_continuous_apply_ranges(candidates, story_order_without_base)
        raw_applicable = tuple(candidate.target_story_name for candidate in candidates if candidate.can_apply)
        base_centered = self._base_centered_applicable_story_names(
            base_story=base_story,
            candidates=candidates,
            story_order=ordered_story_names,
        )
        blocked = tuple(
            (candidate.target_story_name, candidate.reason)
            for candidate in candidates
            if not candidate.can_apply
        )
        check = {
            "region_key": key,
            "region": region,
            "base_story": base_story,
            "can_select": bool(base_centered),
            "reason": "OK" if base_centered else "적용 가능한 연속층 없음",
            "candidates": candidates,
            "applicable_targets": tuple(base_centered),
            "all_applicable_targets": raw_applicable,
            "recommended_targets": tuple(base_centered),
            "base_centered_targets": tuple(base_centered),
            "ranges": ranges,
            "blocked_targets": blocked,
        }
        self.continuous_hatch_checks[key] = check
        return check

    def _editable_hatch_region_by_key(self, region_key: str):
        key = str(region_key or "")
        region_by_key = self.__dict__.get("hatch_view_edit_region_by_key", {}) or {}
        region = region_by_key.get(key)
        if region is not None:
            return region
        for state in (self.__dict__.get("hatch_edit_states_by_story", {}) or {}).values():
            region = getattr(state, "regions_by_key", {}).get(key)
            if region is not None:
                return region
        return None

    def _visible_applicable_targets_for_region_key(self, region_key: str) -> tuple[str, ...]:
        key = str(region_key or "")
        check = self._continuous_check_for_region_key(key) or {}
        try:
            cache_key = self._visible_targets_cache_key(key, check)
            cache = self.__dict__.setdefault("_visible_targets_cache", {})
            if cache_key in cache:
                return tuple(cache[cache_key])
        except Exception:
            cache_key = None
            cache = None
        for field in ("base_centered_targets", "recommended_targets", "applicable_targets"):
            values = tuple(str(name or "") for name in tuple(check.get(field, ()) or ()) if str(name or ""))
            if values:
                result = self._continuous_below_allowed_visible_targets(key, values)
                if cache_key is not None and isinstance(cache, dict):
                    cache[cache_key] = result
                return result
        if cache_key is not None and isinstance(cache, dict):
            cache[cache_key] = ()
        return ()

    def _continuous_below_allowed_visible_targets(self, region_key: str, targets) -> tuple[str, ...]:
        key = str(region_key or "")
        blocked: dict[str, str] = {}
        visible: list[str] = []
        for target in tuple(targets or ()):
            target_story = str(target or "")
            if not target_story:
                continue
            reason = self._continuous_target_below_allowed_reason(key, target_story)
            if reason:
                blocked[target_story] = reason
            else:
                visible.append(target_story)
        blocked_map = self.__dict__.setdefault("continuous_below_blocked_targets_by_region", {})
        blocked_map[key] = blocked
        return tuple(visible)

    def _continuous_target_visibility_reason(self, region_key: str, target_story: str) -> str:
        key = str(region_key or "")
        target = str(target_story or "")
        blocked_map = self.__dict__.get("continuous_below_blocked_targets_by_region", {}) or {}
        reason = (blocked_map.get(key, {}) or {}).get(target, "")
        if reason:
            return reason
        return self._continuous_target_below_allowed_reason(key, target)

    def _continuous_target_below_allowed_reason(self, region_key: str, target_story: str) -> str:
        key = str(region_key or "")
        target = str(target_story or "")
        if not key or not target:
            return ""
        if not (self.__dict__.get("stories") and self.__dict__.get("nodes") and self.__dict__.get("elements")):
            return ""
        polygon_xy = self._continuous_target_polygon_xy_for_below_check(key, target)
        try:
            cache_key = self._continuous_below_allowed_reason_cache_key(key, target, polygon_xy)
            cache = self.__dict__.setdefault("_continuous_below_allowed_reason_cache", {})
            if cache_key in cache:
                self._continuous_below_allowed_reason_cache_hits = int(self.__dict__.get("_continuous_below_allowed_reason_cache_hits", 0) or 0) + 1
                return str(cache[cache_key] or "")
            self._continuous_below_allowed_reason_cache_misses = int(self.__dict__.get("_continuous_below_allowed_reason_cache_misses", 0) or 0) + 1
        except Exception:
            cache_key = None
            cache = None
        if polygon_xy is None:
            reason = ""
            if cache_key is not None and isinstance(cache, dict):
                cache[cache_key] = reason
            return reason
        if not polygon_xy:
            reason = "해당 층의 target 폐합영역을 찾지 못해 연속층 적용 대상에서 제외됩니다."
            if cache_key is not None and isinstance(cache, dict):
                cache[cache_key] = reason
            return reason
        polygon = self._polygon_from_xy(polygon_xy)
        if polygon is None:
            reason = "해당 층의 target 폐합영역을 찾지 못해 연속층 적용 대상에서 제외됩니다."
            if cache_key is not None and isinstance(cache, dict):
                cache[cache_key] = reason
            return reason
        try:
            allowed_map = self._story_below_allowed_polygons_by_name((target,))
            snap_var = self.__dict__.get("snap_tol_var")
            config = self.__dict__.get("config_data")
            snap_tolerance = float(snap_var.get()) if snap_var is not None else float(getattr(config, "snap_tolerance", 0.5))
            check = check_polygon_against_allowed_story_polygons(
                polygon,
                target,
                allowed_map,
                snap_tolerance=snap_tolerance,
            )
        except Exception:
            reason = ""
            if cache_key is not None and isinstance(cache, dict):
                cache[cache_key] = reason
            return reason
        if check.status:
            reason = "해당 층의 BELOW 하중입력 가능 영역과 일치하지 않아 연속층 적용 대상에서 제외됩니다."
        else:
            reason = ""
        if cache_key is not None and isinstance(cache, dict):
            cache[cache_key] = reason
        return reason

    def _continuous_target_polygon_xy_for_below_check(self, region_key: str, target_story: str):
        key = str(region_key or "")
        target = str(target_story or "")
        source_edit_region = self._editable_hatch_region_by_key(key)
        if source_edit_region is not None:
            states = self.__dict__.get("hatch_edit_states_by_story", {}) or {}
            if target not in states:
                try:
                    self._ensure_hatch_edit_states(target)
                except Exception:
                    return None
                states = self.__dict__.get("hatch_edit_states_by_story", {}) or {}
            target_state = states.get(target)
            if target_state is None:
                return None
            if not (getattr(target_state, "cells_by_id", {}) or {}):
                return None
            match = self._matching_target_cell_projection_for_region(source_edit_region, target_state)
            return tuple(match.polygon_xy) if match.ok else ()
        source_dxf_region = self._dxf_region_by_key(key)
        if source_dxf_region is not None:
            states = self.__dict__.get("hatch_edit_states_by_story", {}) or {}
            if target not in states:
                try:
                    self._ensure_hatch_edit_states(target)
                except Exception:
                    pass
                states = self.__dict__.get("hatch_edit_states_by_story", {}) or {}
            target_state = states.get(target)
            if target_state is not None and (getattr(target_state, "cells_by_id", {}) or {}):
                source_projection = self._editable_region_from_dxf_region(source_dxf_region, base_region_key=key)
                match = self._matching_target_cell_projection_for_region(source_projection, target_state)
                return tuple(match.polygon_xy) if match.ok else ()
            dxf_match = self._matching_target_dxf_projection_for_region_key(key, target)
            if dxf_match.ok:
                return tuple(dxf_match.polygon_xy)
            return None if dxf_match.status == "TARGET_GEOMETRY_UNAVAILABLE" else ()
        return ()

    def _set_continuous_active_visible_targets(self, targets) -> tuple[str, ...]:
        normalized = tuple(str(name or "") for name in tuple(targets or ()) if str(name or ""))
        self.continuous_active_visible_targets = normalized
        return normalized

    def _get_continuous_active_visible_targets(self) -> tuple[str, ...]:
        return tuple(
            str(name or "")
            for name in tuple(self.__dict__.get("continuous_active_visible_targets", ()) or ())
            if str(name or "")
        )

    def _targets_follow_active_visible_range(self, targets, visible_targets) -> bool:
        visible = tuple(str(name or "") for name in tuple(visible_targets or ()) if str(name or ""))
        selected = {str(name or "") for name in tuple(targets or ()) if str(name or "")}
        if not visible or not selected:
            return False
        positions = [index for index, name in enumerate(visible) if name in selected]
        if len(positions) != len(selected):
            return False
        return positions == list(range(min(positions), max(positions) + 1))

    def _visible_common_targets_for_region_keys(self, region_keys) -> tuple[str, ...]:
        keys = tuple(str(key or "") for key in tuple(region_keys or ()) if str(key or ""))
        target_sets = [set(self._visible_applicable_targets_for_region_key(key)) for key in keys]
        if not target_sets:
            return ()
        common = set.intersection(*target_sets)
        order = self._story_order_names()
        ordered = [name for name in order if name in common]
        ordered.extend(sorted(name for name in common if name not in set(ordered)))
        return tuple(ordered)

    def _common_applicable_story_names_for_selected_regions(self, region_keys=None) -> tuple[str, ...]:
        keys = tuple(region_keys or self._selected_hatch_region_keys_for_continuous_info())
        return self._visible_common_targets_for_region_keys(keys)

    def _continuous_story_runs(self, story_names) -> list[tuple[str, ...]]:
        names = {str(name or "") for name in tuple(story_names or ()) if str(name or "")}
        if not names:
            return []
        order = self._story_order_names()
        ordered = [name for name in order if name in names]
        ordered.extend(sorted(name for name in names if name not in set(ordered)))
        if not ordered:
            return []
        index_by_name = {name: index for index, name in enumerate(order)}
        runs: list[list[str]] = []
        current: list[str] = []
        previous_index: int | None = None
        for name in ordered:
            index = index_by_name.get(name)
            if index is None:
                if current:
                    runs.append(current)
                runs.append([name])
                current = []
                previous_index = None
                continue
            if current and previous_index is not None and index == previous_index + 1:
                current.append(name)
            else:
                if current:
                    runs.append(current)
                current = [name]
            previous_index = index
        if current:
            runs.append(current)
        return [tuple(run) for run in runs]

    def _common_continuous_story_range_for_selected_regions(self, region_keys=None) -> tuple[str, ...]:
        return self._common_applicable_story_names_for_selected_regions(region_keys)

    def _format_story_range_text(self, story_names) -> str:
        names = tuple(str(name or "") for name in tuple(story_names or ()) if str(name or ""))
        if not names:
            return "없음"
        runs = self._continuous_story_runs(names)
        if len(runs) == 1 and set(runs[0]) == set(names):
            run = runs[0]
            return run[0] if len(run) == 1 else f"{run[0]} ~ {run[-1]}"
        return ", ".join(names)

    def _selected_edit_region_story_names(self, region_keys) -> tuple[str, ...]:
        region_by_key = self.__dict__.get("hatch_view_edit_region_by_key", {}) or {}
        names: list[str] = []
        for key in tuple(region_keys or ()):
            region = region_by_key.get(str(key))
            name = str(getattr(region, "story_name", "") or "")
            if name and name not in names:
                names.append(name)
        return tuple(names)

    def _refresh_selected_hatch_continuous_info(self) -> None:
        self._cancel_scheduled_hatch_continuous_refresh()
        keys = self._selected_hatch_region_keys_for_continuous_info()
        if not keys:
            self._sync_continuous_base_story_from_selection()
            return
        self._sync_continuous_base_story_from_selection()
        dxf_keys = [key for key in keys if key in (self.__dict__.get("hatch_view_region_by_key", {}) or {})]
        if dxf_keys:
            missing = [key for key in dxf_keys if key not in (self.__dict__.get("continuous_hatch_checks", {}) or {})]
            if missing:
                try:
                    self._recompute_hatch_continuous_checks()
                except Exception:
                    pass
        status_var = self.__dict__.get("continuous_apply_status_var")
        if status_var is None:
            return
        try:
            if len(keys) > 1:
                common_targets = self._visible_common_targets_for_region_keys(keys)
                self._set_continuous_active_visible_targets(common_targets)
                self._prune_saved_continuous_targets_to_common(keys, common_targets)
                self._refresh_common_continuous_candidate_tree(keys, common_targets)
                story_names = self._selected_hatch_story_names()
                prefix = "여러 Story 선택: " if len(story_names) > 1 else ""
                if common_targets:
                    self._set_continuous_status(f"{prefix}선택 영역 {len(keys)}개 공통 연속층 적용 가능: {self._format_story_range_text(common_targets)}")
                else:
                    self._set_continuous_status(f"{prefix}선택 영역 {len(keys)}개 공통 적용 가능층 없음")
                return
            key = keys[0]
            self.continuous_active_region_keys = ()
            check = self._continuous_check_for_region_key(key)
            if not check:
                self._set_continuous_active_visible_targets(())
                story_names = self._selected_edit_region_story_names(keys)
                if story_names:
                    self._set_continuous_status(f"선택 폐합영역 Story {', '.join(story_names)}: DXF 해치 연속층 정보 없음")
                return
            visible_targets = self._visible_applicable_targets_for_region_key(key)
            self._set_continuous_active_visible_targets(visible_targets)
            self._refresh_continuous_candidate_tree(
                str(check.get("base_story") or ""),
                tuple(check.get("candidates", ()) or ()),
                region_key=key,
                visible_targets=visible_targets,
            )
            target_map = dict(self.__dict__.get("continuous_apply_targets_by_region", {}) or {})
            saved_targets = tuple(target_map.get(key, ()) or ())
            base_story = str(check.get("base_story") or "")
            if saved_targets:
                self._set_continuous_status(f"자동 저장됨: {base_story or '-'} -> {', '.join(saved_targets)}")
            elif check.get("can_select"):
                self._set_continuous_status(f"{base_story or '-'} 기준 연속층 적용 가능: {self._format_story_range_text(visible_targets)}")
            else:
                self._set_continuous_status(self._continuous_reason_user_text(SimpleNamespace(can_apply=False, reason=str(check.get("reason") or ""))))
        except Exception:
            return

    def _cancel_scheduled_hatch_continuous_refresh(self) -> None:
        after_id = self.__dict__.get("_hatch_continuous_refresh_after_id")
        self._hatch_continuous_refresh_after_id = None
        if after_id is None:
            return
        canvas = self.__dict__.get("hatch_preview_canvas")
        after_cancel = getattr(canvas, "after_cancel", None) if canvas is not None else None
        if callable(after_cancel):
            try:
                after_cancel(after_id)
            except Exception:
                pass

    def _schedule_selected_hatch_continuous_refresh(self, delay_ms: int = 180) -> None:
        self._cancel_scheduled_hatch_continuous_refresh()
        canvas = self.__dict__.get("hatch_preview_canvas")
        after = getattr(canvas, "after", None) if canvas is not None else None
        if not callable(after):
            self._refresh_selected_hatch_continuous_info()
            return

        def refresh_scheduled() -> None:
            self._hatch_continuous_refresh_after_id = None
            self._refresh_selected_hatch_continuous_info()

        try:
            self._hatch_continuous_refresh_after_id = after(max(int(delay_ms), 0), refresh_scheduled)
        except Exception:
            self._hatch_continuous_refresh_after_id = None
            self._refresh_selected_hatch_continuous_info()

    def _prune_saved_continuous_targets_to_common(self, region_keys, common_targets) -> None:
        target_map = self.__dict__.get("continuous_apply_targets_by_region")
        if not isinstance(target_map, dict):
            return
        common = {str(name or "") for name in tuple(common_targets or ()) if str(name or "")}
        for key in tuple(region_keys or ()):
            text_key = str(key or "")
            if text_key not in target_map:
                continue
            saved = tuple(str(name or "") for name in tuple(target_map.get(text_key, ()) or ()) if str(name or ""))
            pruned = tuple(name for name in saved if name in common)
            if pruned:
                target_map[text_key] = pruned
            else:
                target_map[text_key] = ()

    def _refresh_common_continuous_candidate_tree(self, region_keys, common_targets) -> None:
        tree = self.__dict__.get("continuous_tree")
        if tree is None:
            return
        keys = tuple(str(key or "") for key in tuple(region_keys or ()) if str(key or ""))
        self.continuous_active_region_keys = keys
        if not keys:
            return
        checks = [self._continuous_check_for_region_key(key) for key in keys]
        checks = [check for check in checks if check]
        if not checks:
            return
        base_check = checks[0]
        base_story = str(base_check.get("base_story") or "")
        common = {str(name or "") for name in tuple(common_targets or ()) if str(name or "")}
        limited_candidates = []
        for candidate in tuple(base_check.get("candidates", ()) or ()):
            target = str(getattr(candidate, "target_story_name", "") or "")
            can_apply = _continuous_candidate_can_apply(candidate) and target in common
            reason = str(getattr(candidate, "reason", "") or "")
            if not can_apply and target not in common:
                reason = "공통 적용 가능층 아님"
            limited_candidates.append(self._copy_continuous_candidate(candidate, can_apply=can_apply, reason=reason))
        self._refresh_continuous_candidate_tree(
            base_story,
            tuple(limited_candidates),
            region_key=keys[0],
            visible_targets=tuple(common_targets or ()),
        )
        self.continuous_active_region_keys = keys

    def _copy_continuous_candidate(self, candidate, *, can_apply: bool, reason: str):
        try:
            return replace(candidate, can_apply=can_apply, reason=reason)
        except Exception:
            return SimpleNamespace(
                base_story_name=getattr(candidate, "base_story_name", ""),
                target_story_name=getattr(candidate, "target_story_name", ""),
                can_apply=can_apply,
                similarity_score=float(getattr(candidate, "similarity_score", 0.0) or 0.0),
                boundary_node_match_ratio=float(getattr(candidate, "boundary_node_match_ratio", 0.0) or 0.0),
                iou=float(getattr(candidate, "iou", 0.0) or 0.0),
                reason=reason,
            )

    def _refresh_continuous_base_story_values(self) -> None:
        story_names = [story.name for story in self.__dict__.get("stories", [])]
        synced = self._sync_continuous_base_story_from_selection()
        if synced:
            return
        selected_region = self._selected_dxf_load_region()
        preferred = str(getattr(getattr(selected_region, "region", None), "story_name", "") or "")
        if preferred and preferred in story_names:
            self.continuous_base_story_name.set(preferred)
            if "selected_hatch_story_var" in self.__dict__:
                self.selected_hatch_story_var.set(f"기준 STORY: {preferred}")
        elif story_names and self.continuous_base_story_name.get() not in story_names:
            self.continuous_base_story_name.set(story_names[0])

    def _refresh_hatch_view_story_controls(self) -> None:
        combo = self.__dict__.get("hatch_view_story_combo")
        story_names = list(self._hatch_view_available_story_names())
        if combo is not None:
            combo.configure(values=story_names)
        selected_var = self.__dict__.get("hatch_view_selected_story_var")
        if selected_var is not None:
            try:
                current = str(selected_var.get() or "")
                if story_names and current not in story_names:
                    selected_var.set(story_names[0])
            except Exception:
                pass

    def _hatch_view_available_story_names(self) -> tuple[str, ...]:
        names: list[str] = []

        def add(value) -> None:
            name = str(value or "")
            if name and name not in names:
                names.append(name)

        for name in tuple(self.__dict__.get("generated_dxf_story_names") or ()):
            add(name)
        for layout in tuple(self.__dict__.get("generated_dxf_layout_metadata") or ()):
            add(getattr(layout, "story_name", ""))
        for name in self._loaded_region_story_names():
            add(name)
        for story in tuple(self.__dict__.get("stories", []) or ()):
            add(getattr(story, "name", ""))
        return tuple(names)

    def _on_hatch_view_display_mode_changed(self) -> None:
        if self.__dict__.get("generated_dxf_mode") == "SINGLE_STORY":
            self.hatch_view_display_mode_var.set("STORY")
        self._reset_hatch_view_zoom()
        self._render_hatch_preview()
        self._refresh_selected_hatch_continuous_info()

    def _on_hatch_view_story_changed(self, _event=None) -> None:
        display_mode_var = self.__dict__.get("hatch_view_display_mode_var")
        if display_mode_var is not None:
            try:
                display_mode_var.set("STORY")
            except Exception:
                pass
        self._reset_hatch_view_zoom()
        self._clear_dummy_issue_selection(update_overlay=False)
        self._ensure_hatch_edit_states(self._hatch_view_story_filter())
        self._render_hatch_preview()
        self._refresh_selected_hatch_continuous_info()

    def _hatch_view_display_mode(self) -> str:
        mode_var = self.__dict__.get("hatch_view_display_mode_var")
        mode = str(mode_var.get() if mode_var is not None else "ALL")
        if self.__dict__.get("generated_dxf_mode") == "SINGLE_STORY":
            return "STORY"
        return "STORY" if mode == "STORY" else "ALL"

    def _hatch_view_is_all_story_display(self) -> bool:
        return self._hatch_view_display_mode() == "ALL" and self._hatch_view_has_all_story_context()

    def _loaded_region_story_names(self, regions=None) -> tuple[str, ...]:
        result: list[str] = []
        source = self.__dict__.get("loaded_regions", ()) if regions is None else (regions or ())
        for region in tuple(source):
            name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
            if name and name not in result:
                result.append(name)
        return tuple(result)

    def _loaded_regions_have_placed_coordinates(self, regions=None) -> bool:
        source = self.__dict__.get("loaded_regions", ()) if regions is None else (regions or ())
        for region in tuple(source):
            hatch = getattr(region, "region", None)
            if getattr(hatch, "placed_vertices", ()) or getattr(hatch, "placed_bbox", ()):
                return True
            if bool(getattr(hatch, "layout_metadata_used", False)) and bool(getattr(hatch, "transform_applied", False)):
                return True
        return False

    def _hatch_view_has_all_story_context(self) -> bool:
        if self.__dict__.get("generated_dxf_mode") == "ALL_STORIES":
            return True
        layouts = tuple(self.__dict__.get("generated_dxf_layout_metadata") or ())
        if len(layouts) > 1:
            return True
        region_story_names = self._loaded_region_story_names()
        return len(region_story_names) > 1 and self._loaded_regions_have_placed_coordinates()

    def _hatch_view_story_filter(self) -> str:
        if self._hatch_view_display_mode() != "STORY":
            return ""
        selected_var = self.__dict__.get("hatch_view_selected_story_var")
        try:
            return str(selected_var.get() or "") if selected_var is not None else ""
        except Exception:
            return ""

    def _layout_by_story(self) -> dict[str, object]:
        return {
            str(getattr(layout, "story_name", "") or ""): layout
            for layout in tuple(self.__dict__.get("generated_dxf_layout_metadata") or ())
            if str(getattr(layout, "story_name", "") or "")
        }

    def _ensure_hatch_edit_states(self, story_name: str | None = None) -> None:
        if "hatch_edit_states_by_story" not in self.__dict__:
            self.hatch_edit_states_by_story = {}
        if not getattr(self, "stories", None) or not getattr(self, "nodes", None) or not getattr(self, "elements", None):
            return
        generated_story_names = tuple(self.__dict__.get("generated_dxf_story_names") or ())
        story_names = [story_name] if story_name else list(generated_story_names or tuple(story.name for story in self.stories))
        story_names = [name for name in story_names if name]
        if not story_names:
            story_names = [story.name for story in self.stories]
        config = self.__dict__.get("config_data")
        story_tol = float(self.story_tol_var.get()) if hasattr(self, "story_tol_var") else float(getattr(config, "story_tolerance", 1.0e-4))
        geometry_tol = self._closed_region_geometry_tolerance()
        geometry_tokens = self.__dict__.setdefault("_hatch_edit_state_geometry_token_by_story", {})
        for name in story_names:
            geometry_token = self._hatch_edit_state_geometry_token(str(name))
            existing_state = self.hatch_edit_states_by_story.get(name)
            if existing_state is not None and name not in geometry_tokens:
                geometry_tokens[name] = geometry_token
                continue
            if existing_state is not None and geometry_tokens.get(name) == geometry_token:
                continue
            if existing_state is not None:
                stale_keys = set((getattr(existing_state, "regions_by_key", {}) or {}).keys())
                selected_keys = set(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set())
                self.hatch_view_selected_edit_region_keys = selected_keys.difference(stale_keys)
                self.hatch_edit_states_by_story.pop(name, None)
                geometry_tokens.pop(name, None)
            story_elements = self._story_below_elements_for_story(str(name))
            diagnostics: list[dict] = []
            perf_token = self._hatch_perf_start("detect_closed_cells")
            cells = detect_closed_cells(
                stories=self.stories,
                nodes=self.nodes,
                elements=story_elements or self.elements,
                story_name=name,
                story_tolerance=story_tol,
                xy_tolerance=geometry_tol,
                mgt_text=getattr(self, "current_mgt_text", "") or None,
                elements_by_story_name={str(name): story_elements} if story_elements else None,
                diagnostics=diagnostics,
                extra_boundary_segments_by_story=self._approved_dummy_segments_by_story(),
            )
            self._hatch_perf_end(
                perf_token,
                story_name=str(name),
                display_mode=self._hatch_view_display_mode(),
                visible_region_count=0,
                structure_item_count=0,
                candidate_target_count=0,
                cache_hit=int(self.__dict__.get("_story_below_element_index_cache_hits", 0) or 0),
                cache_miss=int(self.__dict__.get("_story_below_element_index_cache_misses", 0) or 0),
                input_element_count=len(tuple(story_elements or self.elements or ())),
                cell_count=len(cells),
            )
            self._write_hatch_closed_region_diagnostics(diagnostics)
            self.hatch_edit_states_by_story[name] = create_edit_state(name, cells)
            geometry_tokens[name] = geometry_token
            self._invalidate_continuous_below_allowed_reason_cache("HATCH VIEW editable state 생성")

    def _hatch_view_active_edit_states(self) -> list[HatchEditState]:
        story_filter = self._hatch_view_story_filter()
        self._ensure_hatch_edit_states(story_filter or None)
        states_by_story = self.__dict__.setdefault("hatch_edit_states_by_story", {})
        if story_filter:
            state = states_by_story.get(story_filter)
            return [state] if state is not None else []
        story_names = self._hatch_view_available_story_names()
        return [states_by_story[name] for name in story_names if name in states_by_story]

    def _loaded_internal_hatch_regions(self):
        return loaded_editable_regions(self.__dict__.get("hatch_edit_states_by_story", {}).values())

    def _write_hatch_view_input_state_snapshot(self, reports_dir: str | Path, *, dxf_regions, internal_regions, model_name: str, source_dxf_path: str, layout_metadata_path: str):
        try:
            dxf_region_key_map = {
                id(region): str(key)
                for key, region in (self.__dict__.get("hatch_view_region_by_key", {}) or {}).items()
            }
            display_mode = self._hatch_view_display_mode() if hasattr(self, "_hatch_view_display_mode") else ""
            selected_story = ""
            selected_var = self.__dict__.get("hatch_view_selected_story_var")
            if selected_var is not None:
                try:
                    selected_story = str(selected_var.get() or "")
                except Exception:
                    selected_story = ""
            json_path, csv_path = write_hatch_view_input_state(
                output_dir=reports_dir,
                model_name=model_name,
                source_dxf_path=source_dxf_path,
                layout_metadata_path=layout_metadata_path,
                display_mode=display_mode,
                selected_story=selected_story,
                dxf_regions=tuple(dxf_regions or ()),
                internal_regions=tuple(internal_regions or ()),
                selected_region_keys=set(self.__dict__.get("hatch_view_selected_region_keys", set()) or set()),
                selected_edit_region_keys=set(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set()),
                continuous_apply_targets_by_region=dict(self.__dict__.get("continuous_apply_targets_by_region", {}) or {}),
                continuous_materialized_targets_by_region=dict(self.__dict__.get("continuous_materialized_targets_by_region", {}) or {}),
                dxf_region_key_map=dxf_region_key_map,
            )
            queue_obj = self.__dict__.get("queue")
            if queue_obj is not None:
                queue_obj.put(("log", f"HATCH VIEW 입력상태 저장: {json_path}, {csv_path}"))
            return json_path, csv_path
        except Exception as exc:  # noqa: BLE001 - audit output must not block MGT generation
            logger = self.__dict__.get("logger")
            if logger is not None:
                logger.warning("HATCH VIEW input snapshot write failed: %s", exc)
            queue_obj = self.__dict__.get("queue")
            if queue_obj is not None:
                try:
                    queue_obj.put(("log", f"HATCH VIEW 입력상태 저장 실패(생성은 계속): {exc}"))
                except Exception:
                    pass
            return None, None

    def _hatch_closed_region_reports_dir(self) -> Path | None:
        subdirs = self.__dict__.get("current_project_subdirs") or {}
        reports_dir = subdirs.get("reports") if isinstance(subdirs, dict) else None
        if reports_dir:
            return Path(reports_dir)
        output_root = self.__dict__.get("output_root")
        if output_root is None:
            data_root = self.__dict__.get("data_root")
            if data_root is not None:
                try:
                    output_root = output_root_dir(Path(data_root))
                except Exception:
                    output_root = None
        if output_root is None:
            return None
        return Path(output_root) / "reports"

    def _write_hatch_closed_region_diagnostics(self, diagnostics) -> None:
        rows = tuple(dict(row) for row in tuple(diagnostics or ()) if isinstance(row, dict))
        self._last_hatch_closed_region_diagnostics = rows
        if not rows:
            return
        reports_dir = self._hatch_closed_region_reports_dir()
        if reports_dir is None:
            return
        try:
            json_path, csv_path = write_closed_region_diagnostics(rows, reports_dir)
            logger = self.__dict__.get("logger")
            if logger is not None:
                logger.debug("HATCH closed region diagnostics saved: %s, %s", json_path, csv_path)
        except Exception as exc:  # noqa: BLE001 - diagnostics must not block HATCH VIEW
            logger = self.__dict__.get("logger")
            if logger is not None:
                logger.warning("HATCH closed region diagnostics write failed: %s", exc)

    def _planned_region_story_names(self, regions, internal_regions) -> tuple[str, ...]:
        names: list[str] = []
        for region in tuple(regions or ()):
            name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
            if name and name not in names:
                names.append(name)
        for region in tuple(internal_regions or ()):
            name = str(getattr(region, "story_name", "") or "")
            if name and name not in names:
                names.append(name)
        return tuple(names)

    def _story_below_allowed_polygons_by_name(self, story_names: Sequence[str] | None = None) -> dict[str, tuple[object, ...]]:
        if not self.__dict__.get("stories") or not self.__dict__.get("nodes") or not self.__dict__.get("elements"):
            return {}
        requested = {str(name) for name in tuple(story_names or ()) if str(name or "")}
        perf_token = self._hatch_perf_start("_story_below_allowed_polygons_by_name")
        cache_hit = False
        try:
            token = self._story_below_allowed_polygon_cache_token()
        except Exception:
            token = None
        cached_token = self.__dict__.get("_story_below_allowed_polygon_cached_token")
        cached = self.__dict__.get("_story_below_allowed_polygon_cache")
        if token is not None and cached_token == token and isinstance(cached, dict):
            self._story_below_allowed_polygon_cache_hits = int(self.__dict__.get("_story_below_allowed_polygon_cache_hits", 0) or 0) + 1
            cache_hit = True
            result = cached
        else:
            self._story_below_allowed_polygon_cache_misses = int(self.__dict__.get("_story_below_allowed_polygon_cache_misses", 0) or 0) + 1
            try:
                story_tolerance = float(self.story_tol_var.get()) if hasattr(self, "story_tol_var") else self._model_story_tolerance()
            except Exception:
                story_tolerance = self._model_story_tolerance()
            geometry_tolerance = self._closed_region_geometry_tolerance()
            try:
                cells = self._closed_cells_from_complete_hatch_edit_states()
                if cells is None:
                    elements_by_story = self._story_below_elements_by_story_for_detector(None)
                    diagnostics: list[dict] = []
                    cells = detect_closed_cells(
                        stories=self.stories,
                        nodes=self.nodes,
                        elements=self.elements,
                        story_name=None,
                        story_tolerance=story_tolerance,
                        xy_tolerance=geometry_tolerance,
                        mgt_text=str(self.__dict__.get("current_mgt_text", "") or "") or None,
                        elements_by_story_name=elements_by_story or None,
                        diagnostics=diagnostics,
                    )
                    self._write_hatch_closed_region_diagnostics(diagnostics)
            except Exception as exc:  # noqa: BLE001 - downstream validation must report missing allowed regions
                logger = self.__dict__.get("logger")
                if logger is not None:
                    logger.warning("story BELOW allowed polygon detection failed: %s", exc)
                self._warn_story_below_allowed_region_missing(requested, detail=str(exc))
                result = {}
                if token is not None:
                    self._story_below_allowed_polygon_cached_token = token
                    self._story_below_allowed_polygon_cache = result
                self._hatch_perf_end(
                    perf_token,
                    story_name=",".join(sorted(requested)),
                    display_mode=self._hatch_view_display_mode(),
                    visible_region_count=0,
                    structure_item_count=0,
                    candidate_target_count=0,
                    cache_hit=cache_hit,
                    cache_miss=not cache_hit,
                    error=str(exc),
                )
                return {name: tuple() for name in sorted(requested)}
            from shapely.geometry import Polygon

            by_story: dict[str, list[object]] = {}
            for cell in cells:
                story_name = str(getattr(cell, "story_name", "") or "")
                points = tuple(getattr(cell, "polygon_xy", ()) or ())
                if len(points) < 3:
                    continue
                polygon = Polygon(points)
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)
                if polygon.is_empty or polygon.area <= 1.0e-12:
                    continue
                by_story.setdefault(story_name, []).append(polygon)
            result = {name: tuple(polygons) for name, polygons in by_story.items() if polygons}
            if token is not None:
                self._story_below_allowed_polygon_cached_token = token
                self._story_below_allowed_polygon_cache = result
        missing = requested.difference(result)
        if missing:
            self._warn_story_below_allowed_region_missing(missing)
        self._hatch_perf_end(
            perf_token,
            story_name=",".join(sorted(requested)),
            display_mode=self._hatch_view_display_mode(),
            visible_region_count=0,
            structure_item_count=0,
            candidate_target_count=0,
            cache_hit=cache_hit,
            cache_miss=not cache_hit,
            story_count=len(result),
            polygon_count=sum(len(tuple(polygons or ())) for polygons in result.values()),
        )
        if requested:
            return {name: tuple(result.get(name, ())) for name in sorted(requested)}
        return {name: tuple(polygons) for name, polygons in result.items() if polygons}

    def _closed_cells_from_complete_hatch_edit_states(self):
        story_names = tuple(
            str(getattr(story, "name", "") or "")
            for story in tuple(self.__dict__.get("stories", ()) or ())
            if str(getattr(story, "name", "") or "")
        )
        states = self.__dict__.get("hatch_edit_states_by_story", {}) or {}
        if not story_names or any(name not in states for name in story_names):
            return None
        geometry_tokens = self.__dict__.get("_hatch_edit_state_geometry_token_by_story", {}) or {}
        if any(geometry_tokens.get(name) != self._hatch_edit_state_geometry_token(name) for name in story_names):
            return None
        cells = []
        for story_name in story_names:
            state = states[story_name]
            cells.extend(tuple((getattr(state, "cells_by_id", {}) or {}).values()))
        return tuple(cells)

    def _warn_story_below_allowed_region_missing(self, story_names: Iterable[str], *, detail: str = "") -> None:
        names = tuple(str(name) for name in story_names if str(name or ""))
        if not names:
            return
        story_text = ", ".join(names)
        message = (
            f"{story_text} Story의 BELOW 기준 하중 허용영역을 확인하지 못했습니다. "
            "구조요소 표시/Story metadata를 확인하세요."
        )
        logger = self.__dict__.get("logger")
        if logger is not None:
            logger.warning("%s%s", message, f" ({detail})" if detail else "")
        queue_obj = self.__dict__.get("queue")
        if queue_obj is not None:
            try:
                queue_obj.put(("log", message))
                queue_obj.put(("dxf_status", message))
            except Exception:
                pass

    def _refresh_hatch_edit_region_index(self) -> None:
        self.hatch_view_edit_region_by_key = {}
        for state in (self.__dict__.get("hatch_edit_states_by_story", {}) or {}).values():
            for key, region in getattr(state, "regions_by_key", {}).items():
                self.hatch_view_edit_region_by_key[str(key)] = region
        self._invalidate_continuous_below_allowed_reason_cache("HATCH VIEW editable region index 갱신")

    def _load_payload_from_item(self, item: dict) -> dict:
        one_way_angle = item.get("one_way_angle")
        return {
            "load_name": str(item.get("display_name") or item.get("name") or "LOAD"),
            "load_layer": self._hatch_load_layer_for_item(item),
            "dl": float(item.get("dl", 0.0) or 0.0),
            "ll": float(item.get("ll", 0.0) or 0.0),
            "distribution": str(item.get("distribution") or "TWO_WAY"),
            "one_way_angle": None if one_way_angle in (None, "") else float(one_way_angle),
        }

    def _load_payload_from_region_key(self, region_key: str) -> dict | None:
        key = str(region_key or "")
        dxf_region = self._dxf_region_by_key(key)
        if dxf_region is not None and getattr(dxf_region, "load", None) is not None:
            load = dxf_region.load
            return {
                "load_name": str(getattr(load, "real_name", "") or getattr(load, "layer", "") or "LOAD"),
                "load_layer": str(getattr(load, "layer", "") or getattr(load, "real_name", "") or "LOAD"),
                "dl": float(getattr(load, "dl", 0.0) or 0.0),
                "ll": float(getattr(load, "ll", 0.0) or 0.0),
                "distribution": str(getattr(load, "distribution", "") or "TWO_WAY"),
                "one_way_angle": getattr(load, "one_way_angle_deg", None),
            }

        edit_region = self._editable_hatch_region_by_key(key)
        if edit_region is not None and str(getattr(edit_region, "load_name", "") or ""):
            return {
                "load_name": str(getattr(edit_region, "load_name", "") or "LOAD"),
                "load_layer": str(getattr(edit_region, "load_layer", "") or getattr(edit_region, "load_name", "") or "LOAD"),
                "dl": float(getattr(edit_region, "dl", 0.0) or 0.0),
                "ll": float(getattr(edit_region, "ll", 0.0) or 0.0),
                "distribution": str(getattr(edit_region, "distribution", "") or "TWO_WAY"),
                "one_way_angle": getattr(edit_region, "one_way_angle", None),
            }
        return None

    def _load_info_from_payload(self, payload: dict):
        one_way_angle = payload.get("one_way_angle")
        if one_way_angle in (None, ""):
            one_way_angle = payload.get("one_way_angle_deg")
        try:
            one_way_angle = None if one_way_angle in (None, "") else float(one_way_angle) % 180.0
        except Exception:
            one_way_angle = None
        return LoadLayerInfo(
            layer=str(payload.get("load_layer") or payload.get("load_name") or "LOAD"),
            real_name=str(payload.get("load_name") or "LOAD"),
            dl=float(payload.get("dl", 0.0) or 0.0),
            ll=float(payload.get("ll", 0.0) or 0.0),
            source="hatch_view_continuous_sync",
            distribution=str(payload.get("distribution") or "TWO_WAY"),
            one_way_angle_deg=one_way_angle,
            distribution_source="HATCH_VIEW_CONTINUOUS_SYNC",
        )

    def _load_conflicts_with_payload(self, existing_payload: dict | None, new_payload: dict | None) -> bool:
        if existing_payload is None or new_payload is None:
            return False
        return (
            str(existing_payload.get("load_name") or "") != str(new_payload.get("load_name") or "")
            or abs(float(existing_payload.get("dl", 0.0) or 0.0) - float(new_payload.get("dl", 0.0) or 0.0)) > 1.0e-9
            or abs(float(existing_payload.get("ll", 0.0) or 0.0) - float(new_payload.get("ll", 0.0) or 0.0)) > 1.0e-9
            or str(existing_payload.get("distribution") or "") != str(new_payload.get("distribution") or "")
            or abs(float(existing_payload.get("one_way_angle") or 0.0) - float(new_payload.get("one_way_angle") or 0.0)) > 1.0e-9
        )

    def _load_payload_from_edit_region(self, region) -> dict | None:
        if region is None or not str(getattr(region, "load_name", "") or ""):
            return None
        return {
            "load_name": str(getattr(region, "load_name", "") or "LOAD"),
            "load_layer": str(getattr(region, "load_layer", "") or getattr(region, "load_name", "") or "LOAD"),
            "dl": float(getattr(region, "dl", 0.0) or 0.0),
            "ll": float(getattr(region, "ll", 0.0) or 0.0),
            "distribution": str(getattr(region, "distribution", "") or "TWO_WAY"),
            "one_way_angle": getattr(region, "one_way_angle", None),
        }

    def _continuous_target_load_conflict_reason(self, base_region_key: str, target_story: str, payload: dict | None) -> str:
        if payload is None:
            return ""
        key = str(base_region_key or "")
        try:
            cache_key = self._continuous_target_load_conflict_reason_cache_key(key, target_story, payload)
            cache = self.__dict__.setdefault("_continuous_target_load_conflict_reason_cache", {})
            if cache_key in cache:
                self._continuous_target_load_conflict_reason_cache_hits = int(self.__dict__.get("_continuous_target_load_conflict_reason_cache_hits", 0) or 0) + 1
                return str(cache[cache_key] or "")
            self._continuous_target_load_conflict_reason_cache_misses = int(self.__dict__.get("_continuous_target_load_conflict_reason_cache_misses", 0) or 0) + 1
        except Exception:
            cache_key = None
            cache = None
        source_region = self._editable_hatch_region_by_key(key)
        target_story = str(target_story or "")
        reason = ""
        if source_region is not None:
            target_state = (self.__dict__.get("hatch_edit_states_by_story", {}) or {}).get(target_story)
            if target_state is not None:
                cell_ids, _polygon_xy = self._matching_target_cell_geometry_for_region(source_region, target_state)
                selected_cells = set(cell_ids)
                if not selected_cells:
                    if cache_key is not None and isinstance(cache, dict):
                        cache[cache_key] = reason
                    return reason
                for region in getattr(target_state, "regions_by_key", {}).values():
                    if not set(getattr(region, "cell_ids", ()) or ()).intersection(selected_cells):
                        continue
                    if self._load_conflicts_with_payload(self._load_payload_from_edit_region(region), payload):
                        reason = "이미 다른 하중이 반영되어 있습니다. 계속 선택하면 겹치는 영역만 새 연속층 하중으로 대체됩니다."
                        break
            if cache_key is not None and isinstance(cache, dict):
                cache[cache_key] = reason
            return reason

        source_dxf_region = self._dxf_region_by_key(key)
        if source_dxf_region is None:
            if cache_key is not None and isinstance(cache, dict):
                cache[cache_key] = reason
            return reason
        target_state = (self.__dict__.get("hatch_edit_states_by_story", {}) or {}).get(target_story)
        if target_state is not None and (getattr(target_state, "cells_by_id", {}) or {}):
            source_projection = self._editable_region_from_dxf_region(source_dxf_region, base_region_key=key)
            match = self._matching_target_cell_projection_for_region(source_projection, target_state)
            selected_cells = set(match.cell_ids)
            for region in getattr(target_state, "regions_by_key", {}).values():
                if not set(getattr(region, "cell_ids", ()) or ()).intersection(selected_cells):
                    continue
                if self._load_conflicts_with_payload(self._load_payload_from_edit_region(region), payload):
                    reason = "이미 다른 하중이 반영되어 있습니다. 계속 선택하면 겹치는 영역만 새 연속층 하중으로 대체됩니다."
                    break
        else:
            dxf_match = self._matching_target_dxf_projection_for_region_key(key, target_story)
            for target_key in dxf_match.cell_ids:
                if self._load_conflicts_with_payload(self._load_payload_from_region_key(target_key), payload):
                    reason = "이미 다른 하중이 반영되어 있습니다. 계속 선택하면 겹치는 영역만 새 연속층 하중으로 대체됩니다."
                    break
        if cache_key is not None and isinstance(cache, dict):
            cache[cache_key] = reason
        return reason

    def _continuous_load_conflict_reason_for_region_keys(self, region_keys, target_story: str) -> str:
        perf_token = self._hatch_perf_start("_continuous_load_conflict_reason_for_region_keys")
        try:
            cache_key = self._continuous_load_conflict_reason_cache_key(region_keys, target_story)
            cache = self.__dict__.setdefault("_continuous_load_conflict_reason_cache", {})
            if cache_key in cache:
                self._continuous_load_conflict_reason_cache_hits = int(self.__dict__.get("_continuous_load_conflict_reason_cache_hits", 0) or 0) + 1
                result = str(cache[cache_key] or "")
                self._hatch_perf_end(
                    perf_token,
                    story_name=str(target_story or ""),
                    display_mode=self._hatch_view_display_mode(),
                    visible_region_count=len(tuple(region_keys or ())),
                    structure_item_count=0,
                    candidate_target_count=1,
                    cache_hit=1,
                    cache_miss=0,
                )
                return result
            self._continuous_load_conflict_reason_cache_misses = int(self.__dict__.get("_continuous_load_conflict_reason_cache_misses", 0) or 0) + 1
        except Exception:
            cache_key = None
            cache = None
        result = ""
        for key in tuple(region_keys or ()):
            text_key = str(key or "")
            if not text_key:
                continue
            reason = self._continuous_target_load_conflict_reason(text_key, target_story, self._load_payload_from_region_key(text_key))
            if reason:
                result = reason
                break
        if cache_key is not None and isinstance(cache, dict):
            cache[cache_key] = result
        self._hatch_perf_end(
            perf_token,
            story_name=str(target_story or ""),
            display_mode=self._hatch_view_display_mode(),
            visible_region_count=len(tuple(region_keys or ())),
            structure_item_count=0,
            candidate_target_count=1,
            cache_hit=0,
            cache_miss=1,
            has_conflict=bool(result),
        )
        return result

    def _continuous_reason_user_text(self, candidate, *, conflict_reason: str = "") -> str:
        if conflict_reason:
            return conflict_reason
        if candidate is None:
            return "검토 정보가 없습니다."
        raw_reason = str(getattr(candidate, "reason", "") or "")
        if _continuous_candidate_can_apply(candidate) and raw_reason.upper() in {"", "OK", "APPLY", "CAN_APPLY"}:
            return "적용 가능합니다."
        mapping = {
            "OK": "적용 가능합니다.",
            "NO_PROFILE": "해당 층의 폐합영역 정보를 찾지 못했습니다.",
            "NO_MATCH": "선택한 해치와 같은 형상의 영역을 찾지 못했습니다.",
            "LOW_SIMILARITY": "형상 유사도가 낮아 자동 적용할 수 없습니다.",
            "AREA_MISMATCH": "면적 차이가 커서 자동 적용할 수 없습니다.",
            "BOUNDARY_MISMATCH": "경계선 구성이 달라 자동 적용할 수 없습니다.",
            "DIFFERENT_LOAD": "이미 다른 하중이 반영되어 있습니다.",
            "NOT_CONTINUOUS": "선택층과 연속된 적용 가능층이 아닙니다.",
            "COMMON_TARGET_ONLY": "선택한 여러 영역의 공통 적용 가능층이 아닙니다.",
        }
        normalized = raw_reason.strip().upper()
        if raw_reason == "공통 적용 가능층 아님":
            return "선택한 여러 영역의 공통 적용 가능층이 아닙니다."
        if normalized in mapping:
            return mapping[normalized]
        if any("\uac00" <= ch <= "\ud7a3" for ch in raw_reason):
            return raw_reason
        if _continuous_candidate_can_apply(candidate):
            return "적용 가능합니다."
        return "적용 조건을 만족하지 않아 자동 적용할 수 없습니다."

    def _sync_load_to_continuous_targets_for_region_keys(
        self,
        region_keys=None,
        *,
        remove: bool = False,
        refresh_ui: bool = True,
    ) -> None:
        raw_keys = {
            str(key or "")
            for key in tuple(region_keys or self._selected_hatch_region_keys_for_continuous_info() or ())
            if str(key or "")
        }
        keys = tuple(
            sorted(
                raw_keys,
                key=lambda key: (
                    self._continuous_region_geometry_fingerprint(key),
                    key,
                ),
            )
        )
        if not keys:
            return
        target_map = dict(self.__dict__.get("continuous_apply_targets_by_region", {}) or {})
        changed = False
        for key in keys:
            targets = tuple(str(name or "") for name in tuple(target_map.get(key, ()) or ()) if str(name or ""))
            if not targets:
                continue
            payload = None if remove else self._load_payload_from_region_key(key)
            if payload is None and not remove:
                continue
            for target_story in targets:
                if self._apply_or_remove_continuous_load_to_target_story(
                    base_region_key=key,
                    target_story=target_story,
                    payload=payload,
                    remove=remove,
                ):
                    changed = True
        if changed:
            self._refresh_hatch_edit_region_index()
            if refresh_ui:
                self._render_hatch_preview()
                self._refresh_selected_hatch_continuous_info()

    def _apply_or_remove_continuous_load_to_target_story(
        self,
        *,
        base_region_key: str,
        target_story: str,
        payload: dict | None,
        remove: bool = False,
    ) -> bool:
        key = str(base_region_key or "")
        target_story = str(target_story or "")
        if not key or not target_story:
            return False
        source_edit_region = self._editable_hatch_region_by_key(key)
        if source_edit_region is not None:
            return self._apply_or_remove_continuous_load_to_target_edit_region(
                base_region_key=key,
                source_region=source_edit_region,
                target_story=target_story,
                payload=payload,
                remove=remove,
            )
        source_dxf_region = self._dxf_region_by_key(key)
        if source_dxf_region is not None:
            return self._apply_or_remove_continuous_load_to_target_dxf_region(
                base_region_key=key,
                source_region=source_dxf_region,
                target_story=target_story,
                payload=payload,
                remove=remove,
            )
        return False

    def _set_one_way_target_guard_warning(self) -> None:
        self._set_continuous_status(
            "ONE-WAY 연속층 하중은 3각형 또는 4각형 target 영역에만 적용할 수 있습니다. 해당 층에서 직접 해치분리 후 다시 적용해 주세요.",
            warning=True,
        )

    def _apply_or_remove_continuous_load_to_target_edit_region(
        self,
        *,
        base_region_key: str,
        source_region,
        target_story: str,
        payload: dict | None,
        remove: bool = False,
    ) -> bool:
        target_state = self._ensure_hatch_edit_state_for_story(str(target_story or ""))
        if target_state is None:
            return False
        mirror_key = self._continuous_mirror_region_key(base_region_key, target_story)
        existing_key = self._find_matching_edit_region_key_for_target(source_region, target_state, mirror_key=mirror_key)
        cell_ids, polygon_xy = self._matching_target_cell_geometry_for_region(source_region, target_state)
        if cell_ids:
            previous_selected_regions = set(getattr(target_state, "selected_region_keys", set()) or set())
            previous_selected_cells = set(getattr(target_state, "selected_cell_ids", set()) or set())
            selected_cells = set(cell_ids)
            target_state.selected_cell_ids = set(selected_cells)
            target_state.selected_region_keys = set()
            if remove:
                updated_state = remove_load_from_selection(target_state)
            else:
                if payload is None:
                    target_state.selected_region_keys = previous_selected_regions
                    target_state.selected_cell_ids = previous_selected_cells
                    return False
                one_way_payload = self._payload_is_one_way(payload)
                updated_state, stats = apply_load_to_selection_with_stats(
                    target_state,
                    load_name=str(payload.get("load_name") or "LOAD"),
                    load_layer=str(payload.get("load_layer") or payload.get("load_name") or "LOAD"),
                    dl=float(payload.get("dl", 0.0) or 0.0),
                    ll=float(payload.get("ll", 0.0) or 0.0),
                    distribution=str(payload.get("distribution") or "TWO_WAY"),
                    one_way_angle=payload.get("one_way_angle") if payload.get("one_way_angle") not in (None, "") else payload.get("one_way_angle_deg"),
                    shape_tolerance=self._one_way_shape_tolerance(),
                )
                if one_way_payload and int(stats.get("applied", 0) or 0) <= 0:
                    target_state.selected_region_keys = previous_selected_regions
                    target_state.selected_cell_ids = previous_selected_cells
                    self._set_one_way_target_guard_warning()
                    return False
                applied_cells = set(selected_cells)
                if one_way_payload:
                    applied_cells = {
                        cell_id
                        for cell_id in selected_cells
                        if (cell := target_state.cells_by_id.get(cell_id)) is not None
                        and is_one_way_tri_or_quad(
                            getattr(cell, "polygon_xy", ()) or (),
                            tolerance=self._one_way_shape_tolerance(),
                        )
                    }
                adjusted_regions = {}
                for key, region in updated_state.regions_by_key.items():
                    if set(getattr(region, "cell_ids", ()) or ()).intersection(applied_cells) and getattr(region, "load_name", None):
                        adjusted_regions[key] = replace(region, source="CONTINUOUS_SYNC")
                    else:
                        adjusted_regions[key] = region
                updated_state = HatchEditState(
                    updated_state.story_name,
                    dict(updated_state.cells_by_id),
                    adjusted_regions,
                    set(updated_state.selected_region_keys),
                    set(updated_state.selected_cell_ids),
                )
            updated_state.selected_region_keys = previous_selected_regions
            updated_state.selected_cell_ids = previous_selected_cells
            self.hatch_edit_states_by_story[str(target_story)] = updated_state
            self._set_continuous_materialized_target(base_region_key, target_story, not remove)
            return True
        if not remove and (getattr(target_state, "cells_by_id", {}) or {}):
            self._set_continuous_status(
                "선택 영역의 수직투영을 완전히 덮는 target 폐합영역을 찾지 못해 적용하지 않았습니다.",
                warning=True,
            )
            return False
        if not remove and self.__dict__.get("stories") and self.__dict__.get("nodes") and self.__dict__.get("elements"):
            self._set_continuous_status(
                "target Story의 폐합 geometry를 검증하지 못해 연속층 하중을 적용하지 않았습니다.",
                warning=True,
            )
            return False
        if remove:
            if existing_key is None:
                self._set_continuous_materialized_target(base_region_key, target_story, False)
                return False
            existing = target_state.regions_by_key.get(existing_key)
            if existing is not None and str(getattr(existing, "source", "") or "") == "CONTINUOUS_SYNC":
                target_state.regions_by_key.pop(existing_key, None)
            elif existing is not None:
                target_state.regions_by_key[existing_key] = replace(
                    existing,
                    load_name=None,
                    load_layer=None,
                    dl=None,
                    ll=None,
                    distribution=str(getattr(existing, "distribution", "") or "TWO_WAY"),
                    one_way_angle=None,
                )
            self._set_continuous_materialized_target(base_region_key, target_story, False)
            return True
        if payload is None:
            return False
        existing = target_state.regions_by_key.get(existing_key) if existing_key is not None else None
        base_region = existing if existing is not None else source_region
        region_key = str(getattr(base_region, "region_key", "") or mirror_key)
        if existing is None:
            region_key = mirror_key
        payload_for_target = payload
        target_vertices = polygon_xy or tuple(getattr(base_region, "polygon_xy", ()) or ()) or tuple(getattr(source_region, "polygon_xy", ()) or ())
        if self._payload_is_one_way(payload):
            payload_for_target = self._one_way_item_for_vertices(payload, target_vertices)
            if payload_for_target is None:
                self._set_one_way_target_guard_warning()
                return False
        updated = replace(
            base_region,
            region_key=region_key,
            story_name=str(target_story),
            cell_ids=cell_ids or tuple(getattr(base_region, "cell_ids", ()) or ()),
            polygon_xy=polygon_xy or tuple(getattr(source_region, "polygon_xy", ()) or ()),
            load_name=str(payload_for_target.get("load_name") or "LOAD"),
            load_layer=str(payload_for_target.get("load_layer") or payload_for_target.get("load_name") or "LOAD"),
            dl=float(payload_for_target.get("dl", 0.0) or 0.0),
            ll=float(payload_for_target.get("ll", 0.0) or 0.0),
            distribution=str(payload_for_target.get("distribution") or "TWO_WAY"),
            one_way_angle=payload_for_target.get("one_way_angle") if payload_for_target.get("one_way_angle") not in (None, "") else payload_for_target.get("one_way_angle_deg"),
            source=str(getattr(base_region, "source", "") or "CONTINUOUS_SYNC") if existing is not None else "CONTINUOUS_SYNC",
        )
        if existing_key is not None and existing_key != region_key:
            target_state.regions_by_key.pop(existing_key, None)
        target_state.regions_by_key[region_key] = updated
        self._set_continuous_materialized_target(base_region_key, target_story, True)
        return True

    def _apply_or_remove_continuous_load_to_target_dxf_region(
        self,
        *,
        base_region_key: str,
        source_region,
        target_story: str,
        payload: dict | None,
        remove: bool = False,
    ) -> bool:
        target_state = self._ensure_hatch_edit_state_for_story(str(target_story or ""))
        if target_state is not None and (getattr(target_state, "cells_by_id", {}) or {}):
            source_edit_region = self._editable_region_from_dxf_region(source_region, base_region_key=base_region_key)
            return self._apply_or_remove_continuous_load_to_target_edit_region(
                base_region_key=base_region_key,
                source_region=source_edit_region,
                target_story=target_story,
                payload=payload,
                remove=remove,
            )
        if remove and self._remove_continuous_dxf_split_regions(base_region_key=base_region_key, target_story=target_story):
            self._set_continuous_materialized_target(base_region_key, target_story, False)
            return True
        dxf_match = self._matching_target_dxf_projection_for_region_key(base_region_key, target_story)
        target_keys = tuple(dxf_match.cell_ids) if dxf_match.ok else ()
        if not target_keys and not remove:
            overlapping_key = self._find_overlapping_dxf_region_key_for_target_story(base_region_key, target_story)
            target_keys = (overlapping_key,) if overlapping_key else ()
        if target_keys:
            changed = False
            for target_key in target_keys:
                target_region = self._dxf_region_by_key(target_key)
                if target_region is None:
                    continue
                if remove:
                    previous_load = getattr(target_region, "_continuous_previous_load", None)
                    if previous_load is not None:
                        target_region.load = copy.deepcopy(previous_load)
                        target_region.status = "OK" if target_region.load is not None else "NO_LOAD"
                    else:
                        target_region.load = None
                        target_region.status = "NO_LOAD"
                    changed = True
                    continue
                if payload is None:
                    continue
                if self._split_dxf_region_by_overlap_and_apply_load(
                    target_key=target_key,
                    base_region_key=base_region_key,
                    source_region=source_region,
                    target_region=target_region,
                    target_story=target_story,
                    payload=payload,
                ):
                    changed = True
            if changed:
                self._set_continuous_materialized_target(base_region_key, target_story, not remove)
            return changed
        if remove:
            self._set_continuous_materialized_target(base_region_key, target_story, False)
            return False
        if target_state is not None and (getattr(target_state, "cells_by_id", {}) or {}):
            return False
        source_edit_region = self._editable_region_from_dxf_region(source_region, base_region_key=base_region_key)
        return self._apply_or_remove_continuous_load_to_target_edit_region(
            base_region_key=base_region_key,
            source_region=source_edit_region,
            target_story=target_story,
            payload=payload,
            remove=remove,
        )

    def _split_dxf_region_by_overlap_and_apply_load(
        self,
        *,
        target_key: str,
        base_region_key: str,
        source_region,
        target_region,
        target_story: str,
        payload: dict,
    ) -> bool:
        source_polygon = self._polygon_from_load_region(source_region)
        target_polygon = self._polygon_from_load_region(target_region)
        if source_polygon is None or target_polygon is None:
            self._set_continuous_status("겹치는 영역을 자동 분리하지 못했습니다. 해당 층에서 직접 해치분리 후 다시 적용해 주세요.", warning=True)
            return False
        try:
            iou = self._polygon_iou(source_polygon, target_polygon)
            intersection = target_polygon.intersection(source_polygon)
            remain = target_polygon.difference(source_polygon)
        except Exception:
            self._set_continuous_status("겹치는 영역을 자동 분리하지 못했습니다. 해당 층에서 직접 해치분리 후 다시 적용해 주세요.", warning=True)
            return False
        intersection_parts = self._polygon_parts(intersection)
        if not intersection_parts:
            self._set_continuous_status("선택한 해치와 겹치는 target DXF 하중영역을 찾지 못했습니다.", warning=True)
            return False
        one_way_payload = self._payload_is_one_way(payload)
        valid_intersections: list[tuple[object, dict]] = []
        invalid_intersections: list[object] = []
        if one_way_payload:
            for polygon in intersection_parts:
                payload_for_part = self._one_way_item_for_vertices(payload, self._polygon_exterior_xy(polygon))
                if payload_for_part is None:
                    invalid_intersections.append(polygon)
                else:
                    valid_intersections.append((polygon, payload_for_part))
            if not valid_intersections:
                self._set_one_way_target_guard_warning()
                return False
        else:
            valid_intersections = [(polygon, payload) for polygon in intersection_parts]
        previous_load = copy.deepcopy(getattr(target_region, "load", None))
        if iou >= 0.98:
            new_load = self._load_info_from_payload(valid_intersections[0][1])
            setattr(target_region, "_continuous_previous_load", previous_load)
            target_region.load = new_load
            target_region.status = "OK"
            return True
        remain_parts = self._polygon_parts(remain)
        if not remain_parts:
            first_polygon, first_payload = valid_intersections[0]
            new_load = self._load_info_from_payload(first_payload)
            setattr(target_region, "_continuous_previous_load", previous_load)
            self._update_load_region_geometry(target_region, first_polygon, source_id=f"{target_key}:continuous-full")
            target_region.load = new_load
            target_region.status = "OK"
            additions = []
            split_prefix = f"continuous:{str(base_region_key or '')}@{str(target_story or '')}:overlap"
            for index, (polygon, part_payload) in enumerate(valid_intersections[1:], start=2):
                split_region = self._clone_load_region_with_polygon(
                    target_region,
                    polygon,
                    load=self._load_info_from_payload(part_payload),
                    status="OK",
                    source_id=f"{split_prefix}:{index}",
                )
                setattr(split_region, "_continuous_previous_load", previous_load)
                additions.append(split_region)
            for index, polygon in enumerate(invalid_intersections, start=1):
                additions.append(
                    self._clone_load_region_with_polygon(
                        target_region,
                        polygon,
                        load=previous_load,
                        status="OK" if previous_load is not None else "NO_LOAD",
                        source_id=f"{target_key}:one-way-guard:{index}",
                    )
                )
            if additions:
                loaded_regions = list(self.__dict__.get("loaded_regions", []) or [])
                loaded_regions.extend(additions)
                self.loaded_regions = loaded_regions
                self._invalidate_continuous_below_allowed_reason_cache("연속층 DXF split 영역 추가")
            return True
        old_load_parts = list(remain_parts)
        if one_way_payload:
            old_load_parts.extend(invalid_intersections)
        additions = []
        if old_load_parts:
            self._update_load_region_geometry(target_region, old_load_parts[0], source_id=f"{target_key}:remain:1")
            target_region.load = previous_load
            target_region.status = "OK" if target_region.load is not None else "NO_LOAD"
            for index, polygon in enumerate(old_load_parts[1:], start=2):
                additions.append(
                    self._clone_load_region_with_polygon(
                        target_region,
                        polygon,
                        load=previous_load,
                        status="OK" if previous_load is not None else "NO_LOAD",
                        source_id=f"{target_key}:remain:{index}",
                    )
                )
        else:
            first_polygon, first_payload = valid_intersections[0]
            setattr(target_region, "_continuous_previous_load", previous_load)
            self._update_load_region_geometry(target_region, first_polygon, source_id=f"{target_key}:continuous-full")
            target_region.load = self._load_info_from_payload(first_payload)
            target_region.status = "OK"
            valid_intersections = valid_intersections[1:]
        split_prefix = f"continuous:{str(base_region_key or '')}@{str(target_story or '')}:overlap"
        for index, (polygon, part_payload) in enumerate(valid_intersections, start=1):
            split_region = self._clone_load_region_with_polygon(
                target_region,
                polygon,
                load=self._load_info_from_payload(part_payload),
                status="OK",
                source_id=f"{split_prefix}:{index}",
            )
            setattr(split_region, "_continuous_previous_load", previous_load)
            additions.append(split_region)
        loaded_regions = list(self.__dict__.get("loaded_regions", []) or [])
        loaded_regions.extend(additions)
        self.loaded_regions = loaded_regions
        self._invalidate_continuous_below_allowed_reason_cache("연속층 DXF split 영역 추가")
        return True

    def _remove_continuous_dxf_split_regions(self, *, base_region_key: str, target_story: str) -> bool:
        prefix = f"continuous:{str(base_region_key or '')}@{str(target_story or '')}:overlap"
        changed = False
        for region in tuple(self.__dict__.get("loaded_regions", []) or ()):
            hatch = getattr(region, "region", None)
            source_id = str(getattr(hatch, "source_id", "") or getattr(hatch, "handle", "") or "")
            if not source_id.startswith(prefix):
                continue
            previous_load = getattr(region, "_continuous_previous_load", None)
            region.load = copy.deepcopy(previous_load) if previous_load is not None else None
            region.status = "OK" if region.load is not None else "NO_LOAD"
            changed = True
        return changed

    def _clone_load_region_with_polygon(self, load_region, polygon, *, load, status: str, source_id: str):
        hatch = getattr(load_region, "region", None)
        coords = list(self._polygon_exterior_xy(polygon))
        bounds = tuple(float(value) for value in getattr(polygon, "bounds", ()) or ())
        if len(bounds) != 4:
            bounds = (0.0, 0.0, 0.0, 0.0)
        cloned_hatch = replace(
            hatch,
            handle=str(source_id or getattr(hatch, "handle", "") or ""),
            source_id=str(source_id or getattr(hatch, "source_id", "") or ""),
            vertices=coords,
            polygon=polygon,
            area=float(getattr(polygon, "area", 0.0) or 0.0),
            bbox=bounds,
            placed_vertices=[],
            placed_bbox=bounds,
            source_bbox=bounds,
            model_bbox=bounds,
        )
        return replace(
            load_region,
            region=cloned_hatch,
            load=copy.deepcopy(load),
            status=str(status or "NO_LOAD"),
            warnings=list(getattr(load_region, "warnings", []) or []),
        )

    def _update_load_region_geometry(self, load_region, polygon, *, source_id: str) -> None:
        updated = self._clone_load_region_with_polygon(
            load_region,
            polygon,
            load=getattr(load_region, "load", None),
            status=str(getattr(load_region, "status", "") or "NO_LOAD"),
            source_id=source_id,
        )
        load_region.region = updated.region
        self._invalidate_continuous_below_allowed_reason_cache("DXF 해치 geometry 변경")

    def _polygon_parts(self, geometry) -> list:
        if geometry is None or getattr(geometry, "is_empty", True):
            return []
        geom_type = str(getattr(geometry, "geom_type", "") or "")
        if geom_type == "Polygon":
            polygons = [geometry]
        elif geom_type == "MultiPolygon":
            polygons = list(getattr(geometry, "geoms", ()) or ())
        else:
            return []
        result = []
        for polygon in polygons:
            try:
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)
                if not polygon.is_empty and str(getattr(polygon, "geom_type", "") or "") == "Polygon" and float(polygon.area) > 1.0e-12:
                    result.append(polygon)
            except Exception:
                continue
        return sorted(result, key=lambda item: float(getattr(item, "area", 0.0) or 0.0), reverse=True)

    def _dxf_region_by_key(self, region_key: str):
        key = str(region_key or "")
        region_by_key = self.__dict__.get("hatch_view_region_by_key", {}) or {}
        if key in region_by_key:
            return region_by_key[key]
        for index, region in enumerate(tuple(self.__dict__.get("loaded_regions", ()) or ()), start=1):
            if self._region_key(region, index=index) == key:
                return region
        return None

    def _ensure_hatch_edit_state_for_story(self, story_name: str):
        story_name = str(story_name or "")
        if not story_name:
            return None
        states = self.__dict__.setdefault("hatch_edit_states_by_story", {})
        if story_name not in states:
            self._ensure_hatch_edit_states(story_name)
        if story_name not in states:
            states[story_name] = HatchEditState(story_name, {}, {}, set(), set())
        return states.get(story_name)

    def _continuous_mirror_region_key(self, base_region_key: str, target_story: str) -> str:
        return f"continuous:{str(base_region_key or '')}@{str(target_story or '')}"

    def _editable_region_from_dxf_region(self, load_region, *, base_region_key: str) -> EditableHatchRegion:
        hatch = getattr(load_region, "region", load_region)
        vertices = tuple((float(x), float(y)) for x, y in tuple(getattr(hatch, "vertices", ()) or ()))
        return EditableHatchRegion(
            region_key=f"continuous-source:{base_region_key}",
            story_name=str(getattr(hatch, "story_name", "") or ""),
            cell_ids=(),
            polygon_xy=vertices,
            load_name=None,
            load_layer=None,
            dl=None,
            ll=None,
            distribution="TWO_WAY",
            one_way_angle=None,
            source="DXF_CONTINUOUS_SOURCE",
            is_merged=False,
            warning_codes=(),
        )

    def _find_matching_edit_region_key_for_target(self, source_region, target_state, *, mirror_key: str) -> str | None:
        if mirror_key in getattr(target_state, "regions_by_key", {}):
            return mirror_key
        source_polygon = self._polygon_from_xy(getattr(source_region, "polygon_xy", ()) or ())
        if source_polygon is None:
            return None
        best_key = None
        best_score = 0.0
        for key, region in getattr(target_state, "regions_by_key", {}).items():
            target_polygon = self._polygon_from_xy(getattr(region, "polygon_xy", ()) or ())
            score = self._polygon_iou(source_polygon, target_polygon)
            if score > best_score:
                best_key = str(key)
                best_score = score
        return best_key if best_score >= 0.90 else None

    def _continuous_projection_policy(self) -> tuple[float, float]:
        config = self.__dict__.get("config_data")
        try:
            min_coverage = float(getattr(config, "continuous_projection_min_coverage"))
        except Exception:
            min_coverage = 0.995
        try:
            max_overreach = float(getattr(config, "continuous_projection_max_overreach_ratio"))
        except Exception:
            max_overreach = 0.005
        return (_clamp(min_coverage, 0.0, 1.0), _clamp(max_overreach, 0.0, 1.0))

    def _matching_target_cell_projection_for_region(self, source_region, target_state) -> ContinuousTargetCellMatch:
        perf_token = self._hatch_perf_start("_matching_target_cell_geometry_for_region")
        try:
            cache_key = self._matching_target_cell_geometry_cache_key(source_region, target_state)
            cache = self.__dict__.setdefault("_matching_target_cell_geometry_cache", {})
            if cache_key in cache:
                self._matching_target_cell_geometry_cache_hits = int(self.__dict__.get("_matching_target_cell_geometry_cache_hits", 0) or 0) + 1
                result = cache[cache_key]
                self._hatch_perf_end(
                    perf_token,
                    story_name=str(getattr(target_state, "story_name", "") or ""),
                    display_mode=self._hatch_view_display_mode(),
                    visible_region_count=1,
                    structure_item_count=0,
                    candidate_target_count=len(getattr(target_state, "cells_by_id", {}) or {}),
                    cache_hit=1,
                    cache_miss=0,
                )
                return result
            self._matching_target_cell_geometry_cache_misses = int(self.__dict__.get("_matching_target_cell_geometry_cache_misses", 0) or 0) + 1
        except Exception:
            cache_key = None
            cache = None
        source_polygon = self._polygon_from_xy(getattr(source_region, "polygon_xy", ()) or ())
        if source_polygon is None:
            result = ContinuousTargetCellMatch((), (), "INVALID_SOURCE", 0.0, 0.0, 0.0)
            if cache_key is not None and isinstance(cache, dict):
                cache[cache_key] = result
            self._hatch_perf_end(
                perf_token,
                story_name=str(getattr(target_state, "story_name", "") or ""),
                display_mode=self._hatch_view_display_mode(),
                visible_region_count=1,
                structure_item_count=0,
                candidate_target_count=len(getattr(target_state, "cells_by_id", {}) or {}),
                cache_hit=0,
                cache_miss=1,
                matched_cell_count=0,
            )
            return result
        xy_tolerance = self._continuous_sync_xy_tolerance()
        min_coverage, max_overreach = self._continuous_projection_policy()
        source_area = max(float(source_polygon.area), 1.0e-12)
        source_buffer = source_polygon.buffer(xy_tolerance)
        area_epsilon = max(1.0e-12, xy_tolerance * xy_tolerance * 1.0e-6)
        matches: list[tuple[str, object]] = []
        for cell_id, cell in getattr(target_state, "cells_by_id", {}).items():
            cell_polygon = self._polygon_from_xy(getattr(cell, "polygon_xy", ()) or ())
            if cell_polygon is None:
                continue
            try:
                intersection_area = float(source_polygon.intersection(cell_polygon).area)
                cell_area = max(float(cell_polygon.area), 1.0e-12)
                cell_overreach = float(cell_polygon.difference(source_buffer).area) / cell_area
            except Exception:
                continue
            if intersection_area <= area_epsilon or cell_overreach > max_overreach:
                continue
            matches.append((str(cell_id), cell_polygon))
        if not matches:
            result = ContinuousTargetCellMatch((), (), "NO_SAFE_TARGET_CELLS", 0.0, 0.0, 0.0)
            if cache_key is not None and isinstance(cache, dict):
                cache[cache_key] = result
            self._hatch_perf_end(
                perf_token,
                story_name=str(getattr(target_state, "story_name", "") or ""),
                display_mode=self._hatch_view_display_mode(),
                visible_region_count=1,
                structure_item_count=0,
                candidate_target_count=len(getattr(target_state, "cells_by_id", {}) or {}),
                cache_hit=0,
                cache_miss=1,
                matched_cell_count=0,
            )
            return result
        try:
            from shapely.ops import unary_union

            merged = unary_union([polygon for _cell_id, polygon in matches])
            intersection_area = float(source_polygon.intersection(merged).area)
            target_area = max(float(merged.area), 1.0e-12)
            union_area = max(float(source_polygon.union(merged).area), 1.0e-12)
            source_coverage = _clamp(intersection_area / source_area, 0.0, 1.0)
            target_overreach = _clamp(float(merged.difference(source_buffer).area) / target_area, 0.0, 1.0)
            source_missing_beyond_tolerance = float(source_polygon.difference(merged.buffer(xy_tolerance)).area) / source_area
            iou = _clamp(intersection_area / union_area, 0.0, 1.0)
            polygon_xy = self._polygon_exterior_xy(merged)
        except Exception:
            result = ContinuousTargetCellMatch((), (), "TARGET_UNION_ERROR", 0.0, 0.0, 0.0)
            if cache_key is not None and isinstance(cache, dict):
                cache[cache_key] = result
            return result
        coverage_ok = source_coverage >= min_coverage or source_missing_beyond_tolerance <= max_overreach
        if not coverage_ok:
            status = "INCOMPLETE_SOURCE_COVERAGE"
        elif target_overreach > max_overreach:
            status = "TARGET_OVERREACH"
        elif not polygon_xy:
            status = "NON_POLYGON_TARGET_UNION"
        else:
            status = "MATCH"
        result = ContinuousTargetCellMatch(
            tuple(cell_id for cell_id, _polygon in matches) if status == "MATCH" else (),
            tuple(polygon_xy) if status == "MATCH" else (),
            status,
            source_coverage,
            target_overreach,
            iou,
        )
        if cache_key is not None and isinstance(cache, dict):
            cache[cache_key] = result
        self._hatch_perf_end(
            perf_token,
            story_name=str(getattr(target_state, "story_name", "") or ""),
            display_mode=self._hatch_view_display_mode(),
            visible_region_count=1,
            structure_item_count=0,
            candidate_target_count=len(getattr(target_state, "cells_by_id", {}) or {}),
            cache_hit=0,
            cache_miss=1,
            matched_cell_count=len(result.cell_ids),
            source_coverage=round(result.source_coverage, 6),
            target_overreach=round(result.target_overreach_ratio, 6),
            iou=round(result.iou, 6),
        )
        return result

    def _matching_target_cell_geometry_for_region(self, source_region, target_state) -> tuple[tuple[str, ...], tuple[tuple[float, float], ...]]:
        match = self._matching_target_cell_projection_for_region(source_region, target_state)
        return (tuple(match.cell_ids), tuple(match.polygon_xy))

    def _matching_target_dxf_projection_for_region_key(self, base_region_key: str, target_story: str) -> ContinuousTargetCellMatch:
        base_region = self._dxf_region_by_key(base_region_key)
        base_polygon = self._polygon_from_load_region(base_region) if base_region is not None else None
        if base_polygon is None:
            return ContinuousTargetCellMatch((), (), "INVALID_SOURCE", 0.0, 0.0, 0.0)
        xy_tolerance = self._continuous_sync_xy_tolerance()
        min_coverage, max_overreach = self._continuous_projection_policy()
        source_buffer = base_polygon.buffer(xy_tolerance)
        source_area = max(float(base_polygon.area), 1.0e-12)
        area_epsilon = max(1.0e-12, xy_tolerance * xy_tolerance * 1.0e-6)
        matches: list[tuple[str, object]] = []
        target_geometry_seen = False
        for index, region in enumerate(tuple(self.__dict__.get("loaded_regions", ()) or ()), start=1):
            key = self._region_key(region, index=index)
            if key == str(base_region_key or ""):
                continue
            if str(getattr(getattr(region, "region", None), "story_name", "") or "") != str(target_story or ""):
                continue
            polygon = self._polygon_from_load_region(region)
            if polygon is None:
                continue
            target_geometry_seen = True
            try:
                intersection_area = float(base_polygon.intersection(polygon).area)
                polygon_area = max(float(polygon.area), 1.0e-12)
                overreach = float(polygon.difference(source_buffer).area) / polygon_area
            except Exception:
                continue
            if intersection_area <= area_epsilon or overreach > max_overreach:
                continue
            matches.append((key, polygon))
        if not matches:
            status = "NO_SAFE_TARGET_CELLS" if target_geometry_seen else "TARGET_GEOMETRY_UNAVAILABLE"
            return ContinuousTargetCellMatch((), (), status, 0.0, 0.0, 0.0)
        try:
            from shapely.ops import unary_union

            merged = unary_union([polygon for _key, polygon in matches])
            intersection_area = float(base_polygon.intersection(merged).area)
            target_area = max(float(merged.area), 1.0e-12)
            union_area = max(float(base_polygon.union(merged).area), 1.0e-12)
            source_coverage = _clamp(intersection_area / source_area, 0.0, 1.0)
            target_overreach = _clamp(float(merged.difference(source_buffer).area) / target_area, 0.0, 1.0)
            source_missing_beyond_tolerance = float(base_polygon.difference(merged.buffer(xy_tolerance)).area) / source_area
            polygon_xy = self._polygon_exterior_xy(merged)
        except Exception:
            return ContinuousTargetCellMatch((), (), "TARGET_UNION_ERROR", 0.0, 0.0, 0.0)
        coverage_ok = source_coverage >= min_coverage or source_missing_beyond_tolerance <= max_overreach
        status = "MATCH" if coverage_ok and target_overreach <= max_overreach and polygon_xy else "PROJECTED_UNION_MISMATCH"
        return ContinuousTargetCellMatch(
            tuple(key for key, _polygon in matches) if status == "MATCH" else (),
            tuple(polygon_xy) if status == "MATCH" else (),
            status,
            source_coverage,
            target_overreach,
            _clamp(intersection_area / union_area, 0.0, 1.0),
        )

    def _find_matching_dxf_region_key_for_target_story(self, base_region_key: str, target_story: str) -> str | None:
        base_region = self._dxf_region_by_key(base_region_key)
        if base_region is None:
            return None
        base_polygon = self._polygon_from_load_region(base_region)
        if base_polygon is None:
            return None
        best_key = None
        best_score = 0.0
        for index, region in enumerate(tuple(self.__dict__.get("loaded_regions", ()) or ()), start=1):
            key = self._region_key(region, index=index)
            if key == str(base_region_key or ""):
                continue
            if str(getattr(getattr(region, "region", None), "story_name", "") or "") != str(target_story or ""):
                continue
            target_polygon = self._polygon_from_load_region(region)
            score = self._polygon_iou(base_polygon, target_polygon)
            if score > best_score:
                best_key = key
                best_score = score
        return best_key if best_score >= 0.90 else None

    def _find_overlapping_dxf_region_key_for_target_story(self, base_region_key: str, target_story: str) -> str | None:
        base_region = self._dxf_region_by_key(base_region_key)
        if base_region is None:
            return None
        base_polygon = self._polygon_from_load_region(base_region)
        if base_polygon is None:
            return None
        base_area = max(float(getattr(base_polygon, "area", 0.0) or 0.0), 1.0e-12)
        best_key = None
        best_score = 0.0
        for index, region in enumerate(tuple(self.__dict__.get("loaded_regions", ()) or ()), start=1):
            key = self._region_key(region, index=index)
            if key == str(base_region_key or ""):
                continue
            if str(getattr(getattr(region, "region", None), "story_name", "") or "") != str(target_story or ""):
                continue
            target_polygon = self._polygon_from_load_region(region)
            if target_polygon is None:
                continue
            try:
                overlap_area = float(base_polygon.intersection(target_polygon).area)
            except Exception:
                continue
            score = overlap_area / base_area
            if score > best_score:
                best_key = key
                best_score = score
        return best_key if best_score > 1.0e-6 else None

    def _polygon_from_load_region(self, load_region):
        hatch = getattr(load_region, "region", load_region)
        polygon = getattr(load_region, "polygon", None) or getattr(hatch, "polygon", None)
        if polygon is not None and not getattr(polygon, "is_empty", True):
            return polygon
        return self._polygon_from_xy(getattr(hatch, "vertices", ()) or ())

    def _polygon_from_xy(self, points):
        try:
            from shapely.geometry import Polygon

            coords = tuple((float(x), float(y)) for x, y in tuple(points or ()))
            if len(coords) < 3:
                return None
            polygon = Polygon(coords)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty or float(getattr(polygon, "area", 0.0) or 0.0) <= 1.0e-12:
                return None
            if getattr(polygon, "geom_type", "") != "Polygon":
                return None
            return polygon
        except Exception:
            return None

    def _polygon_iou(self, first, second) -> float:
        if first is None or second is None:
            return 0.0
        try:
            union_area = float(first.union(second).area)
            if union_area <= 1.0e-12:
                return 0.0
            return float(first.intersection(second).area) / union_area
        except Exception:
            return 0.0

    def _polygon_exterior_xy(self, polygon) -> tuple[tuple[float, float], ...]:
        try:
            if getattr(polygon, "geom_type", "") != "Polygon":
                return ()
            coords = list(polygon.exterior.coords)
            if len(coords) > 1 and coords[0] == coords[-1]:
                coords = coords[:-1]
            return tuple((float(x), float(y)) for x, y in coords)
        except Exception:
            return ()

    def _continuous_sync_xy_tolerance(self) -> float:
        value = None
        snap_tol_var = self.__dict__.get("snap_tol_var")
        if snap_tol_var is not None:
            try:
                value = float(snap_tol_var.get())
            except Exception:
                value = None
        if value is None:
            config = self.__dict__.get("config_data")
            try:
                value = float(getattr(config, "snap_tolerance"))
            except Exception:
                value = 0.5
        return max(float(value), 1.0e-9)

    def _set_continuous_materialized_target(self, base_region_key: str, target_story: str, materialized: bool) -> None:
        key = str(base_region_key or "")
        target = str(target_story or "")
        if not key or not target:
            return
        materialized_map = self.__dict__.setdefault("continuous_materialized_targets_by_region", {})
        values = {str(name or "") for name in tuple(materialized_map.get(key, ()) or ()) if str(name or "")}
        if materialized:
            values.add(target)
        else:
            values.discard(target)
        if values:
            order = self._story_order_names()
            ordered = [name for name in order if name in values]
            ordered.extend(sorted(name for name in values if name not in set(ordered)))
            materialized_map[key] = tuple(ordered)
        else:
            materialized_map.pop(key, None)

    def _hatch_edit_region_display_vertices(self, region, story_offsets: dict[str, tuple[float, float]] | None = None) -> list[tuple[float, float]]:
        points = [(float(x), float(y)) for x, y in tuple(getattr(region, "polygon_xy", ()) or ())]
        if not points:
            return []
        if self._hatch_view_is_all_story_display():
            display_transform = self._hatch_all_story_transform_for_story(str(getattr(region, "story_name", "") or ""), story_offsets)
            return [display_transform.apply(x, y) for x, y in points]
        return points

    def _hatch_view_display_edit_regions(self, story_offsets: dict[str, tuple[float, float]] | None = None):
        display = []
        self.hatch_view_edit_region_by_key = {}
        for state in self._hatch_view_active_edit_states():
            for region in state.regions_by_key.values():
                vertices = self._hatch_edit_region_display_vertices(region, story_offsets)
                if not vertices:
                    continue
                self.hatch_view_edit_region_by_key[region.region_key] = region
                display.append((region.region_key, region, vertices))
        return display

    def _hatch_edit_regions_for_display_selection(self, story_offsets: dict[str, tuple[float, float]] | None = None):
        from dataclasses import replace as _replace

        return [
            _replace(region, polygon_xy=tuple(vertices))
            for _key, region, vertices in self._hatch_view_display_edit_regions(story_offsets)
        ]

    def _dummy_member_display_points(
        self,
        member: DummyDisplayMember,
        story_offsets: dict[str, tuple[float, float]] | None = None,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        story_filter = self._hatch_view_story_filter()
        if story_filter and str(member.story_name) != str(story_filter):
            return None
        points = (tuple(member.start_xy), tuple(member.end_xy))
        if self._hatch_view_is_all_story_display():
            display_transform = self._hatch_all_story_transform_for_story(str(member.story_name), story_offsets or {})
            return (display_transform.apply(*points[0]), display_transform.apply(*points[1]))
        return points

    def _dummy_display_members(self, phase: str = "all") -> tuple[DummyDisplayMember, ...]:
        members: list[DummyDisplayMember] = []
        if phase in {"all", "committed"}:
            members.extend((self.__dict__.get("committed_dummy_members", {}) or {}).values())
        if phase in {"all", "pending"}:
            for plan in (self.__dict__.get("approved_dummy_plans", {}) or {}).values():
                state = "INVALID" if str(plan.collision_reason or "") else "APPROVED_PENDING"
                members.append(
                    DummyDisplayMember(
                        display_key=f"approved:{plan.issue_key}",
                        story_name=plan.story_name,
                        node_i=plan.free_node_id,
                        node_j=plan.boundary_node_id,
                        start_xy=plan.start_xy,
                        end_xy=plan.end_xy,
                        state=state,
                        source="USER_APPROVED_PLAN",
                        issue_key=plan.issue_key,
                        invalid_reason=plan.collision_reason,
                    )
                )
            plan = self.__dict__.get("dummy_preview_plan")
            if plan is not None:
                members.append(
                    DummyDisplayMember(
                        display_key=f"preview:{plan.issue_key}",
                        story_name=plan.story_name,
                        node_i=plan.free_node_id,
                        node_j=plan.boundary_node_id,
                        start_xy=plan.start_xy,
                        end_xy=plan.end_xy,
                        state="INVALID" if str(plan.collision_reason or "") else "PREVIEW",
                        source="USER_APPROVED_PLAN",
                        issue_key=plan.issue_key,
                        invalid_reason=plan.collision_reason,
                    )
                )
        return tuple(members)

    def _dummy_overlay_fingerprint(self, phase: str = "all") -> tuple[object, ...]:
        return tuple(
            sorted(
                (
                    member.display_key,
                    member.story_name,
                    member.state,
                    member.element_id,
                    tuple(round(float(value), 9) for value in (*member.start_xy, *member.end_xy)),
                )
                for member in self._dummy_display_members(phase)
            )
        )

    def _draw_dummy_member_overlay(self, canvas, transform, story_offsets=None, *, phase: str = "all", members_override=None) -> None:
        styles = {
            "PREVIEW": {"fill": "#f97316", "width": 2, "dash": (7, 4)},
            "APPROVED_PENDING": {"fill": "#7c3aed", "width": 4, "dash": (10, 3)},
            "COMMITTED_EXISTING": {"fill": "#0f766e", "width": 4, "dash": ()},
            "COMMITTED_NEW": {"fill": "#047857", "width": 4, "dash": ()},
            "INVALID": {"fill": "#dc2626", "width": 3, "dash": (4, 3)},
        }
        for member in tuple(self._dummy_display_members(phase) if members_override is None else members_override):
            points = self._dummy_member_display_points(member, story_offsets)
            if points is None:
                continue
            (x1, y1), (x2, y2) = points
            tx1, ty1 = transform(float(x1), float(y1))
            tx2, ty2 = transform(float(x2), float(y2))
            style = styles.get(str(member.state), styles["INVALID"])
            tags = (
                "dummy_member",
                f"dummy_member:{member.display_key}",
                f"dummy_state:{member.state}",
                f"dummy_source:{member.source}",
            )
            options = {"fill": style["fill"], "width": style["width"], "tags": tags}
            if style["dash"]:
                options["dash"] = style["dash"]
            line_id = canvas.create_line(tx1, ty1, tx2, ty2, **options)
            radius = 4 if member.state == "PREVIEW" else 5
            first_id = canvas.create_oval(tx1 - radius, ty1 - radius, tx1 + radius, ty1 + radius, outline=style["fill"], fill="#ffffff", width=2, tags=tags)
            second_id = canvas.create_oval(tx2 - radius, ty2 - radius, tx2 + radius, ty2 + radius, outline=style["fill"], fill="#ffffff", width=2, tags=tags)
            self.dummy_member_canvas_items[member.display_key] = (line_id, first_id, second_id)

    def _draw_dummy_issue_overlay(self, canvas, transform, story_offsets=None) -> None:
        self.dummy_issue_canvas_items = {}
        story_filter = self._hatch_view_story_filter()
        for key, issue in (self.__dict__.get("dummy_issue_by_key", {}) or {}).items():
            if story_filter and str(issue.story_name) != str(story_filter):
                continue
            x, y = issue.xy
            if self._hatch_view_is_all_story_display():
                display_transform = self._hatch_all_story_transform_for_story(str(issue.story_name), story_offsets or {})
                x, y = display_transform.apply(float(x), float(y))
            tx, ty = transform(float(x), float(y))
            pending = str(issue.status) == "RESOLVED_PENDING"
            color = "#7c3aed" if pending else "#dc2626"
            tags = ("dummy_issue", f"dummy_issue:{key}")
            halo = canvas.create_oval(tx - 11, ty - 11, tx + 11, ty + 11, outline=color, fill="#fee2e2", stipple="gray50", width=1, tags=tags)
            first = canvas.create_line(tx - 7, ty - 7, tx + 7, ty + 7, fill=color, width=3, tags=tags)
            second = canvas.create_line(tx - 7, ty + 7, tx + 7, ty - 7, fill=color, width=3, tags=tags)
            self.dummy_issue_canvas_items[str(key)] = (halo, first, second)

    def _clear_dummy_member_overlay(self) -> None:
        canvas = self.__dict__.get("hatch_preview_canvas")
        if canvas is not None:
            for item_ids in tuple((self.__dict__.get("dummy_member_canvas_items", {}) or {}).values()):
                for item_id in tuple(item_ids or ()):
                    try:
                        canvas.delete(item_id)
                    except Exception:
                        pass
        self.dummy_member_canvas_items = {}
        self.dummy_overlay_member_fingerprint_by_key = {}

    def _update_dummy_member_overlay(self) -> None:
        canvas = self.__dict__.get("hatch_preview_canvas")
        transform = self.__dict__.get("_dummy_last_render_transform")
        if canvas is None or transform is None:
            return
        fingerprint = self._dummy_overlay_fingerprint("all")
        if fingerprint == self.__dict__.get("dummy_overlay_render_fingerprint"):
            return
        story_offsets = self.__dict__.get("_dummy_last_story_offsets", {})
        desired_members = {
            member.display_key: member
            for member in self._dummy_display_members("all")
            if self._dummy_member_display_points(member, story_offsets) is not None
        }
        desired_fingerprints = {
            key: (
                member.story_name,
                member.state,
                member.element_id,
                member.source,
                tuple(round(float(value), 9) for value in (*member.start_xy, *member.end_xy)),
            )
            for key, member in desired_members.items()
        }
        previous_fingerprints = self.__dict__.get("dummy_overlay_member_fingerprint_by_key", {}) or {}
        changed_keys = {
            key
            for key in set(previous_fingerprints).union(desired_fingerprints)
            if previous_fingerprints.get(key) != desired_fingerprints.get(key)
        }
        for key in changed_keys:
            for item_id in tuple((self.__dict__.get("dummy_member_canvas_items", {}) or {}).pop(key, ()) or ()):
                try:
                    canvas.delete(item_id)
                except Exception:
                    pass
        changed_members = [desired_members[key] for key in changed_keys if key in desired_members]
        self._draw_dummy_member_overlay(canvas, transform, story_offsets, phase="all", members_override=changed_members)
        self.dummy_overlay_member_fingerprint_by_key = desired_fingerprints
        for item_ids in tuple((self.__dict__.get("dummy_issue_canvas_items", {}) or {}).values()):
            for item_id in tuple(item_ids or ()):
                try:
                    canvas.delete(item_id)
                except Exception:
                    pass
        self._draw_dummy_issue_overlay(canvas, transform, story_offsets)
        try:
            canvas.tag_raise("dummy_member")
            canvas.tag_raise("dummy_issue")
            canvas.tag_raise("hatch_one_way_handle")
        except Exception:
            pass
        self.dummy_overlay_render_fingerprint = fingerprint

    def _refresh_dummy_issues_from_diagnostics(self, issues) -> None:
        supported_types = {
            "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD",
            "OPEN_BOUNDARY",
            "NO_CLOSED_REGION",
        }
        nodes = tuple(self.__dict__.get("nodes", ()) or ())
        node_by_id = {int(node.node_id): node for node in nodes}
        degree: Counter[int] = Counter()
        for element in tuple(self.__dict__.get("elements", ()) or ()):
            if str(getattr(element, "elem_type", "") or "").upper() in HATCH_VIEW_STRUCTURE_EXCLUDED_TYPES:
                continue
            for node_id in tuple(getattr(element, "node_ids", ()) or ()):
                degree[int(node_id)] += 1
        story_elevation = {str(story.name): float(story.elevation) for story in tuple(self.__dict__.get("stories", ()) or ())}
        result: dict[str, DummyIssueViewModel] = {}
        for index, issue in enumerate(tuple(issues or ()), start=1):
            issue_type = str(getattr(issue, "issue_type", "") or "").upper()
            if issue_type not in supported_types and "FLOORLOAD" not in issue_type:
                continue
            story_name = str(getattr(issue, "story_name", "") or "")
            node_ids = tuple(int(value) for value in tuple(getattr(issue, "node_ids", ()) or ()) if int(value) in node_by_id)
            free_node_id = node_ids[0] if node_ids else None
            free_node = node_by_id.get(free_node_id) if free_node_id is not None else None
            candidates: list[int] = []
            if free_node is not None and issue_type == "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD":
                elevation = story_elevation.get(story_name, float(free_node.z))
                candidates = [
                    int(node.node_id)
                    for node in nodes
                    if int(node.node_id) != int(free_node.node_id)
                    and degree[int(node.node_id)] > 0
                    and abs(float(node.z) - elevation) <= self._model_story_tolerance()
                ]
                candidates.sort(key=lambda node_id: (math.hypot(node_by_id[node_id].x - free_node.x, node_by_id[node_id].y - free_node.y), node_id))
            key = f"{story_name}:{issue_type}:{free_node_id or 0}:{index}"
            previous = (self.__dict__.get("dummy_issue_by_key", {}) or {}).get(key)
            result[key] = DummyIssueViewModel(
                issue_key=key,
                story_name=story_name,
                issue_type=issue_type,
                free_node_id=free_node_id,
                source_element_ids=tuple(int(value) for value in tuple(getattr(issue, "element_ids", ()) or ())),
                region_id="",
                xy=(float(getattr(issue, "x", 0.0)), float(getattr(issue, "y", 0.0))),
                candidate_boundary_nodes=tuple(candidates[:20]),
                recommended_boundary_node=candidates[0] if candidates else None,
                status=str(getattr(previous, "status", "OPEN") or "OPEN"),
                reason_ko=str(getattr(issue, "message", "") or ""),
                can_generate=bool(candidates and free_node_id is not None),
            )
        self.dummy_issue_by_key = result
        if self.__dict__.get("selected_dummy_issue_key") not in result:
            self._clear_dummy_issue_selection(update_overlay=False)
        self.dummy_overlay_render_fingerprint = None

    def _commit_dummy_generation_summary(self, summary) -> None:
        created_ids = {
            int(record.dummy_element_id)
            for record in tuple(getattr(summary, "records", ()) or ())
            if str(getattr(record, "status", "")) == "CREATED" and getattr(record, "dummy_element_id", None) is not None
        }
        committed = {}
        for member in parse_existing_load_dm_members(str(getattr(summary, "patched_text", "") or "")):
            committed[member.element_id] = DummyDisplayMember(
                display_key=f"element:{member.element_id}",
                story_name=member.story_name,
                node_i=member.node_i,
                node_j=member.node_j,
                start_xy=member.start_xy,
                end_xy=member.end_xy,
                element_id=member.element_id,
                state="COMMITTED_NEW" if member.element_id in created_ids else ("INVALID" if member.warnings else "COMMITTED_EXISTING"),
                source="GENERATED_PATCH" if member.element_id in created_ids else "CURRENT_MGT",
                material_id=member.material_id,
                section_id=member.section_id,
                release_added=member.release is not None,
                invalid_reason="; ".join(member.warnings),
            )
        self.committed_dummy_members = committed
        for record in tuple(getattr(summary, "records", ()) or ()):
            region_id = str(getattr(record, "region_id", "") or "")
            if str(getattr(record, "status", "")) == "CREATED":
                self.approved_dummy_plans.pop(region_id, None)
                issue = (self.__dict__.get("dummy_issue_by_key", {}) or {}).get(region_id)
                if issue is not None:
                    self.dummy_issue_by_key[region_id] = replace(issue, status="RESOLVED_COMMITTED")
        self.dummy_preview_plan = None
        self._invalidate_dummy_virtual_boundaries("LOAD DM 최종 생성")
        self._update_dummy_action_buttons()
        self.dummy_status_var.set(f"LOAD DM 생성 완료: {len(created_ids)}개")

    def _render_hatch_preview(self, *, focus_region_key: str | None = None) -> None:
        self._cancel_scheduled_hatch_preview_render()
        canvas = getattr(self, "hatch_preview_canvas", None)
        if canvas is None:
            return
        winfo_exists = getattr(canvas, "winfo_exists", None)
        if callable(winfo_exists) and not winfo_exists():
            return
        perf_token = self._hatch_perf_start("_render_hatch_preview")
        canvas.delete("all")
        self.hatch_view_region_items = {}
        self.hatch_view_checkbox_items = {}
        self.hatch_view_region_by_key = {}
        self.hatch_view_edit_region_items = {}
        self.hatch_view_edit_checkbox_items = {}
        self.dummy_member_canvas_items = {}
        self.dummy_issue_canvas_items = {}
        self.dummy_overlay_member_fingerprint_by_key = {}
        self._hatch_structure_status_message = ""
        width = max(int(canvas.winfo_width() or 0), 320)
        height = max(int(canvas.winfo_height() or 0), 480)
        regions = list(getattr(self, "loaded_regions", []) or [])
        display_mode = self._hatch_view_display_mode()
        story_filter = self._hatch_view_story_filter()
        story_offsets = self._hatch_story_display_offsets(regions)
        edit_display_regions = self._hatch_view_display_edit_regions(story_offsets)
        dummy_points = [
            points
            for member in self._dummy_display_members("all")
            for points in [self._dummy_member_display_points(member, story_offsets)]
            if points is not None
        ]
        has_dummy_overlay = bool(dummy_points or self.__dict__.get("dummy_issue_by_key"))
        has_layout_metadata = bool(self.__dict__.get("generated_dxf_layout_metadata"))
        if not regions and not edit_display_regions and not has_layout_metadata and not has_dummy_overlay:
            self.hatch_view_fit_bbox = None
            self.hatch_view_view_bbox = None
            self.hatch_view_manual_zoom = False
            canvas.configure(scrollregion=(0, 0, width, height))
            canvas.create_text(width / 2, height / 2, text="표시할 해치 또는 폐합 후보 영역이 없습니다.", fill="#666666")
            self._set_hatch_preview_info_message("모델을 불러오면 HATCH VIEW에서 폐합 후보 영역을 자동 생성합니다.")
            self._hatch_perf_end(
                perf_token,
                story_name=story_filter,
                display_mode=display_mode,
                visible_region_count=0,
                structure_item_count=0,
                candidate_target_count=0,
                cache_hit=0,
                cache_miss=0,
            )
            return
        if regions and not self.continuous_hatch_checks:
            self._recompute_hatch_continuous_checks(regions=regions)
        full_plan_var = self.__dict__.get("hatch_view_show_full_plan_var")
        full_plan = bool(full_plan_var.get()) if full_plan_var is not None else False
        _ = focus_region_key
        display_regions = []
        for index, region in enumerate(regions, start=1):
            region_key = self._region_key(region, index=index)
            self.hatch_view_region_by_key[region_key] = region
            if story_filter and str(getattr(getattr(region, "region", None), "story_name", "") or "") != story_filter:
                continue
            vertices = self._region_display_vertices(region, story_offsets)
            if not vertices:
                continue
            display_regions.append((region_key, region, vertices))
        structure_items = []
        show_structure_var = self.__dict__.get("hatch_view_show_structure_var")
        show_structure = True if show_structure_var is None else bool(show_structure_var.get())
        if show_structure:
            structure_items = self._structure_preview_items_for_hatch_view(display_regions, story_offsets)
        story_label_items = self._hatch_view_story_label_items(display_regions, edit_display_regions, structure_items)
        fit_bbox = self._hatch_preview_focus_bbox(display_regions, structure_items)
        if self._hatch_view_is_all_story_display():
            for layout in tuple(self.__dict__.get("generated_dxf_layout_metadata") or ()):
                fit_bbox = self._diagnostic_merge_bbox(fit_bbox, self._bbox_tuple_from_layout(getattr(layout, "placed_bbox", None)))
        for _region_key, _region, vertices in edit_display_regions:
            fit_bbox = self._diagnostic_merge_bbox(fit_bbox, self._bbox_from_points_for_preview(vertices))
        for label_item in story_label_items:
            fit_bbox = self._diagnostic_merge_bbox(fit_bbox, tuple(label_item.get("bbox", ()) or ()) or None)
        for points in dummy_points:
            fit_bbox = self._diagnostic_merge_bbox(fit_bbox, self._bbox_from_points_for_preview(points))
        for issue in (self.__dict__.get("dummy_issue_by_key", {}) or {}).values():
            point = DummyDisplayMember("issue", issue.story_name, 0, 0, issue.xy, issue.xy)
            display_points = self._dummy_member_display_points(point, story_offsets)
            if display_points is not None:
                fit_bbox = self._diagnostic_merge_bbox(fit_bbox, self._bbox_from_points_for_preview(display_points))
        if structure_items and fit_bbox is not None and not full_plan:
            structure_items = self._filter_structure_items_near_bbox(structure_items, fit_bbox, margin_ratio=0.50)
        if fit_bbox is None:
            canvas.configure(scrollregion=(0, 0, width, height))
            canvas.create_text(width / 2, height / 2, text="표시할 해치 좌표가 없습니다.", fill="#666666")
            self._hatch_perf_end(
                perf_token,
                story_name=story_filter,
                display_mode=self._hatch_view_display_mode(),
                visible_region_count=0,
                structure_item_count=len(structure_items),
                candidate_target_count=0,
                cache_hit=0,
                cache_miss=0,
            )
            return
        fit_bbox = self._hatch_view_bbox_for_canvas(fit_bbox, width, height)
        self._set_hatch_view_fit_bbox(fit_bbox)
        view_bbox = self.__dict__.get("hatch_view_view_bbox") or fit_bbox
        transform, content_width, content_height = self._hatch_canvas_transform(view_bbox, width, height)
        self._dummy_last_render_transform = transform
        self._dummy_last_story_offsets = dict(story_offsets)
        canvas.configure(scrollregion=(0, 0, content_width, content_height))
        viewport_bbox = self._expand_bbox(view_bbox, ratio=0.02)
        simplify_tolerance = self._hatch_display_simplify_tolerance(view_bbox, width, height)
        visible_display_regions = [
            (region_key, region, vertices)
            for region_key, region, vertices in display_regions
            if self._hatch_points_intersect_viewport(vertices, viewport_bbox)
        ]
        visible_edit_display_regions = [
            (region_key, region, vertices)
            for region_key, region, vertices in edit_display_regions
            if self._hatch_points_intersect_viewport(vertices, viewport_bbox)
        ]
        visible_unloaded_edit_display_regions = [
            item for item in visible_edit_display_regions if not str(getattr(item[1], "load_name", "") or "")
        ]
        visible_loaded_edit_display_regions = [
            item for item in visible_edit_display_regions if str(getattr(item[1], "load_name", "") or "")
        ]
        visible_structure_items = self._filter_structure_items_by_viewport(structure_items, viewport_bbox)
        visible_story_label_items = [
            item
            for item in story_label_items
            if self._bboxes_intersect(viewport_bbox, tuple(item.get("bbox", ()) or viewport_bbox))
        ]
        color_legend: dict[str, str] = {}
        background_structure_items, column_structure_items = self._split_structure_items_for_layering(visible_structure_items)
        self._draw_hatch_structure_items(canvas, background_structure_items, transform)
        self._draw_dummy_member_overlay(canvas, transform, story_offsets, phase="committed")
        self._draw_hatch_edit_regions(canvas, visible_unloaded_edit_display_regions, transform, color_legend, viewport_bbox=viewport_bbox, simplify_tolerance=simplify_tolerance)
        hover_key = str(self.__dict__.get("hatch_load_drag_hover_key") or "")
        selected_region_keys = set(self.__dict__.get("hatch_view_selected_region_keys", set()) or set())
        selected_single_key = str(self.__dict__.get("hatch_view_selected_region_key") or "")
        if selected_single_key:
            selected_region_keys.add(selected_single_key)
        for region_key, region, vertices in visible_display_regions:
            selected = region_key in selected_region_keys
            is_hover = bool(hover_key and region_key == hover_key and not selected)
            check = self.continuous_hatch_checks.get(region_key, {})
            can_select = bool(check.get("can_select"))
            fill = self._region_display_color(region)
            if self.hatch_view_highlight_continuous_var.get() and not can_select:
                fill = "#e5e7eb"
            legend_label = self._region_color_label(region)
            color_legend.setdefault(fill, legend_label)
            draw_vertices = self._simplify_hatch_display_vertices(vertices, simplify_tolerance)
            points = [coord for xy in draw_vertices for coord in transform(*xy)]
            polygon_options = {
                "outline": "#1a73e8" if selected else ("#fbbc04" if is_hover else "#374151"),
                "fill": fill,
                "width": 4 if selected or is_hover else 2,
                "joinstyle": tk.ROUND,
                "stipple": "" if is_hover or can_select or not self.hatch_view_highlight_continuous_var.get() else "gray25",
                "tags": ("hatch_region", f"region:{region_key}"),
            }
            if is_hover:
                polygon_options["dash"] = (4, 2)
            item = canvas.create_polygon(points, **polygon_options)
            self.hatch_view_region_items[region_key] = item
            load = getattr(region, "load", None)
            if self._is_one_way_distribution(getattr(load, "distribution", "")):
                angle = getattr(load, "one_way_angle_deg", None)
                if angle in (None, ""):
                    angle = self._one_way_angle_from_vertices(self._dxf_region_polygon_vertices_for_one_way(region_key))
                if angle is not None:
                    self._draw_one_way_direction_handles(canvas, region_key, vertices, float(angle), transform, source="dxf")
            cx, cy = self._polygon_centroid(vertices)
            tx, ty = transform(cx, cy)
            half_size, font_size, show_text = self._hatch_checkbox_canvas_metrics(vertices, transform)
            marker_width = max(1, int(round(_clamp(half_size * 0.25, 1.0, 2.0))))
            marker_outline = "#1a73e8" if can_select else "#9ca3af"
            marker_fill = "#ffffff" if can_select else "#f3f4f6"
            marker_text = "V" if selected else ("" if can_select else "i")
            if not show_text:
                marker_text = ""
            box_id = canvas.create_rectangle(
                tx - half_size,
                ty - half_size,
                tx + half_size,
                ty + half_size,
                outline=marker_outline,
                fill=marker_fill,
                width=marker_width,
                tags=("hatch_check", f"region:{region_key}"),
            )
            text_id = canvas.create_text(
                tx,
                ty,
                text=marker_text,
                fill="#1a73e8" if selected or can_select else "#6b7280",
                font=("TkDefaultFont", font_size, "bold"),
                tags=("hatch_check", f"region:{region_key}"),
            )
            self.hatch_view_checkbox_items[region_key] = (box_id, text_id)
        self._draw_hatch_edit_regions(
            canvas,
            visible_loaded_edit_display_regions,
            transform,
            color_legend,
            viewport_bbox=viewport_bbox,
            simplify_tolerance=simplify_tolerance,
        )
        self._draw_hatch_story_labels(canvas, visible_story_label_items, transform)
        self._draw_hatch_structure_items(canvas, column_structure_items, transform)
        self._draw_dummy_member_overlay(canvas, transform, story_offsets, phase="pending")
        self._draw_dummy_issue_overlay(canvas, transform, story_offsets)
        self.dummy_overlay_render_fingerprint = self._dummy_overlay_fingerprint("all")
        self.dummy_overlay_member_fingerprint_by_key = {
            member.display_key: (
                member.story_name,
                member.state,
                member.element_id,
                member.source,
                tuple(round(float(value), 9) for value in (*member.start_xy, *member.end_xy)),
            )
            for member in self._dummy_display_members("all")
            if self._dummy_member_display_points(member, story_offsets) is not None
        }
        try:
            canvas.tag_bind("hatch_one_way_handle", "<Button-1>", self._on_one_way_handle_click)
            canvas.tag_bind("hatch_one_way_handle", "<Double-Button-1>", self._on_one_way_handle_double_click)
            canvas.tag_raise("structure:COLUMN")
            canvas.tag_raise("structure_marker")
            canvas.tag_raise("dummy_member")
            canvas.tag_raise("dummy_issue")
            canvas.tag_raise("hatch_one_way_handle")
        except Exception:
            pass
        self._draw_hatch_legend(canvas, color_legend, content_width)
        structure_status = str(self.__dict__.get("_hatch_structure_status_message") or "")
        self._set_hatch_preview_info_message(structure_status or self._hatch_preview_info_text())
        if hasattr(self, "hatch_preview_legend_var"):
            self.hatch_preview_legend_var.set(f"표시 해치 {len(visible_display_regions)}개 / 폐합 후보 {len(visible_edit_display_regions)}개")
        self._hatch_perf_end(
            perf_token,
            story_name=story_filter,
            display_mode=self._hatch_view_display_mode(),
            visible_region_count=len(visible_display_regions) + len(visible_edit_display_regions),
            structure_item_count=len(visible_structure_items),
            candidate_target_count=len(tuple(self.__dict__.get("continuous_active_visible_targets", ()) or ())),
            cache_hit=int(self.__dict__.get("_continuous_load_conflict_reason_cache_hits", 0) or 0),
            cache_miss=int(self.__dict__.get("_continuous_load_conflict_reason_cache_misses", 0) or 0),
            culled_region_count=(len(display_regions) - len(visible_display_regions)) + (len(edit_display_regions) - len(visible_edit_display_regions)),
            culled_structure_item_count=len(structure_items) - len(visible_structure_items),
        )

    def _hatch_checkbox_canvas_half_size(self, vertices, transform) -> float:
        return self._hatch_checkbox_canvas_metrics(vertices, transform)[0]

    def _hatch_checkbox_canvas_metrics(self, vertices, transform) -> tuple[float, int, bool]:
        is_all_story = self._hatch_view_is_all_story_display()
        default_half_size = 5.0 if is_all_story else 8.0
        canvas_points: list[tuple[float, float]] = []
        for x, y in tuple(vertices or ()):
            try:
                tx, ty = transform(float(x), float(y))
            except Exception:
                continue
            canvas_points.append((float(tx), float(ty)))
        if canvas_points:
            xs = [x for x, _y in canvas_points]
            ys = [y for _x, y in canvas_points]
            short_px = max(min(max(xs) - min(xs), max(ys) - min(ys)), 0.0)
            if is_all_story:
                half_size = _clamp(short_px * 0.08, 2.5, 8.0)
            else:
                half_size = _clamp(short_px * 0.10, 5.0, 10.0)
        else:
            half_size = default_half_size
        font_size = int(_clamp(half_size * 1.25, 6.0, 12.0))
        show_text = half_size >= 4.0
        return (half_size, font_size, show_text)

    def _hatch_story_label_candidate_height(self, story_bbox) -> float:
        min_x, min_y, max_x, max_y = [float(value) for value in story_bbox]
        _ = min_x, max_x
        story_height = max(max_y - min_y, 1.0)
        text_height = _clamp(story_height * 0.16, story_height * 0.07, story_height * 0.32)
        return _clamp(text_height, 1.0, max(story_height * 0.35, 1.0))

    def _common_hatch_story_label_height(self, story_bboxes: dict[str, tuple[float, float, float, float]]) -> float:
        heights = [self._hatch_story_label_candidate_height(bbox) for bbox in story_bboxes.values()]
        return max(heights) if heights else 1.0

    def _hatch_view_story_label_items(self, display_regions, edit_display_regions, structure_items) -> list[dict]:
        _ = structure_items
        if self._hatch_view_story_filter():
            return []
        if self._hatch_view_display_mode() != "ALL":
            return []
        story_bboxes: dict[str, tuple[float, float, float, float]] = {}
        for layout in tuple(self.__dict__.get("generated_dxf_layout_metadata") or ()):
            story_name = str(getattr(layout, "story_name", "") or "")
            bbox = self._bbox_tuple_from_layout(getattr(layout, "placed_bbox", None))
            if story_name and bbox is not None:
                story_bboxes[story_name] = self._diagnostic_merge_bbox(story_bboxes.get(story_name), bbox)
        for _region_key, region, vertices in display_regions:
            story_name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
            bbox = self._bbox_from_points_for_preview(vertices)
            if story_name and bbox is not None:
                story_bboxes[story_name] = self._diagnostic_merge_bbox(story_bboxes.get(story_name), bbox)
        for _region_key, region, vertices in edit_display_regions:
            story_name = str(getattr(region, "story_name", "") or "")
            bbox = self._bbox_from_points_for_preview(vertices)
            if story_name and bbox is not None:
                story_bboxes[story_name] = self._diagnostic_merge_bbox(story_bboxes.get(story_name), bbox)
        if not story_bboxes:
            return []
        story_order = list(tuple(self.__dict__.get("generated_dxf_story_names") or ()) or tuple(story.name for story in self.__dict__.get("stories", []) or ()))
        story_order.extend(name for name in story_bboxes if name not in story_order)
        common_text_height = self._common_hatch_story_label_height(story_bboxes)
        labels = []
        for story_name in story_order:
            bbox = story_bboxes.get(story_name)
            if bbox is None:
                continue
            min_x, min_y, max_x, max_y = [float(value) for value in bbox]
            story_width = max(max_x - min_x, 1.0)
            text_height = common_text_height
            text = self._hatch_story_label_text(story_name)
            text_width = max(text_height * max(len(text), 2) * 0.62, story_width * 0.10)
            gap = max(story_width * 0.04, text_height * 1.3)
            x_right = min_x - gap
            y = (min_y + max_y) / 2.0
            story_bbox = (min_x, min_y, max_x, max_y)
            label_bbox = (x_right - text_width, y - text_height * 0.65, x_right, y + text_height * 0.65)
            for _attempt in range(10):
                if not self._bboxes_intersect(label_bbox, story_bbox) and label_bbox[2] <= min_x - gap * 0.5:
                    break
                x_right -= text_height
                label_bbox = (x_right - text_width, y - text_height * 0.65, x_right, y + text_height * 0.65)
            labels.append(
                {
                    "story_name": story_name,
                    "text": text,
                    "position": (x_right, y),
                    "height": text_height,
                    "story_bbox": story_bbox,
                    "bbox": label_bbox,
                }
            )
        return labels

    def _bbox_tuple_from_layout(self, bbox) -> tuple[float, float, float, float] | None:
        if bbox is None:
            return None
        try:
            return (float(bbox.min_x), float(bbox.min_y), float(bbox.max_x), float(bbox.max_y))
        except Exception:
            pass
        try:
            values = tuple(float(value) for value in bbox)
        except Exception:
            return None
        return values[:4] if len(values) >= 4 else None

    def _hatch_story_label_text(self, story_name: str) -> str:
        name = str(story_name or "")
        if name and name in set(typical_story_names(self.__dict__.get("typical_floor_groups", ()) or ())):
            return f"typ. {name}"
        return name

    def _draw_hatch_story_labels(self, canvas, label_items, transform) -> None:
        if not label_items or not hasattr(canvas, "create_text"):
            return
        for item in label_items:
            x, y = item.get("position", (0.0, 0.0))
            height = float(item.get("height", 1.0) or 1.0)
            tx, ty = transform(float(x), float(y))
            _tx2, ty2 = transform(float(x), float(y) + height)
            font_size = int(_clamp(abs(ty2 - ty), 12, 56))
            canvas.create_text(
                tx,
                ty,
                text=str(item.get("text", "") or ""),
                anchor="e",
                fill="#111827",
                font=("TkDefaultFont", font_size, "bold"),
                tags=("hatch_story_label", f"story_label:{item.get('story_name', '')}"),
            )

    def _region_vertices(self, region) -> list[tuple[float, float]]:
        if region is None:
            return []
        raw = getattr(getattr(region, "region", None), "vertices", ()) or ()
        return [(float(x), float(y)) for x, y in raw]

    def _region_display_vertices(self, region, story_offsets: dict[str, tuple[float, float]]) -> list[tuple[float, float]]:
        hatch = getattr(region, "region", None)
        if hatch is None:
            return []
        model_points = [(float(x), float(y)) for x, y in tuple(getattr(hatch, "vertices", ()) or ())]
        if not model_points:
            polygon = getattr(hatch, "polygon", None)
            try:
                coords = list(polygon.exterior.coords) if getattr(polygon, "geom_type", "") == "Polygon" else []
                if len(coords) > 1 and coords[0] == coords[-1]:
                    coords = coords[:-1]
                model_points = [(float(x), float(y)) for x, y in coords]
            except Exception:
                model_points = []
        placed_points = [(float(x), float(y)) for x, y in tuple(getattr(hatch, "placed_vertices", ()) or ())]
        story_name = str(getattr(hatch, "story_name", "") or "")
        if self._hatch_view_is_all_story_display():
            if placed_points:
                return placed_points
            display_transform = self._hatch_all_story_transform_for_story(story_name, story_offsets)
            return [display_transform.apply(x, y) for x, y in model_points]
        return model_points

    def _hatch_preview_focus_bbox(self, display_regions, structure_items) -> tuple[float, float, float, float] | None:
        full_plan_var = self.__dict__.get("hatch_view_show_full_plan_var")
        full_plan = bool(full_plan_var.get()) if full_plan_var is not None else False
        bbox = None
        for _region_key, _region, vertices in display_regions:
            bbox = self._diagnostic_merge_bbox(bbox, self._bbox_from_points_for_preview(vertices))
        if full_plan:
            for item in structure_items or ():
                bbox = self._diagnostic_merge_bbox(bbox, self._bbox_from_points_for_preview(item.get("points", ())))
            return self._expand_bbox(bbox, ratio=0.08) if bbox else None
        return self._expand_bbox(bbox, ratio=0.12) if bbox else None

    def _hatch_view_bbox_for_canvas(self, bbox, width: int, height: int, *, margin_ratio: float = 0.08) -> tuple[float, float, float, float]:
        min_x, min_y, max_x, max_y = self._normalized_hatch_bbox(bbox)
        span = max(max_x - min_x, max_y - min_y, 1.0e-9)
        pad = span * _clamp(float(margin_ratio), 0.0, 0.12)
        min_x -= pad
        min_y -= pad
        max_x += pad
        max_y += pad
        model_width = max(max_x - min_x, 1.0e-9)
        model_height = max(max_y - min_y, 1.0e-9)
        canvas_aspect = max(float(width), 1.0) / max(float(height), 1.0)
        model_aspect = model_width / model_height
        if model_aspect > canvas_aspect:
            target_height = model_width / canvas_aspect
            extra = (target_height - model_height) / 2.0
            min_y -= extra
            max_y += extra
        else:
            target_width = model_height * canvas_aspect
            extra = (target_width - model_width) / 2.0
            min_x -= extra
            max_x += extra
        return (min_x, min_y, max_x, max_y)

    def _set_hatch_view_fit_bbox(self, bbox) -> None:
        fit_bbox = self._normalized_hatch_bbox(bbox)
        self.hatch_view_fit_bbox = fit_bbox
        if bool(self.__dict__.get("hatch_view_manual_zoom", False)):
            return
        self.hatch_view_view_bbox = fit_bbox
        self.hatch_view_manual_zoom = False

    def _reset_hatch_view_zoom(self) -> None:
        fit_bbox = self.__dict__.get("hatch_view_fit_bbox")
        if fit_bbox is not None:
            self.hatch_view_view_bbox = fit_bbox
        self.hatch_view_manual_zoom = False

    def _normalized_hatch_bbox(self, bbox) -> tuple[float, float, float, float]:
        min_x, min_y, max_x, max_y = [float(value) for value in bbox]
        if max_x - min_x <= 1.0e-9:
            min_x -= 0.5
            max_x += 0.5
        if max_y - min_y <= 1.0e-9:
            min_y -= 0.5
            max_y += 0.5
        return (min_x, min_y, max_x, max_y)

    def _hatch_bboxes_close(self, first, second, *, rel_tol: float = 1.0e-6, abs_tol: float = 1.0e-6) -> bool:
        return all(math.isclose(float(a), float(b), rel_tol=rel_tol, abs_tol=abs_tol) for a, b in zip(first, second))

    def _filter_structure_items_near_bbox(self, items, bbox, *, margin_ratio: float = 0.50) -> list[dict]:
        if bbox is None:
            return list(items or [])
        expanded = self._expand_bbox(bbox, ratio=margin_ratio)
        filtered = []
        for item in items or []:
            item_bbox = self._bbox_from_points_for_preview(item.get("points", ()))
            if item_bbox and self._bboxes_intersect(expanded, item_bbox):
                filtered.append(item)
        return filtered or list(items or [])

    def _filter_structure_items_by_viewport(self, items, viewport_bbox) -> list[dict]:
        if viewport_bbox is None:
            return list(items or [])
        return [
            item
            for item in tuple(items or ())
            if self._hatch_points_intersect_viewport(item.get("points", ()), viewport_bbox)
        ]

    def _hatch_points_intersect_viewport(self, points, viewport_bbox) -> bool:
        if viewport_bbox is None:
            return True
        bbox = self._bbox_from_points_for_preview(points)
        if bbox is None:
            return False
        return self._bboxes_intersect(viewport_bbox, bbox)

    def _hatch_display_simplify_tolerance(self, view_bbox, width: int, height: int) -> float:
        if view_bbox is None:
            return 0.0
        try:
            min_x, min_y, max_x, max_y = self._normalized_hatch_bbox(view_bbox)
            model_per_pixel = max((max_x - min_x) / max(float(width), 1.0), (max_y - min_y) / max(float(height), 1.0))
            return max(model_per_pixel * 0.75, 0.0)
        except Exception:
            return 0.0

    def _simplify_hatch_display_vertices(self, vertices, tolerance: float):
        points = tuple((float(x), float(y)) for x, y in tuple(vertices or ()))
        if len(points) < 8 or float(tolerance) <= 0.0:
            return list(points)
        try:
            from shapely.geometry import Polygon

            polygon = Polygon(points)
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            simplified = polygon.simplify(float(tolerance), preserve_topology=True)
            if getattr(simplified, "geom_type", "") != "Polygon" or simplified.is_empty:
                return list(points)
            simplified_points = self._polygon_exterior_xy(simplified)
            return list(simplified_points) if len(simplified_points) >= 3 else list(points)
        except Exception:
            return list(points)

    def _hatch_canvas_visible_bbox(self, canvas, *, padding_px: float = 32.0):
        try:
            width = max(float(canvas.winfo_width() or 0.0), 1.0)
            height = max(float(canvas.winfo_height() or 0.0), 1.0)
            canvasx = getattr(canvas, "canvasx", None)
            canvasy = getattr(canvas, "canvasy", None)
            left = float(canvasx(0.0)) if callable(canvasx) else 0.0
            top = float(canvasy(0.0)) if callable(canvasy) else 0.0
            pad = max(float(padding_px), 0.0)
            return (left - pad, top - pad, left + width + pad, top + height + pad)
        except Exception:
            return None

    def _split_structure_items_for_layering(self, structure_items) -> tuple[list[dict], list[dict]]:
        background_items = []
        column_items = []
        for item in tuple(structure_items or ()):
            copied = dict(item)
            if str(copied.get("kind", "") or "").upper() == "COLUMN":
                column_items.append(copied)
            else:
                background_items.append(copied)
        return background_items, column_items

    def _expand_bbox(self, bbox, *, ratio: float) -> tuple[float, float, float, float] | None:
        if bbox is None:
            return None
        min_x, min_y, max_x, max_y = [float(value) for value in bbox]
        span = max(max_x - min_x, max_y - min_y, 1.0e-9)
        pad = span * max(float(ratio), 0.0)
        return (min_x - pad, min_y - pad, max_x + pad, max_y + pad)

    def _bboxes_intersect(self, first, second) -> bool:
        return not (
            first[2] < second[0]
            or second[2] < first[0]
            or first[3] < second[1]
            or second[3] < first[1]
        )

    def _hatch_structure_story_name(self, display_regions) -> str:
        selected_key = str(self.__dict__.get("hatch_view_selected_region_key") or "")
        for region_key, region, _vertices in display_regions:
            if region_key == selected_key:
                return str(getattr(getattr(region, "region", None), "story_name", "") or "")
        full_plan_var = self.__dict__.get("hatch_view_show_full_plan_var")
        full_plan = bool(full_plan_var.get()) if full_plan_var is not None else False
        if full_plan:
            for _region_key, region, _vertices in display_regions:
                story_name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
                if story_name:
                    return story_name
        base_var = self.__dict__.get("continuous_base_story_name")
        try:
            base_story = str(base_var.get() or "") if base_var is not None else ""
        except Exception:
            base_story = ""
        if base_story:
            return base_story
        for _region_key, region, _vertices in display_regions:
            story_name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
            if story_name:
                return story_name
        return ""

    def _structure_preview_items_for_hatch_view(self, display_regions, story_offsets) -> list[dict]:
        perf_token = self._hatch_perf_start("_structure_preview_items_for_hatch_view")
        cache_hits_before = int(self.__dict__.get("_story_below_element_index_cache_hits", 0) or 0)
        cache_misses_before = int(self.__dict__.get("_story_below_element_index_cache_misses", 0) or 0)
        story_names = self._hatch_structure_story_names_for_display(display_regions)
        items: list[dict] = []
        for story_name in story_names:
            try:
                story_items = self._structure_preview_items_for_story(story_name)
                if self._hatch_view_is_all_story_display():
                    display_transform = self._hatch_display_transform_for_story(story_name, display_regions, story_offsets)
                    transformed = self._transform_structure_preview_items(story_items, display_transform)
                else:
                    transformed = story_items
                for item in transformed:
                    copied = dict(item)
                    copied["story_name"] = story_name
                    items.append(copied)
            except Exception as exc:  # noqa: BLE001 - preview failure must not block hatch selection
                logger = self.__dict__.get("logger")
                if logger is not None:
                    logger.warning("hatch structure preview failed for %s: %s", story_name, exc)
                self._set_hatch_structure_preview_status(f"구조요소 표시 실패: {story_name}")
        items = self._merge_collinear_structure_beam_items(items)
        self._hatch_perf_end(
            perf_token,
            story_name=",".join(story_names),
            display_mode=self._hatch_view_display_mode(),
            visible_region_count=len(tuple(display_regions or ())),
            structure_item_count=len(items),
            candidate_target_count=0,
            cache_hit=int(self.__dict__.get("_story_below_element_index_cache_hits", 0) or 0) - cache_hits_before,
            cache_miss=int(self.__dict__.get("_story_below_element_index_cache_misses", 0) or 0) - cache_misses_before,
        )
        return items

    def _hatch_structure_story_names_for_display(self, display_regions) -> tuple[str, ...]:
        story_filter = self._hatch_view_story_filter()
        if story_filter:
            return (story_filter,)
        if self._hatch_view_is_all_story_display():
            names = list(tuple(self.__dict__.get("generated_dxf_story_names") or ()))
            for name in self._layout_by_story().keys():
                if name and name not in names:
                    names.append(name)
            for _region_key, region, _vertices in display_regions:
                name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
                if name and name not in names:
                    names.append(name)
            return tuple(names)
        story_name = self._hatch_structure_story_name(display_regions)
        return (story_name,) if story_name else ()

    def _structure_preview_items_for_story(self, story_name: str) -> list[dict]:
        perf_token = self._hatch_perf_start("_structure_preview_items_for_story")
        story_name = str(story_name or "")
        if not story_name:
            self._set_hatch_structure_preview_status("구조요소 표시 기준 Story가 없습니다.")
            self._hatch_perf_end(perf_token, story_name=story_name, display_mode=self._hatch_view_display_mode(), visible_region_count=0, structure_item_count=0, candidate_target_count=0, cache_hit=0, cache_miss=0)
            return []
        story = self._story_by_name(story_name)
        if story is None:
            self._set_hatch_structure_preview_status(f"구조요소 표시 실패: {story_name} Story를 찾을 수 없습니다.")
            self._hatch_perf_end(perf_token, story_name=story_name, display_mode=self._hatch_view_display_mode(), visible_region_count=0, structure_item_count=0, candidate_target_count=0, cache_hit=0, cache_miss=0)
            return []
        try:
            preview_token = (
                self._story_below_element_index_cache_token(),
                self._current_mgt_text_signature(),
            )
        except Exception:
            stories = self.__dict__.get("stories", ()) or ()
            nodes = self.__dict__.get("nodes", ()) or ()
            elements = self.__dict__.get("elements", ()) or ()
            preview_token = (
                id(stories), len(stories), id(nodes), len(nodes), id(elements), len(elements),
                self._current_mgt_text_signature(),
            )
        if self.__dict__.get("_hatch_structure_preview_cache_token") != preview_token:
            self._hatch_structure_preview_cache_token = preview_token
            self._hatch_structure_preview_cache = {}
        preview_cache = self.__dict__.setdefault("_hatch_structure_preview_cache", {})
        if story_name in preview_cache:
            cached_items = tuple(preview_cache[story_name] or ())
            if any(bool(item.get("fallback_thickness")) for item in cached_items):
                self._set_hatch_structure_preview_status("벽체 단면 두께 정보 없음: 기본 표시 두께로 HATCH VIEW에만 표시합니다.")
            result = [dict(item) for item in cached_items]
            self._hatch_perf_end(
                perf_token,
                story_name=story_name,
                display_mode=self._hatch_view_display_mode(),
                visible_region_count=0,
                structure_item_count=len(result),
                candidate_target_count=0,
                cache_hit=1,
                cache_miss=0,
                input_element_count=0,
            )
            return result
        node_by_id = {node.node_id: node for node in list(getattr(self, "nodes", []) or [])}
        if not node_by_id:
            self._set_hatch_structure_preview_status("구조요소 표시 실패: 모델 node 정보가 없습니다.")
            self._hatch_perf_end(perf_token, story_name=story_name, display_mode=self._hatch_view_display_mode(), visible_region_count=0, structure_item_count=0, candidate_target_count=0, cache_hit=0, cache_miss=0)
            return []
        tolerance = self._model_story_tolerance()
        section_sizes = self._section_display_sizes_for_hatch_view()
        wall_thicknesses = self._wall_thicknesses_for_hatch_view()
        below_range = story_below_range(list(getattr(self, "stories", []) or [story]), story, tolerance)
        story_elements = self._story_below_elements_for_story(story_name)
        elements = list(story_elements or list(getattr(self, "elements", []) or []))
        story_node_ids = {
            node.node_id
            for node in node_by_id.values()
            if abs(float(getattr(node, "z", 0.0)) - float(story.elevation)) <= tolerance
        }
        items: list[dict] = []
        for element in elements:
            elem_type = str(getattr(element, "elem_type", "") or "").upper()
            if elem_type in HATCH_VIEW_STRUCTURE_EXCLUDED_TYPES:
                continue
            if not element_is_in_story_below_range(element, node_by_id, below_range, tolerance):
                continue
            if elem_type in HATCH_VIEW_STRUCTURE_PLANAR_WALL_TYPES:
                wall_edge = self._planar_wall_edge_points_for_story(element, node_by_id, float(story.elevation), tolerance, story_range=below_range)
                if len(wall_edge) >= 2:
                    for first, second in zip(wall_edge, wall_edge[1:]):
                        items.append(self._hatch_structure_item("WALL", [first, second], element, section_sizes, wall_thicknesses))
                continue
            points = [
                (float(node_by_id[node_id].x), float(node_by_id[node_id].y))
                for node_id in getattr(element, "node_ids", ()) or ()
                if node_id in story_node_ids and node_id in node_by_id
            ]
            if elem_type == "COLUMN":
                if points:
                    items.append(self._hatch_structure_item("COLUMN", [points[0]], element, section_sizes, wall_thicknesses))
                continue
            if elem_type in HATCH_VIEW_STRUCTURE_LINE_TYPES and len(points) >= 2:
                items.append(self._hatch_structure_item("BEAM", points[:2], element, section_sizes, wall_thicknesses))
                continue
            if elem_type in HATCH_VIEW_STRUCTURE_WALL_TYPES and len(points) >= 2:
                items.append(self._hatch_structure_item("WALL", points, element, section_sizes, wall_thicknesses))
                continue
        self._hatch_perf_end(
            perf_token,
            story_name=story_name,
            display_mode=self._hatch_view_display_mode(),
            visible_region_count=0,
            structure_item_count=len(items),
            candidate_target_count=0,
            cache_hit=int(bool(story_elements)),
            cache_miss=0 if story_elements else 1,
            input_element_count=len(elements),
        )
        preview_cache[story_name] = tuple(dict(item) for item in items)
        return [dict(item) for item in items]

    def _planar_wall_edge_points_for_story(self, element, node_by_id: dict[int, object], story_elevation: float, tolerance: float, story_range=None) -> list[tuple[float, float]]:
        node_ids = tuple(getattr(element, "node_ids", ()) or ())
        nodes = [node_by_id[node_id] for node_id in node_ids if node_id in node_by_id]
        if len(nodes) < 2:
            return []
        if story_range is None:
            stories = list(getattr(self, "stories", []) or ())
            fallback_story = next(
                (
                    item
                    for item in stories
                    if abs(float(getattr(item, "elevation", 0.0)) - float(story_elevation)) <= float(tolerance)
                ),
                Story("", float(story_elevation)),
            )
            below_range = story_below_range(stories or [fallback_story], fallback_story, tolerance)
        else:
            below_range = story_range
        if not element_is_in_story_below_range(element, node_by_id, below_range, tolerance):
            return []
        on_story = [
            abs(float(getattr(node, "z", 0.0)) - float(story_elevation)) <= float(tolerance)
            for node in nodes
        ]
        if all(on_story):
            return []
        story_nodes = [node for node, is_on_story in zip(nodes, on_story) if is_on_story]

        def unique_points(ordered_nodes) -> list[tuple[float, float]]:
            points: list[tuple[float, float]] = []
            seen: set[tuple[float, float]] = set()
            for node in ordered_nodes:
                point = (float(getattr(node, "x", 0.0)), float(getattr(node, "y", 0.0)))
                key = (round(point[0], 9), round(point[1], 9))
                if key in seen:
                    continue
                seen.add(key)
                points.append(point)
            return points

        all_story_points = unique_points(story_nodes)
        if len(all_story_points) < 2:
            return []
        runs: list[list[int]] = []
        current_run: list[int] = []
        for index, is_on_story in enumerate(on_story):
            if is_on_story:
                current_run.append(index)
            elif current_run:
                runs.append(current_run)
                current_run = []
        if current_run:
            runs.append(current_run)
        if len(runs) > 1 and on_story[0] and on_story[-1]:
            runs[0] = runs[-1] + runs[0]
            runs.pop()
        best_run = max(runs, key=len, default=[])
        ordered_points = unique_points(nodes[index] for index in best_run)
        if len(ordered_points) >= 2 and len(ordered_points) == len(all_story_points):
            return ordered_points

        best_pair: tuple[tuple[float, float], tuple[float, float]] | None = None
        best_distance = -1.0
        for index, first in enumerate(all_story_points[:-1]):
            for second in all_story_points[index + 1:]:
                distance = math.hypot(second[0] - first[0], second[1] - first[1])
                if distance > best_distance:
                    best_distance = distance
                    best_pair = (first, second)
        return list(best_pair or ())

    def _section_display_sizes_for_hatch_view(self) -> dict[int, object]:
        text = str(self.__dict__.get("current_mgt_text", "") or "")
        cache_key = "_hatch_section_display_sizes_cache"
        if not text:
            self.__dict__[cache_key] = (text, {})
            return {}
        cached = self.__dict__.get(cache_key)
        if cached and cached[0] == text:
            return cached[1]
        try:
            sizes = section_display_size_by_id_from_text(text)
        except Exception:
            sizes = {}
        self.__dict__[cache_key] = (text, sizes)
        return sizes

    def _wall_thicknesses_for_hatch_view(self) -> dict[int, float]:
        text = str(self.__dict__.get("current_mgt_text", "") or "")
        cache_key = "_hatch_wall_thicknesses_cache"
        if not text:
            self.__dict__[cache_key] = (text, {})
            return {}
        cached = self.__dict__.get(cache_key)
        if cached and cached[0] == text:
            return cached[1]
        try:
            thicknesses = thickness_value_by_id_from_text(text)
        except Exception:
            thicknesses = {}
        self.__dict__[cache_key] = (text, thicknesses)
        return thicknesses

    def _beam_plan_display_width(self, element, size) -> float | None:
        plan_width = getattr(size, "plan_width", None) if size is not None else None
        width_b = getattr(size, "width", None) if size is not None else None
        depth_h = getattr(size, "depth", None) if size is not None else None
        if width_b is None:
            width_b = plan_width
        if plan_width is not None and depth_h is None:
            try:
                return float(plan_width)
            except Exception:
                return None
        if width_b is None:
            return None
        try:
            b = float(width_b)
            h = float(depth_h) if depth_h is not None else b
        except Exception:
            try:
                return float(plan_width) if plan_width is not None else None
            except Exception:
                return None
        try:
            beta = float(getattr(element, "angle_deg", 0.0) or 0.0)
        except Exception:
            beta = 0.0
        beta_mod = abs(beta) % 180.0
        if math.isclose(beta_mod, 0.0, abs_tol=1.0e-6):
            return b
        if math.isclose(beta_mod, 90.0, abs_tol=1.0e-6):
            return h
        theta = math.radians(beta_mod)
        return abs(b * math.cos(theta)) + abs(h * math.sin(theta))

    def _hatch_structure_item(
        self,
        kind: str,
        points: list[tuple[float, float]],
        element,
        section_sizes: dict[int, object],
        wall_thicknesses: dict[int, float] | None = None,
    ) -> dict:
        section_id = getattr(element, "prop", None)
        try:
            section_id = int(section_id) if section_id is not None else None
        except Exception:
            section_id = None
        size = section_sizes.get(section_id) if section_id is not None else None
        width = getattr(size, "width", None) if size is not None else None
        depth = getattr(size, "depth", None) if size is not None else None
        plan_width = getattr(size, "plan_width", None) if size is not None else None
        fallback_thickness = False
        wall_thickness = None
        resolution_reason = ""
        kind_upper = str(kind or "").upper()
        if kind_upper == "BEAM":
            width = self._beam_plan_display_width(element, size)
            try:
                beta_mod = abs(float(getattr(element, "angle_deg", 0.0) or 0.0)) % 180.0
            except Exception:
                beta_mod = 0.0
            if math.isclose(beta_mod, 0.0, abs_tol=1.0e-6):
                beta_reason = "beta_0_b"
            elif math.isclose(beta_mod, 90.0, abs_tol=1.0e-6):
                beta_reason = "beta_90_h"
            else:
                beta_reason = "beta_projected_bh"
            resolution_reason = f"{getattr(size, 'reason', '') or 'section_unresolved'};{beta_reason}"
        elif kind_upper == "WALL":
            wall_thicknesses = wall_thicknesses or {}
            candidate = wall_thicknesses.get(section_id) if section_id is not None else None
            try:
                wall_thickness = float(candidate) if candidate is not None else None
            except Exception:
                wall_thickness = None
            if wall_thickness is not None and math.isfinite(wall_thickness) and wall_thickness > 0.0:
                width = wall_thickness
                resolution_reason = "wall_thickness_property"
            elif plan_width is not None:
                width = plan_width
                resolution_reason = f"wall_section_plan_width:{getattr(size, 'reason', '') or 'heuristic'}"
            else:
                width = self._fallback_wall_display_thickness()
                fallback_thickness = True
                resolution_reason = "wall_unit_fallback"
                self._set_hatch_structure_preview_status("벽체 단면 두께 정보 없음: 기본 표시 두께로 HATCH VIEW에만 표시합니다.")
        else:
            resolution_reason = f"section_width:{getattr(size, 'reason', '') or 'unresolved'}"
        return {
            "kind": kind,
            "points": points,
            "element": element,
            "element_id": getattr(element, "elem_id", None),
            "section_id": section_id,
            "width": width,
            "depth": depth,
            "plan_width": plan_width,
            "section_name": getattr(size, "name", "") if size is not None else "",
            "section_role": getattr(size, "role", "UNKNOWN") if size is not None else "UNKNOWN",
            "section_shape": getattr(size, "shape", "") if size is not None else "",
            "section_d1": getattr(size, "d1", None) if size is not None else None,
            "section_d2": getattr(size, "d2", None) if size is not None else None,
            "wall_thickness_property": wall_thickness,
            "fallback_thickness": fallback_thickness,
            "width_resolution_reason": resolution_reason,
        }

    def _fallback_wall_display_thickness(self) -> float:
        text = str(self.__dict__.get("current_mgt_text", "") or "")
        signature = self._current_mgt_text_signature()
        cached = self.__dict__.get("_fallback_wall_display_thickness_cache")
        if cached and cached[0] == signature:
            return float(cached[1])
        try:
            unit = str(getattr(parse_unit_from_text(text), "length", "") or "").upper()
        except Exception:
            unit = ""
        if unit in {"MM", "MILLIMETER", "MILLIMETRE"}:
            thickness = 200.0
        elif unit in {"CM", "CENTIMETER", "CENTIMETRE"}:
            thickness = 20.0
        else:
            thickness = 0.2
        self._fallback_wall_display_thickness_cache = (signature, thickness)
        return thickness

    def _set_hatch_structure_preview_status(self, message: str) -> None:
        message = str(message or "")
        self._hatch_structure_status_message = message
        self._set_hatch_preview_info_message(message)

    def _set_hatch_preview_info_message(self, message: str) -> None:
        message = str(message or "")
        info_var = self.__dict__.get("hatch_preview_info_var")
        if info_var is not None:
            token = (id(info_var), message)
            if self.__dict__.get("_hatch_preview_info_last_message") == token:
                return
            try:
                info_var.set(message)
                self._hatch_preview_info_last_message = token
            except Exception:
                pass

    def _story_by_name(self, story_name: str):
        story_name = str(story_name or "")
        return next((story for story in list(getattr(self, "stories", []) or []) if str(getattr(story, "name", "") or "") == story_name), None)

    def _model_story_tolerance(self) -> float:
        value = None
        story_tol_var = self.__dict__.get("story_tol_var")
        if story_tol_var is not None:
            try:
                value = float(story_tol_var.get())
            except Exception:
                value = None
        if value is None:
            config_data = self.__dict__.get("config_data")
            try:
                value = float(getattr(config_data, "story_tolerance"))
            except Exception:
                value = 0.01
        if not math.isfinite(value) or value <= 0.0:
            return 0.01
        return max(value, 1.0e-9)

    def _closed_region_geometry_tolerance(self) -> float:
        signature = self._current_mgt_text_signature()
        cached = self.__dict__.get("_closed_region_geometry_tolerance_cache")
        if cached and cached[0] == signature:
            return float(cached[1])
        text = str(self.__dict__.get("current_mgt_text", "") or "")
        try:
            unit = str(getattr(parse_unit_from_text(text), "length", "") or "").upper()
        except Exception:
            unit = ""
        tolerance_by_unit = {
            "M": 0.001,
            "METER": 0.001,
            "METRE": 0.001,
            "CM": 0.1,
            "CENTIMETER": 0.1,
            "CENTIMETRE": 0.1,
            "MM": 1.0,
            "MILLIMETER": 1.0,
            "MILLIMETRE": 1.0,
            "FT": 0.00328084,
            "FOOT": 0.00328084,
            "FEET": 0.00328084,
            "IN": 0.0393701,
            "INCH": 0.0393701,
            "INCHES": 0.0393701,
        }
        tolerance = max(float(tolerance_by_unit.get(unit, 0.005)), 1.0e-9)
        self._closed_region_geometry_tolerance_cache = (signature, tolerance)
        return tolerance

    def _one_way_shape_tolerance(self) -> float:
        return self._closed_region_geometry_tolerance()

    def _hatch_all_story_transform_for_story(self, story_name: str, story_offsets=None) -> HatchDisplayTransform:
        story_name = str(story_name or "")
        layout = self._layout_by_story().get(story_name)
        layout_transform = getattr(layout, "transform", None) if layout is not None else None
        if layout_transform is not None and hasattr(layout_transform, "apply"):
            dimension_scale = self._layout_transform_dimension_scale(layout_transform, (0.0, 0.0))
            return HatchDisplayTransform(
                story_name=story_name,
                source="layout_metadata",
                scale_x=dimension_scale,
                scale_y=dimension_scale,
                layout_transform=layout_transform,
            )
        dx, dy = dict(story_offsets or {}).get(story_name, (0.0, 0.0))
        source = "story_offset" if abs(float(dx)) > 1.0e-12 or abs(float(dy)) > 1.0e-12 else "identity"
        return HatchDisplayTransform(story_name=story_name, source=source, dx=float(dx), dy=float(dy))

    def _hatch_placed_bbox_transform_for_story(self, story_name: str, display_regions=None) -> HatchDisplayTransform | None:
        story_name = str(story_name or "")
        selected_key = str(self.__dict__.get("hatch_view_selected_region_key") or "")
        candidates = []
        for region_key, region, _vertices in tuple(display_regions or ()):
            hatch = getattr(region, "region", None)
            if str(getattr(hatch, "story_name", "") or "") != story_name:
                continue
            candidates.append((0 if region_key == selected_key else 1, hatch))
        for _priority, hatch in sorted(candidates, key=lambda item: item[0]):
            placed_bbox = tuple(float(value) for value in (getattr(hatch, "placed_bbox", ()) or ()))
            model_bbox = tuple(float(value) for value in (getattr(hatch, "model_bbox", ()) or getattr(hatch, "bbox", ()) or ()))
            if len(placed_bbox) < 4 or len(model_bbox) < 4:
                continue
            if (
                not getattr(hatch, "placed_vertices", ())
                and not bool(getattr(hatch, "transform_applied", False))
                and self._hatch_bboxes_close(placed_bbox, model_bbox)
            ):
                continue
            model_width = model_bbox[2] - model_bbox[0]
            model_height = model_bbox[3] - model_bbox[1]
            placed_width = placed_bbox[2] - placed_bbox[0]
            placed_height = placed_bbox[3] - placed_bbox[1]
            if abs(model_width) <= 1.0e-9 or abs(model_height) <= 1.0e-9:
                continue
            scale_x = placed_width / model_width
            scale_y = placed_height / model_height
            if not all(math.isfinite(value) and abs(value) > 1.0e-12 for value in (scale_x, scale_y)):
                continue
            return HatchDisplayTransform(
                story_name=story_name,
                source="placed_bbox",
                scale_x=scale_x,
                scale_y=scale_y,
                dx=placed_bbox[0] - model_bbox[0] * scale_x,
                dy=placed_bbox[1] - model_bbox[1] * scale_y,
            )
        return None

    def _unified_hatch_display_transform_for_story(self, story_name: str, display_regions=None, story_offsets=None) -> HatchDisplayTransform:
        story_name = str(story_name or "")
        if self._hatch_view_is_all_story_display():
            transform = self._hatch_all_story_transform_for_story(story_name, story_offsets)
            if transform.source in {"layout_metadata", "story_offset"}:
                return transform
            placed_transform = self._hatch_placed_bbox_transform_for_story(story_name, display_regions)
            if placed_transform is not None:
                return placed_transform
            return transform
        return HatchDisplayTransform(story_name=story_name, source="identity")

    def _hatch_structure_display_transform_for_story(self, story_name: str, display_regions, story_offsets) -> tuple[float, float, float, float]:
        display_transform = self._unified_hatch_display_transform_for_story(story_name, display_regions, story_offsets)
        if display_transform.source == "identity":
            placed_transform = self._hatch_placed_bbox_transform_for_story(story_name, display_regions)
            if placed_transform is not None:
                display_transform = placed_transform
            else:
                offset_transform = self._hatch_all_story_transform_for_story(story_name, story_offsets)
                if offset_transform.source == "story_offset":
                    display_transform = offset_transform
        if display_transform.source == "layout_metadata":
            try:
                x0, y0 = display_transform.apply(0.0, 0.0)
                x1, _y1 = display_transform.apply(1.0, 0.0)
                _x2, y2 = display_transform.apply(0.0, 1.0)
                scale_x = x1 - x0
                scale_y = y2 - y0
                if math.isfinite(scale_x) and math.isfinite(scale_y):
                    return (scale_x, scale_y, x0, y0)
            except Exception:
                pass
        return display_transform.as_tuple()

    def _hatch_display_transform_for_story(self, story_name: str, display_regions, story_offsets):
        return self._unified_hatch_display_transform_for_story(story_name, display_regions, story_offsets)

    def _transform_structure_preview_items(self, items: list[dict], transform) -> list[dict]:
        if hasattr(transform, "apply"):
            return self._transform_structure_preview_items_with_layout(items, transform)
        scale_x, scale_y, dx, dy = [float(value) for value in transform]
        if (
            math.isclose(scale_x, 1.0)
            and math.isclose(scale_y, 1.0)
            and math.isclose(dx, 0.0)
            and math.isclose(dy, 0.0)
        ):
            return items
        result = []
        dimension_scale = (abs(scale_x) + abs(scale_y)) / 2.0
        for item in items:
            copied = dict(item)
            copied["points"] = [(float(x) * scale_x + dx, float(y) * scale_y + dy) for x, y in item.get("points", ())]
            for key in ("width", "depth"):
                if copied.get(key) is None:
                    continue
                try:
                    copied[key] = float(copied[key]) * dimension_scale
                except Exception:
                    copied[key] = None
            result.append(copied)
        return result

    def _transform_structure_preview_items_with_layout(self, items: list[dict], layout_transform) -> list[dict]:
        result = []
        for item in items:
            copied = dict(item)
            points = [(float(x), float(y)) for x, y in item.get("points", ())]
            copied["points"] = [layout_transform.apply(x, y) for x, y in points]
            origin = points[0] if points else (0.0, 0.0)
            try:
                dimension_scale = float(getattr(layout_transform, "dimension_scale"))
            except Exception:
                dimension_scale = self._layout_transform_dimension_scale(layout_transform, origin)
            if not math.isfinite(dimension_scale) or dimension_scale <= 0.0:
                dimension_scale = 1.0
            for key in ("width", "depth"):
                if copied.get(key) is None:
                    continue
                try:
                    copied[key] = float(copied[key]) * dimension_scale
                except Exception:
                    copied[key] = None
            result.append(copied)
        return result

    def _layout_transform_dimension_scale(self, layout_transform, origin: tuple[float, float]) -> float:
        x, y = origin
        try:
            x0, y0 = layout_transform.apply(float(x), float(y))
            x1, y1 = layout_transform.apply(float(x) + 1.0, float(y))
            x2, y2 = layout_transform.apply(float(x), float(y) + 1.0)
        except Exception:
            return 1.0
        scale_x = math.hypot(x1 - x0, y1 - y0)
        scale_y = math.hypot(x2 - x0, y2 - y0)
        scale = (abs(scale_x) + abs(scale_y)) / 2.0
        return scale if math.isfinite(scale) and scale > 0.0 else 1.0

    def _offset_structure_preview_items(self, items: list[dict], dx: float, dy: float) -> list[dict]:
        return self._transform_structure_preview_items(items, (1.0, 1.0, float(dx), float(dy)))

    def _merge_collinear_structure_beam_items(self, items) -> list[dict]:
        source = [dict(item) for item in tuple(items or ())]
        endpoint_tolerance = 1.0e-7
        angle_tolerance_deg = 0.75

        def point_key(point) -> tuple[float, float]:
            return (round(float(point[0]), 7), round(float(point[1]), 7))

        def group_key(item):
            points = tuple(item.get("points", ()) or ())
            if str(item.get("kind", "") or "").upper() != "BEAM" or len(points) != 2:
                return None
            first = (float(points[0][0]), float(points[0][1]))
            second = (float(points[1][0]), float(points[1][1]))
            if math.hypot(second[0] - first[0], second[1] - first[1]) <= endpoint_tolerance:
                return None
            width = item.get("width")
            try:
                width_key = round(float(width), 9) if width is not None else None
            except Exception:
                width_key = None
            return (str(item.get("story_name", "") or ""), item.get("section_id"), width_key)

        endpoint_maps: dict[tuple[object, ...], dict[tuple[float, float], list[int]]] = {}
        item_groups: dict[int, tuple[object, ...]] = {}
        for index, item in enumerate(source):
            key = group_key(item)
            if key is None:
                continue
            item_groups[index] = key
            endpoint_map = endpoint_maps.setdefault(key, {})
            for point in tuple(item.get("points", ()) or ()):
                endpoint_map.setdefault(point_key(point), []).append(index)

        def continuation(index: int, interior, endpoint):
            points = [(float(x), float(y)) for x, y in tuple(source[index].get("points", ()) or ())]
            if math.hypot(points[0][0] - endpoint[0], points[0][1] - endpoint[1]) <= endpoint_tolerance:
                other = points[1]
            elif math.hypot(points[1][0] - endpoint[0], points[1][1] - endpoint[1]) <= endpoint_tolerance:
                other = points[0]
            else:
                return None
            incoming = (endpoint[0] - interior[0], endpoint[1] - interior[1])
            outgoing = (other[0] - endpoint[0], other[1] - endpoint[1])
            denominator = math.hypot(*incoming) * math.hypot(*outgoing)
            if denominator <= 1.0e-18:
                return None
            cosine = _clamp((incoming[0] * outgoing[0] + incoming[1] * outgoing[1]) / denominator, -1.0, 1.0)
            angle = math.degrees(math.acos(cosine))
            return angle, other

        used: set[int] = set()
        merged: list[dict] = []
        for start_index, item in enumerate(source):
            key = item_groups.get(start_index)
            if key is None:
                merged.append(item)
                continue
            if start_index in used:
                continue
            points = [(float(x), float(y)) for x, y in tuple(item.get("points", ()) or ())]
            chain = [points[0], points[1]]
            chain_indices = [start_index]
            used.add(start_index)

            def extend(at_head: bool) -> bool:
                endpoint = chain[0] if at_head else chain[-1]
                interior = chain[1] if at_head else chain[-2]
                candidates = []
                for candidate_index in endpoint_maps[key].get(point_key(endpoint), ()):
                    if candidate_index in used:
                        continue
                    candidate = continuation(candidate_index, interior, endpoint)
                    if candidate is None or candidate[0] > angle_tolerance_deg:
                        continue
                    candidates.append((candidate[0], candidate_index, candidate[1]))
                candidates.sort(key=lambda value: (value[0], value[1]))
                if not candidates:
                    return False
                if len(candidates) > 1 and math.isclose(candidates[0][0], candidates[1][0], abs_tol=1.0e-9):
                    return False
                _angle, candidate_index, other = candidates[0]
                used.add(candidate_index)
                if at_head:
                    chain.insert(0, other)
                    chain_indices.insert(0, candidate_index)
                else:
                    chain.append(other)
                    chain_indices.append(candidate_index)
                return True

            while extend(False):
                pass
            while extend(True):
                pass

            copied = dict(source[chain_indices[0]])
            copied["points"] = chain
            element_ids = []
            for index in chain_indices:
                values = tuple(source[index].get("element_ids", ()) or ())
                if not values and source[index].get("element_id") is not None:
                    values = (source[index].get("element_id"),)
                for value in values:
                    if value not in element_ids:
                        element_ids.append(value)
            if element_ids:
                copied["element_ids"] = tuple(element_ids)
            merged.append(copied)
        return merged

    def _draw_hatch_structure_items(self, canvas, items: list[dict], transform) -> None:
        for item in items:
            points = list(item.get("points", ()) or ())
            if not points:
                continue
            kind = str(item.get("kind", "") or "").upper()
            canvas_points = [transform(x, y) for x, y in points]
            if kind == "COLUMN":
                if not hasattr(canvas, "create_oval"):
                    continue
                style = HATCH_VIEW_STRUCTURE_STYLE["COLUMN"]
                x, y = canvas_points[0]
                size_x = self._structure_canvas_dimension(item.get("width"), transform, points[0])
                size_y = self._structure_canvas_dimension(item.get("depth"), transform, points[0])
                stroke_width = int(_clamp(float(style.get("stroke_width", 3)), 1.0, 3.0))
                if size_x is not None and size_y is not None and hasattr(canvas, "create_rectangle"):
                    x1 = x - size_x / 2.0
                    y1 = y - size_y / 2.0
                    x2 = x + size_x / 2.0
                    y2 = y + size_y / 2.0
                    canvas.create_rectangle(
                        x1,
                        y1,
                        x2,
                        y2,
                        outline=style["outline"],
                        fill=style["fill"],
                        stipple=style["stipple"],
                        width=stroke_width,
                        tags=("hatch_structure", "structure:COLUMN", "structure_fill"),
                    )
                    marker_size = max(4.0, min(10.0, min(abs(x2 - x1), abs(y2 - y1)) * 0.35))
                else:
                    canvas.create_oval(
                        x - 6,
                        y - 6,
                        x + 6,
                        y + 6,
                        outline=style["outline"],
                        fill=style["fill"],
                        stipple=style["stipple"],
                        width=stroke_width,
                        tags=("hatch_structure", "structure:COLUMN", "structure_fill"),
                    )
                    marker_size = 6.0
                if hasattr(canvas, "create_rectangle"):
                    half_marker = marker_size / 2.0
                    canvas.create_rectangle(
                        x - half_marker,
                        y - half_marker,
                        x + half_marker,
                        y + half_marker,
                        outline=style["marker_outline"],
                        fill=style["marker_fill"],
                        width=1,
                        tags=("hatch_structure", "structure:COLUMN", "structure_marker"),
                    )
                continue
            if not hasattr(canvas, "create_line"):
                continue
            width_px = self._structure_canvas_dimension(item.get("width"), transform, points[0]) if points else None
            if kind == "WALL":
                style = HATCH_VIEW_STRUCTURE_STYLE["WALL"]
                self._draw_dashed_offset_polyline(
                    canvas,
                    canvas_points,
                    width_px,
                    outline=style["outline"],
                    fill=style["fill"],
                    stipple=style["stipple"],
                    stroke_width=style["stroke_width"],
                    tags=("hatch_structure", "structure:WALL"),
                )
            else:
                style = HATCH_VIEW_STRUCTURE_STYLE["BEAM"]
                self._draw_dashed_offset_polyline(
                    canvas,
                    canvas_points,
                    width_px,
                    outline=style["outline"],
                    fill=style["fill"],
                    stipple=style["stipple"],
                    stroke_width=style["stroke_width"],
                    tags=("hatch_structure", "structure:BEAM"),
                )

    def _structure_canvas_dimension(self, value, transform, origin: tuple[float, float]) -> float | None:
        try:
            dimension = float(value)
        except Exception:
            return None
        if not math.isfinite(dimension) or dimension <= 0.0:
            return None
        x, y = origin
        tx0, ty0 = transform(x, y)
        tx1, ty1 = transform(x + dimension, y)
        tx2, ty2 = transform(x, y + dimension)
        pixels = max(math.hypot(tx1 - tx0, ty1 - ty0), math.hypot(tx2 - tx0, ty2 - ty0))
        return pixels if math.isfinite(pixels) and pixels > 0.0 else None

    def _debug_hatch_structure_scale_report(self, story_name: str) -> dict:
        story_name = str(story_name or "")
        regions = list(self.__dict__.get("loaded_regions", []) or [])
        story_offsets = self._hatch_story_display_offsets(regions)
        display_regions = []
        for index, region in enumerate(regions, start=1):
            try:
                region_key = self._region_key(region, index=index)
            except Exception:
                region_key = f"loaded:{index}"
            vertices = self._region_display_vertices(region, story_offsets)
            if vertices:
                display_regions.append((region_key, region, vertices))
        display_transform = self._hatch_display_transform_for_story(story_name, display_regions, story_offsets)
        if hasattr(display_transform, "dimension_scale"):
            dimension_scale = float(display_transform.dimension_scale)
            transform_source = str(getattr(display_transform, "source", "") or "")
        else:
            values = tuple(float(value) for value in tuple(display_transform or (1.0, 1.0, 0.0, 0.0)))
            dimension_scale = (abs(values[0]) + abs(values[1])) / 2.0
            transform_source = "tuple"
        try:
            unit = str(getattr(parse_unit_from_text(str(self.__dict__.get("current_mgt_text", "") or "")), "length", "") or "")
        except Exception:
            unit = ""
        story_items = self._structure_preview_items_for_story(story_name)
        sample_item = next((item for item in story_items if item.get("width") is not None), None)
        sample_width_model = None
        sample_width_display = None
        sample_width_px = None
        if sample_item is not None:
            try:
                sample_width_model = float(sample_item.get("width"))
                sample_width_display = sample_width_model * dimension_scale
                origin = tuple(sample_item.get("points", ((0.0, 0.0),))[0])
                if hasattr(display_transform, "apply"):
                    display_origin = display_transform.apply(float(origin[0]), float(origin[1]))
                else:
                    sx, sy, dx, dy = tuple(float(value) for value in tuple(display_transform or (1.0, 1.0, 0.0, 0.0)))
                    display_origin = (float(origin[0]) * sx + dx, float(origin[1]) * sy + dy)
                view_bbox = self.__dict__.get("hatch_view_view_bbox") or self.__dict__.get("hatch_view_fit_bbox")
                if view_bbox is not None:
                    canvas_transform, _content_width, _content_height = self._hatch_canvas_transform(view_bbox, 1000, 1000)
                    sample_width_px = self._structure_canvas_dimension(sample_width_display, canvas_transform, display_origin)
            except Exception:
                sample_width_model = sample_width_display = sample_width_px = None
        return {
            "story_name": story_name,
            "model_unit": unit,
            "display_mode": self._hatch_view_display_mode(),
            "all_story": self._hatch_view_is_all_story_display(),
            "transform_source": transform_source,
            "dimension_scale": dimension_scale,
            "view_bbox": self.__dict__.get("hatch_view_view_bbox"),
            "sample_width_model": sample_width_model,
            "sample_width_display": sample_width_display,
            "sample_width_px": sample_width_px,
        }

    def _debug_hatch_structure_element_report(self, element_id: int, story_name: str = "") -> dict:
        try:
            requested_id = int(element_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid structure element id: {element_id}") from exc
        element = next(
            (
                candidate
                for candidate in tuple(self.__dict__.get("elements", ()) or ())
                if getattr(candidate, "elem_id", None) is not None
                and int(getattr(candidate, "elem_id")) == requested_id
            ),
            None,
        )
        if element is None:
            raise KeyError(f"Structure element not found: {requested_id}")

        candidate_stories = [str(story_name)] if str(story_name or "") else [
            str(getattr(story, "name", "") or "")
            for story in tuple(self.__dict__.get("stories", ()) or ())
        ]
        item = None
        resolved_story = ""
        for candidate_story in candidate_stories:
            if not candidate_story:
                continue
            for candidate_item in self._structure_preview_items_for_story(candidate_story):
                if int(candidate_item.get("element_id") or -1) == requested_id:
                    item = candidate_item
                    resolved_story = candidate_story
                    break
            if item is not None:
                break

        section_sizes = self._section_display_sizes_for_hatch_view()
        wall_thicknesses = self._wall_thicknesses_for_hatch_view()
        property_id = getattr(element, "prop", None)
        try:
            property_id = int(property_id) if property_id is not None else None
        except (TypeError, ValueError):
            property_id = None
        size = section_sizes.get(property_id) if property_id is not None else None
        element_type = str(getattr(element, "elem_type", "") or "").upper()
        if item is None:
            if element_type in HATCH_VIEW_STRUCTURE_WALL_TYPES:
                kind = "WALL"
            elif element_type == "COLUMN":
                kind = "COLUMN"
            else:
                kind = "BEAM"
            node_by_id = {
                int(getattr(node, "node_id")): node
                for node in tuple(self.__dict__.get("nodes", ()) or ())
                if getattr(node, "node_id", None) is not None
            }
            points = [
                (float(node_by_id[node_id].x), float(node_by_id[node_id].y))
                for node_id in tuple(getattr(element, "node_ids", ()) or ())
                if node_id in node_by_id
            ]
            points = points[:1] if kind == "COLUMN" else points[:2]
            item = self._hatch_structure_item(kind, points, element, section_sizes, wall_thicknesses)
            resolved_story = next((name for name in candidate_stories if name), "")

        canvas_pixel_width = None
        if resolved_story and item.get("points") and item.get("width") is not None:
            try:
                regions = list(self.__dict__.get("loaded_regions", []) or [])
                story_offsets = self._hatch_story_display_offsets(regions)
                display_regions = []
                for index, region in enumerate(regions, start=1):
                    region_key = self._region_key(region, index=index)
                    vertices = self._region_display_vertices(region, story_offsets)
                    if vertices:
                        display_regions.append((region_key, region, vertices))
                display_transform = self._hatch_display_transform_for_story(resolved_story, display_regions, story_offsets)
                display_item = self._transform_structure_preview_items([item], display_transform)[0]
                origin = tuple(display_item.get("points", ((0.0, 0.0),))[0])
                view_bbox = self.__dict__.get("hatch_view_view_bbox") or self.__dict__.get("hatch_view_fit_bbox")
                if view_bbox is not None:
                    canvas = self.__dict__.get("hatch_preview_canvas")
                    width_px = max(int(getattr(canvas, "winfo_width", lambda: 1000)() or 0), 1) if canvas is not None else 1000
                    height_px = max(int(getattr(canvas, "winfo_height", lambda: 1000)() or 0), 1) if canvas is not None else 1000
                    canvas_transform, _content_width, _content_height = self._hatch_canvas_transform(view_bbox, width_px, height_px)
                    canvas_pixel_width = self._structure_canvas_dimension(display_item.get("width"), canvas_transform, origin)
            except Exception:
                canvas_pixel_width = None

        return {
            "story_name": resolved_story,
            "element_id": requested_id,
            "element_type": element_type,
            "property_id": property_id,
            "beta_deg": float(getattr(element, "angle_deg", 0.0) or 0.0),
            "section_name": getattr(size, "name", "") if size is not None else "",
            "section_role": getattr(size, "role", "UNKNOWN") if size is not None else "UNKNOWN",
            "section_shape": getattr(size, "shape", "") if size is not None else "",
            "section_d1": getattr(size, "d1", None) if size is not None else None,
            "section_d2": getattr(size, "d2", None) if size is not None else None,
            "resolved_width": item.get("width"),
            "resolved_depth": item.get("depth"),
            "plan_width": getattr(size, "plan_width", None) if size is not None else None,
            "wall_thickness_property": wall_thicknesses.get(property_id) if property_id is not None else None,
            "fallback_thickness": bool(item.get("fallback_thickness")),
            "canvas_pixel_width": canvas_pixel_width,
            "width_resolution_reason": str(item.get("width_resolution_reason") or ""),
        }

    def _selected_hatch_geometry_debug_report(self, region_key: str) -> dict:
        from shapely.geometry import Polygon
        from shapely.ops import unary_union

        key = str(region_key or "")
        internal_region = (self.__dict__.get("hatch_view_edit_region_by_key", {}) or {}).get(key)
        dxf_region = (self.__dict__.get("hatch_view_region_by_key", {}) or {}).get(key)
        if internal_region is None and dxf_region is None:
            raise KeyError(f"HATCH region not found: {key}")

        story_offsets = self._hatch_story_display_offsets(list(self.__dict__.get("loaded_regions", []) or []))
        cells = []
        if internal_region is not None:
            source = "INTERNAL"
            story_name = str(getattr(internal_region, "story_name", "") or "")
            raw_points = [(float(x), float(y)) for x, y in tuple(getattr(internal_region, "polygon_xy", ()) or ())]
            display_points = self._hatch_edit_region_display_vertices(internal_region, story_offsets)
            cell_ids = set(tuple(getattr(internal_region, "cell_ids", ()) or ()))
            state = (self.__dict__.get("hatch_edit_states_by_story", {}) or {}).get(story_name)
            cells_by_id = getattr(state, "cells_by_id", {}) or {}
            cells = [cells_by_id[cell_id] for cell_id in cell_ids if cell_id in cells_by_id]
        else:
            source = "DXF"
            hatch = getattr(dxf_region, "region", None)
            story_name = str(getattr(hatch, "story_name", "") or "")
            raw_points = [(float(x), float(y)) for x, y in tuple(getattr(hatch, "vertices", ()) or ())]
            display_points = self._region_display_vertices(dxf_region, story_offsets)

        canvas = self.__dict__.get("hatch_preview_canvas")
        view_bbox = self.__dict__.get("hatch_view_view_bbox") or self.__dict__.get("hatch_view_fit_bbox")
        width = max(int(getattr(canvas, "winfo_width", lambda: 1000)() or 0), 1) if canvas is not None else 1000
        height = max(int(getattr(canvas, "winfo_height", lambda: 1000)() or 0), 1) if canvas is not None else 1000
        simplify_tolerance = self._hatch_display_simplify_tolerance(view_bbox, width, height) if view_bbox is not None else 0.0
        simplified_points = self._simplify_hatch_display_vertices(display_points, simplify_tolerance)
        if view_bbox is not None:
            canvas_transform, _content_width, _content_height = self._hatch_canvas_transform(view_bbox, width, height)
            canvas_points = [canvas_transform(x, y) for x, y in simplified_points]
        else:
            canvas_points = list(simplified_points)

        boundary_element_ids = []
        source_node_ids = []
        for cell in cells:
            for element_id in tuple(getattr(cell, "boundary_element_ids", ()) or ()):
                if element_id not in boundary_element_ids:
                    boundary_element_ids.append(element_id)
            for node_id in tuple(getattr(cell, "node_ids", ()) or ()):
                if node_id not in source_node_ids:
                    source_node_ids.append(node_id)
        node_by_id = {
            int(getattr(node, "node_id")): node
            for node in tuple(self.__dict__.get("nodes", ()) or ())
            if getattr(node, "node_id", None) is not None
        }
        source_node_coordinates = [
            (float(node_by_id[node_id].x), float(node_by_id[node_id].y))
            for node_id in source_node_ids
            if node_id in node_by_id
        ]
        element_by_id = {
            int(getattr(element, "elem_id")): element
            for element in tuple(self.__dict__.get("elements", ()) or ())
            if getattr(element, "elem_id", None) is not None
        }
        matching_structure_points = []
        for element_id in boundary_element_ids:
            element = element_by_id.get(int(element_id))
            if element is None:
                continue
            points = [
                (float(node_by_id[node_id].x), float(node_by_id[node_id].y))
                for node_id in tuple(getattr(element, "node_ids", ()) or ())
                if node_id in node_by_id
            ]
            matching_structure_points.append({"element_id": int(element_id), "points": points})

        coordinate_shifts = [
            min(math.hypot(x - sx, y - sy) for sx, sy in source_node_coordinates)
            for x, y in raw_points
        ] if raw_points and source_node_coordinates else []
        raw_polygon = Polygon(raw_points) if len(raw_points) >= 3 else Polygon()
        source_polygons = []
        for cell in cells:
            points = [
                (float(node_by_id[node_id].x), float(node_by_id[node_id].y))
                for node_id in tuple(getattr(cell, "node_ids", ()) or ())
                if node_id in node_by_id
            ]
            if len(points) >= 3:
                polygon = Polygon(points)
                if not polygon.is_valid:
                    polygon = polygon.buffer(0)
                if not polygon.is_empty:
                    source_polygons.append(polygon)
        source_geometry = unary_union(source_polygons) if source_polygons else Polygon()
        hausdorff_distance = None
        symmetric_difference_area = None
        if not raw_polygon.is_empty and not source_geometry.is_empty:
            hausdorff_distance = float(raw_polygon.boundary.hausdorff_distance(source_geometry.boundary))
            symmetric_difference_area = float(raw_polygon.symmetric_difference(source_geometry).area)

        try:
            floorload_snap_tolerance = float(self.snap_tol_var.get()) if hasattr(self, "snap_tol_var") else 0.5
        except Exception:
            floorload_snap_tolerance = 0.5
        return {
            "region_key": key,
            "story_name": story_name,
            "source": source,
            "raw_hatch_polygon_xy": raw_points,
            "display_simplified_polygon_xy": list(simplified_points),
            "canvas_polygon_xy": canvas_points,
            "matching_boundary_element_ids": boundary_element_ids,
            "matching_structure_centerline_points": matching_structure_points,
            "source_node_coordinates": source_node_coordinates,
            "maximum_coordinate_shift": max(coordinate_shifts) if coordinate_shifts else None,
            "average_coordinate_shift": sum(coordinate_shifts) / len(coordinate_shifts) if coordinate_shifts else None,
            "hausdorff_distance": hausdorff_distance,
            "symmetric_difference_area": symmetric_difference_area,
            "polygon_area": float(raw_polygon.area) if not raw_polygon.is_empty else None,
            "vertex_count_raw": len(raw_points),
            "vertex_count_display": len(simplified_points),
            "geometry_tolerance": self._closed_region_geometry_tolerance(),
            "floorload_snap_tolerance": floorload_snap_tolerance,
        }

    def _write_selected_hatch_geometry_debug_report(self, output_dir, region_key: str):
        try:
            output = Path(output_dir) if output_dir is not None else self._hatch_closed_region_reports_dir()
            if output is None:
                return None
            output.mkdir(parents=True, exist_ok=True)
            report = self._selected_hatch_geometry_debug_report(region_key)
            json_path = output / "hatch_selection_geometry_debug.json"
            csv_path = output / "hatch_selection_geometry_debug.csv"
            json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            csv_row = {
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (list, tuple, dict)) else value
                for key, value in report.items()
            }
            with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(csv_row))
                writer.writeheader()
                writer.writerow(csv_row)
            return json_path, csv_path
        except Exception as exc:  # noqa: BLE001 - debug output must never block HATCH VIEW
            logger = self.__dict__.get("logger")
            if logger is not None:
                logger.warning("selected HATCH geometry debug report failed: %s", exc)
            return None

    def _structure_centerline_to_hatch_boundary_offset_report(self, story_name: str) -> list[dict]:
        story_name = str(story_name or "")
        if not story_name:
            return []
        regions = list(self.__dict__.get("loaded_regions", []) or [])
        story_offsets = self._hatch_story_display_offsets(regions)
        display_regions = []
        boundary_segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        for index, region in enumerate(regions, start=1):
            hatch = getattr(region, "region", None)
            if str(getattr(hatch, "story_name", "") or "") != story_name:
                continue
            try:
                region_key = self._region_key(region, index=index)
            except Exception:
                region_key = f"loaded:{index}"
            vertices = self._region_display_vertices(region, story_offsets)
            if vertices:
                display_regions.append((region_key, region, vertices))
                boundary_segments.extend(self._closed_polyline_segments(vertices))
        for _key, region, vertices in self._hatch_view_display_edit_regions(story_offsets):
            if str(getattr(region, "story_name", "") or "") == story_name and vertices:
                boundary_segments.extend(self._closed_polyline_segments(vertices))
        if not boundary_segments:
            return []
        story_items = self._structure_preview_items_for_story(story_name)
        if self._hatch_view_is_all_story_display():
            display_transform = self._hatch_display_transform_for_story(story_name, display_regions, story_offsets)
            story_items = self._transform_structure_preview_items(story_items, display_transform)
        report = []
        for item in story_items:
            kind = str(item.get("kind", "") or "").upper()
            if kind not in {"BEAM", "WALL"}:
                continue
            points = [(float(x), float(y)) for x, y in tuple(item.get("points", ()) or ())]
            distances = []
            for first, second in zip(points, points[1:]):
                distances.append(
                    min(
                        self._segment_to_segment_distance(first, second, boundary_first, boundary_second)
                        for boundary_first, boundary_second in boundary_segments
                    )
                )
            if not distances:
                continue
            report.append(
                {
                    "story_name": story_name,
                    "kind": kind,
                    "element_id": item.get("element_id"),
                    "average_offset": sum(distances) / len(distances),
                    "max_offset": max(distances),
                    "segment_count": len(distances),
                    "tolerance": self._continuous_sync_xy_tolerance(),
                }
            )
        return report

    def _closed_polyline_segments(self, points) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        vertices = [(float(x), float(y)) for x, y in tuple(points or ())]
        if len(vertices) < 2:
            return []
        pairs = list(zip(vertices, vertices[1:]))
        if len(vertices) > 2:
            pairs.append((vertices[-1], vertices[0]))
        return pairs

    def _segment_to_segment_distance(self, a, b, c, d) -> float:
        if self._segments_intersect(a, b, c, d):
            return 0.0
        return min(
            self._point_to_segment_distance(a, c, d),
            self._point_to_segment_distance(b, c, d),
            self._point_to_segment_distance(c, a, b),
            self._point_to_segment_distance(d, a, b),
        )

    def _point_to_segment_distance(self, point, first, second) -> float:
        px, py = float(point[0]), float(point[1])
        x1, y1 = float(first[0]), float(first[1])
        x2, y2 = float(second[0]), float(second[1])
        dx = x2 - x1
        dy = y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq <= 1.0e-18:
            return math.hypot(px - x1, py - y1)
        t = _clamp(((px - x1) * dx + (py - y1) * dy) / length_sq, 0.0, 1.0)
        return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))

    def _segments_intersect(self, a, b, c, d) -> bool:
        def orientation(p, q, r) -> float:
            return (float(q[1]) - float(p[1])) * (float(r[0]) - float(q[0])) - (float(q[0]) - float(p[0])) * (float(r[1]) - float(q[1]))

        def on_segment(p, q, r) -> bool:
            return (
                min(float(p[0]), float(r[0])) - 1.0e-9 <= float(q[0]) <= max(float(p[0]), float(r[0])) + 1.0e-9
                and min(float(p[1]), float(r[1])) - 1.0e-9 <= float(q[1]) <= max(float(p[1]), float(r[1])) + 1.0e-9
            )

        o1 = orientation(a, b, c)
        o2 = orientation(a, b, d)
        o3 = orientation(c, d, a)
        o4 = orientation(c, d, b)
        if o1 * o2 < 0.0 and o3 * o4 < 0.0:
            return True
        return (
            math.isclose(o1, 0.0, abs_tol=1.0e-9)
            and on_segment(a, c, b)
            or math.isclose(o2, 0.0, abs_tol=1.0e-9)
            and on_segment(a, d, b)
            or math.isclose(o3, 0.0, abs_tol=1.0e-9)
            and on_segment(c, a, d)
            or math.isclose(o4, 0.0, abs_tol=1.0e-9)
            and on_segment(c, b, d)
        )

    def _draw_dashed_offset_polyline(
        self,
        canvas,
        canvas_points,
        width_px: float | None,
        *,
        outline: str,
        tags,
        fill: str = "",
        stipple: str = "",
        stroke_width: int = 2,
    ) -> None:
        points = [(float(x), float(y)) for x, y in canvas_points]
        if len(points) < 2:
            return
        stroke_width = int(_clamp(float(stroke_width), 1.0, 3.0))
        if width_px is None or width_px <= 4.0:
            flat = [coord for point in points for coord in point]
            canvas.create_line(*flat, fill=outline, width=stroke_width, dash=(5, 3), joinstyle=tk.ROUND, tags=tags)
            return
        if len(points) == 2:
            outline_points = self._offset_rectangle_from_canvas_segment(points[0], points[1], width_px)
            self._draw_structure_offset_shape(
                canvas,
                outline_points,
                outline_color=outline,
                fill=fill,
                stipple=stipple,
                tags=tags,
                stroke_width=stroke_width,
            )
            return
        try:
            buffered = LineString(points).buffer(float(width_px) / 2.0, cap_style=2, join_style=2)
            if hasattr(buffered, "geoms") and not hasattr(buffered, "exterior"):
                buffered = max(tuple(buffered.geoms), key=lambda geometry: float(geometry.area))
            outline_points = [(float(x), float(y)) for x, y in list(buffered.exterior.coords)[:-1]]
            if len(outline_points) < 3:
                raise ValueError("joined offset polygon has fewer than three points")
            self._draw_structure_offset_shape(
                canvas,
                outline_points,
                outline_color=outline,
                fill=fill,
                stipple=stipple,
                tags=tags,
                stroke_width=stroke_width,
            )
            return
        except Exception:
            pass
        for first, second in zip(points, points[1:]):
            outline_points = self._offset_rectangle_from_canvas_segment(first, second, width_px)
            self._draw_structure_offset_shape(
                canvas,
                outline_points,
                outline_color=outline,
                fill=fill,
                stipple=stipple,
                tags=tags,
                stroke_width=stroke_width,
            )

    def _draw_structure_offset_shape(
        self,
        canvas,
        outline_points,
        *,
        outline_color: str,
        fill: str,
        stipple: str,
        tags,
        stroke_width: int,
    ) -> None:
        if fill and hasattr(canvas, "create_polygon"):
            flat_polygon = [coord for point in outline_points for coord in point]
            canvas.create_polygon(
                *flat_polygon,
                fill=fill,
                outline="",
                stipple=stipple or "gray25",
                tags=tuple(tags) + ("structure_fill",),
            )
        flat_line = [coord for point in list(outline_points) + [outline_points[0]] for coord in point]
        canvas.create_line(*flat_line, fill=outline_color, width=stroke_width, dash=(5, 3), tags=tags)

    def _offset_rectangle_from_canvas_segment(
        self,
        first: tuple[float, float],
        second: tuple[float, float],
        width_px: float,
    ) -> list[tuple[float, float]]:
        dx = second[0] - first[0]
        dy = second[1] - first[1]
        length = math.hypot(dx, dy)
        if length <= 1.0e-9:
            half = float(width_px) / 2.0
            return [(first[0] - half, first[1] - half), (first[0] + half, first[1] - half), (first[0] + half, first[1] + half), (first[0] - half, first[1] + half)]
        nx = -dy / length
        ny = dx / length
        half = float(width_px) / 2.0
        return [
            (first[0] + nx * half, first[1] + ny * half),
            (second[0] + nx * half, second[1] + ny * half),
            (second[0] - nx * half, second[1] - ny * half),
            (first[0] - nx * half, first[1] - ny * half),
        ]

    def _is_one_way_distribution(self, value) -> bool:
        return str(value or "").strip().upper().replace("-", "_").replace(" ", "_") == DISTRIBUTION_ONE_WAY

    def _one_way_angle_from_vertices(self, vertices) -> float | None:
        points = tuple((float(x), float(y)) for x, y in tuple(vertices or ()))
        if len(points) < 3:
            return None
        angle, _source, _warnings = infer_short_span_angle(points)
        if angle is None:
            return None
        return float(angle) % 180.0

    def _one_way_handle_orientation_group(self, angle_deg: float) -> str:
        theta = math.radians(float(angle_deg) % 180.0)
        return "horizontal" if abs(math.cos(theta)) >= abs(math.sin(theta)) else "vertical"

    def _draw_one_way_direction_handles(self, canvas, region_key: str, vertices, angle_deg: float, transform, *, source: str) -> None:
        perf_token = self._hatch_perf_start("_draw_one_way_direction_handles")

        def finish(*, created: int = 0, culled: bool = False) -> None:
            self._hatch_perf_end(
                perf_token,
                story_name="",
                display_mode=self._hatch_view_display_mode(),
                visible_region_count=1 if created else 0,
                structure_item_count=0,
                candidate_target_count=0,
                cache_hit=0,
                cache_miss=0,
                region_key=str(region_key or ""),
                source=str(source or ""),
                culled=culled,
            )

        points = [(float(x), float(y)) for x, y in tuple(vertices or ())]
        if len(points) < 3:
            finish()
            return
        cx, cy = self._polygon_centroid(points)
        angle = math.radians(float(angle_deg) % 180.0)
        try:
            tx, ty = transform(cx, cy)
            px, py = transform(cx + math.cos(angle), cy + math.sin(angle))
            canvas_points = [(float(x), float(y)) for x, y in (transform(x, y) for x, y in points)]
        except Exception:
            finish()
            return
        if len(canvas_points) < 3:
            finish()
            return
        cxs = [float(x) for x, _y in canvas_points]
        cys = [float(y) for _x, y in canvas_points]
        min_x, max_x = min(cxs), max(cxs)
        min_y, max_y = min(cys), max(cys)
        width_px = max(max_x - min_x, 0.0)
        height_px = max(max_y - min_y, 0.0)
        if width_px <= 1.0e-9 or height_px <= 1.0e-9:
            finish()
            return
        short_px = max(min(width_px, height_px), 1.0)
        ux = float(px) - float(tx)
        uy = float(py) - float(ty)
        length = math.hypot(ux, uy)
        if length <= 1.0e-9:
            finish()
            return
        ux /= length
        uy /= length
        checkbox_half_size = self._hatch_checkbox_canvas_half_size(points, transform)
        line_width = max(1, int(round(_clamp(short_px * 0.035, 1.0, 12.0))))
        hitbox_width = max(
            line_width + 1,
            int(round(_clamp(short_px * 0.09, float(line_width + 1), max(float(line_width + 1), 18.0)))),
        )
        canvas_viewport = self._hatch_canvas_visible_bbox(canvas, padding_px=max(32.0, float(hitbox_width) * 2.0))
        if canvas_viewport is not None and not self._bboxes_intersect(canvas_viewport, (min_x, min_y, max_x, max_y)):
            finish(culled=True)
            return
        arrowshape = (
            int(round(_clamp(short_px * 0.10, line_width * 3.0, line_width * 6.0))),
            int(round(_clamp(short_px * 0.12, line_width * 3.5, line_width * 7.0))),
            int(round(_clamp(short_px * 0.045, line_width * 1.5, line_width * 3.0))),
        )
        edge_margin = max(float(hitbox_width) * 0.65, float(line_width) * 1.8, short_px * 0.025)
        clearance = max(float(hitbox_width) * 0.55, checkbox_half_size * 0.30, short_px * 0.020)
        checkbox_bbox = (
            tx - checkbox_half_size,
            ty - checkbox_half_size,
            tx + checkbox_half_size,
            ty + checkbox_half_size,
        )
        tags = (
            "hatch_one_way_handle",
            f"one_way_region:{region_key}",
            f"one_way_source:{source}",
        )

        def line_bbox(x1: float, y1: float, x2: float, y2: float, width_px: float) -> tuple[float, float, float, float]:
            pad = max(float(width_px) / 2.0, 0.0)
            return (
                min(x1, x2) - pad,
                min(y1, y2) - pad,
                max(x1, x2) + pad,
                max(y1, y2) + pad,
            )

        def bbox_with_clearance(bbox, clearance_px: float) -> tuple[float, float, float, float]:
            return (
                float(bbox[0]) - clearance_px,
                float(bbox[1]) - clearance_px,
                float(bbox[2]) + clearance_px,
                float(bbox[3]) + clearance_px,
            )

        def bbox_intersects(first, second) -> bool:
            return not (
                first[2] < second[0]
                or second[2] < first[0]
                or first[3] < second[1]
                or second[3] < first[1]
            )

        def point_on_segment(px_value: float, py_value: float, ax: float, ay: float, bx: float, by: float) -> bool:
            dx = bx - ax
            dy = by - ay
            denom = dx * dx + dy * dy
            if denom <= 1.0e-9:
                return math.hypot(px_value - ax, py_value - ay) <= 1.0
            t = _clamp(((px_value - ax) * dx + (py_value - ay) * dy) / denom, 0.0, 1.0)
            nearest_x = ax + dx * t
            nearest_y = ay + dy * t
            return math.hypot(px_value - nearest_x, py_value - nearest_y) <= 1.0

        def point_inside_canvas_polygon(px_value: float, py_value: float) -> bool:
            inside = False
            previous_x, previous_y = canvas_points[-1]
            for current_x, current_y in canvas_points:
                if point_on_segment(px_value, py_value, previous_x, previous_y, current_x, current_y):
                    return True
                crosses = (current_y > py_value) != (previous_y > py_value)
                if crosses:
                    x_at_y = (previous_x - current_x) * (py_value - current_y) / (previous_y - current_y + 1.0e-12) + current_x
                    if px_value < x_at_y:
                        inside = not inside
                previous_x, previous_y = current_x, current_y
            return inside

        def polygon_intervals_at_y(y_value: float) -> list[tuple[float, float]]:
            crossings: list[float] = []
            previous_x, previous_y = canvas_points[-1]
            for current_x, current_y in canvas_points:
                if abs(previous_y - current_y) > 1.0e-9:
                    low_y = min(previous_y, current_y)
                    high_y = max(previous_y, current_y)
                    if low_y <= y_value < high_y:
                        ratio = (y_value - previous_y) / (current_y - previous_y)
                        crossings.append(previous_x + (current_x - previous_x) * ratio)
                previous_x, previous_y = current_x, current_y
            crossings.sort()
            return [
                (crossings[index], crossings[index + 1])
                for index in range(0, len(crossings) - 1, 2)
                if crossings[index + 1] - crossings[index] > 1.0e-9
            ]

        def polygon_intervals_at_x(x_value: float) -> list[tuple[float, float]]:
            crossings: list[float] = []
            previous_x, previous_y = canvas_points[-1]
            for current_x, current_y in canvas_points:
                if abs(previous_x - current_x) > 1.0e-9:
                    low_x = min(previous_x, current_x)
                    high_x = max(previous_x, current_x)
                    if low_x <= x_value < high_x:
                        ratio = (x_value - previous_x) / (current_x - previous_x)
                        crossings.append(previous_y + (current_y - previous_y) * ratio)
                previous_x, previous_y = current_x, current_y
            crossings.sort()
            return [
                (crossings[index], crossings[index + 1])
                for index in range(0, len(crossings) - 1, 2)
                if crossings[index + 1] - crossings[index] > 1.0e-9
            ]

        def candidate_cross_values(start: float, end: float) -> list[float]:
            cross_min = min(start, end) + float(hitbox_width) * 0.5
            cross_max = max(start, end) - float(hitbox_width) * 0.5
            if cross_max <= cross_min:
                return []
            span = cross_max - cross_min
            return [
                (cross_min + cross_max) / 2.0,
                cross_min + span * 0.35,
                cross_min + span * 0.65,
            ]

        checkbox_guard_bbox = bbox_with_clearance(checkbox_bbox, clearance)

        def line_clear_of_checkbox(x1: float, y1: float, x2: float, y2: float) -> bool:
            visual_width = max(float(line_width), float(arrowshape[1]))
            return not (
                bbox_intersects(checkbox_guard_bbox, line_bbox(x1, y1, x2, y2, visual_width))
                or bbox_intersects(checkbox_guard_bbox, line_bbox(x1, y1, x2, y2, float(hitbox_width)))
            )

        def line_inside_polygon(x1: float, y1: float, x2: float, y2: float) -> bool:
            center_x = (x1 + x2) / 2.0
            center_y = (y1 + y2) / 2.0
            sample_points = [
                (x1, y1),
                (center_x, center_y),
                (x2, y2),
                (x1 * 0.75 + x2 * 0.25, y1 * 0.75 + y2 * 0.25),
                (x1 * 0.25 + x2 * 0.75, y1 * 0.25 + y2 * 0.75),
            ]
            if not all(point_inside_canvas_polygon(x, y) for x, y in sample_points):
                return False
            hitbox_points = self._offset_rectangle_from_canvas_segment((x1, y1), (x2, y2), float(hitbox_width))
            return all(point_inside_canvas_polygon(x, y) for x, y in hitbox_points)

        def target_arrow_length(available_length: float) -> float:
            if available_length <= 0.0:
                return 0.0
            arrow_len = min(available_length * 0.72, short_px * 0.70)
            minimum = max(short_px * 0.12, float(hitbox_width) * 1.10)
            if arrow_len < minimum and available_length >= minimum:
                arrow_len = minimum
            return min(arrow_len, available_length)

        def build_horizontal_candidate(y_value: float, interval_start: float, interval_end: float):
            start = float(interval_start) + edge_margin
            end = float(interval_end) - edge_margin
            available = end - start
            arrow_len = target_arrow_length(available)
            if arrow_len <= 0.0:
                return None
            min_len = max(short_px * 0.08, float(line_width) * 2.0)
            if arrow_len < min_len:
                return None
            for scale in (1.0, 0.82, 0.64, 0.48):
                scaled_len = min(arrow_len * scale, available)
                if scaled_len < min_len:
                    continue
                center_x = _clamp(float(tx), start + scaled_len * 0.5, end - scaled_len * 0.5)
                center_y = float(y_value)
                x1 = center_x - ux * scaled_len * 0.5
                y1 = center_y - uy * scaled_len * 0.5
                x2 = center_x + ux * scaled_len * 0.5
                y2 = center_y + uy * scaled_len * 0.5
                if not line_clear_of_checkbox(x1, y1, x2, y2):
                    continue
                if not line_inside_polygon(x1, y1, x2, y2):
                    continue
                return {
                    "line": (x1, y1, x2, y2),
                    "length": scaled_len,
                    "available": available,
                }
            return None

        def build_vertical_candidate(x_value: float, interval_start: float, interval_end: float):
            start = float(interval_start) + edge_margin
            end = float(interval_end) - edge_margin
            available = end - start
            arrow_len = target_arrow_length(available)
            if arrow_len <= 0.0:
                return None
            min_len = max(short_px * 0.08, float(line_width) * 2.0)
            if arrow_len < min_len:
                return None
            for scale in (1.0, 0.82, 0.64, 0.48):
                scaled_len = min(arrow_len * scale, available)
                if scaled_len < min_len:
                    continue
                center_x = float(x_value)
                center_y = _clamp(float(ty), start + scaled_len * 0.5, end - scaled_len * 0.5)
                x1 = center_x - ux * scaled_len * 0.5
                y1 = center_y - uy * scaled_len * 0.5
                x2 = center_x + ux * scaled_len * 0.5
                y2 = center_y + uy * scaled_len * 0.5
                if not line_clear_of_checkbox(x1, y1, x2, y2):
                    continue
                if not line_inside_polygon(x1, y1, x2, y2):
                    continue
                return {
                    "line": (x1, y1, x2, y2),
                    "length": scaled_len,
                    "available": available,
                }
            return None

        candidates = []
        orientation_group = self._one_way_handle_orientation_group(angle_deg)
        if orientation_group == "horizontal":
            lanes = (
                (min_y + edge_margin, checkbox_guard_bbox[1]),
                (checkbox_guard_bbox[3], max_y - edge_margin),
            )
            for lane_start, lane_end in lanes:
                for y_value in candidate_cross_values(lane_start, lane_end):
                    for interval_start, interval_end in polygon_intervals_at_y(y_value):
                        candidate = build_horizontal_candidate(y_value, interval_start, interval_end)
                        if candidate is not None:
                            candidates.append(candidate)
        else:
            lanes = (
                (min_x + edge_margin, checkbox_guard_bbox[0]),
                (checkbox_guard_bbox[2], max_x - edge_margin),
            )
            for lane_start, lane_end in lanes:
                for x_value in candidate_cross_values(lane_start, lane_end):
                    for interval_start, interval_end in polygon_intervals_at_x(x_value):
                        candidate = build_vertical_candidate(x_value, interval_start, interval_end)
                        if candidate is not None:
                            candidates.append(candidate)

        if not candidates:
            finish()
            return
        selected = max(candidates, key=lambda item: (item["available"], item["length"]))
        x1, y1, x2, y2 = selected["line"]
        canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            fill="#dc2626",
            width=line_width,
            arrow=tk.BOTH,
            arrowshape=arrowshape,
            tags=tags + ("hatch_one_way_arrow",),
        )
        canvas.create_line(
            x1,
            y1,
            x2,
            y2,
            fill="",
            width=hitbox_width,
            tags=tags + ("hatch_one_way_hitbox",),
        )
        finish(created=1)

    def _draw_hatch_edit_regions(self, canvas, display_regions, transform, color_legend: dict[str, str], *, viewport_bbox=None, simplify_tolerance: float = 0.0) -> None:
        selected_keys = set(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set())
        hover_key = str(self.__dict__.get("hatch_load_drag_hover_key") or "")
        for region_key, region, vertices in display_regions:
            if not self._hatch_points_intersect_viewport(vertices, viewport_bbox):
                continue
            selected = region_key in selected_keys
            is_hover = bool(hover_key and region_key == hover_key and not selected)
            has_load = bool(getattr(region, "load_name", None))
            fill = self._editable_region_display_color(region) if has_load else "#fef3c7"
            outline = "#1a73e8" if selected else ("#fbbc04" if is_hover else ("#b45309" if not has_load else "#374151"))
            draw_vertices = self._simplify_hatch_display_vertices(vertices, simplify_tolerance)
            points = [coord for xy in draw_vertices for coord in transform(*xy)]
            layer_tag = "hatch_edit_loaded" if has_load else "hatch_edit_unloaded"
            source_tag = "hatch_continuous_sync" if str(getattr(region, "source", "") or "") == "CONTINUOUS_SYNC" else "hatch_internal"
            polygon_options = {
                "outline": outline,
                "fill": fill,
                "width": 4 if selected or is_hover else 2,
                "joinstyle": tk.ROUND,
                "stipple": "" if has_load or is_hover else "gray25",
                "tags": ("hatch_edit_region", layer_tag, source_tag, f"edit_region:{region_key}"),
            }
            if is_hover:
                polygon_options["dash"] = (4, 2)
            item = canvas.create_polygon(points, **polygon_options)
            self.hatch_view_edit_region_items[region_key] = item
            label = str(getattr(region, "load_name", "") or "하중 미입력")
            color_legend.setdefault(fill, label)
            if has_load and self._is_one_way_distribution(getattr(region, "distribution", "")):
                angle = getattr(region, "one_way_angle", None)
                if angle in (None, ""):
                    angle = self._one_way_angle_from_vertices(getattr(region, "polygon_xy", ()) or vertices)
                if angle is not None:
                    self._draw_one_way_direction_handles(canvas, region_key, vertices, float(angle), transform, source="edit")
            cx, cy = self._polygon_centroid(vertices)
            tx, ty = transform(cx, cy)
            half_size, font_size, show_text = self._hatch_checkbox_canvas_metrics(vertices, transform)
            marker_width = max(1, int(round(_clamp(half_size * 0.25, 1.0, 2.0))))
            if is_hover:
                marker_width += 1
            marker_text = "V" if selected else ("+" if not has_load else "")
            if not show_text:
                marker_text = ""
            box_id = canvas.create_rectangle(
                tx - half_size,
                ty - half_size,
                tx + half_size,
                ty + half_size,
                outline="#1a73e8" if selected else ("#fbbc04" if is_hover else "#b45309"),
                fill="#ffffff",
                width=marker_width,
                tags=("hatch_edit_region", layer_tag, source_tag, f"edit_region:{region_key}"),
            )
            text_id = canvas.create_text(
                tx,
                ty,
                text=marker_text,
                fill="#1a73e8" if selected else "#b45309",
                font=("TkDefaultFont", font_size, "bold"),
                tags=("hatch_edit_region", layer_tag, source_tag, f"edit_region:{region_key}"),
            )
            self.__dict__.setdefault("hatch_view_edit_checkbox_items", {})[region_key] = (box_id, text_id)

    def _editable_region_display_color(self, region) -> str:
        key = str(getattr(region, "load_name", "") or getattr(region, "load_layer", "") or "INTERNAL")
        palette = (
            "#7dd3fc",
            "#86efac",
            "#fde047",
            "#fca5a5",
            "#c4b5fd",
            "#fdba74",
            "#67e8f9",
            "#f9a8d4",
            "#bef264",
            "#93c5fd",
        )
        return palette[sum(ord(ch) for ch in key) % len(palette)]

    def _hatch_story_display_offsets(self, regions) -> dict[str, tuple[float, float]]:
        if any(getattr(region.region, "placed_vertices", ()) for region in regions):
            return {}
        story_names = [str(getattr(region.region, "story_name", "") or "") for region in regions]
        unique_names = [name for name in [story.name for story in self.stories] if name in set(story_names)]
        unique_names.extend(name for name in story_names if name and name not in unique_names)
        if len(unique_names) <= 1:
            return {}
        all_points = [point for region in regions for point in self._region_vertices(region)]
        bbox = self._bbox_from_points_for_preview(all_points)
        if bbox is None:
            return {}
        step = max(bbox[2] - bbox[0], 1.0) * 1.35
        return {name: (index * step, 0.0) for index, name in enumerate(unique_names)}

    def _region_display_color(self, region) -> str:
        hatch = getattr(region, "region", None)
        explicit = str(getattr(hatch, "display_color", "") or "")
        if explicit.startswith("#") and len(explicit) == 7 and not self._hatch_color_is_near_white(explicit):
            return explicit
        key = self._region_color_label(region)
        palette = (
            "#7dd3fc",
            "#86efac",
            "#fde047",
            "#fca5a5",
            "#c4b5fd",
            "#fdba74",
            "#67e8f9",
            "#f9a8d4",
            "#bef264",
            "#93c5fd",
        )
        index = sum(ord(ch) for ch in key) % len(palette)
        return palette[index]

    def _hatch_color_is_near_white(self, color: str) -> bool:
        try:
            red = int(color[1:3], 16)
            green = int(color[3:5], 16)
            blue = int(color[5:7], 16)
        except Exception:
            return False
        return red >= 238 and green >= 238 and blue >= 238

    def _region_color_label(self, region) -> str:
        load_name = str(getattr(getattr(region, "load", None), "real_name", "") or "")
        layer = str(getattr(getattr(region, "region", None), "layer", "") or "")
        return load_name or layer or "해치"

    def _polygon_centroid(self, points: list[tuple[float, float]]) -> tuple[float, float]:
        if not points:
            return (0.0, 0.0)
        area = 0.0
        cx = 0.0
        cy = 0.0
        for index, start in enumerate(points):
            end = points[(index + 1) % len(points)]
            cross = start[0] * end[1] - end[0] * start[1]
            area += cross
            cx += (start[0] + end[0]) * cross
            cy += (start[1] + end[1]) * cross
        if abs(area) <= 1.0e-12:
            return (sum(x for x, _y in points) / len(points), sum(y for _x, y in points) / len(points))
        area *= 0.5
        return (cx / (6.0 * area), cy / (6.0 * area))

    def _draw_hatch_legend(self, canvas, color_legend: dict[str, str], content_width: float) -> None:
        if not color_legend:
            return
        x = max(float(content_width) - 190.0, 12.0)
        y = 12.0
        canvas.create_text(x, y, text="레이어/하중 색상", anchor="nw", fill="#333333", font=("TkDefaultFont", 9, "bold"))
        y += 20.0
        for color, label in list(color_legend.items())[:10]:
            canvas.create_rectangle(x, y, x + 16, y + 12, outline="#555555", fill=color)
            canvas.create_text(x + 22, y - 1, text=str(label)[:24], anchor="nw", fill="#333333", font=("TkDefaultFont", 9))
            y += 18.0

    def _hatch_preview_info_text(self) -> str:
        selected_keys = self._selected_hatch_region_keys_for_continuous_info()
        if len(selected_keys) > 1:
            common_range = self._common_continuous_story_range_for_selected_regions(selected_keys)
            story_names = self._selected_edit_region_story_names(selected_keys)
            story_text = f" | Story {', '.join(story_names)}" if story_names else ""
            return (
                f"선택 영역 {len(selected_keys)}개{story_text} | "
                f"공통 연속층 적용 가능 {self._format_story_range_text(common_range)}"
            )
        region_key = str(self.__dict__.get("hatch_view_selected_region_key") or "")
        if not region_key:
            if selected_keys:
                story_names = self._selected_edit_region_story_names(selected_keys)
                story_text = f"Story {', '.join(story_names)}" if story_names else "Story -"
                return f"선택 폐합영역 | {story_text} | 하중을 선택하면 내부 입력으로 자동 저장됩니다."
            return "전체 해치를 표시 중입니다. 연속층 적용 가능한 해치 중앙의 체크 영역을 클릭하세요."
        region = (self.__dict__.get("hatch_view_region_by_key", {}) or {}).get(region_key)
        check = (self.__dict__.get("continuous_hatch_checks", {}) or {}).get(region_key, {})
        if region is None:
            return "선택 해치 정보를 찾을 수 없습니다."
        load_name = str(getattr(getattr(region, "load", None), "real_name", "") or "")
        hatch = region.region
        targets = ", ".join(tuple(check.get("applicable_targets", ()) or ())) or "-"
        blocked = tuple(check.get("blocked_targets", ()) or ())[:4]
        blocked_text = " / ".join(f"{name}:{reason}" for name, reason in blocked) or "-"
        return (
            f"선택 해치 | Story {getattr(hatch, 'story_name', '') or '-'} | "
            f"Layer {getattr(hatch, 'layer', '') or '-'} | 하중 {load_name or '-'} | "
            f"연속층 {'가능' if check.get('can_select') else '불가'} | 대상 {targets} | 제외 {blocked_text}"
        )

    def _hatch_canvas_transform(self, bbox, width: int, height: int, padding: int = 40, *, zoom_factor: float = 1.0):
        _ = padding, zoom_factor
        metrics = self._hatch_canvas_transform_metrics(bbox, width, height)

        def transform(x: float, y: float) -> tuple[float, float]:
            return (
                metrics["offset_x"] + (float(x) - metrics["min_x"]) * metrics["scale"],
                metrics["offset_y"] + (metrics["max_y"] - float(y)) * metrics["scale"],
            )

        return transform, metrics["content_width"], metrics["content_height"]

    def _hatch_canvas_transform_metrics(self, bbox, width: int, height: int) -> dict[str, float]:
        min_x, min_y, max_x, max_y = self._normalized_hatch_bbox(bbox)
        model_width = max(max_x - min_x, 1.0e-9)
        model_height = max(max_y - min_y, 1.0e-9)
        content_width = max(float(width), 1.0)
        content_height = max(float(height), 1.0)
        scale = min(content_width / model_width, content_height / model_height)
        drawn_width = model_width * scale
        drawn_height = model_height * scale
        return {
            "min_x": min_x,
            "min_y": min_y,
            "max_x": max_x,
            "max_y": max_y,
            "scale": scale,
            "offset_x": (content_width - drawn_width) / 2.0,
            "offset_y": (content_height - drawn_height) / 2.0,
            "content_width": content_width,
            "content_height": content_height,
        }

    def _hatch_canvas_to_world(self, x: float, y: float, bbox, width: int, height: int) -> tuple[float, float]:
        metrics = self._hatch_canvas_transform_metrics(bbox, width, height)
        scale = max(float(metrics["scale"]), 1.0e-12)
        return (
            metrics["min_x"] + (float(x) - metrics["offset_x"]) / scale,
            metrics["max_y"] - (float(y) - metrics["offset_y"]) / scale,
        )

    def _cancel_scheduled_hatch_preview_render(self) -> None:
        after_id = self.__dict__.get("_hatch_preview_render_after_id")
        self._hatch_preview_render_after_id = None
        if after_id is None:
            return
        canvas = self.__dict__.get("hatch_preview_canvas")
        after_cancel = getattr(canvas, "after_cancel", None) if canvas is not None else None
        if callable(after_cancel):
            try:
                after_cancel(after_id)
            except Exception:
                pass

    def _schedule_hatch_preview_render(self) -> None:
        if self.__dict__.get("_hatch_preview_render_after_id") is not None:
            return
        canvas = self.__dict__.get("hatch_preview_canvas")
        after = getattr(canvas, "after", None) if canvas is not None else None
        if not callable(after):
            self._render_hatch_preview()
            return

        def render_scheduled() -> None:
            self._hatch_preview_render_after_id = None
            self._render_hatch_preview()

        try:
            self._hatch_preview_render_after_id = after(16, render_scheduled)
        except Exception:
            self._hatch_preview_render_after_id = None
            self._render_hatch_preview()

    def _on_hatch_view_mousewheel(self, event):
        canvas = getattr(self, "hatch_preview_canvas", None) or getattr(event, "widget", None)
        if canvas is None:
            return None
        fit_bbox = self.__dict__.get("hatch_view_fit_bbox")
        view_bbox = self.__dict__.get("hatch_view_view_bbox") or fit_bbox
        if fit_bbox is None or view_bbox is None:
            return "break"
        delta = int(getattr(event, "delta", 0) or 0)
        if delta == 0:
            button = getattr(event, "num", None)
            delta = 120 if button == 4 else -120 if button == 5 else 0
        if delta == 0:
            return "break"
        width = max(float(canvas.winfo_width() or 0), 1.0)
        height = max(float(canvas.winfo_height() or 0), 1.0)
        min_x, min_y, max_x, max_y = self._normalized_hatch_bbox(view_bbox)
        fit_min_x, fit_min_y, fit_max_x, fit_max_y = self._normalized_hatch_bbox(fit_bbox)
        cursor_x = _clamp(float(getattr(event, "x", width / 2.0)), 0.0, width)
        cursor_y = _clamp(float(getattr(event, "y", height / 2.0)), 0.0, height)
        world_x, world_y = self._hatch_canvas_to_world(cursor_x, cursor_y, view_bbox, width, height)
        factor = 0.82 if delta > 0 else 1.22
        current_width = max(max_x - min_x, 1.0e-9)
        current_height = max(max_y - min_y, 1.0e-9)
        target_width = current_width * factor
        target_height = current_height * factor
        fit_width = max(fit_max_x - fit_min_x, 1.0e-9)
        fit_height = max(fit_max_y - fit_min_y, 1.0e-9)
        target_width = _clamp(target_width, fit_width / 200.0, fit_width * 8.0)
        target_height = _clamp(target_height, fit_height / 200.0, fit_height * 8.0)
        ratio_x = (world_x - min_x) / current_width
        ratio_y = (world_y - min_y) / current_height
        new_min_x = world_x - ratio_x * target_width
        new_min_y = world_y - ratio_y * target_height
        self.hatch_view_view_bbox = (
            new_min_x,
            new_min_y,
            new_min_x + target_width,
            new_min_y + target_height,
        )
        self.hatch_view_manual_zoom = True
        self._schedule_hatch_preview_render()
        return "break"

    def _event_has_ctrl(self, event) -> bool:
        return bool(int(getattr(event, "state", 0) or 0) & 0x0004)

    def _hatch_selection_snapshot(self) -> tuple[frozenset[str], frozenset[str]]:
        dxf_keys = {
            str(key or "")
            for key in tuple(self.__dict__.get("hatch_view_selected_region_keys", set()) or set())
            if str(key or "")
        }
        selected_key = str(self.__dict__.get("hatch_view_selected_region_key") or "")
        if selected_key:
            dxf_keys.add(selected_key)
        edit_keys = {
            str(key or "")
            for key in tuple(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set())
            if str(key or "")
        }
        return frozenset(dxf_keys), frozenset(edit_keys)

    def _update_hatch_selection_visuals(self, previous_selection=None) -> bool:
        canvas = getattr(self, "hatch_preview_canvas", None)
        if canvas is None:
            return False
        winfo_exists = getattr(canvas, "winfo_exists", None)
        if callable(winfo_exists):
            try:
                if not winfo_exists():
                    return False
            except Exception:
                return False
        current_dxf, current_edit = self._hatch_selection_snapshot()
        if previous_selection is None:
            previous_dxf: frozenset[str] = frozenset()
            previous_edit: frozenset[str] = frozenset()
            dxf_keys = set(current_dxf)
            edit_keys = set(current_edit)
        else:
            try:
                previous_dxf = frozenset(str(key or "") for key in tuple(previous_selection[0] or ()) if str(key or ""))
                previous_edit = frozenset(str(key or "") for key in tuple(previous_selection[1] or ()) if str(key or ""))
            except Exception:
                return False
            dxf_keys = set(previous_dxf) | set(current_dxf)
            edit_keys = set(previous_edit) | set(current_edit)
        try:
            for key in dxf_keys:
                if not self._update_dxf_hatch_selection_visual(canvas, key, key in current_dxf):
                    return False
            for key in edit_keys:
                if not self._update_edit_hatch_selection_visual(canvas, key, key in current_edit):
                    return False
        except Exception:
            return False
        return True

    def _update_dxf_hatch_selection_visual(self, canvas, region_key: str, selected: bool) -> bool:
        key = str(region_key or "")
        if not key:
            return True
        region_items = self.__dict__.get("hatch_view_region_items", {}) or {}
        checkbox_items = self.__dict__.get("hatch_view_checkbox_items", {}) or {}
        if key not in region_items and key not in checkbox_items:
            return key not in (self.__dict__.get("hatch_view_region_by_key", {}) or {})
        item_id = region_items.get(key)
        checkbox_ids = tuple(checkbox_items.get(key, ()) or ())
        if item_id is None or len(checkbox_ids) < 2:
            return False
        hover_key = str(self.__dict__.get("hatch_load_drag_hover_key") or "")
        is_hover = bool(hover_key and hover_key == key and not selected)
        outline = "#1a73e8" if selected else ("#fbbc04" if is_hover else "#374151")
        if not self._canvas_itemconfig(canvas, item_id, outline=outline, width=4 if selected or is_hover else 2, dash=(4, 2) if is_hover else ""):
            return False
        check = (self.__dict__.get("continuous_hatch_checks", {}) or {}).get(key, {}) or {}
        can_select = bool(check.get("can_select"))
        marker_text = "V" if selected else ("" if can_select else "i")
        if not self._canvas_itemconfig(canvas, checkbox_ids[0], outline="#1a73e8" if can_select else "#9ca3af", fill="#ffffff" if can_select else "#f3f4f6"):
            return False
        return self._canvas_itemconfig(canvas, checkbox_ids[1], text=marker_text, fill="#1a73e8" if selected or can_select else "#6b7280")

    def _update_edit_hatch_selection_visual(self, canvas, region_key: str, selected: bool) -> bool:
        key = str(region_key or "")
        if not key:
            return True
        region_items = self.__dict__.get("hatch_view_edit_region_items", {}) or {}
        checkbox_items = self.__dict__.get("hatch_view_edit_checkbox_items", {}) or {}
        if key not in region_items and key not in checkbox_items:
            return key not in (self.__dict__.get("hatch_view_edit_region_by_key", {}) or {})
        item_id = region_items.get(key)
        checkbox_ids = tuple(checkbox_items.get(key, ()) or ())
        if item_id is None or len(checkbox_ids) < 2:
            return False
        region = (self.__dict__.get("hatch_view_edit_region_by_key", {}) or {}).get(key) or self._editable_hatch_region_by_key(key)
        has_load = bool(getattr(region, "load_name", None))
        hover_key = str(self.__dict__.get("hatch_load_drag_hover_key") or "")
        is_hover = bool(hover_key and hover_key == key and not selected)
        outline = "#1a73e8" if selected else ("#fbbc04" if is_hover else ("#b45309" if not has_load else "#374151"))
        if not self._canvas_itemconfig(canvas, item_id, outline=outline, width=4 if selected or is_hover else 2, dash=(4, 2) if is_hover else ""):
            return False
        marker_text = "V" if selected else ("+" if not has_load else "")
        if not self._canvas_itemconfig(canvas, checkbox_ids[0], outline="#1a73e8" if selected else ("#fbbc04" if is_hover else "#b45309")):
            return False
        return self._canvas_itemconfig(canvas, checkbox_ids[1], text=marker_text, fill="#1a73e8" if selected else "#b45309")

    def _canvas_itemconfig(self, canvas, item_id, **kwargs) -> bool:
        try:
            itemconfig = getattr(canvas, "itemconfig", None) or getattr(canvas, "itemconfigure", None)
            if itemconfig is None:
                return False
            itemconfig(item_id, **kwargs)
            return True
        except Exception:
            return False

    def _select_dxf_hatch_regions(self, keys, *, mode: str = "replace") -> None:
        key_list = [str(key) for key in tuple(keys or ()) if str(key)]
        current = set(self.__dict__.get("hatch_view_selected_region_keys", set()) or set())
        selected = select_regions_by_keys(key_list, mode=mode, current=current)
        self.hatch_view_selected_region_keys = set(selected)
        if key_list and key_list[-1] in selected:
            self.hatch_view_selected_region_key = key_list[-1]
        else:
            self.hatch_view_selected_region_key = sorted(selected)[0] if selected else None
        if selected and mode == "replace":
            self.hatch_view_selected_edit_region_keys = set()
            for state in (self.__dict__.get("hatch_edit_states_by_story", {}) or {}).values():
                state.selected_region_keys = set()
                state.selected_cell_ids = set()
        self._sync_continuous_base_story_from_selection()

    def _clear_hatch_view_selection(self) -> None:
        self.hatch_view_selected_region_key = None
        self.hatch_view_selected_region_keys = set()
        self.hatch_view_selected_edit_region_keys = set()
        for state in (self.__dict__.get("hatch_edit_states_by_story", {}) or {}).values():
            state.selected_region_keys = set()
            state.selected_cell_ids = set()
        self._sync_continuous_base_story_from_selection()

    def _selected_hatch_story_names(self) -> tuple[str, ...]:
        names: list[str] = []
        region_by_key = self.__dict__.get("hatch_view_region_by_key", {}) or {}
        for key in tuple(self.__dict__.get("hatch_view_selected_region_keys", set()) or set()):
            region = region_by_key.get(str(key))
            name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
            if name and name not in names:
                names.append(name)
        selected_key = str(self.__dict__.get("hatch_view_selected_region_key") or "")
        if selected_key:
            region = region_by_key.get(selected_key)
            name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
            if name and name not in names:
                names.append(name)
        edit_region_by_key = self.__dict__.get("hatch_view_edit_region_by_key", {}) or {}
        for key in tuple(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set()):
            region = edit_region_by_key.get(str(key)) or self._editable_hatch_region_by_key(str(key))
            name = str(getattr(region, "story_name", "") or "")
            if name and name not in names:
                names.append(name)
        return tuple(names)

    def _sync_continuous_base_story_from_selection(self) -> str:
        story_names = self._selected_hatch_story_names()
        selected_var = self.__dict__.get("selected_hatch_story_var")
        base_var = self.__dict__.get("continuous_base_story_name")
        if len(story_names) == 1:
            story_name = story_names[0]
            if base_var is not None:
                try:
                    base_var.set(story_name)
                except Exception:
                    pass
            if selected_var is not None:
                try:
                    selected_var.set(f"기준 STORY: {story_name}")
                except Exception:
                    pass
            return story_name
        if len(story_names) > 1:
            if base_var is not None:
                try:
                    base_var.set("")
                except Exception:
                    pass
            if selected_var is not None:
                try:
                    selected_var.set("기준 STORY: 여러 Story 선택")
                except Exception:
                    pass
            return ""
        if selected_var is not None:
            try:
                selected_var.set("기준 STORY: 선택 해치층 자동")
            except Exception:
                pass
        return ""

    def _on_hatch_view_middle_pan_start(self, event):
        self.hatch_view_middle_pan_active = True
        self.hatch_view_middle_pan_last = (float(getattr(event, "x", 0)), float(getattr(event, "y", 0)))
        canvas = getattr(self, "hatch_preview_canvas", None) or getattr(event, "widget", None)
        if canvas is not None:
            try:
                canvas.configure(cursor="fleur")
            except Exception:
                pass
        return "break"

    def _on_hatch_view_middle_pan_drag(self, event):
        if not bool(self.__dict__.get("hatch_view_middle_pan_active", False)):
            return "break"
        canvas = getattr(self, "hatch_preview_canvas", None) or getattr(event, "widget", None)
        view_bbox = self.__dict__.get("hatch_view_view_bbox") or self.__dict__.get("hatch_view_fit_bbox")
        last = self.__dict__.get("hatch_view_middle_pan_last")
        if canvas is None or view_bbox is None or last is None:
            return "break"
        x = float(getattr(event, "x", 0))
        y = float(getattr(event, "y", 0))
        dx_pixel = x - float(last[0])
        dy_pixel = y - float(last[1])
        width = max(float(canvas.winfo_width() or 0), 1.0)
        height = max(float(canvas.winfo_height() or 0), 1.0)
        min_x, min_y, max_x, max_y = self._normalized_hatch_bbox(view_bbox)
        metrics = self._hatch_canvas_transform_metrics(view_bbox, width, height)
        scale = max(float(metrics["scale"]), 1.0e-12)
        world_dx = -dx_pixel / scale
        world_dy = dy_pixel / scale
        self.hatch_view_view_bbox = (
            min_x + world_dx,
            min_y + world_dy,
            max_x + world_dx,
            max_y + world_dy,
        )
        self.hatch_view_middle_pan_last = (x, y)
        self.hatch_view_manual_zoom = True
        self._schedule_hatch_preview_render()
        return "break"

    def _on_hatch_view_middle_pan_end(self, event):
        self.hatch_view_middle_pan_active = False
        self.hatch_view_middle_pan_last = None
        canvas = getattr(self, "hatch_preview_canvas", None) or getattr(event, "widget", None)
        if canvas is not None:
            try:
                canvas.configure(cursor="")
            except Exception:
                pass
        return "break"

    def _bbox_from_points_for_preview(self, points) -> tuple[float, float, float, float] | None:
        pts = [(float(x), float(y)) for x, y in points]
        if not pts:
            return None
        min_x = min(x for x, _y in pts)
        max_x = max(x for x, _y in pts)
        min_y = min(y for _x, y in pts)
        max_y = max(y for _x, y in pts)
        pad = max(max_x - min_x, max_y - min_y, 1.0) * 0.08
        return (min_x - pad, min_y - pad, max_x + pad, max_y + pad)

    def _one_way_handle_region_key_from_event(self, event) -> tuple[str, str] | None:
        direct_key = str(getattr(event, "region_key", "") or "")
        direct_source = str(getattr(event, "source", "") or "")
        if direct_key and direct_source:
            return direct_key, direct_source
        canvas = getattr(self, "hatch_preview_canvas", None) or getattr(event, "widget", None)
        if canvas is None:
            return None
        item_ids = []
        try:
            item_ids = list(canvas.find_withtag("current"))
        except Exception:
            item_ids = []
        for item_id in item_ids:
            try:
                tags = tuple(canvas.gettags(item_id))
            except Exception:
                tags = ()
            if "hatch_one_way_handle" not in tags:
                continue
            region_key = ""
            source = ""
            for tag in tags:
                text = str(tag)
                if text.startswith("one_way_region:"):
                    region_key = text.split(":", 1)[1]
                elif text.startswith("one_way_source:"):
                    source = text.split(":", 1)[1]
            if region_key and source:
                return region_key, source
        return None

    def _cancel_pending_one_way_click(self) -> None:
        after_id = self.__dict__.get("hatch_one_way_click_after_id")
        self.hatch_one_way_click_after_id = None
        if after_id is None:
            return
        try:
            self.after_cancel(after_id)
        except Exception:
            pass

    def _on_one_way_handle_click(self, event):
        target = self._one_way_handle_region_key_from_event(event)
        if target is None:
            return "break"
        self._cancel_pending_one_way_click()

        def rotate() -> None:
            self.hatch_one_way_click_after_id = None
            self._rotate_one_way_region_angle(*target)

        after = getattr(self, "after", None)
        if callable(after):
            self.hatch_one_way_click_after_id = after(220, rotate)
        else:
            rotate()
        return "break"

    def _on_one_way_handle_double_click(self, event):
        target = self._one_way_handle_region_key_from_event(event)
        self._cancel_pending_one_way_click()
        if target is None:
            return "break"
        region_key, source = target
        current_angle = self._current_one_way_region_angle(region_key, source)
        angle = self._ask_one_way_angle(current_angle)
        if angle is None:
            return "break"
        normalized = float(angle) % 180.0
        targets = self._one_way_angle_change_targets(source, region_key)
        if not targets:
            self._set_hatch_direct_status("각도를 변경할 ONE-WAY 해치가 없습니다.")
            return "break"
        if len(targets) > 1:
            status_message = f"선택된 ONE-WAY 해치 {len(targets)}개의 재하 각도를 {normalized:.1f}도로 변경했습니다."
        else:
            status_message = f"ONE-WAY 하중 각도를 {normalized:.1f}도로 변경했습니다."
        self._set_one_way_regions_angle(targets, normalized, status_message=status_message, focus_region_key=region_key)
        return "break"

    def _ask_one_way_angle(self, current_angle: float | None) -> float | None:
        try:
            return simpledialog.askfloat(
                "ONE-WAY 하중 각도",
                "1WAY 하중 재하 각도(global XY 기준, degree)를 입력하세요.\n예: X방향=0, Y방향=90",
                initialvalue=0.0 if current_angle is None else float(current_angle),
                parent=self,
            )
        except Exception:
            return None

    def _rotate_one_way_region_angle(self, region_key: str, source: str) -> None:
        current = self._current_one_way_region_angle(region_key, source)
        if current is None:
            current = 0.0
        self._set_one_way_region_angle(
            region_key,
            source,
            (float(current) + 90.0) % 180.0,
            status_message="ONE-WAY 하중 각도를 90도 회전했습니다.",
        )

    def _current_one_way_region_angle(self, region_key: str, source: str) -> float | None:
        if str(source) == "dxf":
            region = self._dxf_region_by_key(region_key)
            load = getattr(region, "load", None)
            angle = getattr(load, "one_way_angle_deg", None)
            if angle not in (None, ""):
                return float(angle) % 180.0
            return self._one_way_angle_from_vertices(self._dxf_region_polygon_vertices_for_one_way(region_key))
        region = self._editable_hatch_region_by_key(region_key)
        angle = getattr(region, "one_way_angle", None)
        if angle not in (None, ""):
            return float(angle) % 180.0
        return self._one_way_angle_from_vertices(getattr(region, "polygon_xy", ()) if region is not None else ())

    def _region_has_one_way_load(self, source: str, region_key: str) -> bool:
        if str(source) == "dxf":
            region = self._dxf_region_by_key(region_key)
            load = getattr(region, "load", None)
            return load is not None and self._is_one_way_distribution(getattr(load, "distribution", ""))
        region = self._editable_hatch_region_by_key(region_key)
        return (
            region is not None
            and bool(str(getattr(region, "load_name", "") or ""))
            and self._is_one_way_distribution(getattr(region, "distribution", ""))
        )

    def _one_way_angle_change_targets(self, clicked_source: str, clicked_key: str) -> list[tuple[str, str]]:
        clicked = (str(clicked_source or ""), str(clicked_key or ""))
        selected: list[tuple[str, str]] = []
        selected.extend(("edit", key) for key in self._selected_edit_region_keys())
        selected.extend(("dxf", key) for key in self._selected_dxf_region_keys())
        candidates = selected if clicked in selected else [clicked]
        targets: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for source, key in candidates:
            source = str(source or "")
            key = str(key or "")
            item = (source, key)
            if not source or not key or item in seen:
                continue
            seen.add(item)
            if self._region_has_one_way_load(source, key):
                targets.append(item)
        return targets

    def _set_one_way_regions_angle(
        self,
        targets: list[tuple[str, str]] | tuple[tuple[str, str], ...],
        angle: float,
        *,
        status_message: str,
        focus_region_key: str | None = None,
    ) -> bool:
        normalized = float(angle) % 180.0
        changed_keys: list[str] = []
        edit_changed = False
        command_label = "ONE-WAY 다중 각도 변경" if len(tuple(targets or ())) > 1 else "ONE-WAY 각도 변경"
        with self._hatch_edit_command(command_label):
            for source, key in tuple(targets or ()):
                source = str(source or "")
                key = str(key or "")
                if not key:
                    continue
                if source == "dxf":
                    region = self._dxf_region_by_key(key)
                    load = getattr(region, "load", None)
                    if region is None or load is None or not self._is_one_way_distribution(getattr(load, "distribution", "")):
                        continue
                    current_angle = getattr(load, "one_way_angle_deg", None)
                    if current_angle not in (None, "") and abs((float(current_angle) % 180.0) - normalized) <= 1.0e-9:
                        continue
                    region.load = replace(load, distribution=DISTRIBUTION_ONE_WAY, one_way_angle_deg=normalized)
                    region.status = "OK"
                    changed_keys.append(key)
                    continue
                for state in (self.__dict__.get("hatch_edit_states_by_story", {}) or {}).values():
                    region = getattr(state, "regions_by_key", {}).get(key)
                    if region is None or not self._is_one_way_distribution(getattr(region, "distribution", "")):
                        continue
                    current_angle = getattr(region, "one_way_angle", None)
                    if current_angle not in (None, "") and abs((float(current_angle) % 180.0) - normalized) <= 1.0e-9:
                        continue
                    state.regions_by_key[key] = replace(region, distribution=DISTRIBUTION_ONE_WAY, one_way_angle=normalized)
                    changed_keys.append(key)
                    edit_changed = True
                    break
            if edit_changed:
                self._refresh_hatch_edit_region_index()
            if changed_keys:
                self._sync_load_to_continuous_targets_for_region_keys(tuple(changed_keys))
        if changed_keys:
            focus_key = str(focus_region_key or changed_keys[0])
            self._set_hatch_direct_status(status_message)
            self._render_hatch_preview(focus_region_key=focus_key)
            self._refresh_selected_hatch_continuous_info()
            return True
        self._set_hatch_direct_status("각도를 변경할 ONE-WAY 해치가 없습니다.")
        return False

    def _set_one_way_region_angle(self, region_key: str, source: str, angle: float, *, status_message: str) -> None:
        key = str(region_key or "")
        source = str(source or "")
        self._set_one_way_regions_angle(((source, key),), angle, status_message=status_message, focus_region_key=key)

    def _log_hatch_view_selection_performance(
        self,
        *,
        started_at: float,
        region_key: str = "",
        mode: str = "",
        visual_elapsed_ms: float = 0.0,
        continuous_elapsed_ms: float = 0.0,
        below_cache_hits_before: int = 0,
        below_cache_misses_before: int = 0,
    ) -> None:
        elapsed_ms = (time.perf_counter() - float(started_at)) * 1000.0
        if elapsed_ms < 100.0:
            return
        logger = self.__dict__.get("logger")
        if logger is None:
            return
        below_hits = int(self.__dict__.get("_continuous_below_allowed_reason_cache_hits", 0) or 0) - int(below_cache_hits_before or 0)
        below_misses = int(self.__dict__.get("_continuous_below_allowed_reason_cache_misses", 0) or 0) - int(below_cache_misses_before or 0)
        try:
            logger.debug(
                "HATCH VIEW selection slow: region=%s mode=%s total=%.1fms visual=%.1fms continuous=%.1fms below_cache_hit=%s below_cache_miss=%s",
                str(region_key or ""),
                str(mode or ""),
                elapsed_ms,
                float(visual_elapsed_ms),
                float(continuous_elapsed_ms),
                below_hits,
                below_misses,
            )
        except Exception:
            pass

    def _on_hatch_view_click(self, event) -> None:
        canvas = getattr(self, "hatch_preview_canvas", None)
        if canvas is None:
            return
        started_at = time.perf_counter()
        visual_elapsed_ms = 0.0
        continuous_elapsed_ms = 0.0
        below_hits_before = int(self.__dict__.get("_continuous_below_allowed_reason_cache_hits", 0) or 0)
        below_misses_before = int(self.__dict__.get("_continuous_below_allowed_reason_cache_misses", 0) or 0)
        region_key_for_log = ""
        selection_mode_for_log = ""
        try:
            if self._one_way_handle_region_key_from_event(event) is not None:
                return "break"
            previous_selection = self._hatch_selection_snapshot()
            item_ids = list(canvas.find_withtag("current"))
            if not item_ids:
                item_ids = list(canvas.find_closest(canvas.canvasx(event.x), canvas.canvasy(event.y)))
            dummy_issue_key = ""
            for item_id in item_ids:
                for tag in canvas.gettags(item_id):
                    if str(tag).startswith("dummy_issue:"):
                        dummy_issue_key = str(tag).split(":", 1)[1]
                        break
                if dummy_issue_key:
                    break
            if dummy_issue_key:
                self._select_dummy_issue(dummy_issue_key)
                return "break"
            region_key = ""
            for item_id in item_ids:
                for tag in canvas.gettags(item_id):
                    if str(tag).startswith("region:"):
                        region_key = str(tag).split(":", 1)[1]
                        break
                if region_key:
                    break
            edit_region_key = ""
            for item_id in item_ids:
                for tag in canvas.gettags(item_id):
                    if str(tag).startswith("edit_region:"):
                        edit_region_key = str(tag).split(":", 1)[1]
                        break
                if edit_region_key:
                    break
            if edit_region_key:
                self._clear_dummy_issue_selection(update_overlay=False)
                mode = "toggle" if self._event_has_ctrl(event) else "replace"
                region_key_for_log = edit_region_key
                selection_mode_for_log = f"edit:{mode}"
                self._select_hatch_edit_regions([edit_region_key], mode=mode, refresh_continuous=False)
                region = self.hatch_view_edit_region_by_key.get(edit_region_key)
                story_name = str(getattr(region, "story_name", "") or "")
                story_var = self.__dict__.get("hatch_view_selected_story_var")
                if story_name and story_var is not None:
                    story_var.set(story_name)
                visual_started = time.perf_counter()
                if not self._update_hatch_selection_visuals(previous_selection):
                    self._render_hatch_preview()
                visual_elapsed_ms += (time.perf_counter() - visual_started) * 1000.0
                if mode == "toggle":
                    self._schedule_selected_hatch_continuous_refresh(180)
                else:
                    continuous_started = time.perf_counter()
                    self._refresh_selected_hatch_continuous_info()
                    continuous_elapsed_ms += (time.perf_counter() - continuous_started) * 1000.0
                return
            if not region_key:
                self._clear_dummy_issue_selection(update_overlay=False)
                selection_mode_for_log = "clear"
                if not self._event_has_ctrl(event):
                    self._clear_hatch_view_selection()
                    visual_started = time.perf_counter()
                    if not self._update_hatch_selection_visuals(previous_selection):
                        self._render_hatch_preview()
                    visual_elapsed_ms += (time.perf_counter() - visual_started) * 1000.0
                    continuous_started = time.perf_counter()
                    self._refresh_selected_hatch_continuous_info()
                    continuous_elapsed_ms += (time.perf_counter() - continuous_started) * 1000.0
                return
            mode = "toggle" if self._event_has_ctrl(event) else "replace"
            self._clear_dummy_issue_selection(update_overlay=False)
            region_key_for_log = region_key
            selection_mode_for_log = f"dxf:{mode}"
            if mode == "replace":
                self._cancel_scheduled_hatch_continuous_refresh()
            self._select_dxf_hatch_regions([region_key], mode=mode)
            selected_keys = set(self.__dict__.get("hatch_view_selected_region_keys", set()) or set())
            if mode == "toggle":
                visual_started = time.perf_counter()
                if not self._update_hatch_selection_visuals(previous_selection):
                    self._render_hatch_preview(focus_region_key=region_key)
                visual_elapsed_ms += (time.perf_counter() - visual_started) * 1000.0
                self._schedule_selected_hatch_continuous_refresh(180)
                return
            if region_key not in selected_keys:
                visual_started = time.perf_counter()
                if not self._update_hatch_selection_visuals(previous_selection):
                    self._render_hatch_preview()
                visual_elapsed_ms += (time.perf_counter() - visual_started) * 1000.0
                continuous_started = time.perf_counter()
                self._refresh_selected_hatch_continuous_info()
                continuous_elapsed_ms += (time.perf_counter() - continuous_started) * 1000.0
                return
            self._select_dxf_tree_region(region_key)
            self._load_selected_hatch_as_base_story(region_key)
            continuous_started = time.perf_counter()
            if region_key not in getattr(self, "continuous_hatch_checks", {}):
                self._recompute_hatch_continuous_checks()
            self._load_continuous_candidates_for_region(region_key, allow_unavailable=True)
            continuous_elapsed_ms += (time.perf_counter() - continuous_started) * 1000.0
            visual_started = time.perf_counter()
            if not self._update_hatch_selection_visuals(previous_selection):
                self._render_hatch_preview(focus_region_key=region_key)
            visual_elapsed_ms += (time.perf_counter() - visual_started) * 1000.0
        finally:
            self._log_hatch_view_selection_performance(
                started_at=started_at,
                region_key=region_key_for_log,
                mode=selection_mode_for_log,
                visual_elapsed_ms=visual_elapsed_ms,
                continuous_elapsed_ms=continuous_elapsed_ms,
                below_cache_hits_before=below_hits_before,
                below_cache_misses_before=below_misses_before,
            )

    def _on_hatch_view_button_press(self, event) -> None:
        if self._one_way_handle_region_key_from_event(event) is not None:
            self.hatch_view_drag_start = None
            self.hatch_view_drag_item = None
            self.hatch_view_drag_moved = False
            return "break"
        self.hatch_view_drag_start = (float(event.x), float(event.y))
        self.hatch_view_drag_moved = False
        canvas = getattr(self, "hatch_preview_canvas", None)
        if canvas is not None:
            try:
                canvas.focus_set()
            except Exception:
                pass
            self.hatch_view_drag_item = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#1a73e8", dash=())

    def _on_hatch_view_drag(self, event) -> None:
        canvas = getattr(self, "hatch_preview_canvas", None)
        start = self.__dict__.get("hatch_view_drag_start")
        item = self.__dict__.get("hatch_view_drag_item")
        if canvas is None or start is None or item is None:
            return
        if abs(float(event.x) - start[0]) > 3.0 or abs(float(event.y) - start[1]) > 3.0:
            self.hatch_view_drag_moved = True
        canvas.coords(item, start[0], start[1], event.x, event.y)
        if float(event.x) >= float(start[0]):
            self._canvas_itemconfig(canvas, item, outline="#1a73e8", dash=())
        else:
            self._canvas_itemconfig(canvas, item, outline="#16a34a", dash=(4, 3))

    def _on_hatch_view_button_release(self, event) -> None:
        if self._one_way_handle_region_key_from_event(event) is not None:
            self.hatch_view_drag_start = None
            self.hatch_view_drag_item = None
            self.hatch_view_drag_moved = False
            return "break"
        canvas = getattr(self, "hatch_preview_canvas", None)
        start = self.__dict__.get("hatch_view_drag_start")
        item = self.__dict__.get("hatch_view_drag_item")
        moved = bool(self.__dict__.get("hatch_view_drag_moved", False))
        if canvas is not None and item is not None:
            canvas.delete(item)
        self.hatch_view_drag_start = None
        self.hatch_view_drag_item = None
        self.hatch_view_drag_moved = False
        if not moved or start is None:
            self._on_hatch_view_click(event)
            return
        first = self._canvas_point_to_hatch_world(start[0], start[1])
        second = self._canvas_point_to_hatch_world(float(event.x), float(event.y))
        selection_rule = "window" if float(event.x) >= float(start[0]) else "crossing"
        mode = "add" if int(getattr(event, "state", 0) or 0) & 0x0004 else "replace"
        previous_selection = self._hatch_selection_snapshot()
        edit_candidates, dxf_candidates = self._hatch_drag_selection_candidates()
        edit_hits = select_polygon_keys_by_rect(
            edit_candidates,
            (first[0], first[1], second[0], second[1]),
            selection_rule=selection_rule,
        )
        dxf_hits = select_polygon_keys_by_rect(
            dxf_candidates,
            (first[0], first[1], second[0], second[1]),
            selection_rule=selection_rule,
        )
        if mode == "replace":
            self._clear_hatch_view_selection()
        self._select_hatch_edit_regions(edit_hits, mode="add", refresh_continuous=False)
        self._select_dxf_hatch_regions(dxf_hits, mode="add")
        if not self._update_hatch_selection_visuals(previous_selection):
            self._render_hatch_preview()
        self._schedule_selected_hatch_continuous_refresh(120)

    def _hatch_drag_selection_candidates(self):
        loaded_regions = list(self.__dict__.get("loaded_regions", ()) or ())
        if loaded_regions:
            dxf_sources = [
                (self._region_key(region, index=index), region)
                for index, region in enumerate(loaded_regions, start=1)
            ]
        else:
            dxf_sources = list((self.__dict__.get("hatch_view_region_by_key", {}) or {}).items())
        story_offsets: dict[str, tuple[float, float]] = {}
        try:
            if dxf_sources and self._hatch_view_is_all_story_display():
                story_offsets = self._hatch_story_display_offsets([region for _key, region in dxf_sources])
        except Exception:
            story_offsets = {}
        edit_selection_override = self.__dict__.get("_hatch_edit_regions_for_display_selection")
        edit_regions = (
            edit_selection_override()
            if callable(edit_selection_override)
            else self._hatch_edit_regions_for_display_selection(story_offsets)
        )
        edit_candidates = tuple(
            (str(region.region_key), tuple(region.polygon_xy))
            for region in edit_regions
            if str(getattr(region, "region_key", "") or "") and tuple(getattr(region, "polygon_xy", ()) or ())
        )
        if not dxf_sources:
            return edit_candidates, ()
        story_filter = self._hatch_view_story_filter()
        dxf_candidates: list[tuple[str, tuple[tuple[float, float], ...]]] = []
        for key, region in dxf_sources:
            story_name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
            if story_filter and story_name != story_filter:
                continue
            vertices = tuple(self._region_display_vertices(region, story_offsets))
            if vertices:
                dxf_candidates.append((str(key), vertices))
        return edit_candidates, tuple(dxf_candidates)

    def _canvas_point_to_hatch_world(self, x: float, y: float) -> tuple[float, float]:
        canvas = getattr(self, "hatch_preview_canvas", None)
        view_bbox = self.__dict__.get("hatch_view_view_bbox") or self.__dict__.get("hatch_view_fit_bbox")
        if canvas is None or view_bbox is None:
            return (float(x), float(y))
        width = max(float(canvas.winfo_width() or 0), 1.0)
        height = max(float(canvas.winfo_height() or 0), 1.0)
        return self._hatch_canvas_to_world(float(x), float(y), view_bbox, width, height)

    def _select_hatch_edit_regions(self, keys, *, mode: str = "replace", refresh_continuous: bool = True) -> None:
        current = set(self.__dict__.get("hatch_view_selected_edit_region_keys", set()) or set())
        selected = select_regions_by_keys(keys, mode=mode, current=current)
        self.hatch_view_selected_edit_region_keys = set(selected)
        if mode == "replace":
            self.hatch_view_selected_region_key = None
            self.hatch_view_selected_region_keys = set()
        if "hatch_edit_states_by_story" not in self.__dict__:
            self.hatch_edit_states_by_story = {}
        for state in self.hatch_edit_states_by_story.values():
            state.selected_region_keys = set(key for key in selected if key in state.regions_by_key)
            state.selected_cell_ids = {
                cell_id
                for key in state.selected_region_keys
                for cell_id in state.regions_by_key[key].cell_ids
            }
        if selected and mode != "replace":
            self.hatch_view_selected_region_key = None
        if refresh_continuous:
            self._refresh_selected_hatch_continuous_info()
        self._sync_continuous_base_story_from_selection()

    def _load_selected_hatch_as_base_story(self, region_key: str) -> None:
        region = self.hatch_view_region_by_key.get(region_key)
        story_name = str(getattr(getattr(region, "region", None), "story_name", "") or "")
        if story_name:
            self.continuous_base_story_name.set(story_name)
            if "selected_hatch_story_var" in self.__dict__:
                self.selected_hatch_story_var.set(f"기준 STORY: {story_name}")
            return
        if "selected_hatch_story_var" in self.__dict__:
            self.selected_hatch_story_var.set("기준 STORY: Story 미인식")
        if "continuous_apply_status_var" in self.__dict__:
            self._set_continuous_status("Story 미인식: ALL STORIES DXF metadata를 확인하세요.")

    def _select_dxf_tree_region(self, region_key: str) -> None:
        tree = self.__dict__.get("dxf_tree")
        if tree is None:
            return
        key_text = str(region_key or "")
        iid = (self.__dict__.get("dxf_tree_iid_by_region_key", {}) or {}).get(key_text)
        if iid:
            tree.selection_set(iid)
            tree.see(iid)
            return
        for iid, key in getattr(self, "dxf_region_key_by_tree_iid", {}).items():
            if key != key_text:
                continue
            self.__dict__.setdefault("dxf_tree_iid_by_region_key", {})[key_text] = iid
            tree.selection_set(iid)
            tree.see(iid)
            return

    def _load_continuous_candidates_for_region(self, region_key: str, *, silent: bool = False, allow_unavailable: bool = False) -> bool:
        check = self.continuous_hatch_checks.get(region_key)
        if check is None:
            self._recompute_hatch_continuous_checks()
            check = self.continuous_hatch_checks.get(region_key)
        if not check:
            if not silent:
                self._set_continuous_status("해치 연속층 검토 정보를 찾을 수 없습니다.")
            return False
        region = self.hatch_view_region_by_key.get(region_key) or check.get("region")
        base_story = str(check.get("base_story") or getattr(getattr(region, "region", None), "story_name", "") or "")
        if base_story:
            self.continuous_base_story_name.set(base_story)
        self.continuous_active_region_key = region_key
        self.continuous_active_region_keys = ()
        candidates = tuple(check.get("candidates", ()) or ())
        visible_targets = self._visible_applicable_targets_for_region_key(region_key)
        self._refresh_continuous_candidate_tree(base_story, candidates, region_key=region_key, visible_targets=visible_targets)
        if not silent:
            target_map = dict(self.__dict__.get("continuous_apply_targets_by_region", {}) or {})
            saved_targets = tuple(target_map.get(region_key, ()) or ())
            if saved_targets:
                self._set_continuous_status(f"자동 저장됨: {base_story} -> {', '.join(saved_targets)}")
            elif check.get("can_select"):
                applicable = len(tuple(check.get("applicable_targets", ()) or ()))
                self._set_continuous_status(f"{base_story} 기준 적용 가능층 {applicable}개: 적용층을 선택하면 자동 저장됩니다.")
            else:
                self._set_continuous_status(self._continuous_reason_user_text(SimpleNamespace(can_apply=False, reason=str(check.get("reason") or ""))))
        return bool(check.get("can_select"))

    def verify_continuous_apply_range(self, silent: bool = False) -> None:
        if not self.story_shape_profiles:
            self._ensure_typical_floor_analysis(reason="연속층 후보 자동 확인")
        if not self.story_shape_profiles:
            if not silent:
                messagebox.showwarning("층 형상 분석 필요", "모델/해치 정보를 확인한 뒤 해치를 다시 선택해 주세요.")
            return
        base_story = self.continuous_base_story_name.get().strip()
        region = self._selected_dxf_load_region()
        region_key = self.hatch_view_selected_region_key
        if not base_story:
            base_story = str(getattr(getattr(region, "region", None), "story_name", "") or "")
            self.continuous_base_story_name.set(base_story)
        if not base_story:
            if not silent:
                messagebox.showwarning("기준 Story 없음", "기준 Story 또는 검증된 DXF 해치를 선택해 주세요.")
            return
        ordered_story_names = [profile.story_name for profile in self.story_shape_profiles]
        candidates = evaluate_continuous_apply_candidates(
            self.story_shape_profiles,
            base_story_name=base_story,
            target_story_names=ordered_story_names,
            hatch_polygon_xy=self._region_vertices(region),
            typical_groups=self.typical_floor_groups,
            xy_tolerance=float(self.snap_tol_var.get() if hasattr(self, "snap_tol_var") else self.config_data.snap_tolerance),
        )
        visible_targets = self._visible_applicable_targets_for_region_key(region_key)
        self._refresh_continuous_candidate_tree(base_story, candidates, region_key=region_key, visible_targets=visible_targets)

    def _refresh_continuous_candidate_tree(
        self,
        base_story: str,
        candidates,
        *,
        region_key: str | None = None,
        visible_targets=None,
    ) -> None:
        if "continuous_tree" not in self.__dict__:
            return
        perf_token = self._hatch_perf_start("_refresh_continuous_candidate_tree")
        conflict_hits_before = int(self.__dict__.get("_continuous_load_conflict_reason_cache_hits", 0) or 0)
        conflict_misses_before = int(self.__dict__.get("_continuous_load_conflict_reason_cache_misses", 0) or 0)
        matching_hits_before = int(self.__dict__.get("_matching_target_cell_geometry_cache_hits", 0) or 0)
        matching_misses_before = int(self.__dict__.get("_matching_target_cell_geometry_cache_misses", 0) or 0)
        self.continuous_active_region_key = region_key or self.__dict__.get("continuous_active_region_key", "")
        profile_by_name = {profile.story_name: profile for profile in self.story_shape_profiles}
        base_profile = profile_by_name.get(base_story)
        applicable = 0
        target_map = dict(self.__dict__.get("continuous_apply_targets_by_region", {}) or {})
        saved_targets = tuple(target_map.get(region_key or "", ()) or ())
        selected_targets = set(saved_targets)
        active_region_keys = tuple(
            str(key or "")
            for key in tuple(self.__dict__.get("continuous_active_region_keys", ()) or ())
            if str(key or "")
        ) or ((str(region_key or ""),) if str(region_key or "") else ())
        if visible_targets is None:
            visible_targets_tuple = self._visible_applicable_targets_for_region_key(str(region_key or "")) if region_key else ()
        else:
            visible_targets_tuple = tuple(str(name or "") for name in tuple(visible_targets or ()) if str(name or ""))
        self._set_continuous_active_visible_targets(visible_targets_tuple)
        visible_target_set = set(visible_targets_tuple)
        restrict_to_visible_targets = bool(region_key) or visible_targets is not None
        selected_iids = []
        conflict_reason_by_target: dict[str, str] = {}
        candidate_by_iid: dict[str, object] = {}
        ordered_iids: list[str] = []
        rows: list[tuple[str, tuple[object, ...], tuple[str, ...]]] = []
        for index, candidate in enumerate(candidates, start=1):
            iid = f"continuous_{index}"
            target_name = str(getattr(candidate, "target_story_name", "") or "")
            display_can_apply = _continuous_candidate_can_apply(candidate) and (not restrict_to_visible_targets or target_name in visible_target_set)
            reason = str(getattr(candidate, "reason", "") or "")
            if _continuous_candidate_can_apply(candidate) and restrict_to_visible_targets and target_name not in visible_target_set:
                reason = self._continuous_target_visibility_reason(str(region_key or ""), target_name) or "공통 적용 가능층 아님"
            display_candidate = self._copy_continuous_candidate(candidate, can_apply=display_can_apply, reason=reason)
            conflict_reason = self._continuous_load_conflict_reason_for_region_keys(active_region_keys, target_name)
            if conflict_reason:
                conflict_reason_by_target[target_name] = conflict_reason
            display_reason = self._continuous_reason_user_text(display_candidate, conflict_reason=conflict_reason)
            candidate_by_iid[iid] = display_candidate
            ordered_iids.append(iid)
            target_profile = profile_by_name.get(display_candidate.target_story_name)
            area_ratio = self._profile_area_ratio(base_profile, target_profile)
            if display_candidate.can_apply:
                applicable += 1
            if display_candidate.target_story_name in selected_targets and display_candidate.can_apply:
                selected_iids.append(iid)
            values = (
                "✓" if display_candidate.target_story_name in selected_targets and display_candidate.can_apply else "",
                display_candidate.target_story_name,
                f"{display_candidate.similarity_score:.3f}",
                f"{display_candidate.boundary_node_match_ratio:.3f}",
                f"{display_candidate.iou:.3f}" if hasattr(display_candidate, "iou") else ("" if area_ratio is None else f"{area_ratio:.3f}"),
                "가능" if display_candidate.can_apply else "불가",
                display_reason,
            )
            tags = self._continuous_tree_item_tags(
                display_candidate,
                selected=display_candidate.target_story_name in selected_targets and display_candidate.can_apply,
                conflict=bool(conflict_reason),
            )
            rows.append((iid, values, tags))

        fingerprint = (
            str(base_story or ""),
            str(region_key or ""),
            visible_targets_tuple,
            saved_targets,
            active_region_keys,
            tuple(rows),
        )
        if bool(self.__dict__.get("continuous_drag_active")):
            self._cancel_continuous_tree_drag(
                restore_initial=True,
                status_message="연속층 후보 목록이 갱신되어 진행 중인 드래그 선택을 취소했습니다.",
            )
        self.continuous_candidate_by_iid = candidate_by_iid
        self.continuous_ordered_iids = ordered_iids
        self.continuous_story_anchor_iid = None
        tree_matches = fingerprint == self.__dict__.get("_continuous_tree_render_fingerprint")
        if not tree_matches:
            for item in self.continuous_tree.get_children():
                self.continuous_tree.delete(item)
            for iid, values, tags in rows:
                self.continuous_tree.insert(
                    "",
                    "end",
                    iid=iid,
                    values=values,
                    tags=tags,
                )
            self._continuous_tree_render_fingerprint = fingerprint
        if selected_iids:
            self._set_continuous_tree_selection(selected_iids, sync_targets=False)
        if hasattr(self, "continuous_apply_status_var"):
            selected_conflicts = [story for story in saved_targets if story in conflict_reason_by_target]
            if saved_targets:
                if selected_conflicts:
                    self._set_continuous_status(conflict_reason_by_target[selected_conflicts[0]], warning=True)
                else:
                    self._set_continuous_status(f"자동 저장됨: {base_story} -> {', '.join(saved_targets)}")
            else:
                self._set_continuous_status(f"기준 {base_story}: 적용 가능 {applicable}/{len(tuple(candidates))}")
        self._hatch_perf_end(
            perf_token,
            story_name=str(base_story or ""),
            display_mode=self._hatch_view_display_mode(),
            visible_region_count=0,
            structure_item_count=0,
            candidate_target_count=len(tuple(candidates or ())),
            cache_hit=(
                int(self.__dict__.get("_continuous_load_conflict_reason_cache_hits", 0) or 0)
                - conflict_hits_before
                + int(self.__dict__.get("_matching_target_cell_geometry_cache_hits", 0) or 0)
                - matching_hits_before
            ),
            cache_miss=(
                int(self.__dict__.get("_continuous_load_conflict_reason_cache_misses", 0) or 0)
                - conflict_misses_before
                + int(self.__dict__.get("_matching_target_cell_geometry_cache_misses", 0) or 0)
                - matching_misses_before
            ),
            region_key=str(region_key or ""),
            tree_cache_hit=tree_matches,
            visible_target_count=len(visible_targets_tuple),
        )

    def _profile_area_ratio(self, first, second) -> float | None:
        if first is None or second is None:
            return None
        try:
            first_area = float(first.union_area)
            second_area = float(second.union_area)
        except Exception:
            return None
        denominator = max(first_area, second_area, 1.0e-12)
        return min(first_area, second_area) / denominator

    def select_applicable_continuous_stories(self) -> None:
        if not hasattr(self, "continuous_tree"):
            return
        selections = self._nearest_applicable_continuous_iids()
        self._set_continuous_tree_selection(selections)

    def _nearest_applicable_continuous_iids(self) -> list[str]:
        active_visible_targets = set(self._get_continuous_active_visible_targets())
        if active_visible_targets:
            return [
                iid
                for iid in getattr(self, "continuous_ordered_iids", []) or []
                if iid in getattr(self, "continuous_candidate_by_iid", {})
                and _continuous_candidate_can_apply(self.continuous_candidate_by_iid[iid])
                and str(getattr(self.continuous_candidate_by_iid[iid], "target_story_name", "") or "") in active_visible_targets
            ]
        active_keys = tuple(self.__dict__.get("continuous_active_region_keys") or ())
        if active_keys:
            common_targets = set(self._visible_common_targets_for_region_keys(active_keys))
            if not common_targets:
                return []
            return [
                iid
                for iid in getattr(self, "continuous_ordered_iids", []) or []
                if _continuous_candidate_can_apply(getattr(self, "continuous_candidate_by_iid", {}).get(iid))
                and str(getattr(getattr(self, "continuous_candidate_by_iid", {}).get(iid), "target_story_name", "") or "") in common_targets
            ]
        region_key = self.__dict__.get("continuous_active_region_key") or self.__dict__.get("hatch_view_selected_region_key") or ""
        check = (self.__dict__.get("continuous_hatch_checks", {}) or {}).get(str(region_key), {})
        preferred_targets = self._visible_applicable_targets_for_region_key(str(region_key)) or tuple(
            check.get("base_centered_targets", ()) or check.get("recommended_targets", ()) or ()
        )
        if preferred_targets:
            preferred = set(str(name or "") for name in preferred_targets)
            return [
                iid
                for iid in getattr(self, "continuous_ordered_iids", []) or []
                if iid in getattr(self, "continuous_candidate_by_iid", {})
                and _continuous_candidate_can_apply(self.continuous_candidate_by_iid[iid])
                and str(getattr(self.continuous_candidate_by_iid[iid], "target_story_name", "") or "") in preferred
            ]
        story_order = [profile.story_name for profile in getattr(self, "story_shape_profiles", ()) or ()]
        if not story_order:
            return [
                iid
                for iid in getattr(self, "continuous_ordered_iids", []) or []
                if _continuous_candidate_can_apply(getattr(self, "continuous_candidate_by_iid", {}).get(iid))
            ]
        candidates = [getattr(self, "continuous_candidate_by_iid", {}).get(iid) for iid in getattr(self, "continuous_ordered_iids", []) or []]
        base_story = str(self.__dict__.get("continuous_base_story_name").get() if self.__dict__.get("continuous_base_story_name") is not None else "")
        centered = set(self._base_centered_applicable_story_names(base_story=base_story, candidates=candidates, story_order=story_order))
        if not centered:
            centered = {
                str(getattr(candidate, "target_story_name", "") or "")
                for candidate in candidates
                if _continuous_candidate_can_apply(candidate)
            }
        return [
            iid
            for iid in getattr(self, "continuous_ordered_iids", []) or []
            if iid in getattr(self, "continuous_candidate_by_iid", {})
            and _continuous_candidate_can_apply(self.continuous_candidate_by_iid[iid])
            and str(getattr(self.continuous_candidate_by_iid[iid], "target_story_name", "") or "") in centered
        ]

    def select_recommended_continuous_stories(self) -> None:
        if not hasattr(self, "continuous_tree"):
            return
        region_key = self.continuous_active_region_key or self.hatch_view_selected_region_key or ""
        check = self.continuous_hatch_checks.get(region_key, {})
        recommended_targets = set(check.get("recommended_targets", ()) or ())
        selections = [
            iid
            for iid, candidate in getattr(self, "continuous_candidate_by_iid", {}).items()
            if _continuous_candidate_can_apply(candidate) and candidate.target_story_name in recommended_targets
        ]
        self._set_continuous_tree_selection(selections)
        if hasattr(self, "continuous_apply_status_var"):
            label = ", ".join(
                candidate.target_story_name
                for iid, candidate in getattr(self, "continuous_candidate_by_iid", {}).items()
                if iid in selections
            )
            self._set_continuous_status(f"자동 후보 반영: {label or '없음'}")

    def clear_continuous_apply_results(self) -> None:
        self.continuous_apply_targets = {}
        self.continuous_apply_targets_by_region = {}
        self.continuous_materialized_targets_by_region = {}
        if hasattr(self, "continuous_tree"):
            self._set_continuous_tree_selection(())
        if hasattr(self, "continuous_apply_status_var"):
            self._set_continuous_status("연속층 적용 결과를 초기화했습니다.")
        self._render_hatch_preview()

    def _continuous_tree_candidate_token(self) -> tuple[object, ...]:
        ordered = tuple(self.__dict__.get("continuous_ordered_iids", ()) or ())
        candidates = self.__dict__.get("continuous_candidate_by_iid", {}) or {}
        return (
            ordered,
            tuple(
                (
                    iid,
                    id(candidates.get(iid)),
                    _continuous_candidate_can_apply(candidates.get(iid)),
                    str(getattr(candidates.get(iid), "target_story_name", "") or ""),
                )
                for iid in ordered
            ),
        )

    def _on_continuous_tree_button_press(self, event):
        tree = self.__dict__.get("continuous_tree")
        if tree is None:
            return None
        iid = tree.identify_row(event.y)
        if not iid:
            return None
        state = int(getattr(event, "state", 0) or 0)
        shift = bool(state & 0x0001)
        ctrl = bool(state & 0x0004)
        candidate = self.continuous_candidate_by_iid.get(iid)
        if not _continuous_candidate_can_apply(candidate):
            if "continuous_apply_status_var" in self.__dict__:
                reason = self._continuous_reason_user_text(candidate)
                target = str(getattr(candidate, "target_story_name", "") or "")
                self._set_continuous_status(f"{target} 적용 불가: {reason}")
            return "break"
        initial = set(tree.selection())
        mode = "shift" if shift else ("ctrl_remove" if ctrl and iid in initial else ("ctrl_add" if ctrl else "plain"))
        self._cancel_continuous_tree_autoscroll()
        self.continuous_drag_active = True
        self.continuous_drag_start_iid = iid
        self.continuous_drag_current_iid = iid
        self.continuous_drag_initial_selection = set(initial)
        self.continuous_drag_preview_selection = set(initial)
        self.continuous_drag_mode = mode
        self.continuous_drag_start_xy = (int(getattr(event, "x", 0) or 0), int(getattr(event, "y", 0) or 0))
        self.continuous_drag_moved = False
        self._continuous_drag_last_y = int(getattr(event, "y", 0) or 0)
        self._continuous_drag_candidate_token = self._continuous_tree_candidate_token()
        focus_set = getattr(tree, "focus_set", None)
        if callable(focus_set):
            focus_set()
        grab_set = getattr(tree, "grab_set", None)
        if callable(grab_set):
            try:
                grab_set()
            except Exception:
                pass
        return "break"

    def _on_continuous_tree_drag_motion(self, event):
        if not bool(self.__dict__.get("continuous_drag_active")):
            return None
        if self.__dict__.get("_continuous_drag_candidate_token") != self._continuous_tree_candidate_token():
            self._cancel_continuous_tree_drag(
                restore_initial=True,
                status_message="연속층 후보 목록이 변경되어 드래그 선택을 취소했습니다.",
            )
            return "break"
        tree = self.__dict__.get("continuous_tree")
        if tree is None:
            return None
        x = int(getattr(event, "x", 0) or 0)
        y = int(getattr(event, "y", 0) or 0)
        self._continuous_drag_last_y = y
        start_xy = self.__dict__.get("continuous_drag_start_xy") or (x, y)
        distance = math.hypot(x - int(start_xy[0]), y - int(start_xy[1]))
        if distance < CONTINUOUS_TREE_DRAG_THRESHOLD_PX and not self.continuous_drag_moved:
            return "break"
        self.continuous_drag_moved = True
        iid = tree.identify_row(y)
        if iid:
            self._update_continuous_tree_drag_preview(iid)
        self._update_continuous_tree_autoscroll(y)
        return "break"

    def _update_continuous_tree_drag_preview(self, current_iid: str) -> None:
        if current_iid not in tuple(self.__dict__.get("continuous_ordered_iids", ()) or ()):
            return
        self.continuous_drag_current_iid = current_iid
        visible_targets = tuple(self._get_continuous_active_visible_targets())
        preview = compute_continuous_drag_selection(
            tuple(self.__dict__.get("continuous_ordered_iids", ()) or ()),
            dict(self.__dict__.get("continuous_candidate_by_iid", {}) or {}),
            set(self.__dict__.get("continuous_drag_initial_selection", set()) or set()),
            str(self.__dict__.get("continuous_drag_start_iid") or ""),
            current_iid,
            mode=str(self.__dict__.get("continuous_drag_mode") or "plain"),
            anchor_iid=self.__dict__.get("continuous_story_anchor_iid"),
            visible_target_names=visible_targets if visible_targets else None,
        )
        self._preview_continuous_tree_selection(preview)
        candidate = (self.__dict__.get("continuous_candidate_by_iid", {}) or {}).get(current_iid)
        if not _continuous_candidate_can_apply(candidate) and "continuous_apply_status_var" in self.__dict__:
            target = str(getattr(candidate, "target_story_name", "") or "")
            self._set_continuous_status(f"{target} 적용 불가 지점에서 드래그 범위를 중단했습니다: {self._continuous_reason_user_text(candidate)}")

    def _preview_continuous_tree_selection(self, selected_iids) -> None:
        tree = self.__dict__.get("continuous_tree")
        if tree is None:
            return
        accepted = {
            iid
            for iid in set(selected_iids or ())
            if _continuous_candidate_can_apply((self.__dict__.get("continuous_candidate_by_iid", {}) or {}).get(iid))
        }
        tree.selection_set(list(accepted))
        for iid in tree.get_children():
            candidate = (self.__dict__.get("continuous_candidate_by_iid", {}) or {}).get(iid)
            values = list(tree.item(iid, "values"))
            if values:
                values[0] = "✓" if iid in accepted else ""
                tree.item(
                    iid,
                    values=tuple(values),
                    tags=self._continuous_tree_item_tags(candidate, selected=iid in accepted),
                )
        self.continuous_drag_preview_selection = set(accepted)

    def _on_continuous_tree_button_release(self, event):
        if not bool(self.__dict__.get("continuous_drag_active")):
            return None
        tree = self.__dict__.get("continuous_tree")
        if tree is None:
            self._reset_continuous_tree_drag_state()
            return None
        start_iid = str(self.__dict__.get("continuous_drag_start_iid") or "")
        initial = set(self.__dict__.get("continuous_drag_initial_selection", set()) or set())
        final_selection = set(self.__dict__.get("continuous_drag_preview_selection", initial) or set())
        moved = bool(self.__dict__.get("continuous_drag_moved"))
        mode = str(self.__dict__.get("continuous_drag_mode") or "plain")
        self._cancel_continuous_tree_autoscroll()
        self._release_continuous_tree_grab()
        self._reset_continuous_tree_drag_state(cancel_autoscroll=False)
        if moved:
            if mode != "shift":
                self.continuous_story_anchor_iid = start_iid or self.continuous_story_anchor_iid
            self._set_continuous_tree_selection(final_selection, sync_targets=True)
            return "break"
        state = int(getattr(event, "state", 0) or 0)
        return self._apply_continuous_tree_click(
            start_iid,
            current_selection=initial,
            shift=bool(state & 0x0001),
            ctrl=bool(state & 0x0004),
        )

    def _apply_continuous_tree_click(
        self,
        iid: str,
        *,
        current_selection: Iterable[str] | None = None,
        shift: bool = False,
        ctrl: bool = False,
    ):
        tree = self.__dict__.get("continuous_tree")
        if tree is None or not iid:
            return None
        candidate = (self.__dict__.get("continuous_candidate_by_iid", {}) or {}).get(iid)
        if not _continuous_candidate_can_apply(candidate):
            return "break"
        selected, anchor = update_story_check_selection(
            list(getattr(self, "continuous_ordered_iids", []) or []),
            dict(getattr(self, "continuous_candidate_by_iid", {}) or {}),
            set(tree.selection()) if current_selection is None else set(current_selection),
            iid,
            self.continuous_story_anchor_iid,
            shift=shift,
            ctrl=ctrl,
        )
        self.continuous_story_anchor_iid = anchor
        self._set_continuous_tree_selection(selected)
        return "break"

    def _on_continuous_tree_click(self, event):
        """Compatibility entry point retained for tests and older bindings."""
        tree = self.__dict__.get("continuous_tree")
        if tree is None:
            return None
        iid = tree.identify_row(event.y)
        state = int(getattr(event, "state", 0) or 0)
        return self._apply_continuous_tree_click(
            iid,
            shift=bool(state & 0x0001),
            ctrl=bool(state & 0x0004),
        )

    def _on_continuous_tree_leave(self, event):
        if not bool(self.__dict__.get("continuous_drag_active")):
            return None
        y = int(getattr(event, "y", self.__dict__.get("_continuous_drag_last_y", 0)) or 0)
        self._continuous_drag_last_y = y
        self._update_continuous_tree_autoscroll(y)
        return "break"

    def _update_continuous_tree_autoscroll(self, pointer_y: int) -> None:
        tree = self.__dict__.get("continuous_tree")
        if tree is None or not bool(self.__dict__.get("continuous_drag_active")):
            self._cancel_continuous_tree_autoscroll()
            return
        try:
            height = max(1, int(tree.winfo_height()))
        except Exception:
            height = 1
        direction = -1 if pointer_y <= CONTINUOUS_TREE_AUTOSCROLL_EDGE_PX else (1 if pointer_y >= height - CONTINUOUS_TREE_AUTOSCROLL_EDGE_PX else 0)
        self._continuous_drag_autoscroll_direction = direction
        if direction == 0:
            self._cancel_continuous_tree_autoscroll()
            return
        if self.__dict__.get("continuous_drag_autoscroll_after_id") is not None:
            return
        after = getattr(tree, "after", None)
        if callable(after):
            self.continuous_drag_autoscroll_after_id = after(
                CONTINUOUS_TREE_AUTOSCROLL_INTERVAL_MS,
                self._continuous_tree_autoscroll_tick,
            )

    def _continuous_tree_autoscroll_tick(self) -> None:
        self.continuous_drag_autoscroll_after_id = None
        if not bool(self.__dict__.get("continuous_drag_active")):
            return
        tree = self.__dict__.get("continuous_tree")
        direction = int(self.__dict__.get("_continuous_drag_autoscroll_direction", 0) or 0)
        if tree is None or direction == 0:
            return
        tree.yview_scroll(direction, "units")
        try:
            height = max(1, int(tree.winfo_height()))
        except Exception:
            height = 1
        probe_y = CONTINUOUS_TREE_AUTOSCROLL_EDGE_PX if direction < 0 else max(0, height - CONTINUOUS_TREE_AUTOSCROLL_EDGE_PX)
        iid = tree.identify_row(probe_y)
        if iid:
            self._update_continuous_tree_drag_preview(iid)
        self._update_continuous_tree_autoscroll(int(self.__dict__.get("_continuous_drag_last_y", probe_y) or probe_y))

    def _cancel_continuous_tree_autoscroll(self) -> None:
        after_id = self.__dict__.get("continuous_drag_autoscroll_after_id")
        self.continuous_drag_autoscroll_after_id = None
        self._continuous_drag_autoscroll_direction = 0
        if after_id is None:
            return
        tree = self.__dict__.get("continuous_tree")
        after_cancel = getattr(tree, "after_cancel", None) if tree is not None else None
        if callable(after_cancel):
            try:
                after_cancel(after_id)
            except Exception:
                pass

    def _release_continuous_tree_grab(self) -> None:
        tree = self.__dict__.get("continuous_tree")
        grab_release = getattr(tree, "grab_release", None) if tree is not None else None
        if callable(grab_release):
            try:
                grab_release()
            except Exception:
                pass

    def _reset_continuous_tree_drag_state(self, *, cancel_autoscroll: bool = True) -> None:
        if cancel_autoscroll:
            self._cancel_continuous_tree_autoscroll()
        self.continuous_drag_active = False
        self.continuous_drag_start_iid = None
        self.continuous_drag_current_iid = None
        self.continuous_drag_initial_selection = set()
        self.continuous_drag_preview_selection = set()
        self.continuous_drag_mode = "plain"
        self.continuous_drag_start_xy = None
        self.continuous_drag_moved = False
        self._continuous_drag_candidate_token = ()

    def _cancel_continuous_tree_drag(self, *, restore_initial: bool, status_message: str = "") -> None:
        if not bool(self.__dict__.get("continuous_drag_active")):
            self._cancel_continuous_tree_autoscroll()
            return
        initial = set(self.__dict__.get("continuous_drag_initial_selection", set()) or set())
        self._cancel_continuous_tree_autoscroll()
        if restore_initial:
            self._preview_continuous_tree_selection(initial)
        self._release_continuous_tree_grab()
        self._reset_continuous_tree_drag_state(cancel_autoscroll=False)
        if status_message and "continuous_apply_status_var" in self.__dict__:
            self._set_continuous_status(status_message)

    def _on_continuous_tree_drag_cancel(self, _event=None):
        self._cancel_continuous_tree_drag(
            restore_initial=True,
            status_message="연속층 드래그 선택을 취소했습니다.",
        )
        return "break"

    def _on_continuous_tree_destroy(self, event=None):
        tree = self.__dict__.get("continuous_tree")
        if event is not None and tree is not None and getattr(event, "widget", tree) is not tree:
            return None
        self._cancel_continuous_tree_drag(restore_initial=False)
        return None

    def _set_continuous_tree_selection(self, selected_iids, *, sync_targets: bool = True) -> None:
        self._cancel_scheduled_hatch_continuous_refresh()
        tree = self.__dict__.get("continuous_tree")
        if tree is None:
            return
        requested = set(selected_iids or [])
        current_selection_keys = tuple(self._selected_hatch_region_keys_for_continuous_info())
        active_region_keys = tuple(
            str(key or "")
            for key in tuple(self.__dict__.get("continuous_active_region_keys", ()) or ())
            if str(key or "")
        )
        if not active_region_keys:
            active_key = str(self.__dict__.get("continuous_active_region_key") or "")
            active_region_keys = (active_key,) if active_key else ()
        region_keys = current_selection_keys or active_region_keys

        requested_targets_by_iid = {
            iid: str(getattr(candidate, "target_story_name", "") or "")
            for iid, candidate in (self.__dict__.get("continuous_candidate_by_iid", {}) or {}).items()
            if iid in requested and _continuous_candidate_can_apply(candidate)
        }
        visible_common_targets: tuple[str, ...] = ()
        if region_keys:
            try:
                visible_common_targets = tuple(self._visible_common_targets_for_region_keys(region_keys))
            except Exception:
                visible_common_targets = ()
        geometry_ready = bool(self.__dict__.get("stories")) and bool(
            self.__dict__.get("nodes") or self.__dict__.get("elements")
        )
        if not visible_common_targets and not geometry_ready:
            visible_common_targets = tuple(
                str(getattr(self.continuous_candidate_by_iid[iid], "target_story_name", "") or "")
                for iid in tuple(self.__dict__.get("continuous_ordered_iids", ()) or ())
                if iid in self.continuous_candidate_by_iid
                and _continuous_candidate_can_apply(self.continuous_candidate_by_iid[iid])
            )
        allowed_targets = set(visible_common_targets)
        target_values = tuple(
            requested_targets_by_iid[iid]
            for iid in tuple(self.__dict__.get("continuous_ordered_iids", ()) or ())
            if iid in requested_targets_by_iid and requested_targets_by_iid[iid] in allowed_targets
        )
        filtered_target_values = target_values
        base_story = self._hatch_var_text("continuous_base_story_name")
        story_order = self._story_order_names()
        follows_visible = self._targets_follow_active_visible_range(target_values, visible_common_targets)
        follows_story_order = self._targets_are_single_base_centered_range(target_values, story_order, base_story)
        discontinuous = bool(target_values) and not (
            follows_story_order if story_order else follows_visible
        )
        if discontinuous:
            target_values = ()
        accepted = {
            iid
            for iid, target_story in requested_targets_by_iid.items()
            if target_story in set(filtered_target_values)
        }
        tree.selection_set(list(accepted))
        tag_region_keys = region_keys
        for iid in tree.get_children():
            candidate = self.continuous_candidate_by_iid.get(iid)
            values = list(tree.item(iid, "values"))
            if not values:
                continue
            target_story = str(getattr(candidate, "target_story_name", "") or "")
            conflict_reason = self._continuous_load_conflict_reason_for_region_keys(tag_region_keys, target_story)
            if len(values) > 6:
                values[6] = self._continuous_reason_user_text(candidate, conflict_reason=conflict_reason)
            values[0] = "✓" if iid in accepted and _continuous_candidate_can_apply(candidate) else ""
            tree.item(
                iid,
                values=tuple(values),
                tags=self._continuous_tree_item_tags(candidate, selected=iid in accepted, conflict=bool(conflict_reason)),
            )
        if sync_targets:
            if region_keys:
                before_snapshot = self._safe_capture_hatch_edit_snapshot()
                target_map = self.__dict__.setdefault("continuous_apply_targets_by_region", {})
                previous_target_map = {
                    key: tuple(
                        str(name or "")
                        for name in tuple(target_map.get(key, ()) or ())
                        if str(name or "")
                    )
                    for key in region_keys
                }
                if discontinuous:
                    for key in region_keys:
                        target_map[key] = ()
                    if hasattr(self, "continuous_apply_status_var"):
                        self._set_continuous_status(
                            "비연속 층은 연속층 일괄 적용 대상으로 저장할 수 없습니다. 하나의 연속 구간만 선택해 주세요."
                        )
                else:
                    for key in region_keys:
                        target_map[key] = target_values
                    if hasattr(self, "continuous_apply_status_var"):
                        if target_values:
                            conflict_reason = ""
                            for target_story in target_values:
                                conflict_reason = self._continuous_load_conflict_reason_for_region_keys(region_keys, target_story)
                                if conflict_reason:
                                    break
                            if conflict_reason:
                                self._set_continuous_status(conflict_reason, warning=True)
                            else:
                                self._set_continuous_status(f"자동 저장됨: {base_story or '-'} -> {', '.join(target_values)}")
                        else:
                            self._set_continuous_status(f"자동 저장 해제됨: {base_story or '-'}")
                removed_changed = False
                for key in region_keys:
                    removed_targets = set(previous_target_map.get(key, ())).difference(set(target_values))
                    for removed_target in removed_targets:
                        if self._apply_or_remove_continuous_load_to_target_story(
                            base_region_key=key,
                            target_story=removed_target,
                            payload=None,
                            remove=True,
                        ):
                            removed_changed = True
                if removed_changed:
                    self._refresh_hatch_edit_region_index()
                if target_values:
                    self._sync_load_to_continuous_targets_for_region_keys(region_keys, refresh_ui=False)
                self._render_hatch_preview()
                self._record_hatch_edit_change("연속층 적용", before_snapshot)

    def _continuous_tree_item_tags(self, candidate, *, selected: bool = False, conflict: bool = False) -> tuple[str, ...]:
        tags = ["can_apply" if _continuous_candidate_can_apply(candidate) else "cannot_apply"]
        if conflict:
            tags.append("load_conflict")
        if selected and _continuous_candidate_can_apply(candidate):
            tags.append("selected_apply")
        return tuple(tags)

    def confirm_continuous_apply(self) -> None:
        if not hasattr(self, "continuous_tree"):
            return
        if not getattr(self, "continuous_candidate_by_iid", None):
            self.verify_continuous_apply_range()
        region_key = self.continuous_active_region_key or self.hatch_view_selected_region_key or ""
        if not region_key:
            messagebox.showwarning("해치 선택 필요", "먼저 해치 보기에서 연속층 적용할 해치를 선택해 주세요.")
            return
        selected_iids = list(self.continuous_tree.selection())
        if not selected_iids:
            check = self.continuous_hatch_checks.get(region_key, {})
            preferred = set(check.get("recommended_targets", ()) or ())
            selected_iids = [
                iid
                for iid, candidate in self.continuous_candidate_by_iid.items()
                if candidate.can_apply and (not preferred or candidate.target_story_name in preferred)
            ]
        targets = [
            self.continuous_candidate_by_iid[iid].target_story_name
            for iid in selected_iids
            if iid in self.continuous_candidate_by_iid and self.continuous_candidate_by_iid[iid].can_apply
        ]
        base_story = self.continuous_base_story_name.get().strip()
        if not base_story or not targets:
            messagebox.showwarning("연속층 대상 없음", "적용 가능한 target Story가 선택되지 않았습니다.")
            return
        if not self._targets_are_single_continuous_range(targets):
            messagebox.showwarning("비연속 선택", "선택한 Story가 하나의 연속 구간이 아닙니다. 연속 구간만 선택해 주세요.")
            return
        self.continuous_apply_targets_by_region[region_key] = tuple(targets)
        if hasattr(self, "continuous_apply_status_var"):
            self._set_continuous_status(f"연속층 적용 저장: {base_story} -> {', '.join(targets)}")
        self._set_continuous_tree_selection(selected_iids)
        self._render_hatch_preview()

    def _targets_are_single_continuous_range(self, targets: list[str]) -> bool:
        order = [profile.story_name for profile in self.story_shape_profiles]
        base_story = str(self.continuous_base_story_name.get() or "")
        return self._targets_are_single_base_centered_range(tuple(targets), order, base_story)

    def _targets_are_single_base_centered_range(self, targets, story_order, base_story: str) -> bool:
        target_tuple = tuple(str(name or "") for name in tuple(targets or ()) if str(name or ""))
        order = [str(name or "") for name in tuple(story_order or ()) if str(name or "")]
        if len(target_tuple) <= 1:
            return True
        if str(base_story or "") in order:
            expanded = tuple(dict.fromkeys((*target_tuple, str(base_story or ""))))
            return _continuous_targets_are_single_range(expanded, order)
        return _continuous_targets_are_single_range(target_tuple, order)

    def _regions_with_continuous_apply(self, regions):
        target_map = dict(self.__dict__.get("continuous_apply_targets_by_region", {}) or {})
        if not target_map:
            return regions
        materialized_map = dict(self.__dict__.get("continuous_materialized_targets_by_region", {}) or {})
        expanded = list(regions)
        for index, region in enumerate(list(regions), start=1):
            region_key = self._region_key(region, index=index)
            base_story = str(getattr(region.region, "story_name", "") or "")
            targets = tuple(target_map.get(region_key, ()) or ())
            if not targets:
                continue
            materialized_targets = {
                str(name or "")
                for name in tuple(materialized_map.get(region_key, ()) or ())
                if str(name or "")
            }
            if materialized_targets:
                targets = tuple(target for target in targets if str(target or "") not in materialized_targets)
            if not targets:
                continue
            check = self.continuous_hatch_checks.get(region_key, {})
            can_apply_targets = {
                candidate.target_story_name
                for candidate in tuple(check.get("candidates", ()) or ())
                if candidate.can_apply
            }
            if can_apply_targets:
                targets = tuple(target for target in targets if target in can_apply_targets)
            targets = tuple(
                target
                for target in targets
                if not self._continuous_target_below_allowed_reason(region_key, str(target or ""))
            )
            base_source_id = str(getattr(region.region, "source_id", "") or getattr(region.region, "handle", "") or "hatch")
            for target_story in targets:
                if target_story == base_story:
                    continue
                cloned_region = replace(
                    region.region,
                    story_name=str(target_story),
                    source_id=f"{base_source_id}@{target_story}",
                )
                cloned = replace(region, region=cloned_region, warnings=list(region.warnings))
                expanded.append(cloned)
        return expanded

    def _refresh_diagnostic_tree(self, issues) -> None:
        summary = getattr(issues, "summary", None)
        raw_issues = list(getattr(issues, "issues", issues or []))
        self.diagnostic_issues = raw_issues
        self._refresh_dummy_issues_from_diagnostics(raw_issues)
        if self.__dict__.get("hatch_preview_canvas") is not None:
            self._render_hatch_preview()
        if summary is not None and hasattr(self, "diagnostic_summary_var"):
            element_types = ", ".join(f"{name}={count}" for name, count in sorted(summary.element_type_counts.items()))
            status_label = {
                "READY": "입력 가능",
                "READY_WITH_WARNINGS": "입력 가능, 확인 필요",
                "BLOCKED": "입력 보류",
                "NO_TARGET_REGION": "대상 영역 없음",
            }.get(str(summary.status), str(summary.status))
            self.diagnostic_summary_var.set(
                f"판정: {status_label} | 단위: {summary.unit_force or '?'}-{summary.unit_length or '?'} | "
                f"Story {summary.story_count}개, Node {summary.node_count}개, Element {summary.element_count}개 "
                f"({element_types or '부재 없음'}) | FLOORLOAD TYPE {summary.floadtype_count}개, "
                f"기존 FLOORLOAD {summary.existing_floorload_count}개, 입력 대상 {summary.planned_region_count}개 | "
                f"ELASTIC LINK {getattr(summary, 'elastic_link_count', 0)}개, "
                f"연결된 내부/외팔 부재 {getattr(summary, 'internal_member_supported_count', 0)}개, "
                f"확인 필요 내부/외팔 부재 {getattr(summary, 'internal_member_warning_count', 0)}개 | "
                f"오류 {summary.error_count}, 확인 필요 {summary.warning_count}, 참고 {summary.info_count} | "
                f"{getattr(summary, 'diagnostic_message', '')}"
            )
        if hasattr(self, "open_diag_dxf_button") and self.last_diagnostic_dxf_path:
            self.open_diag_dxf_button.state(["!disabled"])
        if hasattr(self, "open_diag_report_button") and self.last_diagnostic_report_path:
            self.open_diag_report_button.state(["!disabled"])
        if not hasattr(self, "diagnostic_tree"):
            return
        for item in self.diagnostic_tree.get_children():
            self.diagnostic_tree.delete(item)
        self.diagnostic_issue_by_tree_iid = {}
        blocking_issues = [issue for issue in self.diagnostic_issues if str(issue.severity).upper() in {"ERROR", "WARNING"}]
        visible_issues = blocking_issues
        if not visible_issues:
            visible_issues = self.diagnostic_issues[:20]
        first_iid = ""
        for index, issue in enumerate(visible_issues, start=1):
            display = diagnostic_issue_user_text(issue)
            iid = f"diag_{index}"
            if not first_iid:
                first_iid = iid
            self.diagnostic_issue_by_tree_iid[iid] = issue
            self.diagnostic_tree.insert(
                "",
                "end",
                iid=iid,
                values=(
                    issue.story_name,
                    display["severity_label"],
                    display["type_label"],
                    f"{issue.x:.3f}, {issue.y:.3f}",
                    ",".join(str(value) for value in issue.node_ids),
                    ",".join(str(value) for value in issue.element_ids),
                    display["cause"],
                    display["action"],
                ),
            )
        if _should_show_diagnostic_preview(blocking_issues):
            self._show_diagnostic_preview_panel()
            self.diagnostic_preview_zoom = 1.0
            if first_iid:
                self.diagnostic_tree.selection_set(first_iid)
                selected_issue = self.diagnostic_issue_by_tree_iid.get(first_iid)
                self._render_diagnostic_preview(selected_issue, fit_all=True)
                self._center_preview_on_issue(selected_issue)
            else:
                self._render_diagnostic_preview(None, fit_all=True)
        else:
            self._hide_diagnostic_preview_panel(clear_canvas=True)
            if first_iid:
                self.diagnostic_tree.selection_set(first_iid)
            self.diagnostic_preview_info_var.set("오류/경고가 있을 때 진단 위치 미리보기가 자동으로 표시됩니다.")

    def _show_diagnostic_preview_panel(self) -> None:
        pane = getattr(self, "diagnostic_pane", None)
        panel = getattr(self, "diagnostic_preview_panel", None)
        if pane is None or panel is None:
            return
        panes = set(str(item) for item in pane.panes())
        if str(panel) not in panes:
            pane.add(panel, weight=3)
        self.diagnostic_preview_visible = True

    def _hide_diagnostic_preview_panel(self, *, clear_canvas: bool = False) -> None:
        pane = getattr(self, "diagnostic_pane", None)
        panel = getattr(self, "diagnostic_preview_panel", None)
        if pane is not None and panel is not None and str(panel) in set(str(item) for item in pane.panes()):
            try:
                pane.forget(panel)
            except tk.TclError:
                pass
        self.diagnostic_preview_visible = False
        if clear_canvas:
            canvas = getattr(self, "diagnostic_preview_canvas", None)
            if canvas is not None:
                canvas.delete("all")
                canvas.configure(scrollregion=(0, 0, 0, 0))

    def _fit_diagnostic_preview(self) -> None:
        self.diagnostic_preview_zoom = 1.0
        self._render_diagnostic_preview(self.diagnostic_preview_selected_issue, fit_all=True)
        self._center_preview_on_issue(self.diagnostic_preview_selected_issue)

    def _zoom_diagnostic_preview(self, factor: float) -> None:
        self.diagnostic_preview_zoom = max(0.2, min(float(self.diagnostic_preview_zoom) * float(factor), 8.0))
        self._render_diagnostic_preview(self.diagnostic_preview_selected_issue)
        self._center_preview_on_issue(self.diagnostic_preview_selected_issue)

    def _on_diagnostic_preview_mousewheel(self, event) -> None:
        if getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
            self._zoom_diagnostic_preview(1 / 1.25)
        else:
            self._zoom_diagnostic_preview(1.25)

    def _selected_diagnostic_issue(self):
        if not hasattr(self, "diagnostic_tree"):
            return None
        selection = self.diagnostic_tree.selection()
        return self.diagnostic_issue_by_tree_iid.get(selection[0]) if selection else None

    def _diagnostic_preview_issues_for_story(self, story_name: str) -> list:
        candidates = [issue for issue in self.diagnostic_issues if str(issue.severity).upper() in {"ERROR", "WARNING"}]
        if story_name:
            story_candidates = [issue for issue in candidates if issue.story_name == story_name]
            if story_candidates:
                return story_candidates
        return candidates

    def _on_diagnostic_issue_selected(self, _event=None) -> None:
        issue = self._selected_diagnostic_issue()
        if not self.diagnostic_preview_visible:
            self.diagnostic_preview_selected_issue = issue
            return
        self._render_diagnostic_preview(issue)
        self._center_preview_on_issue(issue)

    def _render_diagnostic_preview(self, issue=None, *, fit_all: bool = False) -> None:
        if fit_all and issue is None:
            issue = self._selected_diagnostic_issue()
        self.diagnostic_preview_selected_issue = issue
        canvas = getattr(self, "diagnostic_preview_canvas", None)
        if canvas is None:
            return
        canvas.delete("all")
        canvas.configure(scrollregion=(0, 0, 0, 0))
        self.diagnostic_preview_last_transform = None
        width = max(int(canvas.winfo_width() or 0), 320)
        height = max(int(canvas.winfo_height() or 0), 300)
        node_list = list(getattr(self, "nodes", []) or [])
        element_list = list(getattr(self, "elements", []) or [])
        if not node_list or not element_list:
            canvas.create_text(
                width / 2,
                height / 2,
                text="모델 기하 정보가 없어 진단 위치만 표시할 수 있습니다.",
                fill="#666666",
                width=max(width - 40, 120),
            )
            if hasattr(self, "diagnostic_preview_info_var"):
                self.diagnostic_preview_info_var.set("MGT 모델을 먼저 불러오면 Story 평면과 관련 부재가 함께 표시됩니다.")
            return

        preview_candidates = [item for item in self.diagnostic_issues if str(item.severity).upper() in {"ERROR", "WARNING"}]
        story_name = getattr(issue, "story_name", "") if issue is not None else ""
        if not story_name and preview_candidates:
            story_name = str(getattr(preview_candidates[0], "story_name", "") or "")
        preview_issues = self._diagnostic_preview_issues_for_story(story_name)
        story_nodes, story_elements, story = self._diagnostic_story_nodes_and_elements(story_name)
        if not story_nodes:
            story_nodes = node_list
        if not story_elements:
            story_elements = element_list
        node_by_id = {node.node_id: node for node in node_list}
        element_by_id = {element.elem_id: element for element in element_list}
        bbox = self._diagnostic_bbox_from_nodes(story_nodes)
        for preview_issue in preview_issues:
            bbox = self._diagnostic_merge_bbox(bbox, self._diagnostic_issue_focus_bbox(preview_issue, node_by_id, element_by_id))
        if bbox is None:
            canvas.create_text(width / 2, height / 2, text="표시할 모델 좌표가 없습니다.", fill="#666666")
            return
        transform, content_width, _content_height = self._diagnostic_model_to_canvas_transform(bbox, width, height)
        self.diagnostic_preview_last_transform = transform

        story_title = story.name if story is not None else (story_name or "전체 모델")
        canvas.create_text(12, 10, text=story_title, anchor="nw", fill="#2d4b73", font=("TkDefaultFont", 10, "bold"))
        for element in story_elements:
            self._draw_diagnostic_element_on_canvas(canvas, element, node_by_id, transform, base=True)
        for preview_issue in preview_issues:
            self._draw_diagnostic_issue_on_canvas(
                canvas,
                preview_issue,
                node_by_id,
                element_by_id,
                transform,
                selected=preview_issue is issue,
            )
        self._draw_diagnostic_preview_legend(canvas, content_width)

        if hasattr(self, "diagnostic_preview_info_var"):
            if issue is None:
                self.diagnostic_preview_info_var.set("진단 항목을 선택하면 관련 Element/Node가 강조됩니다.")
            else:
                display = diagnostic_issue_user_text(issue)
                self.diagnostic_preview_info_var.set(f"{story_title} | {display['severity_label']} | {display['type_label']}")

    def _diagnostic_story_nodes_and_elements(self, story_name: str):
        node_list = list(getattr(self, "nodes", []) or [])
        element_list = list(getattr(self, "elements", []) or [])
        story = next((value for value in list(getattr(self, "stories", []) or []) if value.name == story_name), None)
        if story is None:
            story_nodes = node_list
        else:
            try:
                tolerance = float(self.story_tol_var.get())
            except Exception:
                tolerance = 0.01
            story_nodes = select_nodes_by_story(node_list, story.elevation, tolerance)
        story_node_ids = {node.node_id for node in story_nodes}
        if story_node_ids:
            story_elements = [element for element in element_list if story_node_ids.intersection(element.node_ids)]
        else:
            story_elements = element_list
        return story_nodes, story_elements, story

    def _diagnostic_model_to_canvas_transform(self, bbox, width: int, height: int, padding: int = 24):
        min_x, min_y, max_x, max_y = bbox
        model_width = max(max_x - min_x, 1e-9)
        model_height = max(max_y - min_y, 1e-9)
        usable_width = max(width - padding * 2, 1)
        usable_height = max(height - padding * 2, 1)
        fit_scale = min(usable_width / model_width, usable_height / model_height)
        scale = fit_scale * max(float(getattr(self, "diagnostic_preview_zoom", 1.0)), 0.2)
        content_width = max(width, model_width * scale + padding * 2)
        content_height = max(height, model_height * scale + padding * 2)
        offset_x = (content_width - model_width * scale) / 2
        offset_y = (content_height - model_height * scale) / 2

        def transform(x: float, y: float) -> tuple[float, float]:
            canvas_x = offset_x + (x - min_x) * scale
            canvas_y = content_height - offset_y - (y - min_y) * scale
            return canvas_x, canvas_y

        canvas = getattr(self, "diagnostic_preview_canvas", None)
        if canvas is not None:
            canvas.configure(scrollregion=(0, 0, content_width, content_height))
        return transform, content_width, content_height

    def _draw_diagnostic_issue_on_canvas(self, canvas, issue, node_by_id, element_by_id, transform, *, selected: bool = False) -> None:
        if issue is None:
            return
        category = diagnostic_issue_category(issue.issue_type)
        severity = str(issue.severity or "").upper()
        if category == "duplicate":
            color = "#d93025"
        elif category == "cantilever":
            color = "#8a3ffc"
        elif category == "closure":
            color = "#876400"
        elif category == "snap":
            color = "#188038"
        elif severity == "ERROR":
            color = "#d93025"
        elif severity == "WARNING":
            color = "#b06000"
        else:
            color = "#1a73e8"
        marker_width = 3 if selected else 2
        element_width = 5 if selected else 3
        marker_radius = 8 if selected else 5

        for element_id in issue.element_ids:
            element = element_by_id.get(element_id)
            if element is None:
                continue
            self._draw_diagnostic_element_on_canvas(canvas, element, node_by_id, transform, base=False, color=color, width_override=element_width)

        for node_id in issue.node_ids:
            node = node_by_id.get(node_id)
            if node is None:
                continue
            x, y = transform(node.x, node.y)
            canvas.create_oval(x - marker_radius, y - marker_radius, x + marker_radius, y + marker_radius, outline=color, fill="white", width=marker_width)

        try:
            marker_x = float(issue.x)
            marker_y = float(issue.y)
        except Exception:
            return
        if math.isfinite(marker_x) and math.isfinite(marker_y):
            x, y = transform(marker_x, marker_y)
            if category == "cantilever":
                canvas.create_polygon(x, y - marker_radius, x - marker_radius, y + marker_radius, x + marker_radius, y + marker_radius, outline=color, fill="", width=marker_width)
            elif category == "closure":
                canvas.create_rectangle(x - marker_radius, y - marker_radius, x + marker_radius, y + marker_radius, outline=color, width=marker_width)
            elif category == "snap":
                canvas.create_line(x - marker_radius, y - marker_radius, x + marker_radius, y + marker_radius, fill=color, width=marker_width)
                canvas.create_line(x - marker_radius, y + marker_radius, x + marker_radius, y - marker_radius, fill=color, width=marker_width)
            else:
                canvas.create_oval(x - marker_radius, y - marker_radius, x + marker_radius, y + marker_radius, outline=color, width=marker_width)
                canvas.create_line(x - marker_radius - 2, y, x + marker_radius + 2, y, fill=color, width=marker_width)
                canvas.create_line(x, y - marker_radius - 2, x, y + marker_radius + 2, fill=color, width=marker_width)
            if selected:
                canvas.create_oval(x - marker_radius * 1.8, y - marker_radius * 1.8, x + marker_radius * 1.8, y + marker_radius * 1.8, outline=color, width=1, dash=(3, 2))

    def _draw_diagnostic_preview_legend(self, canvas, content_width: float) -> None:
        entries = (
            ("#d93025", "중복부재"),
            ("#8a3ffc", "외팔보/자유단"),
            ("#876400", "폐합불가/영역오류"),
            ("#188038", "스냅오류"),
            ("#b06000", "일반 경고"),
        )
        x = max(float(content_width) - 180.0, 14.0)
        y = 14.0
        canvas.create_text(x, y, text="범례", anchor="nw", fill="#333333", font=("TkDefaultFont", 9, "bold"))
        y += 18.0
        for color, label in entries:
            canvas.create_line(x, y + 6, x + 18, y + 6, fill=color, width=3)
            canvas.create_text(x + 24, y, text=label, anchor="nw", fill="#333333", font=("TkDefaultFont", 9))
            y += 18.0

    def _center_preview_on_issue(self, issue) -> None:
        if issue is None:
            return
        canvas = getattr(self, "diagnostic_preview_canvas", None)
        transform = getattr(self, "diagnostic_preview_last_transform", None)
        if canvas is None or transform is None:
            return
        node_by_id = {node.node_id: node for node in list(getattr(self, "nodes", []) or [])}
        element_by_id = {element.elem_id: element for element in list(getattr(self, "elements", []) or [])}
        anchor = self._diagnostic_issue_anchor(issue, node_by_id, element_by_id)
        if anchor is None:
            return
        x, y = transform(*anchor)
        self._center_preview_on_canvas_point(x, y)

    def _center_preview_on_canvas_point(self, x: float, y: float) -> None:
        canvas = getattr(self, "diagnostic_preview_canvas", None)
        if canvas is None:
            return
        try:
            canvas.update_idletasks()
            scrollregion = [float(value) for value in str(canvas.cget("scrollregion")).split()]
        except Exception:
            return
        if len(scrollregion) != 4:
            return
        min_x, min_y, max_x, max_y = scrollregion
        total_width = max(max_x - min_x, 1.0)
        total_height = max(max_y - min_y, 1.0)
        view_width = max(float(canvas.winfo_width()), 1.0)
        view_height = max(float(canvas.winfo_height()), 1.0)
        if total_width > view_width:
            canvas.xview_moveto(_clamp((x - view_width / 2 - min_x) / total_width, 0.0, 1.0))
        else:
            canvas.xview_moveto(0.0)
        if total_height > view_height:
            canvas.yview_moveto(_clamp((y - view_height / 2 - min_y) / total_height, 0.0, 1.0))
        else:
            canvas.yview_moveto(0.0)

    def _diagnostic_issue_anchor(self, issue, node_by_id, element_by_id) -> tuple[float, float] | None:
        try:
            marker_x = float(issue.x)
            marker_y = float(issue.y)
        except Exception:
            marker_x = marker_y = math.nan
        if math.isfinite(marker_x) and math.isfinite(marker_y):
            return marker_x, marker_y
        for node_id in getattr(issue, "node_ids", []) or []:
            node = node_by_id.get(node_id)
            if node is not None:
                return node.x, node.y
        for element_id in getattr(issue, "element_ids", []) or []:
            element = element_by_id.get(element_id)
            center = self._diagnostic_element_center(element, node_by_id) if element is not None else None
            if center is not None:
                return center
        return None

    def _draw_diagnostic_element_on_canvas(self, canvas, element, node_by_id, transform, *, base: bool, color: str | None = None, width_override: int | None = None) -> None:
        points = self._diagnostic_element_points(element, node_by_id)
        if not points:
            return
        elem_type = str(element.elem_type or "").upper()
        if color is None:
            if elem_type == "COLUMN":
                color = "#188038"
            elif elem_type in DIAGNOSTIC_PREVIEW_WALL_TYPES:
                color = "#5f6368"
            else:
                color = "#8b8f94"
        width = width_override if width_override is not None else (1 if base else 4)
        dash = (3, 3) if base and elem_type not in DIAGNOSTIC_PREVIEW_LINE_TYPES and elem_type != "COLUMN" else None
        canvas_points = [transform(x, y) for _node_id, x, y in points]
        if elem_type == "COLUMN":
            x, y = canvas_points[0]
            if len(canvas_points) >= 2 and self._diagnostic_canvas_distance(canvas_points[0], canvas_points[-1]) > 3:
                canvas.create_line(*canvas_points[0], *canvas_points[-1], fill=color, width=width)
            else:
                radius = 3 if base else 5
                canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline=color, fill="white", width=width)
            return
        if elem_type in DIAGNOSTIC_PREVIEW_WALL_TYPES and len(canvas_points) >= 3:
            flat = [coord for point in canvas_points for coord in point]
            canvas.create_polygon(*flat, outline=color, fill="", width=width)
            return
        if len(canvas_points) >= 2:
            if elem_type in DIAGNOSTIC_PREVIEW_LINE_TYPES:
                canvas.create_line(*canvas_points[0], *canvas_points[1], fill=color, width=width)
            else:
                for first, second in zip(canvas_points, canvas_points[1:]):
                    canvas.create_line(*first, *second, fill=color, width=width, dash=dash)

    def _diagnostic_element_points(self, element, node_by_id) -> list[tuple[int, float, float]]:
        return [(node_id, node_by_id[node_id].x, node_by_id[node_id].y) for node_id in element.node_ids if node_id in node_by_id]

    def _diagnostic_element_center(self, element, node_by_id) -> tuple[float, float] | None:
        points = self._diagnostic_element_points(element, node_by_id)
        if not points:
            return None
        return (
            sum(x for _node_id, x, _y in points) / len(points),
            sum(y for _node_id, _x, y in points) / len(points),
        )

    def _diagnostic_bbox_from_nodes(self, nodes) -> tuple[float, float, float, float] | None:
        points = [(node.x, node.y) for node in nodes]
        if not points:
            return None
        return self._diagnostic_bbox_from_points(points)

    def _diagnostic_issue_focus_bbox(self, issue, node_by_id, element_by_id) -> tuple[float, float, float, float] | None:
        points: list[tuple[float, float]] = []
        for node_id in getattr(issue, "node_ids", []) or []:
            node = node_by_id.get(node_id)
            if node is not None:
                points.append((node.x, node.y))
        for element_id in getattr(issue, "element_ids", []) or []:
            element = element_by_id.get(element_id)
            if element is not None:
                points.extend((x, y) for _node_id, x, y in self._diagnostic_element_points(element, node_by_id))
        try:
            marker_x = float(issue.x)
            marker_y = float(issue.y)
        except Exception:
            marker_x = marker_y = math.nan
        if math.isfinite(marker_x) and math.isfinite(marker_y):
            points.append((marker_x, marker_y))
        return self._diagnostic_bbox_from_points(points) if points else None

    def _diagnostic_bbox_from_points(self, points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
        min_x = min(x for x, _y in points)
        max_x = max(x for x, _y in points)
        min_y = min(y for _x, y in points)
        max_y = max(y for _x, y in points)
        width = max(max_x - min_x, 1.0)
        height = max(max_y - min_y, 1.0)
        pad = max(width, height) * 0.08
        return (min_x - pad, min_y - pad, max_x + pad, max_y + pad)

    def _diagnostic_merge_bbox(self, first, second):
        if first is None:
            return second
        if second is None:
            return first
        return (
            min(first[0], second[0]),
            min(first[1], second[1]),
            max(first[2], second[2]),
            max(first[3], second[3]),
        )

    def _diagnostic_canvas_distance(self, first: tuple[float, float], second: tuple[float, float]) -> float:
        return math.hypot(first[0] - second[0], first[1] - second[1])

    def _ensure_pdf_tab_visible(self, *, select: bool = True) -> None:
        if not self.notebook:
            return
        if not self.pdf_tab_visible:
            self.notebook.insert(2, self.tab_pdf, text="3 PDF 하중 입력(선택)")
            self.pdf_tab_visible = True
            self._refresh_tab_labels()
        if select:
            self.notebook.select(self.tab_pdf)

    def _refresh_tab_labels(self) -> None:
        if not self.notebook:
            return
        if self.pdf_tab_visible:
            self.notebook.tab(self.tab_api, text="1 API 설정")
            self.notebook.tab(self.tab_model, text="2 모델/Story")
            self.notebook.tab(self.tab_pdf, text="3 PDF 하중 입력(선택)")
            self.notebook.tab(self.tab_dxf, text="4 DXF 생성/검증")
            self.notebook.tab(self.tab_hatch_work, text="5 기준층 하중/연속층 적용")
            self.notebook.tab(self.tab_build, text="6 MGT 입력/저장")
        else:
            self.notebook.tab(self.tab_api, text="1 API 설정")
            self.notebook.tab(self.tab_model, text="2 모델/Story")
            self.notebook.tab(self.tab_dxf, text="3 DXF 생성/검증")
            self.notebook.tab(self.tab_hatch_work, text="4 기준층 하중/연속층 적용")
            self.notebook.tab(self.tab_build, text="5 MGT 입력/저장")

    def _update_floorload_status(self, presence) -> None:
        self.floorload_status_var.set(presence.message)
        self.open_pdf_tab_button.state(["!disabled"])
        if presence.has_floorload:
            self.floorload_status_label.configure(foreground="green")
            self.open_pdf_tab_button.configure(text="PDF 하중 입력 탭 열기(선택)")
        else:
            self.floorload_status_label.configure(foreground="#b36b00")
            self.open_pdf_tab_button.configure(text="PDF로 하중 입력하기")

    def _refresh_pdf_listbox(self) -> None:
        if not hasattr(self, "pdf_listbox"):
            return
        self.pdf_listbox.delete(0, "end")
        for path in self.selected_pdf_paths:
            self.pdf_listbox.insert("end", str(path))

    def _update_pdf_result(self, result: PdfLoadImportResult) -> None:
        self.pdf_import_result = result
        if result.mgtx_path:
            self.pdf_mgtx_path.set(str(result.mgtx_path))
        self._refresh_pdf_tree(result.classified_rows)
        self._update_pdf_load_items_from_lines(result.layer_lines)
        self.pdf_summary_label.configure(
            text=(
                f"PDF 분석 결과: PDF {len(result.input_pdf_paths)}개, 원시 후보 {len(result.raw_rows)}개, "
                f"MGTX 유효 row {len(result.valid_rows)}개, 검토/제외 {len(result.error_rows)}개, "
                f"DXF 레이어 후보 {len(result.layer_lines)}개\n"
                f"작업 폴더: {result.output_dir}"
            )
        )

    def _refresh_pdf_tree(self, rows) -> None:
        if not hasattr(self, "pdf_tree"):
            return
        for item in self.pdf_tree.get_children():
            self.pdf_tree.delete(item)
        for row in rows or []:
            valid = bool(row.get("is_valid_for_mgtx"))
            status = "입력 가능" if valid else "검토/제외"
            source = f"{row.get('source_pdf') or ''} / p{row.get('source_page') or ''}"
            reason = row.get("exclude_reason") or row.get("failure_reason") or row.get("review_required_reason") or row.get("validation_messages") or ""
            if isinstance(reason, (list, tuple)):
                reason = " | ".join(map(str, reason))
            self.pdf_tree.insert(
                "",
                "end",
                values=(
                    status,
                    row.get("floor_load_type_name") or row.get("floor_usage_name") or "",
                    row.get("load_case_name") or "",
                    row.get("floor_load_value") or row.get("load_value_kn_per_m2") or "",
                    source,
                    reason,
                ),
            )

    def log(self, message: str) -> None:
        self.logger.info(message)
        self.log_text.insert("end", str(message) + "\n") if hasattr(self, "log_text") else None
        if hasattr(self, "log_text"):
            self.log_text.see("end")


def main() -> None:
    app = FloorLoadAutoApp()
    app.mainloop()


if __name__ == "__main__":
    main()
