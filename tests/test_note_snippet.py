"""The editor's one-line block summary (_snippet)."""
from diannot.models import (
    BannerBlock,
    BodyBlock,
    CalloutBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    TableBlock,
    TermDefinitionBlock,
)
from diannot.studio.pages.note import _snippet


def test_snippet_per_type():
    assert _snippet(BannerBlock(text="Hello")) == "Hello"
    assert _snippet(BodyBlock(text="a **bold** word")) == "a bold word"  # markdown stripped
    assert _snippet(TermDefinitionBlock(term="RBC", definition="red cell")) == "RBC — red cell"
    assert _snippet(ListBlock(items=[ListItem(text="one"), ListItem(text="two")])) == "one  (+1)"
    assert _snippet(TableBlock(headers=["A", "B"], rows=[["1", "2"]])) == "table 1×2"
    assert _snippet(ImageBlock(src="x.png")) == "x.png"
    assert _snippet(CalloutBlock(variant="warning")) == "warning"


def test_snippet_truncates_and_falls_back():
    out = _snippet(BodyBlock(text="x" * 100))
    assert out.endswith("…") and len(out) == 61
    assert _snippet(BodyBlock(text="")) == "body"  # empty -> block type
