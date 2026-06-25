"""Structuring failure is preserved + flagged, never silently truncated (no live AI).

Regression guard for the silent-data-loss bug: when AI structuring fails (usually a rate limit),
the old code dumped a chunk as ONE low-confidence body block truncated to 4000 chars and threw the
rest away. These tests assert the FULL text is kept and the note is flagged for retry.
"""
import diannot.structure as S
from diannot.config import Settings
from diannot.models import BannerBlock, BodyBlock, Note

# A minimal valid structured note the model could return.
GOOD = ('{"title":"T","blocks":[{"type":"banner","text":"T"},'
        '{"type":"list","ordered":false,"items":[{"text":"a"},{"text":"b"}]}]}')


def _norm(s: str) -> str:
    return "".join(s.split())  # compare ignoring whitespace packing


def test_fallback_preserves_full_text_and_flags_failed(monkeypatch):
    # _gen_text always fails -> _structure_one exhausts retries -> _structure_one_safe falls back.
    monkeypatch.setattr(S, "_gen_text",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("rate limit was hit")))
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)

    raw = "\n\n".join(f"Paragraph {i}. " + ("word " * 50) for i in range(20))  # ~5 kB, >4000
    note = S._structure_one_safe(raw, None, "circulatory", "study_notes", "m", Settings(),
                                 max_retries=1, is_first=False)

    assert note.extraction_status == "failed"
    bodies = [b for b in note.blocks if b.type == "body"]
    assert bodies and all(b.confidence == "low" for b in bodies)
    assert len(bodies) >= 2                                   # split, not one truncated block
    # nothing dropped: the old code capped at 4000; the full ~5 kB is preserved
    assert sum(len(b.text) for b in bodies) > 4000
    assert _norm("".join(b.text for b in bodies)) == _norm(raw)


def test_no_path_truncates_to_4000(monkeypatch):
    """Explicit guard: no produced block is the old fixed 4000-char slice of the input."""
    monkeypatch.setattr(S, "_gen_text",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("overloaded")))
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    raw = "x" * 9000  # one giant blob, no paragraph breaks
    note = S._structure_one_safe(raw, None, "circulatory", "study_notes", "m", Settings(),
                                 max_retries=1, is_first=False)
    assert all(b.text != raw[:4000] for b in note.blocks if b.type == "body")
    assert sum(len(b.text) for b in note.blocks if b.type == "body") == len(raw)  # every char kept


def test_structure_text_marks_failed_when_all_chunks_fail(monkeypatch):
    monkeypatch.setattr(S, "_structure_one",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429 too many requests")))
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    big = "\n\n".join(["paragraph text here. " * 60] * 20)  # forces multiple chunks
    assert len(S._split_for_structuring(big)) > 1
    note = S.structure_text(big, title="Doc")
    assert note.extraction_status == "failed"
    assert note.source_text == big   # FULL input kept for retry


def test_structure_text_marks_partial_when_some_chunks_fail(monkeypatch):
    big = "\n\n".join(["paragraph text here. " * 60] * 20)
    chunks = S._split_for_structuring(big)
    assert len(chunks) > 1
    fail_text = chunks[0]  # deterministic: results are placed by chunk index regardless of order

    def fake_one(text, title, theme, pack, model, settings, max_retries):
        if text == fail_text:
            raise RuntimeError("usage limit")
        return Note(title="Doc", blocks=[BannerBlock(text="Doc"), BodyBlock(text="ok")])

    monkeypatch.setattr(S, "_structure_one", fake_one)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    note = S.structure_text(big, title="Doc")
    assert note.extraction_status == "partial"
    assert note.source_text == big


def test_structure_text_ok_leaves_status_and_source_text_none(monkeypatch):
    monkeypatch.setattr(S, "_structure_one",
                        lambda *a, **k: Note(title="Doc", blocks=[BannerBlock(text="Doc"),
                                                                  BodyBlock(text="ok")]))
    big = "\n\n".join(["paragraph text here. " * 60] * 20)
    note = S.structure_text(big, title="Doc")
    assert note.extraction_status is None and note.source_text is None  # never over-alarm a real note


def test_claude_cli_error_wraps_as_runtimeerror_carrying_stderr():
    err = S._claude_cli_error(ValueError("Command failed with exit code 1"),
                              ["noise\n", "  Error: rate limit reached \n"])
    assert isinstance(err, RuntimeError)
    assert "exit code 1" in str(err) and "rate limit reached" in str(err)


def test_backoff_is_jittered(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(S.time, "sleep", lambda s: slept.append(s))
    replies = iter([RuntimeError("overloaded"), (GOOD, [])])  # fail once (rate limit), then succeed

    def fake_gen(prompt, model, settings, provider, system):
        v = next(replies)
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(S, "_gen_text", fake_gen)
    S._structure_one("small text", "T", "circulatory", "study_notes", "m", Settings(), 2)
    # rate-limit base is 22s; jitter adds [0,3) so the wait is never a fixed constant.
    assert slept and 22.0 <= slept[0] < 25.0
