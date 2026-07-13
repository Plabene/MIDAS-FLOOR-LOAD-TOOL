from app.core.mgt_import_validator import (
    MgtImportCapabilities,
    iter_mgt_logical_records,
    validate_mgt_for_import,
)
from app.core.floorload_mgt_builder import FloorLoadAssignment, merge_adjacent_floorload_assignments
from app.core.mgt_parser import Node


def _model(floorload_lines: list[str]) -> str:
    return "\r\n".join(
        [
            "*UNIT",
            "   N, MM, KJ, C",
            "*MATERIAL",
            "   1, CONC, C30",
            "*SECTION",
            "   1, DBUSER, B1",
            "*NODE",
            *[f"   {node_id}, {x}, {y}, 0" for node_id, (x, y) in enumerate(((0, 0), (1, 0), (2, 0), (2, 1), (1, 2), (0, 1)), start=1)],
            "*ELEMENT",
            "   1, BEAM, 1, 1, 1, 2",
            "*STORY",
            "   1F, 0, 3",
            "*STLDCASE",
            "   DL, D",
            "*FLOADTYPE",
            "   Roof,",
            "   DL, -1, YES",
            "*FLOORLOAD",
            *floorload_lines,
            "*ENDDATA",
            "",
        ]
    )


def _capabilities(limit: int) -> MgtImportCapabilities:
    return MgtImportCapabilities(max_logical_fields_by_command={"FLOORLOAD": limit}, text_encoding="utf-8")


def test_wrapped_floorload_is_checked_as_one_logical_record():
    text = _model(
        [
            "   Roof, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, 3, \\",
            "        4, 5, 6",
        ]
    )

    records = [record for record in iter_mgt_logical_records(text) if record.section_name == "FLOORLOAD"]
    result = validate_mgt_for_import(text, capabilities=_capabilities(16))

    assert len(records) == 1
    assert records[0].continued
    assert len(records[0].fields) == 18
    assert records[0].physical_end_line == records[0].physical_start_line + 1
    assert {issue.code for issue in result.issues} >= {
        "FLOORLOAD_LOGICAL_FIELD_LIMIT_EXCEEDED",
        "FLOORLOAD_NODE_LIMIT_EXCEEDED",
    }


def test_physical_wrapping_passes_when_logical_record_is_within_limit():
    text = _model(
        [
            "   Roof, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 1, 2, \\",
            "        3, 4",
        ]
    )

    result = validate_mgt_for_import(text, capabilities=_capabilities(16))

    assert not any("LIMIT_EXCEEDED" in issue.code for issue in result.issues)
    assert not result.has_errors


def test_connected_component_is_partitioned_before_oversized_merge():
    coordinates = {
        1: (0, 0), 2: (1, 0), 3: (1, 1), 4: (0, 1),
        5: (2, 0), 6: (2, 1), 7: (2, 2), 8: (1, 2),
    }
    nodes = [Node(node_id, x, y, 0.0) for node_id, (x, y) in coordinates.items()]
    assignments = [
        _assignment((1, 2, 3, 4), ((0, 0), (1, 0), (1, 1), (0, 1)), "A"),
        _assignment((2, 5, 6, 3), ((1, 0), (2, 0), (2, 1), (1, 1)), "B"),
        _assignment((3, 6, 7, 8), ((1, 1), (2, 1), (2, 2), (1, 2)), "C"),
    ]

    merged = merge_adjacent_floorload_assignments(
        assignments,
        story_nodes=nodes,
        snap_tolerance=0.01,
        capabilities=_capabilities(16),
    )

    assert len(merged) == 2
    assert all(len(item.node_ids) <= 4 for item in merged)
    assert sum(item.area for item in merged) == 3.0
    assert sum(item.merged_source_count for item in merged) == 3


def _assignment(node_ids, vertices, source_id):
    return FloorLoadAssignment(
        load_type_name="Roof",
        dl=1.0,
        ll=0.0,
        node_ids=tuple(node_ids),
        source_layer="LOAD",
        source_type="HATCH",
        area=1.0,
        status="OK",
        warnings=(),
        story_name="1F",
        source_id=source_id,
        polygon_vertices=tuple(vertices),
    )
