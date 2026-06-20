"""Local (Ollama) provider client + the AI-backend dispatch in structure.py."""
import json
import urllib.error

import diannot.providers as P
from diannot.config import ProvidersCfg, Settings, load_config_file, update_config
from diannot.structure import complete_json, structure_text


class _FakeResp:
    def __init__(self, body: bytes = b"", status: int = 200):
        self._body, self.status = body, status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_ollama_complete_parses(monkeypatch):
    body = json.dumps({"message": {"content": '{"ok": true}'}}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: _FakeResp(body))
    assert P.ollama_complete("sys", "prompt", "qwen2.5") == '{"ok": true}'


def test_ollama_models_lists_installed(monkeypatch):
    body = json.dumps({"models": [{"name": "qwen2.5"}, {"name": "llama3.2:3b"}]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda url, timeout=0: _FakeResp(body))
    assert P.ollama_models() == ["qwen2.5", "llama3.2:3b"]


def test_ollama_available_false_when_unreachable(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert P.ollama_available() is False


def test_structure_text_routes_to_ollama(monkeypatch):
    note_json = '{"title":"T","blocks":[{"type":"banner","text":"T"},{"type":"body","text":"hi"}]}'
    monkeypatch.setattr("diannot.providers.ollama_complete", lambda *a, **k: note_json)
    note = structure_text("some study text", settings=Settings(providers=ProvidersCfg(notes="ollama")))
    assert note.title == "T"
    assert [b.type for b in note.blocks] == ["banner", "body"]


def test_complete_json_routes_to_ollama(monkeypatch):
    monkeypatch.setattr("diannot.providers.ollama_complete", lambda *a, **k: '{"k": 1}')
    out = complete_json("sys", "prompt", settings=Settings(providers=ProvidersCfg(study="ollama")))
    assert out == {"k": 1}


def test_update_config_merges_without_clobbering(tmp_path):
    p = tmp_path / "diannot.toml"
    update_config("providers", {"notes": "ollama", "ollama_model": "qwen2.5"}, path=p)
    update_config("render", {"default_theme": "histology"}, path=p)
    update_config("providers", {"study": "claude"}, path=p)  # second providers write
    data = load_config_file(p)
    assert data["render"]["default_theme"] == "histology"  # not wiped
    assert data["providers"] == {"notes": "ollama", "ollama_model": "qwen2.5", "study": "claude"}
