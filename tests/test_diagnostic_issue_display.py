from app.core.model_floorload_diagnostics import FloorLoadDiagnosticIssue, diagnostic_issue_user_text


def test_split_overlap_duplicate_issue_uses_korean_user_text():
    issue = FloorLoadDiagnosticIssue(
        story_name="5F",
        severity="WARNING",
        issue_type="SPLIT_OVERLAP_DUPLICATE_ELEMENT",
        message="raw message",
        x=0.0,
        y=0.0,
        node_ids=[],
        element_ids=[100, 101],
        suggested_action="raw action",
    )

    text = diagnostic_issue_user_text(issue)

    assert text["severity_label"] == "확인 필요"
    assert "분할" in text["type_label"]
    assert "중복" in text["type_label"]
    assert "정리" in text["action"]
    assert text["short_label"] == "분할중복"


def test_cantilever_free_end_action_mentions_load_dm_dummy_beam():
    issue = FloorLoadDiagnosticIssue(
        story_name="5F",
        severity="WARNING",
        issue_type="CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD",
        message="raw message",
        x=0.0,
        y=0.0,
        node_ids=[10],
        element_ids=[20],
        suggested_action="raw action",
    )

    text = diagnostic_issue_user_text(issue)

    assert "외팔보" in text["type_label"]
    assert "LOAD DM dummy BEAM 자동 생성" in text["action"]


def test_unknown_issue_type_keeps_raw_message_and_action():
    issue = FloorLoadDiagnosticIssue(
        story_name="",
        severity="INFO",
        issue_type="CUSTOM_RAW_TYPE",
        message="raw message",
        x=0.0,
        y=0.0,
        node_ids=[],
        element_ids=[],
        suggested_action="raw action",
    )

    text = diagnostic_issue_user_text(issue)

    assert text["type_label"] == "CUSTOM_RAW_TYPE"
    assert text["cause"] == "raw message"
    assert text["action"] == "raw action"
