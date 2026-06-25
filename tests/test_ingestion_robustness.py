"""Ingestion robustness: big-file vision batching, size-scaled timeouts, cross-engine failover when the
Gemini pool drains, and a never-crash flashcard/quiz JSON call. All deterministic (no live AI)."""
import asyncio

import pytest

import diannot.structure as S
from diannot.config import ProvidersCfg, Settings

GOOD = ('{"title":"T","blocks":[{"type":"banner","text":"T"},'
        '{"type":"body","text":"transcribed content"}]}')
SIX = [f"page{i}".encode() for i in range(6)]  # 6 pages -> 2 vision batches (4 + 2)


# ---- size-scaled timeouts (more leeway for big input, never unbounded) ---------------------------

def test_scaled_timeout_grows_with_size_and_caps():
    assert S._scaled_timeout(0, 8.0) == S._CLAUDE_TIMEOUT             # empty -> base
    assert S._scaled_timeout(10, 8.0) == S._CLAUDE_TIMEOUT + 80.0     # +8s per unit
    assert S._scaled_timeout(1_000_000, 8.0) == S._CLAUDE_CALL_MAX    # clamped to the ceiling
    assert S._CLAUDE_CALL_MAX > S._CLAUDE_TIMEOUT                      # ceiling is more generous than 300s


# ---- vision batching: a big scan is split into bounded calls, not one giant request --------------

def test_vision_batches_merge_in_page_order(monkeypatch):
    # Distinct content per batch so a reordered/dropped merge is actually caught (not just counted).
    def fake_gen(content, prompt_text, images, model, settings, provider):
        tag = "A" if SIX[0] in images else "B"                       # first batch -> A, second -> B
        banner = '{"type":"banner","text":"T"},' if tag == "A" else ""
        return '{"title":"T","blocks":[' + banner + '{"type":"body","text":"' + tag + '"}]}', []

    monkeypatch.setattr(S, "_gen_vision", fake_gen)
    note = S._structure_image_safe(SIX, title="T", settings=Settings(), max_retries=1,
                                   source_pages=[1, 2, 3, 4, 5, 6])

    assert note.extraction_status is None
    assert [b.text for b in note.blocks if b.type == "body"] == ["A", "B"]   # page order preserved
    assert sum(1 for b in note.blocks if b.type == "banner") == 1
    assert note.blocks[0].type == "banner"


def test_vision_merge_keeps_one_banner_when_first_batch_lacks_it(monkeypatch):
    # Model variance: the FIRST batch omits the banner, a LATER batch leads with one. The merge must
    # still yield exactly ONE banner (the old positional strip produced ZERO here).
    def fake_gen(content, prompt_text, images, model, settings, provider):
        if SIX[0] in images:
            return '{"title":"T","blocks":[{"type":"body","text":"A"}]}', []
        return '{"title":"T","blocks":[{"type":"banner","text":"T"},{"type":"body","text":"B"}]}', []

    monkeypatch.setattr(S, "_gen_vision", fake_gen)
    note = S._structure_image_safe(SIX, title="T", settings=Settings(), max_retries=1,
                                   source_pages=[1, 2, 3, 4, 5, 6])

    assert sum(1 for b in note.blocks if b.type == "banner") == 1    # exactly one, not zero
    assert note.blocks[0].type == "banner"
    assert [b.text for b in note.blocks if b.type == "body"] == ["A", "B"]


def test_non_runtimeerror_in_batch_degrades_not_crash(monkeypatch):
    # A non-RuntimeError bug from a batch must STILL degrade to preserved scans, never escape.
    monkeypatch.setattr(S, "_gen_vision",
                        lambda *a, **k: (_ for _ in ()).throw(ValueError("unexpected non-RuntimeError")))
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    note = S._structure_image_safe([b"p1", b"p2"], title="T", settings=Settings(), max_retries=1,
                                   source_pages=[1, 2])
    assert note.extraction_status == "failed"
    assert note._pending_page_images == [b"p1", b"p2"]


def test_vision_one_failed_batch_degrades_whole_note_keeping_all_scans(monkeypatch):
    # The second batch (pages 5-6) always fails -> contract-preserving all-pages fallback: every scan
    # is kept as a placeholder + carried out for retry, nothing is lost.
    def fake_gen(content, prompt_text, images, model, settings, provider):
        if SIX[4] in images:  # the second batch
            raise RuntimeError("rate limit was hit")
        return GOOD, []

    monkeypatch.setattr(S, "_gen_vision", fake_gen)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    note = S._structure_image_safe(SIX, title="T", settings=Settings(), max_retries=1,
                                   source_pages=[1, 2, 3, 4, 5, 6])

    assert note.extraction_status == "failed"
    imgs = [b for b in note.blocks if b.type == "image"]
    assert len(imgs) == 6                                           # one placeholder per page
    assert note._pending_page_images == SIX                        # every scan preserved for retry
    assert [b.source_page for b in imgs] == [1, 2, 3, 4, 5, 6]


