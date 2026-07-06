from pathlib import Path
import shutil

import pytest

ezdxf = pytest.importorskip("ezdxf")

from app.core.dxf_load_reader import read_load_regions
from app.core.dxf_story_layout import find_layout_metadata_path, read_layout_metadata, select_layout_metadata
from app.core.dxf_template_writer import LoadLayerSpec, write_all_story_centerline_dxf
from app.core.mgt_parser import Element, Node, Story


def test_select_layout_metadata_by_story_label_fingerprint_when_multiple_candidates(tmp_path: Path):
    template_dir = tmp_path / "dxf_templates"
    template_dir.mkdir()
    target = _write_template(template_dir / "target_ALL_STORIES_floorload_template.dxf", ["1F", "2F", "3F", "4F"])
    _write_template(template_dir / "other_ALL_STORIES_floorload_template.dxf", ["B3", "B2", "B1"])
    user_dxf = _write_user_hatch_dxf(tmp_path / "renamed_anything.dxf", target, "3F")

    selection = select_layout_metadata(dxf_path=user_dxf, project_dxf_templates_dir=template_dir)

    assert selection.selected_path == target.layout_metadata_path
    assert selection.selection_required is False
    assert selection.candidates[0].details["label_match_count"] == 4


def test_multiple_candidates_do_not_fail_when_best_score_is_clear(tmp_path: Path):
    template_dir = tmp_path / "dxf_templates"
    template_dir.mkdir()
    target = _write_template(template_dir / "target_ALL_STORIES_floorload_template.dxf", ["1F", "2F", "3F", "4F"])
    _write_template(template_dir / "other_ALL_STORIES_floorload_template.dxf", ["B3", "B2", "B1"])
    user_dxf = _write_user_hatch_dxf(tmp_path / "arbitrary_saved_name.dxf", target, "4F")

    metadata_path = find_layout_metadata_path(user_dxf, project_dxf_templates_dir=template_dir)
    regions = read_load_regions(user_dxf, project_dxf_templates_dir=template_dir)

    assert metadata_path == target.layout_metadata_path
    assert len(regions) == 1
    assert regions[0].region.story_name == "4F"


def test_ambiguous_metadata_candidates_return_selection_required(tmp_path: Path):
    template_dir = tmp_path / "dxf_templates"
    template_dir.mkdir()
    target = _write_template(template_dir / "target_ALL_STORIES_floorload_template.dxf", ["1F", "2F", "3F"])
    duplicate = template_dir / "target_copy_ALL_STORIES_floorload_template.layout_metadata.json"
    shutil.copyfile(target.layout_metadata_path, duplicate)
    user_dxf = _write_user_hatch_dxf(tmp_path / "renamed_anything.dxf", target, "2F")

    selection = select_layout_metadata(dxf_path=user_dxf, project_dxf_templates_dir=template_dir)

    assert selection.selected_path is None
    assert selection.selection_required is True
    assert len(selection.candidates) >= 2
    assert selection.candidates[0].score == pytest.approx(selection.candidates[1].score)


def _write_template(path: Path, story_names: list[str]):
    stories = [Story(name, float(index) * 3.0) for index, name in enumerate(story_names)]
    nodes: list[Node] = []
    elements: list[Element] = []
    for index, story in enumerate(stories):
        base = index * 10
        nodes.extend(
            [
                Node(base + 1, 0.0, 0.0, story.elevation),
                Node(base + 2, 10.0, 0.0, story.elevation),
                Node(base + 3, 10.0, 10.0, story.elevation),
                Node(base + 4, 0.0, 10.0, story.elevation),
            ]
        )
        elements.append(Element(index + 1, "SLAB", node_ids=(base + 1, base + 2, base + 3, base + 4)))
    return write_all_story_centerline_dxf(
        output_path=path,
        stories=stories,
        nodes=nodes,
        elements=elements,
        load_layers=[LoadLayerSpec("Office", 1.2, 3.4)],
    )


def _write_user_hatch_dxf(path: Path, template_result, story_name: str) -> Path:
    layout = next(item for item in read_layout_metadata(template_result.layout_metadata_path) if item.story_name == story_name)
    doc = ezdxf.readfile(template_result.dxf_path)
    hatch = doc.modelspace().add_hatch(dxfattribs={"layer": "LOAD_001_Office_DL_1.2_LL_3.4"})
    hatch.paths.add_polyline_path([layout.transform.apply(x, y) for x, y in [(1, 1), (3, 1), (3, 2), (1, 2)]], is_closed=True)
    doc.saveas(path)
    return path
