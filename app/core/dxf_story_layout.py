from __future__ import annotations

from dataclasses import asdict, dataclass
from math import hypot
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence
import json
import re

import ezdxf
from shapely.affinity import affine_transform
from shapely.geometry import Polygon

from .load_parser import normalize_cad_layer_name

_HATCH_BBOX_EXCLUDED_LAYERS = {
    "CENTERLINE_COLUMN",
    "CENTERLINE_BEAM",
    "CENTERLINE_WALL",
    "REFERENCE_GRID",
    "FLOAD_GUIDE",
    "FLOAD_HATCH_GUIDE",
    "STORY_LABEL",
    "FLOAD_DIRECTION_GUIDE",
}


@dataclass(frozen=True)
class BBox2D:
    min_x: float
    min_y: float
    max_x: float
    max_y: float

    @property
    def width(self) -> float:
        return max(0.0, self.max_x - self.min_x)

    @property
    def height(self) -> float:
        return max(0.0, self.max_y - self.min_y)

    @property
    def area(self) -> float:
        return self.width * self.height

    def translated(self, dx: float, dy: float) -> "BBox2D":
        return BBox2D(self.min_x + dx, self.min_y + dy, self.max_x + dx, self.max_y + dy)

    def to_polygon(self) -> Polygon:
        return Polygon([(self.min_x, self.min_y), (self.max_x, self.min_y), (self.max_x, self.max_y), (self.min_x, self.max_y)])

    def contains_point(self, x: float, y: float) -> bool:
        return self.min_x <= float(x) <= self.max_x and self.min_y <= float(y) <= self.max_y

    def overlap_area(self, other: "BBox2D") -> float:
        min_x = max(self.min_x, other.min_x)
        min_y = max(self.min_y, other.min_y)
        max_x = min(self.max_x, other.max_x)
        max_y = min(self.max_y, other.max_y)
        if max_x <= min_x or max_y <= min_y:
            return 0.0
        return (max_x - min_x) * (max_y - min_y)


def normalize_dxf_unit_scale(value) -> float:
    try:
        scale = float(value)
    except Exception:
        return 1.0
    if scale <= 0.0:
        return 1.0
    return scale


@dataclass(frozen=True)
class Affine2D:
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def apply(self, x: float, y: float) -> tuple[float, float]:
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)

    def inverse(self) -> "Affine2D":
        det = self.a * self.d - self.b * self.c
        if abs(det) < 1.0e-12:
            raise ValueError("DXF story layout transform is not invertible.")
        inv_a = self.d / det
        inv_b = -self.b / det
        inv_c = -self.c / det
        inv_d = self.a / det
        inv_e = -(inv_a * self.e + inv_c * self.f)
        inv_f = -(inv_b * self.e + inv_d * self.f)
        return Affine2D(inv_a, inv_b, inv_c, inv_d, inv_e, inv_f)

    def shapely_tuple(self) -> tuple[float, float, float, float, float, float]:
        return (self.a, self.c, self.b, self.d, self.e, self.f)


@dataclass(frozen=True)
class StoryLayout:
    story_name: str
    story_index: int | None
    elevation: float | None
    source_bbox: BBox2D
    placed_bbox: BBox2D
    offset_x: float
    offset_y: float
    scale: float
    rotation_deg: float
    insertion_x: float
    insertion_y: float
    transform: Affine2D
    inverse_transform: Affine2D
    label_x: float
    label_y: float
    text_height: float


@dataclass(frozen=True)
class DxfStoryLabel:
    text: str
    x: float
    y: float
    layer: str


@dataclass(frozen=True)
class LayoutMetadataCandidateScore:
    path: Path
    score: float
    details: dict


@dataclass(frozen=True)
class LayoutMetadataSelection:
    selected_path: Path | None
    candidates: tuple[LayoutMetadataCandidateScore, ...]
    selection_required: bool = False
    reason: str = ""


