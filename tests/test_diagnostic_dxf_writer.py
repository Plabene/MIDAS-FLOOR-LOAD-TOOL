import ezdxf

from app.core.diagnostic_dxf_writer import write_floorload_diagnostic_dxf
from app.core.mgt_parser import Element, Node, Story
from app.core.model_floorload_diagnostics import FloorLoadDiagnosticIssue


def _all_dxf_text(doc) -> str:
    msp = doc.modelspace()
    values = [entity.dxf.text for entity in msp.query("TEXT")]
    values.extend(getattr(entity, "text", "") for entity in msp.query("MTEXT"))
    return "\n".join(values)


def test_diagnostic_dxf_writer_uses_legend_without_repeated_issue_type_text(tmp_path):
    nodes = [
        Node(1, 0.0, 0.0, 5.0),
        Node(2, 10.0, 0.0, 5.0),
        Node(3, 10.0, 8.0, 5.0),
        Node(4, 0.0, 8.0, 5.0),
    ]
    elements = [
        Element(100, "BEAM", node_ids=(1, 2)),
        Element(101, "BEAM", node_ids=(1, 2)),
        Element(102, "BEAM", node_ids=(3, 4)),
        Element(200, "WALL", node_ids=(2, 3, 4)),
        Element(300, "COLUMN", node_ids=(1,)),
    ]
    issues = [
        FloorLoadDiagnosticIssue(
            story_name="5F",
            severity="WARNING",
            issue_type="SPLIT_OVERLAP_DUPLICATE_ELEMENT",
            message="raw",
            x=5.0,
            y=0.0,
            node_ids=[],
            element_ids=[100, 101],
            suggested_action="raw action",
        ),
        FloorLoadDiagnosticIssue(
            story_name="5F",
            severity="WARNING",
            issue_type="CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD",
            message="raw",
            x=5.0,
            y=8.0,
            node_ids=[4],
            element_ids=[102],
            suggested_action="raw action",
        ),
        FloorLoadDiagnosticIssue(
            story_name="5F",
            severity="ERROR",
            issue_type="SNAP_ERROR_EXCEEDED",
            message="raw",
            x=10.0,
            y=8.0,
            node_ids=[],
            element_ids=[],
            suggested_action="raw action",
        ),
    ]

    path = write_floorload_diagnostic_dxf(
        output_path=tmp_path / "diag.dxf",
        issues=issues,
        nodes=nodes,
        elements=elements,
        stories=[Story("5F", 5.0)],
        story_tolerance=0.01,
    )

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    layer_names = {layer.dxf.name for layer in doc.layers}
    assert "FLOAD_DIAG_MODEL_BEAM" in layer_names
    assert "FLOAD_DIAG_MODEL_WALL" in layer_names
    assert "FLOAD_DIAG_MODEL_COLUMN" in layer_names
    assert "FLOAD_DIAG_DUPLICATE" in layer_names
    assert "FLOAD_DIAG_CANTILEVER" in layer_names
    assert "FLOAD_DIAG_SNAP" in layer_names
    assert "FLOAD_DIAG_LEGEND" in layer_names
    assert len([entity for entity in msp.query("LINE") if entity.dxf.layer == "FLOAD_DIAG_MODEL_BEAM"]) >= 2
    assert len([entity for entity in msp.query("LINE") if entity.dxf.layer == "FLOAD_DIAG_DUPLICATE"]) >= 2
    assert any(entity.dxf.layer == "FLOAD_DIAG_CANTILEVER" for entity in list(msp.query("LINE")) + list(msp.query("LWPOLYLINE")))
    assert any(entity.dxf.layer == "FLOAD_DIAG_SNAP" for entity in list(msp.query("LINE")) + list(msp.query("CIRCLE")))
    text = _all_dxf_text(doc)
    assert "SPLIT_OVERLAP_DUPLICATE_ELEMENT" not in text
    assert "CANTILEVER_FREE_END_MAY_BLOCK_FLOORLOAD" not in text
    assert "SNAP_ERROR_EXCEEDED" not in text
    assert "진단 범례" in text
    assert "중복부재" in text
    assert "외팔보/자유단" in text
    assert "스냅오류" in text
    assert "E100" in text
    assert "E101" in text


def test_diagnostic_dxf_writer_keeps_marker_and_legend_fallback(tmp_path):
    issue = FloorLoadDiagnosticIssue(
        story_name="",
        severity="ERROR",
        issue_type="SNAP_ERROR_EXCEEDED",
        message="raw",
        x=1.0,
        y=2.0,
        node_ids=[],
        element_ids=[],
        suggested_action="raw action",
    )

    path = write_floorload_diagnostic_dxf(output_path=tmp_path / "fallback.dxf", issues=[issue])

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    assert any(entity.dxf.layer == "FLOAD_DIAG_SNAP" for entity in list(msp.query("CIRCLE")) + list(msp.query("LINE")))
    text = _all_dxf_text(doc)
    assert "SNAP_ERROR_EXCEEDED" not in text
    assert "진단 범례" in text
    assert "스냅오류" in text


def test_diagnostic_dxf_writer_draws_model_geometry_without_issues(tmp_path):
    nodes = [Node(1, 0.0, 0.0, 0.0), Node(2, 6.0, 0.0, 0.0)]
    elements = [Element(10, "BEAM", node_ids=(1, 2))]

    path = write_floorload_diagnostic_dxf(
        output_path=tmp_path / "no_issues.dxf",
        issues=[],
        nodes=nodes,
        elements=elements,
        stories=[Story("1F", 0.0)],
    )

    doc = ezdxf.readfile(path)
    msp = doc.modelspace()
    assert any(entity.dxf.layer == "FLOAD_DIAG_MODEL_BEAM" for entity in msp.query("LINE"))
    assert any(entity.dxf.layer == "FLOAD_DIAG_STORY_LABEL" and entity.dxf.text == "1F" for entity in msp.query("TEXT"))
