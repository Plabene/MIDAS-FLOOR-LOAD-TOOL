from types import SimpleNamespace

from app.main import FloorLoadAutoApp, compute_continuous_drag_selection


def _candidate(story: str, can_apply: bool = True):
    return SimpleNamespace(target_story_name=story, can_apply=can_apply, reason="unavailable" if not can_apply else "")


def test_plain_ctrl_and_shift_drag_selection_math():
    ordered = ["a", "b", "c", "d"]
    candidates = {iid: _candidate(iid) for iid in ordered}

    assert compute_continuous_drag_selection(ordered, candidates, {"d"}, "a", "c") == {"a", "b", "c"}
    assert compute_continuous_drag_selection(ordered, candidates, {"d"}, "a", "c", mode="ctrl_add") == set(ordered)
    assert compute_continuous_drag_selection(ordered, candidates, {"a", "b", "d"}, "a", "c", mode="ctrl_remove") == {"d"}
    assert compute_continuous_drag_selection(ordered, candidates, {"d"}, "b", "c", mode="shift", anchor_iid="a") == set(ordered)


def test_unavailable_row_stops_drag_range():
    ordered = ["a", "b", "c", "d"]
    candidates = {"a": _candidate("a"), "b": _candidate("b"), "c": _candidate("c", False), "d": _candidate("d")}

    selected = compute_continuous_drag_selection(ordered, candidates, set(), "a", "d")

    assert selected == {"a", "b"}


def test_motion_only_previews_and_release_syncs_once():
    app, tree, sync_calls = _app()
    initial_targets = {"region": ("d",)}
    app.continuous_apply_targets_by_region = dict(initial_targets)

    app._on_continuous_tree_button_press(SimpleNamespace(x=5, y=10, state=0))
    app._on_continuous_tree_drag_motion(SimpleNamespace(x=5, y=35, state=0))

    assert tree.selected == {"a", "b", "c"}
    assert app.continuous_apply_targets_by_region == initial_targets
    assert sync_calls == []

    app._on_continuous_tree_button_release(SimpleNamespace(x=5, y=35, state=0))

    assert sync_calls == [({"a", "b", "c"}, True)]


def test_small_motion_uses_existing_click_toggle_and_escape_restores_preview():
    app, tree, sync_calls = _app(initial={"d"})
    app._on_continuous_tree_button_press(SimpleNamespace(x=5, y=10, state=0))
    app._on_continuous_tree_drag_motion(SimpleNamespace(x=6, y=11, state=0))
    app._on_continuous_tree_button_release(SimpleNamespace(x=6, y=11, state=0))
    assert sync_calls == [({"a", "d"}, True)]

    sync_calls.clear()
    tree.selection_set(["d"])
    app._on_continuous_tree_button_press(SimpleNamespace(x=5, y=10, state=0))
    app._on_continuous_tree_drag_motion(SimpleNamespace(x=5, y=35, state=0))
    app._on_continuous_tree_drag_cancel()
    assert tree.selected == {"d"}
    assert sync_calls == []


def test_autoscroll_callback_is_cancelled_on_release():
    app, tree, _sync_calls = _app()
    app._on_continuous_tree_button_press(SimpleNamespace(x=5, y=10, state=0))
    app._on_continuous_tree_drag_motion(SimpleNamespace(x=5, y=99, state=0))
    assert tree.after_callbacks

    app._on_continuous_tree_button_release(SimpleNamespace(x=5, y=99, state=0))

    assert tree.cancelled_after_ids


def _app(initial=()):
    app = object.__new__(FloorLoadAutoApp)
    tree = _Tree(initial)
    app.continuous_tree = tree
    app.continuous_ordered_iids = ["a", "b", "c", "d"]
    app.continuous_candidate_by_iid = {iid: _candidate(iid) for iid in app.continuous_ordered_iids}
    app.continuous_story_anchor_iid = None
    app.continuous_drag_active = False
    app.continuous_drag_autoscroll_after_id = None
    app._continuous_drag_autoscroll_direction = 0
    app._get_continuous_active_visible_targets = lambda: ()
    sync_calls = []

    def sync(selected, *, sync_targets=True):
        sync_calls.append((set(selected), sync_targets))
        tree.selection_set(selected)

    app._set_continuous_tree_selection = sync
    return app, tree, sync_calls


class _Tree:
    def __init__(self, selected=()):
        self.selected = set(selected)
        self.rows = ["a", "b", "c", "d"]
        self.values = {iid: ["", iid, "", "", "", "가능", ""] for iid in self.rows}
        self.after_callbacks = {}
        self.cancelled_after_ids = []
        self.grabbed = False

    def identify_row(self, y):
        index = max(0, min(len(self.rows) - 1, int(y) // 12))
        return self.rows[index]

    def selection(self):
        return tuple(self.selected)

    def selection_set(self, selected):
        self.selected = set(selected)

    def get_children(self):
        return tuple(self.rows)

    def item(self, iid, option=None, **kwargs):
        if "values" in kwargs:
            self.values[iid] = list(kwargs["values"])
        if option == "values":
            return tuple(self.values[iid])
        return {"values": tuple(self.values[iid])}

    def focus_set(self):
        return None

    def grab_set(self):
        self.grabbed = True

    def grab_release(self):
        self.grabbed = False

    def winfo_height(self):
        return 100

    def after(self, _delay, callback):
        after_id = f"after-{len(self.after_callbacks) + 1}"
        self.after_callbacks[after_id] = callback
        return after_id

    def after_cancel(self, after_id):
        self.cancelled_after_ids.append(after_id)
        self.after_callbacks.pop(after_id, None)

    def yview_scroll(self, direction, units):
        self.last_scroll = (direction, units)

