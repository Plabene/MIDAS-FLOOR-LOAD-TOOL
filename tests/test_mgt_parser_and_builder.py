from app.core.floorload_mgt_builder import FloorLoadAssignment, patch_full_mgt_text
from app.core.mgt_parser import parse_elements_from_text, parse_nodes_from_text, parse_stories_from_text

SAMPLE = """
*UNIT
 KN, M, KCAL, C
*NODE
; iNO, X, Y, Z
 1, 0, 0, 0
 2, 5, 0, 0
 3, 5, 5, 0
 4, 0, 5, 0
*ELEMENT
 1, BEAM, 1, 1, 1, 2, 0, 0
 2, WALL, 1, 1, 1, 2, 3, 4, 1, 1, 0
*STORY
 NAME=1F, 0, YES, 0,0,0,0,0,0,0,0,1,1,0,0,0
*ENDDATA
"""


def test_parse_mgt_core_blocks():
    assert parse_stories_from_text(SAMPLE)[0].name == "1F"
    assert len(parse_nodes_from_text(SAMPLE)) == 4
    assert len(parse_elements_from_text(SAMPLE)) == 2


def test_patch_full_mgt_adds_floorload_blocks():
    assignment = FloorLoadAssignment("사무실", 1.2, 3.0, (1, 2, 3, 4), "LOAD_001", "HATCH", 25.0, "OK", tuple())
    patched = patch_full_mgt_text(SAMPLE, assignments=[assignment])
    assert "*FLOADTYPE" in patched
    assert "*FLOORLOAD" in patched
    assert "사무실" in patched
    assert "DL, -1.2, YES" in patched
    assert "LL, -3, NO" in patched
