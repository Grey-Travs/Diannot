"""Phase-1 gate: study mode is shelved behind ``config.STUDY_ENABLED``.

Two things are locked in here, both deterministic + offline (no NiceGUI server, no AI):
1. The flag defaults off, and the "Review" nav entry is filtered out while it's off.
2. Importing the Studio app does NOT pull the study / SRS / quiz / Anki modules (or genanki)
   onto the startup path — they must stay lazy so a disabled feature costs nothing at launch.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from diannot.config import STUDY_ENABLED


def test_study_disabled_by_default():
    assert STUDY_ENABLED is False


def test_review_nav_gated_while_study_off():
    pytest.importorskip("nicegui")
    from diannot.studio import layout

    # The study nav route is declared so re-enabling is a one-line flip (NAV keeps "Review"),
    # but "/review" is marked as a study route the drawer skips while STUDY_ENABLED is False.
    assert "/review" in layout._STUDY_NAV_ROUTES
    assert any(route == "/review" for _label, route, _icon in layout.NAV)


def test_studio_startup_does_not_import_study_modules():
    """A fresh interpreter that imports the Studio app must not have loaded any study code."""
    pytest.importorskip("nicegui")
    code = textwrap.dedent(
        """
        import sys
        import diannot.studio.app  # registers routes; must stay clear of study code

        watched = (
            "genanki",
            "diannot.srs",
            "diannot.cards",
            "diannot.quiz",
            "diannot.glossary",
            "diannot.anki",
            "diannot.studio.pages.study",
            "diannot.studio.pages.review_all",
        )
        print(",".join(m for m in watched if m in sys.modules))
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=180
    )
    assert result.returncode == 0, result.stderr
    leaked = result.stdout.strip()
    assert not leaked, f"study modules leaked onto the studio startup path: {leaked}"
