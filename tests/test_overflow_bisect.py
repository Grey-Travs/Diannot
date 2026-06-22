"""On an output-token OVERFLOW (model reply cut off / truncated JSON), _structure_one bisects the
chunk and structures each half, instead of re-sending the same oversized chunk every retry (which
used to exhaust the retries and dump raw text)."""
import diannot.structure as S


def test_is_overflow_detects_cutoff_and_truncated_json():
    assert S._is_overflow("Gemini's reply was cut off (the document is too long)", "")
    truncated = "{" + ("x" * 3000)                                   # long, opens JSON, never closes
    assert S._is_overflow("response was not a single JSON object", truncated)
    assert not S._is_overflow("response was not a single JSON object", "not json")  # short -> plain error
    assert not S._is_overflow("Gemini timed out — check your connection", "")


def test_bisect_splits_at_paragraph_boundary():
    a, b = S._bisect(("A" * 1000) + "\n\n" + ("B" * 1000))
    assert a.startswith("A") and b.startswith("B")
    assert "B" not in a and "A" not in b   # clean split, nothing lost or duplicated


def test_bisect_hard_splits_when_no_boundary():
    parts = S._bisect("abcdefgh")          # no paragraph/line/sentence boundary -> split at midpoint
    assert len(parts) == 2 and "".join(parts) == "abcdefgh"


def test_overflow_chunk_is_bisected_and_merged(monkeypatch):
    monkeypatch.setattr(S.time, "sleep", lambda *_a, **_k: None)  # no backoff delay in the test
    big = ("alpha " * 300) + "\n\n" + ("omega " * 300)  # ~3.6 kB, > _BISECT_FLOOR, splittable

    def fake_gen(prompt, model, settings, provider, system):
        if "alpha" in prompt and "omega" in prompt:           # the FULL chunk overflows
            raise RuntimeError("Gemini's reply was cut off (the document is too long).")
        return '{"title":"T","blocks":[{"type":"body","text":"ok"}]}', []   # each HALF succeeds

    monkeypatch.setattr(S, "_gen_text", fake_gen)
    note = S._structure_one(big, "T", "circulatory", "study_notes", "m", S.Settings(), max_retries=2)
    # full chunk failed -> bisected into two halves -> two structured bodies merged, NO raw fallback
    assert sum(1 for b in note.blocks if b.type == "body") == 2


def test_non_overflow_error_still_re_prompts_not_bisects(monkeypatch):
    monkeypatch.setattr(S.time, "sleep", lambda *_a, **_k: None)
    seen = []

    def fake_gen(prompt, model, settings, provider, system):
        seen.append(prompt)
        if len(seen) == 1:
            return "not json at all", []   # invalid -> validation error (NOT an overflow)
        return '{"title":"T","blocks":[{"type":"body","text":"ok"}]}', []

    monkeypatch.setattr(S, "_gen_text", fake_gen)
    note = S._structure_one("short input", "T", "circulatory", "study_notes", "m", S.Settings(), 2)
    assert note.blocks[0].type == "body"
    assert "corrected single JSON" in seen[1]   # re-prompted (not bisected) on a plain invalid reply
