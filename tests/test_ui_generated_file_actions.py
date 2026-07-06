from pathlib import Path

from app import main as main_mod
from app.main import BuildPipelineUiResult, FloorLoadAutoApp


class _Var:
    def __init__(self, value: str = ""):
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value) -> None:
        self.value = str(value)


class _Button:
    def __init__(self):
        self.options = {
            "state": "disabled",
            "text": "",
            "background": "SystemButtonFace",
            "activebackground": "SystemButtonFace",
            "foreground": "SystemButtonText",
            "relief": "raised",
        }

    def configure(self, **kwargs) -> None:
        self.options.update(kwargs)

    def cget(self, option):
        return self.options[option]

    def state(self, states=None):
        if states is None:
            return (self.options["state"],)
        if "disabled" in states:
            self.options["state"] = "disabled"
        if "!disabled" in states:
            self.options["state"] = "normal"

    def __getitem__(self, key):
        return self.options[key]


class _Label:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs) -> None:
        self.options.update(kwargs)

    def __getitem__(self, key):
        return self.options[key]


def _app_with_action_widgets() -> FloorLoadAutoApp:
    app = object.__new__(FloorLoadAutoApp)
    app.last_generated_dxf_path = None
    app.last_generated_model_path = None
    app.generated_dxf_path = _Var()
    app.generated_model_path = _Var()
    app.target_model_path = _Var()
    app.dxf_next_action_text_var = _Var()
    app.model_next_action_text_var = _Var()
    app.open_generated_dxf_button = _Button()
    app.open_generated_model_button = _Button()
    app._dxf_open_button_defaults = app._capture_button_visual_defaults(app.open_generated_dxf_button)
    app._model_open_button_defaults = app._capture_button_visual_defaults(app.open_generated_model_button)
    app.result_label = _Label()
    return app


def test_mark_dxf_generated_success_enables_open_button(tmp_path: Path):
    app = _app_with_action_widgets()
    dxf = tmp_path / "template.dxf"

    app._mark_dxf_generated_success(dxf)

    assert app.generated_dxf_path.get() == str(dxf)
    assert app.last_generated_dxf_path == dxf
    assert app.open_generated_dxf_button["state"] == "normal"
    assert app.open_generated_dxf_button["text"].startswith("생성 DXF 파일 열기")
    assert app.open_generated_dxf_button["background"] == main_mod.DXF_NEXT_ACTION_BG
    assert "다음 단계" in app.dxf_next_action_text_var.get()


def test_mark_dxf_generated_failed_disables_open_button(tmp_path: Path):
    app = _app_with_action_widgets()
    app._mark_dxf_generated_success(tmp_path / "old.dxf")

    app._mark_dxf_generated_failed("write error")

    assert app.generated_dxf_path.get() == ""
    assert app.last_generated_dxf_path is None
    assert app.open_generated_dxf_button["state"] == "disabled"
    assert app.open_generated_dxf_button["text"] == "생성 DXF 파일 열기"
    assert "DXF 생성 실패" in app.dxf_next_action_text_var.get()


def test_mark_model_generated_success_enables_open_button(tmp_path: Path):
    app = _app_with_action_widgets()
    saved = tmp_path / "model_floorload_added_2.mgbx"

    app._mark_model_generated_success(saved)

    assert app.generated_model_path.get() == str(saved)
    assert app.target_model_path.get() == str(saved)
    assert app.last_generated_model_path == saved
    assert app.open_generated_model_button["state"] == "normal"
    assert app.open_generated_model_button["text"].startswith("생성 모델링 파일 열기")
    assert app.open_generated_model_button["background"] == main_mod.MODEL_NEXT_ACTION_BG


def test_mark_model_generated_failed_disables_open_button(tmp_path: Path):
    app = _app_with_action_widgets()
    app._mark_model_generated_success(tmp_path / "old.mgbx")

    app._mark_model_generated_failed("save failed")

    assert app.generated_model_path.get() == ""
    assert app.last_generated_model_path is None
    assert app.open_generated_model_button["state"] == "disabled"
    assert "모델링 파일 생성 실패" in app.model_next_action_text_var.get()


def test_open_file_with_default_app_missing_file_shows_error(tmp_path: Path, monkeypatch):
    app = _app_with_action_widgets()
    shown = []
    monkeypatch.setattr(main_mod.messagebox, "showerror", lambda title, message: shown.append((title, message)))
    app._launch_file_with_default_app = lambda path: shown.append(("launched", str(path)))

    opened = app._open_file_with_default_app(tmp_path / "missing.dxf")

    assert opened is False
    assert shown and shown[0][0] == "파일 없음"
    assert all(item[0] != "launched" for item in shown)


def test_open_file_with_default_app_existing_file_launches(tmp_path: Path):
    app = _app_with_action_widgets()
    path = tmp_path / "model.mgbx"
    path.write_text("dummy", encoding="utf-8")
    launched = []
    app._launch_file_with_default_app = lambda value: launched.append(value)

    opened = app._open_file_with_default_app(path)

    assert opened is True
    assert launched == [path]


def test_saved_model_path_reflected_in_generated_model_path(tmp_path: Path):
    app = _app_with_action_widgets()
    saved = tmp_path / "model_floorload_added_3.mgbx"

    app._handle_mgt_build_result(BuildPipelineUiResult("ok", generated_model_path=saved))

    assert app.generated_model_path.get() == str(saved)
    assert app.target_model_path.get() == str(saved)
    assert app.open_generated_model_button["state"] == "normal"
    assert app.result_label["text"] == "결과 파일: ok"
