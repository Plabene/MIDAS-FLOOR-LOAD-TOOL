from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
import json
import logging
import math
import os
import re
import time

import requests

from ..utils.path_utils import unique_numbered_path
from .mgt_import_validator import (
    MgtImportCapabilities,
    ModelImportFingerprint,
    validate_mgt_for_import,
)


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


class MidasImportVerificationError(MidasProjectError):
    def __init__(
        self,
        message: str,
        *,
        detail: str = "",
        expected_fingerprint: ModelImportFingerprint | None = None,
        actual_fingerprint: ModelImportFingerprint | None = None,
        import_response: Any = None,
        db_responses: Mapping[str, Any] | None = None,
    ):
        super().__init__(message, detail=detail)
        self.expected_fingerprint = expected_fingerprint
        self.actual_fingerprint = actual_fingerprint
        self.import_response = import_response
        self.db_responses = dict(db_responses or {})


class MidasSaveVerificationError(MidasProjectError):
    pass


@dataclass
class MidasApiResult:
    ok: bool
    message: str
    endpoint: str = ""
    data: Any = None


@dataclass(frozen=True)
class MidasImportVerificationResult:
    status: str
    source_path: Path
    expected_fingerprint: ModelImportFingerprint
    actual_fingerprint: ModelImportFingerprint
    import_response: Any
    db_responses: Mapping[str, Any]
    poll_attempts: int

    @property
    def ok(self) -> bool:
        return self.status == "PASS"


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
                data: Any = {}
                _assert_command_response_success(data, path)
                return data
            try:
                data = response.json()
            except ValueError:
                data = {"raw_text": response.text}
            _assert_command_response_success(data, path)
            return data
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

    def save_as_project(self, target_path: str | Path, *, avoid_overwrite: bool = False) -> Path:
        path = Path(target_path).expanduser().resolve()
        if path.suffix.lower() != ".mgbx":
            path = path.with_suffix(".mgbx")
        if avoid_overwrite:
            path = unique_numbered_path(path, start=2)
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

    def import_mgt_verified(
        self,
        source_mgt_path: str | Path,
        expected_fingerprint: ModelImportFingerprint,
        *,
        poll_timeout_seconds: float = 15.0,
        poll_interval_seconds: float = 0.25,
    ) -> MidasImportVerificationResult:
        source = _require_file(source_mgt_path, "MGT/MGTX import 파일")
        import_response = self.import_mgt(source)
        _assert_command_response_success(import_response, self.IMPORT_ENDPOINT)
        deadline = time.monotonic() + max(0.0, float(poll_timeout_seconds))
        attempts = 0
        last_actual = ModelImportFingerprint()
        last_responses: dict[str, Any] = {}
        last_reason = "MIDAS DB가 아직 기대 model fingerprint에 도달하지 않았습니다."
        while True:
            attempts += 1
            try:
                node_response = self.get("db/NODE")
                elem_response = self.get("db/ELEM")
                stor_response = self.get("db/STOR")
                last_responses = {"NODE": node_response, "ELEM": elem_response, "STOR": stor_response}
                last_actual = _fingerprint_from_db_responses(node_response, elem_response, stor_response)
                last_reason = _fingerprint_mismatch_reason(expected_fingerprint, last_actual)
                if not last_reason:
                    return MidasImportVerificationResult(
                        status="PASS",
                        source_path=source,
                        expected_fingerprint=expected_fingerprint,
                        actual_fingerprint=last_actual,
                        import_response=import_response,
                        db_responses=last_responses,
                        poll_attempts=attempts,
                    )
            except MidasApiError as exc:
                last_reason = f"import 후 DB 조회에 실패했습니다: {exc}"
            if time.monotonic() >= deadline:
                break
            time.sleep(max(0.01, min(float(poll_interval_seconds), max(0.01, deadline - time.monotonic()))))
        raise MidasImportVerificationError(
            "MIDAS MGT import 응답은 완료되었지만 실제 NODE/ELEMENT/STORY model 구성을 검증하지 못했습니다. "
            "빈 프로젝트에는 SAVEAS를 수행하지 않습니다.",
            detail=(
                f"{last_reason} expected={expected_fingerprint.counts()} "
                f"actual={last_actual.counts()} attempts={attempts}"
            ),
            expected_fingerprint=expected_fingerprint,
            actual_fingerprint=last_actual,
            import_response=import_response,
            db_responses=last_responses,
        )

    def verify_import_by_export(
        self,
        target_mgt_path: str | Path,
        expected_fingerprint: ModelImportFingerprint,
        *,
        capabilities: MgtImportCapabilities | None = None,
    ) -> Path:
        target = Path(target_mgt_path).expanduser().resolve()
        target.unlink(missing_ok=True)
        exported = self.export_mgt(target)
        if not exported.exists() or not exported.is_file() or exported.stat().st_size <= 0:
            raise MidasImportVerificationError(
                "strict import 검증용 MGT export 파일이 생성되지 않았습니다.",
                detail=str(exported),
            )
        result = validate_mgt_for_import(exported, capabilities=capabilities)
        reason = _fingerprint_mismatch_reason(
            expected_fingerprint,
            result.model_fingerprint,
            check_story=True,
            check_extended=True,
        )
        if result.has_errors or reason:
            first_error = next((issue for issue in result.issues if issue.severity == "ERROR"), None)
            raise MidasImportVerificationError(
                "import 후 임시 MGT export의 model 무결성 검증에 실패했습니다.",
                detail=reason or (f"{first_error.code}: {first_error.message_ko}" if first_error else "preflight error"),
            )
        return exported

    def save_as_project_verified(
        self,
        target_path: str | Path,
        *,
        expected_fingerprint: ModelImportFingerprint | None = None,
        avoid_overwrite: bool = False,
        remove_failed_file: bool = True,
    ) -> Path:
        path = Path(target_path).expanduser().resolve()
        if path.suffix.lower() != ".mgbx":
            path = path.with_suffix(".mgbx")
        if avoid_overwrite:
            path = unique_numbered_path(path, start=2)
        path.parent.mkdir(parents=True, exist_ok=True)
        previous_stat = path.stat() if path.exists() else None
        request_started_ns = time.time_ns()
        try:
            response = self.post(self.SAVEAS_ENDPOINT, {"Argument": str(path)})
            _assert_command_response_success(response, self.SAVEAS_ENDPOINT)
            if not path.exists() or not path.is_file():
                raise MidasSaveVerificationError(
                    "MIDAS SAVEAS 응답 후 결과 MGBX 파일이 생성되지 않았습니다.", detail=str(path)
                )
            stat = path.stat()
            if stat.st_size <= 0:
                raise MidasSaveVerificationError("MIDAS SAVEAS 결과 MGBX 파일이 비어 있습니다.", detail=str(path))
            if previous_stat is not None and stat.st_mtime_ns == previous_stat.st_mtime_ns and stat.st_size == previous_stat.st_size:
                raise MidasSaveVerificationError("MIDAS SAVEAS가 기존 MGBX 파일을 갱신하지 않았습니다.", detail=str(path))
            # Some file systems expose coarse timestamps, so only reject an old
            # timestamp when this call created the target and it is clearly stale.
            if previous_stat is None and stat.st_mtime_ns + 2_000_000_000 < request_started_ns:
                raise MidasSaveVerificationError("MIDAS SAVEAS 결과 파일의 수정시간이 현재 작업보다 오래되었습니다.", detail=str(path))
            return path
        except Exception:
            if remove_failed_file and path.exists():
                try:
                    if previous_stat is None or path.stat().st_size <= 0:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

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


