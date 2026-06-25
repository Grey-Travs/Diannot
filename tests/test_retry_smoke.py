"""Real-browser smoke test: the degraded-note 'Retry organizing' button works without the v0.6.1
'parent element this slot belongs to has been deleted' crash.

This is the one test class the fast NiceGUI `user` fixture CANNOT cover — the slot-deletion bug lives
in the browser/Vue lifecycle, so it needs a real headless Chromium driving the live studio server.
Mechanics: a subprocess launches the real app with `structure_text` mocked to a deterministic success
(no network), Playwright clicks Retry, and we assert (a) no slot-deletion error server-side or in the
browser console and (b) the banner clears on the success reload (a silently-failing retry would leave
it and time out — so this is a genuine gate, not a no-op).

Skips automatically where Chromium isn't installed (e.g. the Ubuntu CI), so it never breaks the suite.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

import pytest

from diannot.models import BannerBlock, BodyBlock, Note

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
    "import diannot.studio.pages.note as note_mod\n"
    "from diannot.models import Note, BannerBlock, ScriptHeadingBlock, TermDefinitionBlock, BodyBlock\n"
    "def _mock(raw_text, title=None, theme='circulatory', pack='study_notes', model=None,\n"
    "          settings=None, max_retries=2, on_progress=None):\n"
    "    return Note(title=title or 'Organized', theme=theme, pack=pack,\n"
    "        blocks=[BannerBlock(text=title or 'Organized'), ScriptHeadingBlock(text='Overview'),\n"
    "                TermDefinitionBlock(term='Mitochondria', definition='Powerhouse of the cell.'),\n"
    "                BodyBlock(text='Structured body.')], extraction_status=None)\n"
    "note_mod.structure_text = _mock\n"
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


def test_retry_organizing_button_no_slot_crash(tmp_path):
    from playwright.sync_api import sync_playwright

    ws = tmp_path / "ws"
    ws.mkdir()
    raw = "\n\n".join(f"Paragraph {i}: long lecture text that failed to structure. " * 3 for i in range(8))
    note = Note(
        title="Big Lecture", theme="circulatory", pack="study_notes",
        blocks=[BannerBlock(text="Big Lecture"),
                BodyBlock(text=raw[:1200], confidence="low"),
                BodyBlock(text=raw[1200:2400], confidence="low")],
        extraction_status="failed", source_text=raw,
    )
    note_file = ws / "Big_Lecture.note.json"
    note_file.write_text(note.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")

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
                page.wait_for_selector("text=Retry organizing", timeout=15000)
                assert "couldn't be auto-organized" in page.content()

                page.click("text=Retry organizing")
                # success reloads the page -> banner/button detaches; a no-op retry would time out here
                page.wait_for_selector("text=Retry organizing", state="detached", timeout=20000)
                page.wait_for_load_state("networkidle")
                assert page.query_selector("text=Retry organizing") is None
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
