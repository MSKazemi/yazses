"""The no-code tester guide must keep pointing at things that exist (#449).

`design/eye-control/BEGINNER_TESTING.md` is read by someone who has never seen the
project, who will not guess their way around a dead link, a renamed command or an issue
number that moved. The first read-through (#449) found a link-shaped defect that no test
could see: the guide wrote issue numbers as bare `#428`, which GitHub does not turn into a
link inside a repository Markdown file, so the person it was written for could not click
the one thing the page exists to point them at.

What is checked, all offline, all derived from the guide text itself:

* every relative Markdown link resolves to a tracked file, and an `#anchor` on a Markdown
  target names a real heading;
* every `#NNN` is written as a link to that same issue (so it is clickable), and every
  hardware slot in `validation-slots.json` appears in the guide (so a slot added to the
  registry cannot be missing from the page that tells people which one to pick);
* every `yazses ...` code span names a command or a root option the CLI really has, and
  every backticked repo path (`scripts/x.py`, `validation-slots.json`) exists.

What is deliberately NOT checked: that a GitHub issue is open, labelled or READY. That is
live state on GitHub; a file cannot track it (see the README of this programme), and an
offline test must not reach the network.

A checker that finds nothing is not evidence of a healthy guide, so `problems()` reports an
empty guide as a problem of its own, and the tests below show each defect class is
actually reported.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import typer

from tests.test_advised_commands_exist import advised_flags, unresolved
from yazses.cli import app

ROOT = Path(__file__).resolve().parents[1]
EYE = ROOT / "design" / "eye-control"
REGISTRY = EYE / "validation-slots.json"

#: The guide a first-time reader opens, and the two files issue #449 sends them to.
GUIDES = ("BEGINNER_TESTING.md", "VALIDATION_MATRIX.md", "DATA_SHARING.md")

#: Pages allowed to carry no Markdown links (they cite bare URLs). Anything not here must have some.
LINKLESS_OK = frozenset({"DATA_SHARING.md"})

_LINK = re.compile(r"(?<!!)\[(?P<text>[^\]]*)\]\((?P<target>[^)\s]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(?P<title>.+?)\s*#*\s*$", re.MULTILINE)
_CODE_SPAN = re.compile(r"`([^`\n]+)`")
_ISSUE_REF = re.compile(r"(?<![\w/])#(?P<n>\d{2,5})\b")
_ISSUE_URL = re.compile(r"^https://github\.com/MSKazemi/yazses/issues/(?P<n>\d+)$")
_PATHLIKE = re.compile(r"^[\w.][\w./-]*\.(?:py|json|yml|yaml|md|toml)$")


def _slug(title: str) -> str:
    """GitHub's heading anchor: lower-case, markup and punctuation dropped, spaces to `-`."""
    title = re.sub(r"`([^`]*)`", r"\1", title)
    title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title)
    title = title.strip().lower()
    title = re.sub(r"[^\w\- ]", "", title)
    return title.replace(" ", "-")


def anchors_of(text: str) -> set[str]:
    """Every anchor a GitHub renderer gives the headings in *text* (repeats get `-1`, `-2`)."""
    seen: dict[str, int] = {}
    out: set[str] = set()
    for match in _HEADING.finditer(text):
        base = _slug(match.group("title"))
        count = seen.get(base, 0)
        out.add(base if count == 0 else f"{base}-{count}")
        seen[base] = count + 1
    return out


def _root_options() -> set[str]:
    root = typer.main.get_command(app)
    opts: set[str] = set()
    for param in getattr(root, "params", []):
        opts |= set(getattr(param, "opts", ()) or ())
    return {o for o in opts if o.startswith("-")}


def _exists_in_repo(rel: str, base: Path) -> bool:
    """Is *rel* a file under the repo, relative to the guide's folder or the repo root?"""
    for start in (base, ROOT):
        candidate = (start / rel).resolve()
        try:
            candidate.relative_to(ROOT)
        except ValueError:
            continue
        if candidate.is_file():
            return True
    return False