def _assert_command_response_success(response: Any, endpoint: str) -> None:
    failures: list[str] = []

    def inspect(value: Any, path: str = "") -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                lowered = str(key).strip().lower()
                item_path = f"{path}.{key}" if path else str(key)
                if lowered in {"error", "errors", "fail", "failed", "exception"} and _is_truthy_error(item):
                    failures.append(f"{item_path}={_truncate(str(item), 300)}")
                if lowered in {"success", "ok"} and item is False:
                    failures.append(f"{item_path}=false")
                if lowered == "result" and item is False:
                    failures.append(f"{item_path}=false")
                inspect(item, item_path)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for index, item in enumerate(value):
                inspect(item, f"{path}[{index}]")
        elif isinstance(value, str):
            normalized = value.strip()
            if re.search(r"\b(?:failed|failure|exception|fatal\s+error)\b|오류|실패", normalized, re.IGNORECASE):
                failures.append(f"{path or 'message'}={_truncate(normalized, 300)}")

    inspect(response)
    if failures:
        raise MidasProjectError(
            f"MIDAS command 응답이 application-level 실패를 반환했습니다: {endpoint}",
            detail=" | ".join(dict.fromkeys(failures)),
        )


def _is_truthy_error(value: Any) -> bool:
    if value in (None, False, 0, "", [], {}):
        return False
    if isinstance(value, str) and value.strip().lower() in {"false", "none", "null", "ok", "success"}:
        return False
    return True


