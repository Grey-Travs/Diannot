"""GitHub-Releases self-update: version compare + release check (mocked HTTP)."""
import json
import urllib.error

from diannot.studio import updater


class _FakeResp:
    def __init__(self, body: bytes):
        self._body = body
        self.headers = {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_version_parse_and_compare():
    assert updater._ver("v1.2.3") == (1, 2, 3)
    assert updater._ver("0.1") == (0, 1, 0)
    assert updater._ver("v2") == (2, 0, 0)
    assert updater._ver("") == (0, 0, 0)
    assert updater._ver("v1.0.0") > updater._ver("0.9.9")


def test_check_offers_newer_signed_release(monkeypatch):
    body = json.dumps({
        "tag_name": "v9.9.9",
        "body": "release notes",
        "assets": [
            {"name": "DiannotStudio-Setup.exe", "browser_download_url": "https://x/setup.exe"},
            {"name": "manifest.json", "browser_download_url": "https://x/manifest.json"},
            {"name": "manifest.sig", "browser_download_url": "https://x/manifest.sig"},
        ],
    }).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: _FakeResp(body))
    info = updater.check_for_update()
    assert info is not None
    assert info["version"] == "9.9.9"
    assert info["url"].endswith("setup.exe")
    assert info["manifest_url"].endswith("manifest.json")
    assert info["sig_url"].endswith("manifest.sig")


def test_check_none_when_release_is_unsigned(monkeypatch):
    # A newer release with an installer but NO manifest/sig is treated as no update (fail-closed):
    # an unsigned release must never be offered for auto-install.
    body = json.dumps({
        "tag_name": "v9.9.9",
        "assets": [{"name": "DiannotStudio-Setup.exe", "browser_download_url": "https://x/setup.exe"}],
    }).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: _FakeResp(body))
    assert updater.check_for_update() is None


def test_check_none_when_not_newer(monkeypatch):
    body = json.dumps({
        "tag_name": "v0.0.1",
        "assets": [{"name": "DiannotStudio-Setup.exe", "browser_download_url": "x"}],
    }).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: _FakeResp(body))
    assert updater.check_for_update() is None


def test_check_none_without_exe_asset(monkeypatch):
    body = json.dumps({"tag_name": "v9.9.9", "assets": [{"name": "notes.txt", "browser_download_url": "x"}]}).encode()
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: _FakeResp(body))
    assert updater.check_for_update() is None


def test_check_none_on_network_error(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("no internet")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert updater.check_for_update() is None
