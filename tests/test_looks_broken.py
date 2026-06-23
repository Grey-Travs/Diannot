"""looks_broken / heuristic_flags / scan_note_blocks — precision-first flagging (no live AI)."""
import diannot.structure as S
from diannot.models import (
    BannerBlock,
    BodyBlock,
    ImageBlock,
    ListBlock,
    ListItem,
    Note,
    ScriptHeadingBlock,
    TableBlock,
    TermDefinitionBlock,
)


# ---- looks_broken: must NOT flag well-formed content (precision is the whole point) --------------
def test_clean_blocks_are_not_flagged():
    assert S.looks_broken(BodyBlock(text="The **heart** pumps blood through the body.")) is None
    assert S.looks_broken(ScriptHeadingBlock(text="Circulation")) is None
    assert S.looks_broken(BannerBlock(text="Chapter 1")) is None
    assert S.looks_broken(ImageBlock(src="x.png")) is None
    assert S.looks_broken(TableBlock(headers=["A", "B"], rows=[["1", "2"], ["3", "4"]])) is None
    assert S.looks_broken(ListBlock(items=[ListItem(text="alpha"), ListItem(text="beta")])) is None
    assert S.looks_broken(TermDefinitionBlock(term="Mitosis", definition="cell division")) is None


def test_raw_text_wall_flagged():
    wall = BodyBlock(text="word " * 200)  # ~1000 chars, no ** bold structure
    assert S.looks_broken(wall) and "unstructured" in S.looks_broken(wall).lower()
    structured = BodyBlock(text="The **term** is important. " * 40)  # long but bolded -> not a wall
    assert S.looks_broken(structured) is None


def test_table_flattened_into_list_flagged():
    flat = ListBlock(items=[ListItem(text="Na | 11 | sodium"), ListItem(text="K | 19 | potassium"),
                            ListItem(text="Ca | 20 | calcium")])
    assert S.looks_broken(flat) and "table" in S.looks_broken(flat).lower()
    assert S.looks_broken(ListBlock(items=[ListItem(text="first"), ListItem(text="second"),
                                           ListItem(text="third")])) is None  # plain list is fine


def test_broken_math_flagged_but_currency_is_not():
    leaked = BodyBlock(text=r"The variance is \sigma^2 and the mean \bar{x} over n.")
    assert S.looks_broken(leaked) and "math" in S.looks_broken(leaked).lower()
    unbalanced = BodyBlock(text=r"The mean is $\bar{x} and the variance grows.")  # one unclosed $
    assert S.looks_broken(unbalanced) and "math" in S.looks_broken(unbalanced).lower()
    assert S.looks_broken(BodyBlock(text=r"Energy is $E=mc^2$ exactly.")) is None      # balanced math
    assert S.looks_broken(BodyBlock(text="It costs $5 for one and $10 for two.")) is None  # currency
    # precision: prose mentioning NON-math LaTeX commands must NOT flag (the review's concern)
    assert S.looks_broken(BodyBlock(text=r"In LaTeX use \section and \subsection for headings.")) is None
    # precision: escaped currency alongside real (balanced) math must NOT flag
    assert S.looks_broken(BodyBlock(text=r"It costs \$50 but the area is $\pi r^2$ exactly.")) is None


def test_ragged_table_flagged():
    ragged = TableBlock(headers=["A", "B", "C"], rows=[["1", "2"]])  # row narrower than headers
    assert S.looks_broken(ragged) and "table" in S.looks_broken(ragged).lower()


def test_heuristic_flags_empty_for_clean_note():
    note = Note(title="t", blocks=[
        BannerBlock(text="Ch"),
        BodyBlock(text="The **cell** is the basic unit of life."),
        TableBlock(headers=["A", "B"], rows=[["1", "2"]]),
        ListBlock(items=[ListItem(text="one"), ListItem(text="two")]),
    ])
    assert S.heuristic_flags(note) == {}   # the core anti-false-positive guarantee


def test_heuristic_flags_maps_indices():
    note = Note(title="t", blocks=[BodyBlock(text="ok **fine**"), BodyBlock(text="x" * 700)])
    flags = S.heuristic_flags(note)
    assert set(flags) == {1} and isinstance(flags[1], str)


# ---- scan_note_blocks: one advisory AI call, robust to junk (never raises) ------------------------
def _mock_gen(monkeypatch, reply):
    def fake(prompt, model, settings, provider, system):
        return reply, []
    monkeypatch.setattr(S, "_gen_text", fake)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)


def _note():
    return Note(title="t", blocks=[BannerBlock(text="Ch"), BodyBlock(text="a"), BodyBlock(text="b")])


def test_scan_maps_broken_indices(monkeypatch):
    _mock_gen(monkeypatch, '{"broken":[{"i":2,"reason":"raw wall"}]}')
    assert S.scan_note_blocks(_note()) == {2: "raw wall"}


def test_scan_drops_out_of_range_and_junk(monkeypatch):
    _mock_gen(monkeypatch, '{"broken":[{"i":99,"reason":"x"},{"i":1,"reason":"ok"},{"nope":1}]}')
    assert S.scan_note_blocks(_note()) == {1: "ok"}


def test_scan_empty_or_malformed_returns_empty(monkeypatch):
    _mock_gen(monkeypatch, '{"broken":[]}')
    assert S.scan_note_blocks(_note()) == {}
    _mock_gen(monkeypatch, "not json at all")
    assert S.scan_note_blocks(_note(), max_retries=0) == {}
