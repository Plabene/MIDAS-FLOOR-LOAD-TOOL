from app.main import FloorLoadAutoApp


def test_one_way_mode_button_defaults_off_and_toggles_styles():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_one_way_mode_var = _Var(False)
    app.hatch_one_way_button = _Button()

    app._refresh_hatch_one_way_button_style()
    assert app._hatch_one_way_mode_enabled() is False
    assert app.hatch_one_way_button.options["text"] == "ONE-WAY OFF"
    assert app.hatch_one_way_button.options["bg"] == "#fee2e2"

    app._toggle_hatch_one_way_mode()
    assert app._hatch_one_way_mode_enabled() is True
    assert app.hatch_one_way_button.options["text"] == "ONE-WAY ON"
    assert app.hatch_one_way_button.options["bg"] == "#fca5a5"

    app._toggle_hatch_one_way_mode()
    assert app._hatch_one_way_mode_enabled() is False
    assert app.hatch_one_way_button.options["text"] == "ONE-WAY OFF"


def test_hatch_load_item_for_current_mode_does_not_mutate_original_item():
    app = object.__new__(FloorLoadAutoApp)
    app.hatch_one_way_mode_var = _Var(True)
    item = {"name": "Office", "distribution": "TWO_WAY", "dl": 1.0, "ll": 2.0}

    one_way = app._hatch_load_item_for_current_mode(item)
    assert one_way["distribution"] == "ONE_WAY"
    assert item["distribution"] == "TWO_WAY"

    app.hatch_one_way_mode_var.set(False)
    off = app._hatch_load_item_for_current_mode(item)
    assert off["distribution"] == "TWO_WAY"


class _Var:
    def __init__(self, value=False):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Button:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)
