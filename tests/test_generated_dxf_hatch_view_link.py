from pathlib import Path
from types import SimpleNamespace

from app.core.dxf_story_layout import Affine2D, BBox2D, StoryLayout, write_layout_metadata
from app.main import FloorLoadAutoApp


def test_generated_dxf_state_initializes_hatch_view_story_controls(tmp_path: Path):
    app = object.__new__(FloorLoadAutoApp)
    dxf = tmp_path / "generated.dxf"
    metadata = tmp_path / "generated.layout_metadata.json"
    write_layout_metadata(metadata, [_layout("1F", 0, 0.0), _layout("2F", 1, 100.0)])
    app.generated_dxf_path = _Var()
    app.dxf_next_action_text_var = _Var()
    app.hatch_view_display_mode_var = _Var()
    app.hatch_view_selected_story_var = _Var()
    app.dxf_validation_status_var = _Var()
    app.open_generated_dxf_button = _Button()
    app._dxf_open_button_defaults = None
    app.open_hatch_work_tab_button = _Button()
    app.hatch_view_story_combo = _Combo()
    app.stories = []
    app.nodes = []
    app.elements = []
    app.hatch_edit_states_by_story = {}
    app.log = lambda _message: None

    app._mark_dxf_generated_success(dxf)
    app._register_generated_dxf_result(SimpleNamespace(layout_metadata_path=metadata, story_count=2))

    assert app.generated_dxf_path.get() == str(dxf)
    assert app.generated_dxf_metadata_path == metadata
    assert app.generated_dxf_mode == "ALL_STORIES"
    assert app.generated_dxf_story_names == ("1F", "2F")
    assert app.hatch_view_display_mode_var.get() == "ALL"
    assert app.hatch_view_selected_story_var.get() == "1F"
    assert app.hatch_view_story_combo.values == ["1F", "2F"]
    assert app.open_hatch_work_tab_button.states[-1] == ["!disabled"]
    assert app.open_hatch_work_tab_button.configs[-1]["text"].startswith("4번 탭")
    assert "생성 DXF 기반 내부 입력 가능" in app.dxf_validation_status_var.get()


def test_generated_dxf_completion_message_prioritizes_internal_direct_input(monkeypatch, tmp_path: Path):
    app = object.__new__(FloorLoadAutoApp)
    dxf = tmp_path / "generated.dxf"
    mapping = tmp_path / "generated.layer_mapping.json"
    app.generated_dxf_path = _Var()
    app.dxf_next_action_text_var = _Var()
    app.hatch_view_display_mode_var = _Var()
    app.hatch_view_selected_story_var = _Var()
    app.dxf_validation_status_var = _Var()
    app.open_generated_dxf_button = _Button()
    app._dxf_open_button_defaults = None
    app.open_hatch_work_tab_button = _Button()
    app.hatch_view_story_combo = _Combo()
    app.mapping_path = _Var()
    app.layout_metadata_path = _Var()
    app.stories = []
    app.nodes = []
    app.elements = []
    app.hatch_edit_states_by_story = {}
    app.log = lambda _message: None
    messages = []
    monkeypatch.setattr("app.main.messagebox.showinfo", lambda *args, **kwargs: messages.append((args, kwargs)))

    app._handle_dxf_template_result(
        SimpleNamespace(dxf_path=dxf, mapping_json_path=mapping, layout_metadata_path=None, story_count=1, selected_story_name="3F")
    )

    assert messages
    body = messages[0][0][1]
    assert "4번" in body
    assert "직접 입력" in body
    assert body.find("직접 입력") < body.find("CAD")
    assert app.open_hatch_work_tab_button.configs[-1]["text"].startswith("4번 탭")


def test_generated_single_story_falls_back_to_selected_story_when_metadata_is_empty():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_display_mode_var = _Var()
    app.hatch_view_selected_story_var = _Var()
    app.dxf_validation_status_var = _Var()
    app.open_hatch_work_tab_button = _Button()
    app.hatch_view_story_combo = _Combo()
    app.stories = []
    app.nodes = []
    app.elements = []
    app.hatch_edit_states_by_story = {}
    app.log = lambda _message: None

    app._register_generated_dxf_result(SimpleNamespace(layout_metadata_path=None, story_count=1, selected_story_name="5F"))

    assert app.generated_dxf_story_names == ("5F",)
    assert app.hatch_view_display_mode_var.get() == "STORY"
    assert app.hatch_view_selected_story_var.get() == "5F"


def _layout(story_name: str, index: int, dx: float) -> StoryLayout:
    return StoryLayout(
        story_name=story_name,
        story_index=index,
        elevation=float(index) * 3.0,
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


class _Button:
    def __init__(self):
        self.states = []
        self.configs = []

    def state(self, values):
        self.states.append(list(values))

    def configure(self, **kwargs):
        self.configs.append(kwargs)


class _Combo:
    def __init__(self):
        self.values = []

    def configure(self, **kwargs):
        self.values = list(kwargs.get("values", self.values))