def problems(
    text: str,
    base: Path,
    *,
    registry_issues: frozenset[int] = frozenset(),
    require_links: bool = True,
) -> list[str]:
    """Everything wrong with one guide's *text*, as readable sentences. Pure but for file stats.

    *require_links* is on by default: a guide with no links is reported rather than passed.
    It is switched off only for a page that genuinely carries none (DATA_SHARING.md cites
    bare URLs), and `test_the_guides_that_may_have_no_links_really_have_none` pins that.
    """
    found: list[str] = []
    links = _LINK.findall(text)
    if require_links and not links:
        found.append("the guide contains no links at all, so this check is blind to it")

    own_anchors = anchors_of(text)
    for _label, target in links:
        issue = _ISSUE_URL.match(target)
        if issue or target.startswith(("http://", "https://", "mailto:")):
            continue  # external: reachability is live state, not a repo fact
        path_part, _, fragment = target.partition("#")
        if not path_part:
            if fragment and fragment not in own_anchors:
                found.append(f"anchor #{fragment} matches no heading in this file")
            continue
        if not _exists_in_repo(path_part, base):
            found.append(f"link target {path_part} does not exist in the repository")
            continue
        if fragment and path_part.endswith(".md"):
            for start in (base, ROOT):
                candidate = (start / path_part).resolve()
                if candidate.is_file():
                    other = candidate.read_text(encoding="utf-8")
                    if fragment not in anchors_of(other):
                        found.append(f"anchor #{fragment} matches no heading in {path_part}")
                    break

    # Every #NNN must be a clickable link to that same issue.
    linked: dict[int, int] = {}
    for label, target in links:
        issue = _ISSUE_URL.match(target)
        if issue:
            linked[int(issue.group("n"))] = linked.get(int(issue.group("n")), 0) + 1
            shown = _ISSUE_REF.search(label)
            if shown and int(shown.group("n")) != int(issue.group("n")):
                found.append(f"link text #{shown.group('n')} points at issue {issue.group('n')}")
    without_links = _LINK.sub(" ", text)
    without_code = _CODE_SPAN.sub(" ", without_links)
    for match in _ISSUE_REF.finditer(without_code):
        n = int(match.group("n"))
        found.append(f"#{n} is written as plain text; GitHub does not link it in a Markdown file")
    for n in sorted(registry_issues):
        if n not in linked:
            found.append(f"slot issue #{n} is in validation-slots.json but not linked in the guide")

    # Commands and paths named in code spans.
    for span in _CODE_SPAN.findall(text):
        words = span.split()
        if words[:1] == ["yazses"] and len(words) > 1:
            if words[1].startswith("-"):
                if words[1] not in _root_options():
                    found.append(f"`{span}`: yazses has no root option {words[1]}")
                continue
            for parts in unresolved(f"`{span}`"):
                found.append(f"`{span}`: the CLI has no command `yazses {' '.join(parts)}`")
            for invocation, flag in advised_flags(span):
                found.append(f"`{span}`: {invocation} does not accept {flag}")
        for word in words:
            if _PATHLIKE.match(word) and not _exists_in_repo(word, base):
                found.append(f"`{span}` names {word}, which does not exist")
    return found


def _registry_issues() -> frozenset[int]:
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return frozenset(int(s["issue"]) for s in data["slots"] if s.get("issue"))


# --- the guards must be able to fail ----------------------------------------------------


def test_an_empty_guide_is_reported_not_passed():
    """The vacuity proof the task asked for: nothing to check is a finding, never a pass."""
    assert problems("", EYE)
    assert any("no links" in p for p in problems("", EYE))
    assert any("no links" in p for p in problems("just prose, no links", EYE))


