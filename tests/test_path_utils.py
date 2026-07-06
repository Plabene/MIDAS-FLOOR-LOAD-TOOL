from app.utils.path_utils import ensure_project_output_subdirs, output_root_dir, project_output_dir, unique_numbered_path, unique_output_path


def test_unique_output_path_returns_original_when_missing(tmp_path):
    path = tmp_path / "model_B3_floorload_template.dxf"
    assert unique_output_path(path) == path


def test_unique_output_path_adds_sequence_when_file_exists(tmp_path):
    path = tmp_path / "model_B3_floorload_template.dxf"
    path.write_text("locked or existing", encoding="utf-8")
    assert unique_output_path(path) == tmp_path / "model_B3_floorload_template_001.dxf"


def test_unique_output_path_skips_existing_sequence_files(tmp_path):
    path = tmp_path / "model_B3_floorload_template.dxf"
    path.write_text("existing", encoding="utf-8")
    (tmp_path / "model_B3_floorload_template_001.dxf").write_text("existing", encoding="utf-8")
    assert unique_output_path(path) == tmp_path / "model_B3_floorload_template_002.dxf"


def test_unique_numbered_path_uses_2_3_4_suffix(tmp_path):
    path = tmp_path / "model_floorload_added.mgbx"
    assert unique_numbered_path(path) == path

    path.write_text("existing", encoding="utf-8")
    assert unique_numbered_path(path) == tmp_path / "model_floorload_added_2.mgbx"

    (tmp_path / "model_floorload_added_2.mgbx").write_text("existing", encoding="utf-8")
    assert unique_numbered_path(path) == tmp_path / "model_floorload_added_3.mgbx"


def test_project_output_dir_creates_reusable_project_workspace(tmp_path):
    project_dir = project_output_dir(tmp_path, "A/B Model")
    again = project_output_dir(tmp_path, "A/B Model")
    subdirs = ensure_project_output_subdirs(project_dir)

    assert output_root_dir(tmp_path) == tmp_path / "OUTPUT"
    assert project_dir == tmp_path / "OUTPUT" / "A_B_Model"
    assert again == project_dir
    assert set(subdirs) == {"dxf_templates", "imported_dxf", "mgt", "models", "reports", "pdf_jobs"}
    assert all(path.exists() for path in subdirs.values())
