"""Real-browser smoke test: 'Retry organizing' on a VISION-failed note re-runs vision (from the
preserved page scans) without the v0.6.1 'parent element this slot belongs to has been deleted' crash.

Sibling of test_retry_smoke.py (the text path). The vision retry branch in note.py reads the persisted
PNGs back from <note>.assets/ and calls structure_image — this asserts that path clears the degraded
banner with no slot-deletion error. structure_image is mocked to a deterministic success (no network).

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

from diannot.models import BannerBlock, ImageBlock, Note

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

# Mock structure_image (the VISION re-run) to a deterministic success — no network, no real model.
_LAUNCHER = (
    "import sys\n"
    "import diannot.studio.pages.note as note_mod\n"
    "from diannot.models import Note, BannerBlock, ScriptHeadingBlock, BodyBlock\n"
    "def _mock(images, title=None, theme='circulatory', pack='study_notes', model=None,\n"
    "          settings=None, max_retries=2, source_pages=None):\n"
    "    assert images and all(isinstance(b, (bytes, bytearray)) for b in images)  # read back from disk\n"
    "    return Note(title=title or 'Organized', theme=theme, pack=pack,\n"
    "        blocks=[BannerBlock(text=title or 'Organized'), ScriptHeadingBlock(text='Overview'),\n"
    "                BodyBlock(text='Structured from the page image.')], extraction_status=None)\n"
    "note_mod.structure_image = _mock\n"
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


def test_vision_retry_organizing_button_no_slot_crash(tmp_path):
    from playwright.sync_api import sync_playwright

    ws = tmp_path / "ws"
    ws.mkdir()
    note_file = ws / "Scanned_Lecture.note.json"
    # The assets dir is keyed on the note STEM (note.py / pipeline.persist_page_images agree).
    assets = ws / f"{note_file.stem}.assets"
    assets.mkdir()
    (assets / "page_01.png").write_bytes(b"\x89PNG-fake-scan-bytes")  # content irrelevant (mock)
    img_src = f"/file?path={quote(str((assets / 'page_01.png').resolve()))}"
    note = Note(
        title="Scanned Lecture", theme="circulatory", pack="study_notes",
        blocks=[BannerBlock(text="Scanned Lecture"),
                ImageBlock(src=img_src, caption="Couldn't auto-organize this page.",
                           confidence="low", source_page=1)],
        extraction_status="failed", source_images=["page_01.png"],
    )
    note_file.write_text(note.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")

    launcher = tmp_path / "launch.py"
    launcher.write_text(_LAUNCHER, encoding="utf-8")
    log_path = tmp_path / "server.log"
    port = _free_port()

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
