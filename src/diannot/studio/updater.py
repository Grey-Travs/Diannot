"""Self-update via GitHub Releases — content-fail-closed.

The installed app asks GitHub for the project's latest release; if it's newer than the running
version *and* the release carries a valid signed manifest, the user can download + launch the new
``DiannotStudio-Setup.exe`` with one click. The installer upgrades in place (fixed App ID), and the
user's notes/settings live in separate folders, so updates are non-destructive.

**Integrity gate (the reason this module exists).** A partial/truncated/corrupted/tampered or
rolled-back installer must never reach a machine and auto-execute. Before launching anything we:

1. download the release's ``manifest.json`` + ``manifest.sig`` and verify the **Ed25519 signature**
   against the embedded *public* key (the private key is offline/human-held);
2. only then read the manifest's fields, and refuse any version ``<=`` the installed one
   (**anti-rollback**) or a manifest that doesn't match the offered release tag;
3. download the installer and verify its **exact byte-size + SHA-256** against the (now-trusted)
   manifest — **refusing to launch** on any mismatch.

This is TUF's core idea (signed manifest, offline trust root, anti-rollback) without the full role
hierarchy — right-sized for a trusted-friends fleet. Only meaningful in the frozen (installed) build;
a dev checkout reports no update. Every *network* call still fails closed (returns ``None`` / raises,
never auto-runs). Verification uses ``cryptography`` (Ed25519 is not in the stdlib); if it is somehow
unavailable, ``verify_manifest`` returns ``False`` (fail-closed → no update), never a crash.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

from .. import __version__

REPO = "Grey-Travs/Diannot"
_API = f"https://api.github.com/repos/{REPO}/releases/latest"
_SETUP_NAME = "DiannotStudio-Setup.exe"
_MANIFEST_NAME = "manifest.json"
_SIG_NAME = "manifest.sig"

# Ed25519 *public* key (32 bytes, base64) that signed releases must verify against. NOT a secret.
#
# Ships UNCONFIGURED: the all-zero sentinel below means "no real signing key yet", and verify_manifest
# short-circuits to False for it — so an unconfigured/placeholder build can NEVER verify (and never
# auto-install) anything, regardless of who holds any private key. This makes fail-closed STRUCTURAL,
# not a trust assumption about a discarded private key. Replace it with the real public key before the
# first signed release:
#   uv run python scripts/gen_release_key.py   (prints the constant; keep the private key OFFLINE)
_UNCONFIGURED_KEY_B64 = base64.b64encode(b"\x00" * 32).decode()
_PUBLIC_KEY_B64 = _UNCONFIGURED_KEY_B64


class IntegrityError(Exception):
    """A downloaded installer or its manifest failed verification (size, hash, signature, or rollback)."""


def _ver(text: str) -> tuple[int, int, int]:
    """Parse 'v1.2.3' / '1.2' / 'v2' into a comparable (major, minor, patch) tuple."""
    parts = (str(text or "").strip().lstrip("vV").split(".") + ["0", "0", "0"])[:3]
    nums = []
    for part in parts:
        digits = "".join(c for c in part if c.isdigit())
        nums.append(int(digits) if digits else 0)
    return nums[0], nums[1], nums[2]


def current_version() -> str:
    return __version__


def is_installed_build() -> bool:
    """True only when running as the packaged/installed exe (where self-update makes sense)."""
    return bool(getattr(sys, "frozen", False))


# --------------------------------------------------------------------------------------------------
# Verification primitives (pure, deterministic, no network — directly unit-tested).
# --------------------------------------------------------------------------------------------------

def _public_key():
    """The embedded Ed25519 public key as a verifier object. Raises if the constant is malformed."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    return Ed25519PublicKey.from_public_bytes(base64.b64decode(_PUBLIC_KEY_B64))


