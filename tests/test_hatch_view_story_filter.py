from app.core.dxf_story_layout import Affine2D, BBox2D, StoryLayout
from app.core.hatch_region_editor import EditableHatchRegion, HatchEditState
from app.main import FloorLoadAutoApp


def test_hatch_view_story_filter_switches_between_placed_and_model_coordinates():
    app = object.__new__(FloorLoadAutoApp)
    first = _region("1F", "A")
    second = _region("2F", "B")
    app.hatch_edit_states_by_story = {
        "1F": HatchEditState("1F", {}, {first.region_key: first}, set(), set()),
        "2F": HatchEditState("2F", {}, {second.region_key: second}, set(), set()),
    }
    app.generated_dxf_story_names = ("1F", "2F")
    app.generated_dxf_mode = "ALL_STORIES"
    app.generated_dxf_layout_metadata = (_layout("1F", 100.0), _layout("2F", 200.0))
    app.hatch_view_display_mode_var = _Var("ALL")
    app.hatch_view_selected_story_var = _Var("2F")
    app.stories = []
    app.nodes = []
    app.elements = []

    all_display = app._hatch_view_display_edit_regions()

    assert len(all_display) == 2
    assert all_display[0][2][0] == (100.0, 0.0)
    assert all_display[1][2][0] == (200.0, 0.0)

    app.hatch_view_display_mode_var.set("STORY")
    story_display = app._hatch_view_display_edit_regions()

    assert [region.story_name for _key, region, _vertices in story_display] == ["2F"]
    assert story_display[0][2][0] == (0.0, 0.0)


def _region(story_name: str, cell_id: str) -> EditableHatchRegion:
    return EditableHatchRegion(
        region_key=f"INTERNAL|{story_name}|{cell_id}|UNLOADED",
        story_name=story_name,
        cell_ids=(cell_id,),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        load_name=None,
        load_layer=None,
        dl=None,
        ll=None,
        distribution="TWO_WAY",
    )


def _layout(story_name: str, dx: float) -> StoryLayout:
    return StoryLayout(
        story_name=story_name,
        story_index=None,
        elevation=None,
        source_bbox=BBox2D(0.0, 0.0, 10.0, 10.0),
        placed_bbox=BBox2D(dx, 0.0, dx + 10.0, 10.0),
        offset_x=dx,
        offset_y=0.0,
        scale=1.0,
        rotation_deg=0.0,
        insertion_x=dx,
        insertion_y=0.0,
        transform=Affine2D(e=dx),
        inverse_transform=Affine2D(e=-dx),
        label_x=dx,
        label_y=0.0,
        text_height=1.0,
    )


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
