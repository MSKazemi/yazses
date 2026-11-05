"""Two statements the code contradicted, found by checking docs against behaviour.

* Eight RECOMMENDED cards (``checkdigit``, ``focusprofile``, ``timeline``, ``compute``,
  ``corrdict``, ``verbatim``, ``spelling``, ``cmdsafety``) said "Off by default". Their config
  keys do default to off, but first-run setup writes the whole recommended tier on
  (``default_enabled_slugs``), so a fresh install has them running.
* ``yazses jump --help`` named "Neovim/VS Code" while the command itself refuses VS Code, whose
  bridge supplies dictation context only and has no cursor motion.
"""

from __future__ import annotations

import re
from pathlib import Path

from yazses.config import Config
from yazses.system import features as F

ROOT = Path(__file__).resolve().parents[1]
#: The sentence every first-run-only card carries (see the registry descriptions).
FIRST_RUN_PHRASE = "On after first-run setup"


def _on_only_after_first_run() -> set[str]:
    """Slugs whose config key defaults to off but which first-run setup writes on.

    Derived from the code, never listed by hand: seeded by ``default_enabled_slugs`` AND
    off in a bare ``Config()``. (The DEFAULT_ON tier is on in the dataclass already, so
    "after first-run setup" would be false for it.)
    """
    seeded = set(F.default_enabled_slugs())
    return {
        f.slug for f in F.feature_status(Config()) if f.slug in seeded and not f.on
    }


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


def test_the_first_run_set_is_the_recommended_tier() -> None:
    """The count the docs state is the size of this set; pin its relation to the tier."""
    rec = {f.slug for f in F.feature_status(Config()) if f.tier == F.RECOMMENDED}
    assert _on_only_after_first_run() == rec


def test_every_first_run_card_says_so_and_no_other_card_does() -> None:
    first_run = _on_only_after_first_run()
    assert first_run  # an empty set would make this test vacuous
    for feature in F.feature_status(Config()):
        says = FIRST_RUN_PHRASE in (feature.why or "")
        assert says == (feature.slug in first_run), feature.slug


def test_features_page_counts_the_first_run_cards_the_code_seeds() -> None:
    """`docs/features.md` is generated, so this catches a stale checkout and a registry
    row that lost (or gained) the sentence: card count == size of the seeded set."""
    page = (ROOT / "docs" / "features.md").read_text(encoding="utf-8")
    assert page.count(FIRST_RUN_PHRASE) == len(_on_only_after_first_run())
    recommended_cards = len(re.findall(r"\*\*Tier:\*\* recommended\b(?! \()", page))
    assert recommended_cards == len(_on_only_after_first_run())


def test_v2_page_names_exactly_the_seeded_features_it_lists() -> None:
    """The v2 page's "switches on ..." sentence must name every seeded feature that has a
    row on that page, nothing first-run setup does not seed, and state the true total."""
    text = (ROOT / "docs" / "v2-features.md").read_text(encoding="utf-8")
    para = text.split("**Every v2 feature is off", 1)[1].split("\n\n", 1)[0]
    listed, _, rest = para.partition("(")  # the list, then a parenthetical about the rest
    named = set(re.findall(r"`([a-z0-9-]+)`", listed.split("`yazses features", 1)[0]))
    first_run = _on_only_after_first_run()
    rows = {
        m.group(1)
        for m in re.finditer(r"^\|[^|]*\|\s*`([a-z0-9-]+)`\s*\|", text, re.MULTILINE)
    }
    assert named == first_run & rows
    off_page = first_run - rows
    assert {s for s in re.findall(r"`([a-z0-9-]+)`", rest.split(")")[0])} == off_page
    words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
             8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve"}
    assert f"{words[len(first_run)]} in all" in para