def verify_manifest(manifest_bytes: bytes, sig: bytes) -> bool:
    """True iff ``sig`` is a valid Ed25519 signature over the EXACT ``manifest_bytes`` for the embedded
    public key. Fail-closed: any error (bad signature, wrong length, missing dep, malformed key)
    returns False and never raises. Verify the bytes you will then parse — do not re-serialize first."""
    if _PUBLIC_KEY_B64 == _UNCONFIGURED_KEY_B64:
        return False  # no real signing key configured -> nothing verifies (fail-closed by construction)
    try:
        _public_key().verify(bytes(sig), bytes(manifest_bytes))
        return True
    except Exception:
        return False


def _sha256_file(path: str, chunk: int = 262144) -> str:
    """Streaming SHA-256 of a file as lowercase hex (256 KiB chunks, mirroring download_installer)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def verify_installer(path: str, manifest: dict) -> None:
    """Raise :class:`IntegrityError` unless the on-disk file at ``path`` matches the (already
    signature-verified) ``manifest``: exact ``size_bytes`` then ``sha256``. Size is checked FIRST as a
    cheap early-out for the partial-upload case (the bug this gate exists to stop)."""
    # Fail closed on a manifest from a NEWER format we don't understand (don't read its fields blindly).
    schema = manifest.get("schema")
    if schema is not None and schema != 1:
        raise IntegrityError(f"unsupported manifest schema: {schema!r}")
    expected_file = manifest.get("file")
    if expected_file and expected_file != _SETUP_NAME:
        raise IntegrityError(f"manifest names an unexpected installer file: {expected_file!r}")
    try:
        size = os.path.getsize(path)
    except OSError as exc:
        raise IntegrityError("the downloaded update could not be read") from exc
    try:
        expected_size = int(manifest["size_bytes"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrityError("the manifest has no valid size_bytes") from exc
    if size != expected_size:
        raise IntegrityError(f"size mismatch: got {size} bytes, expected {expected_size}")
    expected_hash = str(manifest.get("sha256", "")).strip().lower()
    if len(expected_hash) != 64 or any(c not in "0123456789abcdef" for c in expected_hash):
        raise IntegrityError("the manifest has no valid sha256")
    actual = _sha256_file(path)
    if actual != expected_hash:
        raise IntegrityError("sha256 mismatch — the installer does not match its manifest")


# --------------------------------------------------------------------------------------------------
# Network flow (fail-closed): check → download+verify → launch.
# --------------------------------------------------------------------------------------------------

def _asset_url(assets, name: str) -> str | None:
    """The download URL of the release asset named exactly ``name`` (case-insensitive), or None."""
    target = name.lower()
    return next(
        (a.get("browser_download_url") for a in (assets or [])
         if str(a.get("name", "")).lower() == target),
        None,
    )


def check_for_update(timeout: float = 6.0) -> dict | None:
    """Return ``{'version','url','notes','manifest_url','sig_url'}`` if a newer, SIGNED release exists,
    else None. Never raises. A release without both ``manifest.json`` and ``manifest.sig`` assets is
    treated as "no update" (fail-closed) — an unsigned release is never offered."""
    try:
        req = urllib.request.Request(
            _API, headers={"Accept": "application/vnd.github+json", "User-Agent": "Diannot-Updater"}
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    tag = data.get("tag_name") or data.get("name") or ""
    if _ver(tag) <= _ver(__version__):
        return None
    assets = data.get("assets") or []
    url = next(
        (a.get("browser_download_url") for a in assets
         if str(a.get("name", "")).lower().endswith(".exe")),
        None,
    )
    manifest_url = _asset_url(assets, _MANIFEST_NAME)
    sig_url = _asset_url(assets, _SIG_NAME)
    if not url or not manifest_url or not sig_url:
        return None  # no installer, or an unsigned/un-manifested release -> no update
    return {
        "version": tag.lstrip("vV"),
        "url": url,
        "notes": (data.get("body") or "").strip()[:600],
        "manifest_url": manifest_url,
        "sig_url": sig_url,
    }


def _download_bytes(url: str, timeout: float = 30.0) -> bytes:
    """GET the raw bytes at ``url`` (used for the small manifest + signature assets)."""
    req = urllib.request.Request(url, headers={"User-Agent": "Diannot-Updater"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def download_installer(url: str, on_progress=None, timeout: float = 60.0) -> str:
    """Download the setup.exe into a FRESH per-download temp directory and return its path.
    ``on_progress(fraction)`` optional.

    Uses a unique ``mkdtemp`` directory rather than a fixed, world-predictable path, so the verified
    file can't be swapped under us in the window between verification and launch. Performs NO
    verification — callers must use :func:`download_and_verify` (or :func:`verify_installer`) before
    :func:`launch_installer`. On any download error the partial file + its temp dir are removed before
    the error propagates, so no stray installer is left behind.
    """
    dest_dir = tempfile.mkdtemp(prefix="diannot-update-")
    dest = os.path.join(dest_dir, _SETUP_NAME)
    req = urllib.request.Request(url, headers={"User-Agent": "Diannot-Updater"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            got = 0
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                out.write(chunk)
                got += len(chunk)
                if on_progress and total:
                    on_progress(got / total)
    except BaseException:
        _safe_cleanup(dest)
        raise
    return dest


def _safe_remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _safe_cleanup(path: str) -> None:
    """Remove a downloaded installer and the per-download temp dir created for it (best-effort)."""
    _safe_remove(path)
    try:
        os.rmdir(os.path.dirname(path))
    except OSError:
        pass


def download_and_verify(info: dict, on_progress=None, timeout: float = 60.0) -> str:
    """Full content-fail-closed update flow. Returns the path to a verified installer ready to launch,
    or raises :class:`IntegrityError` (verification failed — caller must NOT launch and stays on the
    current version) / a network error. Order matters: verify the manifest *signature* first, then
    trust its fields (anti-rollback + tag binding), then verify the downloaded installer's bytes.

    On any integrity failure the (possibly partial) installer temp file is deleted, so no unverified
    ``.exe`` is left behind."""
    manifest_url = info.get("manifest_url")
    sig_url = info.get("sig_url")
    if not manifest_url or not sig_url:
        raise IntegrityError("this release has no signed manifest")

    manifest_bytes = _download_bytes(manifest_url, timeout=timeout)
    sig = _download_bytes(sig_url, timeout=timeout)
    if not verify_manifest(manifest_bytes, sig):
        raise IntegrityError("the update's signature could not be verified")

    try:
        manifest = json.loads(manifest_bytes)
    except ValueError as exc:
        raise IntegrityError("the update manifest was unreadable") from exc
    if not isinstance(manifest, dict):
        raise IntegrityError("the update manifest was malformed")

    # Only now that the manifest is trusted may we read its fields.
    manifest_ver = str(manifest.get("version", ""))
    if _ver(manifest_ver) <= _ver(__version__):
        raise IntegrityError(f"refusing to roll back to v{manifest_ver or '?'} from v{__version__}")
    # Bind the manifest to the tag the user was offered (defeats a re-pointed asset). Mandatory on
    # every path into this function — never silently skip the binding when the offered version is empty.
    offered = str(info.get("version", ""))
    if not offered:
        raise IntegrityError("the offered release has no version to bind the manifest to")
    if _ver(manifest_ver) != _ver(offered):
        raise IntegrityError("the update manifest does not match the offered release")

    path = download_installer(info["url"], on_progress=on_progress, timeout=timeout)
    try:
        verify_installer(path, manifest)
    except IntegrityError:
        _safe_cleanup(path)
        raise
    return path


def launch_installer(path: str) -> None:
    """Launch the downloaded installer (Windows). The app should quit right after.

    Only call this on a path returned by :func:`download_and_verify` (or one you have passed through
    :func:`verify_installer`) — it runs the file unconditionally.
    """
    os.startfile(path)  # noqa: S606 — runs the just-verified official Diannot installer
