"""Real-browser smoke test: opening a note written by a NEWER build shows the read-only "safe mode"
banner, doesn't crash, and does NOT clobber the on-disk file (its newer content survives).

Schema versioning's whole promise is that a staggered auto-update rollout never bricks or silently
corrupts a user's notes. The fast `user` fixture can't prove the editor's autosave/lifecycle leaves
the file untouched — that needs the real server + a real browser. Mechanics: a subprocess launches the
real studio (no AI, so no mock needed), Playwright opens a ``schema_version: 999`` note, and we assert
(a) the read-only banner renders, (b) no slot-deletion error server-side or in the console, and
(c) the on-disk JSON still carries ``schema_version: 999`` and its unknown block after the page settles.

Skips automatically where Chromium isn't installed (e.g. the Ubuntu CI), so it never breaks the suite.
"""
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest

pytest.importorskip("playwright")


def _chromium_path() -> str | None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = p.chromium.executable_path
        return exe if (exe and Path(exe).exists()) else None
    except Exception:
        return None


pytestmark = [
    pytest.mark.browser,  # deselected by default; run serially in the dedicated CI smoke job
    pytest.mark.skipif(
        _chromium_path() is None,
        reason="Chromium not installed (run a PDF/PNG export once, or `playwright install chromium`).",
    ),
]

_LAUNCHER = (
    "import sys\n"
    "from diannot.studio.app import launch_studio\n"
    "launch_studio(workspace=sys.argv[1], native=False, host='127.0.0.1', port=int(sys.argv[2]), show=False)\n"
)

# A note from a hypothetical future Diannot: a version this build doesn't understand, an unknown
# top-level field, and an unknown block type alongside a known one.
_FUTURE_NOTE = {
    "schema_version": 999,
    "title": "From a newer Diannot",
    "theme": "circulatory",
    "pack": "study_notes",
    "future_only_field": {"added": "by a newer build"},
    "blocks": [
        {"type": "banner", "text": "FUTURE NOTE"},
        {"type": "body", "text": "This block is understood today."},
        {"type": "hologram", "data": "a block type this build has never heard of"},
    ],
}


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_port(port: int, timeout: float = 30.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.3)
    return False


def test_future_schema_note_is_read_only_and_not_clobbered(tmp_path):
    from playwright.sync_api import sync_playwright

    ws = tmp_path / "ws"
    ws.mkdir()
    note_file = ws / "Future.note.json"
    original_text = json.dumps(_FUTURE_NOTE, indent=2)
    note_file.write_text(original_text, encoding="utf-8")

    launcher = tmp_path / "launch.py"
    launcher.write_text(_LAUNCHER, encoding="utf-8")
    log_path = tmp_path / "server.log"
    port = _free_port()

    # Strip PYTEST_CURRENT_TEST so NiceGUI's is_pytest() is False in the child and it runs the real
    # server (otherwise it switches to its screen-test mode and demands NICEGUI_SCREEN_TEST_PORT).
    child_env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, str(launcher), str(ws), str(port)],
                                stdout=log, stderr=subprocess.STDOUT, env=child_env)
        try:
            assert _wait_port(port), f"studio server didn't start:\n{log_path.read_text(errors='replace')}"
            time.sleep(2.0)  # let routes settle after the port opens

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                console: list[str] = []
                page.on("console", lambda m: console.append(f"{m.type}:{m.text}"))
                page.on("pageerror", lambda e: console.append(f"pageerror:{e}"))

                page.goto(f"http://127.0.0.1:{port}/note?path={quote(str(note_file))}",
                          wait_until="networkidle")
                # The read-only safe-mode banner renders (and the note opened — no hard crash).
                page.wait_for_selector("text=made in a newer version of Diannot", timeout=15000)
                # Give any autosave/disconnect path a chance to (wrongly) fire before we check the file.
                time.sleep(2.5)
                browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    # The on-disk note must be untouched: its newer version + unknown block survive read-only viewing.
    after = json.loads(note_file.read_text(encoding="utf-8"))
    assert after.get("schema_version") == 999, "future-schema note was clobbered on load/save!"
    assert any(b.get("type") == "hologram" for b in after["blocks"]), "unknown block was dropped from disk!"
    assert "future_only_field" in after, "unknown top-level field was dropped from disk!"

    server_log = log_path.read_text(encoding="utf-8", errors="replace")
    assert "slot belongs to has been deleted" not in server_log, server_log[-2000:]
    browser_slot = [c for c in console if "slot" in c.lower() and "delet" in c.lower()]
    assert not browser_slot, browser_slot