def bbox_from_points(points: Iterable[tuple[float, float]], fallback_size: float = 1.0) -> BBox2D:
    pts = [(float(x), float(y)) for x, y in points]
    if not pts:
        half = max(float(fallback_size), 1.0) / 2.0
        return BBox2D(-half, -half, half, half)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    if abs(max_x - min_x) <= 1.0e-9:
        min_x -= fallback_size / 2.0
        max_x += fallback_size / 2.0
    if abs(max_y - min_y) <= 1.0e-9:
        min_y -= fallback_size / 2.0
        max_y += fallback_size / 2.0
    return BBox2D(min_x, min_y, max_x, max_y)


def _bbox_reference_dimension(bbox: BBox2D) -> float:
    width = max(float(bbox.width), 0.0)
    height = max(float(bbox.height), 0.0)
    if width > 0.0 and height > 0.0:
        return min(width, height)
    return max(width, height, 1.0)


def _compute_story_label_text_height(bbox: BBox2D) -> float:
    return _compute_story_label_text_height_from_ref(_bbox_reference_dimension(bbox))


def _compute_story_label_text_height_from_ref(ref: float) -> float:
    base = max(float(ref), 1.0e-9)
    return _clamp(base * 0.045, base * 0.025, base * 0.080)


def _compute_point_display_size_from_ref(ref: float) -> float:
    base = max(float(ref), 1.0e-9)
    return _clamp(base * 0.012, base * 0.004, base * 0.025)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(float(minimum), min(float(value), float(maximum)))


def plan_story_layouts(
    stories: Sequence[object],
    source_bboxes: Sequence[BBox2D],
    *,
    dxf_unit_scale_from_model: float = 1.0,
) -> list[StoryLayout]:
    if len(stories) != len(source_bboxes):
        raise ValueError("stories and source_bboxes must have the same length.")
    if not stories:
        return []

    scale = normalize_dxf_unit_scale(dxf_unit_scale_from_model)
    layouts: list[StoryLayout] = []
    cursor_y = 0.0
    for index, (story, bbox) in enumerate(zip(stories, source_bboxes)):
        scaled_bbox = BBox2D(bbox.min_x * scale, bbox.min_y * scale, bbox.max_x * scale, bbox.max_y * scale)
        offset_x = -scaled_bbox.min_x
        offset_y = cursor_y - scaled_bbox.max_y
        transform = Affine2D(a=scale, d=scale, e=offset_x, f=offset_y)
        inverse = transform.inverse()
        placed = transform_bbox(bbox, transform)
        text_height = _compute_story_label_text_height(placed)
        story_short = max(min(placed.width, placed.height), 1.0)
        label_margin = max(text_height * 2.5, story_short * 0.03)
        story_name = str(getattr(story, "name", f"Story{index + 1}"))
        elevation = getattr(story, "elevation", None)
        layouts.append(
            StoryLayout(
                story_name=story_name,
                story_index=index,
                elevation=None if elevation is None else float(elevation),
                source_bbox=bbox,
                placed_bbox=placed,
                offset_x=offset_x,
                offset_y=offset_y,
                scale=scale,
                rotation_deg=0.0,
                insertion_x=0.0,
                insertion_y=0.0,
                transform=transform,
                inverse_transform=inverse,
                label_x=placed.min_x - label_margin,
                label_y=(placed.min_y + placed.max_y) / 2.0,
                text_height=text_height,
            )
        )
        gap = max(placed.height * 0.25, text_height * 4.0, story_short * 0.10)
        cursor_y = placed.min_y - gap
    return layouts


def transform_bbox(bbox: BBox2D, transform: Affine2D) -> BBox2D:
    points = [
        transform.apply(bbox.min_x, bbox.min_y),
        transform.apply(bbox.max_x, bbox.min_y),
        transform.apply(bbox.max_x, bbox.max_y),
        transform.apply(bbox.min_x, bbox.max_y),
    ]
    return bbox_from_points(points)


