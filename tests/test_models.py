"""Block model validation and JSON round-tripping."""
import pytest
from pydantic import ValidationError

from diannot.models import (
    BannerBlock,
    BodyBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    Note,
    TableBlock,
    TermDefinitionBlock,
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
