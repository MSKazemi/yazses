"""Staged dictation: speak → review → commit (#294).

Every transcript types straight into the focused app. For prose that is the whole
point of hold-to-talk. For **code and terminal input it is the wrong default**,
because a mis-transcribed token is not a typo you skim past — it is a command you
did not mean to run, or a symbol that does not exist.

Staged mode puts an explicit review step in between: bursts accumulate in a
buffer, you look at it, and the *commit* is the thing that types.

## Why this is not "just use the clipboard"

The clipboard path exists already — it is what the no-text-target guard falls back
to — but it is a **failure** path, not a workflow. Staged mode is chosen
deliberately, is visible while you speak, and puts correction *before* anything
reaches the target application. That last part is the point: `scratch that` is
already too late when the wrong text is in your editor.

## The decisions this module makes

The issue left two things open. Both are decided here, and both are decided the
same way — **the review step must not be defeatable by the very mis-transcription
it exists to catch.**

1. **Commit is deterministic by default, spoken only if asked for.** A spoken
   commit inside a buffer whose purpose is catching mis-recognition has an obvious
   failure mode: prose mis-heard as "commit" types the buffer early, which is
   exactly the accident staged mode was turned on to prevent. So the default path
   is an explicit action (`yazses staged commit`, the tray, or a key), and the
   spoken phrase is opt-in via `[staged] spoken_commit`. When it *is* on, the
   grammar is anchored at both ends like `commands/revise.py::_SCRATCH_RE` — "commit"
   is an ordinary word, and a suffix match would swallow "git commit" instead of
   staging it.

2. **While something is pending, revision edits the buffer, not the document.**
   "scratch that" during staged mode drops the last staged chunk. Editing already
   committed text would be a different, more surprising action reached by the same
   words, and the buffer is the thing the user is looking at.

The asymmetry that drives both: a **missed** commit is visible and costs one more
action, while a **premature** commit has already typed into your terminal.

Pure and dependency-free — no I/O, no clock, no Qt. The daemon owns an instance and
the overlay renders :meth:`StagedBuffer.preview`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# Anchored at both ends: a suffix match would turn "git commit" into a commit and
# "let's discard that idea" into a discard. Whole utterance or nothing.
_COMMIT_RE = re.compile(
    r"^\s*(commit(?: that| it| this)?|send it|type it|paste it)[.!]?\s*$", re.IGNORECASE
)
_DISCARD_RE = re.compile(
    r"^\s*(discard(?: that| it| this)?|throw (?:that|it) away|clear the buffer)[.!]?\s*$",
    re.IGNORECASE,
)
_UNDO_RE = re.compile(
    r"^\s*(scratch that|undo that|take that back)[.!]?\s*$", re.IGNORECASE
)


class StagedAction(Enum):
    """What an utterance means while staged mode is active."""

    STAGE = "stage"        # ordinary dictation → append to the buffer
    COMMIT = "commit"      # type the buffer into the focused app and clear it
    DISCARD = "discard"    # drop everything pending
    UNDO = "undo"          # drop the last staged chunk


@dataclass
class CommitResult:
    """The outcome of a commit attempt."""

    text: str
    committed: bool

    @property
    def is_empty(self) -> bool:
        return not self.committed


def classify(text: str, *, spoken_commands: bool) -> StagedAction:
    """What does this utterance mean in staged mode?

    With ``spoken_commands`` off, everything is :attr:`StagedAction.STAGE` — the
    buffer can then only be committed by an explicit action, which is the default
    precisely because a spoken commit can be triggered by a mis-transcription.

    ``undo`` is recognised either way: it only ever *removes* pending text, so the
    failure mode of a false positive is one repeated sentence, not text typed into
    a terminal.
    """
    if _UNDO_RE.match(text or ""):
        return StagedAction.UNDO
    if not spoken_commands:
        return StagedAction.STAGE
    if _COMMIT_RE.match(text or ""):
        return StagedAction.COMMIT
    if _DISCARD_RE.match(text or ""):
        return StagedAction.DISCARD
    return StagedAction.STAGE


def join_chunks(chunks: list[str]) -> str:
    """Join staged bursts the way successive dictations would have been typed.

    Mirrors `postprocess/spacing.py`: one separating space, suppressed before
    closing punctuation, so a staged burst reads identically to an unstaged one.
    """
    out = ""
    for chunk in chunks:
        piece = chunk.strip()
        if not piece:
            continue
        if not out:
            out = piece
            continue
        if piece[0] in ",.;:!?)]}":
            out += piece
        else:
            out += " " + piece
    return out


@dataclass
class StagedBuffer:
    """Pending dictation, awaiting review.

    Chunks are kept separately rather than as one string so "scratch that" can
    remove exactly the last burst — which is what the user means by it, and what
    a single concatenated string cannot support.
    """

    chunks: list[str] = field(default_factory=list)

    # ---- state ----

    @property
    def is_empty(self) -> bool:
        return not any(c.strip() for c in self.chunks)

    @property
    def text(self) -> str:
        """Everything pending, as it would be typed."""
        return join_chunks(self.chunks)

    def preview(self, *, max_chars: int = 240) -> str:
        """What the overlay shows. Truncated from the *left*.

        The tail is where the words you just said are, and that is what you are
        checking; an ellipsis at the front says plainly that there is more above.
        """
        full = self.text
        if len(full) <= max_chars:
            return full
        return "…" + full[-(max_chars - 1):]

    # ---- transitions ----

    def stage(self, text: str) -> None:
        """Add one burst. Blank input is not a chunk — it would make undo a no-op."""
        if text and text.strip():
            self.chunks.append(text)

    def undo(self) -> bool:
        """Drop the most recent chunk. False when there was nothing to drop."""
        if not self.chunks:
            return False
        self.chunks.pop()
        return True

    def discard(self) -> str:
        """Drop everything, returning what was thrown away (for the notification)."""
        text = self.text
        self.chunks.clear()
        return text

    def commit(self) -> CommitResult:
        """Take the pending text and clear the buffer.

        An empty commit returns ``committed=False`` rather than injecting "" — the
        caller must be able to tell "nothing was pending" from "typed nothing",
        because the first deserves a message and the second is a bug.
        """
        text = self.text
        if not text:
            return CommitResult(text="", committed=False)
        self.chunks.clear()
        return CommitResult(text=text, committed=True)


def describe(buffer: StagedBuffer) -> str:
    """One line for `yazses staged status` and the tray tooltip."""
    if buffer.is_empty:
        return "Staged mode: nothing pending."
    words = len(buffer.text.split())
    bursts = len([c for c in buffer.chunks if c.strip()])
    return (
        f"Staged mode: {words} word{'s' if words != 1 else ''} pending "
        f"in {bursts} burst{'s' if bursts != 1 else ''} — "
        "`yazses staged commit` to type it, `yazses staged discard` to drop it."
    )