def transform_polygon(polygon: Polygon, transform: Affine2D) -> Polygon:
    return affine_transform(polygon, transform.shapely_tuple())


def choose_story_layout_for_polygon(
    polygon: Polygon,
    layouts: Sequence[StoryLayout],
    *,
    min_overlap_ratio: float = 0.60,
    ambiguous_delta: float = 0.10,
) -> tuple[StoryLayout | None, str | None]:
    if not layouts or polygon.is_empty or polygon.area <= 1.0e-12:
        return None, "NO_STORY_LAYOUT"

    rep = polygon.representative_point()
    polygon_bbox = _bbox_from_bounds(polygon.bounds)
    bbox_area = max(polygon_bbox.area, 1.0e-12)
    scores: list[tuple[float, float, float, StoryLayout]] = []
    for layout in layouts:
        placed_poly = layout.placed_bbox.to_polygon()
        overlap = polygon.intersection(placed_poly).area
        ratio = overlap / max(polygon.area, 1.0e-12)
        point_score = 1.0 if layout.placed_bbox.contains_point(rep.x, rep.y) else 0.0
        bbox_ratio = layout.placed_bbox.overlap_area(polygon_bbox) / bbox_area
        scores.append((ratio, point_score, bbox_ratio, layout))
    scores.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

    best_ratio, best_point_score, best_bbox_ratio, best_layout = scores[0]
    if best_ratio < min_overlap_ratio and best_point_score <= 0.0:
        return best_layout, "AMBIGUOUS_STORY"
    if best_ratio <= 1.0e-12 and best_bbox_ratio <= 1.0e-12:
        return best_layout, "AMBIGUOUS_STORY"
    if len(scores) > 1 and best_ratio - scores[1][0] < ambiguous_delta and scores[1][0] > 1.0e-12:
        return best_layout, "AMBIGUOUS_STORY"
    return best_layout, None


_USER_EDIT_SUFFIXES = (
    "_사용자입력",
    "_user_input",
    "_edited",
    "_작성",
    "_수정",
    "_수정본",
    "_copy",
    "_복사본",
)


AUTO_SELECT_MIN_SCORE = 700.0
AUTO_SELECT_MIN_DELTA = 50.0


