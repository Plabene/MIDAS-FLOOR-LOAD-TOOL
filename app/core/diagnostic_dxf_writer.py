from __future__ import annotations

from pathlib import Path
from typing import Sequence

import ezdxf

from .model_floorload_diagnostics import FloorLoadDiagnosticIssue


def write_floorload_diagnostic_dxf(
    *,
    output_path: str | Path,
    issues: Sequence[FloorLoadDiagnosticIssue],
) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc = ezdxf.new("R2010")
    _ensure_layer(doc, "FLOAD_DIAG_ERROR", 1)
    _ensure_layer(doc, "FLOAD_DIAG_WARN", 2)
    _ensure_layer(doc, "FLOAD_DIAG_INFO", 5)
    _ensure_layer(doc, "FLOAD_DIAG_TEXT", 7)
    style_name = _ensure_korean_text_style(doc)
    msp = doc.modelspace()

    for index, issue in enumerate(issues, start=1):
        layer = _layer_for_severity(issue.severity)
        radius = 0.35 if issue.severity == "ERROR" else 0.25
        msp.add_circle((issue.x, issue.y), radius, dxfattribs={"layer": layer})
        msp.add_line((issue.x - radius, issue.y), (issue.x + radius, issue.y), dxfattribs={"layer": layer})
        msp.add_line((issue.x, issue.y - radius), (issue.x, issue.y + radius), dxfattribs={"layer": layer})
        label = f"{index}:{issue.story_name}:{issue.issue_type}"
        msp.add_text(
            label,
            dxfattribs={"layer": "FLOAD_DIAG_TEXT", "height": 0.25, "style": style_name},
        ).set_placement((issue.x + radius * 1.5, issue.y + radius * 1.5))

    doc.saveas(out)
    return out


def _ensure_layer(doc, name: str, color: int) -> None:
    if name not in doc.layers:
        doc.layers.add(name, color=color)


def _ensure_korean_text_style(doc) -> str:
    style_name = "MALGUN_GOTHIC"
    try:
        style = doc.styles.get(style_name)
    except Exception:
        style = doc.styles.new(style_name)
    try:
        style.dxf.font = "malgun.ttf"
    except Exception:
        pass
    return style_name


def _layer_for_severity(severity: str) -> str:
    value = str(severity or "").upper()
    if value == "ERROR":
        return "FLOAD_DIAG_ERROR"
    if value == "WARNING":
        return "FLOAD_DIAG_WARN"
    return "FLOAD_DIAG_INFO"
