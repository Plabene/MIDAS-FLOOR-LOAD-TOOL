from types import SimpleNamespace

from app.core.dxf_story_layout import Affine2D, BBox2D, StoryLayout
from app.main import FloorLoadAutoApp


def test_story_labels_are_left_of_story_bbox_and_larger():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_display_mode_var = SimpleNamespace(get=lambda: "ALL")
    app.generated_dxf_mode = "ALL_STORIES"
    app.generated_dxf_story_names = ("1F",)
    app.generated_dxf_layout_metadata = (_layout("1F"),)
    app.stories = []
    app.typical_floor_groups = ()

    labels = app._hatch_view_story_label_items([], [], [])

    label = labels[0]
    story_bbox = label["story_bbox"]
    assert label["position"][0] < story_bbox[0]
    assert label["bbox"][2] <= story_bbox[0]
    assert label["position"][0] < story_bbox[2]
    assert not app._bboxes_intersect(label["bbox"], story_bbox)
    assert label["height"] >= 1.5


def test_story_label_font_clamp_is_larger_than_previous_minimum():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _LabelCanvas()

    app._draw_hatch_story_labels(
        canvas,
        [{"story_name": "1F", "text": "1F", "position": (-2.0, 5.0), "height": 1.0}],
        lambda x, y: (x, y),
    )

    assert canvas.text_calls[0]["kwargs"]["anchor"] == "e"
    assert canvas.text_calls[0]["kwargs"]["font"][1] == 12


def _layout(story_name: str) -> StoryLayout:
    return StoryLayout(
        story_name=story_name,
        story_index=0,
        elevation=0.0,
        source_bbox=BBox2D(0.0, 0.0, 10.0, 10.0),
        placed_bbox=BBox2D(0.0, 0.0, 10.0, 10.0),
        offset_x=0.0,
        offset_y=0.0,
        scale=1.0,
        rotation_deg=0.0,
        insertion_x=0.0,
        insertion_y=0.0,
        transform=Affine2D(),
        inverse_transform=Affine2D(),
        label_x=0.0,
        label_y=0.0,
        text_height=1.0,
    )


class _LabelCanvas:
    def __init__(self):
        self.text_calls = []

    def create_text(self, *args, **kwargs):
        self.text_calls.append({"args": args, "kwargs": kwargs})
