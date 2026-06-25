"""Real-browser smoke: the first-run welcome shows the zero-config nudge and the
'Import your first PDF' button drops the user straight into the import wizard — without a
NiceGUI slot-lifecycle crash (the v0.6.1 'parent element this slot belongs to has been deleted'
class). The fast `user` fixture can't see this: the dialog → navigate flow is browser-only.

Mechanics mirror test_retry_smoke: a subprocess launches the real studio (no AI needed on first
run, so nothing is mocked), Playwright drives Chromium, and we assert the dialog → /import path
works and no slot-deletion error is logged. Storage is fresh because the launcher lives in tmp_path,
so `onboarded` is unset and the welcome actually shows.

Skips automatically where Chromium isn't installed (e.g. the Ubuntu CI), so it never breaks the suite.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

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


def test_first_run_nudge_opens_import_without_slot_crash(tmp_path):
    from playwright.sync_api import sync_playwright

    ws = tmp_path / "ws"
    ws.mkdir()
    launcher = tmp_path / "launch.py"
    launcher.write_text(_LAUNCHER, encoding="utf-8")
    log_path = tmp_path / "server.log"
    port = _free_port()

    # Strip PYTEST_CURRENT_TEST so NiceGUI's is_pytest() is False in the child (else it switches to
    # its screen-test mode and demands NICEGUI_SCREEN_TEST_PORT).
    child_env = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}
    # Run in tmp_path: NiceGUI persists app.storage.general in `.nicegui/` relative to CWD, so a fresh
    # CWD means `onboarded` is unset and the first-run welcome actually shows (the dev repo's own
    # .nicegui already has onboarded=True, which would otherwise suppress it).
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen([sys.executable, str(launcher), str(ws), str(port)],
                                stdout=log, stderr=subprocess.STDOUT, env=child_env, cwd=str(tmp_path))
        try:
            assert _wait_port(port), f"studio server didn't start:\n{log_path.read_text(errors='replace')}"
            time.sleep(2.0)  # let routes settle after the port opens

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                console: list[str] = []
                page.on("console", lambda m: console.append(f"{m.type}:{m.text}"))
                page.on("pageerror", lambda e: console.append(f"pageerror:{e}"))

                page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                page.wait_for_selector("text=Welcome to Diannot Studio", timeout=15000)
                assert "Import your first PDF" in page.content()

                page.click("text=Import your first PDF")
                page.wait_for_url("**/import**", timeout=15000)
                # the import wizard rendered (didn't crash on the dialog->navigate handoff)
                page.wait_for_selector("text=Make notes from files", timeout=15000)
                browser.close()
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    server_log = log_path.read_text(encoding="utf-8", errors="replace")
    assert "slot belongs to has been deleted" not in server_log, server_log[-2000:]
    browser_slot = [c for c in console if "slot" in c.lower() and "delet" in c.lower()]
    assert not browser_slot, browser_slot
