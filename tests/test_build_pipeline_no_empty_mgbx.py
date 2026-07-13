from pathlib import Path

import pytest

from app.core.mgt_import_validator import ModelImportFingerprint
from app.core.midas_api_client import MidasGenApiClient, MidasImportVerificationError


class _Response:
    status_code = 200
    text = "{}"

    def json(self):
        return {}


class _EmptyModelSession:
    def __init__(self):
        self.urls = []

    def request(self, method, url, **kwargs):
        self.urls.append(url)
        return _Response()


def test_empty_import_never_reaches_saveas(tmp_path: Path):
    source = tmp_path / "full.mgt"
    source.write_text("*ENDDATA\n", encoding="utf-8")
    session = _EmptyModelSession()
    client = MidasGenApiClient("http://midas.example", session=session, retries=0)

    with pytest.raises(MidasImportVerificationError):
        client.import_mgt_verified(
            source,
            ModelImportFingerprint(node_count=1, element_count=1),
            poll_timeout_seconds=0,
        )

    assert not any(url.endswith("/doc/SAVEAS") for url in session.urls)
    assert list(tmp_path.glob("*.mgbx")) == []

