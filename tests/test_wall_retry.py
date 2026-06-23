"""Under-structured 'wall' detection + the _structure_one retry that fixes it (no live AI)."""
import diannot.structure as S
from diannot.config import Settings
from diannot.models import BannerBlock, BodyBlock, ListBlock, ListItem, Note


def test_looks_understructured():
    raw = "word " * 300  # ~1500-char input
    wall = Note(title="T", blocks=[BannerBlock(text="T"), BodyBlock(text="x" * 800)])
    assert S._looks_understructured(wall, raw) is True
    structured = Note(title="T", blocks=[BannerBlock(text="T"),
                                         ListBlock(items=[ListItem(text="a"), ListItem(text="b")])])
    assert S._looks_understructured(structured, raw) is False
    short = Note(title="T", blocks=[BannerBlock(text="T"), BodyBlock(text="A short note.")])
    assert S._looks_understructured(short, raw) is False


def _mock(monkeypatch, *replies):
    calls = []
    it = iter(replies)

    def fake(prompt, model, settings, provider, system):
        calls.append(prompt)
        return next(it, replies[-1]), []

    monkeypatch.setattr(S, "_gen_text", fake)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    return calls


WALL = '{"title":"T","blocks":[{"type":"banner","text":"T"},{"type":"body","text":"%s"}]}' % ("x " * 400)
GOOD = ('{"title":"T","blocks":[{"type":"banner","text":"T"},'
        '{"type":"list","ordered":false,"items":[{"text":"a"},{"text":"b"}]}]}')


def test_structure_one_retries_on_wall(monkeypatch):
    calls = _mock(monkeypatch, WALL, GOOD)
    note = S._structure_one("word " * 300, "T", "circulatory", "study_notes", "m", Settings(), 2)
    assert any(b.type == "list" for b in note.blocks)   # took the structured retry
    assert len(calls) == 2 and "WALL of unstructured text" in calls[1]  # the nudge was sent


def test_structure_one_accepts_wall_after_one_retry(monkeypatch):
    # if the model keeps dumping a wall, retry only ONCE then accept (no infinite loop)
    calls = _mock(monkeypatch, WALL, WALL, WALL)
    note = S._structure_one("word " * 300, "T", "circulatory", "study_notes", "m", Settings(), 2)
    assert any(b.type == "body" for b in note.blocks) and len(calls) == 2