# ---- cross-engine failover: a drained Gemini pool falls back to Claude before degrading -----------

def test_gemini_pool_exhausted_detection():
    assert S._gemini_pool_exhausted(RuntimeError("All your Gemini keys are rate-limited right now."))
    assert S._gemini_pool_exhausted(S._providers.GeminiKeyInvalid("All your Gemini keys were rejected"))
    # a LONE transient 429 is NOT pool-exhaustion -> we don't burn Claude on a blip
    assert not S._gemini_pool_exhausted(RuntimeError("Gemini's free limit was hit. Wait a minute."))


def test_text_falls_back_to_claude_when_gemini_pool_drained(monkeypatch):
    monkeypatch.setattr(
        "diannot.providers.gemini_complete_pooled",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("All your Gemini keys are rate-limited right now.")),
    )
    monkeypatch.setattr(S, "claude_engine_available", lambda: True)

    async def fake_run_text(prompt, model, system=S.SYSTEM_PROMPT, timeout=S._CLAUDE_TIMEOUT):
        return GOOD, []

    monkeypatch.setattr(S, "_run_text", fake_run_text)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")

    note = S.structure_text("some study text to structure into a note",
                            settings=Settings(providers=ProvidersCfg(notes="gemini")))
    assert note.title == "T"                 # structured via the Claude fallback...
    assert note.extraction_status is None    # ...not degraded to a raw-text wall


def test_no_claude_fallback_when_unavailable_degrades_safely(monkeypatch):
    # Pool drained AND Claude not available -> never crash: degrade to preserved raw text.
    monkeypatch.setattr(
        "diannot.providers.gemini_complete_pooled",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("All your Gemini keys are rate-limited right now.")),
    )
    monkeypatch.setattr(S, "claude_engine_available", lambda: False)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")

    raw = "some study text to structure into a note"
    note = S.structure_text(raw, settings=Settings(providers=ProvidersCfg(notes="gemini")))
    assert note.extraction_status == "failed"   # never raised
    assert note.source_text == raw              # full content preserved for "Retry organizing"


# ---- flashcard/quiz JSON never crashes on a transient rate limit ---------------------------------

def test_complete_json_retries_transient_then_succeeds(monkeypatch):
    replies = iter([RuntimeError("Gemini's free limit was hit"), '{"k": 9}'])

    def fake_gen(prompt, model, settings, provider, system):
        v = next(replies)
        if isinstance(v, Exception):
            raise v
        return v, []

    monkeypatch.setattr(S, "_gen_text", fake_gen)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    out = S.complete_json("sys", "prompt", settings=Settings())
    assert out == {"k": 9}  # retried the rate limit instead of crashing the study action


def test_complete_json_raises_after_exhausting_retries(monkeypatch):
    calls = {"n": 0}

    def always_fail(prompt, model, settings, provider, system):
        calls["n"] += 1
        raise RuntimeError("rate limit was hit")

    monkeypatch.setattr(S, "_gen_text", always_fail)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="JSON completion failed"):
        S.complete_json("sys", "prompt", settings=Settings(), max_retries=2)
    assert calls["n"] == 3  # max_retries + 1 attempts, then surfaces (not an infinite loop / junk)


def test_complete_json_claude_missing_propagates_without_retry(monkeypatch):
    calls = {"n": 0}

    def missing(prompt, model, settings, provider, system):
        calls["n"] += 1
        raise RuntimeError(S._CLAUDE_MISSING)

    monkeypatch.setattr(S, "_gen_text", missing)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    with pytest.raises(RuntimeError, match="Claude Code CLI"):
        S.complete_json("sys", "prompt", settings=Settings(), max_retries=2)
    assert calls["n"] == 1  # a config error is not retried


# ---- vision cross-engine failover + Claude-missing degrade + timeout wiring -----------------------

def test_vision_falls_back_to_claude_with_images_intact(monkeypatch):
    monkeypatch.setattr(
        "diannot.providers.gemini_complete_pooled",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("All your Gemini keys are rate-limited right now.")),
    )
    monkeypatch.setattr(S, "claude_engine_available", lambda: True)
    captured = {}

    async def fake_run_mm(content, model, system=S.SYSTEM_PROMPT, timeout=S._CLAUDE_TIMEOUT):
        captured["content"] = content
        return GOOD, []

    monkeypatch.setattr(S, "_run_multimodal", fake_run_mm)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")

    note = S._structure_image_safe([b"\x89PNG-1", b"\x89PNG-2"], title="T", max_retries=1,
                                   settings=Settings(providers=ProvidersCfg(notes="gemini")))
    assert note.extraction_status is None                                  # structured via Claude vision
    assert any(p.get("type") == "image" for p in captured["content"])      # the page images carried through


