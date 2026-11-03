"""Two statements the code contradicted, found by checking docs against behaviour.

* Eight RECOMMENDED cards (``checkdigit``, ``focusprofile``, ``timeline``, ``compute``,
  ``corrdict``, ``verbatim``, ``spelling``, ``cmdsafety``) said "Off by default". Their config
  keys do default to off, but first-run setup writes the whole recommended tier on
  (``default_enabled_slugs``), so a fresh install has them running.
* ``yazses jump --help`` named "Neovim/VS Code" while the command itself refuses VS Code, whose
  bridge supplies dictation context only and has no cursor motion.
"""

from __future__ import annotations

from yazses.config import Config
from yazses.system import features as F


def test_no_card_the_first_run_turns_on_says_it_is_off_by_default() -> None:
    seeded = set(F.default_enabled_slugs())
    assert "focusprofile" in seeded  # the case that was reported
    for feature in F.feature_status(Config()):
        if feature.slug in seeded:
            assert "off by default" not in (feature.why or "").lower(), feature.slug


def test_a_card_that_is_not_seeded_still_says_off_by_default() -> None:
    cards = {f.slug: f for f in F.feature_status(Config())}
    assert "off by default" in cards["voicetimer"].why.lower()


def test_jump_help_does_not_promise_vs_code() -> None:
    import inspect

    import yazses.cli as cli

    doc = " ".join((inspect.getdoc(cli.jump) or "").split())
    assert "Neovim/VS Code" not in doc
    assert "VS Code cannot be used for jumping" in doc
