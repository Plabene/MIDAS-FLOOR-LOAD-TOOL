from app.core.floorload_mgt_builder import (
    FloorLoadAssignment,
    _format_floorload_record_lines,
    patch_full_mgt_text,
)


def _two_way_prefix(load_name: str = "RoofLoad") -> list[str]:
    return [load_name, "2", "0", "0", "0", "0", "GZ", "NO", "", "NO", "YES", ""]


def test_floorload_record_with_many_nodes_uses_mgt_continuation():
    lines = _format_floorload_record_lines(
        prefix_fields=_two_way_prefix(),
        node_ids=tuple(range(1, 35)),
    )

    assert len(lines) > 1
    assert lines[0].rstrip().endswith("\\")
    assert any(line.startswith("        ") for line in lines[1:])
    assert all("," in line for line in lines)


def test_floorload_record_with_six_nodes_stays_one_line():
    lines = _format_floorload_record_lines(
        prefix_fields=_two_way_prefix(),
        node_ids=(989, 978, 972, 1010, 1008, 1007),
    )

    assert lines == ["   RoofLoad, 2, 0, 0, 0, 0, GZ, NO, , NO, YES, , 989, 978, 972, 1010, 1008, 1007"]
    assert not lines[0].rstrip().endswith("\\")


def test_mgt_floorload_record_does_not_include_dxf_layer_name():
    assignment = FloorLoadAssignment(
        "RoofLoad",
        8.6,
        1.0,
        (1, 2, 3, 4),
        "LOAD_001_RoofLoad_DL_8.6_LL_1",
        "HATCH",
        28.77,
        "OK",
        (),
    )

    patched_mgt = patch_full_mgt_text("*ENDDATA", assignments=[assignment])

    assert "LOAD_001_" not in patched_mgt
    assert "DXF_AUTO layer=" not in patched_mgt
    assert "DXF_FLOORLOAD" not in patched_mgt


def test_generated_floorload_line_does_not_put_34_nodes_on_one_physical_line():
    assignment = FloorLoadAssignment(
        "RoofLoad",
        8.6,
        1.0,
        tuple(range(1, 35)),
        "LOAD_001_RoofLoad_DL_8.6_LL_1",
        "HATCH",
        28.77,
        "OK",
        (),
    )

    patched_mgt = patch_full_mgt_text("*ENDDATA", assignments=[assignment])
    floorload_lines = []
    in_floorload = False
    for line in patched_mgt.splitlines():
        head = line.strip().split(None, 1)[0].upper() if line.strip().startswith("*") else ""
        if head == "*FLOORLOAD":
            in_floorload = True
            continue
        if in_floorload and head:
            in_floorload = False
        if in_floorload and line.strip() and not line.lstrip().startswith(";"):
            floorload_lines.append(line)

    assert len(floorload_lines) > 1
    for line in floorload_lines:
        assert line.count(",") <= 24 or line.rstrip().endswith("\\")
