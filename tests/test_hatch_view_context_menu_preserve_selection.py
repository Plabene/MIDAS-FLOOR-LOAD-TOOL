from types import SimpleNamespace

from app.main import FloorLoadAutoApp


def test_right_click_on_selected_dxf_region_preserves_multi_selection(monkeypatch):
    app = _app_for_context_menu()
    app.hatch_view_region_by_key = {"A": object(), "B": object(), "C": object()}
    app.hatch_view_selected_region_keys = {"A", "B"}
    app.hatch_view_selected_region_key = "A"
    app._hatch_region_key_at_canvas_point = lambda _x, _y: "A"
    rendered = []
    app._render_hatch_preview = lambda *args, **kwargs: rendered.append(kwargs)
    created = _patch_menu(monkeypatch)

    app._on_hatch_view_context_menu(SimpleNamespace(x=1, y=2, x_root=11, y_root=12))

    assert app.hatch_view_selected_region_keys == {"A", "B"}
    assert app.hatch_view_selected_region_key == "A"
    assert rendered == []
    assert created[0].states["선택영역 하중 제거"] == "normal"


def test_right_click_on_selected_edit_region_preserves_multi_selection(monkeypatch):
    app = _app_for_context_menu()
    app.hatch_view_edit_region_by_key = {"A": object(), "B": object(), "C": object()}
    app.hatch_view_selected_edit_region_keys = {"A", "B"}
    app._hatch_region_key_at_canvas_point = lambda _x, _y: "A"
    created = _patch_menu(monkeypatch)

    app._on_hatch_view_context_menu(SimpleNamespace(x=1, y=2, x_root=11, y_root=12))

    assert app.hatch_view_selected_edit_region_keys == {"A", "B"}
    assert created[0].states["해치영역 구분하기"] == "normal"


def test_right_click_on_unselected_region_replaces_selection(monkeypatch):
    app = _app_for_context_menu()
    app.hatch_view_region_by_key = {"A": object(), "B": object(), "C": object()}
    app.hatch_view_selected_region_keys = {"A", "B"}
    app.hatch_view_selected_region_key = "A"
    app._hatch_region_key_at_canvas_point = lambda _x, _y: "C"
    rendered = []
    app._render_hatch_preview = lambda *args, **kwargs: rendered.append(kwargs)
    _patch_menu(monkeypatch)

    app._on_hatch_view_context_menu(SimpleNamespace(x=1, y=2, x_root=11, y_root=12))

    assert app.hatch_view_selected_region_keys == {"C"}
    assert app.hatch_view_selected_region_key == "C"
    assert rendered == [{"focus_region_key": "C"}]


def test_right_click_empty_space_preserves_existing_selection(monkeypatch):
    app = _app_for_context_menu()
    app.hatch_view_region_by_key = {"A": object(), "B": object()}
    app.hatch_view_selected_region_keys = {"A", "B"}
    app.hatch_view_selected_region_key = "A"
    app._hatch_region_key_at_canvas_point = lambda _x, _y: None
    created = _patch_menu(monkeypatch)

    app._on_hatch_view_context_menu(SimpleNamespace(x=1, y=2, x_root=11, y_root=12))

    assert app.hatch_view_selected_region_keys == {"A", "B"}
    assert created[0].states["선택영역 하중 제거"] == "normal"


def _app_for_context_menu():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_view_region_by_key = {}
    app.hatch_view_edit_region_by_key = {}
    app.hatch_view_selected_region_key = ""
    app.hatch_view_selected_region_keys = set()
    app.hatch_view_selected_edit_region_keys = set()
    app.hatch_edit_states_by_story = {}
    app.final_load_items = []
    app._sync_continuous_base_story_from_selection = lambda: ""
    app._refresh_selected_hatch_continuous_info = lambda: None
    app._select_dxf_tree_region = lambda _key: None
    app._load_selected_hatch_as_base_story = lambda _key: None
    app._render_hatch_preview = lambda *args, **kwargs: None
    return app


def _patch_menu(monkeypatch):
    created = []
    monkeypatch.setattr("app.main.tk.Menu", lambda *args, **kwargs: _Menu(created, *args, **kwargs))
    return created


class _Menu:
    def __init__(self, created, *_args, **_kwargs):
        self.states = {}
        self.cascade_states = {}
        created.append(self)

    def add_command(self, *, label, state="normal", **_kwargs):
        self.states[label] = state

    def add_cascade(self, *, label, state="normal", **_kwargs):
        self.cascade_states[label] = state

    def tk_popup(self, _x, _y):
        return None

    def grab_release(self):
        return None
