from pathlib import Path
import csv
import json

import pytest
from shapely.geometry import Polygon

from app.core.dxf_load_reader import HatchRegion, LoadRegion
from app.core.floorload_audit_report import (
    FloorloadAuditCollector,
    compare_floorload_mgt_baseline,
    parse_floorload_records,
    write_hatch_view_input_state,
)
from app.core.floorload_mgt_builder import BELOW_ALLOWED_REGION_MISMATCH, run_mgt_build_pipeline
from app.core.hatch_region_editor import EditableHatchRegion
from app.core.load_parser import LoadLayerInfo
from app.core.mgt_parser import Node, Story


def test_hatch_view_input_state_snapshot_records_internal_dxf_and_continuous_targets(tmp_path: Path):
    internal = EditableHatchRegion(
        region_key="INTERNAL|1F|A|LOADED|Office",
        story_name="1F",
        cell_ids=("A",),
        polygon_xy=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        load_name="Office",
        load_layer="LOAD_001_Office_DL_1.2_LL_3.4",
        dl=1.2,
        ll=3.4,
        distribution="TWO_WAY",
    )
    dxf = _dxf_region("1F", ((20.0, 0.0), (30.0, 0.0), (30.0, 10.0), (20.0, 10.0)), name="Lobby")

    json_path, csv_path = write_hatch_view_input_state(
        output_dir=tmp_path,
        model_name="model.mgb",
        source_dxf_path="user.dxf",
        layout_metadata_path="layout.json",
        display_mode="ALL",
        selected_story="1F",
        dxf_regions=[dxf],
        internal_regions=[internal],
        selected_region_keys={"DXF|1F|D1|0"},
        selected_edit_region_keys={internal.region_key},
        continuous_apply_targets_by_region={internal.region_key: ("2F", "3F")},
        continuous_materialized_targets_by_region={internal.region_key: ("2F",)},
        dxf_region_key_map={id(dxf): "DXF|1F|D1|0"},
    )

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["region_count"] == 2
    internal_row = next(row for row in payload["regions"] if row["source"] == "INTERNAL")
    dxf_row = next(row for row in payload["regions"] if row["source"] == "DXF")
    assert internal_row["load_name"] == "Office"
    assert internal_row["continuous_targets"] == ["2F", "3F"]
    assert internal_row["continuous_materialized_targets"] == ["2F"]
    assert internal_row["is_selected"] is True
    assert dxf_row["load_name"] == "Lobby"
    assert dxf_row["polygon_xy"][0] == [20.0, 0.0]
    assert csv_path.exists()


def test_audit_collector_writes_stage_events_json_and_csv(tmp_path: Path):
    collector = FloorloadAuditCollector()
    collector.add(
        "RAW_REGION_INPUT",
        status="OK",
        source="INTERNAL",
        region_key="R1",
        story_name="1F",
        load_name="Office",
        data={"polygon_xy": [(0.0, 0.0), (1.0, 0.0)]},
    )
    collector.add(
        "FINAL_RECORD_SKIPPED",
        status="SKIPPED",
        reason_code=BELOW_ALLOWED_REGION_MISMATCH,
        message_ko="선택 Story의 BELOW 기준 하중입력 가능 영역 밖에 있는 해치입니다.",
        region_key="R2",
    )

    json_path, csv_path = collector.write(tmp_path)

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert [event["stage"] for event in payload["events"]] == ["RAW_REGION_INPUT", "FINAL_RECORD_SKIPPED"]
    assert payload["events"][1]["reason_code"] == BELOW_ALLOWED_REGION_MISMATCH
    with csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[1]["stage"] == "FINAL_RECORD_SKIPPED"
    assert rows[1]["reason_code"] == BELOW_ALLOWED_REGION_MISMATCH


