from app.main import DummyConnectionPlan, DummyDisplayMember, FloorLoadAutoApp
from app.core.mgt_parser import parse_existing_load_dm_members


class Canvas:
    def __init__(self):
        self.next_id = 1
        self.lines = []
        self.ovals = []
        self.deleted = []

    def create_line(self, *coords, **options):
        item = self.next_id
        self.next_id += 1
        self.lines.append((item, coords, options))
        return item

    def create_oval(self, *coords, **options):
        item = self.next_id
        self.next_id += 1
        self.ovals.append((item, coords, options))
        return item

    def delete(self, item):
        self.deleted.append(item)

    def tag_raise(self, _tag):
        return None


def _app():
    app = object.__new__(FloorLoadAutoApp)
    app.committed_dummy_members = {
        100: DummyDisplayMember("element:100", "1F", 1, 2, (0, 0), (5, 0), 100, "COMMITTED_EXISTING", "CURRENT_MGT")
    }
    app.approved_dummy_plans = {
        "I1": DummyConnectionPlan("I1", "1F", 3, 4, (0, 2), (5, 2), 5, approved=True),
        "I3": DummyConnectionPlan("I3", "1F", 7, 8, (0, 6), (5, 6), 5, collision_reason="INTERSECTS", approved=True),
    }
    app.dummy_preview_plan = DummyConnectionPlan("I2", "1F", 5, 6, (0, 4), (5, 4), 5)
    app.dummy_member_canvas_items = {}
    app._hatch_view_story_filter = lambda: "1F"
    app._hatch_view_is_all_story_display = lambda: False
    return app


def test_state_styles_are_distinct_and_story_filter_is_respected():
    app = _app()
    canvas = Canvas()
    app._draw_dummy_member_overlay(canvas, lambda x, y: (x, y), {}, phase="all")
    styles = {next(tag for tag in options["tags"] if tag.startswith("dummy_state:")): options for _id, _coords, options in canvas.lines}
    assert styles["dummy_state:PREVIEW"]["fill"] == "#f97316"
    assert styles["dummy_state:PREVIEW"]["dash"]
    assert styles["dummy_state:APPROVED_PENDING"]["fill"] == "#7c3aed"
    assert styles["dummy_state:COMMITTED_EXISTING"]["fill"] == "#0f766e"
    assert styles["dummy_state:INVALID"]["fill"] == "#dc2626"
    assert styles["dummy_state:INVALID"]["dash"]
    assert len(app.dummy_member_canvas_items) == 4

    app._hatch_view_story_filter = lambda: "2F"
    hidden = Canvas()
    app.dummy_member_canvas_items = {}
    app._draw_dummy_member_overlay(hidden, lambda x, y: (x, y), {}, phase="all")
    assert hidden.lines == []


def test_existing_mgt_load_dm_is_reconstructed_with_release_warning_policy():
    text = """
*STORY
 NAME=1F, 0
*NODE
 1, 0, 0, 0
 2, 5, 0, 0
*MATERIAL
 9999, CONC, LOAD DM
*SECTION
 9999, DBUSER, LOAD DM, CC, 0, 0, 0, 0, 0, 0, YES, NO, SB, 2, 0.003, 0.003
*ELEMENT
 100, BEAM, 9999, 9999, 1, 2, 0, 0
*FRAME-RLS
 100, NO, 000011, 0, 0, 0, 0, 0, 0
      000011, 0, 0, 0, 0, 0, 0,
*ENDDATA
"""
    members = parse_existing_load_dm_members(text)
    assert len(members) == 1
    assert members[0].element_id == 100
    assert members[0].story_name == "1F"
    assert members[0].warnings == ()


def test_incremental_update_replaces_only_changed_member_items():
    app = _app()
    canvas = Canvas()
    app.hatch_preview_canvas = canvas
    app._dummy_last_render_transform = lambda x, y: (x, y)
    app._dummy_last_story_offsets = {}
    app.dummy_issue_by_key = {}
    app.dummy_issue_canvas_items = {}
    app.dummy_overlay_render_fingerprint = None
    app.dummy_overlay_member_fingerprint_by_key = {}

    app._update_dummy_member_overlay()
    committed_ids = app.dummy_member_canvas_items["element:100"]
    canvas.deleted.clear()
    app.dummy_preview_plan = DummyConnectionPlan("I2", "1F", 5, 6, (0, 4), (6, 4), 6)
    app._update_dummy_member_overlay()

    assert not set(committed_ids).intersection(canvas.deleted)
    assert len(canvas.deleted) == 3
