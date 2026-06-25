"""End-to-end CLI happy-path via Typer's CliRunner — guards the 13-command surface against regressions.

Deterministic and offline: `render` turns an existing note into themed HTML with no AI call.
"""
from pathlib import Path

from typer.testing import CliRunner

from diannot.cli import app

runner = CliRunner()
_FIXTURE = Path(__file__).parent / "fixtures" / "notes" / "legacy_kitchen_sink.note.json"


def test_render_writes_themed_html(tmp_path, monkeypatch):
    # render writes to ./output relative to cwd — run in tmp so we don't litter the repo.
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["render", str(_FIXTURE.resolve()), "--theme", "circulatory"])
    assert result.exit_code == 0, result.output

    htmls = list((tmp_path / "output").glob("*.html"))
    assert htmls, f"render produced no HTML. CLI output:\n{result.output}"
    html = htmls[0].read_text(encoding="utf-8")
    assert "HEMOSTASIS" in html          # the fixture's banner text made it into the render
    assert "<style" in html.lower()      # self-contained: the theme CSS is inlined


def test_render_rejects_missing_note(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["render", str(tmp_path / "nope.note.json")])
    assert result.exit_code != 0  # Typer's exists=True guard fails cleanly, not with a traceback