def _fingerprint_from_db_responses(node_response: Any, elem_response: Any, stor_response: Any) -> ModelImportFingerprint:
    node_table = _extract_table(node_response, "NODE")
    elem_table = _extract_table(elem_response, "ELEM")
    stor_table = _extract_table(stor_response, "STOR")
    node_ids, coordinates = _table_ids_and_coordinates(node_table)
    element_ids, _unused = _table_ids_and_coordinates(elem_table)
    bbox = None
    if coordinates:
        xs, ys, zs = zip(*coordinates)
        bbox = (min(xs), min(ys), min(zs), max(xs), max(ys), max(zs))
    return ModelImportFingerprint(
        node_count=_table_count(node_table),
        element_count=_table_count(elem_table),
        story_count=_table_count(stor_table),
        coordinate_bbox=bbox,
        node_id_sample=_sample_ids(node_ids),
        element_id_sample=_sample_ids(element_ids),
    )


def _table_count(table: Any) -> int:
    if table is None:
        return 0
    if isinstance(table, Mapping):
        for key in ("Assign", "assign", "DATA", "data", "NODE", "ELEM", "STOR"):
            if key in table and table[key] is not table:
                return _table_count(table[key])
        return len(table)
    if isinstance(table, Sequence) and not isinstance(table, (str, bytes, bytearray)):
        return len(table)
    return 0


def _table_ids_and_coordinates(table: Any) -> tuple[list[int], list[tuple[float, float, float]]]:
    if isinstance(table, Mapping):
        for key in ("Assign", "assign", "DATA", "data", "NODE", "ELEM"):
            if key in table:
                return _table_ids_and_coordinates(table[key])
        entries = list(table.items())
    elif isinstance(table, Sequence) and not isinstance(table, (str, bytes, bytearray)):
        entries = list(enumerate(table, start=1))
    else:
        return [], []
    ids: list[int] = []
    coordinates: list[tuple[float, float, float]] = []
    for key, record in entries:
        record_id = _coerce_int(key)
        if isinstance(record, Mapping):
            record_id = _coerce_int(record.get("ID", record.get("id", record.get("NODE", record_id)))) or record_id
            xyz = tuple(_coerce_float(record.get(axis, record.get(axis.lower()))) for axis in ("X", "Y", "Z"))
            if all(value is not None for value in xyz):
                coordinates.append((float(xyz[0]), float(xyz[1]), float(xyz[2])))  # type: ignore[arg-type]
        if record_id is not None:
            ids.append(record_id)
    return ids, coordinates


