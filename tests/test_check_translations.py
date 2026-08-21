"""Tests for the README translation drift checker (#166).

The checker's whole value is that it fails on real drift and stays quiet
otherwise, so both directions are pinned here. Nothing writes to a translation:
the checker is read-only by design, and these tests assert that too.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("check_translations",
                                                  ROOT / "scripts/check-translations.py")
    module = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations via sys.modules, so register before exec.
    sys.modules["check_translations"] = module
    spec.loader.exec_module(module)
    return module


ct = _load()

# The English source: it lives at the repo root and names the other locales, which
# live under `docs/<locale>/`, but not itself.
EN = """**Read this in other languages:** **English** · [Русский](docs/ru/index.md)

Install it:

```bash
yazses doctor
yazses start
```

See https://github.com/MSKazemi/yazses for more.
"""

# A translation: same commands, translated prose, and a link *back* to English.
# Tests that mutate a translation start from this, not from EN.
#
# The switcher opens in English in every locale — it is navigation for a reader who
# cannot yet read this page — and the link home is absolute, because a translation
# at `docs/ru/index.md` renders on both GitHub and the docs site and only one of
# those can reach a repo-root file relatively.
TR = f"""**Read this in other languages:** [English](../index.md) · Русский

Перевод [README.md]({ct.ENGLISH_README}).

```bash
yazses doctor
yazses start
```

Смотрите https://github.com/MSKazemi/yazses для подробностей.
"""

#: A path that really exists, so the switcher-resolution check has a real tree to
#: resolve against — `../index.md` and `../de/index.md` are files, not fixtures.
RU = ROOT / "docs" / "ru" / "index.md"


def _locale(**kw):
    defaults = dict(path=RU, locale="ru", source_sha="abc1234",
                    scope="full", status="active")
    return ct.Locale(**{**defaults, **kw})


def _check(text, locale=None, known=(RU,)):
    return ct.check_locale(locale or _locale(), text, EN, known_locales=set(known))


# ---- metadata parsing ------------------------------------------------------


def test_metadata_comment_is_parsed():
    meta = ct.parse_metadata(
        "<!-- yazses-l10n: locale=ru; source_sha=abc1234; scope=full; status=active -->"
    )
    assert meta == {"locale": "ru", "source_sha": "abc1234",
                    "scope": "full", "status": "active"}


def test_missing_metadata_is_an_empty_dict_not_a_crash():
    assert ct.parse_metadata("# just a readme") == {}


def test_metadata_tolerates_spacing_and_case():
    meta = ct.parse_metadata("<!--   YAZSES-L10N:  locale = ru ;  status = draft  -->")
    assert meta["locale"] == "ru" and meta["status"] == "draft"


# ---- command preservation: the check that catches real damage --------------


def test_translated_command_is_reported():
    """`yazses диагностика` is not a command; shipping it misleads a reader."""
    text = TR.replace("yazses doctor", "yazses диагностика")
    problems = _check(text).problems
    assert any("диагностика" in p for p in problems)


def test_faithful_translation_of_prose_only_is_clean():
    assert _check(TR).ok


def test_command_named_in_prose_is_not_flagged():
    """Prose inflects; only fenced blocks are checked, to avoid unactionable noise."""
    text = TR + "\n\nThe `yazses doctora` word appears in a sentence here.\n"
    assert _check(text).ok


def test_extra_command_invented_by_a_translation_is_reported():
    text = TR.replace("yazses start", "yazses start\nyazses nonexistent-command")
    assert any("nonexistent-command" in p for p in _check(text).problems)


# ---- structural checks -----------------------------------------------------


def test_missing_link_back_to_english_is_reported():
    text = TR.replace(ct.ENGLISH_README, "the English README")
    assert any("no link back" in p for p in _check(text).problems)


def test_dead_language_switcher_link_is_reported():
    """A switcher pointing at a language directory that does not exist."""
    text = TR.replace("[English](../index.md)", "[English](../gone/index.md)")
    assert any("does not exist" in p for p in _check(text).problems)


def test_missing_metadata_block_is_reported():
    problems = _check(TR, locale=_locale(locale="", source_sha="")).problems
    assert any("yazses-l10n" in p for p in problems)


def test_unknown_status_is_reported():
    assert any("status" in p for p in _check(TR, locale=_locale(status="nearly")).problems)


def test_draft_without_a_visible_banner_is_reported():
    """A reader must be told the text is unreviewed, not just the metadata."""
    problems = _check(TR, locale=_locale(status="draft")).problems
    assert any("review banner" in p for p in problems)


def test_draft_with_a_visible_banner_is_accepted():
    text = TR.replace("```bash", "> Это ЧЕРНОВИК (draft), ещё не проверен.\n\n```bash")
    assert _check(text, locale=_locale(status="draft")).ok


# ---- notes vs problems -----------------------------------------------------


def test_locale_specific_project_url_is_a_note_not_a_failure():
    """A locale landing page legitimately exists only in that translation."""
    text = TR + "\nhttps://mskazemi.com/yazses/ru/russian-voice-typing.html\n"
    report = _check(text)
    assert report.ok, "a locale-specific page must not fail the build"
    assert any("russian-voice-typing" in n for n in report.notes)


def test_third_party_url_is_ignored_entirely():
    text = TR + "\nhttps://example.com/some-blog-post\n"
    report = _check(text)
    assert report.ok and not any("example.com" in n for n in report.notes)


# ---- the repository's own translations must pass ---------------------------


def test_shipped_translations_have_no_drift():
    """The real files, checked the way CI checks them."""
    source = (ROOT / "README.md").read_text(encoding="utf-8")
    locales = ct.load_locales(ROOT)
    assert locales, "no docs/<locale>/index.md found -- test is looking at nothing"
    known = {loc.path for loc in locales}
    problems = []
    for loc in locales:
        problems += ct.check_locale(
            loc, loc.path.read_text(encoding="utf-8"), source, known_locales=known
        ).problems
    assert not problems, "shipped translations have drift:\n  " + "\n  ".join(problems)


def test_every_shipped_translation_declares_its_metadata():
    for loc in ct.load_locales(ROOT):
        assert loc.locale, f"{loc.name} has no locale in its metadata"
        assert loc.source_sha, f"{loc.name} has no source_sha"
        assert loc.status in ct.VALID_STATUS, f"{loc.name} status={loc.status!r}"


def test_status_page_lists_every_shipped_translation():
    """The matrix going stale is the failure mode a status page has."""
    status = (ROOT / "docs/localization/STATUS.md").read_text(encoding="utf-8")
    for loc in ct.load_locales(ROOT):
        assert loc.name in status, f"{loc.name} is missing from docs/localization/STATUS.md"


@pytest.mark.parametrize(
    "name", ["docs/hi/index.md", "docs/zh-CN/index.md", "docs/ru/index.md"]
)
def test_checker_never_modifies_a_translation(name, tmp_path):
    before = (ROOT / name).read_bytes()
    source = (ROOT / "README.md").read_text(encoding="utf-8")
    locales = ct.load_locales(ROOT)
    loc = next(loc for loc in locales if loc.name == name)
    ct.check_locale(loc, loc.path.read_text(encoding="utf-8"), source,
                    known_locales={x.path for x in locales})
    assert (ROOT / name).read_bytes() == before, "the checker must be read-only"
