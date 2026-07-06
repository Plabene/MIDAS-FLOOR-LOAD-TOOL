from app.core.midas_api_client import MidasGenApiClient


class _Response:
    status_code = 200
    text = "{}"

    def json(self):
        return {}


class _Session:
    def __init__(self):
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        return _Response()


def test_save_as_project_normalizes_target_to_mgbx(tmp_path):
    session = _Session()
    client = MidasGenApiClient("http://midas.example", session=session)

    saved = client.save_as_project(tmp_path / "model_floorload_added.mgb")

    assert saved.suffix.lower() == ".mgbx"
    assert saved.name == "model_floorload_added.mgbx"
    _method, url, kwargs = session.requests[-1]
    assert url.endswith("/doc/SAVEAS")
    assert kwargs["json"]["Argument"].endswith("model_floorload_added.mgbx")


def test_save_as_project_can_avoid_overwrite_with_numbered_suffix(tmp_path):
    session = _Session()
    client = MidasGenApiClient("http://midas.example", session=session)
    (tmp_path / "model_floorload_added.mgbx").write_text("existing", encoding="utf-8")

    saved = client.save_as_project(tmp_path / "model_floorload_added.mgbx", avoid_overwrite=True)

    assert saved.name == "model_floorload_added_2.mgbx"
    _method, _url, kwargs = session.requests[-1]
    assert kwargs["json"]["Argument"].endswith("model_floorload_added_2.mgbx")
