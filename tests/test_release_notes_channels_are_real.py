"""Every install channel the release notes advertise must have something publishing it.

`release.yml` builds the GitHub release notes from a template, and that template is
the single most-read document this project ships: it is what a person sees the moment
they decide to install. For two years it carried

    **Launchpad PPA (Ubuntu):**
    ```bash
    sudo add-apt-repository ppa:mskazemi/yazses
    ```

for a PPA that does not exist. Launchpad answers 404 for
`~mskazemi/+archive/ubuntu/yazses` and 404 for the person `~mskazemi`, so not only was
the archive empty -- the account it would belong to was never created. `ppa.yml` was
the intended publisher and had been dead since v1.0.0, triggering on `v0.*` tags only
and handing off to a `rust-release.yml` that was deleted when the Rust line was
archived. Every release since then told Ubuntu users to run a command that fails.

Both halves were individually invisible. Reading `ppa.yml` shows a workflow that never
runs, which looks like a dormant channel and not a defect -- and its own comment said,
in good faith, "Nothing advertises a PPA to users". Reading the notes template shows an
ordinary install instruction. Only holding the two side by side shows the fault, and
nothing did.

So this test is the thing that holds them side by side: it lifts every advertised
channel out of the notes template and asks what in this repository publishes it. A
channel with no publisher is either a broken promise to users or a workflow someone
forgot to wire, and both need a person to decide which.
"""

from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RELEASE = ROOT / ".github" / "workflows" / "release.yml"
WORKFLOWS = ROOT / ".github" / "workflows"

#: A bolded heading inside the notes template: `**Snap:**`, `**APT repository:**`.
_HEADING = re.compile(r"^\s+\*\*(?P<label>[^*]+?):\*\*\s*$", re.MULTILINE)

#: For each advertised channel, one piece of evidence that something publishes it.
#: A path relative to the repository root, plus a string that must appear in it. The
#: pairing is the point -- naming only the file would pass on a file that had stopped
#: doing the thing, and naming only the string would match a comment anywhere.
PUBLISHERS: dict[str, tuple[str, str]] = {
    "One-line installer (Debian/Ubuntu)": ("install.sh", "yazses"),
    # The APT repository is served from the gh-pages branch, which apt-repo.yml
    # regenerates on every tag. That branch is deliberately not merged into main, so
    # the workflow is the evidence available from here.
    "APT repository": (".github/workflows/apt-repo.yml", "gh-pages"),
    "Snap": (".github/workflows/snap.yml", "snapcraft"),
    "pipx (any Linux)": (".github/workflows/release.yml", "pypi"),
    ".deb package": (".github/workflows/release.yml", "build-deb"),
}


def _advertised() -> list[str]:
    text = RELEASE.read_text(encoding="utf-8")
    return [m.group("label") for m in _HEADING.finditer(text)]


def test_the_template_still_advertises_channels_at_all() -> None:
    """Without this, deleting the whole Linux section would make every assertion below
    pass -- the failure mode of any test that iterates over what it finds."""
    found = _advertised()
    assert len(found) >= 4, (
        f"only {len(found)} advertised channels were parsed out of {RELEASE.name}; "
        f"the heading format probably changed and this guard is now reading nothing: "
        f"{found}"
    )


@pytest.mark.parametrize("label", _advertised())
def test_every_advertised_channel_has_something_that_publishes_it(label: str) -> None:
    assert label in PUBLISHERS, (
        f"the release notes advertise **{label}** and this test does not know what "
        f"publishes it. Add it to PUBLISHERS with the workflow or script that does -- "
        f"or, if nothing does, remove it from the notes. A install instruction with no "
        f"publisher behind it is what shipped `add-apt-repository ppa:mskazemi/yazses` "
        f"in every release for two years, for a PPA that has never existed."
    )
    relative, needle = PUBLISHERS[label]
    path = ROOT / relative
    assert path.exists(), f"**{label}** names {relative} as its publisher, and it is gone"
    assert needle in path.read_text(encoding="utf-8"), (
        f"**{label}** is advertised to users, but {relative} no longer mentions "
        f"{needle!r} -- so the thing that was publishing it may have stopped"
    )


def test_no_workflow_publishes_to_a_launchpad_ppa_while_the_notes_stay_silent() -> None:
    """The specific regression, from the direction it actually arrived.

    `ppa.yml` is kept in the tree on purpose: the packaging work in it is real and a
    Launchpad account is a decision, not a defect. What must not come back is the
    advertisement without the publisher. If someone revives the PPA, this fails and
    says so -- which is the moment to put the section back.
    """
    notes = RELEASE.read_text(encoding="utf-8")
    assert "add-apt-repository ppa:" not in notes, (
        "the release notes advertise a Launchpad PPA again. Before restoring this, "
        "check that the archive exists: https://launchpad.net/~mskazemi/+archive/"
        "ubuntu/yazses answered 404 on 2026-08-30, as did the Launchpad person "
        "~mskazemi, and ppa.yml has never run."
    )


def test_a_workflow_that_can_never_fire_says_so_where_it_is_read() -> None:
    """`ppa.yml` triggers on `v0.*` and this project is on v2. A tag pattern that can
    no longer match is indistinguishable from a channel nobody has released to lately,
    and the GitHub Actions list shows it as `active` either way. The marker below is
    what separates 'dormant on purpose' from 'quietly broken'."""
    ppa = (WORKFLOWS / "ppa.yml").read_text(encoding="utf-8")
    if '- "v0.*"' not in ppa:
        pytest.skip("ppa.yml no longer pins the dead tag pattern; this guard is spent")
    assert "RELEASE-TRIGGER-DISABLED" in ppa, (
        "ppa.yml still triggers only on v0.* tags, which this project passed at "
        "v1.0.0, but no longer carries the marker explaining that it is deliberately "
        "dormant. Without it the next reader sees an active workflow."
    )
