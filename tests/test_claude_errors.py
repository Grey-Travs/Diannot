"""Claude CLI process failures are surfaced (with stderr) + made retryable (no live AI)."""
import asyncio

import pytest

import diannot.structure as S


def test_claude_cli_error_carries_stderr():
    err = S._claude_cli_error(Exception("Command failed with exit code 1"),
                              ["", "  Claude AI usage limit reached  ", ""])
    assert isinstance(err, RuntimeError)  # retry loops only catch RuntimeError
    assert "exit code 1" in str(err) and "usage limit reached" in str(err)  # real reason visible


def test_run_text_converts_process_error_and_surfaces_stderr(monkeypatch):
    async def fake_collect(_msgs):
        raise RuntimeError("Command failed with exit code 1")  # stand-in for ProcessError (also Exception)

    def fake_query(prompt, options):
        options.stderr("anthropic: rate limit reached")  # the CLI's real reason -> the sink
        return iter([])

    monkeypatch.setattr(S, "_collect", fake_collect)
    monkeypatch.setattr(S, "query", fake_query)
    with pytest.raises(RuntimeError, match="rate limit reached"):
        asyncio.run(S._run_text("hi", "claude-opus-4-8", "sys"))


def test_claude_concurrency_is_low():
    # Opus rate-limits under many concurrent calls -> keep the structuring fan-out small.
    assert S._PARALLEL["claude"] <= 2
