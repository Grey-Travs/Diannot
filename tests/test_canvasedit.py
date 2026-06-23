"""Canvas editor round-trip: note_to_canvas / apply_box / find_index (pure, no browser)."""
from diannot.models import BodyBlock, Box, ImageBlock, Note
from diannot.studio.canvasedit import apply_box, default_box, find_index, note_to_canvas


def _note():
    return Note(title="C", layout_mode="canvas", blocks=[
        BodyBlock(text="alpha **beta**"),
        ImageBlock(src="p.png", caption="a figure"),
    ])


def test_note_to_canvas_assigns_ids_and_boxes():
    note = _note()
    boxes = note_to_canvas(note)
    assert len(boxes) == 2
    # every block now has a stable id + a box, and the seed carries geometry + a label
    assert all(b.id for b in note.blocks) and all(b.box for b in note.blocks)
    assert boxes[0]["label"] == "alpha beta"        # markdown stripped for the label
    assert boxes[1]["type"] == "image" and boxes[1]["label"] == "a figure"
    assert {"id", "type", "label", "x", "y", "w", "h", "z"} <= set(boxes[0])


def test_note_to_canvas_preserves_existing_boxes():
    note = Note(title="C", layout_mode="canvas",
                blocks=[BodyBlock(text="x", id="keep", box=Box(x=12, y=34, w=20, h=8, z=3))])
    note_to_canvas(note)
    assert note.blocks[0].id == "keep"
    assert note.blocks[0].box.x == 12 and note.blocks[0].box.z == 3  # untouched


def test_apply_box_updates_by_id_and_roundtrips():
    note = _note()
    note_to_canvas(note)  # assign ids
    bid = note.blocks[1].id
    assert apply_box(note, bid, 25.5, 40.0, 30.0, 18.0, 5)
    box = note.blocks[1].box
    assert (box.x, box.y, box.w, box.h, box.z) == (25.5, 40.0, 30.0, 18.0, 5)
    # the change survives a full JSON round-trip
    back = Note.model_validate_json(note.model_dump_json())
    assert back.blocks[1].box.x == 25.5 and back.blocks[1].box.z == 5
    assert not apply_box(note, "no-such-id", 0, 0, 1, 1, 0)


def test_apply_box_clamps_garbage():
    # a buggy/hostile client can't push Infinity/NaN/out-of-range geometry into the saved note
    note = _note()
    note_to_canvas(note)
    bid = note.blocks[0].id
    assert apply_box(note, bid, float("inf"), float("nan"), 1e9, -5, 2)
    box = note.blocks[0].box
    assert box.x == 0.0 and box.y == 0.0          # inf/nan -> default 0
    assert box.w == 100.0 and box.h == 1.0        # 1e9 -> 100, -5 -> min 1
    assert box.z == 2
    # and a non-int z falls back to 0 without raising
    assert apply_box(note, bid, 10, 10, 20, 10, "oops")
    assert note.blocks[0].box.z == 0


def test_find_index_and_default_box():
    note = _note()
    note_to_canvas(note)
    assert find_index(note, note.blocks[0].id) == 0
    assert find_index(note, None) == -1 and find_index(note, "missing") == -1
    # default boxes stack down the page, wrapping to a second column after 6
    assert default_box(0).y < default_box(1).y
    assert default_box(6).x > default_box(0).x
