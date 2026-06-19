"""PyInstaller entry point for Diannot Studio (the packaged double-click app).

Double-clicking the built ``DiannotStudio`` opens the native desktop window.
Pass ``--web`` to use a browser instead, plus ``--port``/``--no-show``/``--workspace``.
"""
from __future__ import annotations

import argparse
import multiprocessing
import os
import sys


def _prepare_env() -> None:
    # In the packaged app, keep Playwright's Chromium in a writable per-user cache
    # so the first PDF/PNG export can download it (the build ships without Chromium).
    if getattr(sys, "frozen", False) and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = os.path.join(base, "Diannot", "ms-playwright")


def main() -> None:
    _prepare_env()
    parser = argparse.ArgumentParser(prog="DiannotStudio")
    parser.add_argument("--web", action="store_true", help="Open in a browser instead of a native window.")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--no-show", action="store_true")
    parser.add_argument("--workspace", default=None)
    args, _ = parser.parse_known_args()

    from diannot.studio.app import launch_studio

    launch_studio(workspace=args.workspace, native=not args.web, port=args.port, show=not args.no_show)


if __name__ == "__main__":
    multiprocessing.freeze_support()  # MUST be first — native mode spawns a child process
    main()
