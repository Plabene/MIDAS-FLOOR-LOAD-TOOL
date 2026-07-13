from contextlib import nullcontext

from app.core.mgt_parser import Node
from app.main import DummyIssueViewModel, FloorLoadAutoApp


class Button:
    def __init__(self):
        self.state = "disabled"

    def configure(self, **kwargs):
        self.state = kwargs.get("state", self.state)


class TextVar:
    def __init__(self):
        self.value = ""

    def set(self, value):
        self.value = str(value)


def test_problem_x_selection_enables_only_valid_plan_and_cancel_restores_issue():
    app = object.__new__(FloorLoadAutoApp)
    issue = DummyIssueViewModel(
        issue_key="I1",
        story_name="1F",
        issue_type="CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD",
        free_node_id=1,
        source_element_ids=(10,),
        region_id="R1",
        xy=(0, 0),
        candidate_boundary_nodes=(2,),
        recommended_boundary_node=2,
        can_generate=True,
    )
    app.dummy_issue_by_key = {"I1": issue}
    app.selected_dummy_issue_key = None
    app.dummy_preview_plan = None
    app.approved_dummy_plans = {}
    app.nodes = [Node(1, 0, 0, 0), Node(2, 5, 0, 0)]
    app.dummy_create_button = Button()
    app.dummy_cancel_button = Button()
    app.dummy_status_var = TextVar()
    app._update_dummy_member_overlay = lambda: None
    app._invalidate_continuous_below_allowed_reason_cache = lambda _reason="": None
    app._ensure_hatch_edit_states = lambda _story=None: None
    app._hatch_edit_command = lambda _label: nullcontext()

    assert app._select_dummy_issue("I1") is True
    assert app.dummy_create_button.state == "normal"
    assert app._approve_selected_dummy_plan(confirm=False) is True
    assert app.dummy_create_button.state == "disabled"
    assert app.dummy_cancel_button.state == "normal"
    assert app.approved_dummy_plans["I1"].approved is True

    assert app._cancel_selected_dummy_plan() is True
    assert app.dummy_issue_by_key["I1"].status == "OPEN"
    assert app.dummy_cancel_button.state == "disabled"

    app._clear_dummy_issue_selection(update_overlay=False)
    assert app.selected_dummy_issue_key is None
    assert app.dummy_create_button.state == "disabled"
