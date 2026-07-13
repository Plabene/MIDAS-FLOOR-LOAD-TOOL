from app.core.mgt_parser import FloorLoadTypeSpec
from app.main import FloorLoadAutoApp


class Var:
    def __init__(self, value=False):
        self.value = bool(value)

    def get(self):
        return self.value

    def set(self, value):
        self.value = bool(value)


def _app(monkeypatch):
    monkeypatch.setattr("app.main.tk.BooleanVar", Var)
    app = object.__new__(FloorLoadAutoApp)
    app.model_load_items = []
    app.pdf_load_items = []
    app.model_load_vars = {}
    app.pdf_load_vars = {}
    app.model_load_all_var = Var(False)
    app.pdf_load_all_var = Var(False)
    app.selected_pdf_paths = []
    app.load_selection_user_dirty = False
    app.load_selection_default_mode = ""
    app.load_selection_source_signature = ""
    app._sync_final_load_list = lambda: None
    app._refresh_model_load_checklist = lambda: None
    app._refresh_pdf_load_checklist = lambda: None
    app._refresh_pdf_load_lines_listbox = lambda: None
    return app


def test_model_only_auto_select_pdf_transition_clears_and_manual_refresh_is_preserved(monkeypatch):
    app = _app(monkeypatch)
    app._update_model_load_items([FloorLoadTypeSpec("Office", 1.2, 3.0), FloorLoadTypeSpec("Lobby", 1.5, 5.0)])
    assert all(var.get() for var in app.model_load_vars.values())
    assert app.load_selection_default_mode == "MODEL_ONLY_AUTO_SELECTED"

    app._update_pdf_load_items_from_lines(["PDF Office, DL:1.3 LL:3.1"])
    assert not any(var.get() for var in app.model_load_vars.values())
    assert not any(var.get() for var in app.pdf_load_vars.values())
    assert app.load_selection_default_mode == "PDF_PRESENT_AUTO_CLEARED"

    pdf_var = next(iter(app.pdf_load_vars.values()))
    pdf_var.set(True)
    app._mark_load_selection_user_dirty()
    app._update_pdf_load_items_from_lines(["PDF Office, DL:1.3 LL:3.1"])
    assert next(iter(app.pdf_load_vars.values())).get() is True
    assert app.load_selection_default_mode == "USER_MANUAL"


def test_pdf_deletion_restores_model_only_when_not_manual(monkeypatch):
    app = _app(monkeypatch)
    app._update_model_load_items([FloorLoadTypeSpec("Office", 1.2, 3.0)])
    app._update_pdf_load_items_from_lines(["PDF Office, DL:1.3 LL:3.1"])
    app._update_pdf_load_items_from_lines([])
    assert next(iter(app.model_load_vars.values())).get() is True

    app._update_pdf_load_items_from_lines(["PDF Office, DL:1.3 LL:3.1"])
    app._mark_load_selection_user_dirty()
    next(iter(app.model_load_vars.values())).set(False)
    app._update_pdf_load_items_from_lines([])
    assert next(iter(app.model_load_vars.values())).get() is False
