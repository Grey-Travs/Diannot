"""Plain-language error messages for non-technical students.

The studio surfaces failures through ``ui.notify``. A student should never see a raw
traceback, a Claude-CLI ``stderr`` blob, or a ``{exc}`` dump. :func:`friendly_error`
turns whatever the engine raised into one calm sentence.

Classification prefers the *typed* errors the engine already raises
(:class:`~diannot.providers.GeminiRateLimited` / :class:`~diannot.providers.GeminiKeyInvalid`
and :data:`diannot.structure._CLAUDE_MISSING`); a small substring fallback covers the
wrapped ``RuntimeError``s that carry CLI/HTTP text. This substring step is *cosmetic only* —
unlike the engine's retry/fallback logic it never decides control flow, so a wrong guess
just shows a slightly-less-specific calm message and never loses or mis-routes content.
"""
from __future__ import annotations

# Substring hints for the wrapped RuntimeErrors (lower-cased). Checked rate -> network -> key
# so an overlapping message (e.g. "rate-limited ... add another key") lands in the rate bucket.
_RATE_LIMIT_HINTS = (
    "rate limit", "rate-limit", "rate limited", "rate-limited", "usage limit", "limit was hit",
    "limit reached", "overloaded", "is busy", "are busy", "too many requests", "429",
    "quota", "resource_exhausted", "exhausted",
)
_NETWORK_HINTS = (
    "internet connection", "couldn't reach", "could not reach", "couldn’t reach", "timed out",
    "timeout", "connection", "network", "unreachable", "offline", "failed to establish",
)
_NO_KEY_HINTS = (
    "no gemini key", "no claude", "no api key", "add a free", "add a key", "add another key",
    "add a valid", "api key", "rejected", "bad or expired", "looks bad", "unauthorized",
    "authentication", "401", "403",
)
# A bare Claude-CLI failure (``_claude_cli_error`` → "Claude CLI failed: …") is *usually* a rate/usage
# limit, but its stderr tail can name the real cause. Consulted LAST so explicit network/auth text in
# the same message wins; a CLI failure with no clearer signal still maps to "busy, wait a minute".
_CLI_FAIL_HINTS = ("claude cli failed",)
# Markers that mean the raw text is technical and must NEVER be shown verbatim to a student.
_UGLY_MARKERS = (
    "traceback", "exit code", "check stderr", "  at ", "{", "}", "errno", ".py",
    "validationerror", "keyerror", "typeerror", "attributeerror", "nonetype", "0x",
)


def classify_error(exc: BaseException) -> str:
    """One of ``rate_limit`` | ``no_key`` | ``network`` | ``claude_missing`` | ``unknown``."""
    try:  # typed errors first — the most reliable signal
        from ..providers import GeminiKeyInvalid, GeminiRateLimited
    except Exception:  # pragma: no cover — providers always importable in practice
        GeminiKeyInvalid = GeminiRateLimited = ()  # isinstance(exc, ()) is always False
    if isinstance(exc, GeminiRateLimited):
        return "rate_limit"
    if isinstance(exc, GeminiKeyInvalid):
        return "no_key"
    try:
        from ..structure import _CLAUDE_MISSING
        if str(exc) == _CLAUDE_MISSING:
            return "claude_missing"
    except Exception:  # pragma: no cover
        pass

    low = str(exc).lower()
    if any(h in low for h in _RATE_LIMIT_HINTS):
        return "rate_limit"
    if any(h in low for h in _NETWORK_HINTS):
        return "network"
    if any(h in low for h in _NO_KEY_HINTS):
        return "no_key"
    if any(h in low for h in _CLI_FAIL_HINTS):
        return "rate_limit"
    return "unknown"


def _looks_clean(msg: str) -> bool:
    """True if a message is short, single-line, and free of technical leakage — safe to show as-is."""
    if not msg or len(msg) > 200 or "\n" in msg:
        return False
    low = msg.lower()
    return not any(m in low for m in _UGLY_MARKERS)


def friendly_error(exc: BaseException, *, action: str = "") -> str:
    """A calm, plain-language message for ``exc``.

    ``action`` is a short verb phrase for the thing being attempted (e.g. ``"organize this
    note"``, ``"make the quiz"``); when given it leads the message so the student knows which
    step failed.
    """
    kind = classify_error(exc)
    if kind == "claude_missing":
        return str(exc)  # already a self-contained, actionable instruction
    if kind == "rate_limit":
        if action:
            return f"Couldn't {action} — the AI service is busy. Please wait a minute and try again."
        return "The AI service is busy right now — please wait a minute and try again."
    if kind == "network":
        if action:
            return f"Couldn't {action} — check your internet connection and try again."
        return "Couldn't reach the AI service — check your internet connection and try again."
    if kind == "no_key":
        if action:
            return (f"Couldn't {action} — there's no working AI key. Add a free one in Settings "
                    "(or it'll use the shared one).")
        return "There's no working AI key — add a free one in Settings (or the shared key will be used)."

    msg = str(exc).strip()
    if _looks_clean(msg):
        return msg  # an already-plain message from our own engine (e.g. a safety-filter note)
    return f"Couldn't {action} — please try again." if action else "Something went wrong — please try again."
