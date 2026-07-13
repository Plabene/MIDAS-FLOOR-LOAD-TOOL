from types import SimpleNamespace

from app.main import _continuous_targets_are_single_range, update_story_check_selection


def test_single_click_toggles_clicked_iid_and_anchor():
    selected, anchor = update_story_check_selection(
        ["a", "b", "c"],
        {"a": _candidate(True), "b": _candidate(True), "c": _candidate(True)},
        {"a"},
        "b",
        None,
    )

    assert selected == {"a", "b"}
    assert anchor == "b"


def test_second_single_click_removes_existing_check():
    selected, anchor = update_story_check_selection(
        ["a", "b", "c"],
        {"a": _candidate(True), "b": _candidate(True), "c": _candidate(True)},
        {"a", "b"},
        "b",
        "b",
    )

    assert selected == {"a"}
    assert anchor == "b"


def test_ctrl_click_toggles_without_clearing_existing_selection():
    selected, anchor = update_story_check_selection(
        ["a", "b", "c"],
        {"a": _candidate(True), "b": _candidate(True), "c": _candidate(True)},
        {"a"},
        "c",
        "a",
        ctrl=True,
    )

    assert selected == {"a", "c"}
    assert anchor == "a"


def test_shift_click_selects_range_but_skips_not_applicable_rows():
    selected, anchor = update_story_check_selection(
        ["a", "b", "c", "d"],
        {"a": _candidate(True), "b": _candidate(False), "c": _candidate(True), "d": _candidate(True)},
        {"a"},
        "d",
        "a",
        shift=True,
    )

    assert selected == {"a", "c", "d"}
    assert anchor == "a"


def test_continuous_target_range_policy_rejects_gapped_selection():
    assert _continuous_targets_are_single_range(("2F", "3F"), ["1F", "2F", "3F", "4F"])
    assert not _continuous_targets_are_single_range(("2F", "4F"), ["1F", "2F", "3F", "4F"])


def _candidate(can_apply: bool):
    return SimpleNamespace(can_apply=can_apply)
