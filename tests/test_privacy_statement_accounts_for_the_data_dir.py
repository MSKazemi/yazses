"""The privacy statement must account for every file YazSes writes to your data directory.

It said *"The `recall` and `scratch` note features read from this same local corpus"* —
inside the section explaining that the corpus is machine-bound AES-256-GCM with only coarse
metadata in the clear. Half of that is right. Spoken Recall does query the encrypted corpus.
Ambient Scratch does not: `recall/scratch.py` appends each spoken note-to-self to
`scratch.jsonl` as plain JSON, and says so in its own docstring — *"Notes are plain local
files under the user's data dir."* So a reader was told their notes-to-self were encrypted
when they are a text file.

Auditing the rest of the directory turned up the same gap by omission. `src/` writes
thirteen things under `data_dir` and the page named four of them. Meeting Mode — the one
capability that records **other people's voices**, keeps plain-text transcripts, retains the
recording on request, and stores enrolled participants as voiceprints — did not appear on
the page at all. Neither did `few_shots.toml`, which `yazses tune --apply` fills with
decrypted utterances from the corpus.

## Derived, because a hand-written list is the defect it is checking for

The set comes from the source: every ``data_dir / "<name>"`` literal in `src/yazses`. A
feature that starts writing somewhere new fails this test on the commit that adds it, which
is the only moment anyone knows what it holds. There is no allow-list of "not really user
content" — lock files and model caches are one table row each, and saying "this is a lock
file" costs a line and removes a judgement call that would otherwise be made by whoever is
in a hurry.

`corpus.key` is checked separately: it is not built from a `data_dir / …` expression
(`learning/crypto.py` composes it from `_KEY_FILENAME`), and it is the one file whose
presence beside the database is the reason the encryption story needs explaining at all.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "yazses"
PAGE = ROOT / "docs" / "privacy-statement.md"

#: `data_dir / "x"` and `paths.data_dir / "x"`, the only way the tree names one.
_CHILD = re.compile(r'data_dir\s*/\s*"([^"]+)"')

#: A floor, so a scan whose input silently empties cannot pass on everything.
_MIN_CHILDREN = 8


def _data_dir_children() -> set[str]:
    found: set[str] = set()
    for path in SRC.rglob("*.py"):
        found |= set(_CHILD.findall(path.read_text(encoding="utf-8")))
    return found


def _page() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_the_scan_finds_the_paths_the_tree_writes() -> None:
    children = _data_dir_children()
    assert len(children) >= _MIN_CHILDREN, (
        f"only found {children}; the expression shape probably changed and every "
        "assertion below would be vacuous"
    )


def test_every_path_the_tree_writes_is_named_on_the_page() -> None:
    page = _page()
    missing = sorted(name for name in _data_dir_children() if name not in page)
    assert not missing, (
        "these are written under the user's data directory and the privacy statement "
        f"does not mention them: {missing}"
    )


def test_the_key_beside_the_corpus_is_named_too() -> None:
    """It is composed from a constant, so the scan above cannot see it."""
    from yazses.learning.crypto import _KEY_FILENAME

    assert _KEY_FILENAME in _page()


def test_the_page_says_which_stores_are_not_encrypted() -> None:
    """The three plain-text stores are the reason this section exists."""
    page = _page()
    for name in ("scratch.jsonl", "few_shots.toml", "meetings/"):
        line = next((ln for ln in page.splitlines() if name in ln and ln.startswith("|")), "")
        assert line, f"{name} is mentioned but not in the table of what is stored"
        assert "no" in line.lower(), f"{name} holds plain text; the table must say so: {line}"


def test_scratch_is_not_described_as_part_of_the_encrypted_corpus() -> None:
    """The specific sentence that was wrong, pinned against its own module."""
    from yazses.recall import scratch

    source = Path(scratch.__file__).read_text(encoding="utf-8")
    assert "plain local files" in source, (
        "recall/scratch.py no longer claims to write plain files -- if it encrypts now, "
        "this test and the privacy statement should both be updated, not just one"
    )
    # Collapsed, because the sentence wraps and a line break is not a difference.
    flowed = " ".join(_page().split())
    assert "Ambient Scratch does **not**" in flowed, (
        "the page must keep Recall (encrypted corpus) and Scratch (plain JSONL) apart"
    )


def test_meeting_mode_is_on_the_page_at_all() -> None:
    """It records other people; its absence was the largest omission found."""
    page = _page()
    assert "## Meeting Mode" in page
    for fact in ("retain_audio", "consent", "participants/"):
        assert fact in page, f"the Meeting Mode section does not mention {fact}"


def test_the_guard_would_notice_a_new_unmentioned_store(tmp_path) -> None:
    invented = "biometrics.db"
    assert invented not in _page(), "pick a name the page really does not contain"
    fake = f'path = paths.data_dir / "{invented}"'
    assert _CHILD.findall(fake) == [invented], "the scan would not see a new store"
