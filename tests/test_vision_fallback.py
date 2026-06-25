"""Vision structuring failure is preserved + flagged, never lost (no live AI).

The VISION counterpart of ``test_structure_fallback.py``. When vision structuring of a scanned PDF /
photo fails (usually a rate limit), the page images must be kept (as ImageBlock placeholders carried
out for the caller to persist) and the note flagged ``extraction_status="failed"`` — not raised away.
Also guards the BONUS bug: the vision retry loop now actually retries a transient error with backoff,
instead of failing on the first one (it had no try/except and no sleep).
"""
import pytest

import diannot.structure as S
from diannot.config import ProvidersCfg, Settings

# A minimal valid structured note the model could return for a page image.
GOOD = ('{"title":"T","blocks":[{"type":"banner","text":"T"},'
        '{"type":"body","text":"transcribed page content"}]}')

IMAGES = [b"\x89PNG-page-1", b"\x89PNG-page-2"]  # opaque bytes — only their identity/count matter here


def test_safe_preserves_pages_and_flags_failed(monkeypatch):
    # _gen_vision always fails -> structure_image exhausts retries -> _structure_image_safe falls back.
    monkeypatch.setattr(S, "_gen_vision",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("rate limit was hit")))
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)

    note = S._structure_image_safe(IMAGES, title="Chapter 4", theme="circulatory", pack="study_notes",
                                   model="m", settings=Settings(), max_retries=1, source_pages=[3, 4])

    assert note.extraction_status == "failed"
    imgs = [b for b in note.blocks if b.type == "image"]
    assert len(imgs) == 2                                   # one placeholder per page, nothing dropped
    assert all(b.confidence == "low" for b in imgs)
    assert [b.source_page for b in imgs] == [3, 4]          # per-page attribution preserved
    assert note.blocks[0].type == "banner"                 # title kept as the banner
    # the raw page bytes ride out for the caller to persist (the note path isn't known here)
    assert note._pending_page_images == IMAGES


def test_safe_bad_json_falls_back(monkeypatch):
    # A reply that never parses (not transient, not Claude-missing) still degrades, never raises.
    monkeypatch.setattr(S, "_gen_vision", lambda *a, **k: ("not json at all", []))
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    note = S._structure_image_safe(IMAGES, title=None, settings=Settings(), max_retries=1)
    assert note.extraction_status == "failed"
    assert len([b for b in note.blocks if b.type == "image"]) == 2
    assert note.blocks[0].type == "image"                  # no title -> no banner, just the pages


def test_safe_ok_leaves_status_none(monkeypatch):
    monkeypatch.setattr(S, "_gen_vision", lambda *a, **k: (GOOD, []))
    note = S._structure_image_safe(IMAGES, title="T", settings=Settings(), max_retries=1)
    assert note.extraction_status is None                  # never over-alarm a real note
    assert not note._pending_page_images                   # healthy note carries no pages to persist
    assert [b.type for b in note.blocks] == ["banner", "body"]


def test_safe_claude_missing_reraises(monkeypatch):
    # A config error (CLI not logged in / no key) must NOT be hidden inside a degraded note.
    monkeypatch.setattr(S, "_gen_vision",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError(S._CLAUDE_MISSING)))
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="Claude Code CLI"):
        S._structure_image_safe(IMAGES, title="T", settings=Settings(), max_retries=1)


def test_gemini_vision_failure_also_degrades(monkeypatch):
    """Provider parity: the safe wrapper catches PROVIDER RuntimeErrors (real _gen_vision dispatch),
    not only the Claude path — a Gemini vision failure degrades just the same."""
    def boom(*a, **k):
        raise RuntimeError("Gemini hit its free limit (429).")

    monkeypatch.setattr("diannot.providers.gemini_complete_pooled", boom)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    settings = Settings(providers=ProvidersCfg(notes="gemini"))
    note = S._structure_image_safe(IMAGES, title="T", settings=settings, max_retries=1)
    assert note.extraction_status == "failed"
    assert len([b for b in note.blocks if b.type == "image"]) == 2


def test_retry_loop_retries_transient_with_backoff(monkeypatch):
    """Bonus-bug guard: a raised transient error now triggers a SECOND attempt + a backoff sleep
    (previously _gen_vision had no try/except and no sleep, so the loop died on the first failure)."""
    slept: list[float] = []
    monkeypatch.setattr(S.time, "sleep", lambda s: slept.append(s))
    replies = iter([RuntimeError("overloaded"), (GOOD, [])])  # fail once, then succeed

    def fake_gen(content, prompt_text, images, model, settings, provider):
        v = next(replies)
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(S, "_gen_vision", fake_gen)
    note = S.structure_image(IMAGES, title="T", settings=Settings(), max_retries=2)
    assert note.title == "T"                               # it retried and succeeded (didn't raise)
    assert slept and 22.0 <= slept[0] < 25.0               # rate-limit backoff (22s base + jitter)
