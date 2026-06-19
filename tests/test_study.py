"""Study features: flashcards, SM-2, glossary, full-text search."""
from datetime import date

from diannot.cards import Card, Deck, card_id, cards_from_note, merge_cards
from diannot.glossary import build_glossary, load_notes
from diannot.models import BannerBlock, Note, TermDefinitionBlock
from diannot.search import build_index, search
from diannot.srs import deck_stats, is_due, review_card


def _note():
    return Note(
        title="Heart",
        theme="circulatory",
        blocks=[
            BannerBlock(text="Heart"),
            TermDefinitionBlock(term="Myocardium", definition="the **middle** layer"),
            TermDefinitionBlock(term="Atria", definition="upper chambers"),
        ],
    )


def test_cards_extraction():
    cards = cards_from_note(_note())
    assert len(cards) == 2
    assert cards[0].front == "Myocardium"
    assert "middle" in cards[0].back and "**" not in cards[0].back  # markdown stripped
    assert cards[0].id == card_id("Myocardium")


def test_merge_preserves_srs_state():
    deck = Deck(name="d", cards=[Card(id=card_id("Myocardium"), front="Myocardium", back="x", reps=5)])
    merge_cards(deck, cards_from_note(_note()))
    assert len(deck.cards) == 2  # Atria added; Myocardium not duplicated
    myo = next(c for c in deck.cards if c.front == "Myocardium")
    assert myo.reps == 5  # existing review state kept


def test_sm2_scheduling():
    t = date(2026, 6, 19)
    c = Card(id="x", front="f", back="b")
    assert is_due(c, t)  # new card
    review_card(c, 4, t)
    assert c.interval == 1 and c.reps == 1
    review_card(c, 4, t)
    assert c.interval == 6
    review_card(c, 1, t)  # lapse
    assert c.interval == 1 and c.lapses == 1 and c.ease < 2.5


def test_deck_stats():
    t = date(2026, 6, 19)
    deck = Deck(name="d", cards=[Card(id="a", front="a", back="b")])
    assert deck_stats(deck, t)["new"] == 1


def test_glossary_dedupe_and_sort():
    g = build_glossary([_note(), _note()], title="G")
    terms = [b for b in g.blocks if b.type == "term_definition"]
    assert len(terms) == 2  # deduped across two identical notes
    assert terms[0].term == "Atria"  # alphabetized


def test_load_notes_skips_non_notes(tmp_path):
    (tmp_path / "n.note.json").write_text(_note().model_dump_json(), encoding="utf-8")
    (tmp_path / "deck.json").write_text('{"name":"d","cards":[]}', encoding="utf-8")
    notes = load_notes(tmp_path)
    assert len(notes) == 1 and notes[0].title == "Heart"


def test_fts_search(tmp_path):
    (tmp_path / "h.note.json").write_text(_note().model_dump_json(), encoding="utf-8")
    db = tmp_path / "idx.db"
    assert build_index(tmp_path, db) >= 2
    results = search("myocardium", db)
    assert results and "Myocardium" in results[0]["snippet"]
