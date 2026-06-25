"""friendly_error() turns whatever the engine raised into a calm, student-safe sentence.

Deterministic + offline — it only classifies exception objects, no AI/network. Guards the promise
that a non-technical student never sees a raw traceback, a Claude-CLI stderr blob, or a `{exc}` dump.
"""
import pytest

from diannot.providers import GeminiKeyInvalid, GeminiRateLimited
from diannot.structure import _CLAUDE_MISSING
from diannot.studio.errors import classify_error, friendly_error


def test_typed_rate_limit_is_classified_and_calm():
    exc = GeminiRateLimited("Gemini's free limit was hit", retry_after=30)
    assert classify_error(exc) == "rate_limit"
    msg = friendly_error(exc, action="make the quiz")
    assert "busy" in msg.lower()
    assert "make the quiz" in msg  # the action leads so the student knows which step failed
    assert "GeminiRateLimited" not in msg  # never leak the class name


def test_typed_key_invalid_points_to_settings():
    exc = GeminiKeyInvalid("Gemini rejected the request — the API key looks bad or expired.")
    assert classify_error(exc) == "no_key"
    assert "Settings" in friendly_error(exc, action="organize this note")


def test_claude_missing_is_passed_through_verbatim():
    exc = RuntimeError(_CLAUDE_MISSING)
    assert classify_error(exc) == "claude_missing"
    # the install instruction is already friendly + actionable — don't paraphrase it
    assert friendly_error(exc) == _CLAUDE_MISSING


@pytest.mark.parametrize("text,kind", [
    ("All your Gemini keys are rate-limited right now. Add another key.", "rate_limit"),
    ("HTTP 429 Too Many Requests", "rate_limit"),
    ("Claude CLI failed: usage limit reached", "rate_limit"),
    ("Gemini is busy right now (the free service is overloaded).", "rate_limit"),
    ("Couldn't reach Gemini — check your internet connection.", "network"),
    ("Gemini timed out — check your internet connection and try again.", "network"),
    ("No Gemini key. Add a free one in Settings.", "no_key"),
    ("Gemini rejected the request — the API key looks bad or expired.", "no_key"),
    # A bare Claude-CLI failure with no clearer signal is treated as "busy" (its documented usual cause)…
    ("Claude CLI failed (exit code 1)", "rate_limit"),
    # …but explicit auth / network text in the stderr tail must win over that weak CLI fallback.
    ("Claude CLI failed: 401 Unauthorized", "no_key"),
    ("Claude CLI failed: <urlopen error timed out>", "network"),
])
def test_substring_classification_of_wrapped_runtimeerrors(text, kind):
    assert classify_error(RuntimeError(text)) == kind


def test_ugly_blob_is_suppressed_for_unknown_errors():
    blob = 'Traceback (most recent call last):\n  File "x.py", line 1\nKeyError: \'blocks\''
    msg = friendly_error(RuntimeError(blob), action="fix this block")
    assert "Traceback" not in msg and "KeyError" not in msg and ".py" not in msg
    assert "fix this block" in msg


def test_clean_unknown_message_still_shows():
    # a plain one-liner from our own engine that fits no bucket is safe to show as-is
    text = "Gemini declined this content (safety filter). Try different source text."
    assert classify_error(RuntimeError(text)) == "unknown"
    assert friendly_error(RuntimeError(text)) == text


def test_no_action_messages_are_self_contained():
    assert friendly_error(GeminiRateLimited("x")).strip().endswith("try again.")
    assert "internet connection" in friendly_error(RuntimeError("connection refused"))
    assert "Settings" in friendly_error(GeminiKeyInvalid("bad key"))