def _fingerprint_mismatch_reason(
    expected: ModelImportFingerprint,
    actual: ModelImportFingerprint,
    *,
    check_story: bool = True,
    check_extended: bool = False,
) -> str:
    if actual.node_count <= 0:
        return "import 후 NODE count가 0입니다."
    if actual.element_count <= 0:
        return "import 후 ELEMENT count가 0입니다."
    checks = (("NODE", expected.node_count, actual.node_count), ("ELEMENT", expected.element_count, actual.element_count))
    if check_story:
        checks = (*checks, ("STORY", expected.story_count, actual.story_count))
    if check_extended:
        checks = (
            *checks,
            ("MATERIAL", expected.material_count, actual.material_count),
            ("SECTION", expected.section_count, actual.section_count),
            ("THICKNESS", expected.thickness_count, actual.thickness_count),
            ("STLDCASE", expected.load_case_count, actual.load_case_count),
            ("FLOADTYPE", expected.floorload_type_count, actual.floorload_type_count),
            ("FLOORLOAD", expected.floorload_count, actual.floorload_count),
        )
    for label, expected_count, actual_count in checks:
        if expected_count > 0 and actual_count != expected_count:
            return f"{label} count 불일치: expected={expected_count}, actual={actual_count}"
    if expected.node_id_sample and actual.node_id_sample and not set(expected.node_id_sample).issubset(set(actual.node_id_sample)):
        return f"NODE ID sample 불일치: expected={expected.node_id_sample}, actual={actual.node_id_sample}"
    if expected.element_id_sample and actual.element_id_sample and not set(expected.element_id_sample).issubset(set(actual.element_id_sample)):
        return f"ELEMENT ID sample 불일치: expected={expected.element_id_sample}, actual={actual.element_id_sample}"
    if expected.coordinate_bbox is not None and actual.coordinate_bbox is not None:
        scale = max(1.0, *(abs(value) for value in expected.coordinate_bbox))
        tolerance = scale * 1.0e-6
        if any(abs(left - right) > tolerance for left, right in zip(expected.coordinate_bbox, actual.coordinate_bbox)):
            return f"NODE coordinate bbox 불일치: expected={expected.coordinate_bbox}, actual={actual.coordinate_bbox}"
    return ""


def write_import_verification_report(
    output_path: str | Path,
    *,
    status: str,
    source_path: str | Path,
    target_path: str | Path | None = None,
    expected_fingerprint: ModelImportFingerprint | None = None,
    actual_fingerprint: ModelImportFingerprint | None = None,
    api_response: Any = None,
    message_ko: str = "",
    action_ko: str = "",
    saved_file: str | Path | None = None,
) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    saved_path = Path(saved_file).expanduser().resolve() if saved_file else None
    payload = {
        "stage": "MIDAS_IMPORT_VERIFICATION",
        "status": status,
        "code": "MIDAS_IMPORT_VERIFIED" if status == "PASS" else "MIDAS_IMPORT_VERIFICATION_FAILED",
        "endpoint": MidasGenApiClient.IMPORT_ENDPOINT,
        "source_path": str(source_path),
        "target_path": str(target_path or ""),
        "section": "",
        "logical_record": "",
        "physical_line_range": "",
        "expected_counts": expected_fingerprint.counts() if expected_fingerprint else {},
        "actual_counts": actual_fingerprint.counts() if actual_fingerprint else {},
        "api_response": _redact_sensitive(api_response),
        "message_ko": message_ko,
        "action_ko": action_ko,
        "saved_file_exists": bool(saved_path and saved_path.exists()),
        "saved_file_size": saved_path.stat().st_size if saved_path and saved_path.exists() else 0,
    }
    temp = path.with_name(f".{path.name}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, default=str)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def _redact_sensitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: "***REDACTED***" if str(key).lower().replace("-", "_") in {"mapi_key", "api_key", "authorization"} else _redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _coerce_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _sample_ids(values: Sequence[int], limit: int = 12) -> tuple[int, ...]:
    ordered = sorted(set(int(value) for value in values))
    if len(ordered) <= limit:
        return tuple(ordered)
    half = max(1, limit // 2)
    return tuple(ordered[:half] + ordered[-half:])


def _truncate(value: str, limit: int = 1000) -> str:
    text = value or ""
    return text if len(text) <= limit else text[:limit] + "...<truncated>"
