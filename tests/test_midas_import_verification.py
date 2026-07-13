from pathlib import Path

import pytest

from app.core.mgt_import_validator import ModelImportFingerprint
from app.core.midas_api_client import MidasGenApiClient, MidasImportVerificationError, MidasProjectError


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload
        self.text = "payload"

    def json(self):
        return self.payload


class _Session:
    def __init__(self, *, empty_db=False, import_payload=None):
        self.empty_db = empty_db
        self.import_payload = import_payload or {"message": "completed"}
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if url.endswith("/doc/IMPORTMXT"):
            return _Response(self.import_payload)
        if self.empty_db:
            return _Response({})
        if url.endswith("/db/NODE"):
            return _Response({"NODE": {"1": {"X": 0, "Y": 0, "Z": 0}, "2": {"X": 1, "Y": 0, "Z": 0}}})
        if url.endswith("/db/ELEM"):
            return _Response({"ELEM": {"1": {"TYPE": "BEAM"}}})
        if url.endswith("/db/STOR"):
            return _Response({"STOR": {"1": {"NAME": "1F"}}})
        return _Response({})


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "full.mgt"
    path.write_text("*ENDDATA\n", encoding="utf-8")
    return path


def _expected() -> ModelImportFingerprint:
    return ModelImportFingerprint(
        node_count=2,
        element_count=1,
        story_count=1,
        coordinate_bbox=(0, 0, 0, 1, 0, 0),
        node_id_sample=(1, 2),
        element_id_sample=(1,),
    )


def test_http_200_generic_completion_with_empty_db_fails_before_saveas(tmp_path):
    session = _Session(empty_db=True)
    client = MidasGenApiClient("http://midas.example", session=session, retries=0)

    with pytest.raises(MidasImportVerificationError):
        client.import_mgt_verified(_source(tmp_path), _expected(), poll_timeout_seconds=0)

    assert not any(url.endswith("/doc/SAVEAS") for _method, url, _kwargs in session.requests)


def test_application_level_error_payload_is_rejected(tmp_path):
    session = _Session(import_payload={"success": False, "error": "parser failed"})
    client = MidasGenApiClient("http://midas.example", session=session, retries=0)

    with pytest.raises(MidasProjectError):
        client.import_mgt_verified(_source(tmp_path), _expected(), poll_timeout_seconds=0)


def test_db_fingerprint_success_allows_verified_result(tmp_path):
    session = _Session()
    client = MidasGenApiClient("http://midas.example", session=session, retries=0)

    result = client.import_mgt_verified(_source(tmp_path), _expected(), poll_timeout_seconds=0)

    assert result.ok
    assert result.actual_fingerprint.node_count == 2
    assert result.actual_fingerprint.element_count == 1


def test_saveas_missing_file_is_failure(tmp_path):
    session = _Session()
    client = MidasGenApiClient("http://midas.example", session=session, retries=0)

    with pytest.raises(Exception, match="생성되지 않았습니다"):
        client.save_as_project_verified(tmp_path / "missing.mgbx")

