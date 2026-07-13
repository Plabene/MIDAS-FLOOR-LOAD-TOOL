from types import SimpleNamespace

from app.main import FloorLoadAutoApp


def test_hatch_view_right_click_selects_region_and_builds_context_menu(monkeypatch):
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_region_by_key = {"R1": object()}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.final_load_items = [{"display_name": "Office", "name": "Office", "dl": 1.0, "ll": 2.0}]
    selected = []
    rendered = []
    app._hatch_region_key_at_canvas_point = lambda _x, _y: "R1"
    app._select_dxf_tree_region = selected.append
    app._render_hatch_preview = lambda *args, **kwargs: rendered.append(kwargs)

    created = []
    monkeypatch.setattr("app.main.tk.Menu", lambda *args, **kwargs: _Menu(created, *args, **kwargs))

    result = app._on_hatch_view_context_menu(SimpleNamespace(x=10, y=20, x_root=110, y_root=120))

    root_menu = created[0]
    load_menu = created[1]
    assert result == "break"
    assert app.hatch_view_selected_region_key == "R1"
    assert selected == ["R1"]
    assert rendered == [{"focus_region_key": "R1"}]
    assert "선택영역 하중 제거" in root_menu.command_labels
    assert "해치영역 구분하기" in root_menu.command_labels
    assert root_menu.cascade_labels == ["선택영역에 하중 적용"]
    assert load_menu.command_labels == ["Office DL 1 LL 2"]
    assert root_menu.popup == (110, 120)


class _Menu:
    def __init__(self, created, *_args, **_kwargs):
        self.command_labels = []
        self.cascade_labels = []
        self.popup = None
        created.append(self)

    def add_command(self, *, label, **_kwargs):
        self.command_labels.append(label)

    def add_cascade(self, *, label, **_kwargs):
        self.cascade_labels.append(label)

    def tk_popup(self, x, y):
        self.popup = (x, y)

    def grab_release(self):
        return None
