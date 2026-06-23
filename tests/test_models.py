"""Block model validation and JSON round-tripping."""
import pytest
from pydantic import ValidationError

from diannot.models import (
    BannerBlock,
    BodyBlock,
    Box,
    ImageBlock,
    ListBlock,
    ListItem,
    Note,
    TableBlock,
    TermDefinitionBlock,
    ensure_ids,
)


def test_image_width_optional_and_bounded():
    assert ImageBlock(src="x").width is None
    assert ImageBlock(src="x", width=50).width == 50
    with pytest.raises(ValidationError):
        ImageBlock(src="x", width=5)
    with pytest.raises(ValidationError):
        ImageBlock(src="x", width=200)


def test_column_layout_values_accepted():
    assert BodyBlock(text="x", layout="col1").layout == "col1"
    assert BodyBlock(text="x", layout="col2").layout == "col2"


def test_note_roundtrip():
    note = Note(
        title="T",
        theme="circulatory",
        blocks=[
            BannerBlock(text="B"),
            BodyBlock(text="hello **world**"),
            TermDefinitionBlock(term="X", definition="y"),
            ListBlock(items=[ListItem(text="a", children=[ListItem(text="b")])]),
            TableBlock(headers=["h"], rows=[["c"]]),
        ],
    )
    back = Note.model_validate_json(note.model_dump_json())
    assert back == note
    assert back.blocks[0].layout == "full"  # banner defaults to full-width


def test_discriminated_union_by_type():
    note = Note.model_validate({"title": "t", "blocks": [{"type": "body", "text": "x"}]})
    assert isinstance(note.blocks[0], BodyBlock)


def test_optional_provenance_and_confidence():
    assert BodyBlock(text="x").confidence is None
    b = BodyBlock(text="x", confidence="low", source_page=3)
    assert b.confidence == "low" and b.source_page == 3


def test_note_extra_forbidden():
    with pytest.raises(ValidationError):
        Note.model_validate({"title": "t", "blocks": [], "bogus": 1})


def test_layout_mode_defaults_to_flow():
    # An old note JSON with no layout_mode / id / box must still load (backward-compat).
    note = Note.model_validate({"title": "t", "blocks": [{"type": "body", "text": "x"}]})
    assert note.layout_mode == "flow"
    assert note.blocks[0].id is None and note.blocks[0].box is None
    # ...and re-serializing with exclude_none keeps flow blocks free of canvas noise.
    dumped = note.model_dump_json(exclude_none=True)
    assert '"box"' not in dumped and '"id"' not in dumped


def test_canvas_note_roundtrip():
    note = Note(
        title="Canvas",
        layout_mode="canvas",
        blocks=[
            BodyBlock(text="free **text**", id="b1", box=Box(x=10, y=20, w=40, h=15, z=2)),
            ImageBlock(src="p.png", id="b2", box=Box(x=55, y=5, w=35, h=30)),
        ],
    )
    back = Note.model_validate_json(note.model_dump_json())
    assert back == note
    assert back.layout_mode == "canvas"
    assert back.blocks[0].box.x == 10 and back.blocks[0].box.z == 2
    assert back.blocks[1].box.h == 30 and back.blocks[1].box.z == 0  # z defaults to 0


def test_ensure_ids_assigns_and_is_stable():
    note = Note(title="t", blocks=[BodyBlock(text="a"), BodyBlock(text="b", id="keep")])
    ensure_ids(note)
    ids = [b.id for b in note.blocks]
    assert all(ids) and ids[1] == "keep" and ids[0] != ids[1]
    ensure_ids(note)  # idempotent — existing ids are not regenerated
    assert [b.id for b in note.blocks] == ids
