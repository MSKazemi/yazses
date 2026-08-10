"""The contributors wall must agree with itself.

Credit is spread across three hand-maintained surfaces — `.all-contributorsrc` (the
source of truth), the generated wall + badge in `README.md`, and the prose in
`CONTRIBUTORS.md`. Nothing kept them in step, and all three had drifted: the rc badge
template said 8, the README badge said 9, and there were 10 people. @YossiMH was
credited in CONTRIBUTORS.md for the design review that produced `contract/semantic/`
and was missing from the wall entirely — the surface people actually look at.

Being forgotten is the one failure mode a contributor never reports. These checks are
offline and deterministic; "is someone with merged work missing from all three?" needs
the GitHub API and is a maintainer task, not a unit test.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RC = ROOT / ".all-contributorsrc"
README = ROOT / "README.md"
CONTRIBUTORS = ROOT / "CONTRIBUTORS.md"


def _rc_logins() -> list[str]:
    return [c["login"] for c in json.loads(RC.read_text(encoding="utf-8"))["contributors"]]


def _contributors_md_logins() -> set[str]:
    """Every `[@login](...)` mentioned in CONTRIBUTORS.md, any section."""
    return set(re.findall(r"\[@([A-Za-z0-9-]+)\]", CONTRIBUTORS.read_text(encoding="utf-8")))


def test_everyone_on_the_wall_is_named_in_contributors_md():
    missing = sorted(set(_rc_logins()) - _contributors_md_logins())
    assert not missing, (
        f"on the README wall but absent from CONTRIBUTORS.md: {missing} — "
        "add them, or remove them from .all-contributorsrc"
    )


def test_everyone_named_in_contributors_md_is_on_the_wall():
    """The direction that actually broke: credited in prose, invisible on the wall."""
    missing = sorted(_contributors_md_logins() - set(_rc_logins()))
    assert not missing, (
        f"credited in CONTRIBUTORS.md but missing from the README wall: {missing} — "
        "run `npx all-contributors-cli add <login> <types>`. A contribution with no "
        "commit behind it (ideas, bug, research) is exactly the kind that gets dropped."
    )


def test_the_badge_counts_the_people_actually_on_the_wall():
    badge = re.search(r"all_contributors-(\d+)-", README.read_text(encoding="utf-8"))
    assert badge, "the all-contributors badge is gone from README.md"
    assert int(badge.group(1)) == len(_rc_logins()), (
        f"badge says {badge.group(1)}, .all-contributorsrc has {len(_rc_logins())} "
        "contributors. The generator does not own this line — update it by hand."
    )


def test_the_wall_renders_every_contributor():
    wall = README.read_text(encoding="utf-8")
    start, end = wall.find("ALL-CONTRIBUTORS-LIST:START"), wall.find("ALL-CONTRIBUTORS-LIST:END")
    assert start != -1 and end != -1, "the ALL-CONTRIBUTORS-LIST markers are gone from README.md"
    section = wall[start:end]
    missing = [login for login in _rc_logins() if f'href="https://github.com/{login}"' not in section]
    assert not missing, (
        f"in .all-contributorsrc but not rendered in the README wall: {missing} — "
        "run `npx all-contributors-cli generate`"
    )


def test_no_duplicate_entries():
    logins = _rc_logins()
    dupes = sorted({x for x in logins if logins.count(x) > 1})
    assert not dupes, f"listed twice in .all-contributorsrc: {dupes}"
