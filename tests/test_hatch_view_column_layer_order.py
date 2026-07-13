from app.main import FloorLoadAutoApp


def test_structure_items_split_columns_to_top_layer():
    app = object.__new__(FloorLoadAutoApp)

    background, columns = app._split_structure_items_for_layering(
        [
            {"kind": "BEAM", "element_id": 1},
            {"kind": "COLUMN", "element_id": 2},
            {"kind": "WALL", "element_id": 3},
        ]
    )

    assert [item["element_id"] for item in background] == [1, 3]
    assert [item["element_id"] for item in columns] == [2]


def test_column_draw_tags_are_raiseable_without_region_hit_test_tags():
    app = object.__new__(FloorLoadAutoApp)
    canvas = _Canvas()

    app._draw_hatch_structure_items(
        canvas,
        [{"kind": "COLUMN", "points": [(0.0, 0.0)], "width": None, "depth": None}],
        lambda x, y: (x, y),
    )
    canvas.tag_raise("structure:COLUMN")
    canvas.tag_raise("structure_marker")

    tag_sets = [call["kwargs"]["tags"] for call in canvas.calls if "tags" in call["kwargs"]]
    assert all(not any(str(tag).startswith(("region:", "edit_region:")) for tag in tags) for tags in tag_sets)
    assert ("structure:COLUMN", "structure_marker") == tuple(canvas.raised)


class _Canvas:
    def __init__(self):
        self.calls = []
        self.raised = []

    def create_line(self, *args, **kwargs):
        self.calls.append({"kind": "line", "args": args, "kwargs": kwargs})

    def create_polygon(self, *args, **kwargs):
        self.calls.append({"kind": "polygon", "args": args, "kwargs": kwargs})

    def create_rectangle(self, *args, **kwargs):
        self.calls.append({"kind": "rectangle", "args": args, "kwargs": kwargs})

    def create_oval(self, *args, **kwargs):
        self.calls.append({"kind": "oval", "args": args, "kwargs": kwargs})

    def tag_raise(self, tag):
        self.raised.append(tag)
