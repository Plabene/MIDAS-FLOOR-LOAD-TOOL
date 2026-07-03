from app.utils.path_utils import unique_output_path


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
