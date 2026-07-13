from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_pyinstaller_spec_contains_distribution_settings():
    spec = ROOT / "midas_floorload_auto_v4.spec"
    assert spec.exists()

    text = spec.read_text(encoding="utf-8")
    assert "app/main.py" in text
    assert "legacy_v3" in text
    assert "user_config" in text
    assert "resources" in text
    assert "console=False" in text
    assert "upx=False" in text
    assert "midas_floorload_auto_v4" in text


def test_packaging_scripts_and_installer_files_exist():
    assert (ROOT / "build" / "build_exe.bat").exists()
    assert (ROOT / "build" / "build_debug_exe.bat").exists()
    assert (ROOT / "build" / "validate_distribution.py").exists()
    assert (ROOT / "build" / "package_release_zip.bat").exists()
    assert (ROOT / "installer" / "midas_floorload_auto_v4.iss").exists()
    assert (ROOT / "packaging" / "README_DEPLOY.md").exists()


def test_deployment_readme_mentions_required_workflow():
    readme = _read("packaging/README_DEPLOY.md")
    assert "build\\build_exe.bat" in readme
    assert "Inno Setup" in readme
    assert "Python 없는 PC" in readme


def test_build_bat_uses_crlf_and_quoted_python_runner():
    for rel in ["build/build_exe.bat", "build/build_debug_exe.bat"]:
        data = (ROOT / rel).read_bytes()
        assert b"\r\n" in data
        assert data.count(b"\r\n") == data.count(b"\n")
        text = data.decode("ascii")
        assert 'set "PY_RUN=' in text
        assert '.venv\\Scripts\\python.exe' in text
        assert 'set "PY_RUN="%ROOT_DIR%\\.venv\\Scripts\\python.exe""' in text
        assert "%PY_RUN%" in text
        assert "chcp 65001" not in text


def test_build_exe_bat_uses_quoted_spec_path():
    text = (ROOT / "build" / "build_exe.bat").read_bytes().decode("ascii")
    assert '"%ROOT_DIR%\\midas_floorload_auto_v4.spec"' in text


def test_release_zip_bat_uses_dist_folder_and_warns_about_base_library():
    data = (ROOT / "build" / "package_release_zip.bat").read_bytes()
    assert b"\r\n" in data
    assert data.count(b"\r\n") == data.count(b"\n")
    text = data.decode("ascii")
    assert "Compress-Archive" in text
    assert "dist\\midas_floorload_auto_v4" in text
    assert "Do NOT extract _internal\\base_library.zip" in text
    assert "build\\midas_floorload_auto_v4" not in text


def test_validate_distribution_checks_internal_runtime_files():
    text = (ROOT / "build" / "validate_distribution.py").read_text(encoding="utf-8")
    assert "_internal" in text
    assert "python*.dll" in text
    assert "base_library.zip" in text
    assert "Analysis-00.toc" in text
    assert "Do not extract base_library.zip" in text or "must remain zipped" in text


def test_deploy_readme_explains_one_unzip_and_base_library():
    text = (ROOT / "packaging" / "README_DEPLOY.md").read_text(encoding="utf-8")
    assert "base_library.zip" in text
    assert "추가로 압축 해제하지 마세요" in text or "Do not extract" in text
    assert "Python은 설치하지 않아도 됩니다" in text


def test_build_exe_copies_runtime_data_to_dist_root():
    text = (ROOT / "build" / "build_exe.bat").read_bytes().decode("ascii")
    assert "robocopy" in text
    assert "legacy_v3" in text
    assert "user_config" in text
    assert "resources" in text
    assert "dist\\midas_floorload_auto_v4\\legacy_v3" in text
    assert "dist\\midas_floorload_auto_v4\\user_config" in text
    assert "dist\\midas_floorload_auto_v4\\resources" in text
    assert "*.local.json" in text
    assert "errorlevel 8" in text


def test_debug_build_copies_runtime_data_to_debug_dist_root():
    text = (ROOT / "build" / "build_debug_exe.bat").read_bytes().decode("ascii")
    assert "robocopy" in text
    assert "dist\\midas_floorload_auto_v4_debug\\legacy_v3" in text
    assert "dist\\midas_floorload_auto_v4_debug\\user_config" in text
    assert "dist\\midas_floorload_auto_v4_debug\\resources" in text
    assert "*.local.json" in text
    assert "errorlevel 8" in text


def test_validator_explains_internal_data_folder_mismatch():
    text = (ROOT / "build" / "validate_distribution.py").read_text(encoding="utf-8")
    assert "under _internal" in text
    assert "next to the exe" in text
    assert "post-build copy" in text


def test_readme_has_troubleshooting_for_missing_runtime_data_folders():
    text = (ROOT / "packaging" / "README_DEPLOY.md").read_text(encoding="utf-8")
    assert "legacy_v3/user_config 누락" in text
    assert "legacy_v3" in text
    assert "user_config" in text
    assert "post-build copy" in text or "검증 실패" in text
    assert "*.local.json" in text
