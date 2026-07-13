from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.dxf_story_layout import Affine2D, BBox2D, StoryLayout
from app.core.load_parser import LoadLayerInfo
from app.main import FloorLoadAutoApp


SAME_SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
SQUARE_AT_100 = [(100.0, 0.0), (110.0, 0.0), (110.0, 10.0), (100.0, 10.0)]
SQUARE_AT_1000 = [(1000.0, 0.0), (1010.0, 0.0), (1010.0, 10.0), (1000.0, 10.0)]


def test_all_story_context_inferred_from_loaded_regions_with_placed_vertices():
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = None
    app.generated_dxf_layout_metadata = ()
    app.generated_dxf_story_names = ()
    app.hatch_view_display_mode_var = _Var("ALL")
    app.loaded_regions = [
        _load_region("1F", SAME_SQUARE, SQUARE_AT_100),
        _load_region("2F", SAME_SQUARE, SQUARE_AT_1000),
    ]

    assert app._hatch_view_is_all_story_display() is True
    assert app._region_display_vertices(app.loaded_regions[0], {}) == SQUARE_AT_100
    assert app._region_display_vertices(app.loaded_regions[1], {}) == SQUARE_AT_1000


def test_all_story_context_inferred_from_layout_metadata_without_generated_mode():
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = None
    app.generated_dxf_layout_metadata = (_layout("1F", 100.0), _layout("2F", 1000.0))
    app.generated_dxf_story_names = ()
    app.hatch_view_display_mode_var = _Var("ALL")
    app.loaded_regions = []

    assert app._hatch_view_is_all_story_display() is True


def test_single_story_context_is_not_all_story():
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = None
    app.generated_dxf_layout_metadata = ()
    app.generated_dxf_story_names = ()
    app.hatch_view_display_mode_var = _Var("ALL")
    app.loaded_regions = [_load_region("5F", SAME_SQUARE, SQUARE_AT_100)]

    assert app._hatch_view_has_all_story_context() is False
    assert app._hatch_view_is_all_story_display() is False
    assert app._region_display_vertices(app.loaded_regions[0], {}) == SAME_SQUARE


def test_region_tree_registration_sets_all_story_context_from_loaded_regions():
    app = object.__new__(FloorLoadAutoApp)
    app.generated_dxf_mode = None
    app.generated_dxf_layout_metadata = ()
    app.generated_dxf_story_names = ()
    app.hatch_view_display_mode_var = _Var("STORY")
    app.hatch_view_selected_story_var = _Var("")
    app.hatch_view_story_combo = _Combo()
    app.loaded_regions = [
        _load_region("1F", SAME_SQUARE, SQUARE_AT_100),
        _load_region("2F", SAME_SQUARE, SQUARE_AT_1000),
    ]

    app._register_hatch_view_layout_context_from_regions(app.loaded_regions)

    assert app.generated_dxf_mode == "ALL_STORIES"
    assert app.generated_dxf_story_names == ("1F", "2F")
    assert app.hatch_view_display_mode_var.get() == "ALL"
    assert app.hatch_view_selected_story_var.get() == "1F"
    assert app.hatch_view_story_combo.values == ("1F", "2F")


def _load_region(story_name: str, model_vertices, placed_vertices):
    hatch = HatchRegion(
        source_type="HATCH",
        layer="LOAD_001_A_DL_1_LL_1",
        handle=story_name,
        vertices=list(model_vertices),
        polygon=Polygon(model_vertices),
        area=100.0,
        bbox=(0.0, 0.0, 10.0, 10.0),
        story_name=story_name,
        source_id=story_name,
        placed_vertices=list(placed_vertices),
        placed_bbox=tuple(Polygon(placed_vertices).bounds),
        model_bbox=tuple(Polygon(model_vertices).bounds),
        transform_applied=True,
    )
    load = LoadLayerInfo(layer=hatch.layer, real_name="A", dl=1.0, ll=1.0, source="test")
    return LoadRegion(region=hatch, load=load, status="OK", warnings=[])


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
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Combo:
    def __init__(self):
        self.values = ()

    def configure(self, **kwargs):
        self.values = tuple(kwargs.get("values", ()))
