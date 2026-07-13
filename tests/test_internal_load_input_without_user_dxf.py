from pathlib import Path
from types import SimpleNamespace

from app.core.hatch_region_editor import EditableHatchRegion, HatchEditState
from app.core.mgt_parser import Node, Story
from app.main import FloorLoadAutoApp


def test_build_pipeline_uses_internal_regions_without_user_dxf(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(
        "app.main.messagebox.showwarning",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError(f"unexpected warning: {args}")),
    )
    app = object.__new__(FloorLoadAutoApp)
    internal = EditableHatchRegion(
        region_key="INTERNAL|1F|A|LOADED|Office",
        story_name="1F",
        cell_ids=("A",),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        load_name="Office",
        load_layer="LOAD_001_Office_DL_1.2_LL_3.4",
        dl=1.2,
        ll=3.4,
        distribution="TWO_WAY",
    )
    app.hatch_edit_states_by_story = {
        "1F": HatchEditState("1F", {}, {internal.region_key: internal}, set(), set())
    }
    app.loaded_regions = []
    app.exported_mgt_path = _Var(str(tmp_path / "source.mgt"))
    app.user_dxf_path = _Var("")
    app.generated_dxf_path = _Var(str(tmp_path / "generated.dxf"))
    app.layout_metadata_path = _Var("")
    app.mapping_path = _Var("")
    app.model_path = _Var(str(tmp_path / "model.mgb"))
    app.snap_tol_var = _Var(0.01)
    app.story_tol_var = _Var(0.01)
    app.include_zero_var = _Var(True)
    app.auto_load_dm_dummy_var = _Var(False)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 10.0, 0.0, 0.0), Node(3, 10.0, 10.0, 0.0), Node(4, 0.0, 10.0, 0.0)]
    app.current_project_subdirs = {"dxf_templates": tmp_path, "mgt": tmp_path, "models": tmp_path, "reports": tmp_path}
    app._selected_dxf_story_mode = lambda: ("SINGLE", Story("1F", 0.0))
    app._mark_model_not_generated = lambda _message: None
    app._ensure_current_project_workspace = lambda: None
    app._regions_with_continuous_apply = lambda regions: regions
    worker = {}
    app.run_worker = lambda title, fn: worker.update({"title": title, "fn": fn})
    captured = {}

    def fake_pipeline(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            dummy_summary=None,
            full_mgt_path=tmp_path / "out.mgt",
            report_xlsx_path=tmp_path / "report.xlsx",
            preview_dxf_path=tmp_path / "preview.dxf",
        )

    monkeypatch.setattr("app.main.run_mgt_build_pipeline", fake_pipeline)

    app._build_pipeline(import_to_midas=False)
    result = worker["fn"](_Progress())

    assert captured["regions"] == []
    assert captured["internal_regions"] == (internal,)
    assert captured["dxf_name"] == "generated.dxf"
    assert "out.mgt" in result.message

    captured.clear()
    app.generated_dxf_path.set("")
    app._build_pipeline(import_to_midas=False)
    worker["fn"](_Progress())

    assert captured["dxf_name"] == "HATCH_VIEW_INTERNAL"


def test_validate_user_dxf_can_keep_or_clear_existing_internal_regions(monkeypatch):
    app = object.__new__(FloorLoadAutoApp)
    internal = EditableHatchRegion(
        region_key="INTERNAL|1F|A|LOADED|Office",
        story_name="1F",
        cell_ids=("A",),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        load_name="Office",
        load_layer="LOAD_001_Office_DL_1.2_LL_3.4",
        dl=1.2,
        ll=3.4,
        distribution="TWO_WAY",
    )
    app.hatch_edit_states_by_story = {"1F": HatchEditState("1F", {}, {internal.region_key: internal}, set(), set())}
    app.hatch_view_selected_edit_region_keys = {internal.region_key}
    app.user_dxf_path = _Var("user.dxf")
    app._resolve_layout_metadata_for_dxf = lambda *_args, **_kwargs: None
    app.run_worker = lambda *_args, **_kwargs: None
    app._render_hatch_preview = lambda: None
    logs = []
    app.log = logs.append

    monkeypatch.setattr("app.main.messagebox.askyesno", lambda *args, **kwargs: True)
    app.validate_user_dxf()

    assert app._loaded_internal_hatch_regions() == (internal,)
    assert any("유지" in message for message in logs)

    monkeypatch.setattr("app.main.messagebox.askyesno", lambda *args, **kwargs: False)
    app.validate_user_dxf()

    assert app.hatch_edit_states_by_story == {}
    assert app.hatch_view_selected_edit_region_keys == set()
    assert any("초기화" in message for message in logs)


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Progress:
    def update(self, *_args, **_kwargs):
        return None