def test_pipeline_audit_records_skipped_below_region_and_final_record_created(tmp_path: Path):
    pytest.importorskip("ezdxf")
    source_mgt = tmp_path / "source.mgt"
    output_mgt = tmp_path / "floorload_full.mgt"
    report_dir = tmp_path / "reports"
    preview = report_dir / "preview.dxf"
    source_mgt.write_text("*ENDDATA\n", encoding="cp949")
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
    ]
    valid = _dxf_region("1F", ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), name="Office")
    outside = _dxf_region("1F", ((100.0, 100.0), (110.0, 100.0), (110.0, 110.0), (100.0, 110.0)), name="Lobby")

    result = run_mgt_build_pipeline(
        source_mgt_path=source_mgt,
        output_mgt_path=output_mgt,
        report_dir=report_dir,
        preview_dxf_path=preview,
        model_name="model.mgb",
        story=Story("1F", 0.0),
        dxf_name="user.dxf",
        regions=[valid, outside],
        story_nodes=nodes,
        story_nodes_by_name={"1F": nodes},
        snap_tolerance=0.01,
        include_zero_load=True,
        allowed_story_polygons_by_name={"1F": [Polygon(((0.0, 0.0), (20.0, 0.0), (20.0, 20.0), (0.0, 20.0)))]},
    )

    assert result.audit_json_path is not None
    audit = json.loads(result.audit_json_path.read_text(encoding="utf-8"))
    events = audit["events"]
    assert any(event["stage"] == "FINAL_RECORD_CREATED" and event["load_name"] == "Office" for event in events)
    skipped = [
        event
        for event in events
        if event["stage"] == "FINAL_RECORD_SKIPPED" and event["reason_code"] == BELOW_ALLOWED_REGION_MISMATCH
    ]
    assert skipped
    assert skipped[0]["load_name"] == "Lobby"
    assert skipped[0]["story_name"] == "1F"
    assert skipped[0]["polygon_vertex_count"] == 4
    assert skipped[0]["data"]["allowed_check_mode"] in {"RAW", "SNAP_TOLERANT"}
    assert "raw_polygon_bbox" in skipped[0]["data"]
    assert "allowed_union_bbox" in skipped[0]["data"]

    with result.report_csv_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert {"audit_id", "source_region_key", "pipeline_stage", "skip_reason_code", "final_record_created"}.issubset(rows[0])
    skipped_report = next(row for row in rows if row["하중명"] == "Lobby")
    assert skipped_report["skip_reason_code"] == BELOW_ALLOWED_REGION_MISMATCH
    assert skipped_report["final_record_created"] == "NO"
    ok_report = next(row for row in rows if row["하중명"] == "Office")
    assert ok_report["pipeline_stage"] == "FINAL_RECORD_CREATED"
    assert ok_report["final_record_created"] == "YES"


def test_pipeline_audit_records_duplicate_dxf_removed_by_internal_region(tmp_path: Path):
    pytest.importorskip("ezdxf")
    source_mgt = tmp_path / "source.mgt"
    output_mgt = tmp_path / "floorload_full.mgt"
    report_dir = tmp_path / "reports"
    preview = report_dir / "preview.dxf"
    source_mgt.write_text("*ENDDATA\n", encoding="cp949")
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
    ]
    vertices = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))
    dxf = _dxf_region("1F", vertices, name="Office")
    internal = EditableHatchRegion(
        region_key="INTERNAL|1F|A|LOADED|Office",
        story_name="1F",
        cell_ids=("A",),
        polygon_xy=vertices,
        load_name="Office",
        load_layer="LOAD_001_Office_DL_1.2_LL_3.4",
        dl=1.2,
        ll=3.4,
        distribution="TWO_WAY",
    )

    result = run_mgt_build_pipeline(
        source_mgt_path=source_mgt,
        output_mgt_path=output_mgt,
        report_dir=report_dir,
        preview_dxf_path=preview,
        model_name="model.mgb",
        story=Story("1F", 0.0),
        dxf_name="user.dxf",
        regions=[dxf],
        internal_regions=[internal],
        story_nodes=nodes,
        story_nodes_by_name={"1F": nodes},
        snap_tolerance=0.01,
        include_zero_load=True,
    )

    assert result.duplicate_removed_count == 1
    audit = json.loads(result.audit_json_path.read_text(encoding="utf-8"))
    duplicate_events = [
        event
        for event in audit["events"]
        if event["stage"] == "AFTER_DXF_INTERNAL_FILTER"
        and event["status"] == "SKIPPED"
        and event["reason_code"] == "DUPLICATE_OVERRIDDEN_BY_INTERNAL_REGION"
    ]
    assert len(duplicate_events) == 1
    assert duplicate_events[0]["load_name"] == "Office"
    assert duplicate_events[0]["story_name"] == "1F"
    assert duplicate_events[0]["polygon_vertex_count"] == 4


def test_pipeline_audit_records_below_allowed_region_check_ok_event(tmp_path: Path):
    pytest.importorskip("ezdxf")
    source_mgt = tmp_path / "source.mgt"
    output_mgt = tmp_path / "floorload_full.mgt"
    report_dir = tmp_path / "reports"
    preview = report_dir / "preview.dxf"
    source_mgt.write_text("*ENDDATA\n", encoding="cp949")
    nodes = [
        Node(1, 0.0, 0.0, 0.0),
        Node(2, 10.0, 0.0, 0.0),
        Node(3, 10.0, 10.0, 0.0),
        Node(4, 0.0, 10.0, 0.0),
    ]
    region = _dxf_region("1F", ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)), name="Office")

    result = run_mgt_build_pipeline(
        source_mgt_path=source_mgt,
        output_mgt_path=output_mgt,
        report_dir=report_dir,
        preview_dxf_path=preview,
        model_name="model.mgb",
        story=Story("1F", 0.0),
        dxf_name="user.dxf",
        regions=[region],
        story_nodes=nodes,
        story_nodes_by_name={"1F": nodes},
        snap_tolerance=0.01,
        include_zero_load=True,
        allowed_story_polygons_by_name={"1F": [Polygon(((-1.0, -1.0), (12.0, -1.0), (12.0, 12.0), (-1.0, 12.0)))]},
    )

    audit = json.loads(result.audit_json_path.read_text(encoding="utf-8"))
    assert any(
        event["stage"] == "BELOW_ALLOWED_REGION_CHECK"
        and event["status"] == "OK"
        and event["data"].get("allowed_region_check") == "PASSED"
        for event in audit["events"]
    )
    assert any(event["stage"] == "FINAL_RECORD_CREATED" and event["load_name"] == "Office" for event in audit["events"])


