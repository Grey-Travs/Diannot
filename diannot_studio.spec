# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Diannot Studio — a one-folder Windows desktop app.

Build:  uv run pyinstaller diannot_studio.spec --noconfirm
Result: dist/DiannotStudio/DiannotStudio.exe  (double-click → native window)

Ships WITHOUT Chromium (downloaded on first PDF/PNG export). Bundles the Claude
Agent SDK's CLI, NiceGUI assets, pywebview's WebView2 DLLs, and the diannot
package data (themes/packs/fonts) + sample notebook.
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files

datas, binaries, hiddenimports = [], [], []

# Full collection (code + data + binaries) for the frameworks.
for pkg in ("nicegui", "pywebview", "playwright"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Data-only collection: diannot themes/packs/fonts + certs.
for pkg in ("diannot", "certifi"):
    datas += collect_data_files(pkg)

# Claude Agent SDK: keep the python package (so `import claude_agent_sdk` works) but DROP its
# bundled CLI `_bundled/claude.exe` (~214 MB) — this nearly halves the download. The build defaults
# to the free Gemini key; the Claude engine still works for users who install the Claude Code CLI
# themselves (structure._find_claude_cli detects it and the SDK is pointed at it via cli_path).
datas += [
    (src, dst) for (src, dst) in collect_data_files("claude_agent_sdk")
    if "_bundled" not in src.replace("\\", "/").lower()
]

# Repo-root sample notebook (resolved at runtime via sys._MEIPASS).
datas += [("examples/sample_notebook", "examples/sample_notebook")]

hiddenimports += [
    "uvicorn", "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.loops.asyncio", "uvicorn.protocols", "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto", "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl", "uvicorn.lifespan",
    "uvicorn.lifespan.on", "fastapi", "starlette", "sse_starlette", "anyio",
    "clr", "clr_loader", "pythonnet",
    "webview.platforms.winforms", "webview.platforms.edgechromium",
    "engineio.async_drivers.asgi", "websockets", "websockets.legacy",
    "h11", "watchfiles",
]

excludes = [
    "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6", "qtpy",
    "gi", "gtk", "matplotlib", "IPython", "notebook", "pytest",
]

a = Analysis(
    ["studio_main.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DiannotStudio",
    console=False,  # windowed app — no console window
    disable_windowed_traceback=False,
    icon="assets/diannot.ico",
)
coll = COLLECT(exe, a.binaries, a.datas, name="DiannotStudio")
