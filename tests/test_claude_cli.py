"""Claude engine: system-CLI detection + cli_path wiring for the packaged build.

The packaged app ships without the SDK's bundled CLI, so it must (a) still OFFER Claude and
(b) point the Agent SDK at a system-installed Claude Code CLI (which uses the user's logged-in
subscription) via ``cli_path``.
"""
import diannot.structure as S


def test_find_claude_cli_uses_path(monkeypatch):
    S._find_claude_cli.cache_clear()
    monkeypatch.setattr(S.shutil, "which", lambda name: r"C:\bin\claude.cmd" if name == "claude" else None)
    assert S._find_claude_cli() == r"C:\bin\claude.cmd"
    S._find_claude_cli.cache_clear()


def test_engine_available_from_source(monkeypatch):
    monkeypatch.setattr(S.sys, "frozen", False, raising=False)
    assert S.claude_engine_available() is True  # bundled CLI ships with the SDK in dev


def test_engine_available_frozen_depends_on_system_cli(monkeypatch):
    monkeypatch.setattr(S.sys, "frozen", True, raising=False)
    monkeypatch.setattr(S, "_find_claude_cli", lambda: None)
    assert S.claude_engine_available() is False           # no CLI installed → not ready
    monkeypatch.setattr(S, "_find_claude_cli", lambda: r"C:\bin\claude.cmd")
    assert S.claude_engine_available() is True            # installed → ready


def test_options_sets_cli_path_when_frozen_and_found(monkeypatch):
    monkeypatch.setattr(S.sys, "frozen", True, raising=False)
    monkeypatch.setattr(S, "_find_claude_cli", lambda: r"C:\bin\claude.cmd")
    opts = S._options("claude-x", "system prompt", None)
    assert opts.cli_path == r"C:\bin\claude.cmd"


def test_options_no_cli_path_from_source(monkeypatch):
    monkeypatch.setattr(S.sys, "frozen", False, raising=False)
    opts = S._options("claude-x", "system prompt", None)
    assert not opts.cli_path  # dev uses the SDK's bundled CLI
