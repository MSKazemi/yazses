"""The hands-free setup guide stays true to the code it describes (#410: "setup docs require no
undocumented terminal step", "safe recovery hierarchy documented").

A guide that names the roles, the stop paths and the recovery ladder by hand rots the day one of
them changes, so each is derived from the module that owns it and looked up in the page.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

from yazses.config import HandsfreeConfig
from yazses.handsfree.preset import CHORDS_STOP
from yazses.handsfree.recovery import Route

ROOT = Path(__file__).resolve().parent.parent
GUIDE = ROOT / "docs" / "how-to" / "hands-free-setup.md"


def _text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def test_the_guide_is_listed_in_the_how_to_index_and_the_site_navigation() -> None:
    assert "(hands-free-setup.md)" in (ROOT / "docs" / "how-to" / "index.md").read_text(encoding="utf-8")
    assert "how-to/hands-free-setup.md" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def test_every_role_the_preset_can_compose_is_named_in_the_guide() -> None:
    roles = [f.name for f in dataclasses.fields(HandsfreeConfig) if f.name != "enabled"]
    assert len(roles) == 6, roles
    text = _text()
    missing = [role for role in roles if f"`{role}`" not in text]
    assert missing == []


def test_the_guide_names_the_commands_that_turn_the_preset_on_and_off_and_that_stop_it() -> None:
    text = _text()
    for command in (
        "yazses handsfree explain", "yazses handsfree enable --force", "yazses restart",
        "yazses handsfree resume", "yazses handsfree pause", "yazses handsfree disable", "yazses doctor",
        "yazses features enable overlay",
    ):
        assert f"`{command}`" in text or f"\n   {command}\n" in text or f"\n{command}\n" in text, command


def test_the_chord_that_stops_is_the_one_the_preset_binds() -> None:
    assert CHORDS_STOP.replace("+", " + ") in _text().replace("brow-raise", "brow_raise")


def test_the_guide_says_the_recovery_ladder_has_the_rungs_the_code_has() -> None:
    text = _text().lower()
    ladder = {
        Route.PREFERRED: "preferred",
        Route.ALTERNATE: "alternate",
        Route.FOCUSED: "focused",
        Route.NONE: "cannot act",
    }
    assert set(ladder) == set(Route), "a new rung needs a sentence in the guide"
    for rung, word in ladder.items():
        assert word in text, rung
    assert re.search(r"destructive action only recovers onto a target \*\*you\*\* chose", _text())


def test_the_guide_keeps_the_provisional_and_what_is_not_composed_caveats() -> None:
    text = _text()
    assert "provisional" in text.lower() and "Voice Mouse Grid" in text
    assert "not** turn the overlay on" in text, "dwell-click's overlay prerequisite must stay stated"