@pytest.mark.parametrize(
    "text,needle",
    [
        pytest.param("[x](NO_SUCH_FILE.md)", "does not exist", id="dead-file-link"),
        pytest.param("[x](DATA_SHARING.md#no-such-heading)", "matches no heading", id="dead-anchor"),
        pytest.param("[x](#nowhere)", "matches no heading", id="dead-local-anchor"),
        pytest.param("[a](DATA_SHARING.md) pick #428 now", "plain text", id="unlinked-issue-ref"),
        pytest.param(
            "[#428](https://github.com/MSKazemi/yazses/issues/429)",
            "points at issue",
            id="issue-text-and-url-disagree",
        ),
        pytest.param("[a](DATA_SHARING.md) `yazses nosuchcommand`", "no command", id="dead-command"),
        pytest.param("[a](DATA_SHARING.md) `yazses --nosuchflag`", "no root option", id="dead-root-flag"),
        pytest.param(
            "[a](DATA_SHARING.md) `uv run python scripts/nosuchscript.py`",
            "does not exist",
            id="dead-script",
        ),
    ],
)
def test_each_defect_class_is_actually_reported(text, needle):
    assert any(needle in p for p in problems(text, EYE)), problems(text, EYE)


def test_a_slot_missing_from_the_guide_is_reported():
    found = problems("[a](DATA_SHARING.md)", EYE, registry_issues=frozenset({428}))
    assert any("#428" in p and "not linked" in p for p in found)


def test_good_references_are_accepted():
    """And the other direction: the detector is not just refusing everything."""
    good = (
        "[m](VALIDATION_MATRIX.md#test-packs) "
        "[i](https://github.com/MSKazemi/yazses/issues/428) "
        "[#428](https://github.com/MSKazemi/yazses/issues/428) "
        "`yazses --version` `yazses audio devices` "
        "`scripts/check_eye_validation_slots.py` `validation-slots.json`"
    )
    assert problems(good, EYE) == []


def test_the_heading_slugger_matches_github_for_this_programmes_headings():
    text = "# A\n## Is the test available yet?\n## Pick one task\n### T0 — install / camera\n## Pick one task\n"
    assert anchors_of(text) >= {
        "a",
        "is-the-test-available-yet",
        "pick-one-task",
        "pick-one-task-1",
        "t0--install--camera",
    }


# --- the real guides --------------------------------------------------------------------


def test_the_registry_has_slots_to_check_against():
    issues = _registry_issues()
    assert len(issues) >= 10, "validation-slots.json lost its slots -- the coverage check is blind"
    assert {428, 437, 440} <= issues


@pytest.mark.parametrize("name", [pytest.param(n, id=n.removesuffix(".md").lower()) for n in GUIDES])
def test_every_reference_in_the_guide_exists(name):
    path = EYE / name
    text = path.read_text(encoding="utf-8")
    # Only the beginner page is the slot picker; the other two are checked for what they point at.
    registry = _registry_issues() if name == "BEGINNER_TESTING.md" else frozenset()
    found = problems(
        text, EYE, registry_issues=registry, require_links=name not in LINKLESS_OK
    )
    if name != "BEGINNER_TESTING.md":
        # They name issue numbers in tables as plain text for maintainers; that is the
        # open question recorded for the maintainer, not a regression this guard owns.
        found = [p for p in found if "plain text" not in p]
    assert not found, f"{path.relative_to(ROOT).as_posix()}:\n  " + "\n  ".join(found)


def test_the_guides_that_may_have_no_links_really_have_none():
    """An exemption is a claim; this keeps it true instead of letting it rot into blindness."""
    for name in sorted(LINKLESS_OK):
        text = (EYE / name).read_text(encoding="utf-8")
        assert not _LINK.findall(text), (
            f"{name} now has links: drop it from LINKLESS_OK so they are checked"
        )
    assert LINKLESS_OK <= set(GUIDES)


def test_the_beginner_guide_still_carries_the_privacy_and_research_warnings():
    """#449 acceptance: an edit for clarity must not drop the two warnings."""
    text = (EYE / "BEGINNER_TESTING.md").read_text(encoding="utf-8")
    anchors = anchors_of(text)
    assert "never-share-in-a-public-issue" in anchors
    assert "am-i-joining-a-research-study" in anchors
    assert "community engineering QA" in text
    assert "does not convert your GitHub test into research consent" in text
    assert "GitHub issues are public" in text
