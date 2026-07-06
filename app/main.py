from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import inspect
import os
from datetime import datetime
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

try:
    # package 실행: python -m app.main
    from .core.dxf_load_reader import read_load_regions
    from .core.diagnostic_dxf_writer import write_floorload_diagnostic_dxf
    from .core.dxf_template_writer import LoadLayerSpec, normalize_hatch_scale, write_all_story_centerline_dxf, write_story_centerline_dxf
    from .core.dxf_story_layout import LayoutMetadataSelection, select_layout_metadata
    from .core.floorload_mgt_builder import run_mgt_build_pipeline
    from .core.load_selection import apply_load_display_names
    from .core.pdf_load_importer import (
        PdfLoadImportResult,
        detect_floor_load_presence_from_text,
        merge_pdf_mgtx_into_full_mgt,
        run_pdf_load_import,
    )
    from .core.mgt_parser import (
        FloorLoadTypeSpec,
        Story,
        parse_floorload_type_names_from_text,
        parse_floadtype_specs_from_text,
        parse_mgt_file,
        select_nodes_by_story,
    )
    from .core.midas_api_client import MidasApiError, MidasGenApiClient
    from .core.load_parser import parse_load_layer
    from .core.load_input_policy import infer_distribution
    from .core.model_floorload_diagnostics import analyze_floorload_model, write_diagnostic_reports
    from .core.progress import ProgressReporter
    from .utils.config import AppConfig, load_config, save_config
    from .utils.logger import setup_logger
    from .utils.path_utils import (
        ensure_project_output_subdirs,
        output_root_dir,
        project_output_dir,
        project_root,
        safe_filename,
        unique_numbered_path,
        unique_output_path,
    )
except ImportError:  # 직접 실행: python app/main.py
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from app.core.dxf_load_reader import read_load_regions
    from app.core.diagnostic_dxf_writer import write_floorload_diagnostic_dxf
    from app.core.dxf_template_writer import LoadLayerSpec, normalize_hatch_scale, write_all_story_centerline_dxf, write_story_centerline_dxf
    from app.core.dxf_story_layout import LayoutMetadataSelection, select_layout_metadata
    from app.core.floorload_mgt_builder import run_mgt_build_pipeline
    from app.core.load_selection import apply_load_display_names
    from app.core.pdf_load_importer import (
        PdfLoadImportResult,
        detect_floor_load_presence_from_text,
        merge_pdf_mgtx_into_full_mgt,
        run_pdf_load_import,
    )
    from app.core.mgt_parser import (
        FloorLoadTypeSpec,
        Story,
        parse_floorload_type_names_from_text,
        parse_floadtype_specs_from_text,
        parse_mgt_file,
        select_nodes_by_story,
    )
    from app.core.midas_api_client import MidasApiError, MidasGenApiClient
    from app.core.load_parser import parse_load_layer
    from app.core.load_input_policy import infer_distribution
    from app.core.model_floorload_diagnostics import analyze_floorload_model, write_diagnostic_reports
    from app.core.progress import ProgressReporter
    from app.utils.config import AppConfig, load_config, save_config
    from app.utils.logger import setup_logger
    from app.utils.path_utils import (
        ensure_project_output_subdirs,
        output_root_dir,
        project_output_dir,
        project_root,
        safe_filename,
        unique_numbered_path,
        unique_output_path,
    )


def _mgbx_path(path: str | Path) -> Path:
    target = Path(path)
    if target.suffix.lower() != ".mgbx":
        target = target.with_suffix(".mgbx")
    return target


ALL_STORIES_VALUE = "__ALL_STORIES__"
ALL_STORIES_LABEL = "전층"
DXF_NEXT_ACTION_BG = "#FFD966"
DXF_NEXT_ACTION_ACTIVE_BG = "#FFE699"
MODEL_NEXT_ACTION_BG = "#A9D18E"
MODEL_NEXT_ACTION_ACTIVE_BG = "#C6E0B4"


@dataclass(frozen=True)
class BuildPipelineUiResult:
    message: str
    generated_model_path: Path | None = None

    def __str__(self) -> str:
        return self.message


def _format_dxf_validation_summary(regions) -> str:
    total = len(regions or [])
    ok_count = sum(1 for region in regions if region.status in {"OK", "REVIEW"} or str(region.status).startswith("REVIEW_"))
    story_counts = Counter(str(getattr(region.region, "story_name", "") or "") for region in regions)
    recognized_story_count = total - story_counts.get("", 0)
    metadata_used_count = sum(1 for region in regions if bool(getattr(region.region, "layout_metadata_used", False)))
    transform_count = sum(1 for region in regions if bool(getattr(region.region, "transform_applied", False)))
    lines = [
        "DXF 검증 완료:",
        f"- 하중영역: {total}개",
        f"- 입력 가능 후보: {ok_count}개",
        f"- Story 인식: {recognized_story_count}개",
    ]
    for story_name, count in sorted((name, count) for name, count in story_counts.items() if name):
        lines.append(f"- {story_name}: {count}개")
    lines.append(f"- metadata: {'사용됨' if metadata_used_count else '미사용'}")
    if metadata_used_count:
        lines.append(f"- transform_applied: {transform_count}개")
        metadata_paths = sorted(
            {
                str(getattr(region.region, "layout_metadata_path", "") or "")
                for region in regions
                if getattr(region.region, "layout_metadata_path", "")
            }
        )
        if metadata_paths:
            lines.append(f"- metadata 경로: {metadata_paths[0]}")
    return "\n".join(lines)


def _format_region_bbox_for_ui(values) -> str:
    if not values:
        return ""
    return ",".join(f"{float(value):.3f}".rstrip("0").rstrip(".") for value in values)


class FloorLoadAutoApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("MIDAS Floor Load Auto v4")
        self.geometry("1120x780")
        self.minsize(980, 650)
        self.logger = setup_logger()
        self.config_data = load_config()
        self.root_dir = project_root()
        self.data_dir = self.root_dir / "DATA"
        self.data_root = self.data_dir
        self.output_root = output_root_dir(self.data_root)
        self.current_project_dir: Path | None = None
        self.current_project_subdirs: dict[str, Path] = {}
        self._ensure_data_dirs()
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.notebook: ttk.Notebook | None = None
        self.pdf_tab_visible = False

        self.model_path = tk.StringVar()
        self.exported_mgt_path = tk.StringVar()
        self.user_dxf_path = tk.StringVar()
        self.target_model_path = tk.StringVar()
        self.mapping_path = tk.StringVar()
        self.layout_metadata_path = tk.StringVar()
        self.selected_story_name = tk.StringVar()
        self.stories: list[Story] = []
        self.nodes = []
        self.elements = []
        self.loaded_regions = []
        self.diagnostic_issues = []
        self.last_diagnostic_dxf_path: Path | None = None
        self.last_diagnostic_report_path: Path | None = None
        self.selected_pdf_paths: list[Path] = []
        self.pdf_import_result: PdfLoadImportResult | None = None
        self.model_load_items: list[dict] = []
        self.pdf_load_items: list[dict] = []
        self.model_load_vars: dict[str, tk.BooleanVar] = {}
        self.pdf_load_vars: dict[str, tk.BooleanVar] = {}
        self.model_load_all_var = tk.BooleanVar(value=False)
        self.pdf_load_all_var = tk.BooleanVar(value=False)
        self.final_load_items: list[dict] = []
        self.last_generated_dxf_path: Path | None = None
        self.last_generated_model_path: Path | None = None
        self.generated_dxf_path = tk.StringVar(value="")
        self.generated_model_path = tk.StringVar(value="")
        self.dxf_next_action_text_var = tk.StringVar(value="DXF 생성 전에는 열 수 있는 파일이 없습니다.")
        self.model_next_action_text_var = tk.StringVar(value="모델링 파일 생성 전에는 열 수 있는 파일이 없습니다.")
        self.floorload_status_var = tk.StringVar(value="모델/MGT를 먼저 읽어 FLOOR LOAD 존재 여부를 분석하세요.")
        self.pdf_mgtx_path = tk.StringVar()
        self.pdf_merge_output_path = tk.StringVar()
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text_var = tk.StringVar(value="대기 중")
        self.progress_percent_var = tk.StringVar(value="0%")
        self._busy = False
        self._busy_buttons: list[tk.Widget] = []

        self._build_ui()
        self._poll_queue()

    def _ensure_data_dirs(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.output_root = output_root_dir(self.data_root)

    def _guess_project_name(self) -> str:
        candidates = []

        for attr in ("model_path", "exported_mgt_path", "mgt_path", "selected_mgt_path"):
            var = getattr(self, attr, None)
            try:
                value = var.get() if hasattr(var, "get") else str(var or "")
            except Exception:
                value = ""
            if value:
                candidates.append(value)

        for attr in ("selected_pdf_paths", "pdf_files", "pdf_paths"):
            pdf_files = getattr(self, attr, None)
            if pdf_files:
                try:
                    candidates.append(str(pdf_files[0]))
                    break
                except Exception:
                    pass

        for value in candidates:
            try:
                stem = Path(value).stem
                if stem:
                    return stem
            except Exception:
                continue

        return "untitled_project_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    def _ensure_current_project_workspace(self, project_name: str | None = None) -> Path:
        if project_name is None and self.current_project_dir:
            self.current_project_subdirs = ensure_project_output_subdirs(self.current_project_dir)
            return self.current_project_dir

        if project_name is None:
            project_name = self._guess_project_name()

        project_dir = project_output_dir(self.data_root, project_name)
        self.current_project_dir = project_dir
        self.current_project_subdirs = ensure_project_output_subdirs(project_dir)

        if hasattr(self, "project_data_dir_var"):
            try:
                self.project_data_dir_var.set(str(project_dir))
            except Exception:
                pass

        return project_dir

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        notebook = ttk.Notebook(self)
        self.notebook = notebook
        notebook.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.tab_api = ttk.Frame(notebook)
        self.tab_model = ttk.Frame(notebook)
        self.tab_pdf = ttk.Frame(notebook)
        self.tab_dxf = ttk.Frame(notebook)
        self.tab_build = ttk.Frame(notebook)
        self.tab_log = ttk.Frame(notebook)
        notebook.add(self.tab_api, text="1 API 설정")
        notebook.add(self.tab_model, text="2 모델/Story")
        # PDF 하중 입력 탭은 선택 기능이므로 초기에는 표시하지 않는다.
        notebook.add(self.tab_dxf, text="3 DXF 생성/검증")
        notebook.add(self.tab_build, text="4 MGT 입력/저장")
        notebook.add(self.tab_log, text="로그")

        self._build_api_tab()
        self._build_model_tab()
        self._build_pdf_tab()
        self._build_dxf_tab()
        self._build_build_tab()
        self._build_log_tab()
        self._build_progress_status_bar()

    def _build_api_tab(self) -> None:
        f = self.tab_api
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Base URL").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.base_url_var = tk.StringVar(value=self.config_data.base_url)
        ttk.Entry(f, textvariable=self.base_url_var).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Label(f, text="Port(선택)").grid(row=1, column=0, sticky="w", padx=8, pady=8)
        self.port_var = tk.StringVar(value=self.config_data.port)
        ttk.Entry(f, textvariable=self.port_var, width=16).grid(row=1, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(f, text="MAPI Key").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        self.mapi_key_var = tk.StringVar(value=self.config_data.mapi_key)
        ttk.Entry(f, textvariable=self.mapi_key_var, show="*", width=60).grid(row=2, column=1, sticky="ew", padx=8, pady=8)
        ttk.Label(f, text="Timeout(sec)").grid(row=3, column=0, sticky="w", padx=8, pady=8)
        self.timeout_var = tk.IntVar(value=self.config_data.timeout_seconds)
        ttk.Spinbox(f, from_=10, to=600, textvariable=self.timeout_var, width=10).grid(row=3, column=1, sticky="w", padx=8, pady=8)
        self.verify_ssl_var = tk.BooleanVar(value=self.config_data.verify_ssl)
        ttk.Checkbutton(f, text="SSL 인증서 검증", variable=self.verify_ssl_var).grid(row=4, column=1, sticky="w", padx=8, pady=8)
        button_frame = ttk.Frame(f)
        button_frame.grid(row=5, column=1, sticky="w", padx=8, pady=12)
        self._busy_button(button_frame, text="연결 테스트", command=self.test_api).pack(side="left", padx=4)
        ttk.Button(button_frame, text="설정 저장", command=self.save_current_config).pack(side="left", padx=4)
        ttk.Button(button_frame, text="기존 v3 Streamlit 실행", command=self.launch_legacy_v3).pack(side="left", padx=4)
        ttk.Label(
            f,
            text="주의: 원본 .mgb는 직접 덮어쓰지 않습니다. 새 full MGT를 만든 뒤 doc/NEW → IMPORTMXT → SAVEAS 방식으로 저장합니다.",
            foreground="blue",
        ).grid(row=6, column=0, columnspan=2, sticky="w", padx=8, pady=8)

    def _build_model_tab(self) -> None:
        f = self.tab_model
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="모델 파일(.mgb/.mgbx/.mcb)").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.model_path).grid(row=0, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(f, text="찾기", command=self.select_model_file).grid(row=0, column=2, padx=8, pady=8)
        self._busy_button(f, text="API로 열기 + MGT Export + Story 읽기", command=self.open_model_and_export).grid(row=1, column=1, sticky="w", padx=8, pady=8)

        ttk.Label(f, text="디버그/오프라인용 MGT 직접 읽기").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.exported_mgt_path).grid(row=2, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(f, text="MGT 찾기", command=self.select_mgt_file).grid(row=2, column=2, padx=8, pady=8)
        self._busy_button(f, text="선택 MGT에서 Story 읽기", command=self.load_mgt_snapshot).grid(row=3, column=1, sticky="w", padx=8, pady=8)

        ttk.Separator(f).grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text="FLOOR LOAD 자동 분석").grid(row=5, column=0, sticky="nw", padx=8, pady=8)
        self.floorload_status_label = ttk.Label(f, textvariable=self.floorload_status_var, wraplength=820, foreground="blue")
        self.floorload_status_label.grid(row=5, column=1, columnspan=2, sticky="w", padx=8, pady=8)
        floor_button_frame = ttk.Frame(f)
        floor_button_frame.grid(row=6, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        self._busy_button(floor_button_frame, text="FLOOR LOAD 존재 여부 재분석", command=self.recheck_floorload_presence).pack(side="left", padx=4)
        self.open_pdf_tab_button = ttk.Button(floor_button_frame, text="PDF로 하중 입력하기", command=self.open_pdf_tab)
        self.open_pdf_tab_button.pack(side="left", padx=4)
        self.open_pdf_tab_button.state(["disabled"])
        ttk.Label(
            f,
            text="기존 모델에 FLOOR LOAD가 있으면 현재 흐름을 그대로 유지합니다. FLOOR LOAD가 없거나 사용자가 원할 때만 PDF 입력 탭을 열어 사용합니다.",
            foreground="gray",
            wraplength=900,
        ).grid(row=7, column=1, columnspan=2, sticky="w", padx=8, pady=(0, 8))

        ttk.Label(f, text="Story 목록").grid(row=8, column=0, sticky="nw", padx=8, pady=8)
        self.story_tree = ttk.Treeview(f, columns=("name", "elevation", "height"), show="headings", height=13)
        self.story_tree.heading("name", text="Story")
        self.story_tree.heading("elevation", text="Elevation")
        self.story_tree.heading("height", text="Height")
        self.story_tree.column("name", width=140, anchor="center")
        self.story_tree.column("elevation", width=120, anchor="e")
        self.story_tree.column("height", width=120, anchor="e")
        self.story_tree.grid(row=8, column=1, sticky="nsew", padx=8, pady=8)
        f.rowconfigure(8, weight=1)
        self.story_tree.bind("<<TreeviewSelect>>", self.on_story_select)
        diag_button_frame = ttk.Frame(f)
        diag_button_frame.grid(row=9, column=1, columnspan=2, sticky="w", padx=8, pady=4)
        self._busy_button(diag_button_frame, text="모델링 FLOORLOAD 입력 가능성 분석", command=self.run_floorload_diagnostics).pack(side="left", padx=4)
        self.open_diag_dxf_button = ttk.Button(diag_button_frame, text="진단 DXF 열기", command=self.open_last_diagnostic_dxf)
        self.open_diag_dxf_button.pack(side="left", padx=4)
        self.open_diag_dxf_button.state(["disabled"])
        self.open_diag_report_button = ttk.Button(diag_button_frame, text="진단 보고서 열기", command=self.open_last_diagnostic_report)
        self.open_diag_report_button.pack(side="left", padx=4)
        self.open_diag_report_button.state(["disabled"])
        self.diagnostic_tree = ttk.Treeview(
            f,
            columns=("story", "severity", "type", "xy", "nodes", "elements", "message", "action"),
            show="headings",
            height=7,
        )
        for col, txt, width in (
            ("story", "Story", 90),
            ("severity", "심각도", 80),
            ("type", "문제유형", 140),
            ("xy", "위치 X,Y", 130),
            ("nodes", "Node", 120),
            ("elements", "Element", 120),
            ("message", "추정 원인", 260),
            ("action", "수정 안내", 260),
        ):
            self.diagnostic_tree.heading(col, text=txt)
            self.diagnostic_tree.column(col, width=width)
        self.diagnostic_tree.grid(row=10, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        f.rowconfigure(10, weight=1)

    def _build_pdf_tab(self) -> None:
        f = self.tab_pdf
        f.columnconfigure(1, weight=1)
        ttk.Label(
            f,
            text="이 탭은 선택 기능입니다. 2번 탭에서 FLOOR LOAD가 없다고 판단되거나 사용자가 PDF 기반 하중 타입을 새로 만들고 싶을 때만 사용하세요.",
            foreground="blue",
            wraplength=940,
        ).grid(row=0, column=0, columnspan=3, sticky="w", padx=8, pady=8)

        ttk.Label(f, text="구조계산서 PDF").grid(row=1, column=0, sticky="nw", padx=8, pady=8)
        self.pdf_listbox = tk.Listbox(f, height=5)
        self.pdf_listbox.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
        pdf_button_frame = ttk.Frame(f)
        pdf_button_frame.grid(row=1, column=2, sticky="n", padx=8, pady=8)
        ttk.Button(pdf_button_frame, text="PDF 추가", command=self.select_pdf_files).pack(fill="x", pady=2)
        ttk.Button(pdf_button_frame, text="목록 비우기", command=self.clear_pdf_files).pack(fill="x", pady=2)
        f.rowconfigure(1, weight=0)

        self._busy_button(f, text="PDF 분석 및 MGTX 생성", command=self.run_pdf_analysis).grid(row=2, column=1, sticky="w", padx=8, pady=8)
        ttk.Button(f, text="PDF 하중목록 전체 선택", command=self.apply_pdf_loads_to_dxf_layers).grid(row=2, column=1, sticky="e", padx=8, pady=8)

        ttk.Label(f, text="생성 MGTX").grid(row=3, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.pdf_mgtx_path).grid(row=3, column=1, sticky="ew", padx=8, pady=8)
        self._busy_button(f, text="PDF MGTX를 현재 MGT에 병합", command=self.merge_pdf_mgtx_to_current_mgt).grid(row=3, column=2, sticky="ew", padx=8, pady=8)

        ttk.Label(f, text="병합 출력 MGT").grid(row=4, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.pdf_merge_output_path).grid(row=4, column=1, sticky="ew", padx=8, pady=8)

        self.pdf_summary_label = ttk.Label(f, text="PDF 분석 결과: -", foreground="blue", wraplength=940)
        self.pdf_summary_label.grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=8)

        ttk.Label(f, text="PDF 하중목록").grid(row=6, column=0, sticky="nw", padx=8, pady=(0, 4))
        self.pdf_load_lines_listbox = tk.Listbox(f, height=4)
        self.pdf_load_lines_listbox.grid(row=6, column=1, columnspan=2, sticky="ew", padx=8, pady=(0, 8))

        self.pdf_tree = ttk.Treeview(f, columns=("status", "type", "case", "value", "source", "reason"), show="headings", height=13)
        for col, txt, width in (
            ("status", "상태", 90),
            ("type", "Floor Load Type", 210),
            ("case", "Load Case", 120),
            ("value", "하중값", 90),
            ("source", "PDF/Page", 180),
            ("reason", "검토/제외 사유", 340),
        ):
            self.pdf_tree.heading(col, text=txt)
            self.pdf_tree.column(col, width=width)
        self.pdf_tree.grid(row=7, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        f.rowconfigure(7, weight=1)

    def _build_dxf_tab(self) -> None:
        f = self.tab_dxf
        for col in range(3):
            f.columnconfigure(col, weight=1)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Story tolerance").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.story_tol_var = tk.DoubleVar(value=self.config_data.story_tolerance)
        ttk.Entry(f, textvariable=self.story_tol_var, width=12).grid(row=0, column=1, sticky="w", padx=8, pady=8)
        hatch_scale_frame = ttk.Frame(f)
        hatch_scale_frame.grid(row=0, column=2, sticky="e", padx=8, pady=8)
        ttk.Label(hatch_scale_frame, text="CAD 기본 HATCH 축척").pack(side="left", padx=(0, 4))
        self.default_hatch_scale_var = tk.StringVar(value=str(self.config_data.default_hatch_scale))
        ttk.Entry(hatch_scale_frame, textvariable=self.default_hatch_scale_var, width=10).pack(side="left")

        ttk.Label(
            f,
            text="모델링 입력 하중목록과 PDF 하중목록에서 사용할 하중을 체크하면 오른쪽 최종 적용 하중목록에 실시간 반영됩니다. 최종 적용 하중목록이 DXF 템플릿의 LOAD 레이어로 생성됩니다.",
            foreground="blue",
            wraplength=1000,
        ).grid(row=1, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 0))

        load_select_frame = ttk.Frame(f)
        load_select_frame.grid(row=2, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        for col in range(3):
            load_select_frame.columnconfigure(col, weight=1)
        load_select_frame.rowconfigure(0, weight=1)

        self.model_load_check_frame = self._create_scrollable_checklist(
            load_select_frame,
            "모델링 입력 하중목록",
            0,
            self.model_load_all_var,
            self._toggle_all_model_loads,
        )
        self.pdf_load_check_frame = self._create_scrollable_checklist(
            load_select_frame,
            "PDF 하중목록",
            1,
            self.pdf_load_all_var,
            self._toggle_all_pdf_loads,
        )

        final_frame = ttk.LabelFrame(load_select_frame, text="최종 적용 하중목록")
        final_frame.grid(row=0, column=2, sticky="nsew", padx=4, pady=2)
        final_frame.columnconfigure(0, weight=1)
        final_frame.rowconfigure(0, weight=1)
        self.final_load_tree = ttk.Treeview(final_frame, columns=("display", "source", "dl", "ll"), show="headings", height=12)
        self.final_load_tree.heading("display", text="적용명")
        self.final_load_tree.heading("source", text="출처")
        self.final_load_tree.heading("dl", text="DL")
        self.final_load_tree.heading("ll", text="LL")
        self.final_load_tree.column("display", width=150, minwidth=100, anchor="w", stretch=True)
        self.final_load_tree.column("source", width=55, minwidth=50, anchor="center", stretch=False)
        self.final_load_tree.column("dl", width=55, minwidth=50, anchor="e", stretch=False)
        self.final_load_tree.column("ll", width=55, minwidth=50, anchor="e", stretch=False)
        self.final_load_tree.grid(row=0, column=0, sticky="nsew")
        final_scroll = ttk.Scrollbar(final_frame, orient="vertical", command=self.final_load_tree.yview)
        final_scroll.grid(row=0, column=1, sticky="ns")
        self.final_load_tree.configure(yscrollcommand=final_scroll.set)
        self.final_load_tree.bind("<Configure>", self._resize_final_load_columns)

        dxf_button_frame = ttk.Frame(f)
        dxf_button_frame.grid(row=3, column=0, columnspan=3, sticky="w", padx=8, pady=8)
        ttk.Label(dxf_button_frame, text="DXF 생성 Story").pack(side="left", padx=(0, 4))
        self.dxf_story_combo = ttk.Combobox(
            dxf_button_frame,
            textvariable=self.selected_story_name,
            state="readonly",
            width=22,
        )
        self.dxf_story_combo.pack(side="left", padx=(0, 8))
        self.dxf_story_combo.bind("<<ComboboxSelected>>", self._on_dxf_story_combo_selected)
        self._busy_button(dxf_button_frame, text="선택 Story center line DXF 생성", command=self.create_dxf_template).pack(side="left", padx=(0, 8))
        self.open_generated_dxf_button = tk.Button(
            dxf_button_frame,
            text="생성 DXF 파일 열기",
            command=self.open_last_generated_dxf,
            state="disabled",
            padx=8,
            pady=2,
        )
        self.open_generated_dxf_button.pack(side="left")
        self._dxf_open_button_defaults = self._capture_button_visual_defaults(self.open_generated_dxf_button)
        ttk.Label(
            dxf_button_frame,
            textvariable=self.dxf_next_action_text_var,
            foreground="#805000",
            wraplength=440,
        ).pack(side="left", padx=(8, 0))
        ttk.Separator(f).grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(f, text="사용자 작성 DXF").grid(row=5, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.user_dxf_path).grid(row=5, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(f, text="찾기", command=self.select_user_dxf).grid(row=5, column=2, padx=8, pady=8)
        ttk.Label(f, text="전층 DXF layout metadata").grid(row=6, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.layout_metadata_path).grid(row=6, column=1, sticky="ew", padx=8, pady=8)
        metadata_button_frame = ttk.Frame(f)
        metadata_button_frame.grid(row=6, column=2, sticky="ew", padx=8, pady=8)
        ttk.Button(metadata_button_frame, text="선택", command=self.select_layout_metadata_file).pack(side="left", padx=(0, 4))
        ttk.Button(metadata_button_frame, text="자동 찾기", command=self.auto_find_layout_metadata).pack(side="left")
        self._busy_button(f, text="DXF 검증", command=self.validate_user_dxf).grid(row=7, column=0, sticky="w", padx=8, pady=8)
        self.dxf_tree = ttk.Treeview(
            f,
            columns=(
                "status",
                "story",
                "metadata",
                "transform",
                "source",
                "layer",
                "pattern",
                "solid",
                "mode",
                "mode_source",
                "dir",
                "load",
                "dl",
                "ll",
                "area",
                "placed_bbox",
                "model_bbox",
                "source_id",
                "warnings",
            ),
            show="headings",
            height=12,
        )
        for col, txt, width in (
            ("status", "상태", 120), ("source", "객체", 80), ("layer", "레이어", 220), ("load", "하중명", 140),
            ("dl", "DL", 80), ("ll", "LL", 80), ("area", "면적", 100), ("warnings", "경고", 300),
        ):
            self.dxf_tree.heading(col, text=txt)
            self.dxf_tree.column(col, width=width)
        self.dxf_tree.heading("story", text="Story")
        self.dxf_tree.column("story", width=90)
        self.dxf_tree.heading("metadata", text="metadata")
        self.dxf_tree.column("metadata", width=85, anchor="center")
        self.dxf_tree.heading("transform", text="transform")
        self.dxf_tree.column("transform", width=85, anchor="center")
        for col, txt, width in (
            ("pattern", "HATCH", 95),
            ("solid", "SOLID", 60),
            ("mode", "입력방식", 110),
            ("mode_source", "판정근거", 150),
            ("dir", "방향선", 70),
        ):
            self.dxf_tree.heading(col, text=txt)
            self.dxf_tree.column(col, width=width)
        self.dxf_tree.heading("placed_bbox", text="placed_bbox")
        self.dxf_tree.column("placed_bbox", width=165)
        self.dxf_tree.heading("model_bbox", text="model_bbox")
        self.dxf_tree.column("model_bbox", width=165)
        self.dxf_tree.heading("source_id", text="source_id")
        self.dxf_tree.column("source_id", width=110)
        self.dxf_tree.grid(row=8, column=0, columnspan=3, sticky="nsew", padx=8, pady=8)
        f.rowconfigure(2, weight=2)
        f.rowconfigure(8, weight=1)
        self._refresh_model_load_checklist()
        self._refresh_pdf_load_checklist()
        self._refresh_final_load_tree()

    def _create_scrollable_checklist(
        self,
        parent: tk.Widget,
        title: str,
        column: int,
        all_var: tk.BooleanVar | None = None,
        all_command=None,
    ) -> ttk.Frame:
        panel = ttk.LabelFrame(parent, text=title)
        panel.grid(row=0, column=column, sticky="nsew", padx=4, pady=2)
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(1, weight=1)
        if all_var is not None and all_command is not None:
            tk.Checkbutton(
                panel,
                text="전체선택",
                variable=all_var,
                command=all_command,
                anchor="w",
                padx=1,
                pady=0,
            ).grid(row=0, column=0, columnspan=2, sticky="w", padx=3, pady=(2, 1))
        canvas = tk.Canvas(panel, height=260, highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window_id, width=event.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=1, column=0, sticky="nsew")
        scrollbar.grid(row=1, column=1, sticky="ns")
        return inner

    def _build_build_tab(self) -> None:
        f = self.tab_build
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Snap tolerance").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        self.snap_tol_var = tk.DoubleVar(value=self.config_data.snap_tolerance)
        ttk.Entry(f, textvariable=self.snap_tol_var, width=12).grid(row=0, column=1, sticky="w", padx=8, pady=8)
        self.include_zero_var = tk.BooleanVar(value=self.config_data.include_zero_load)
        ttk.Checkbutton(f, text="0 값도 명시 입력", variable=self.include_zero_var).grid(row=1, column=1, sticky="w", padx=8, pady=8)
        ttk.Label(f, text="결과 .mgbx 저장 경로").grid(row=2, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(f, textvariable=self.target_model_path).grid(row=2, column=1, sticky="ew", padx=8, pady=8)
        ttk.Button(f, text="저장 위치", command=self.select_target_model).grid(row=2, column=2, padx=8, pady=8)
        build_button_frame = ttk.Frame(f)
        build_button_frame.grid(row=3, column=1, columnspan=2, sticky="w", padx=8, pady=12)
        self._busy_button(build_button_frame, text="full MGT 생성 + 새 모델 import/save as", command=self.build_and_import).pack(side="left", padx=(0, 8))
        self._busy_button(build_button_frame, text="API import 없이 full MGT만 생성", command=self.build_mgt_only).pack(side="left", padx=(0, 8))
        self.open_generated_model_button = tk.Button(
            build_button_frame,
            text="생성 모델링 파일 열기",
            command=self.open_generated_model_file,
            state="disabled",
            padx=8,
            pady=2,
        )
        self.open_generated_model_button.pack(side="left")
        self._model_open_button_defaults = self._capture_button_visual_defaults(self.open_generated_model_button)
        ttk.Label(f, textvariable=self.model_next_action_text_var, foreground="#2f6b2f", wraplength=900).grid(
            row=4,
            column=0,
            columnspan=3,
            sticky="w",
            padx=8,
            pady=(0, 4),
        )
        self.result_label = ttk.Label(f, text="결과 파일: -", foreground="blue", wraplength=900)
        self.result_label.grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=8)

    def _build_log_tab(self) -> None:
        self.log_text = tk.Text(self.tab_log, height=25)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)

    def _build_progress_status_bar(self) -> None:
        frame = ttk.Frame(self)
        frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 8))
        frame.columnconfigure(2, weight=1)
        ttk.Label(frame, text="상태:").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Label(frame, textvariable=self.progress_text_var, width=28).grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.progress_bar = ttk.Progressbar(
            frame,
            variable=self.progress_var,
            maximum=100.0,
            mode="determinate",
        )
        self.progress_bar.grid(row=0, column=2, sticky="ew", padx=(0, 8))
        ttk.Label(frame, textvariable=self.progress_percent_var, width=6, anchor="e").grid(row=0, column=3, sticky="e")

    def _busy_button(self, parent, **kwargs):
        button = ttk.Button(parent, **kwargs)
        self._register_busy_button(button)
        return button

    def _register_busy_button(self, button):
        self._busy_buttons.append(button)
        return button

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        self._busy = bool(busy)
        for button in self._busy_buttons:
            try:
                button.state(["disabled"] if busy else ["!disabled"])
            except Exception:
                try:
                    button.configure(state="disabled" if busy else "normal")
                except Exception:
                    pass
        if message:
            self.progress_text_var.set(message)

    def _capture_button_visual_defaults(self, button) -> dict[str, object]:
        defaults: dict[str, object] = {}
        for option in ("background", "activebackground", "foreground", "relief"):
            try:
                defaults[option] = button.cget(option)
            except Exception:
                pass
        return defaults

    def _set_button_enabled(self, button, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        try:
            state_method = getattr(button, "state")
        except Exception:
            state_method = None
        if callable(state_method):
            try:
                state_method(["!disabled"] if enabled else ["disabled"])
                return
            except Exception:
                pass
        try:
            button.configure(state=state)
        except Exception:
            pass

    def _configure_next_action_button(
        self,
        button,
        *,
        enabled: bool,
        text: str,
        defaults: dict[str, object] | None = None,
        background: str | None = None,
        activebackground: str | None = None,
    ) -> None:
        try:
            button.configure(text=text)
        except Exception:
            pass
        self._set_button_enabled(button, enabled)
        if background:
            for option, value in (("background", background), ("activebackground", activebackground or background), ("relief", "raised")):
                try:
                    button.configure(**{option: value})
                except Exception:
                    pass
            return
        for option, value in (defaults or {}).items():
            try:
                button.configure(**{option: value})
            except Exception:
                pass

    def _short_ui_message(self, message: str, *, limit: int = 220) -> str:
        text = " ".join(str(message or "").split())
        if len(text) <= limit:
            return text
        return text[: limit - 3].rstrip() + "..."

    def _reset_dxf_next_action_state(self, message: str = "DXF 생성 중입니다. 완료 후 파일 열기 버튼이 활성화됩니다.") -> None:
        self.last_generated_dxf_path = None
        if hasattr(self, "generated_dxf_path"):
            self.generated_dxf_path.set("")
        if hasattr(self, "open_generated_dxf_button"):
            self._configure_next_action_button(
                self.open_generated_dxf_button,
                enabled=False,
                text="생성 DXF 파일 열기",
                defaults=getattr(self, "_dxf_open_button_defaults", None),
            )
        if hasattr(self, "dxf_next_action_text_var"):
            self.dxf_next_action_text_var.set(message)

    def _mark_dxf_generated_success(self, path: str | Path) -> None:
        generated_path = Path(path)
        self.last_generated_dxf_path = generated_path
        if hasattr(self, "generated_dxf_path"):
            self.generated_dxf_path.set(str(generated_path))
        if hasattr(self, "open_generated_dxf_button"):
            self._configure_next_action_button(
                self.open_generated_dxf_button,
                enabled=True,
                text="생성 DXF 파일 열기 >>",
                defaults=getattr(self, "_dxf_open_button_defaults", None),
                background=DXF_NEXT_ACTION_BG,
                activebackground=DXF_NEXT_ACTION_ACTIVE_BG,
            )
        if hasattr(self, "dxf_next_action_text_var"):
            self.dxf_next_action_text_var.set("DXF 생성 완료. 다음 단계: 생성 DXF 파일 열기를 눌러 CAD에서 하중 위치를 작성하세요.")

    def _mark_dxf_generated_failed(self, message: str = "") -> None:
        text = "DXF 생성 실패. 로그를 확인하세요."
        if message:
            text = f"DXF 생성 실패: {self._short_ui_message(message)}"
        self._reset_dxf_next_action_state(text)

    def _reset_model_next_action_state(self, message: str = "모델링 파일 생성 중입니다. 완료 후 파일 열기 버튼이 활성화됩니다.") -> None:
        self.last_generated_model_path = None
        if hasattr(self, "generated_model_path"):
            self.generated_model_path.set("")
        if hasattr(self, "open_generated_model_button"):
            self._configure_next_action_button(
                self.open_generated_model_button,
                enabled=False,
                text="생성 모델링 파일 열기",
                defaults=getattr(self, "_model_open_button_defaults", None),
            )
        if hasattr(self, "model_next_action_text_var"):
            self.model_next_action_text_var.set(message)

    def _mark_model_generated_success(self, path: str | Path) -> None:
        generated_path = Path(path)
        self.last_generated_model_path = generated_path
        if hasattr(self, "generated_model_path"):
            self.generated_model_path.set(str(generated_path))
        if hasattr(self, "target_model_path"):
            self.target_model_path.set(str(generated_path))
        if hasattr(self, "open_generated_model_button"):
            self._configure_next_action_button(
                self.open_generated_model_button,
                enabled=True,
                text="생성 모델링 파일 열기 >>",
                defaults=getattr(self, "_model_open_button_defaults", None),
                background=MODEL_NEXT_ACTION_BG,
                activebackground=MODEL_NEXT_ACTION_ACTIVE_BG,
            )
        if hasattr(self, "model_next_action_text_var"):
            self.model_next_action_text_var.set("모델링 파일 생성 완료. 생성 모델링 파일 열기를 눌러 결과 모델을 확인하세요.")

    def _mark_model_generated_failed(self, message: str = "") -> None:
        text = "모델링 파일 생성 실패. 로그를 확인하세요."
        if message:
            text = f"모델링 파일 생성 실패: {self._short_ui_message(message)}"
        self._reset_model_next_action_state(text)

    def _mark_model_not_generated(self, message: str = "모델링 파일은 생성되지 않았습니다.") -> None:
        self._reset_model_next_action_state(message)

    def _set_progress(self, percent: float, message: str = "") -> None:
        try:
            value = max(0.0, min(100.0, float(percent)))
        except Exception:
            value = 0.0
        self.progress_var.set(value)
        self.progress_percent_var.set(f"{value:.0f}%")
        if message:
            self.progress_text_var.set(message)
        try:
            self.update_idletasks()
        except Exception:
            pass

    def _start_progress(self, message: str) -> None:
        self._set_progress(0.0, message)

    def _finish_progress(self, message: str = "완료") -> None:
        self._set_progress(100.0, message)

    def _error_progress(self, message: str = "오류") -> None:
        self.progress_text_var.set(message)
        try:
            self.update_idletasks()
        except Exception:
            pass

    # ---------------------------------------------------------------- actions
    def _client(self) -> MidasGenApiClient:
        cfg = self._current_config()
        return MidasGenApiClient(cfg.resolved_base_url, cfg.mapi_key, timeout_seconds=cfg.timeout_seconds, verify_ssl=cfg.verify_ssl, logger=self.logger)

    def _current_config(self) -> AppConfig:
        return AppConfig(
            base_url=self.base_url_var.get(),
            port=self.port_var.get(),
            mapi_key=self.mapi_key_var.get(),
            timeout_seconds=int(self.timeout_var.get()),
            verify_ssl=bool(self.verify_ssl_var.get()),
            story_tolerance=float(self.story_tol_var.get() if hasattr(self, "story_tol_var") else self.config_data.story_tolerance),
            default_hatch_scale=normalize_hatch_scale(
                self.default_hatch_scale_var.get() if hasattr(self, "default_hatch_scale_var") else self.config_data.default_hatch_scale
            ),
            snap_tolerance=float(self.snap_tol_var.get() if hasattr(self, "snap_tol_var") else self.config_data.snap_tolerance),
            include_zero_load=bool(self.include_zero_var.get() if hasattr(self, "include_zero_var") else self.config_data.include_zero_load),
        )

    def save_current_config(self) -> None:
        path = save_config(self._current_config())
        self.log(f"설정을 저장했습니다: {path}")

    def test_api(self) -> None:
        self.run_worker("API 연결 테스트", lambda: self._client().health_check())

    def select_model_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("MIDAS model", "*.mgb *.mgbx *.mcb"), ("All files", "*.*")])
        if path:
            self.model_path.set(path)
            self._ensure_current_project_workspace(Path(path).stem)
            default = self.current_project_subdirs["models"] / f"{Path(path).stem}_floorload_added.mgbx"
            self.target_model_path.set(str(default))

    def select_mgt_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("MIDAS text", "*.mgt *.mgtx *.mct"), ("All files", "*.*")])
        if path:
            self.exported_mgt_path.set(path)
            self._ensure_current_project_workspace(Path(path).stem)

    def select_pdf_files(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf"), ("All files", "*.*")])
        if not paths:
            return
        for path in paths:
            p = Path(path)
            if p not in self.selected_pdf_paths:
                self.selected_pdf_paths.append(p)
        if not self.current_project_dir:
            self._ensure_current_project_workspace()
        self._refresh_pdf_listbox()

    def clear_pdf_files(self) -> None:
        self.selected_pdf_paths.clear()
        self.pdf_import_result = None
        self.pdf_mgtx_path.set("")
        self.pdf_load_items = []
        self.pdf_load_vars = {}
        self._refresh_pdf_listbox()
        self._refresh_pdf_tree([])
        self._refresh_pdf_load_lines_listbox()
        self._refresh_pdf_load_checklist()
        self._sync_final_load_list()
        self.pdf_summary_label.configure(text="PDF 분석 결과: -")

    def open_pdf_tab(self) -> None:
        self._ensure_pdf_tab_visible(select=True)

    def recheck_floorload_presence(self) -> None:
        path = self.exported_mgt_path.get().strip()
        if not path:
            messagebox.showwarning("MGT 없음", "먼저 모델을 API로 열어 MGT를 export하거나 MGT 파일을 직접 읽어 주세요.")
            return

        def job(progress):
            progress.update(15.0, "MGT 파일 읽는 중")
            _stories, _nodes, _elements, text = parse_mgt_file(path)
            progress.update(55.0, "FLOOR LOAD 존재 여부 분석 중")
            presence = detect_floor_load_presence_from_text(text)
            progress.update(80.0, "하중 목록 갱신 중")
            self.queue.put(("floorload_status", presence))
            self.queue.put(("model_load_items", self._model_specs_from_mgt_text(text)))
            return presence.message

        self.run_worker("FLOOR LOAD 재분석", job)

    def run_pdf_analysis(self) -> None:
        if not self.selected_pdf_paths:
            messagebox.showwarning("PDF 없음", "분석할 구조계산서 PDF를 먼저 추가해 주세요.")
            return

        def job(progress):
            progress.update(10.0, "PDF 분석 작업 폴더 준비 중")
            project_dir = self._ensure_current_project_workspace()
            model_stem = safe_filename(project_dir.name)
            pdf_jobs_dir = self.current_project_subdirs["pdf_jobs"]
            progress.update(25.0, "PDF 하중 분석 중")
            result = run_pdf_load_import(
                pdf_paths=self.selected_pdf_paths,
                root_dir=self.root_dir,
                output_root=pdf_jobs_dir,
                job_name=f"{model_stem}_pdf_load",
            )
            progress.update(80.0, "PDF 분석 결과 정리 중")
            self.pdf_import_result = result
            if result.mgtx_path:
                self.pdf_mgtx_path.set(str(result.mgtx_path))
                default_merge = self.current_project_subdirs["mgt"] / f"{model_stem}_pdf_load_types_merged.mgt"
                self.pdf_merge_output_path.set(str(default_merge))
            self.queue.put(("pdf_rows", result))
            progress.update(90.0, "PDF 결과 UI 반영 중")
            valid_count = len(result.valid_rows)
            error_count = len(result.error_rows)
            return f"PDF 분석 완료: 유효 {valid_count}개, 검토/제외 {error_count}개, MGTX={result.mgtx_path or '생성 안 됨'}"

        self.run_worker("PDF 하중 분석", job)

    def apply_pdf_loads_to_dxf_layers(self) -> None:
        if not self.pdf_load_items:
            messagebox.showwarning("적용 대상 없음", "먼저 PDF 분석을 실행하고 유효한 Floor Load Type을 생성해 주세요.")
            return
        self.pdf_load_all_var.set(True)
        self._toggle_all_pdf_loads()
        messagebox.showinfo("PDF 하중목록 선택", "PDF 하중목록을 최종 적용 하중목록에 선택했습니다.")
        self._ensure_pdf_tab_visible(select=False)

    def merge_pdf_mgtx_to_current_mgt(self) -> None:
        source_mgt = self.exported_mgt_path.get().strip()
        pdf_mgtx = self.pdf_mgtx_path.get().strip()
        output_mgt = self.pdf_merge_output_path.get().strip()
        if not output_mgt:
            project_dir = self._ensure_current_project_workspace()
            model_stem = safe_filename(project_dir.name)
            output_mgt = str(self.current_project_subdirs["mgt"] / f"{model_stem}_pdf_load_types_merged.mgt")
            self.pdf_merge_output_path.set(output_mgt)
        if not source_mgt:
            messagebox.showwarning("MGT 없음", "먼저 모델 MGT를 export하거나 직접 읽어 주세요.")
            return
        if not pdf_mgtx:
            messagebox.showwarning("PDF MGTX 없음", "먼저 PDF 분석 및 MGTX 생성을 실행해 주세요.")
            return
        if not output_mgt:
            messagebox.showwarning("출력 경로 없음", "병합 출력 MGT 경로가 비어 있습니다.")
            return

        def job(progress):
            progress.update(15.0, "PDF MGTX 병합 중")
            result = merge_pdf_mgtx_into_full_mgt(
                source_mgt_path=source_mgt,
                pdf_mgtx_path=pdf_mgtx,
                output_mgt_path=output_mgt,
                collision_mode="skip_existing",
            )
            progress.update(60.0, "병합 MGT 다시 읽는 중")
            self.exported_mgt_path.set(str(result.output_mgt_path))
            _stories, _nodes, _elements, text = parse_mgt_file(result.output_mgt_path)
            progress.update(80.0, "병합 결과 분석 중")
            presence = detect_floor_load_presence_from_text(text)
            self.queue.put(("floorload_status", presence))
            self.queue.put(("model_load_items", self._model_specs_from_mgt_text(text)))
            return (
                f"PDF 하중 타입 병합 완료: {result.output_mgt_path}\n"
                f"추가 STLDCASE {result.added_stldcase_count}개, 추가 FLOADTYPE {result.added_floadtype_count}개, "
                f"중복 skip FLOADTYPE {len(result.skipped_floadtype_names)}개"
            )

        self.run_worker("PDF MGTX 병합", job)

    def select_user_dxf(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("DXF", "*.dxf"), ("All files", "*.*")])
        if path:
            self.user_dxf_path.set(path)

    def select_mapping_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Mapping", "*.json *.csv"), ("All files", "*.*")])
        if path:
            self.mapping_path.set(path)

    def select_layout_metadata_file(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Layout metadata", "*.layout_metadata.json *.json"), ("All files", "*.*")])
        if path:
            self.layout_metadata_path.set(path)

    def auto_find_layout_metadata(self) -> None:
        dxf = self.user_dxf_path.get().strip()
        if not dxf:
            messagebox.showwarning("DXF 선택", "먼저 사용자 작성 DXF 파일을 선택해 주세요.")
            return
        selected = self._resolve_layout_metadata_for_dxf(dxf, allow_prompt=True)
        if selected:
            messagebox.showinfo("layout metadata", f"layout metadata를 선택했습니다.\n\n{selected}")
        else:
            messagebox.showinfo("layout metadata", "자동으로 선택할 layout metadata가 없습니다. 단일층 DXF라면 그대로 진행해도 됩니다.")

    def select_target_model(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".mgbx",
            filetypes=[("MIDAS Gen NX Binary", "*.mgbx"), ("MIDAS Gen Binary", "*.mgb"), ("All files", "*.*")],
        )
        if path:
            self.target_model_path.set(str(_mgbx_path(path)))

    def open_model_and_export(self) -> None:
        model = self.model_path.get().strip()
        if not model:
            messagebox.showwarning("모델 선택", "모델 파일을 먼저 선택해 주세요.")
            return

        def job(progress):
            progress.update(10.0, "MIDAS API 클라이언트 준비 중")
            client = self._client()
            progress.update(25.0, "모델 열기 중")
            client.open_project(model)
            progress.update(45.0, "MGT Export 준비 중")
            self._ensure_current_project_workspace(Path(model).stem)
            out = self.current_project_subdirs["mgt"] / f"{Path(model).stem}_exported.mgt"
            progress.update(60.0, "MGT Export 요청 중")
            client.export_mgt(out)
            progress.update(75.0, "MGT 파일 파싱 중")
            self.exported_mgt_path.set(str(out))
            self._load_mgt_snapshot_impl(out, progress=progress)
            return f"모델 열기 및 MGT export 완료: {out}"

        self.run_worker("모델 열기/MGT Export", job)

    def load_mgt_snapshot(self) -> None:
        path = self.exported_mgt_path.get().strip()
        if not path:
            messagebox.showwarning("MGT 선택", "MGT/MGTX 파일을 선택해 주세요.")
            return
        self.run_worker("MGT 읽기", lambda progress: self._load_mgt_snapshot_impl(Path(path), progress=progress))

    def _load_mgt_snapshot_impl(self, path: str | Path, progress: ProgressReporter | None = None):
        if progress:
            progress.update(15.0, "작업 폴더 준비 중")
        if self.current_project_dir:
            self._ensure_current_project_workspace()
        else:
            self._ensure_current_project_workspace(Path(path).stem)
        if progress:
            progress.update(35.0, "MGT 파일 읽는 중")
        stories, nodes, elements, mgt_text = parse_mgt_file(path)
        if not stories:
            raise RuntimeError("Story 정보가 없습니다. MGT의 *STORY 블록 또는 API STOR 데이터를 확인해 주세요.")
        if progress:
            progress.update(70.0, "Story/Node/Element 반영 중")
        self.stories = stories
        self.nodes = nodes
        self.elements = elements
        self.queue.put(("stories", stories))
        if progress:
            progress.update(85.0, "FLOOR LOAD 존재 여부 분석 중")
        self.queue.put(("floorload_status", detect_floor_load_presence_from_text(mgt_text)))
        self.queue.put(("model_load_items", self._model_specs_from_mgt_text(mgt_text)))
        return f"Story {len(stories)}개, Node {len(nodes)}개, Element {len(elements)}개를 읽었습니다."

    def on_story_select(self, _event=None) -> None:
        sel = self.story_tree.selection()
        if not sel:
            return
        values = self.story_tree.item(sel[0], "values")
        if values:
            self.selected_story_name.set(str(values[0]))
            self.log(f"Story 선택: {values[0]}")

    def create_dxf_template(self) -> None:
        story_mode, story = self._selected_dxf_story_mode()
        if story_mode != ALL_STORIES_VALUE and not story:
            messagebox.showwarning("Story 선택", "Story를 먼저 선택해 주세요.")
            return
        if not self.nodes or not self.elements:
            messagebox.showwarning("모델 데이터 없음", "MGT export 또는 MGT 직접 읽기를 먼저 실행해 주세요.")
            return
        specs = self._load_layer_specs()
        if not specs:
            messagebox.showwarning(
                "최종 적용 하중목록 없음",
                "최종 적용 하중목록이 비어 있습니다. 모델링 입력 하중목록 또는 PDF 하중목록에서 적용할 하중을 체크해 주세요.",
            )
            return
        self._reset_dxf_next_action_state()
        default_hatch_scale = normalize_hatch_scale(
            self.default_hatch_scale_var.get() if hasattr(self, "default_hatch_scale_var") else self.config_data.default_hatch_scale
        )

        def job(progress):
            progress.update(10.0, "DXF 생성 작업 폴더 준비 중")
            model_name = Path(self.model_path.get() or self.exported_mgt_path.get() or "model").stem
            self._ensure_current_project_workspace()
            out_dir = self.current_project_subdirs["dxf_templates"]
            test_path = out_dir / ".write_test.tmp"
            try:
                progress.update(20.0, "DXF 출력 권한 확인 중")
                test_path.write_text("test", encoding="utf-8")
                if test_path.exists():
                    test_path.unlink()
            except PermissionError as exc:
                raise PermissionError(
                    "DXF 출력 폴더에 쓰기 권한이 없습니다. "
                    "프로그램 폴더를 관리자 권한이 필요한 위치가 아닌 바탕화면/문서/일반 작업 폴더로 옮긴 뒤 다시 실행해 주세요.\n"
                    f"출력 폴더: {out_dir}"
                ) from exc

            story_part = "ALL_STORIES" if story_mode == ALL_STORIES_VALUE else story.name
            base_out = out_dir / f"{safe_filename(model_name)}_{safe_filename(story_part)}_floorload_template.dxf"
            out = unique_output_path(base_out)
            if story_mode == ALL_STORIES_VALUE:
                progress.update(35.0, "전체 Story DXF geometry 생성 중")
                result = write_all_story_centerline_dxf(
                    output_path=out,
                    stories=self.stories,
                    nodes=self.nodes,
                    elements=self.elements,
                    load_layers=specs,
                    story_tolerance=float(self.story_tol_var.get()),
                    default_hatch_scale=default_hatch_scale,
                )
            else:
                progress.update(35.0, "Story center line DXF geometry 생성 중")
                result = write_story_centerline_dxf(
                    output_path=out,
                    story=story,
                    nodes=self.nodes,
                    elements=self.elements,
                    load_layers=specs,
                    story_tolerance=float(self.story_tol_var.get()),
                    default_hatch_scale=default_hatch_scale,
                )
            progress.update(90.0, "DXF 템플릿 결과 정리 중")
            return result

        self.run_worker("DXF 템플릿 생성", job)

    def validate_user_dxf(self) -> None:
        dxf = self.user_dxf_path.get().strip()
        if not dxf:
            messagebox.showwarning("DXF 선택", "사용자가 작성한 DXF 파일을 선택해 주세요.")
            return
        layout_metadata = self._resolve_layout_metadata_for_dxf(dxf, allow_prompt=True)

        def job(progress):
            progress.update(15.0, "DXF 검증 작업 폴더 준비 중")
            self._ensure_current_project_workspace()
            progress.update(30.0, "DXF HATCH/Polyline 읽는 중")
            regions = read_load_regions(
                dxf,
                mapping_path=self.mapping_path.get().strip() or None,
                layout_metadata_path=layout_metadata,
                project_dxf_templates_dir=self.current_project_subdirs["dxf_templates"],
            )
            progress.update(80.0, "DXF 검증 결과 반영 중")
            self.loaded_regions = regions
            self.queue.put(("regions", regions))
            if not regions:
                raise RuntimeError("선택한 DXF에서 하중 해치를 찾지 못했습니다. 하중 영역을 HATCH로 작성하거나 폐합 Polyline을 사용해 주세요.")
            progress.update(90.0, "DXF 검증 요약 생성 중")
            return _format_dxf_validation_summary(regions)

        self.run_worker("DXF 검증", job)

    def run_floorload_diagnostics(self) -> None:
        if not self.nodes or not self.elements or not self.stories:
            messagebox.showwarning("모델 데이터 없음", "먼저 API로 모델을 열거나 MGT/MGTX에서 Story, Node, Element를 읽어 주세요.")
            return

        def job(progress):
            progress.update(15.0, "진단 작업 폴더 준비 중")
            self._ensure_current_project_workspace()
            reports_dir = self.current_project_subdirs["reports"]
            progress.update(30.0, "FLOORLOAD 모델링 진단 중")
            issues = analyze_floorload_model(
                nodes=self.nodes,
                elements=self.elements,
                stories=self.stories,
                planned_load_regions=self.loaded_regions,
                story_tolerance=float(self.story_tol_var.get()),
                snap_tolerance=float(self.snap_tol_var.get() if hasattr(self, "snap_tol_var") else self.config_data.snap_tolerance),
            )
            progress.update(70.0, "진단 보고서 저장 중")
            json_path, csv_path = write_diagnostic_reports(issues, reports_dir)
            progress.update(85.0, "진단 DXF 생성 중")
            dxf_path = write_floorload_diagnostic_dxf(output_path=reports_dir / "floorload_diagnostics_all.dxf", issues=issues)
            self.last_diagnostic_dxf_path = dxf_path
            self.last_diagnostic_report_path = csv_path
            self.queue.put(("diagnostics", issues))
            progress.update(92.0, "진단 결과 UI 반영 중")
            return f"FLOORLOAD 모델링 진단 완료: {len(issues)}개 이슈\nDXF: {dxf_path}\nCSV: {csv_path}\nJSON: {json_path}"

        self.run_worker("FLOORLOAD 모델링 진단", job)

    def build_mgt_only(self) -> None:
        self._build_pipeline(import_to_midas=False)

    def build_and_import(self) -> None:
        self._build_pipeline(import_to_midas=True)

    def _build_pipeline(self, *, import_to_midas: bool) -> None:
        story_mode, story = self._selected_dxf_story_mode()
        if story_mode == ALL_STORIES_VALUE:
            story = Story("ALL_STORIES", 0.0)
        if not story:
            messagebox.showwarning("Story 선택", "Story를 먼저 선택해 주세요.")
            return
        mgt = self.exported_mgt_path.get().strip()
        dxf = self.user_dxf_path.get().strip()
        if not mgt:
            messagebox.showwarning("MGT 없음", "기존 모델 MGT export 또는 MGT 직접 읽기를 먼저 실행해 주세요.")
            return
        if not dxf:
            messagebox.showwarning("DXF 없음", "사용자가 작성한 DXF 파일을 선택하고 검증해 주세요.")
            return
        layout_metadata = self.layout_metadata_path.get().strip() or None
        if not self.loaded_regions:
            layout_metadata = self._resolve_layout_metadata_for_dxf(dxf, allow_prompt=True)
        if import_to_midas:
            self._reset_model_next_action_state()
        else:
            self._mark_model_not_generated("API import 없이 full MGT만 생성하는 작업입니다. 모델링 파일 열기 버튼은 비활성화됩니다.")

        def job(progress):
            progress.update(10.0, "MGT 생성 작업 폴더 준비 중")
            self._ensure_current_project_workspace()
            progress.update(20.0, "DXF 하중 영역 확인 중")
            regions = self.loaded_regions or read_load_regions(
                dxf,
                mapping_path=self.mapping_path.get().strip() or None,
                layout_metadata_path=layout_metadata,
                project_dxf_templates_dir=self.current_project_subdirs["dxf_templates"],
            )
            progress.update(35.0, "Story node set 준비 중")
            story_nodes_by_name = None
            if any(getattr(region.region, "story_name", "") for region in regions):
                story_nodes_by_name = {
                    item.name: select_nodes_by_story(self.nodes, item.elevation, float(self.story_tol_var.get()))
                    for item in self.stories
                }
                story_nodes = list(self.nodes)
            else:
                story_nodes = select_nodes_by_story(self.nodes, story.elevation, float(self.story_tol_var.get()))
            if not story_nodes:
                raise RuntimeError("선택 Story Level의 노드가 없습니다. Story tolerance 또는 선택 Story를 확인해 주세요.")
            model_stem = Path(self.model_path.get() or mgt).stem
            mgt_dir = self.current_project_subdirs["mgt"]
            model_dir = self.current_project_subdirs["models"]
            reports_dir = self.current_project_subdirs["reports"]
            out_mgt = mgt_dir / f"{safe_filename(model_stem)}_{safe_filename(story.name)}_floorload_full.mgt"
            preview = reports_dir / f"{safe_filename(model_stem)}_{safe_filename(story.name)}_floorload_preview.dxf"
            progress.update(50.0, "FLOORLOAD assignment 및 full MGT 생성 중")
            result = run_mgt_build_pipeline(
                source_mgt_path=mgt,
                output_mgt_path=out_mgt,
                report_dir=reports_dir,
                preview_dxf_path=preview,
                model_name=Path(self.model_path.get() or mgt).name,
                story=story,
                dxf_name=Path(dxf).name,
                regions=regions,
                story_nodes=story_nodes,
                snap_tolerance=float(self.snap_tol_var.get()),
                include_zero_load=bool(self.include_zero_var.get()),
                story_nodes_by_name=story_nodes_by_name,
                mode="append",
            )
            progress.update(75.0, "MGT/보고서/검증 DXF 저장 확인 중")
            if import_to_midas:
                target = self.target_model_path.get().strip()
                if not target:
                    target_path = model_dir / f"{safe_filename(model_stem)}_{safe_filename(story.name)}_floorload_added.mgbx"
                else:
                    target_path = _mgbx_path(target)
                target_path = unique_numbered_path(target_path, start=2)
                self.target_model_path.set(str(target_path))
                if not target_path:
                    raise RuntimeError("결과 .mgbx 저장 경로가 비어 있습니다.")
                progress.update(82.0, "MIDAS 새 프로젝트 생성 중")
                client = self._client()
                client.new_project()
                progress.update(88.0, "MIDAS MGT import 중")
                client.import_mgt(result.full_mgt_path)
                progress.update(94.0, "최종 MGBX 저장 중")
                saved = client.save_as_project(target_path)
                return BuildPipelineUiResult(
                    f"full MGT 생성 및 새 모델 저장 완료\nMGT: {result.full_mgt_path}\n모델: {saved}\n보고서: {result.report_xlsx_path}\n검증 DXF: {result.preview_dxf_path}",
                    generated_model_path=saved,
                )
            return BuildPipelineUiResult(
                f"full MGT 생성 완료(API import 미실행)\nMGT: {result.full_mgt_path}\n보고서: {result.report_xlsx_path}\n검증 DXF: {result.preview_dxf_path}"
            )

        self.run_worker("MGT 생성/import" if import_to_midas else "MGT 생성", job)

    def launch_legacy_v3(self) -> None:
        app_path = self.root_dir / "legacy_v3" / "streamlit_app.py"
        if not app_path.exists():
            messagebox.showerror("v3 없음", f"기존 v3 Streamlit 앱을 찾지 못했습니다: {app_path}")
            return
        try:
            subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(app_path)], cwd=str(self.root_dir))
            self.log("기존 v3 Streamlit 앱 실행을 요청했습니다.")
        except Exception as exc:
            messagebox.showerror("실행 실패", str(exc))

    # -------------------------------------------------------------- helpers
    def _model_specs_from_mgt_text(self, text: str) -> list[FloorLoadTypeSpec]:
        specs = parse_floadtype_specs_from_text(text)
        if specs:
            return specs
        return [FloorLoadTypeSpec(name=name) for name in parse_floorload_type_names_from_text(text)]

    def _make_load_item(self, source: str, name: str, dl: float, ll: float, index: int | None = None) -> dict:
        source_text = str(source or "").upper()
        clean_name = str(name or "").strip() or "이름없음"
        dl_value = float(dl or 0.0)
        ll_value = float(ll or 0.0)
        index_part = "" if index is None else f"::{index}"
        return {
            "key": f"{source_text}::{clean_name}::{dl_value:g}::{ll_value:g}{index_part}",
            "source": source_text,
            "name": clean_name,
            "dl": dl_value,
            "ll": ll_value,
            "line": self._format_load_line(clean_name, dl_value, ll_value),
        }

    def _format_load_line(self, name: str, dl: float, ll: float) -> str:
        return f"{name}, DL:{float(dl):.2f} LL:{float(ll):.2f}"

    def _toggle_all_model_loads(self) -> None:
        checked = bool(self.model_load_all_var.get())
        for item in self.model_load_items:
            key = str(item["key"])
            if key not in self.model_load_vars:
                self.model_load_vars[key] = tk.BooleanVar(value=checked)
            self.model_load_vars[key].set(checked)
        self._refresh_model_load_checklist()
        self._sync_final_load_list()

    def _toggle_all_pdf_loads(self) -> None:
        checked = bool(self.pdf_load_all_var.get())
        for item in self.pdf_load_items:
            key = str(item["key"])
            if key not in self.pdf_load_vars:
                self.pdf_load_vars[key] = tk.BooleanVar(value=checked)
            self.pdf_load_vars[key].set(checked)
        self._refresh_pdf_load_checklist()
        self._sync_final_load_list()

    def _update_all_select_vars(self) -> None:
        if self.model_load_items:
            self.model_load_all_var.set(
                all(
                    self.model_load_vars.get(str(item["key"])) is not None
                    and bool(self.model_load_vars[str(item["key"])].get())
                    for item in self.model_load_items
                )
            )
        else:
            self.model_load_all_var.set(False)

        if self.pdf_load_items:
            self.pdf_load_all_var.set(
                all(
                    self.pdf_load_vars.get(str(item["key"])) is not None
                    and bool(self.pdf_load_vars[str(item["key"])].get())
                    for item in self.pdf_load_items
                )
            )
        else:
            self.pdf_load_all_var.set(False)

    def _refresh_model_load_checklist(self) -> None:
        if not hasattr(self, "model_load_check_frame"):
            return
        self._refresh_load_checklist(
            self.model_load_check_frame,
            self.model_load_items,
            self.model_load_vars,
            "모델링에 입력된 Floor Load Type이 없습니다.",
        )

    def _refresh_pdf_load_checklist(self) -> None:
        if not hasattr(self, "pdf_load_check_frame"):
            return
        self._refresh_load_checklist(
            self.pdf_load_check_frame,
            self.pdf_load_items,
            self.pdf_load_vars,
            "PDF에서 분석된 하중목록이 없습니다.",
        )

    def _refresh_load_checklist(self, parent: tk.Widget, items: list[dict], vars_by_key: dict[str, tk.BooleanVar], empty_text: str) -> None:
        for child in parent.winfo_children():
            child.destroy()
        if not items:
            ttk.Label(parent, text=empty_text, foreground="gray", wraplength=320).pack(anchor="w", padx=3, pady=3)
            return
        valid_keys = {str(item["key"]) for item in items}
        for key in list(vars_by_key):
            if key not in valid_keys:
                vars_by_key.pop(key, None)
        for item in items:
            key = str(item["key"])
            var = vars_by_key.get(key)
            if var is None:
                var = tk.BooleanVar(value=False)
                vars_by_key[key] = var
            tk.Checkbutton(
                parent,
                text=str(item["line"]),
                variable=var,
                command=self._sync_final_load_list,
                anchor="w",
                justify="left",
                wraplength=320,
                padx=1,
                pady=0,
            ).pack(fill="x", anchor="w", padx=2, pady=0)

    def _sync_final_load_list(self) -> None:
        self._update_all_select_vars()
        self.final_load_items = apply_load_display_names(self._get_selected_load_items())
        self._refresh_final_load_tree()

    def _resize_final_load_columns(self, _event=None) -> None:
        if not hasattr(self, "final_load_tree"):
            return
        total_width = max(self.final_load_tree.winfo_width(), 320)
        fixed_width = 55 + 55 + 55 + 28
        display_width = max(100, total_width - fixed_width)
        self.final_load_tree.column("display", width=display_width, minwidth=100, stretch=True)
        self.final_load_tree.column("source", width=55, minwidth=50, stretch=False)
        self.final_load_tree.column("dl", width=55, minwidth=50, stretch=False)
        self.final_load_tree.column("ll", width=55, minwidth=50, stretch=False)

    def _refresh_final_load_tree(self) -> None:
        if not hasattr(self, "final_load_tree"):
            return
        for item_id in self.final_load_tree.get_children():
            self.final_load_tree.delete(item_id)
        for item in self.final_load_items:
            self.final_load_tree.insert(
                "",
                "end",
                values=(
                    item.get("display_name") or item.get("name") or "",
                    item.get("source") or "",
                    f"{float(item.get('dl', 0.0)):.2f}",
                    f"{float(item.get('ll', 0.0)):.2f}",
                ),
            )
        self.after_idle(self._resize_final_load_columns)

    def _get_selected_load_items(self) -> list[dict]:
        selected: list[dict] = []
        for item in self.model_load_items:
            var = self.model_load_vars.get(str(item["key"]))
            if var and var.get():
                selected.append(item)
        for item in self.pdf_load_items:
            var = self.pdf_load_vars.get(str(item["key"]))
            if var and var.get():
                selected.append(item)
        return selected

    def _update_model_load_items(self, specs: list[FloorLoadTypeSpec]) -> None:
        self.model_load_items = [
            self._make_load_item("MODEL", spec.name, spec.dl, spec.ll, index)
            for index, spec in enumerate(specs, start=1)
        ]
        self._refresh_model_load_checklist()
        self._sync_final_load_list()

    def _update_pdf_load_items_from_lines(self, lines) -> None:
        items: list[dict] = []
        for line in lines or []:
            try:
                info = parse_load_layer(str(line))
            except Exception as exc:  # noqa: BLE001 - bad PDF candidates should not stop the GUI
                self.log(f"[PDF 하중목록] 해석 실패: {line} ({exc})")
                continue
            items.append(self._make_load_item("PDF", info.real_name, info.dl, info.ll, len(items) + 1))
        self.pdf_load_items = items
        self.pdf_load_vars = {}
        self._refresh_pdf_load_lines_listbox()
        self._refresh_pdf_load_checklist()
        self._sync_final_load_list()

    def _refresh_pdf_load_lines_listbox(self) -> None:
        if not hasattr(self, "pdf_load_lines_listbox"):
            return
        self.pdf_load_lines_listbox.delete(0, "end")
        for item in self.pdf_load_items:
            self.pdf_load_lines_listbox.insert("end", str(item["line"]))

    def _handle_dxf_template_result(self, result) -> None:
        self._mark_dxf_generated_success(result.dxf_path)
        self.mapping_path.set(str(result.mapping_json_path))
        if getattr(result, "layout_metadata_path", None):
            self.layout_metadata_path.set(str(result.layout_metadata_path))
            self.log(f"DXF layout metadata: {result.layout_metadata_path}")
        messagebox.showinfo(
            "DXF 템플릿 생성 완료",
            (
                "DXF 템플릿 생성이 완료되었습니다.\n\n"
                f"생성 파일:\n{result.dxf_path}\n\n"
                "CAD에서 파일을 열어 하중 영역을 HATCH 또는 폐합 Polyline으로 입력한 뒤 저장해 주세요."
            ),
            detail=(f"layout metadata: {result.layout_metadata_path}" if getattr(result, "layout_metadata_path", None) else ""),
        )

    def _handle_mgt_build_result(self, result) -> None:
        self.result_label.configure(text=f"결과 파일: {result}")
        generated_model_path = getattr(result, "generated_model_path", None)
        if generated_model_path:
            self._mark_model_generated_success(generated_model_path)
        else:
            self._mark_model_not_generated("full MGT 생성 완료. API import/save as를 실행하지 않아 모델링 파일은 생성되지 않았습니다.")

    def _launch_file_with_default_app(self, path: Path) -> None:
        if os.name == "nt":
            os.startfile(str(path))  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
            return
        subprocess.Popen(["xdg-open", str(path)])

    def _open_file_with_default_app(self, path: str | Path, *, title: str = "파일 열기") -> bool:
        target = Path(path)
        if not target.exists():
            messagebox.showerror("파일 없음", f"파일을 찾을 수 없습니다:\n{target}")
            return False
        try:
            self._launch_file_with_default_app(target)
            return True
        except Exception as exc:  # noqa: BLE001 - OS shell open failures should be visible
            if hasattr(self, "logger"):
                self.logger.exception("failed to open file with default app")
            messagebox.showerror(f"{title} 실패", str(exc))
            return False

    def _open_path_with_default_app(self, path: Path) -> None:
        self._open_file_with_default_app(path)

    def open_last_generated_dxf(self) -> None:
        path_text = self.generated_dxf_path.get().strip() if hasattr(self, "generated_dxf_path") else ""
        path = Path(path_text) if path_text else self.last_generated_dxf_path
        if not path:
            messagebox.showwarning("DXF 파일 없음", "열 수 있는 DXF 파일이 없습니다. 먼저 DXF를 생성해 주세요.")
            return
        self._open_file_with_default_app(path, title="DXF 열기")

    def open_generated_model_file(self) -> None:
        path_text = self.generated_model_path.get().strip() if hasattr(self, "generated_model_path") else ""
        path = Path(path_text) if path_text else self.last_generated_model_path
        if not path:
            messagebox.showwarning("모델링 파일 없음", "열 수 있는 모델링 파일이 없습니다. 먼저 full MGT 생성 + 새 모델 import/save as를 실행해 주세요.")
            return
        self._open_file_with_default_app(path, title="모델링 파일 열기")

    def open_last_diagnostic_dxf(self) -> None:
        path = self.last_diagnostic_dxf_path
        if not path or not path.exists():
            messagebox.showwarning("진단 DXF 없음", "먼저 모델링 FLOORLOAD 입력 가능성 분석을 실행해 주세요.")
            return
        self._open_path_with_default_app(path)

    def open_last_diagnostic_report(self) -> None:
        path = self.last_diagnostic_report_path
        if not path or not path.exists():
            messagebox.showwarning("진단 보고서 없음", "먼저 모델링 FLOORLOAD 입력 가능성 분석을 실행해 주세요.")
            return
        self._open_path_with_default_app(path)

    def _resolve_layout_metadata_for_dxf(self, dxf: str | Path, *, allow_prompt: bool) -> str | None:
        self._ensure_current_project_workspace()
        explicit_text = self.layout_metadata_path.get().strip() if hasattr(self, "layout_metadata_path") else ""
        explicit = Path(explicit_text) if explicit_text else None
        selection = select_layout_metadata(
            dxf_path=Path(dxf),
            explicit_path=explicit,
            project_dxf_templates_dir=self.current_project_subdirs.get("dxf_templates"),
            project_root=self.current_project_dir,
        )
        if selection.selected_path:
            selected = str(selection.selected_path)
            self.layout_metadata_path.set(selected)
            self.log(
                "layout metadata 선택: "
                f"{selection.reason}, {selected}"
            )
            return selected
        if selection.selection_required and allow_prompt:
            selected_path = self._prompt_layout_metadata_candidate(selection)
            if selected_path:
                self.layout_metadata_path.set(str(selected_path))
                self.log(f"layout metadata 사용자 선택: {selected_path}")
                return str(selected_path)
        return None

    def _prompt_layout_metadata_candidate(self, selection: LayoutMetadataSelection) -> Path | None:
        if not selection.candidates:
            path = filedialog.askopenfilename(filetypes=[("Layout metadata", "*.layout_metadata.json *.json"), ("All files", "*.*")])
            return Path(path) if path else None

        dialog = tk.Toplevel(self)
        dialog.title("layout metadata 선택")
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("920x360")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)
        ttk.Label(
            dialog,
            text="전층 DXF layout metadata 후보가 여러 개입니다. 사용할 metadata를 선택해 주세요.",
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(10, 4))
        tree = ttk.Treeview(
            dialog,
            columns=("file", "folder", "stories", "score", "matches", "mtime"),
            show="headings",
            height=10,
        )
        for col, text, width in (
            ("file", "파일명", 220),
            ("folder", "폴더", 330),
            ("stories", "Story", 70),
            ("score", "Score", 80),
            ("matches", "Label 일치", 90),
            ("mtime", "수정시간", 150),
        ):
            tree.heading(col, text=text)
            tree.column(col, width=width, anchor="w")
        by_item: dict[str, Path] = {}
        for item in selection.candidates:
            path = Path(item.path)
            details = item.details
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            except OSError:
                modified = ""
            item_id = tree.insert(
                "",
                "end",
                values=(
                    path.name,
                    str(path.parent),
                    details.get("story_count", ""),
                    f"{item.score:.1f}",
                    details.get("label_match_count", ""),
                    modified,
                ),
            )
            by_item[item_id] = path
        first = tree.get_children()
        if first:
            tree.selection_set(first[0])
            tree.focus(first[0])
        tree.grid(row=1, column=0, sticky="nsew", padx=10, pady=6)

        selected: dict[str, Path | None] = {"path": None}

        def choose_current() -> None:
            focus = tree.focus() or (tree.selection()[0] if tree.selection() else "")
            selected["path"] = by_item.get(focus)
            dialog.destroy()

        def choose_file() -> None:
            path_text = filedialog.askopenfilename(
                parent=dialog,
                filetypes=[("Layout metadata", "*.layout_metadata.json *.json"), ("All files", "*.*")],
            )
            selected["path"] = Path(path_text) if path_text else None
            dialog.destroy()

        def cancel() -> None:
            selected["path"] = None
            dialog.destroy()

        tree.bind("<Double-1>", lambda _event: choose_current())
        buttons = ttk.Frame(dialog)
        buttons.grid(row=2, column=0, sticky="e", padx=10, pady=(4, 10))
        ttk.Button(buttons, text="파일에서 선택", command=choose_file).pack(side="left", padx=4)
        ttk.Button(buttons, text="선택", command=choose_current).pack(side="left", padx=4)
        ttk.Button(buttons, text="취소", command=cancel).pack(side="left", padx=4)
        self.wait_window(dialog)
        return selected["path"]

    def _selected_story(self) -> Story | None:
        name = self.selected_story_name.get()
        for story in self.stories:
            if story.name == name:
                return story
        return self.stories[0] if self.stories else None

    def _selected_dxf_story_mode(self) -> tuple[str, Story | None]:
        selected = self.selected_story_name.get()
        if selected in {ALL_STORIES_LABEL, ALL_STORIES_VALUE}:
            return ALL_STORIES_VALUE, None
        return "SINGLE", self._selected_story()

    def _load_layer_specs(self) -> list[LoadLayerSpec]:
        self._sync_final_load_list()
        return [
            LoadLayerSpec(
                real_name=str(item.get("display_name") or item["name"]),
                dl=float(item.get("dl", 0.0)),
                ll=float(item.get("ll", 0.0)),
            )
            for item in self.final_load_items
        ]

    def run_worker(self, title: str, fn) -> None:
        if self._busy:
            messagebox.showinfo("작업 진행 중", "현재 작업이 진행 중입니다. 완료 후 다시 실행해 주세요.")
            return
        self._set_busy(True, title)
        self._start_progress(title)
        self.log(f"[{title}] 시작")
        reporter = ProgressReporter(callback=lambda percent, message="": self.queue.put(("progress", (percent, message or title))))

        def wrapper():
            try:
                reporter.update(3.0, f"{title} 준비 중")
                try:
                    accepts_progress = bool(inspect.signature(fn).parameters)
                except (TypeError, ValueError):
                    accepts_progress = False
                result = fn(reporter) if accepts_progress else fn()
                reporter.update(95.0, f"{title} 마무리 중")
                self.queue.put(("done", (title, result)))
            except PermissionError as exc:
                self.logger.exception("%s failed", title)
                if title == "DXF 템플릿 생성":
                    message = (
                        "DXF 파일을 저장할 수 없습니다.\n\n"
                        "가능한 원인:\n"
                        "1. 같은 이름의 DXF 파일이 CAD/ZWCAD/AutoCAD에서 열려 있습니다.\n"
                        "2. DATA\\OUTPUT\\{project}\\dxf_templates 폴더에 쓰기 권한이 없습니다.\n"
                        "3. OneDrive/백신/권한 정책이 파일 생성을 막고 있습니다.\n\n"
                        "해결 방법:\n"
                        "- 열려 있는 DXF 파일을 닫고 다시 시도하세요.\n"
                        "- 또는 프로그램 폴더를 바탕화면이나 문서 폴더처럼 쓰기 가능한 위치로 옮겨 실행하세요.\n\n"
                        f"상세 오류:\n{exc}"
                    )
                    self.queue.put(("error", (title, message)))
                else:
                    self.queue.put(("error", (title, str(exc))))
            except Exception as exc:  # noqa: BLE001 - GUI must surface all errors
                self.logger.exception("%s failed", title)
                detail = getattr(exc, "detail", "")
                self.queue.put(("error", (title, f"{exc}\n{detail}" if detail else str(exc))))

        threading.Thread(target=wrapper, daemon=True).start()

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "done":
                    title, result = payload
                    self.log(f"[{title}] 완료: {result}")
                    if title == "DXF 템플릿 생성":
                        self._handle_dxf_template_result(result)
                    elif title.startswith("MGT"):
                        self._handle_mgt_build_result(result)
                    self._finish_progress("완료")
                    self._set_busy(False)
                elif kind == "error":
                    title, message = payload
                    self.log(f"[{title}] 오류: {message}")
                    if title == "DXF 템플릿 생성":
                        self._mark_dxf_generated_failed(str(message))
                    elif title == "MGT 생성/import":
                        self._mark_model_generated_failed(str(message))
                    elif title == "MGT 생성":
                        self._mark_model_not_generated("full MGT 생성에 실패했습니다. 모델링 파일은 생성되지 않았습니다.")
                    self._error_progress("오류")
                    self._set_busy(False)
                    messagebox.showerror(title, message)
                elif kind == "progress":
                    percent, message = payload
                    self._set_progress(percent, message)
                elif kind == "stories":
                    self._refresh_story_tree(payload)
                elif kind == "regions":
                    self._refresh_region_tree(payload)
                elif kind == "diagnostics":
                    self._refresh_diagnostic_tree(payload)
                elif kind == "floorload_status":
                    self._update_floorload_status(payload)
                elif kind == "model_load_items":
                    self._update_model_load_items(payload)
                elif kind == "pdf_rows":
                    self._update_pdf_result(payload)
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _refresh_story_tree(self, stories: list[Story]) -> None:
        for item in self.story_tree.get_children():
            self.story_tree.delete(item)
        for story in stories:
            self.story_tree.insert("", "end", values=(story.name, f"{story.elevation:g}", "" if story.height is None else f"{story.height:g}"))
        if stories:
            first = self.story_tree.get_children()[0]
            self.story_tree.selection_set(first)
            self.selected_story_name.set(stories[0].name)
        if hasattr(self, "dxf_story_combo"):
            story_names = [story.name for story in stories]
            display_values = [ALL_STORIES_LABEL] + story_names if story_names else []
            self.dxf_story_combo.configure(values=display_values)
            if story_names and self.selected_story_name.get() not in display_values:
                self.selected_story_name.set(story_names[0])
            if not story_names:
                self.dxf_story_combo.configure(values=[])
                self.selected_story_name.set("")

    def _on_dxf_story_combo_selected(self, _event=None) -> None:
        selected = self.selected_story_name.get()
        if not selected or not hasattr(self, "story_tree"):
            return
        if selected in {ALL_STORIES_LABEL, ALL_STORIES_VALUE}:
            try:
                self.story_tree.selection_remove(self.story_tree.selection())
            except Exception:
                pass
            return
        try:
            for item_id in self.story_tree.get_children():
                values = self.story_tree.item(item_id, "values")
                if values and str(values[0]) == selected:
                    self.story_tree.selection_set(item_id)
                    self.story_tree.see(item_id)
                    break
        except Exception as exc:  # noqa: BLE001 - selection sync should never stop DXF flow
            self.logger.warning("failed to sync DXF story combo selection: %s", exc)

    def _refresh_region_tree(self, regions) -> None:
        for item in self.dxf_tree.get_children():
            self.dxf_tree.delete(item)
        for region in regions:
            load = region.load
            mode, mode_source = infer_distribution(region.region, load) if load else ("", "")
            direction_markers = list(getattr(region.region, "direction_markers", []) or [])
            direction_summary = str(len(direction_markers))
            if direction_markers:
                marker_ids = ",".join(str(getattr(marker, "source_id", "") or "") for marker in direction_markers)
                match_methods = ",".join(str(getattr(marker, "match_method", "") or "") for marker in direction_markers)
                direction_summary = f"{len(direction_markers)} / {match_methods} / {marker_ids}"
            self.dxf_tree.insert(
                "",
                "end",
                values=(
                    region.status,
                    region.region.story_name,
                    "YES" if getattr(region.region, "layout_metadata_used", False) else "NO",
                    "YES" if getattr(region.region, "transform_applied", False) else "NO",
                    region.region.source_type,
                    region.region.layer,
                    region.region.hatch_pattern_name,
                    "YES" if region.region.hatch_solid_fill else "NO",
                    mode,
                    mode_source,
                    direction_summary,
                    load.real_name if load else "",
                    "" if not load else f"{load.dl:.2f}",
                    "" if not load else f"{load.ll:.2f}",
                    f"{region.area:.6g}",
                    _format_region_bbox_for_ui(getattr(region.region, "placed_bbox", ()) or ()),
                    _format_region_bbox_for_ui(getattr(region.region, "model_bbox", ()) or getattr(region.region, "bbox", ()) or ()),
                    region.region.source_id,
                    " | ".join(region.warnings),
                ),
            )

    def _refresh_diagnostic_tree(self, issues) -> None:
        self.diagnostic_issues = list(issues or [])
        if hasattr(self, "open_diag_dxf_button") and self.last_diagnostic_dxf_path:
            self.open_diag_dxf_button.state(["!disabled"])
        if hasattr(self, "open_diag_report_button") and self.last_diagnostic_report_path:
            self.open_diag_report_button.state(["!disabled"])
        if not hasattr(self, "diagnostic_tree"):
            return
        for item in self.diagnostic_tree.get_children():
            self.diagnostic_tree.delete(item)
        for issue in self.diagnostic_issues:
            self.diagnostic_tree.insert(
                "",
                "end",
                values=(
                    issue.story_name,
                    issue.severity,
                    issue.issue_type,
                    f"{issue.x:.3f}, {issue.y:.3f}",
                    ",".join(str(value) for value in issue.node_ids),
                    ",".join(str(value) for value in issue.element_ids),
                    issue.message,
                    issue.suggested_action,
                ),
            )

    def _ensure_pdf_tab_visible(self, *, select: bool = True) -> None:
        if not self.notebook:
            return
        if not self.pdf_tab_visible:
            self.notebook.insert(2, self.tab_pdf, text="3 PDF 하중 입력(선택)")
            self.pdf_tab_visible = True
            self._refresh_tab_labels()
        if select:
            self.notebook.select(self.tab_pdf)

    def _refresh_tab_labels(self) -> None:
        if not self.notebook:
            return
        if self.pdf_tab_visible:
            self.notebook.tab(self.tab_api, text="1 API 설정")
            self.notebook.tab(self.tab_model, text="2 모델/Story")
            self.notebook.tab(self.tab_pdf, text="3 PDF 하중 입력(선택)")
            self.notebook.tab(self.tab_dxf, text="4 DXF 생성/검증")
            self.notebook.tab(self.tab_build, text="5 MGT 입력/저장")
        else:
            self.notebook.tab(self.tab_api, text="1 API 설정")
            self.notebook.tab(self.tab_model, text="2 모델/Story")
            self.notebook.tab(self.tab_dxf, text="3 DXF 생성/검증")
            self.notebook.tab(self.tab_build, text="4 MGT 입력/저장")

    def _update_floorload_status(self, presence) -> None:
        self.floorload_status_var.set(presence.message)
        self.open_pdf_tab_button.state(["!disabled"])
        if presence.has_floorload:
            self.floorload_status_label.configure(foreground="green")
            self.open_pdf_tab_button.configure(text="PDF 하중 입력 탭 열기(선택)")
        else:
            self.floorload_status_label.configure(foreground="#b36b00")
            self.open_pdf_tab_button.configure(text="PDF로 하중 입력하기")

    def _refresh_pdf_listbox(self) -> None:
        if not hasattr(self, "pdf_listbox"):
            return
        self.pdf_listbox.delete(0, "end")
        for path in self.selected_pdf_paths:
            self.pdf_listbox.insert("end", str(path))

    def _update_pdf_result(self, result: PdfLoadImportResult) -> None:
        self.pdf_import_result = result
        if result.mgtx_path:
            self.pdf_mgtx_path.set(str(result.mgtx_path))
        self._refresh_pdf_tree(result.classified_rows)
        self._update_pdf_load_items_from_lines(result.layer_lines)
        self.pdf_summary_label.configure(
            text=(
                f"PDF 분석 결과: PDF {len(result.input_pdf_paths)}개, 원시 후보 {len(result.raw_rows)}개, "
                f"MGTX 유효 row {len(result.valid_rows)}개, 검토/제외 {len(result.error_rows)}개, "
                f"DXF 레이어 후보 {len(result.layer_lines)}개\n"
                f"작업 폴더: {result.output_dir}"
            )
        )

    def _refresh_pdf_tree(self, rows) -> None:
        if not hasattr(self, "pdf_tree"):
            return
        for item in self.pdf_tree.get_children():
            self.pdf_tree.delete(item)
        for row in rows or []:
            valid = bool(row.get("is_valid_for_mgtx"))
            status = "입력 가능" if valid else "검토/제외"
            source = f"{row.get('source_pdf') or ''} / p{row.get('source_page') or ''}"
            reason = row.get("exclude_reason") or row.get("failure_reason") or row.get("review_required_reason") or row.get("validation_messages") or ""
            if isinstance(reason, (list, tuple)):
                reason = " | ".join(map(str, reason))
            self.pdf_tree.insert(
                "",
                "end",
                values=(
                    status,
                    row.get("floor_load_type_name") or row.get("floor_usage_name") or "",
                    row.get("load_case_name") or "",
                    row.get("floor_load_value") or row.get("load_value_kn_per_m2") or "",
                    source,
                    reason,
                ),
            )

    def log(self, message: str) -> None:
        self.logger.info(message)
        self.log_text.insert("end", str(message) + "\n") if hasattr(self, "log_text") else None
        if hasattr(self, "log_text"):
            self.log_text.see("end")


def main() -> None:
    app = FloorLoadAutoApp()
    app.mainloop()


if __name__ == "__main__":
    main()
