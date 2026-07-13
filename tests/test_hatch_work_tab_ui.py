import inspect

from app.main import FloorLoadAutoApp


def _method_source(name: str) -> str:
    return inspect.getsource(getattr(FloorLoadAutoApp, name))


def test_hatch_work_tab_is_registered_in_main_notebook():
    source = _method_source("_build_ui")

    assert "self.tab_hatch_work" in source
    assert "기준층 하중/연속층 적용" in source
    assert "_build_hatch_work_tab" in source


def test_dxf_tab_no_longer_builds_hatch_or_typical_workbench():
    source = _method_source("_build_dxf_tab")

    assert "기준층 자동 분석" not in source
    assert "_build_typical_floor_workbench" not in source
    assert "_build_hatch_view_panel" not in source
    assert "hatch_preview_canvas" not in source
    assert "open_hatch_work_tab_button" in source


def test_hatch_work_tab_builds_hatch_view_workflow():
    source = _method_source("_build_hatch_work_tab")
    hatch_panel_source = _method_source("_build_hatch_view_panel")
    control_panel_source = _method_source("_build_hatch_control_panel")
    typical_source = _method_source("_build_typical_floor_workbench")
    direct_source = _method_source("_build_hatch_direct_load_tab")

    assert "_build_hatch_view_panel" in source
    assert "_build_hatch_control_panel" in source
    assert "main_area.columnconfigure(0, weight=2, minsize=900)" in source
    assert "main_area.columnconfigure(1, weight=1, minsize=420)" in source
    assert "hatch_left.grid(row=0, column=0" in source
    assert "self.hatch_preview_canvas = tk.Canvas" in hatch_panel_source
    assert "_build_typical_floor_workbench" in control_panel_source
    assert "직접 하중 입력" in typical_source
    assert "연속층 적용" in typical_source
    assert "검증결과/수정안내" in typical_source
    assert "ttk.Notebook" not in typical_source
    assert "workbench.add" not in typical_source
    assert "workbench.rowconfigure(0, weight=4)" in typical_source
    assert "workbench.rowconfigure(1, weight=4)" in typical_source
    assert "workbench.rowconfigure(2, weight=2)" in typical_source
    assert "command=self.apply_selected_hatch_load" in direct_source
    assert "command=self.remove_selected_hatch_load" in direct_source
    assert "command=self.split_selected_hatch_region" in direct_source
    assert "적용 가능층 자동 선택" in typical_source
    assert "command=self.verify_continuous_apply_range" not in typical_source
    assert "command=self.select_recommended_continuous_stories" not in typical_source
    assert "command=self.confirm_continuous_apply" not in typical_source


def test_model_tab_hides_manual_floorload_diagnostic_button():
    source = _method_source("_build_model_tab")

    assert "모델링 FLOORLOAD 입력 가능성 분석" not in source


def test_hatch_work_tab_navigation_and_redraw_hooks_exist():
    assert hasattr(FloorLoadAutoApp, "open_hatch_work_tab")
    assert hasattr(FloorLoadAutoApp, "_on_main_tab_changed")

    build_ui_source = _method_source("_build_ui")
    assert "<<NotebookTabChanged>>" in build_ui_source
