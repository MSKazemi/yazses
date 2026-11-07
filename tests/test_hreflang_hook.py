"""Tests for the hreflang hook.

The one rule that makes hreflang work is reciprocity: a declaration on one page
is ignored unless the partner points back. These tests pin that, plus the
absolute-URL and x-default requirements, against the pure helpers.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "hreflang", Path(__file__).resolve().parents[1] / "hooks" / "hreflang.py"
)
assert _SPEC and _SPEC.loader
hreflang = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(hreflang)

SITE = "https://mskazemi.com/yazses/"
HI = "hi/hindi-voice-typing.md"
EN = "use-cases/hindi-voice-typing.md"


def test_language_comes_from_top_level_directory() -> None:
    assert hreflang.page_language(HI) == "hi"
    assert hreflang.page_language(EN) == "en"


def test_section_directory_is_not_mistaken_for_a_language() -> None:
    # "use-cases" and "how-to" are sections, not languages.
    assert hreflang.page_language("how-to/change-hotkey.md") == "en"
    assert hreflang.page_language("index.md") == "en"


def test_a_bare_language_dir_name_is_not_a_translation() -> None:
    # "hi.md" at the root is a page called "hi", not the Hindi tree.
    assert hreflang.page_language("hi.md") == "en"


def test_alternates_are_absolute_and_use_html_extension() -> None:
    out = hreflang.build_alternates(HI, {"en": EN}, SITE)
    assert out["hi"] == "https://mskazemi.com/yazses/hi/hindi-voice-typing.html"
    assert out["en"] == "https://mskazemi.com/yazses/use-cases/hindi-voice-typing.html"


def test_page_includes_itself_and_x_default() -> None:
    out = hreflang.build_alternates(HI, {"en": EN}, SITE)
    assert set(out) == {"hi", "en", "x-default"}
    # x-default must resolve to the default-language page.
    assert out["x-default"] == out["en"]


def test_pair_is_reciprocal_from_a_single_declaration() -> None:
    """Both directions must produce the identical alternate set.

    Only the Hindi page declares `alternates`; the English page must still get
    the same tags, or search engines discard the pair.
    """
    group = {"hi": HI, "en": EN}
    from_hi = hreflang.build_alternates(HI, group, SITE)
    from_en = hreflang.build_alternates(EN, group, SITE)
    assert from_hi == from_en


def test_trailing_slash_in_site_url_does_not_double_up() -> None:
    assert "//yazses" not in hreflang.build_alternates(HI, {"en": EN}, SITE)["hi"]
    no_slash = hreflang.build_alternates(HI, {"en": EN}, SITE.rstrip("/"))
    assert no_slash == hreflang.build_alternates(HI, {"en": EN}, SITE)


class _FakeFile:
    def __init__(self, src_uri: str) -> None:
        self.src_uri = src_uri


class _FakePage:
    def __init__(self, src_uri: str, alternates: dict[str, str] | None = None) -> None:
        self.file = _FakeFile(src_uri)
        self.meta = {"alternates": alternates} if alternates else {}


class _FakeConfig:
    def __init__(self, pages: list[_FakePage]) -> None:
        self._hreflang_pages = pages


def test_many_translations_of_one_page_form_a_single_set() -> None:
    """A set of 3+ must not collapse into disjoint pairs.

    Every translation of the README declares nothing but `en: index.md`. Read as
    independent pairs, each one overwrites `index.md`'s entry, so the English
    page ends up naming only the translation processed last and the rest lose
    reciprocity — which is how 27 of 28 were silently discarded while the
    two-page tests above stayed green.
    """
    langs = ["de", "fr", "fa", "zh-TW"]
    pages = [_FakePage("index.md")] + [
        _FakePage(f"{lang}/index.md", {"en": "index.md"}) for lang in langs
    ]
    groups = hreflang._collect_pairs(_FakeConfig(pages))

    expected = {"en": "index.md", **{lang: f"{lang}/index.md" for lang in langs}}
    # The original must name every translation, not just the last one.
    assert groups["index.md"] == expected
    # And each translation must name its siblings, not only the original.
    for lang in langs:
        assert groups[f"{lang}/index.md"] == expected


def test_unrelated_translation_sets_are_not_merged() -> None:
    """Transitive merging must join only sets that actually share a page."""
    pages = [
        _FakePage("hi/index.md", {"en": "index.md"}),
        _FakePage(HI, {"en": EN}),
    ]
    groups = hreflang._collect_pairs(_FakeConfig(pages))
    assert groups["index.md"] == {"en": "index.md", "hi": "hi/index.md"}
    assert groups[EN] == {"en": EN, "hi": HI}


def test_translated_page_declares_its_own_html_lang() -> None:
    page = '<!doctype html><html lang="en" class="no-js"><head></head></html>'
    assert '<html lang="de" ' in hreflang.with_html_lang(page, "de/index.md")
    assert '<html lang="pt-BR" ' in hreflang.with_html_lang(page, "pt-BR/index.md")
    assert '<html lang="hi" ' in hreflang.with_html_lang(page, HI)

    minified = "<!DOCTYPE html><html lang=en class=no-js><head>"
    assert hreflang.with_html_lang(minified, "ja/index.md") == (
        '<!DOCTYPE html><html lang="ja" class=no-js><head>'
    )


def test_default_language_page_keeps_its_html_lang_untouched() -> None:
    page = '<!doctype html><html lang="en" class="no-js"><head></head></html>'
    assert hreflang.with_html_lang(page, "use-cases/voice-coding.md") == page
    assert hreflang.with_html_lang(page, "index.md") == page


def test_html_lang_is_rewritten_once_and_keeps_other_attributes() -> None:
    page = '<html lang="en" class="no-js"><body><html lang="en"></body>'
    out = hreflang.with_html_lang(page, "fr/index.md")
    assert out.startswith('<html lang="fr" class="no-js">')
    assert out.count('lang="fr"') == 1


def test_html_lang_is_rewritten_after_minification_removed_the_quotes() -> None:
    page = "<!DOCTYPE html><html lang=en class=no-js><head></head>"
    out = hreflang.with_html_lang(page, "ja/index.md")
    assert out.startswith('<!DOCTYPE html><html lang="ja" class=no-js>')
