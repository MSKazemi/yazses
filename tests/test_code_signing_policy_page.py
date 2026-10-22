"""The project's code signing policy carries what the SignPath Foundation requires of it.

SignPath's terms (signpath.org/terms, "Specify a code signing policy") make free signing
conditional on a policy that uses the exact term "Code signing policy" on the home page
and the download/release pages, names committers/reviewers and approvers, links a privacy
policy, requires multi-factor authentication, and carries a fixed credit line. Each piece
lives in a different file, so a rename or a reworded sentence in any one of them silently
fails an application nobody re-reads. These tests pin every piece to the file that holds it.

The credit line is written as what signed releases *will* carry: no release is signed
until SignPath approves, so stating it as present fact would be false. When signing goes
live, move the line out of the "Application pending" note and update this test with it.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
POLICY_URL = "https://mskazemi.com/yazses/code-signing.html#code-signing-policy"
CREDIT = (
    "Free code signing provided by SignPath.io, certificate by SignPath Foundation."
)


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _plain(markdown: str) -> str:
    """Drop link targets, emphasis and admonition indentation; collapse whitespace."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", markdown)
    text = text.replace("*", "")
    return " ".join(text.split())


def _policy_section() -> str:
    page = _read("docs/code-signing.md")
    match = re.search(r"^## Code signing policy\n(.*?)(?=^## )", page, re.S | re.M)
    assert match, 'docs/code-signing.md has no "## Code signing policy" section'
    return match.group(1)


def test_the_policy_section_carries_the_credit_line_verbatim():
    assert CREDIT in _plain(_policy_section())


def test_the_credit_links_point_where_signpath_says():
    section = _policy_section()
    assert "[SignPath.io](https://about.signpath.io)" in section
    assert "[SignPath Foundation](https://signpath.org)" in section


def test_the_policy_names_both_team_roles_and_requires_mfa():
    section = _plain(_policy_section())
    assert "Committers and reviewers" in section
    assert "Approvers" in section
    assert "multi-factor authentication" in section


def test_the_policy_links_the_privacy_statement():
    section = _policy_section()
    assert "(privacy-statement.md)" in section
    assert (ROOT / "docs/privacy-statement.md").is_file()


def test_the_credit_is_not_claimed_while_signing_is_pending():
    """Until SignPath approves, the credit sits inside the pending note, not as fact."""
    section = _policy_section()
    note = re.search(r'!!! note "Application pending"\n(.*?)(?=^\S)', section, re.S | re.M)
    assert note, "the pending note around the credit line is missing"
    assert CREDIT in _plain(note.group(1))
    outside = section.replace(note.group(0), "")
    assert "Free code signing provided by" not in outside


def test_the_readme_has_a_code_signing_policy_section_linking_the_policy():
    readme = _read("README.md")
    match = re.search(r"^## Code signing policy\n(.*?)(?=^## )", readme, re.S | re.M)
    assert match, 'README.md has no "## Code signing policy" section'
    assert POLICY_URL in match.group(1)


def test_every_website_page_footer_links_the_policy():
    """The site's copyright line is the footer of every page, the home page included."""
    mkdocs = _read("mkdocs.yml")
    copyright_block = re.search(r"^copyright: >-\n((?:  .*\n)+)", mkdocs, re.M)
    assert copyright_block, "mkdocs.yml has no folded copyright block"
    assert "Code signing policy" in copyright_block.group(1)
    assert POLICY_URL in copyright_block.group(1)
    home = _read("overrides/home.html")
    assert re.search(r"{% block footer %}.*?{{ super\(\) }}", home, re.S), (
        "the home page footer no longer renders the shared footer with the policy link"
    )


def test_the_download_and_release_pages_use_the_term():
    assert "[code signing policy](code-signing.md#code-signing-policy)" in _read(
        "docs/windows-install.md"
    )
    release = _read(".github/workflows/release.yml")
    assert f"[Code signing policy & verification]({POLICY_URL})" in release
