from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import logging
import time

import requests


class MidasApiError(RuntimeError):
    def __init__(self, message: str, *, detail: str = ""):
        super().__init__(message)
        self.detail = detail


class MidasApiConnectionError(MidasApiError):
    pass


class MidasApiAuthError(MidasApiError):
    pass


class MidasProjectError(MidasApiError):
    pass


@dataclass
class MidasApiResult:
    ok: bool
    message: str
    endpoint: str = ""
    data: Any = None


class MidasGenApiClient:
    """MIDAS Gen/NX REST API thin wrapper.

    Wall SSRF 프로젝트의 방식과 동일하게 doc/* endpoint에는 절대경로를
    {"Argument": "C:\\..."} 형태로 전달한다. API catalog/버전에 따라 일부
    endpoint 응답 포맷이 달라질 수 있으므로 DB 응답은 Assign/DATA/table key를 모두 허용한다.
    """

    OPEN_ENDPOINT = "doc/OPEN"
    NEW_ENDPOINT = "doc/NEW"
    SAVE_ENDPOINT = "doc/SAVE"
    SAVEAS_ENDPOINT = "doc/SAVEAS"
    EXPORT_ENDPOINT = "doc/EXPORTMXT"
    IMPORT_ENDPOINT = "doc/IMPORTMXT"

    def __init__(
        self,
        base_url: str,
        mapi_key: str = "",
        *,
        timeout_seconds: int | float = 60,
        verify_ssl: bool = True,
        logger: logging.Logger | None = None,
        session: requests.Session | None = None,
        retries: int = 1,
    ):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.mapi_key = str(mapi_key or "").strip()
        self.timeout_seconds = float(timeout_seconds)
        self.verify_ssl = bool(verify_ssl)
        self.logger = logger or logging.getLogger(__name__)
        self.session = session or requests.Session()
        self.retries = max(0, int(retries))

    def health_check(self) -> MidasApiResult:
        last: Exception | None = None
        for endpoint in ("db/STOR", "db/NODE", "doc/INFO"):
            try:
                data = self.get(endpoint, allow_endpoint_error=True)
                return MidasApiResult(True, "MIDAS Gen NX API 연결에 성공했습니다.", endpoint, data)
            except MidasApiError as exc:
                last = exc
                self.logger.warning("health_check failed endpoint=%s message=%s detail=%s", endpoint, exc, getattr(exc, "detail", ""))
        return MidasApiResult(False, f"MIDAS Gen NX API 연결에 실패했습니다. 프로그램 실행 여부와 API 포트를 확인해 주세요. ({last})")

    def request(self, method: str, path: str, payload: Any = None, *, timeout_seconds: int | float | None = None, allow_endpoint_error: bool = False) -> Any:
        if not self.base_url:
            raise MidasApiConnectionError("MIDAS API Base URL이 비어 있습니다.")
        url = f"{self.base_url}/{str(path).lstrip('/')}"
        headers = {"Content-Type": "application/json"}
        if self.mapi_key:
            headers["MAPI-Key"] = self.mapi_key
        last_exc: Exception | None = None
        attempts = self.retries + 1
        for attempt in range(1, attempts + 1):
            try:
                self.logger.info("MIDAS API request attempt=%s/%s method=%s endpoint=%s body=%s", attempt, attempts, method.upper(), path, _truncate(str(payload)))
                response = self.session.request(
                    method.upper(),
                    url,
                    json=payload,
                    headers=headers,
                    timeout=float(timeout_seconds or self.timeout_seconds),
                    verify=self.verify_ssl,
                )
                self.logger.info("MIDAS API response endpoint=%s status=%s text=%s", path, response.status_code, _truncate(response.text))
            except requests.exceptions.Timeout as exc:
                last_exc = exc
                if attempt <= self.retries:
                    time.sleep(0.5)
                    continue
                raise MidasApiConnectionError(f"MIDAS API 요청 시간이 초과되었습니다: {path}", detail=str(exc)) from exc
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                if attempt <= self.retries:
                    time.sleep(0.5)
                    continue
                raise MidasApiConnectionError("MIDAS Gen NX API 연결에 실패했습니다. 프로그램 실행 여부와 API 포트를 확인해 주세요.", detail=str(exc)) from exc
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                if attempt <= self.retries:
                    time.sleep(0.5)
                    continue
                raise MidasApiConnectionError(f"MIDAS API 요청에 실패했습니다: {path}", detail=str(exc)) from exc

            if response.status_code in {401, 403}:
                raise MidasApiAuthError("MIDAS API 인증에 실패했습니다. MAPI Key를 확인해 주세요.", detail=response.text)
            if response.status_code >= 400:
                if allow_endpoint_error:
                    raise MidasApiError(f"MIDAS API endpoint 오류: {path}", detail=response.text)
                raise MidasApiError(f"MIDAS API endpoint 오류({response.status_code}): {path}", detail=response.text)
            if not response.text.strip():
                return {}
            try:
                return response.json()
            except ValueError:
                return {"raw_text": response.text}
        raise MidasApiConnectionError(f"MIDAS API 요청 실패: {path}", detail=str(last_exc or ""))

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, payload: Any = None, **kwargs: Any) -> Any:
        return self.request("POST", path, payload, **kwargs)

    def open_project(self, model_path: str | Path) -> Any:
        path = _require_file(model_path, "모델 파일")
        if path.suffix.lower() not in {".mgb", ".mgbx", ".mcb"}:
            raise MidasProjectError(f"doc/OPEN 대상은 .mgb/.mgbx/.mcb만 허용합니다: {path}")
        return self.post(self.OPEN_ENDPOINT, {"Argument": str(path)})

    def new_project(self) -> Any:
        return self.post(self.NEW_ENDPOINT, {"Argument": {}})

    def save_project(self) -> Any:
        return self.post(self.SAVE_ENDPOINT, {"Argument": {}})

    def save_as_project(self, target_path: str | Path) -> Path:
        path = Path(target_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.post(self.SAVEAS_ENDPOINT, {"Argument": str(path)})
        return path

    def export_mgt(self, target_mgt_path: str | Path) -> Path:
        path = Path(target_mgt_path).expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.post(self.EXPORT_ENDPOINT, {"Argument": str(path)}, timeout_seconds=max(self.timeout_seconds, 180))
        return path

    def import_mgt(self, source_mgt_path: str | Path) -> Any:
        path = _require_file(source_mgt_path, "MGT/MGTX import 파일")
        return self.post(self.IMPORT_ENDPOINT, {"Argument": str(path)}, timeout_seconds=max(self.timeout_seconds, 300))

    def close_project(self) -> Any:
        # MIDAS 제품/버전에 따라 doc/CLOSE 미지원일 수 있어 실패해도 상위 흐름을 막지 않는다.
        try:
            return self.post("doc/CLOSE", {"Argument": {}})
        except MidasApiError as exc:
            self.logger.warning("doc/CLOSE skipped/failed: %s", exc)
            return {"warning": str(exc)}

    def get_story_data(self) -> Any:
        return _extract_table(self.get("db/STOR"), "STOR")

    def get_node_data(self) -> Any:
        return _extract_table(self.get("db/NODE"), "NODE")

    def get_element_data(self) -> Any:
        return _extract_table(self.get("db/ELEM"), "ELEM")


def _require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.exists() or not path.is_file():
        raise MidasProjectError(f"{label}을 찾을 수 없습니다: {path}")
    return path


def _extract_table(response: Any, table_key: str) -> Any:
    if isinstance(response, dict):
        for key in (table_key, table_key.upper(), table_key.lower(), "Assign", "assign", "DATA", "data"):
            if key in response:
                return response[key]
    return response


def _truncate(value: str, limit: int = 1000) -> str:
    text = value or ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"
