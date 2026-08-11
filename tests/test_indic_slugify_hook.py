"""Tests for the Indic-safe heading slugifier.

Two properties have to hold at once, and they pull in opposite directions:

* the anchors must keep GitHub's spacing rule, because `docs/features.md` is
  generated with GitHub-style anchors and is read both on the docs site and on
  GitHub; and
* combining marks must survive, because in an abugida they *are* the vowels —
  dropping them turns a heading into a consonant skeleton.

The regression that prompted this: `ईमानदार सीमाएँ` slugged to `ईमनदर-समए`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "indic_slugify", Path(__file__).resolve().parents[1] / "hooks" / "indic_slugify.py"
)
assert _SPEC and _SPEC.loader
indic_slugify = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(indic_slugify)

slug = indic_slugify.slugify_unicode


def test_devanagari_vowel_signs_survive() -> None:
    # The exact heading whose cross-link aborted the strict build.
    assert slug("ईमानदार सीमाएँ", "-") == "ईमानदार-सीमाएँ"


def test_dropped_punctuation_still_yields_github_double_dash() -> None:
    # `Accuracy & correction` -> `accuracy--correction`: spaces are never
    # collapsed, so the site and GitHub agree on the anchor.
    assert slug("Accuracy & correction", "-") == "accuracy--correction"


def test_ascii_headings_are_lowercased_and_hyphenated() -> None:
    assert slug("Quick Start", "-") == "quick-start"


def test_mixed_script_heading_keeps_both_halves() -> None:
    assert slug("कौन-सा model size चुनें", "-") == "कौन-सा-model-size-चुनें"


def test_marks_in_other_scripts_survive_too() -> None:
    # Script-agnostic by construction: Arabic harakat and Thai vowel signs are
    # the same Unicode categories as Devanagari matras.
    assert slug("مُحَمَّد", "-") == "مُحَمَّد"
    assert slug("เสียง", "-") == "เสียง"


def test_html_in_a_heading_does_not_leak_into_the_anchor() -> None:
    assert slug("A <em>bold</em> claim", "-") == "a-bold-claim"


def test_hook_overrides_the_toc_slugifier() -> None:
    config: dict = {"mdx_configs": {"toc": {"permalink": True}}}
    indic_slugify.on_config(config)
    assert config["mdx_configs"]["toc"]["slugify"] is slug
    # The rest of the toc config must be left alone.
    assert config["mdx_configs"]["toc"]["permalink"] is True


def test_hook_works_when_toc_has_no_existing_config() -> None:
    config: dict = {"mdx_configs": {}}
    indic_slugify.on_config(config)
    assert config["mdx_configs"]["toc"]["slugify"] is slug
