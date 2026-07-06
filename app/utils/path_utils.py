from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def safe_filename(value: str, max_len: int = 120) -> str:
    text = str(value or "").strip() or "unnamed"
    invalid = '<>:"/\\|?*\n\r\t'
    for ch in invalid:
        text = text.replace(ch, "_")
    text = "_".join(text.split())
    return text[:max_len].strip("._ ") or "unnamed"


def unique_output_path(path: Path) -> Path:
    """
    기존 파일을 덮어쓰지 않도록 고유 파일명을 반환한다.
    예:
      A.dxf가 없으면 A.dxf
      A.dxf가 있으면 A_001.dxf
      A_001.dxf도 있으면 A_002.dxf
    """
    path = Path(path)
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent

    for index in range(1, 1000):
        candidate = parent / f"{stem}_{index:03d}{suffix}"
        if not candidate.exists():
            return candidate

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return parent / f"{stem}_{timestamp}{suffix}"


def unique_numbered_path(path: str | Path, *, start: int = 2) -> Path:
    path = Path(path)
    if not path.exists():
        return path

    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    try:
        index = max(2, int(start))
    except Exception:
        index = 2

    while index < 10000:
        candidate = parent / f"{stem}_{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return parent / f"{stem}_{timestamp}{suffix}"


def output_root_dir(data_root: Path) -> Path:
    out = Path(data_root) / "OUTPUT"
    out.mkdir(parents=True, exist_ok=True)
    return out


def project_output_dir(data_root: Path, project_name: str | None = None) -> Path:
    raw_name = (project_name or "").strip()
    if not raw_name:
        raw_name = "untitled_project_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    safe_name = safe_filename(raw_name)
    if not safe_name:
        safe_name = "untitled_project_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    out = output_root_dir(data_root) / safe_name
    out.mkdir(parents=True, exist_ok=True)
    return out


def ensure_project_output_subdirs(project_dir: Path) -> dict[str, Path]:
    project_dir = Path(project_dir)
    subdirs = {
        "dxf_templates": project_dir / "dxf_templates",
        "imported_dxf": project_dir / "imported_dxf",
        "mgt": project_dir / "mgt",
        "models": project_dir / "models",
        "reports": project_dir / "reports",
        "pdf_jobs": project_dir / "pdf_jobs",
    }
    for path in subdirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return subdirs
