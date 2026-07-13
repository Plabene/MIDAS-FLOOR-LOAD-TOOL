from types import SimpleNamespace

from app.core.dummy_member_generator import generate_load_dm_dummy_members
from app.core.mgt_parser import parse_existing_load_dm_members


def _assignment():
    return SimpleNamespace(
        story_name="1F",
        source_id="R1",
        load_type_name="Office",
        node_ids=(1, 2, 3, 4),
        polygon_vertices=((0, 0), (10, 0), (10, 10), (0, 10)),
        status="OK",
    )


def _mgt(extra_nodes="", extra_elements=""):
    return f"""
*UNIT
 KN, M, KJ, C
*STORY
 NAME=1F, 0
*NODE
 1, 0, 0, 0
 2, 10, 0, 0
 3, 10, 10, 0
 4, 0, 10, 0
 5, 5, 5, 0
 6, 5, 7, 0
{extra_nodes}
*ELEMENT
 1, BEAM, 1, 2, 6, 5, 0, 0
 10, BEAM, 1, 2, 1, 2, 0, 0
 11, BEAM, 1, 2, 2, 3, 0, 0
 12, BEAM, 1, 2, 3, 4, 0, 0
 13, BEAM, 1, 2, 4, 1, 0, 0
{extra_elements}
*MATERIAL
 1, CONC, DM, 0, 0, , C, NO, 0.05, 2, 2.5e7, 0.167, 1e-5, 0, 2.4
*SECTION
 1, DBUSER, DM, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.0001, 0.0001, 0, 0
 2, DBUSER, B600X800, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.8, 0.6, 0, 0
*ENDDATA
"""


def _created_for_free(summary, free_node_id=5):
    return next(record for record in summary.records if record.status == "CREATED" and record.free_node_id == free_node_id)


def test_beam_actual_width_blocks_parallel_near_path_and_uses_next_candidate():
    text = _mgt(
        extra_nodes=" 7, 0, 0.3, 0\n 8, 4.7, 5, 0",
        extra_elements=" 20, BEAM, 1, 2, 7, 8, 0, 0",
    )
    record = _created_for_free(generate_load_dm_dummy_members(mgt_text=text, assignments=[_assignment()]))
    assert record.boundary_node_id != 1


def test_column_footprint_and_wall_thickness_block_nearest_path():
    column_text = _mgt(
        extra_nodes=" 7, 2.5, 2.5, 0\n 8, 2.5, 2.5, 3",
        extra_elements=" 20, COLUMN, 1, 2, 7, 8, 30, 0",
    )
    assert _created_for_free(generate_load_dm_dummy_members(mgt_text=column_text, assignments=[_assignment()])).boundary_node_id != 1

    wall_text = _mgt(
        extra_nodes=" 7, 1.5, 2.0, 0\n 8, 3.5, 3.0, 0",
        extra_elements=" 20, WALL, 1, 2, 7, 8, 0, 0",
    )
    assert _created_for_free(generate_load_dm_dummy_members(mgt_text=wall_text, assignments=[_assignment()])).boundary_node_id != 1


def test_horizontal_slab_is_not_false_obstacle_and_max_length_is_enforced():
    slab_text = _mgt(extra_elements=" 20, PLATE, 1, 2, 1, 2, 3, 4")
    assert _created_for_free(generate_load_dm_dummy_members(mgt_text=slab_text, assignments=[_assignment()])).boundary_node_id == 1

    limited = generate_load_dm_dummy_members(mgt_text=_mgt(), assignments=[_assignment()], max_dummy_length=2.0)
    assert limited.created_count == 0
    assert any(record.interference_reason == "DUMMY_LENGTH_EXCEEDS_MAXIMUM" for record in limited.records)


def test_generated_patch_reparses_with_both_end_release():
    summary = generate_load_dm_dummy_members(mgt_text=_mgt(), assignments=[_assignment()])
    assert summary.created_count == 1
    members = parse_existing_load_dm_members(summary.patched_text)
    assert len(members) == 1
    assert members[0].release is not None
    assert members[0].warnings == ()
