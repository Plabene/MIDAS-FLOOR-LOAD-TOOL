from queue import Queue
from types import SimpleNamespace
from pathlib import Path

import pytest

from app.core.mgt_parser import Element, Node, Story
from app.main import FloorLoadAutoApp, _diagnostic_penalty_by_story


def test_ensure_typical_floor_analysis_passes_diagnostic_penalties(monkeypatch):
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 1.0, 0.0, 0.0)]
    app.elements = [Element(1, "BEAM", node_ids=(1, 2))]
    app.current_mgt_text = ""
    app.config_data = SimpleNamespace(story_tolerance=0.01, snap_tolerance=0.02)
    app.story_tol_var = SimpleNamespace(get=lambda: 0.01)
    app.snap_tol_var = SimpleNamespace(get=lambda: 0.02)
    app.typical_floor_analysis = None
    app.typical_floor_groups = ()
    app.story_shape_profiles = ()
    app.queue = Queue()
    app.logger = SimpleNamespace(warning=lambda *_args, **_kwargs: None)
    captured = {}

    def fake_analyze_typical_floors(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(groups=("g",), profiles=("p",))

    monkeypatch.setattr("app.main.analyze_typical_floors", fake_analyze_typical_floors)

    assert app._ensure_typical_floor_analysis(story_penalties={"1F": 0.20}, reason="test") is True

    assert captured["story_penalties"] == {"1F": 0.20}
    assert app.typical_floor_groups == ("g",)
    assert app.story_shape_profiles == ("p",)


def test_diagnostic_penalty_map_combines_severity_and_issue_type():
    issue = SimpleNamespace(
        story_name="5F",
        severity="ERROR",
        issue_type="SNAP_ERROR_EXCEEDED",
    )

    assert _diagnostic_penalty_by_story([issue])["5F"] == pytest.approx(0.35)


def test_load_mgt_snapshot_queues_auto_floorload_diagnostics(monkeypatch, tmp_path: Path):
    app = object.__new__(FloorLoadAutoApp)
    app.current_project_dir = None
    app.current_mgt_text = ""
    app.queue = Queue()
    app._ensure_current_project_workspace = lambda *_args, **_kwargs: tmp_path
    app._update_model_unit_state = lambda *_args, **_kwargs: None
    app._model_specs_from_mgt_text = lambda _text: []
    stories = [Story("1F", 0.0)]
    nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 1.0, 0.0, 0.0)]
    elements = [Element(1, "BEAM", node_ids=(1, 2))]

    monkeypatch.setattr("app.main.parse_mgt_file", lambda _path: (stories, nodes, elements, "*UNIT\n"))

    app._load_mgt_snapshot_impl(tmp_path / "model.mgt")

    queued_kinds = [app.queue.get_nowait()[0] for _ in range(app.queue.qsize())]
    assert "auto_floorload_diagnostics" in queued_kinds


def test_poll_queue_handles_auto_floorload_diagnostics_event():
    app = object.__new__(FloorLoadAutoApp)
    app.queue = Queue()
    app.queue.put(("auto_floorload_diagnostics", {"reason": "test"}))
    app.after = lambda *_args, **_kwargs: None
    captured = {}
    app._start_auto_floorload_diagnostics = lambda *, reason="": captured.setdefault("reason", reason)

    app._poll_queue()

    assert captured["reason"] == "test"


def test_auto_floorload_diagnostics_skips_duplicate_signature():
    app = object.__new__(FloorLoadAutoApp)
    app.stories = [Story("1F", 0.0)]
    app.nodes = [Node(1, 0.0, 0.0, 0.0)]
    app.elements = [Element(1, "COLUMN", node_ids=(1,))]
    app.current_mgt_text = "same"
    app._busy = False
    app.after = lambda *_args, **_kwargs: None
    app.log = lambda *_args, **_kwargs: None
    signature = app._floorload_diag_signature()
    app.last_auto_floorload_diag_signature = signature
    called = []
    app.run_floorload_diagnostics = lambda **_kwargs: called.append(True)

    app._start_auto_floorload_diagnostics(reason="same")

    assert called == []
