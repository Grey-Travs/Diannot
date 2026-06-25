"""Onboarding helpers: the zero-config welcome gate + the writable default-workspace fallback.

Pure/deterministic — no NiceGUI UI context needed (the dialog wiring is covered by the browser
smoke test_onboarding_smoke.py).
"""
import diannot.studio.onboarding as ob


def test_ai_ready_true_with_gemini_keys(monkeypatch):
    monkeypatch.setattr(ob, "resolve_gemini_keys", lambda: ["a-key"])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ob._ai_ready() is True


def test_ai_ready_true_with_anthropic_env(monkeypatch):
    monkeypatch.setattr(ob, "resolve_gemini_keys", lambda: [])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert ob._ai_ready() is True


def test_ai_ready_false_with_no_engine(monkeypatch):
    monkeypatch.setattr(ob, "resolve_gemini_keys", lambda: [])
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert ob._ai_ready() is False


def test_default_notes_dir_prefers_documents(monkeypatch, tmp_path):
    home = tmp_path / "home"
    (home / "Documents").mkdir(parents=True)
    monkeypatch.setattr(ob.Path, "home", staticmethod(lambda: home))
    assert ob._default_notes_dir() == home / "Documents" / "Diannot Notes"


def test_default_notes_dir_falls_back_to_home_without_documents(monkeypatch, tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(ob.Path, "home", staticmethod(lambda: home))
    assert ob._default_notes_dir() == home / "Diannot Notes"
