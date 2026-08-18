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
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

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
