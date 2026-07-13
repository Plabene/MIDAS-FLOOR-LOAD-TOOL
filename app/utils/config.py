from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json

from .path_utils import project_root

DEFAULT_BASE_URL = "https://moa-engineers.midasit.com:443/gen"
CONFIG_FILE = "midas_floorload_auto_config.local.json"


@dataclass
class AppConfig:
    base_url: str = DEFAULT_BASE_URL
    port: str = ""
    mapi_key: str = ""
    timeout_seconds: int = 60
    verify_ssl: bool = True
    story_tolerance: float = 0.01
    default_hatch_scale: float = 1.0
    snap_tolerance: float = 0.5
    area_error_limit: float = 0.25
    continuous_projection_min_coverage: float = 0.995
    continuous_projection_max_overreach_ratio: float = 0.005
    include_zero_load: bool = False
    auto_load_dm_dummy_members: bool = False
    mgt_import_capability_profile: str = "AUTO"
    floorload_max_logical_fields: int | None = None
    strict_post_import_verification: bool = True
    remove_failed_model_file: bool = True

    @property
    def resolved_base_url(self) -> str:
        base = (self.base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        port = str(self.port or "").strip()
        if port and "://" in base:
            scheme, rest = base.split("://", 1)
            host_path = rest.split("/", 1)
            host = host_path[0].split(":", 1)[0]
            suffix = "/" + host_path[1] if len(host_path) > 1 else ""
            return f"{scheme}://{host}:{port}{suffix}".rstrip("/")
        return base


def config_path() -> Path:
    return project_root() / "user_config" / CONFIG_FILE


def load_config() -> AppConfig:
    path = config_path()
    if not path.exists():
        return AppConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return AppConfig()
    mgt_import = data.get("mgt_import") if isinstance(data, dict) else None
    if isinstance(mgt_import, dict):
        data = dict(data)
        aliases = {
            "capability_profile": "mgt_import_capability_profile",
            "floorload_max_logical_fields": "floorload_max_logical_fields",
            "strict_post_import_verification": "strict_post_import_verification",
            "remove_failed_model_file": "remove_failed_model_file",
        }
        for source_key, target_key in aliases.items():
            if source_key in mgt_import and target_key not in data:
                data[target_key] = mgt_import[source_key]
    defaults = asdict(AppConfig())
    defaults.update({k: v for k, v in data.items() if k in defaults})
    return AppConfig(**defaults)


def save_config(config: AppConfig) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
