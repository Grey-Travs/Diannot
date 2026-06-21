"""Claude engine availability (drives whether Settings offers it as a ready engine).

In a packaged build the SDK's bundled CLI is stripped, so Claude is "ready" only when a
system-installed Claude Code CLI is found; from source the bundled CLI is always present.
Deterministic via monkeypatching _find_claude_cli (don't depend on the test machine's PATH).
"""
import sys

import diannot.structure as structure


def test_claude_unavailable_in_packaged_build_without_cli(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(structure, "_find_claude_cli", lambda: None)
    assert structure.claude_engine_available() is False


def test_claude_available_in_packaged_build_with_system_cli(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(structure, "_find_claude_cli", lambda: r"C:\npm\claude.cmd")
    assert structure.claude_engine_available() is True


def test_claude_available_from_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert structure.claude_engine_available() is True
