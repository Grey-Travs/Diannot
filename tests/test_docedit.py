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


def _kitchen_sink() -> "Note":
    from diannot.models import (
        BannerBlock,
        CalloutBlock,
        DiagramBlock,
        QuoteBlock,
        ScriptHeadingBlock,
        SubheadingBlock,
    )
    return Note(title="Everything", theme="histology", pack="pro_infographic", blocks=[
        BannerBlock(text="Tissues 101", subtitle="A & B <x>", images=["/a.png", "/b.png"]),
        ScriptHeadingBlock(text="Section"),
        SubheadingBlock(text="Caps one", caps=True),
        SubheadingBlock(text="Plain two", caps=False),
        BodyBlock(text="plain & <x> with **bold** and a lone * star"),
        BodyBlock(text="**Looks** — like a term-def but it IS a body", layout="col1"),
        TermDefinitionBlock(term="Plasma", definition="the **liquid** matrix — really"),
        TermDefinitionBlock(term="X", definition="y", confidence="low", source_page=3, layout="col2"),
        ListBlock(ordered=True, items=[ListItem(text="**a**", children=[ListItem(text="a1"),
                                                                        ListItem(text="a2")]),
                                       ListItem(text="b")]),
        ListBlock(ordered=False, items=[ListItem(text="only")]),
        TableBlock(headers=["A", "B"], rows=[["1", "**2**"], ["3", "4"]], caption="cap"),
        ImageBlock(src="/file?path=x.png", alt="alt", caption="cap **c**",
                   source_credit="me", width=60, layout="col1"),
        ImageBlock(src="/y.png"),
        DiagramBlock(mermaid="graph TD; A-->B", caption="flow"),
        CalloutBlock(variant="tutor_tip", title="Tip", body="some **body** text"),
        CalloutBlock(variant="warning", items=["a", "b"]),
        CalloutBlock(variant="key_points"),
        QuoteBlock(text="quote **q**", attribution="Author"),
        QuoteBlock(text="no attribution"),
    ])


def test_kitchen_sink_round_trips_lossless():
    """Every block type + many field combos survive note -> editor -> note exactly."""
    n = _kitchen_sink()
    assert editor_to_blocks(note_to_editor(n)) == n.blocks


def test_existing_body_that_looks_like_term_def_stays_body():
    """A BODY whose text matches the term-def pattern must NOT be promoted on round-trip."""
    n = Note(title="T", blocks=[BodyBlock(text="**Note** — see chapter 3")])
    out = editor_to_blocks(note_to_editor(n))
    assert out[0].type == "body" and out == n.blocks


def test_text_with_html_and_specials_round_trips():
    for s in ["use <b>literal</b> tags", "a & b < c > d", "back\\slash and 100%",
              "unbalanced ** marker", "emoji 🧪 and — dash"]:
        n = Note(title="T", blocks=[BodyBlock(text=s)])
        assert editor_to_blocks(note_to_editor(n))[0].text == s


def test_empty_blocks_payload_returns_empty():
    assert editor_to_blocks({"blocks": []}) == []
    assert editor_to_blocks({}) == []


def test_hyphenated_bold_word_is_not_promoted_to_term_def():
    """A fresh paragraph that starts with a bold word + hyphen must stay a body (no data loss)."""
    for txt in ["**Note**-taking is a useful skill", "**Cost**-effective methods",
                "**Step**-by-step guide", "**Well** - spaced hyphen is still a body"]:
        payload = {"blocks": [{"type": "paragraph", "data": {"text": _md_to_html(txt)}}]}
        out = editor_to_blocks(payload)
        assert out[0].type == "body", txt
        assert out[0].text == txt


def test_em_dash_paragraph_still_promotes_to_term_def():
    payload = {"blocks": [{"type": "paragraph", "data": {"text": _md_to_html("**Ion** — a charged atom")}}]}
    assert editor_to_blocks(payload)[0].type == "term_definition"


def test_recovery_fallback_reads_dn_meta_on_validation_failure():
    """If a block can't validate, recover the preserved original from the dn tune (not drop it)."""
    payload = {"blocks": [{"type": "paragraph", "data": {"text": "edited"},
                           "tunes": {"dn": {"layout": "not-a-real-layout",
                                            "meta": {"type": "body", "text": "preserved",
                                                     "layout": "auto"}}}}]}
    out = editor_to_blocks(payload)
    assert len(out) == 1 and out[0].type == "body" and out[0].text == "preserved"


def test_multiline_body_round_trips():
    n = Note(title="T", blocks=[BodyBlock(text="line one\nline two with **bold**")])
    assert editor_to_blocks(note_to_editor(n)) == n.blocks
