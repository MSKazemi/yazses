"""Every link YazSes shows a user must go somewhere real.

A URL in a shipped string is compiled into the `.exe`, the `.dmg`, the snap and the
`.deb`. If it 404s, the person who finds out is the user, alone, at the moment they
were already stuck — and nothing in CI would ever say so.

This session produced three instances of one shape in three days: a diagnosis module
linking **three how-to pages that have never existed**, a bug-report bundle reading
`yazses.log` where the file is `daemon.log`, and a settings tooltip naming
`yazses models` where the command is `yazses model list`. Each was caught by hand, and
each had a guard written for it afterwards — one per module. This is the general one.

Two rules, and the second is a near-miss rather than a past defect: the site sets
`use_directory_urls: false`, so a page is `<name>.html` and **never** `<name>/`.
Writing the directory form ships a 404 into a binary, and it was nearly done once.

Docstrings are excluded deliberately. `platform/bsd/__init__.py` ends its module
docstring with "report results on …/issues." — a sentence-final period that would read
as part of the URL. That text is developer-facing and never reaches a user, so holding
it to a user-visible standard would be noise, and a guard that produces noise gets
deleted.

## The other half: links the program never prints

The rules above were applied only to Python strings, and a link does not have to be
printed by the program to be clicked. `packaging/flatpak/…metainfo.xml` **is** the
Flathub listing — GNOME Software and KDE Discover render it — and its
`<url type="help">` is the Help button. It was written in the directory form and would
have 404'd for every person who pressed it. `test_flatpak_metainfo.py` reads that file
and checks its `<url>` fields, but only that none is a placeholder; it verifies that
every *screenshot* resolves to a real file while saying in its own docstring that "a
listing whose images 404 is worse than one with none".

So the same two rules now run over every tracked file, not just `src/`: the snap
listing, `pyproject.toml` (which is the PyPI sidebar), `CITATION.cff`, the AppStream
metainfo, the install scripts and the docs themselves. `tests/` is excluded because a
link checker's own fixtures are deliberately malformed.
"""

from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

import pytest

from tests.gitprobe import require_git

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "yazses"
DOCS = ROOT / "docs"

SITE = "https://mskazemi.com/yazses/"

