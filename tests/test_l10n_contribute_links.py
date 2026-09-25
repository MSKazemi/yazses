"""The draft pages' one outward link, and the generator that owns it (#349, #359).

Every `docs/<locale>/index.md` draft carries one sentence whose entire job is to
recruit a native reviewer, and one link inside it. Until #359 that link was the
locale's `Translate the README into <language>` issue, closed the day the
translation landed — so the one line on the page that asks for help sent every
reader who clicked it to finished, locked work.

#359 corrected the **rendered pages**. These pages are generated output, so the
correction survived only until the next `gen-readme-translation.py --all`, which
reads `scripts/translations.py` and would have written the closed issues straight
back. The same run would have replaced the reviewed Tamil page — a native
speaker's work — with the machine draft it had replaced, banner included.

These tests pin the generator against the shipped tree, which is the only check
that can see either. They are deliberately offline: no issue state is fetched, so
what they enforce is "the source of truth and the shipped file agree", not "the
issue is open". The open/closed judgement is a human one, made when a review lands.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"


def _load_generator():
    sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "gen_readme_translation", SCRIPTS / "gen-readme-translation.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["gen_readme_translation"] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()

#: Issues whose title starts `Translate the README into …`. Every one was closed the
#: day its translation landed, and each is what the matching page used to link.
CLOSED_TRANSLATE_ISSUES = {
    174, 175, 176, 177, 179, 190, 191, 192, 193, 194, 195, 197,
    199, 200, 201, 202, 204, 205, 230, 231, 232,
}

BANNER_LINK = re.compile(
    r"welcome first contribution — see \[issue #(\d+)\]"
    r"\(https://github\.com/MSKazemi/yazses/issues/(\d+)\)"
)


def _draft_locales() -> list[str]:
    return [code for code in sorted(gen.LOCALES) if not gen.is_reviewed(code)]


def test_there_are_draft_locales_to_check():
    """Guard the guard: every assertion below iterates, so an empty list passes."""
    assert _draft_locales(), "no draft locales -- the tests below would prove nothing"


@pytest.mark.parametrize("code", sorted(gen.LOCALES))
def test_no_locale_points_at_a_closed_translate_issue(code):
    """The #349 defect itself, pinned in the source of truth rather than the output."""
    issue = gen.LOCALES[code]["review_issue"]
    assert issue not in CLOSED_TRANSLATE_ISSUES, (
        f"{code} recruits reviewers to #{issue}, a closed "
        f"'Translate the README into …' issue. It wants the open "
        f"'Review the <language> translation' one."
    )


@pytest.mark.parametrize("code", _draft_locales())
def test_the_shipped_page_links_what_the_table_says(code):
    """A fix applied to the page and not to the table is reverted by the next run."""
    text = gen.translation_path(code).read_text(encoding="utf-8")
    match = BANNER_LINK.search(text)
    assert match, f"docs/{code}/index.md has no draft recruiting link"
    label, href = int(match.group(1)), int(match.group(2))
    assert label == href, f"docs/{code}/index.md says #{label} but links to #{href}"
    assert label == gen.LOCALES[code]["review_issue"], (
        f"docs/{code}/index.md links #{label}; scripts/translations.py says "
        f"#{gen.LOCALES[code]['review_issue']}. The generator would overwrite the page."
    )


def test_review_issues_are_one_per_locale():
    """A transposition sends Arabic readers to the Bengali issue and looks fine."""
    issues = [spec["review_issue"] for spec in gen.LOCALES.values()]
    duplicates = {n for n in issues if issues.count(n) > 1}
    assert not duplicates, f"two locales share a review issue: {sorted(duplicates)}"


def test_a_reviewed_page_is_not_regenerated():
    """A native review must survive the next regeneration of its neighbours."""
    reviewed = [code for code in gen.LOCALES if gen.is_reviewed(code)]
    if not reviewed:
        pytest.skip("no reviewed locale in the generated table yet")
    for code in reviewed:
        page = gen.translation_path(code).read_text(encoding="utf-8")
        assert "status=draft" not in page, f"docs/{code}/index.md is marked reviewed"
        assert page != gen.render(code, gen.LOCALES[code], gen.TABLE_SOURCE_SHA), (
            f"docs/{code}/index.md is byte-identical to the machine draft -- "
            f"the review it is supposed to hold is not there"
        )


def test_is_reviewed_does_not_protect_an_unreadable_page(tmp_path, monkeypatch):
    """A guard that cannot parse its input must not report protection."""
    monkeypatch.setattr(gen, "ROOT", tmp_path)
    (tmp_path / "docs" / "xx").mkdir(parents=True)
    page = tmp_path / "docs" / "xx" / "index.md"

    page.write_text("no metadata comment here at all\n", encoding="utf-8")
    assert gen.is_reviewed("xx") is False

    page.write_text("<!-- yazses-l10n: locale=xx; status=draft -->\n", encoding="utf-8")
    assert gen.is_reviewed("xx") is False

    page.write_text("<!-- yazses-l10n: locale=xx; status=active -->\n", encoding="utf-8")
    assert gen.is_reviewed("xx") is True


def test_the_generator_is_in_sync_with_the_shipped_tree():
    """`--check` is the whole contract: edit the table, re-run, commit the result."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "gen-readme-translation.py"), "--all", "--check"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        "scripts/gen-readme-translation.py --all --check is red, so a regeneration "
        "would change the shipped pages:\n" + result.stdout + result.stderr
    )


def test_the_localized_call_carries_no_second_copy_of_the_issue_number():
    """The number lives in `review_issue`; the sentence interpolates it."""
    for code, spec in gen.LOCALES.items():
        call = spec["strings"].get("draft_call", "")
        if not call:
            continue
        assert "{issue" in call, f"{code} draft_call hard-codes its link"
        assert not re.search(r"/issues/\d+", call), (
            f"{code} draft_call pins an issue number that `review_issue` already holds"
        )
