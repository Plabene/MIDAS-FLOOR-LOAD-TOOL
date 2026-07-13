from types import SimpleNamespace

from app.main import FloorLoadAutoApp


def test_continuous_reason_codes_are_rendered_as_korean_messages():
    app = object.__new__(FloorLoadAutoApp)

    assert app._continuous_reason_user_text(_candidate(False, "NO_MATCH")) == "선택한 해치와 같은 형상의 영역을 찾지 못했습니다."
    assert app._continuous_reason_user_text(_candidate(False, "LOW_SIMILARITY")) == "형상 유사도가 낮아 자동 적용할 수 없습니다."
    assert app._continuous_reason_user_text(_candidate(False, "BOUNDARY_MISMATCH")) == "경계선 구성이 달라 자동 적용할 수 없습니다."
    assert app._continuous_reason_user_text(_candidate(True, "OK")) == "적용 가능합니다."


def test_continuous_conflict_reason_overrides_internal_candidate_reason():
    app = object.__new__(FloorLoadAutoApp)
    message = app._continuous_reason_user_text(
        _candidate(True, "OK"),
        conflict_reason="이미 다른 하중이 반영되어 있습니다. 계속 선택하면 겹치는 영역만 새 연속층 하중으로 대체됩니다.",
    )

    assert "이미 다른 하중" in message
    assert "OK" not in message


def _candidate(can_apply: bool, reason: str):
    return SimpleNamespace(can_apply=can_apply, reason=reason)
