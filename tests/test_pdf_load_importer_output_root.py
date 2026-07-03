from pathlib import Path
import sys

from app.core.pdf_load_importer import run_pdf_load_import


def test_run_pdf_load_import_uses_supplied_output_root(tmp_path: Path, monkeypatch):
    legacy_src = tmp_path / "legacy_v3" / "src"
    legacy_config = tmp_path / "legacy_v3" / "config"
    legacy_src.mkdir(parents=True)
    legacy_config.mkdir(parents=True)
    (legacy_config / "midas_settings.yml").write_text("output:\n  file_name: out.mgtx\n", encoding="utf-8")
    (legacy_config / "load_mapping.yml").write_text("{}\n", encoding="utf-8")

    modules = {
        "pdf_extract.py": "def extract_pdf_load_candidates(input_dir):\n    return []\n",
        "load_parser.py": "def parse_load_rows(rows):\n    return rows\n",
        "load_classifier.py": "def classify_loads(rows, mapping_path=None, settings_path=None):\n    return rows\n",
        "manual_overrides.py": (
            "def load_manual_overrides(path):\n    return {}\n"
            "def apply_manual_overrides(rows, overrides):\n    return rows\n"
        ),
        "validators.py": "def validate_rows(rows):\n    return rows, rows\n",
        "midas_mgtx_writer.py": (
            "def write_log_files(rows, error_rows, output_dir):\n"
            "    (output_dir / 'auto_input_log.xlsx').write_text('', encoding='utf-8')\n"
            "    (output_dir / 'auto_input_log.json').write_text('[]', encoding='utf-8')\n"
            "    (output_dir / 'error_log.txt').write_text('', encoding='utf-8')\n"
        ),
    }
    for name, text in modules.items():
        (legacy_src / name).write_text(text, encoding="utf-8")
        monkeypatch.delitem(sys.modules, Path(name).stem, raising=False)

    pdf = tmp_path / "loads.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    output_root = tmp_path / "DATA" / "OUTPUT" / "Project" / "pdf_jobs"

    result = run_pdf_load_import(pdf_paths=[pdf], root_dir=tmp_path, output_root=output_root, job_name="job")

    assert result.job_dir == output_root / "job"
    assert result.input_dir == output_root / "job" / "source_pdfs"
    assert result.input_pdf_paths == (output_root / "job" / "source_pdfs" / "loads.pdf",)
    assert not (tmp_path / "DATA" / "pdf_jobs").exists()
