"""Toggle dictation: press once to start, press again to stop (pure) -- issue #869.

Hold-to-talk asks the user to keep a key down for the whole sentence. For someone with a
motor disability or pain that is the hard part, so ``[hotkey] mode = "toggle"`` turns the
same key into a latch, like "toggle run" next to "hold to run" in a game:

* the first press starts a recording, and its release does nothing;
* the next press ends that recording and the text is transcribed and typed, exactly as a
  hold-to-talk release would; its release does nothing either;
* ``[audio] max_record_seconds`` stays the safety cut-off: a recording left latched is
  ended at that age as if the key had been pressed (0 disables the cap, as it does for
  the recorder itself).

**Only presses count, and each physical press counts once.** The hotkey backends already
collapse key auto-repeat into a single start (``hotkeys/evdev_hold.py``,
``platform/*/hotkey.py``); :meth:`ToggleTurn.press` is idempotent on top of that, so a
duplicate key-down without a key-up in between -- an auto-repeat that got through, a
second keyboard reporting the same key -- is ignored rather than ending the turn it just
started.

**A press while the daemon is busy is ignored.** A press that lands while the previous
dictation is still being transcribed or typed (or anything else that is not idle and not
the latched recording) neither starts nor stops anything; the user presses again when the
tray is back to idle. Starting a recording on top of a transcription would mix two bursts.

**A recording that ends some other way resets the latch.** If the microphone fails to
open, the device disappears, or the daemon ends the recording through any path but this
one, the caller says so with :meth:`ToggleTurn.cancel` (or :meth:`press` notices that the
daemon is no longer recording), and the next press starts a fresh recording instead of
"stopping" one that is already gone.

There is no voice "stop" for a latched recording: speech is only transcribed once the
recording ends, so nothing spoken can end it. The second press and the cap are the ways out.

This module has no imports from the rest of the package and no clock of its own: every
method takes ``now`` (monotonic seconds), so tests drive time directly. Thread-safe: the
hotkey thread (press/release) and the daemon's cap watcher (:meth:`expired`) share one lock
and every transition that ends a turn happens under it, so a turn is ended exactly once.
"""
from __future__ import annotations

import threading
from enum import Enum

#: The values ``[hotkey] mode`` accepts. ``"hold"`` is the shipped default and is the
#: hold-to-talk behaviour the daemon has always had.
MODES = ("hold", "toggle")
DEFAULT_MODE = "hold"


def normalise_mode(value: object) -> str:
    """The mode a config value names, or ``"hold"`` for anything unrecognised. Pure.

    Case and surrounding whitespace are forgiven ("Toggle " is toggle). Anything else falls
    back to hold-to-talk, the behaviour an install had before this key existed, rather than
    leaving the user with a hotkey that does something they did not choose.
    """
    text = str(value).strip().lower() if isinstance(value, str) else ""
    return text if text in MODES else DEFAULT_MODE


class Press(str, Enum):
    """What the daemon does with one key-down."""

    START = "start"    # begin a recording, exactly as a hold-to-talk key-down does
    STOP = "stop"      # end the latched recording, exactly as a hold-to-talk release does
    IGNORE = "ignore"  # nothing: an auto-repeat, or a press while the daemon is busy


class ToggleTurn:
    """The press-to-start, press-to-stop latch for the dictation hotkey. Pure.

    ``max_seconds`` is ``[audio] max_record_seconds``; ``0`` (or less) means no cap.
    """

    def __init__(self, max_seconds: float = 300) -> None:
        self._max_s = float(max_seconds) if max_seconds and max_seconds > 0 else 0.0
        self._lock = threading.Lock()
        self._down = False
        self._latched = False
        self._started_at = 0.0

    @property
    def latched(self) -> bool:
        """True while a recording this latch started is open."""
        return self._latched

    @property
    def max_seconds(self) -> float:
        return self._max_s

    def press(self, now: float, *, recording: bool, busy: bool) -> Press:
        """The hotkey went down.

        ``recording`` is whether the daemon is recording right now; ``busy`` is whether it
        is doing something that a new recording must not start on top of (transcribing,
        typing, reading back, a meeting...). The caller acts on the answer.
        """
        with self._lock:
            if self._down:
                return Press.IGNORE  # a second key-down with no key-up: auto-repeat
            self._down = True
            if self._latched:
                self._latched = False
                if recording:
                    return Press.STOP
                # The recording this latch opened already ended another way; this press
                # is a fresh start, judged below like any other.
            if busy or recording:
                return Press.IGNORE
            self._latched = True
            self._started_at = now
            return Press.START

    def release(self, now: float) -> None:
        """The hotkey came up. A release never starts or ends anything in toggle mode."""
        with self._lock:
            self._down = False

    def expired(self, now: float) -> bool:
        """True once, when a latched recording reaches the cap; the caller ends it.

        The latch is cleared under the lock, so a second press racing the cap cannot also
        end the same recording: whichever arrives first wins and the other is a no-op.
        """
        with self._lock:
            if not self._latched or self._max_s <= 0:
                return False
            if (now - self._started_at) < self._max_s:
                return False
            self._latched = False
            return True

    def cancel(self) -> None:
        """Drop the latch without ending anything (the recording ended, or never began)."""
        with self._lock:
            self._latched = False
