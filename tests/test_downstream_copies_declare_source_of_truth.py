"""A file a release overwrites downstream must say so, in its own text.

Two publish jobs do the same thing: clone a repository this project does not
develop in, copy files from `packaging/` over whatever is there, and push. The
Homebrew tap and the AUR package are both published that way.

The consequence is invisible from the downstream side. A contributor who opens a
PR against the tap -- or a co-maintainer who patches the AUR PKGBUILD -- is
editing a file that the next release replaces wholesale. No conflict, no warning,
no trace. It already cost this project a real one: @slegarraga's one-line cask fix
(homebrew-yazses#1) sat unmerged while two releases shipped, and merging it would
not have helped, because the merge target is a copy.

The cheapest defence is that the file itself says where it lives. The cask always
had that header; PKGBUILD did not. So this asserts the property for every file any
such job copies, and *derives* the list from the workflows rather than naming the
channels -- a third channel added tomorrow is covered the day it is added, which
is the whole point, since a hand-written list is exactly the artefact that goes
stale without anyone noticing.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

# The phrase every such file must carry. Deliberately a whole clause rather than a
# word: "source of truth" appears in prose all over this repo, and a guard that
# matches it would pass on a file that merely mentions the concept.
MARKER = "never the other way round"

# A job block starts at exactly two spaces of indent under `jobs:`.
_JOB_START = re.compile(r"^  ([A-Za-z0-9_-]+):\s*$")
# `cp a b c dest/` -- capture the whole argument list, filter to packaging/ after.
_CP = re.compile(r"^\s*cp\s+(.*)$")
_CLONE = re.compile(r"\bgit\s+clone\b")
_PUSH = re.compile(r"\bgit\s+push\b")

# .SRCINFO is the single exemption, and it is a property of the FORMAT, not a
# decision about the channel: pacman's .SRCINFO grammar is `key = value` lines only
# and has no comment syntax, so the marker cannot be written there at all. It is
# also machine-rendered (`scripts/refresh-package-manifests.py::render_srcinfo`)
# from PKGBUILD, which does carry the marker. `test_every_exemption_is_still_copied`
# fails if this stops being a file we actually copy, so it cannot rot into a
# blanket excuse.
EXEMPT = {"packaging/arch/.SRCINFO"}


def _downstream_copied_files() -> dict[str, set[str]]:
    """job name -> packaging/ paths it copies into a cloned foreign repo."""
    found: dict[str, set[str]] = {}
    for wf in sorted(WORKFLOWS.glob("*.yml")):
        lines = wf.read_text(encoding="utf-8").splitlines()
        starts = [i for i, ln in enumerate(lines) if _JOB_START.match(ln)]
        for n, start in enumerate(starts):
            end = starts[n + 1] if n + 1 < len(starts) else len(lines)
            block = lines[start:end]
            text = "\n".join(block)
            if not (_CLONE.search(text) and _PUSH.search(text)):
                continue
            paths: set[str] = set()
            for ln in block:
                m = _CP.match(ln)
                if not m:
                    continue
                for token in m.group(1).split():
                    if token.startswith("packaging/"):
                        paths.add(token)
            if paths:
                name = _JOB_START.match(lines[start]).group(1)  # type: ignore[union-attr]
                found[f"{wf.name}:{name}"] = paths
    return found


@pytest.fixture(scope="module")
def copied() -> dict[str, set[str]]:
    return _downstream_copied_files()


def test_the_extractor_finds_a_known_downstream_job(copied: dict[str, set[str]]) -> None:
    """Green-on-empty is how this guard would lie.

    If the workflows are restructured -- a different clone form, a script instead of
    an inline `cp` -- every assertion below passes by finding nothing and reports
    compliance it never checked.
    """
    assert copied, (
        "no workflow job was found that clones a foreign repo, copies packaging/ "
        "files into it and pushes. Either the publish jobs changed shape (teach "
        "this extractor the new one) or this guard is now inert."
    )


def test_the_extractor_actually_parses_this_shape() -> None:
    """Prove the probe on a fixture, not only on the repo it is meant to police.

    A guard verified only against a tree that already passes cannot distinguish
    "the property holds" from "the parser matched nothing".
    """
    sample = """jobs:
  unrelated:
    steps:
      - run: echo hello
  publisher:
    steps:
      - run: |
          git clone ssh://example.invalid/pkg.git out
          cp packaging/demo/FILE packaging/demo/OTHER out/
          cd out
          git push origin HEAD:master
"""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        wf = Path(td) / "wf.yml"
        wf.write_text(sample, encoding="utf-8")
        lines = sample.splitlines()
        starts = [i for i, ln in enumerate(lines) if _JOB_START.match(ln)]
        assert [_JOB_START.match(lines[i]).group(1) for i in starts] == [  # type: ignore[union-attr]
            "unrelated",
            "publisher",
        ]
    # And the same block-walk the real extractor performs picks only the publisher.
    picked = {}
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = lines[start:end]
        if not (_CLONE.search("\n".join(block)) and _PUSH.search("\n".join(block))):
            continue
        paths = {
            t
            for ln in block
            if (m := _CP.match(ln))
            for t in m.group(1).split()
            if t.startswith("packaging/")
        }
        picked[_JOB_START.match(lines[start]).group(1)] = paths  # type: ignore[union-attr]
    assert picked == {"publisher": {"packaging/demo/FILE", "packaging/demo/OTHER"}}


def test_every_exemption_is_still_copied(copied: dict[str, set[str]]) -> None:
    """An exemption for a file nobody copies any more is a hole, not an exemption."""
    all_paths = {p for paths in copied.values() for p in paths}
    stale = EXEMPT - all_paths
    assert not stale, (
        f"EXEMPT names {sorted(stale)}, which no publish job copies downstream any "
        "more. Remove the exemption rather than leaving it to cover a future file "
        "that happens to reuse the name."
    )


def test_downstream_copied_files_declare_they_are_the_original(
    copied: dict[str, set[str]],
) -> None:
    missing: list[str] = []
    for job, paths in sorted(copied.items()):
        for rel in sorted(paths):
            if rel in EXEMPT:
                continue
            path = ROOT / rel
            if not path.exists():
                missing.append(f"{job}: {rel} is copied downstream but does not exist")
                continue
            if MARKER not in path.read_text(encoding="utf-8"):
                missing.append(f"{job}: {rel}")
    assert not missing, (
        "these files are copied over a downstream repository on every release, so an "
        f"edit made downstream is silently discarded, but they do not say so. Add a "
        f'header containing "{MARKER}" naming the downstream copy:\n  '
        + "\n  ".join(missing)
    )
