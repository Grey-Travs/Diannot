"""Self-update via GitHub Releases.

The installed app asks GitHub for the project's latest release; if it's newer than the
running version, the user can download + launch the new ``DiannotStudio-Setup.exe`` with one
click. The installer upgrades in place (fixed App ID), and the user's notes/settings live in
separate folders, so updates are non-destructive.

Only meaningful in the frozen (installed) build — a dev checkout reports no update. Stdlib only;
every network call fails closed (returns None / no update) so a missing/private repo or no
internet never breaks the app. For this to reach friends, the GitHub *Releases* must be public.
"""
from __future__ import annotations

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


def check_for_update(timeout: float = 6.0) -> dict | None:
    """Return ``{'version', 'url', 'notes'}`` if a newer release exists, else None. Never raises."""
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
    url = next(
        (a.get("browser_download_url") for a in (data.get("assets") or [])
         if str(a.get("name", "")).lower().endswith(".exe")),
        None,
    )
    if not url:
        return None
    return {"version": tag.lstrip("vV"), "url": url, "notes": (data.get("body") or "").strip()[:600]}


def download_installer(url: str, on_progress=None, timeout: float = 60.0) -> str:
    """Download the setup.exe to a temp file and return its path. ``on_progress(fraction)`` optional."""
    dest = os.path.join(tempfile.gettempdir(), _SETUP_NAME)
    req = urllib.request.Request(url, headers={"User-Agent": "Diannot-Updater"})
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
    return dest


def launch_installer(path: str) -> None:
    """Launch the downloaded installer (Windows). The app should quit right after."""
    os.startfile(path)  # noqa: S606 — runs the just-downloaded official Diannot installer
