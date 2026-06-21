"""The Claude engine is only offered when it can actually run (not in a packaged build)."""
import sys

import diannot.structure as structure


def test_claude_unavailable_in_packaged_build(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert structure.claude_engine_available() is False


def test_claude_available_from_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert structure.claude_engine_available() is True