_DOCS_URL = re.compile(re.escape(SITE) + r"[A-Za-z0-9._/-]*")
_GITHUB_URL = re.compile(r"https://github\.com/([A-Za-z0-9._-]+)/([A-Za-z0-9._-]+)")


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """`id()` of every string node that is a docstring — dev-facing, not shown."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = getattr(node, "body", None)
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                out.add(id(body[0].value))
    return out


def _module_constants(tree: ast.AST) -> dict[str, str]:
    """Module-level ``NAME = "literal"`` bindings, so f-strings can be resolved."""
    out: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        targets = []
        if isinstance(node, ast.Assign):
            targets = [t for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target]
        value = getattr(node, "value", None)
        if targets and isinstance(value, ast.Constant) and isinstance(value.value, str):
            for target in targets:
                out[target.id] = value.value
    return out


def _joined(node: ast.JoinedStr, consts: dict[str, str]) -> str:
    """Reconstruct an f-string, substituting module constants where it can.

    Without this the whole guard was vacuous for the module it was written to
    generalise. `system/diagnosis.py` writes every link as ``f"{_DOCS}/page.html"``,
    which is an `ast.JoinedStr` — **not** an `ast.Constant` — so a scan of string
    constants saw only the fragment ``"/page.html"``, which does not contain the site
    prefix and therefore matched nothing. Sabotaging that file with a link to a page
    that has never existed produced no failure at all.
    """
    parts: list[str] = []
    for piece in node.values:
        if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
            parts.append(piece.value)
        elif isinstance(piece, ast.FormattedValue) and isinstance(piece.value, ast.Name):
            parts.append(consts.get(piece.value.id, "{}"))
        else:
            parts.append("{}")
    return "".join(parts)


def _user_visible_strings() -> list[tuple[Path, str]]:
    """Every string the package can show, that is not a docstring.

    Includes f-strings, resolved against module-level constants — see `_joined`.
    """
    found: list[tuple[Path, str]] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - fails loudly elsewhere
            continue
        skip = _docstring_nodes(tree)
        consts = _module_constants(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
            ):
                found.append((path, node.value))
            elif isinstance(node, ast.JoinedStr):
                found.append((path, _joined(node, consts)))
    return found


@pytest.fixture(scope="module")
def strings() -> list[tuple[Path, str]]:
    return _user_visible_strings()


def test_the_scan_finds_the_strings_it_is_supposed_to(strings) -> None:
    """A guard that scans nothing passes on everything.

    This repo has been bitten by a vacuous guard three times in one day, so the
    scan proves it can see the tree before anything is concluded from it.
    """
    assert len(strings) > 500, f"only {len(strings)} strings — the AST walk is broken"
    assert any(SITE in text for _p, text in strings), "no docs URL found at all"


def test_every_docs_link_resolves_to_a_page_that_exists(strings) -> None:
    """The defect this generalises: three links to pages that never existed."""
    bad: list[str] = []
    for path, text in strings:
        for url in _DOCS_URL.findall(text):
            page = url[len(SITE):].rstrip("/")
            if not page:  # the site root is always valid
                continue
            if not page.endswith(".html"):
                continue  # reported by the next test
            source = DOCS / (page.removesuffix(".html") + ".md")
            if not source.is_file():
                bad.append(f"{path.relative_to(ROOT)}: {url} -> docs/{source.name} missing")
    assert not bad, "shipped links that 404:\n  " + "\n  ".join(sorted(set(bad)))


def test_no_shipped_docs_link_uses_the_directory_form(strings) -> None:
    """`use_directory_urls: false`, so `<name>/` is a 404 and `<name>.html` is right.

    A near-miss rather than a past defect — it was nearly shipped into a binary once,
    which is exactly the case where nobody finds out but the user.
    """
    bad: list[str] = []
    for path, text in strings:
        for url in _DOCS_URL.findall(text):
            page = url[len(SITE):]
            if page and not page.endswith(".html"):
                bad.append(f"{path.relative_to(ROOT)}: {url}")
    assert not bad, (
        "these must end in .html — the site does not use directory URLs:\n  "
        + "\n  ".join(sorted(set(bad)))
    )


def test_no_yazses_github_link_points_at_the_wrong_owner(strings) -> None:
    """A YazSes link under another namespace sends a user to somebody else's repo.

    Scoped to repos *named* `yazses`, not to every GitHub URL. The first version
    demanded `MSKazemi/yazses` everywhere and flagged
    `github.com/k2-fsa/sherpa-onnx` and `github.com/thewh1teagle/kokoro-onnx` — the
    upstream model downloads, which are registered egress and **must** point
    elsewhere. A rule that forbids third-party links in a program that downloads
    third-party models is a rule that gets deleted.

    What is left is the real risk, and it is invisible by reading: the owner is one
    token in a long URL, and a fork's URL differs from the canonical one by that token
    alone.
    """
    wrong: list[str] = []
    for path, text in strings:
        for owner, repo in _GITHUB_URL.findall(text):
            if repo.lower().startswith("yazses") and owner != "MSKazemi":
                wrong.append(f"{path.relative_to(ROOT)}: github.com/{owner}/{repo}")
    assert not wrong, "YazSes links under the wrong owner:\n  " + "\n  ".join(
        sorted(set(wrong))
    )


def test_that_owner_check_can_actually_fail() -> None:
    """The rule is narrow enough to need proof it still catches the thing it is for."""
    assert _GITHUB_URL.findall("see https://github.com/someonelse/yazses/issues") == [
        ("someonelse", "yazses")
    ]


def test_the_guard_would_notice_a_broken_link() -> None:
    """Only worth having if it can fail — checked on the real page set."""
    assert not (DOCS / "how-to/no-text-appears.md").is_file(), (
        "this test assumes the page from the original defect still does not exist"
    )
    assert (DOCS / "troubleshooting.md").is_file()


# --- the same two rules, over every tracked file ------------------------------

#: `mskazemi.com/yazses/apt` is not a page. It is the APT repository published to the
#: `gh-pages` branch, and `install-apt.sh` fetches `$BASE/KEY.gpg` from it — a directory
#: of real files, where `use_directory_urls` has no meaning. Exempting the prefix rather
#: than the two files that name it, so a third caller is covered on the day it is written.
_NOT_A_PAGE = ("apt",)

#: A link checker's fixtures are wrong on purpose.
_SKIP_TREES = ("tests",)

#: Trailing characters a sentence contributes, not the URL. `llms.txt` ends a line with
#: "…/mobile/index.html." and `SUBMISSION.md` with "…/yazses/." — both would otherwise
#: read as a page named `index.html.`. This is the same reason the scan above drops
#: docstrings, met again in prose instead of in Python.
_SENTENCE_TAIL = ".,;:!?)]}\"'"


def _tracked_text_files() -> list[Path]:
    """Every tracked file this guard reads, from git rather than a glob.

    `git ls-files` so a file that is present but untracked — a scratch copy, a local
    draft — cannot fail the build, and so a file that is tracked cannot be missed by a
    pattern nobody remembered to update.
    """
    require_git()
    listing = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    out: list[Path] = []
    for name in listing:
        if name.split("/", 1)[0] in _SKIP_TREES:
            continue
        path = ROOT / name
        if path.suffix.lower() in {".png", ".jpg", ".gif", ".ico", ".icns", ".pdf", ".woff2"}:
            continue
        if path.is_file():
            out.append(path)
    return out


def _site_links() -> list[tuple[Path, str, str]]:
    """`(path, url, tail)` for every docs-site URL in a tracked file.

    Everything is collected, including the bare site root — `snap/snapcraft.yaml`'s
    `website:` field is exactly that, and a collector that filtered it out would have
    reported the snap listing as a file carrying no links at all.
    """
    found: list[tuple[Path, str, str]] = []
    for path in _tracked_text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for raw in _DOCS_URL.findall(text):
            url = raw.rstrip(_SENTENCE_TAIL)
            found.append((path, url, url[len(SITE):].split("#")[0].split("?")[0]))
    return found


def _is_a_page_reference(tail: str) -> bool:
    """True when *tail* names a documentation page rather than the root or an asset.

    Three things on this site are not pages and must not be held to the `.html` rule:
    the root itself, the `apt/` repository directory, and generated assets that mkdocs
    publishes with their own extensions — `sitemap.xml`, `feed_rss_created.xml`,
    `feed_json_created.json`. Keying off "has a non-.html extension" rather than listing
    the asset names, because the plugin set decides those and this file would not hear
    about a new one.
    """
    if not tail or tail.split("/")[0] in _NOT_A_PAGE:
        return False
    last = tail.rstrip("/").split("/")[-1]
    return "." not in last or last.endswith(".html")


@pytest.fixture(scope="module")
def site_links() -> list[tuple[Path, str, str]]:
    return _site_links()


def test_the_repo_wide_scan_reaches_the_files_it_is_for(site_links) -> None:
    """A guard over an empty set passes on everything.

    Named files rather than a count alone: the point of widening the scan is that these
    four surfaces were unreached, so each is asserted to be reachable by name.
    """
    assert len(site_links) > 50, f"only {len(site_links)} site links found repo-wide"
    reached = {p.relative_to(ROOT).as_posix() for p, _u, _t in site_links}
    for surface in (
        "packaging/flatpak/com.mskazemi.YazSes.metainfo.xml",
        "snap/snapcraft.yaml",
        "pyproject.toml",
        "CITATION.cff",
    ):
        assert surface in reached, f"{surface} carries a site URL the scan did not see"


def test_no_tracked_file_uses_the_directory_form(site_links) -> None:
    """The defect: the Flathub listing's Help button pointed at `troubleshooting/`.

    `use_directory_urls: false`, so the page is `troubleshooting.html` and the directory
    form is a 404 — served to whoever pressed Help in GNOME Software, which is the
    moment they were already stuck. `test_flatpak_metainfo.py` reads that same file and
    checks its `<url>` fields, but only that none of them is a placeholder.
    """
    bad = sorted({
        f"{path.relative_to(ROOT)}: {url}"
        for path, url, tail in site_links
        if _is_a_page_reference(tail) and not tail.endswith(".html")
    })
    assert not bad, (
        "these must end in .html — the site does not use directory URLs:\n  "
        + "\n  ".join(bad)
    )


def test_every_tracked_site_link_resolves_to_a_page_that_exists(site_links) -> None:
    """`.html` is necessary, not sufficient — the page behind it has to be there."""
    bad = sorted({
        f"{path.relative_to(ROOT)}: {url} -> docs/{tail.removesuffix('.html')}.md missing"
        for path, url, tail in site_links
        if tail.endswith(".html")
        and not (DOCS / (tail.removesuffix(".html") + ".md")).is_file()
    })
    assert not bad, "tracked links that 404:\n  " + "\n  ".join(bad)


def test_what_counts_as_a_page_is_narrow_in_both_directions() -> None:
    """The classifier is where this guard can go wrong, so it is pinned directly.

    Too wide and it demands `.html` of `sitemap.xml`; too narrow and it excuses
    `troubleshooting/`, which is the defect it exists for.
    """
    for tail, is_page in (
        ("troubleshooting/", True),          # the defect
        ("how-to/air-gapped.html", True),
        ("mobile", True),                    # extensionless: still a page reference
        ("", False),                         # the site root
        ("apt", False),                      # the APT repository directory
        ("apt/KEY.gpg", False),
        ("sitemap.xml", False),              # generated asset
        ("feed_rss_created.xml", False),
        ("feed_json_created.json", False),
    ):
        assert _is_a_page_reference(tail) is is_page, tail


def test_a_sentence_final_period_is_not_part_of_the_url(site_links) -> None:
    """`llms.txt` ends a line with "…/mobile/index.html." — the page is not named
    `index.html.`.

    Asserted through the collector, not against the regex. The first version of this
    test called `_DOCS_URL.findall` and `rstrip` inline, so removing the strip from
    `_site_links` left it perfectly green — it was checking a copy of the logic instead
    of the logic. Worse, the failure it missed is **silent**: a tail of `index.html.`
    has a dot in its last segment and does not end in `.html`, so
    `_is_a_page_reference` files it as an asset and the link stops being checked at all.
    """
    dirty = sorted({
        f"{path.relative_to(ROOT)}: {url}"
        for path, url, _tail in site_links
        if url.rstrip(_SENTENCE_TAIL) != url
    })
    assert not dirty, "sentence punctuation left on a URL:\n  " + "\n  ".join(dirty)

    # …and the corpus really does contain such prose, or the check above proves nothing.
    corpus = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore") for p in _tracked_text_files()
    )
    assert re.search(re.escape(SITE) + r"[A-Za-z0-9._/-]*[.,)]", corpus), (
        "no sentence-final punctuation after a site URL anywhere in the tree — "
        "this guard has nothing to protect and its mutation cannot be observed"
    )


def test_the_repo_wide_rule_can_actually_fail() -> None:
    """Proves the match fires, rather than passing because the tree is already clean."""
    good, bad = SITE + "troubleshooting.html", SITE + "troubleshooting/"
    assert _DOCS_URL.findall(f"see {good} and {bad}") == [good, bad]

    def fails_the_rule(url: str) -> bool:
        tail = url[len(SITE):]
        return _is_a_page_reference(tail) and not tail.endswith(".html")

    assert fails_the_rule(bad), "the directory form must be caught"
    assert not fails_the_rule(good), "the correct form must not be"
