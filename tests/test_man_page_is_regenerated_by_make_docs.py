"""The AUR package would have shipped a man page stamped with the previous version.

`man/yazses.1` carries the version and date in its `.TH` header. The sync test
deliberately ignores that line — `gen_man.body()` explains why, and the reasoning is
sound: enforcing byte-equality would turn every version bump into a red CI run until
someone remembered `make man`, which is a landmine rather than a safety net.

The consequence went unexamined. The stamp was then refreshed by nothing automatic:

* `make docs` regenerated the reference pages and the architecture figures, not the page.
* No workflow ran `make man`.
* The project rule that does cover it — *"CLI change → `make man`"* — is tied to CLI
  changes, and a version bump is not one.

So the file sat at `yazses 2.28.0` in a tree preparing 2.29.0, and the suite was green,
correctly.

## Why that matters for one channel and not the other

`gen_man.body`'s docstring said the shipped page *"always carries the right version
regardless: `scripts/build-deb.sh` regenerates it at package build time."* True — for the
`.deb`. Two packaging paths install this file, and the other is
`packaging/arch/PKGBUILD`, which installs the **committed** file unchanged. The AUR
package ships whatever stamp is in git.

`make docs` now regenerates the page as well, so any "refresh the reference material" step
carries the stamp with it.

## What is deliberately *not* asserted here

That the committed stamp equals the package version. That check would redden CI on a bump —
precisely the failure mode the existing design avoids, and reintroducing it through the back
door would be worse than the drift it prevents. This asserts the *mechanism* instead, which
cannot fail on a bump.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
MAN = ROOT / "man" / "yazses.1"
PKGBUILD = ROOT / "packaging" / "arch" / "PKGBUILD"


def _docs_target() -> str:
    """The body of the `docs:` target."""
    text = MAKEFILE.read_text(encoding="utf-8")
    start = text.index("\ndocs:\n") + 1
    rest = text[start:]
    # A target ends at the first line that is neither indented nor blank.
    lines = rest.splitlines()[1:]
    body: list[str] = []
    for line in lines:
        if line and not line.startswith(("\t", " ")):
            break
        body.append(line)
    return "\n".join(body)


def test_make_docs_regenerates_the_man_page() -> None:
    """The mechanism. Without it the stamp is refreshed only by memory."""
    assert "gen-man.py" in _docs_target(), (
        "`make docs` no longer regenerates man/yazses.1 — the stamp goes back to being "
        "refreshed by whoever remembers `make man` after a version bump, which is nobody"
    )


def test_make_docs_still_regenerates_the_reference_pages() -> None:
    """Guard the guard: a `docs:` target that lost its other steps would pass above."""
    body = _docs_target()
    assert "gen-docs.py" in body
    assert "gen-arch-figures.py" in body


def test_the_man_target_still_exists_on_its_own() -> None:
    """`make man` is still the quick step after a CLI change; this adds, not replaces."""
    assert re.search(r"^man:$", MAKEFILE.read_text(encoding="utf-8"), re.M)


@pytest.mark.skipif(not MAN.exists(), reason="man/yazses.1 not on this checkout")
def test_the_header_still_carries_a_version_and_a_date() -> None:
    """Shape only. Asserting the *value* would redden CI on a bump, which is the failure
    the sync test's design deliberately avoids — see this file's docstring."""
    first = MAN.read_text(encoding="utf-8").splitlines()[0]
    assert re.fullmatch(
        r'\.TH YAZSES 1 "(\d{4}-\d{2}-\d{2}|unreleased)" "yazses [^"]+" "User Commands"',
        first,
    ), f"malformed .TH header: {first!r}"


@pytest.mark.skipif(not PKGBUILD.exists(), reason="arch packaging not on this checkout")
def test_the_arch_package_still_installs_the_committed_file() -> None:
    """The premise for caring about the committed stamp at all.

    If this ever starts regenerating, the docstring in `scripts/gen-man.py` needs
    updating — its claim about which channels regenerate is what went stale before.
    """
    text = PKGBUILD.read_text(encoding="utf-8")
    assert "man/yazses.1" in text
    assert "gen-man" not in text, (
        "the Arch package now regenerates the man page — update the note in "
        "scripts/gen-man.py, which says it installs the committed file"
    )


def test_the_deb_build_does_regenerate_it() -> None:
    """The other half of the same claim, so both stay true together."""
    script = ROOT / "scripts" / "build-deb.sh"
    if not script.exists():
        pytest.skip("deb packaging not on this checkout")
    assert "gen-man.py" in script.read_text(encoding="utf-8")
