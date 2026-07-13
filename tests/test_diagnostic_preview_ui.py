from app.main import _should_show_diagnostic_preview
from app.core.model_floorload_diagnostics import FloorLoadDiagnosticIssue


def _issue(severity: str) -> FloorLoadDiagnosticIssue:
    return FloorLoadDiagnosticIssue(
        story_name="5F",
        severity=severity,
        issue_type="CUSTOM",
        message="",
        x=0.0,
        y=0.0,
        node_ids=[],
        element_ids=[],
        suggested_action="",
    )


def test_should_show_diagnostic_preview_for_error_or_warning_only():
    assert _should_show_diagnostic_preview([_issue("ERROR")]) is True
    assert _should_show_diagnostic_preview([_issue("WARNING")]) is True
    assert _should_show_diagnostic_preview([_issue("INFO")]) is False
    assert _should_show_diagnostic_preview([]) is False
