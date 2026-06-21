"""FTS5 search: no crashes on special characters, and nested list items are searchable."""
from diannot.models import BodyBlock, ListBlock, ListItem, Note
from diannot.search import _fts_query, build_index, search


def _write(tmp_path, name, note):
    p = tmp_path / name
    p.write_text(note.model_dump_json(), encoding="utf-8")
    return p


def test_fts_query_neutralizes_special_characters():
    for q in ["C++", "a AND b", 'foo"', "$x$", "AND", "(test)", ""]:
        assert isinstance(_fts_query(q), str)  # never raises


def test_search_special_char_queries_do_not_crash(tmp_path):
    _write(tmp_path, "n.note.json",
           Note(title="T", blocks=[BodyBlock(text="C++ pointers and hemostasis and H2SO4")]))
    db = tmp_path / "idx.db"
    build_index(tmp_path, db)
    for q in ["C++", "hemostasis", "a AND", '"', "$x$", "O(n)"]:
        assert isinstance(search(q, db), list)  # must not raise


def test_nested_list_item_is_indexed_and_searchable(tmp_path):
    _write(tmp_path, "n.note.json", Note(title="Deep", blocks=[
        ListBlock(items=[ListItem(text="parent", children=[ListItem(text="nestedtermxyz")])])
    ]))
    db = tmp_path / "idx.db"
    build_index(tmp_path, db)
    res = search("nestedtermxyz", db)
    assert res and res[0]["note_title"] == "Deep"


def test_snippet_uses_sentinels_not_brackets(tmp_path):
    _write(tmp_path, "n.note.json",
           Note(title="B", blocks=[BodyBlock(text="arrays use [index] notation for hemostasis")]))
    db = tmp_path / "idx.db"
    build_index(tmp_path, db)
    res = search("hemostasis", db)
    assert res
    snip = res[0]["snippet"]
    assert "\x02" in snip and "\x03" in snip       # highlight sentinels present
    assert "[index]" in snip                        # literal brackets preserved, not eaten
