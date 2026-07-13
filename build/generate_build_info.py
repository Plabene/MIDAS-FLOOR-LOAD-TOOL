from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _source_files() -> list[Path]:
    files = [
        path
        for source_root in (ROOT / "app", ROOT / "legacy_v3" / "src")
        if source_root.exists()
        for path in source_root.rglob("*.py")
        if "__pycache__" not in path.parts
    ]
    files.extend(path for path in (ROOT / "midas_floorload_auto_v4.spec", ROOT / "requirements.txt") if path.exists())
    return sorted(files, key=lambda path: path.relative_to(ROOT).as_posix())


def _source_hash() -> str:
    digest = hashlib.sha256()
    for path in _source_files():
        relative = path.relative_to(ROOT).as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(path.read_bytes())
    return digest.hexdigest()[:16]


def _git_output(*args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return completed.stdout.strip()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "build_info.json")
    args = parser.parse_args()

    now = datetime.now().astimezone()
    git_commit = _git_output("rev-parse", "--short=12", "HEAD") or "unknown"
    git_dirty = bool(_git_output("status", "--porcelain", "--untracked-files=no"))
    payload: dict[str, object] = {
        "version": "v4",
        "build_timestamp": now.isoformat(timespec="seconds"),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "source_hash": _source_hash(),
    }

    if args.exe is not None:
        exe = args.exe.resolve()
        if not exe.is_file():
            raise SystemExit(f"EXE not found: {exe}")
        payload.update(
            {
                "exe_name": exe.name,
                "exe_timestamp": datetime.fromtimestamp(exe.stat().st_mtime).astimezone().isoformat(timespec="seconds"),
                "exe_sha256": _file_sha256(exe),
            }
        )

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[OK] Build info: {output}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
