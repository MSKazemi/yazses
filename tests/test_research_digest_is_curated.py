"""A committed research digest must have been read by a person.

`scripts/research-watch.py` emits every entry with `**So what:** _(unreviewed …)_`. The
rule in `design/research/watch/README.md` is that each one is annotated or deleted before
the digest is committed, because an automated feed nobody prunes is a feed nobody reads —
and this repository already carries enough generated material that nothing consumes.

A rule like that decays silently: the first uncurated digest looks identical to a curated
one at a glance, and the second is easier to justify than the first. So it is a test.

It also guards the two things the digest promises about other people's work: no PDF is
redistributed, and every entry links to the publisher's copy.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WATCH = ROOT / "design/research/watch"
DIGESTS = sorted(WATCH.glob("*-digest.md"))

_UNREVIEWED = re.compile(r"\*\*So what:\*\*\s*_\(unreviewed")
_ENTRY = re.compile(r"^### \[(?P<title>[^\]]+)\]\((?P<link>[^)]+)\)", re.M)
_SO_WHAT = re.compile(r"^\*\*So what:\*\*\s*(?P<note>.+)$", re.M)


def test_the_watch_directory_exists():
    """Guard the guard: a moved directory would make every check below vacuous."""
    assert WATCH.is_dir(), f"{WATCH} is missing — did the watch move?"


@pytest.mark.parametrize("path", DIGESTS, ids=lambda p: p.name)
def test_no_entry_is_left_unreviewed(path: Path):
    text = path.read_text(encoding="utf-8")
    stale = _UNREVIEWED.findall(text)
    assert not stale, (
        f"{path.name} has {len(stale)} unreviewed entr{'y' if len(stale) == 1 else 'ies'}. "
        f"Add a 'So what' note explaining why it matters here, or delete the entry. "
        f"An uncurated digest is worse than no digest — see the README in that directory."
    )


@pytest.mark.parametrize("path", DIGESTS, ids=lambda p: p.name)
def test_every_entry_has_a_note_and_a_link(path: Path):
    text = path.read_text(encoding="utf-8")
    entries = _ENTRY.findall(text)
    notes = _SO_WHAT.findall(text)
    if not entries:
        return  # an empty sweep is a legitimate result
    assert len(notes) == len(entries), (
        f"{path.name}: {len(entries)} entries but {len(notes)} 'So what' notes — "
        f"every entry needs one"
    )
    for _title, link in entries:
        assert link.startswith(("http://", "https://")), (
            f"{path.name}: {link!r} is not a link to the publisher's copy"
        )


@pytest.mark.parametrize("path", DIGESTS, ids=lambda p: p.name)
def test_no_digest_links_to_a_pdf(path: Path):
    """We cite work; we do not redistribute it. The repo blocks committed PDFs, and a
    digest linking straight at one invites someone to save it here."""
    text = path.read_text(encoding="utf-8")
    pdfs = [m for m in re.findall(r"\((https?://[^)]+)\)", text) if m.lower().endswith(".pdf")]
    assert not pdfs, f"{path.name} links directly at PDFs: {pdfs}"


def test_the_seen_index_is_valid_and_not_empty_once_a_digest_exists():
    """`seen.json` is what stops the next run repeating itself. A digest with no index
    behind it means the next sweep reports everything again."""
    import json

    seen_path = WATCH / "seen.json"
    if not DIGESTS:
        return
    assert seen_path.is_file(), "a digest was committed without its seen-index"
    data = json.loads(seen_path.read_text(encoding="utf-8"))
    assert isinstance(data.get("ids"), list) and data["ids"], "the seen-index is empty"