def test_claude_missing_failover_degrades_gemini_user_not_crash(monkeypatch):
    # Pool drained, claude_engine_available True, but Claude turns out UNUSABLE (CLI missing) -> the
    # Gemini user's content is preserved (degrade), NOT a hard "_CLAUDE_MISSING" crash.
    monkeypatch.setattr(
        "diannot.providers.gemini_complete_pooled",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("All your Gemini keys are rate-limited right now.")),
    )
    monkeypatch.setattr(S, "claude_engine_available", lambda: True)

    async def claude_missing(prompt, model, system=S.SYSTEM_PROMPT, timeout=S._CLAUDE_TIMEOUT):
        raise RuntimeError(S._CLAUDE_MISSING)

    monkeypatch.setattr(S, "_run_text", claude_missing)
    monkeypatch.setattr(S.time, "sleep", lambda *a, **k: None)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")

    raw = "some study text to structure into a note"
    note = S.structure_text(raw, settings=Settings(providers=ProvidersCfg(notes="gemini")))
    assert note.extraction_status == "failed"   # degraded, not crashed
    assert note.source_text == raw              # content preserved


def test_gen_vision_converts_timeout_to_retryable(monkeypatch):
    async def slow(content, model, system=S.SYSTEM_PROMPT, timeout=S._CLAUDE_TIMEOUT):
        raise asyncio.TimeoutError()

    monkeypatch.setattr(S, "_run_multimodal", slow)
    with pytest.raises(RuntimeError, match="timed out"):  # converted so structure_image's retry catches it
        S._gen_vision([{"type": "text", "text": "x"}], "x", [b"p"], "claude-x", Settings(), "claude")


def test_scaled_timeout_is_wired_into_the_gemini_call(monkeypatch):
    captured = {}

    def fake_pooled(system, prompt, model, images=None, timeout=300.0, fallback_key=""):
        captured["timeout"] = timeout
        return '{"title":"T","blocks":[{"type":"banner","text":"T"},{"type":"body","text":"x"}]}'

    monkeypatch.setattr("diannot.providers.gemini_complete_pooled", fake_pooled)
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-test")
    S.structure_text("x" * 5000, settings=Settings(providers=ProvidersCfg(notes="gemini")))
    assert captured["timeout"] > S._CLAUDE_TIMEOUT  # a big input gets MORE than the flat base, not 300s


# ---- pipeline read-side never-fail + multi-page persist contract ---------------------------------

def test_pipeline_no_text_pdf_falls_back_to_vision(monkeypatch, tmp_path):
    import diannot.pipeline as PL
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-fake")
    monkeypatch.setattr(PL, "decide_mode", lambda *a, **k: "text")     # routed to text...
    monkeypatch.setattr(PL, "load_raw_text", lambda *a, **k: "")        # ...but no extractable text
    monkeypatch.setattr(PL, "load_image_sources", lambda *a, **k: [b"p1", b"p2"])
    monkeypatch.setattr(PL, "page_numbers_for", lambda *a, **k: [1, 2])
    recorded = {}

    def fake_safe(images, **k):
        recorded["images"], recorded["source_pages"] = images, k.get("source_pages")
        from diannot.models import BodyBlock, Note
        return Note(title="T", blocks=[BodyBlock(text="vision")])

    monkeypatch.setattr(PL, "_structure_image_safe", fake_safe)
    note = PL.ingest_file(pdf)
    assert recorded["images"] == [b"p1", b"p2"]      # auto-fell back to vision instead of raising
    assert recorded["source_pages"] == [1, 2]
    assert note.title == "T"


def test_pipeline_non_pdf_no_text_raises(monkeypatch, tmp_path):
    import diannot.pipeline as PL
    f = tmp_path / "empty.txt"
    f.write_text("", encoding="utf-8")
    monkeypatch.setattr(PL, "decide_mode", lambda *a, **k: "text")
    monkeypatch.setattr(PL, "load_raw_text", lambda *a, **k: "")
    with pytest.raises(ValueError, match="No text"):
        PL.ingest_file(f)


def test_multipage_failed_note_persists_one_to_one(tmp_path):
    import diannot.pipeline as PL
    note = S._pending_image_note(SIX, title="T", theme="circulatory", pack="study_notes",
                                 source_pages=[1, 2, 3, 4, 5, 6])
    names = PL.persist_page_images(note, tmp_path / "N.note.json")
    assert names == [f"page_{i:02d}.png" for i in range(1, 7)]
    assets = tmp_path / "N.note.assets"  # note_path.stem is "N.note" -> "<stem>.assets"
    for i in range(6):  # block[i] <-> page bytes[i] <-> page_(i+1).png — the MUST-NOT-BREAK join
        assert (assets / f"page_{i + 1:02d}.png").read_bytes() == SIX[i]
    img_src = [b.src for b in note.blocks if b.type == "image"]
    assert img_src == [f"N.note.assets/page_{i:02d}.png" for i in range(1, 7)]
