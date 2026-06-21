"""Editor.js <-> Diannot block round-trip mapping (the document editor's core)."""
from pathlib import Path

import pytest

from diannot.models import (
    BodyBlock,
    CalloutBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    Note,
    TableBlock,
    TermDefinitionBlock,
)
from diannot.studio.docedit import (
    _html_to_md,
    _md_to_html,
    editor_to_blocks,
    note_to_editor,
)

_SAMPLES = sorted(Path("examples/sample_notebook").glob("*.note.json"))


@pytest.mark.parametrize("path", _SAMPLES, ids=lambda p: p.name)
def test_sample_notes_round_trip_lossless(path):
    note = Note.model_validate_json(path.read_text(encoding="utf-8"))
    assert editor_to_blocks(note_to_editor(note)) == note.blocks


def test_sample_notes_exist():
    assert _SAMPLES, "no sample notes found to round-trip"


def test_bold_inline_round_trips():
    assert _html_to_md(_md_to_html("a **b** c & <x>")) == "a **b** c & <x>"


def test_body_and_term_definition_round_trip():
    n = Note(title="T", blocks=[
        BodyBlock(text="Blood is **red**."),
        TermDefinitionBlock(term="Plasma", definition="the **liquid** matrix"),
    ])
    assert editor_to_blocks(note_to_editor(n)) == n.blocks


def test_list_table_image_quote_with_meta_round_trip():
    n = Note(title="T", blocks=[
        ListBlock(ordered=True, items=[ListItem(text="one", children=[ListItem(text="sub")]),
                                       ListItem(text="two")]),
        TableBlock(headers=["A", "B"], rows=[["1", "**2**"]], caption="cap"),
        ImageBlock(src="/x.png", caption="c", source_credit="me", width=60, layout="col1"),
        TermDefinitionBlock(term="X", definition="y", confidence="low", source_page=3),
    ])
    assert editor_to_blocks(note_to_editor(n)) == n.blocks


def test_callout_passthrough_round_trip():
    n = Note(title="T", blocks=[
        CalloutBlock(variant="warning", title="Careful", items=["a", "b"], layout="full"),
    ])
    assert editor_to_blocks(note_to_editor(n)) == n.blocks


def test_newly_typed_term_def_paragraph_promotes():
    payload = {"blocks": [{"type": "paragraph", "data": {"text": _md_to_html("**Ion** — a charged atom")}}]}
    blocks = editor_to_blocks(payload)
    assert len(blocks) == 1
    assert blocks[0].type == "term_definition"
    assert blocks[0].term == "Ion" and blocks[0].definition == "a charged atom"


def test_column_tune_sets_layout():
    payload = {"blocks": [{"type": "paragraph", "data": {"text": "hi"}, "tunes": {"dn": {"layout": "col2"}}}]}
    assert editor_to_blocks(payload)[0].layout == "col2"