def find_layout_metadata_candidates(
    *,
    dxf_path: Path,
    explicit_path: Path | None = None,
    project_dxf_templates_dir: Path | None = None,
    project_root: Path | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    dxf = Path(dxf_path)

    if explicit_path and Path(explicit_path).exists():
        candidates.append(Path(explicit_path))

    stems = _candidate_template_stems(dxf.stem)
    for stem in stems:
        candidates.append(dxf.parent / f"{stem}.layout_metadata.json")

    try:
        candidates.extend(path for path in dxf.parent.glob("*layout_metadata.json") if path.is_file())
    except OSError:
        pass

    template_dirs: list[Path] = []
    if project_dxf_templates_dir:
        template_dirs.append(Path(project_dxf_templates_dir))
    if project_root:
        root = Path(project_root)
        template_dirs.extend([root / "dxf_templates", root])

    for directory in template_dirs:
        if not directory.exists():
            continue
        try:
            candidates.extend(path for path in directory.glob("*ALL_STORIES*layout_metadata.json") if path.is_file())
            candidates.extend(path for path in directory.glob("*layout_metadata.json") if path.is_file())
        except OSError:
            continue

    return _dedupe_existing_paths(candidates)


def find_layout_metadata_path(
    dxf_path: str | Path,
    *,
    mapping_path: str | Path | None = None,
    search_dirs: Sequence[str | Path] | None = None,
    project_dxf_templates_dir: str | Path | None = None,
) -> Path | None:
    explicit = None
    candidates = find_layout_metadata_candidates(
        dxf_path=Path(dxf_path),
        explicit_path=explicit,
        project_dxf_templates_dir=Path(project_dxf_templates_dir) if project_dxf_templates_dir else None,
    )
    search_dir_candidates: list[Path] = []
    for directory in search_dirs or ():
        path = Path(directory)
        if not path.exists():
            continue
        try:
            search_dir_candidates.extend(candidate for candidate in path.glob("*ALL_STORIES*layout_metadata.json") if candidate.is_file())
            search_dir_candidates.extend(candidate for candidate in path.glob("*layout_metadata.json") if candidate.is_file())
        except OSError:
            continue
    candidates = _dedupe_existing_paths([*candidates, *search_dir_candidates])
    if not candidates:
        extra_search_dirs = list(search_dirs or [])
        if project_dxf_templates_dir:
            extra_search_dirs.append(project_dxf_templates_dir)
        return _find_template_artifact_path(
            dxf_path,
            suffix=".layout_metadata.json",
            mapping_path=mapping_path,
            search_dirs=extra_search_dirs,
        )
    result = select_layout_metadata(
        dxf_path=Path(dxf_path),
        explicit_path=None,
        project_dxf_templates_dir=Path(project_dxf_templates_dir) if project_dxf_templates_dir else None,
        extra_candidates=candidates,
    )
    return result.selected_path


def find_layer_mapping_path(
    dxf_path: str | Path,
    *,
    search_dirs: Sequence[str | Path] | None = None,
) -> Path | None:
    json_path = _find_template_artifact_path(dxf_path, suffix=".layer_mapping.json", search_dirs=search_dirs)
    if json_path:
        return json_path
    return _find_template_artifact_path(dxf_path, suffix=".layer_mapping.csv", search_dirs=search_dirs)


def select_layout_metadata(
    *,
    dxf_path: Path,
    explicit_path: Path | None = None,
    project_dxf_templates_dir: Path | None = None,
    project_root: Path | None = None,
    extra_candidates: Sequence[Path] | None = None,
) -> LayoutMetadataSelection:
    if explicit_path and Path(explicit_path).exists():
        path = Path(explicit_path)
        score, details = score_layout_metadata_candidate(
            dxf_story_labels=extract_story_label_fingerprint(Path(dxf_path)),
            metadata_path=path,
            hatch_bboxes=_extract_hatch_bboxes(Path(dxf_path)),
        )
        return LayoutMetadataSelection(path, (LayoutMetadataCandidateScore(path, score, details),), False, "EXPLICIT")

    candidates = find_layout_metadata_candidates(
        dxf_path=Path(dxf_path),
        explicit_path=None,
        project_dxf_templates_dir=project_dxf_templates_dir,
        project_root=project_root,
    )
    candidates = _dedupe_existing_paths([*(extra_candidates or ()), *candidates])
    if not candidates:
        return LayoutMetadataSelection(None, tuple(), False, "NO_CANDIDATES")

    labels = extract_story_label_fingerprint(Path(dxf_path))
    hatch_bboxes = _extract_hatch_bboxes(Path(dxf_path))
    scored: list[LayoutMetadataCandidateScore] = []
    for candidate in candidates:
        score, details = score_layout_metadata_candidate(
            dxf_story_labels=labels,
            metadata_path=candidate,
            hatch_bboxes=hatch_bboxes,
        )
        scored.append(LayoutMetadataCandidateScore(candidate, score, details))
    scored.sort(key=lambda item: (-item.score, str(item.path).lower()))

    if len(scored) == 1:
        return LayoutMetadataSelection(scored[0].path, tuple(scored), False, "SINGLE_CANDIDATE")

    best = scored[0]
    second_score = scored[1].score if len(scored) > 1 else 0.0
    if best.score >= AUTO_SELECT_MIN_SCORE and best.score - second_score >= AUTO_SELECT_MIN_DELTA:
        return LayoutMetadataSelection(best.path, tuple(scored), False, "AUTO_SELECTED")
    return LayoutMetadataSelection(None, tuple(scored), True, "AMBIGUOUS_CANDIDATES")


def extract_story_label_fingerprint(dxf_path: Path) -> list[DxfStoryLabel]:
    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception:
        return []

    story_layer_labels: list[DxfStoryLabel] = []
    fallback_labels: list[DxfStoryLabel] = []
    for entity in doc.modelspace():
        if entity.dxftype() not in {"TEXT", "MTEXT"}:
            continue
        text = _entity_text(entity)
        if not text:
            continue
        point = _entity_insert_point(entity)
        if point is None:
            continue
        layer = str(getattr(entity.dxf, "layer", "") or "")
        label = DxfStoryLabel(text=text, x=point[0], y=point[1], layer=layer)
        if layer.upper() == "STORY_LABEL":
            story_layer_labels.append(label)
        elif _looks_like_story_label(text):
            fallback_labels.append(label)
    return story_layer_labels or fallback_labels


def score_layout_metadata_candidate(
    *,
    dxf_story_labels: list[DxfStoryLabel],
    metadata_path: Path,
    hatch_bboxes: list[tuple[float, float, float, float]],
) -> tuple[float, dict]:
    path = Path(metadata_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0.0, {"error": "READ_FAILED", "story_count": 0, "label_match_count": 0}

    layouts = layouts_from_metadata(data)
    details: dict = {
        "mode": str(data.get("mode") or ""),
        "story_count": len(layouts),
        "label_match_count": 0,
        "label_position_error": None,
        "hatch_overlap_ratio": 0.0,
    }
    if not layouts:
        return 0.0, details

    score = 100.0 if data.get("mode") == "ALL_STORIES" else 0.0
    layout_by_name = {_normalize_story_label(layout.story_name): layout for layout in layouts if layout.story_name}
    matched_pairs: list[tuple[DxfStoryLabel, StoryLayout, float]] = []
    for label in dxf_story_labels:
        layout = layout_by_name.get(_normalize_story_label(label.text))
        if not layout:
            continue
        distance = hypot(layout.label_x - label.x, layout.label_y - label.y)
        matched_pairs.append((label, layout, distance))

    if dxf_story_labels:
        match_ratio = len(matched_pairs) / max(len(dxf_story_labels), 1)
        score += match_ratio * 500.0
        details["label_match_count"] = len(matched_pairs)
        details["label_count"] = len(dxf_story_labels)

    if matched_pairs:
        label_bbox = bbox_from_points((label.x, label.y) for label, _layout, _distance in matched_pairs)
        metadata_label_bbox = bbox_from_points((layout.label_x, layout.label_y) for _label, layout, _distance in matched_pairs)
        label_scale = max(
            hypot(label_bbox.width, label_bbox.height),
            median([max(layout.text_height * 10.0, 1.0) for _label, layout, _distance in matched_pairs]),
            1.0,
        )
        avg_error = sum(distance for _label, _layout, distance in matched_pairs) / len(matched_pairs)
        normalized_error = avg_error / label_scale
        score += max(0.0, 300.0 * (1.0 - normalized_error))
        details["label_position_error"] = avg_error

        bbox_size_error = (
            abs(label_bbox.width - metadata_label_bbox.width)
            + abs(label_bbox.height - metadata_label_bbox.height)
        ) / max(label_scale, 1.0)
        score += max(0.0, 100.0 * (1.0 - bbox_size_error))
        details["label_bbox_size_error"] = bbox_size_error

    hatch_overlap_ratio = _hatch_layout_overlap_ratio(hatch_bboxes, layouts)
    score += hatch_overlap_ratio * 100.0
    details["hatch_overlap_ratio"] = hatch_overlap_ratio
    return score, details


def metadata_from_layouts(
    layouts: Sequence[StoryLayout],
    *,
    mode: str = "ALL_STORIES",
    model_length_unit: str = "",
    dxf_unit_scale_from_model: float = 1.0,
) -> dict:
    scale = normalize_dxf_unit_scale(dxf_unit_scale_from_model)
    return {
        "version": 2,
        "mode": str(mode or "ALL_STORIES"),
        "coordinate_system": "model_xy_to_dxf_xy",
        "model_length_unit": str(model_length_unit or ""),
        "dxf_display_unit": "MM",
        "dxf_unit_scale_from_model": scale,
        "model_unit_scale_from_dxf": 1.0 / scale,
        "stories": [_layout_to_dict(layout) for layout in layouts],
    }


def layouts_from_metadata(data: dict) -> list[StoryLayout]:
    if not isinstance(data, dict) or data.get("mode") not in {"ALL_STORIES", "SINGLE_STORY"}:
        return []
    return [_layout_from_dict(row) for row in data.get("stories", []) if isinstance(row, dict)]


def write_layout_metadata(
    path: str | Path,
    layouts: Sequence[StoryLayout],
    *,
    mode: str = "ALL_STORIES",
    model_length_unit: str = "",
    dxf_unit_scale_from_model: float = 1.0,
) -> Path:
    out = Path(path)
    out.write_text(
        json.dumps(
            metadata_from_layouts(
                layouts,
                mode=mode,
                model_length_unit=model_length_unit,
                dxf_unit_scale_from_model=dxf_unit_scale_from_model,
            ),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return out


def read_layout_metadata(path: str | Path) -> list[StoryLayout]:
    p = Path(path)
    if not p.exists():
        return []
    return layouts_from_metadata(json.loads(p.read_text(encoding="utf-8")))


def load_story_layout_metadata(path: str | Path) -> list[StoryLayout]:
    return read_layout_metadata(path)


def _find_template_artifact_path(
    dxf_path: str | Path,
    *,
    suffix: str,
    mapping_path: str | Path | None = None,
    search_dirs: Sequence[str | Path] | None = None,
) -> Path | None:
    dxf = Path(dxf_path)
    dirs = _candidate_search_dirs(dxf, mapping_path=mapping_path, search_dirs=search_dirs)
    stems = _candidate_template_stems(dxf.stem)

    for directory in dirs:
        for stem in stems:
            candidate = directory / f"{stem}{suffix}"
            if candidate.exists():
                return candidate

    matches: list[Path] = []
    for directory in dirs:
        if not directory.exists():
            continue
        for stem in stems[1:] + stems[:1]:
            try:
                matches.extend(path for path in directory.glob(f"{stem}*{suffix}") if path.is_file())
            except OSError:
                continue
    if not matches:
        matches = _all_story_template_artifact_candidates(dirs, suffix)
        if not matches:
            return None
    if len(matches) > 1 and suffix == ".layout_metadata.json":
        result = select_layout_metadata(dxf_path=dxf, extra_candidates=matches)
        return result.selected_path
    matches.sort(key=lambda path: (len(path.stem), str(path).lower()))
    return matches[0]


def _candidate_search_dirs(
    dxf: Path,
    *,
    mapping_path: str | Path | None = None,
    search_dirs: Sequence[str | Path] | None = None,
) -> list[Path]:
    raw_dirs: list[Path] = [dxf.parent]
    if mapping_path:
        raw_dirs.append(Path(mapping_path).parent)
    raw_dirs.extend(Path(path) for path in (search_dirs or ()))

    result: list[Path] = []
    seen: set[str] = set()
    for directory in raw_dirs:
        resolved = directory.expanduser()
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(resolved)
    return result


def _dedupe_existing_paths(paths: Sequence[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        p = Path(path)
        if not p.exists():
            continue
        try:
            key = str(p.resolve()).lower()
        except OSError:
            key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(p)
    return result


def _candidate_template_stems(stem: str) -> list[str]:
    candidates = [stem]
    stripped = stem
    changed = True
    while changed:
        changed = False
        lower = stripped.lower()
        for suffix in _USER_EDIT_SUFFIXES:
            if lower.endswith(suffix.lower()):
                stripped = stripped[: -len(suffix)]
                if stripped and stripped not in candidates:
                    candidates.append(stripped)
                changed = True
                break

    marker = "_floorload_template"
    lower_stem = stem.lower()
    marker_index = lower_stem.find(marker)
    if marker_index >= 0:
        template_stem = stem[: marker_index + len(marker)]
        if template_stem and template_stem not in candidates:
            candidates.append(template_stem)

    return candidates


def _all_story_template_artifact_candidates(dirs: Sequence[Path], suffix: str) -> list[Path]:
    matches: list[Path] = []
    seen: set[str] = set()
    for directory in dirs:
        if not directory.exists():
            continue
        try:
            candidates = [path for path in directory.glob(f"*{suffix}") if path.is_file()]
        except OSError:
            continue
        for path in candidates:
            lower_name = path.name.lower()
            if "all_stories" not in lower_name and "all_story" not in lower_name:
                continue
            if "floorload_template" not in lower_name:
                continue
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            matches.append(path)
    matches.sort(key=lambda path: str(path).lower())
    return matches


def _extract_hatch_bboxes(dxf_path: Path) -> list[tuple[float, float, float, float]]:
    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception:
        return []
    bboxes: list[tuple[float, float, float, float]] = []
    for entity in doc.modelspace():
        layer = normalize_cad_layer_name(str(getattr(entity.dxf, "layer", "") or ""))
        if layer in _HATCH_BBOX_EXCLUDED_LAYERS:
            continue
        if entity.dxftype() == "HATCH":
            bbox = _hatch_entity_bbox(entity)
            if bbox:
                bboxes.append(bbox)
        elif entity.dxftype() in {"LWPOLYLINE", "POLYLINE"}:
            if not layer.startswith("LOAD_"):
                continue
            bbox = _polyline_entity_bbox(entity)
            if bbox:
                bboxes.append(bbox)
    return bboxes


def _hatch_entity_bbox(entity) -> tuple[float, float, float, float] | None:
    points: list[tuple[float, float]] = []
    for path in getattr(entity, "paths", []) or []:
        if hasattr(path, "vertices"):
            for item in path.vertices:
                if len(item) >= 2:
                    points.append((float(item[0]), float(item[1])))
        elif hasattr(path, "edges"):
            for edge in path.edges:
                if hasattr(edge, "start"):
                    points.append(_xy(edge.start))
                if hasattr(edge, "end"):
                    points.append(_xy(edge.end))
                if hasattr(edge, "center") and hasattr(edge, "radius"):
                    cx, cy = _xy(edge.center)
                    radius = float(edge.radius)
                    points.extend([(cx - radius, cy - radius), (cx + radius, cy + radius)])
    return _bbox_tuple_from_points(points)


def _polyline_entity_bbox(entity) -> tuple[float, float, float, float] | None:
    if entity.dxftype() == "LWPOLYLINE":
        points = [(float(x), float(y)) for x, y, *_rest in entity.get_points("xy")]
    else:
        points = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entity.vertices]
    return _bbox_tuple_from_points(points)


def _bbox_tuple_from_points(points: Sequence[tuple[float, float]]) -> tuple[float, float, float, float] | None:
    if not points:
        return None
    xs = [float(x) for x, _y in points]
    ys = [float(y) for _x, y in points]
    return (min(xs), min(ys), max(xs), max(ys))


def _hatch_layout_overlap_ratio(hatch_bboxes: Sequence[tuple[float, float, float, float]], layouts: Sequence[StoryLayout]) -> float:
    if not hatch_bboxes or not layouts:
        return 0.0
    ratios: list[float] = []
    for bbox_tuple in hatch_bboxes:
        bbox = _bbox_from_bounds(bbox_tuple)
        area = max(bbox.area, 1.0e-12)
        best = max(layout.placed_bbox.overlap_area(bbox) / area for layout in layouts)
        ratios.append(min(max(best, 0.0), 1.0))
    return sum(ratios) / len(ratios)


def _entity_insert_point(entity) -> tuple[float, float] | None:
    point = getattr(entity.dxf, "insert", None)
    if point is None and hasattr(entity, "get_location"):
        try:
            point = entity.get_location()[1]
        except Exception:
            point = None
    if point is None:
        return None
    return _xy(point)


def _xy(point) -> tuple[float, float]:
    if hasattr(point, "x") and hasattr(point, "y"):
        return (float(point.x), float(point.y))
    return (float(point[0]), float(point[1]))


def _looks_like_story_label(text: str) -> bool:
    compact = "".join(str(text or "").split())
    if not compact:
        return False
    if len(compact) > 32:
        return False
    return bool(re.match(r"^(?:B\d+|P\d+|\d+F|R(?:F|OOF)?|ROOF|[A-Z가-힣0-9_-]{1,16})$", compact, re.IGNORECASE))


def _entity_text(entity) -> str:
    if entity.dxftype() == "MTEXT":
        text = str(getattr(entity, "text", "") or "")
    else:
        text = str(getattr(entity.dxf, "text", "") or "")
    return " ".join(text.replace("\\P", " ").split()).strip()


def _normalize_story_label(value: object) -> str:
    return "".join(str(value or "").split()).upper()


def _bbox_from_bounds(bounds) -> BBox2D:
    min_x, min_y, max_x, max_y = bounds
    return BBox2D(float(min_x), float(min_y), float(max_x), float(max_y))


def _layout_to_dict(layout: StoryLayout) -> dict:
    data = {
        "story_name": layout.story_name,
        "story_index": layout.story_index,
        "elevation": layout.elevation,
        "source_bbox": asdict(layout.source_bbox),
        "placed_bbox": asdict(layout.placed_bbox),
        "offset": {"x": layout.offset_x, "y": layout.offset_y},
        "scale": layout.scale,
        "rotation_deg": layout.rotation_deg,
        "insertion_point": {"x": layout.insertion_x, "y": layout.insertion_y},
        "transform": asdict(layout.transform),
        "inverse_transform": asdict(layout.inverse_transform),
        "label_position": {"x": layout.label_x, "y": layout.label_y},
        "text_height": layout.text_height,
    }
    return data


def _layout_from_dict(data: dict) -> StoryLayout:
    offset = data.get("offset", {}) or {}
    insertion = data.get("insertion_point", {}) or {}
    label = data.get("label_position", {}) or {}
    transform = _affine_from_dict(data.get("transform", {}) or {})
    inverse = _affine_from_dict(data.get("inverse_transform", {}) or transform.inverse().__dict__)
    return StoryLayout(
        story_name=str(data.get("story_name") or ""),
        story_index=data.get("story_index"),
        elevation=data.get("elevation"),
        source_bbox=_bbox_from_dict(data.get("source_bbox", {}) or {}),
        placed_bbox=_bbox_from_dict(data.get("placed_bbox", {}) or {}),
        offset_x=float(offset.get("x", 0.0)),
        offset_y=float(offset.get("y", 0.0)),
        scale=float(data.get("scale", 1.0)),
        rotation_deg=float(data.get("rotation_deg", 0.0)),
        insertion_x=float(insertion.get("x", 0.0)),
        insertion_y=float(insertion.get("y", 0.0)),
        transform=transform,
        inverse_transform=inverse,
        label_x=float(label.get("x", 0.0)),
        label_y=float(label.get("y", 0.0)),
        text_height=float(data.get("text_height", 0.25)),
    )


def _bbox_from_dict(data: dict) -> BBox2D:
    return BBox2D(float(data.get("min_x", 0.0)), float(data.get("min_y", 0.0)), float(data.get("max_x", 0.0)), float(data.get("max_y", 0.0)))


def _affine_from_dict(data: dict) -> Affine2D:
    return Affine2D(
        float(data.get("a", 1.0)),
        float(data.get("b", 0.0)),
        float(data.get("c", 0.0)),
        float(data.get("d", 1.0)),
        float(data.get("e", 0.0)),
        float(data.get("f", 0.0)),
    )
