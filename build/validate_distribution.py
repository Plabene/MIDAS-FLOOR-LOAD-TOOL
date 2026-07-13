from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


FORBIDDEN_BUILD_FILES = [
    "Analysis-00.toc",
    "EXE-00.toc",
    "COLLECT-00.toc",
    "PKG-00.toc",
    "PYZ-00.pyz",
    "midas_floorload_auto_v4.pkg",
]


def fail(message: str) -> None:
    print(f"[ERROR] {message}")
    raise SystemExit(1)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "dist" / "midas_floorload_auto_v4"
    target = target.resolve()

    if not target.exists() or not target.is_dir():
        fail(f"Distribution folder not found: {target}")

    found_forbidden = [name for name in FORBIDDEN_BUILD_FILES if (target / name).exists()]
    if found_forbidden:
        fail(
            "This looks like a PyInstaller build work folder, not a distributable dist folder. "
            f"Forbidden files found: {', '.join(found_forbidden)}"
        )

    exe = target / "midas_floorload_auto_v4.exe"
    internal = target / "_internal"
    base_library_zip = internal / "base_library.zip"
    required = [
        exe,
        internal,
        base_library_zip,
        target / "build_info.json",
        target / "legacy_v3",
        target / "user_config",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        extra = ""
        if (internal / "legacy_v3").exists() or (internal / "user_config").exists():
            extra = (
                "\nThese folders exist under _internal, but the app expects them next to the exe. "
                "Run the post-build copy step in build_exe.bat."
            )
        fail("Missing required distribution files/folders:\n  " + "\n  ".join(missing) + extra)

    if not base_library_zip.is_file():
        fail("base_library.zip must remain zipped. Do not extract base_library.zip.")

    try:
        build_info = json.loads((target / "build_info.json").read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"build_info.json is invalid: {exc}")
    required_build_fields = {"build_timestamp", "git_commit", "source_hash", "exe_timestamp", "exe_sha256"}
    missing_build_fields = sorted(required_build_fields.difference(build_info))
    if missing_build_fields:
        fail(f"build_info.json is missing fields: {', '.join(missing_build_fields)}")
    actual_exe_sha256 = hashlib.sha256(exe.read_bytes()).hexdigest()
    if str(build_info.get("exe_sha256") or "").lower() != actual_exe_sha256:
        fail("build_info.json exe_sha256 does not match the built executable.")

    extracted_base_library = [
        internal / "base_library",
        internal / "base_library.zip_unpacked",
    ]
    found_extracted = [str(path) for path in extracted_base_library if path.exists()]
    if found_extracted:
        fail(
            "base_library.zip appears to have been extracted. "
            "base_library.zip must remain zipped. Do not extract base_library.zip. "
            f"Found: {', '.join(found_extracted)}"
        )

    python_dlls = list(internal.rglob("python*.dll")) + list(internal.rglob("python*.DLL"))
    if not python_dlls:
        fail(
            "Python runtime DLL was not found under _internal. "
            "Example expected: python311.dll/python312.dll/python313.dll/python314.dll"
        )

    native_files = list(internal.rglob("*.pyd")) + list(internal.rglob("*.dll")) + list(internal.rglob("*.DLL"))
    if not native_files:
        fail("No .pyd/.dll files were found under _internal. The distribution is incomplete.")

    print("[OK] Distribution folder is valid.")
    print("[OK] base_library.zip is a runtime file. Employees do not need to extract it.")
    print(f"[OK] EXE: {exe}")
    print(f"[OK] Build timestamp: {build_info['build_timestamp']}")
    print(f"[OK] Git/source: {build_info['git_commit']} / {build_info['source_hash']}")
    print(f"[OK] EXE SHA-256: {actual_exe_sha256}")
    print(f"[OK] Python DLL: {python_dlls[0]}")


if __name__ == "__main__":
    main()
