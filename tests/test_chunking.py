"""Large documents are split into small chunks and merged into one Note (no AI timeout)."""
import diannot.structure as S
from diannot.models import BannerBlock, BodyBlock, Note
from diannot.structure import _CHUNK_THRESHOLD, _split_for_structuring


def test_small_text_is_a_single_chunk():
    assert _split_for_structuring("a short note") == ["a short note"]
    edge = "x" * (_CHUNK_THRESHOLD - 1)
    assert _split_for_structuring(edge) == [edge]


def test_large_text_splits_into_several_target_sized_chunks():
    para = ("This is a sentence about chemistry. " * 20).strip()  # ~720 chars
    big = "\n\n".join([para] * 40)  # ~29 kB
    chunks = _split_for_structuring(big)
    assert len(chunks) > 1
    assert all(len(c) <= 6500 * 1.8 for c in chunks)
    # content is preserved (ignoring whitespace packing)
    norm = lambda s: "".join(s.split())
    assert norm("".join(chunks)) == norm(big)


def test_one_giant_paragraph_is_hard_split():
    giant = "word " * 5000  # ~25 kB with no blank lines
    chunks = _split_for_structuring(giant)
    assert len(chunks) > 1


def test_merge_keeps_one_banner_and_combines_chunk_blocks(monkeypatch):
    calls = []

    def fake_one(text, title, theme, pack, model, settings, max_retries):
        calls.append((text, title))
        return Note(title="Doc", blocks=[BannerBlock(text="Doc"), BodyBlock(text=f"chunk{len(calls)}")])

    monkeypatch.setattr(S, "_structure_one", fake_one)
    big = "\n\n".join(["paragraph text here. " * 60] * 20)  # forces multiple chunks
    note = S.structure_text(big, title="Doc")

    assert sum(1 for b in note.blocks if b.type == "banner") == 1          # exactly ONE banner
    assert sum(1 for b in note.blocks if b.type == "body") == len(calls)   # one body per chunk
    assert len(calls) > 1                                                  # actually chunked
    assert calls[0][1] == "Doc" and calls[1][1] is None                    # title only on first chunk


def test_single_chunk_path_still_works(monkeypatch):
    monkeypatch.setattr(S, "_structure_one",
                        lambda *a, **k: Note(title="T", blocks=[BannerBlock(text="T")]))
    note = S.structure_text("small input", title="T")
    assert note.title == "T" and note.blocks[0].type == "banner"
