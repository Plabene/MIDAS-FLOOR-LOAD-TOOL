import inspect

from app.main import FloorLoadAutoApp


def test_typical_analysis_tab_is_hidden_from_hatch_workbench():
    source = inspect.getsource(FloorLoadAutoApp._build_typical_floor_workbench)

    assert "workbench.add(analysis_tab" not in source
    assert 'text="기준층/구간 분석"' not in source
    assert "analysis_tab = ttk.Frame(parent)" in source


def test_hidden_typical_analysis_widgets_remain_for_internal_updates():
    source = inspect.getsource(FloorLoadAutoApp._build_typical_floor_workbench)

    assert "self.typical_group_tree" in source
    assert "self.typical_story_tree" in source
    assert "self.typical_analysis_summary_var" in source


def test_manual_typical_analysis_entry_is_marked_internal_compatibility():
    source = inspect.getsource(FloorLoadAutoApp.run_typical_floor_analysis)

    assert "internal/test compatibility" in source
    assert "runs this analysis automatically" in source
