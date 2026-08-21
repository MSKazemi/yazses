"""`CITATION.cff` must not drift from `pyproject.toml`.

It did: the file sat at `version: 2.14.0` / `date-released: 2026-08-07` while PyPI and
Zenodo were both on 2.17.0, and it carried no DOI at all even though the GitHub-Zenodo
integration had already minted one. Nothing failed, because nothing checked — a citation
file is read by humans and by Zenodo, never by the test suite.

The DOI assertion is the one that matters most. Zenodo mints two identifiers per project:
a *concept* DOI that always resolves to the latest release, and a *version* DOI pinned to
one release. Citing the version DOI freezes every future citation to an old archive, and
the mistake is invisible — both resolve, so nothing looks broken.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CITATION = REPO_ROOT / "CITATION.cff"
PYPROJECT = REPO_ROOT / "pyproject.toml"

#: Zenodo *concept* DOI — resolves to the latest release. See the module docstring.
CONCEPT_DOI = "10.5281/zenodo.21856271"


def _citation_text() -> str:
    return CITATION.read_text(encoding="utf-8")


def _citation_statements() -> str:
    """CITATION.cff with YAML comments stripped.

    The file deliberately *names* the version-pinned DOI in a comment, to explain why it
    must not be used. A comment cannot change how Zenodo or any citation tool reads the
    file, so identifier assertions look at statements only.
    """
    lines = []
    for line in _citation_text().splitlines():
        stripped = re.sub(r"(^|\s)#.*$", "", line)
        lines.append(stripped)
    return "\n".join(lines)


def _project_version() -> str:
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def _scalar(field: str) -> str:
    """Read a top-level `field: value` from CITATION.cff without a YAML dependency.

    Anchored at the start of a line so nested keys of the same name (notably the ones
    under `preferred-citation:`) cannot satisfy the match.
    """
    match = re.search(
        rf"^{re.escape(field)}:\s*\"?([^\"\n]+)\"?\s*$", _citation_statements(), re.M
    )
    assert match, f"CITATION.cff has no top-level `{field}:` field"
    return match.group(1).strip()


def test_citation_version_matches_pyproject() -> None:
    assert _scalar("version") == _project_version(), (
        "CITATION.cff `version` is stale. Bump it (and `date-released`) whenever "
        "pyproject.toml's version changes."
    )


def test_citation_declares_the_concept_doi() -> None:
    assert _scalar("doi") == CONCEPT_DOI


def test_citation_does_not_use_a_version_pinned_doi() -> None:
    """A per-version Zenodo DOI here silently freezes the citation to one release."""
    dois = set(re.findall(r"10\.5281/zenodo\.\d+", _citation_statements()))
    assert dois == {CONCEPT_DOI}, (
        f"CITATION.cff references {sorted(dois - {CONCEPT_DOI})}, which is a "
        "version-pinned Zenodo DOI. Use the concept DOI so citations follow releases."
    )


def test_readme_badge_uses_the_same_concept_doi() -> None:
    """No shipped front page may name a DOI that disagrees with the citation file.

    The list was once hard-coded to `README.md` + `README.hi.md`, and two more
    translations arrived afterwards and were never checked; globbing fixed that. It
    then broke the other way: the glob was `README.*.md` at the repo root, and when
    the translations moved to `docs/<locale>/index.md` it matched nothing and the
    test passed by checking one file. So the search is asserted to be non-empty and
    to actually reach the translations.

    Translations no longer carry the badge block — `material/privacy` downloads
    every external asset at build time and zenodo.org answers that downloader with
    403, so one DOI badge on one translated page failed the whole docs build. This
    checks any DOI that *is* present rather than requiring one, which is what keeps
    it correct whichever way that decision goes later.
    """
    translations = sorted(REPO_ROOT.glob("docs/*/index.md"))
    assert len(translations) > 20, (
        f"expected the translations at docs/<locale>/index.md, found {len(translations)} "
        "candidates — if they moved again, repoint this glob rather than letting it "
        "pass by matching nothing"
    )
    for path in [REPO_ROOT / "README.md", *translations]:
        text = path.read_text(encoding="utf-8")
        dois = set(re.findall(r"10\.5281/zenodo\.\d+", text))
        assert dois <= {CONCEPT_DOI}, (
            f"{path.relative_to(REPO_ROOT)} names a DOI that disagrees with "
            f"CITATION.cff: {sorted(dois - {CONCEPT_DOI})}"
        )
    readme_dois = set(
        re.findall(r"10\.5281/zenodo\.\d+", (REPO_ROOT / "README.md").read_text(encoding="utf-8"))
    )
    assert readme_dois == {CONCEPT_DOI}, "README.md must carry the concept-DOI badge"


def test_citation_release_date_is_iso() -> None:
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", _scalar("date-released"))