def test_pipeline_creates_final_record_when_below_check_passes_after_snapping(tmp_path: Path):
    pytest.importorskip("ezdxf")
    source_mgt = tmp_path / "source.mgt"
    output_mgt = tmp_path / "floorload_full.mgt"
    report_dir = tmp_path / "reports"
    preview = report_dir / "preview.dxf"
    source_mgt.write_text("*ENDDATA\n", encoding="cp949")
    nodes = [
        Node(1, 6.585, 0.2, 6.0),
        Node(2, 13.2, 0.2, 6.0),
        Node(3, 13.2, 8.7, 6.0),
        Node(4, 6.585, 8.7, 6.0),
    ]
    region = _dxf_region(
        "3F",
        ((6.5, 0.0), (13.0, 0.0), (13.0, 8.5), (6.5, 8.5)),
        name="근린생활시설(1F)",
        dl=4.8,
        ll=5.0,
    )

    result = run_mgt_build_pipeline(
        source_mgt_path=source_mgt,
        output_mgt_path=output_mgt,
        report_dir=report_dir,
        preview_dxf_path=preview,
        model_name="model.mgb",
        story=Story("3F", 6.0),
        dxf_name="user.dxf",
        regions=[region],
        story_nodes=nodes,
        story_nodes_by_name={"3F": nodes},
        snap_tolerance=0.5,
        include_zero_load=True,
        allowed_story_polygons_by_name={"3F": [Polygon(((6.585, 0.2), (13.2, 0.2), (13.2, 8.7), (6.585, 8.7)))]},
    )

    assert result.assignment_count == 1
    audit = json.loads(result.audit_json_path.read_text(encoding="utf-8"))
    below_ok = next(event for event in audit["events"] if event["stage"] == "BELOW_ALLOWED_REGION_CHECK")
    assert below_ok["status"] == "OK"
    assert below_ok["data"]["allowed_check_mode"] == "SNAP_TOLERANT"
    assert below_ok["data"]["snap_node_ids"] == [1, 2, 3, 4]
    assert any(event["stage"] == "FINAL_RECORD_CREATED" and event["load_name"] == "근린생활시설(1F)" for event in audit["events"])


def test_parse_floorload_records_reads_all_floorload_blocks():
    records = parse_floorload_records(
        "\n".join(
            [
                "*FLOORLOAD",
                "   A, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4",
                "*STLDCASE",
                "   DL, USER",
                "*FLOORLOAD",
                "   B, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 5, 6, 7, 8",
                "*ENDDATA",
            ]
        )
    )

    assert [record["load_name"] for record in records] == ["A", "B"]
    assert [record["record_index"] for record in records] == [1, 2]
    assert [record["block_index"] for record in records] == [1, 2]


def test_floorload_baseline_compare_reports_missing_extra_and_bal_difference(tmp_path: Path):
    baseline = tmp_path / "baseline.mgt"
    generated = tmp_path / "generated.mgt"
    baseline.write_text(
        "\n".join(
            [
                "*FLOORLOAD",
                "   Office, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, 4",
                "   Lobby, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 5, 6, 7, 8",
                "*ENDDATA",
            ]
        ),
        encoding="cp949",
    )
    generated.write_text(
        "\n".join(
            [
                "*FLOORLOAD",
                "   Office, 2, 0, 0, 0, 0, GZ, NO, , NO, NO, , 1, 2, 3, 4",
                "   Roof, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 9, 10, 11, 12",
                "*ENDDATA",
            ]
        ),
        encoding="cp949",
    )

    result = compare_floorload_mgt_baseline(baseline, generated, output_dir=tmp_path / "reports")

    assert [record["load_name"] for record in result["missing_from_generated"]] == ["Lobby"]
    assert [record["load_name"] for record in result["extra_in_generated"]] == ["Roof"]
    assert result["bal_differences"][0]["load_name"] == "Office"
    assert Path(result["json_path"]).exists()
    assert Path(result["csv_path"]).exists()


def _dxf_region(story_name: str, vertices, *, name: str = "Office", dl: float = 1.2, ll: float = 3.4) -> LoadRegion:
    polygon = Polygon(vertices)
    layer = f"LOAD_001_{name}_DL_{dl:g}_LL_{ll:g}"
    return LoadRegion(
        region=HatchRegion(
            source_type="HATCH",
            layer=layer,
            handle="D1",
            vertices=list(vertices),
            polygon=polygon,
            area=float(polygon.area),
            bbox=tuple(float(value) for value in polygon.bounds),
            story_name=story_name,
            source_id=f"{story_name}:{name}:D1",
            polygon_index=0,
            hatch_pattern_name="SOLID",
            hatch_solid_fill=1,
        ),
        load=LoadLayerInfo(layer=layer, real_name=name, dl=dl, ll=ll),
        status="OK",
        warnings=[],
    )
