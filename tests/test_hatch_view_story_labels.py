from types import SimpleNamespace

from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.dxf_story_layout import Affine2D, BBox2D, StoryLayout
from app.core.load_parser import LoadLayerInfo
from app.core.typical_floor_detector import TypicalFloorGroup
from app.main import FloorLoadAutoApp


def test_all_story_hatch_view_adds_story_labels_and_typical_prefix():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_display_mode_var = SimpleNamespace(get=lambda: "ALL")
    app.generated_dxf_mode = "ALL_STORIES"
    app.generated_dxf_story_names = ("1F", "2F")
    app.stories = []
    app.typical_floor_groups = (
        TypicalFloorGroup(
            group_id="G1",
            story_names=("1F", "2F"),
            typical_story_name="2F",
            typical_score=1.0,
            transition_floor_names=(),
            reason="test",
        ),
    )

    first = _load_region("A", "1F", 0.0)
    second = _load_region("B", "2F", 30.0)
    labels = app._hatch_view_story_label_items(
        [
            ("1F|A", first, first.region.vertices),
            ("2F|B", second, second.region.vertices),
        ],
        [],
        [],
    )

    by_story = {item["story_name"]: item for item in labels}
    assert by_story["1F"]["text"] == "1F"
    assert by_story["2F"]["text"] == "typ. 2F"
    assert by_story["1F"]["position"][0] < 0.0
    assert by_story["2F"]["bbox"][2] == by_story["2F"]["position"][0]


def test_all_story_labels_use_layout_metadata_without_regions_and_right_anchor():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_display_mode_var = SimpleNamespace(get=lambda: "ALL")
    app.generated_dxf_story_names = ("1F", "2F")
    app.generated_dxf_layout_metadata = (_layout("1F", 0.0), _layout("2F", 40.0))
    app.stories = []
    app.typical_floor_groups = ()

    labels = app._hatch_view_story_label_items([], [], [])
    by_story = {item["story_name"]: item for item in labels}
    canvas = _LabelCanvas()
    app._draw_hatch_story_labels(canvas, labels, lambda x, y: (x, y))

    assert tuple(by_story) == ("1F", "2F")
    assert by_story["1F"]["bbox"][2] <= by_story["1F"]["story_bbox"][0]
    assert not app._bboxes_intersect(by_story["1F"]["bbox"], by_story["1F"]["story_bbox"])
    assert canvas.text_calls
    assert all(call["kwargs"]["anchor"] == "e" for call in canvas.text_calls)
    fit_bbox = None
    for item in labels:
        fit_bbox = app._diagnostic_merge_bbox(fit_bbox, item["bbox"])
    assert fit_bbox[2] >= max(item["bbox"][2] for item in labels)


def test_all_story_labels_use_common_max_height_for_mixed_story_bboxes():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_display_mode_var = SimpleNamespace(get=lambda: "ALL")
    app.generated_dxf_story_names = ("1F", "2F", "3F")
    app.generated_dxf_layout_metadata = (
        _layout("1F", 0.0, height=8.0),
        _layout("2F", 40.0, height=40.0),
        _layout("3F", 90.0, height=14.0),
    )
    app.stories = []
    app.typical_floor_groups = (
        TypicalFloorGroup(
            group_id="G1",
            story_names=("1F", "2F", "3F"),
            typical_story_name="2F",
            typical_score=1.0,
            transition_floor_names=(),
            reason="test",
        ),
    )

    labels = app._hatch_view_story_label_items([], [], [])
    by_story = {item["story_name"]: item for item in labels}
    heights = {round(float(item["height"]), 6) for item in labels}
    expected = max(app._hatch_story_label_candidate_height(item["story_bbox"]) for item in labels)
    canvas = _LabelCanvas()
    app._draw_hatch_story_labels(canvas, labels, lambda x, y: (x, y))
    font_sizes = {call["kwargs"]["font"][1] for call in canvas.text_calls}

    assert len(heights) == 1
    assert next(iter(heights)) == round(expected, 6)
    assert len(font_sizes) == 1
    assert by_story["2F"]["text"] == "typ. 2F"
    assert by_story["2F"]["height"] == by_story["1F"]["height"]


class _LabelCanvas:
    def __init__(self):
        self.text_calls = []

    def create_text(self, *args, **kwargs):
        self.text_calls.append({"args": args, "kwargs": kwargs})


def _layout(story_name: str, offset: float, *, width: float = 10.0, height: float = 10.0) -> StoryLayout:
    return StoryLayout(
        story_name=story_name,
        story_index=0,
        elevation=0.0,
        source_bbox=BBox2D(0.0, 0.0, width, height),
        placed_bbox=BBox2D(offset, 0.0, offset + width, height),
        offset_x=offset,
        offset_y=0.0,
        scale=1.0,
        rotation_deg=0.0,
        insertion_x=offset,
        insertion_y=0.0,
        transform=Affine2D(e=offset),
        inverse_transform=Affine2D(e=-offset),
        label_x=offset,
        label_y=0.0,
        text_height=1.0,
    )


def _load_region(source_id: str, story_name: str, offset: float):
    vertices = [(offset, 0.0), (offset + 10.0, 0.0), (offset + 10.0, 10.0), (offset, 10.0)]
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle=source_id,
        vertices=vertices,
        polygon=Polygon(vertices),
        area=100.0,
        bbox=(offset, 0.0, offset + 10.0, 10.0),
        story_name=story_name,
        source_id=source_id,
    )
    return LoadRegion(
        region=hatch,
        load=LoadLayerInfo(layer=hatch.layer, real_name="A", dl=1.0, ll=1.0, source="test"),
        status="OK",
        warnings=[],
    )
