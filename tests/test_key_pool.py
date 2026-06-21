"""Gemini multi-key rotation pool: spread work across several keys (different accounts = separate
free-tier quota) and skip any key that just hit its rate limit."""
import os

import pytest

import diannot.studio.credentials as C
from diannot import providers


@pytest.fixture(autouse=True)
def _reset_pool():
    providers.set_gemini_keys([])   # isolate the global singleton between tests
    yield
    providers.set_gemini_keys([])


def test_set_keys_dedups_strips_and_orders():
    providers.set_gemini_keys([" k1 ", "k1", "", "k2", None])
    assert providers.gemini_pool_size() == 2
    assert [providers._GEMINI_POOL.next_key() for _ in range(2)] == ["k1", "k2"]


def test_round_robin_cycles():
    providers.set_gemini_keys(["k1", "k2", "k3"])
    assert [providers._GEMINI_POOL.next_key() for _ in range(6)] == ["k1", "k2", "k3", "k1", "k2", "k3"]


def test_cooldown_key_is_skipped():
    providers.set_gemini_keys(["k1", "k2"])
    providers._GEMINI_POOL.cool_down("k1", seconds=999)
    picks = [providers._GEMINI_POOL.next_key() for _ in range(4)]
    assert set(picks) == {"k2"}  # k1 is resting, never handed out while k2 is free


def test_empty_pool_uses_fallback_key(monkeypatch):
    got = {}

    def fake(system, prompt, model, api_key, images=None, timeout=120.0):
        got["key"] = api_key
        return "OK"

    monkeypatch.setattr(providers, "gemini_complete", fake)
    out = providers.gemini_complete_pooled("s", "p", "m", fallback_key="envkey")
    assert out == "OK" and got["key"] == "envkey"


def test_rotates_past_a_rate_limited_key(monkeypatch):
    providers.set_gemini_keys(["k1", "k2"])
    seen = []

    def fake(system, prompt, model, api_key, images=None, timeout=120.0):
        seen.append(api_key)
        if api_key == "k1":
            raise RuntimeError("Gemini's free limit was hit. Wait a minute.")
        return "STRUCTURED"

    monkeypatch.setattr(providers, "gemini_complete", fake)
    out = providers.gemini_complete_pooled("s", "p", "m")
    assert out == "STRUCTURED"
    assert seen == ["k1", "k2"]  # tried k1, hit its limit, rotated to k2


def test_all_keys_exhausted_raises_generic_keyfree(monkeypatch):
    providers.set_gemini_keys(["k1", "k2"])
    monkeypatch.setattr(providers, "gemini_complete",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("the free limit was hit")))
    with pytest.raises(RuntimeError, match="rate-limited") as ei:
        providers.gemini_complete_pooled("s", "p", "m")
    assert "k1" not in str(ei.value) and "k2" not in str(ei.value)  # generic message, no key leaked


def test_all_cooling_keys_still_rotate():
    providers.set_gemini_keys(["k1", "k2", "k3"])
    for k in ("k1", "k2", "k3"):
        providers._GEMINI_POOL.cool_down(k, seconds=999)
    # Even fully saturated, callers fan out across accounts instead of all hitting one.
    assert [providers._GEMINI_POOL.next_key() for _ in range(6)] == ["k1", "k2", "k3", "k1", "k2", "k3"]


def test_non_ratelimit_error_does_not_rotate(monkeypatch):
    providers.set_gemini_keys(["k1", "k2"])
    calls = []

    def fake(system, prompt, model, api_key, images=None, timeout=120.0):
        calls.append(api_key)
        raise RuntimeError("Gemini error 500. Try again in a moment.")

    monkeypatch.setattr(providers, "gemini_complete", fake)
    with pytest.raises(RuntimeError, match="500"):
        providers.gemini_complete_pooled("s", "p", "m")
    assert calls == ["k1"]  # a non-rate-limit error isn't fixed by switching keys


def test_resolve_prefers_configured_and_ignores_env(monkeypatch):
    # Configured keys (saved + bundled) are authoritative; a stale env key must NOT sneak in.
    monkeypatch.setattr(C, "_read_creds", lambda: {"gemini_api_keys": "u1,u2", "gemini_api_key": "u3"})
    monkeypatch.setattr(C, "_bundled_gemini_keys", lambda: ["b1", "u1"])  # u1 duplicates a user key
    monkeypatch.setenv("GEMINI_API_KEY", "e1")
    assert C.resolve_gemini_keys() == ["u1", "u2", "u3", "b1"]  # user first, deduped, env ignored


def test_resolve_falls_back_to_env_only_when_nothing_configured(monkeypatch):
    monkeypatch.setattr(C, "_read_creds", lambda: {})
    monkeypatch.setattr(C, "_bundled_gemini_keys", lambda: [])
    monkeypatch.setenv("GEMINI_API_KEY", "envonly")
    assert C.resolve_gemini_keys() == ["envonly"]  # bring-your-own env honored when nothing saved


def test_saved_gemini_keys_folds_in_legacy_single(monkeypatch):
    monkeypatch.setattr(C, "_read_creds", lambda: {"gemini_api_keys": "a,b", "gemini_api_key": "c"})
    assert C.saved_gemini_keys() == ["a", "b", "c"]


def test_clearing_saved_keys_actually_removes_them(tmp_path, monkeypatch):
    """Regression: clearing the pool must delete saved keys (was silently kept via _write_creds)."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(C, "_bundled_gemini_keys", lambda: [])
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    C.persist_gemini_keys(["AIzaKEYONE", "AIzaKEYTWO"])
    assert C.saved_gemini_keys() == ["AIzaKEYONE", "AIzaKEYTWO"]
    C.persist_gemini_keys([])  # user clears the textarea and saves
    assert C.saved_gemini_keys() == []
    assert C.resolve_gemini_keys() == []  # truly gone (no bundle, no env)


def test_legacy_single_key_is_removable_via_multikey(tmp_path, monkeypatch):
    """Regression: a legacy gemini_api_key must be deletable through the new multi-key save."""
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(C, "_bundled_gemini_keys", lambda: [])
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    C._write_creds({"gemini_api_key": "LEGACYKEY"})  # simulate an upgrade from the single-key build
    assert "LEGACYKEY" in C.saved_gemini_keys()
    C.persist_gemini_keys([])  # clear
    assert "LEGACYKEY" not in C.resolve_gemini_keys() and C.saved_gemini_keys() == []


def test_clear_gemini_keys_also_drops_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setattr(C, "_bundled_gemini_keys", lambda: [])
    monkeypatch.setenv("GEMINI_API_KEY", "STALEENV")
    C.persist_gemini_keys(["AIzaKEYONE"])
    C.clear_gemini_keys()
    assert C.saved_gemini_keys() == []
    assert "GEMINI_API_KEY" not in os.environ      # env dropped, so it can't linger
    assert C.resolve_gemini_keys() == []
