"""Self-update integrity gate: signed-manifest verification, size/hash checks, anti-rollback, and the
content-fail-closed download flow. All deterministic — a throwaway Ed25519 keypair, no network, no real
installer (the public key constant is monkeypatched to the test key)."""
import base64
import hashlib
import json
import os
import tempfile
import urllib.error
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from diannot.studio import updater

_SETUP_NAME = "DiannotStudio-Setup.exe"


@pytest.fixture
def signer(monkeypatch):
    """A throwaway keypair whose PUBLIC half replaces the embedded one for the duration of a test."""
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    monkeypatch.setattr(updater, "_PUBLIC_KEY_B64", base64.b64encode(pub_raw).decode())
    return priv


def _manifest_bytes(version="9.9.9", size=0, sha="0" * 64, file=_SETUP_NAME):
    manifest = {"schema": 1, "version": version, "file": file, "size_bytes": size, "sha256": sha}
    return (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")


# ---- verify_manifest (signature) -----------------------------------------------------------------

def test_verify_manifest_accepts_valid_signature(signer):
    mb = _manifest_bytes()
    assert updater.verify_manifest(mb, signer.sign(mb)) is True


def test_verify_manifest_rejects_tampered_manifest(signer):
    mb = _manifest_bytes()
    sig = signer.sign(mb)
    tampered = bytearray(mb)
    tampered[10] ^= 0x01
    assert updater.verify_manifest(bytes(tampered), sig) is False


def test_verify_manifest_rejects_tampered_signature(signer):
    mb = _manifest_bytes()
    sig = bytearray(signer.sign(mb))
    sig[0] ^= 0x01
    assert updater.verify_manifest(mb, bytes(sig)) is False


def test_verify_manifest_rejects_wrong_key(signer):
    # Signed by a DIFFERENT key than the embedded one -> rejected.
    other = Ed25519PrivateKey.generate()
    mb = _manifest_bytes()
    assert updater.verify_manifest(mb, other.sign(mb)) is False


def test_verify_manifest_fail_closed_on_garbage(signer):
    # Malformed signature (wrong length) must return False, never raise.
    assert updater.verify_manifest(b"{}", b"too-short") is False
    assert updater.verify_manifest(b"", b"") is False


# ---- verify_installer (size + hash) --------------------------------------------------------------

def _write(tmp_path, data: bytes, name=_SETUP_NAME) -> str:
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def test_verify_installer_passes_on_match(tmp_path):
    data = b"installer bytes " * 64
    path = _write(tmp_path, data)
    manifest = {"file": _SETUP_NAME, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    updater.verify_installer(path, manifest)  # does not raise


def test_verify_installer_rejects_truncated(tmp_path):
    data = b"installer bytes " * 64
    path = _write(tmp_path, data[:-10])  # short upload
    manifest = {"file": _SETUP_NAME, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    with pytest.raises(updater.IntegrityError, match="size mismatch"):
        updater.verify_installer(path, manifest)


def test_verify_installer_rejects_same_size_different_bytes(tmp_path):
    data = b"installer bytes " * 64
    corrupt = bytearray(data)
    corrupt[5] ^= 0xFF  # same length, one byte changed
    path = _write(tmp_path, bytes(corrupt))
    manifest = {"file": _SETUP_NAME, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    with pytest.raises(updater.IntegrityError, match="sha256 mismatch"):
        updater.verify_installer(path, manifest)


def test_verify_installer_rejects_bad_manifest_fields(tmp_path):
    data = b"x" * 32
    path = _write(tmp_path, data)
    with pytest.raises(updater.IntegrityError):  # no size_bytes
        updater.verify_installer(path, {"file": _SETUP_NAME, "sha256": "a" * 64})
    with pytest.raises(updater.IntegrityError):  # not a 64-hex sha
        updater.verify_installer(path, {"file": _SETUP_NAME, "size_bytes": len(data), "sha256": "nope"})
    with pytest.raises(updater.IntegrityError):  # wrong installer file name
        updater.verify_installer(path, {"file": "evil.exe", "size_bytes": len(data),
                                        "sha256": hashlib.sha256(data).hexdigest()})


# ---- download_and_verify (the full content-fail-closed flow) -------------------------------------

def _wire(monkeypatch, tmp_path, manifest_bytes, sig, installer_bytes, *, calls=None):
    """Stub the two network calls: manifest/sig fetch + installer download."""
    def fake_bytes(url, timeout=30.0):
        return {"M": manifest_bytes, "S": sig}[url]

    def fake_download(url, on_progress=None, timeout=60.0):
        if calls is not None:
            calls.append(url)
        p = tmp_path / _SETUP_NAME
        p.write_bytes(installer_bytes)
        return str(p)

    monkeypatch.setattr(updater, "_download_bytes", fake_bytes)
    monkeypatch.setattr(updater, "download_installer", fake_download)


def _info():
    return {"version": "9.9.9", "url": "U", "manifest_url": "M", "sig_url": "S"}


def test_download_and_verify_happy_path(signer, monkeypatch, tmp_path):
    data = b"good installer " * 100
    mb = _manifest_bytes(size=len(data), sha=hashlib.sha256(data).hexdigest())
    _wire(monkeypatch, tmp_path, mb, signer.sign(mb), data)
    path = updater.download_and_verify(_info())
    assert Path(path).exists() and Path(path).read_bytes() == data


def test_download_and_verify_rejects_bad_signature(signer, monkeypatch, tmp_path):
    data = b"good installer " * 100
    mb = _manifest_bytes(size=len(data), sha=hashlib.sha256(data).hexdigest())
    bad_sig = bytearray(signer.sign(mb)); bad_sig[0] ^= 0x01
    calls = []
    _wire(monkeypatch, tmp_path, mb, bytes(bad_sig), data, calls=calls)
    with pytest.raises(updater.IntegrityError, match="signature"):
        updater.download_and_verify(_info())
    assert calls == []  # installer never downloaded — signature checked first


def test_download_and_verify_anti_rollback(signer, monkeypatch, tmp_path):
    # A correctly-signed manifest whose version is OLDER than installed must be refused.
    data = b"old installer " * 100
    mb = _manifest_bytes(version="0.0.1", size=len(data), sha=hashlib.sha256(data).hexdigest())
    calls = []
    _wire(monkeypatch, tmp_path, mb, signer.sign(mb), data, calls=calls)
    with pytest.raises(updater.IntegrityError, match="roll back"):
        updater.download_and_verify(_info())
    assert calls == []  # refused before downloading the installer


def test_download_and_verify_tag_mismatch(signer, monkeypatch, tmp_path):
    # Manifest is validly signed but its version != the offered release tag -> refuse (re-pointed asset).
    data = b"mismatch installer " * 100
    mb = _manifest_bytes(version="8.8.8", size=len(data), sha=hashlib.sha256(data).hexdigest())
    _wire(monkeypatch, tmp_path, mb, signer.sign(mb), data)
    with pytest.raises(updater.IntegrityError, match="does not match"):
        updater.download_and_verify(_info())  # info offers 9.9.9


def test_download_and_verify_deletes_bad_installer(signer, monkeypatch, tmp_path):
    # Signature + version OK, but the downloaded bytes don't match -> raise AND delete the temp file.
    data = b"declared installer " * 100
    mb = _manifest_bytes(size=len(data), sha=hashlib.sha256(data).hexdigest())
    _wire(monkeypatch, tmp_path, mb, signer.sign(mb), data[:-5])  # short download
    with pytest.raises(updater.IntegrityError, match="size mismatch"):
        updater.download_and_verify(_info())
    assert not (tmp_path / _SETUP_NAME).exists()  # no unverified .exe left behind


def test_download_and_verify_requires_manifest_urls(signer):
    with pytest.raises(updater.IntegrityError, match="no signed manifest"):
        updater.download_and_verify({"version": "9.9.9", "url": "U"})


def test_download_and_verify_requires_offered_version(signer, monkeypatch, tmp_path):
    # Tag-binding must be mandatory: a caller that omits the offered version is refused, not silently
    # downgraded to "anti-rollback only".
    data = b"installer " * 80
    mb = _manifest_bytes(size=len(data), sha=hashlib.sha256(data).hexdigest())
    _wire(monkeypatch, tmp_path, mb, signer.sign(mb), data)
    with pytest.raises(updater.IntegrityError, match="no version to bind"):
        updater.download_and_verify({"url": "U", "manifest_url": "M", "sig_url": "S"})  # no "version"


def test_download_and_verify_rejects_unknown_schema(signer, monkeypatch, tmp_path):
    # A validly-signed, newer manifest from a FUTURE format we don't understand must fail closed, not be
    # read field-by-field blindly.
    data = b"future installer " * 50
    manifest = {"schema": 2, "version": "9.9.9", "file": _SETUP_NAME,
                "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    mb = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _wire(monkeypatch, tmp_path, mb, signer.sign(mb), data)
    with pytest.raises(updater.IntegrityError, match="schema"):
        updater.download_and_verify(_info())


def test_manifest_network_error_propagates_as_non_integrity(signer, monkeypatch):
    # A network failure must NOT masquerade as an IntegrityError — home.py shows a different message for
    # each ("download failed" vs "couldn't be verified").
    def boom(url, timeout=30.0):
        raise urllib.error.URLError("no internet")
    monkeypatch.setattr(updater, "_download_bytes", boom)
    with pytest.raises(urllib.error.URLError):
        updater.download_and_verify(_info())


def test_installer_network_error_propagates_as_non_integrity(signer, monkeypatch):
    data = b"good installer " * 100
    mb = _manifest_bytes(size=len(data), sha=hashlib.sha256(data).hexdigest())
    monkeypatch.setattr(updater, "_download_bytes", lambda url, timeout=30.0: {"M": mb, "S": signer.sign(mb)}[url])

    def boom(url, on_progress=None, timeout=60.0):
        raise urllib.error.URLError("connection dropped")
    monkeypatch.setattr(updater, "download_installer", boom)
    with pytest.raises(urllib.error.URLError):
        updater.download_and_verify(_info())


# ---- the shipped public key + download_installer itself --------------------------------------------

def test_embedded_public_key_is_valid_32_bytes():
    # Whether the unconfigured sentinel or a real key, the shipped constant must decode to a loadable
    # 32-byte Ed25519 key — guards against a corrupted constant silently disabling all updates.
    assert len(base64.b64decode(updater._PUBLIC_KEY_B64)) == 32
    updater._public_key()  # must not raise


def test_unconfigured_key_fails_closed(monkeypatch):
    # The all-zero sentinel means "no signing key configured" -> verify_manifest can NEVER succeed,
    # regardless of who holds any private key. This is the structural fail-closed guarantee.
    monkeypatch.setattr(updater, "_PUBLIC_KEY_B64", updater._UNCONFIGURED_KEY_B64)
    assert updater.verify_manifest(b"anything", b"\x00" * 64) is False


class _FakeHTTP:
    """Minimal urlopen stand-in: a context manager that streams `data` in read(n) chunks."""
    def __init__(self, data: bytes, with_length: bool = True):
        self._data, self._pos = data, 0
        self.headers = {"Content-Length": str(len(data))} if with_length else {}

    def read(self, n: int) -> bytes:
        chunk = self._data[self._pos:self._pos + n]
        self._pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_download_installer_streams_to_unique_temp_dir(monkeypatch):
    # The root-cause function: it must write the FULL stream, into a UNIQUE temp subdir (not the fixed
    # world-predictable path), and report progress.
    data = b"installer payload " * 50
    monkeypatch.setattr("urllib.request.urlopen", lambda req, timeout=0: _FakeHTTP(data))
    fractions: list[float] = []
    path = updater.download_installer("http://x/setup.exe", on_progress=fractions.append)
    try:
        assert os.path.basename(path) == _SETUP_NAME
        assert Path(path).read_bytes() == data            # full bytes written
        assert os.path.dirname(path) != tempfile.gettempdir()        # a unique subdir...
        assert Path(path).parent.parent == Path(tempfile.gettempdir())  # ...directly under the temp root
        assert fractions and fractions[-1] == 1.0          # progress reached 100%
    finally:
        updater._safe_cleanup(path)
    assert not Path(path).exists() and not Path(path).parent.exists()  # cleanup removes file + its dir
