"""Routing a literature sweep into the project inbox (`--inbox`).

The radar was already able to write a digest. What it could not do was *tell
anyone*, which is the difference between a feed and a habit: a digest nobody is
prompted to read is a digest nobody reads, and the file is only found by someone
who already remembered to look.

So a run that finds something appends one line to the note's `## 📥 INBOX`, where
the next pass picks it up like any other idea.

The insertion is pure and tested hard for one reason: that file is the user's own
writing, accumulated over time and **not** in git — this repo's `.gitignore`
covers it. A bug here destroys something with no undo. Every test below is
therefore about not damaging what is already in the file.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

NOTE = """<!-- header BEGIN -->
# Note
<!-- header END -->
## 📥 INBOX — dump raw ideas here

<!-- write anything below this line; nothing here needs a format -->

- an idea I already had

---

## ▶️ NOW

- something in flight
"""


def _script():
    spec = importlib.util.spec_from_file_location(
        "research_watch", ROOT / "scripts" / "research-watch.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_the_line_lands_inside_the_inbox() -> None:
    out = _script().insert_into_inbox(NOTE, "- 3 new papers")
    inbox = out.split("## 📥 INBOX")[1].split("---")[0]
    assert "- 3 new papers" in inbox


def test_nothing_already_written_is_lost() -> None:
    """The whole risk. The file is not in git; there is no undo."""
    out = _script().insert_into_inbox(NOTE, "- new")
    for line in NOTE.splitlines():
        assert line in out.splitlines(), f"lost: {line!r}"


def test_the_existing_inbox_entries_keep_their_order() -> None:
    out = _script().insert_into_inbox(NOTE, "- new")
    assert out.index("an idea I already had") < out.index("## ▶️ NOW")


def test_a_note_with_no_inbox_heading_is_left_alone() -> None:
    """Appending to a file whose shape we do not recognise is how you corrupt it.
    Better to write nothing and let the digest be found the ordinary way."""
    other = "# Some other file\n\njust prose\n"
    assert _script().insert_into_inbox(other, "- new") == other


def test_the_file_still_ends_with_a_newline() -> None:
    assert _script().insert_into_inbox(NOTE, "- new").endswith("\n")


def test_two_runs_do_not_stack_identical_lines() -> None:
    """A weekly timer that finds nothing new must not grow the inbox forever."""
    mod = _script()
    once = mod.insert_into_inbox(NOTE, "- 3 new papers")
    twice = mod.insert_into_inbox(once, "- 3 new papers")
    assert twice.count("- 3 new papers") == 1


def test_a_different_line_is_still_added() -> None:
    mod = _script()
    once = mod.insert_into_inbox(NOTE, "- 3 new papers on 2026-08-16")
    twice = mod.insert_into_inbox(once, "- 5 new papers on 2026-08-23")
    assert "2026-08-16" in twice and "2026-08-23" in twice


def test_writing_is_skipped_when_the_note_is_missing(tmp_path) -> None:
    """An unattended run on a machine with no note must not fail the sweep — the
    digest is still written and that is the important half."""
    mod = _script()
    assert mod.write_inbox_line(tmp_path / "absent.md", "- new") is False


def test_writing_returns_true_and_persists(tmp_path) -> None:
    mod = _script()
    note = tmp_path / "note.md"
    note.write_text(NOTE, encoding="utf-8")
    assert mod.write_inbox_line(note, "- 2 new papers") is True
    assert "- 2 new papers" in note.read_text(encoding="utf-8")
