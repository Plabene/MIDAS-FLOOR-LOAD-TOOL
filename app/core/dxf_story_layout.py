from __future__ import annotations

from dataclasses import asdict, dataclass
from math import hypot
from pathlib import Path
from statistics import median
from typing import Iterable, Sequence
import json

import ezdxf
from shapely.affinity import affine_transform
from shapely.geometry import Polygon


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


def plan_story_layouts(stories: Sequence[object], source_bboxes: Sequence[BBox2D]) -> list[StoryLayout]:
    if len(stories) != len(source_bboxes):
        raise ValueError("stories and source_bboxes must have the same length.")
    if not stories:
        return []

    heights = [bbox.height for bbox in source_bboxes if bbox.height > 1.0e-9]
    widths = [bbox.width for bbox in source_bboxes if bbox.width > 1.0e-9]
    representative_height = median(heights) if heights else 1.0
    representative_width = median(widths) if widths else representative_height
    representative_size = max(representative_height, representative_width, 1.0)
    text_height = max(representative_size * 0.025, representative_height * 0.02, 0.25)

    layouts: list[StoryLayout] = []
    cursor_y = 0.0
    for index, (story, bbox) in enumerate(zip(stories, source_bboxes)):
        height = max(bbox.height, representative_height)
        gap = max(height * 0.20, text_height * 8.0, representative_height * 0.10)
        offset_x = -bbox.min_x
        offset_y = cursor_y - bbox.max_y
        transform = Affine2D(e=offset_x, f=offset_y)
        inverse = transform.inverse()
        placed = bbox.translated(offset_x, offset_y)
        label_margin = max(text_height * 4.0, placed.width * 0.04, 1.0)
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
                scale=1.0,
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
        cursor_y = placed.min_y - gap
    return layouts


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
    "_수정본",
)


def find_layout_metadata_path(
    dxf_path: str | Path,
    *,
    mapping_path: str | Path | None = None,
    search_dirs: Sequence[str | Path] | None = None,
    project_dxf_templates_dir: str | Path | None = None,
) -> Path | None:
    extra_search_dirs = list(search_dirs or [])
    if project_dxf_templates_dir:
        extra_search_dirs.append(project_dxf_templates_dir)
    return _find_template_artifact_path(
        dxf_path,
        suffix=".layout_metadata.json",
        mapping_path=mapping_path,
        search_dirs=extra_search_dirs,
    )


def find_layer_mapping_path(
    dxf_path: str | Path,
    *,
    search_dirs: Sequence[str | Path] | None = None,
) -> Path | None:
    json_path = _find_template_artifact_path(dxf_path, suffix=".layer_mapping.json", search_dirs=search_dirs)
    if json_path:
        return json_path
    return _find_template_artifact_path(dxf_path, suffix=".layer_mapping.csv", search_dirs=search_dirs)


def metadata_from_layouts(layouts: Sequence[StoryLayout]) -> dict:
    return {
        "version": 1,
        "mode": "ALL_STORIES",
        "coordinate_system": "model_xy_to_dxf_xy",
        "stories": [_layout_to_dict(layout) for layout in layouts],
    }


def layouts_from_metadata(data: dict) -> list[StoryLayout]:
    if not isinstance(data, dict) or data.get("mode") != "ALL_STORIES":
        return []
    return [_layout_from_dict(row) for row in data.get("stories", []) if isinstance(row, dict)]


def write_layout_metadata(path: str | Path, layouts: Sequence[StoryLayout]) -> Path:
    out = Path(path)
    out.write_text(json.dumps(metadata_from_layouts(layouts), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
            selected = _choose_layout_metadata_by_story_labels(dxf, matches)
            if selected:
                return selected
            if _read_story_labels_from_dxf(dxf):
                raise RuntimeError(
                    "전층 DXF layout metadata 후보가 여러 개라 자동 선택할 수 없습니다. "
                    "DXF 검증 전에 해당 template의 layout_metadata.json을 명시해 주세요."
                )
    if len(matches) > 1 and suffix == ".layout_metadata.json":
        selected = _choose_layout_metadata_by_story_labels(dxf, matches)
        if selected:
            return selected
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


def _choose_layout_metadata_by_story_labels(dxf_path: Path, candidates: Sequence[Path]) -> Path | None:
    labels = _read_story_labels_from_dxf(dxf_path)
    if not labels:
        return None
    scored: list[tuple[int, float, Path]] = []
    for candidate in candidates:
        layouts = read_layout_metadata(candidate)
        if not layouts:
            continue
        layout_by_name = {_normalize_story_label(layout.story_name): layout for layout in layouts if layout.story_name}
        match_count = 0
        distance_sum = 0.0
        for text, x, y in labels:
            layout = layout_by_name.get(_normalize_story_label(text))
            if not layout:
                continue
            tolerance = max(float(layout.text_height or 0.25) * 8.0, layout.placed_bbox.width * 0.02, 0.5)
            distance = hypot(float(layout.label_x) - x, float(layout.label_y) - y)
            if distance <= tolerance:
                match_count += 1
                distance_sum += distance
        if match_count:
            scored.append((match_count, distance_sum, candidate))
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], item[1], str(item[2]).lower()))
    best = scored[0]
    if len(scored) > 1:
        second = scored[1]
        if best[0] == second[0] and abs(best[1] - second[1]) <= 1.0e-6:
            return None
    return best[2]


def _read_story_labels_from_dxf(dxf_path: Path) -> list[tuple[str, float, float]]:
    try:
        doc = ezdxf.readfile(str(dxf_path))
    except Exception:
        return []
    labels: list[tuple[str, float, float]] = []
    for entity in doc.modelspace():
        if entity.dxftype() not in {"TEXT", "MTEXT"}:
            continue
        layer = str(getattr(entity.dxf, "layer", "") or "").upper()
        if layer != "STORY_LABEL":
            continue
        text = _entity_text(entity)
        if not text:
            continue
        insert = getattr(entity.dxf, "insert", None)
        if insert is None:
            continue
        labels.append((text, float(insert.x), float(insert.y)))
    return labels


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
