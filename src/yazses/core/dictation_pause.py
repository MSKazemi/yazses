"""Pause and resume dictation: the state and its rules (pure) -- ADR-037, **Proposed**.

**Not wired.** Nothing in the package imports this module yet: there is no IPC method, CLI
command, tray entry or config key, and the daemon behaves exactly as before. The rules are
written down and tested first so the maintainer can approve them before any public surface
is added (``design/adr/adr-037-dictation-pause.md``).

The pause is a flag *beside* the daemon's state, not a state of its own: a burst, a meeting
or a read-back overwrites :class:`~yazses.platform.base.TrayState` and would silently lift a
pause stored there. ``TrayState.PAUSED`` is only what :func:`visible_state` reports while the
daemon would otherwise be idle.

While paused, every path in :data:`REFUSED_WHILE_PAUSED` is refused. This is not a
microphone mute: a meeting and the hands-free control inputs keep listening.

A pause can land between "may I record?" and the microphone opening, or in the middle of a
recording. So :meth:`DictationPause.admit` returns an :class:`Admission`, and the caller asks
:meth:`DictationPause.still_allowed` before it uses what it captured. A pause in between
makes the answer False for good, even if a resume has followed.

Thread-safe: a pause arrives on the IPC thread while a hotkey, switch or camera thread asks
to record.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum

from yazses.platform.base import TrayState
from yazses.system.uptime import monotonic_including_suspend


class CapturePath(str, Enum):
    """Every way the daemon is asked to listen or to type. A new one must be classified."""

    HOTKEY = "hotkey"  # the dictation key: hold, toggle, or a tap that latches (autostop)
    COMMAND_KEY = "command_key"
    SWITCH_HOLD = "switch_hold"  # an EMG, face or biosignal switch held to talk or command
    WAKE_WORD = "wake_word"  # no daemon path today
    VOCAL_MORSE = "vocal_morse"  # opens a microphone and types what is hummed
    PUNCH_IN = "punch_in"  # re-records a phrase and retypes the last burst
    ASK_HUMAN = "ask_human"  # an agent asks for a spoken answer over MCP
    HELD_RELEASE = "held_release"  # a switch's "confirm", which types held dictation
    MEETING = "meeting"  # started and stopped explicitly; has its own stream
    HANDSFREE_CONTROL = "handsfree_control"  # pointer, gesture, mouth switch, switch intents
    EXPLICIT_TEXT = "explicit_text"  # IPC `inject`, `staged commit`, `send_to`
    MIC_SETUP = "mic_setup"  # re-calibration and enrolment, asked for by the user


REFUSED_WHILE_PAUSED: frozenset[CapturePath] = frozenset(
    {
        CapturePath.HOTKEY,
        CapturePath.COMMAND_KEY,
        CapturePath.SWITCH_HOLD,
        CapturePath.WAKE_WORD,
        CapturePath.VOCAL_MORSE,
        CapturePath.PUNCH_IN,
        CapturePath.ASK_HUMAN,
        CapturePath.HELD_RELEASE,
    }
)

#: Listed rather than derived, so a new :class:`CapturePath` belongs to neither set until
#: somebody decides, and the tests fail until then.
UNAFFECTED_BY_PAUSE: frozenset[CapturePath] = frozenset(
    {
        CapturePath.MEETING,
        CapturePath.HANDSFREE_CONTROL,
        CapturePath.EXPLICIT_TEXT,
        CapturePath.MIC_SETUP,
    }
)

#: Refusals the user caused with their own body, where silence reads as "dictation broke".
#: The others answer their caller (an IPC reply) or never open a stream at all.
_ANNOUNCED: frozenset[CapturePath] = frozenset(
    {
        CapturePath.HOTKEY,
        CapturePath.COMMAND_KEY,
        CapturePath.SWITCH_HOLD,
        CapturePath.HELD_RELEASE,
    }
)


class InFlight(str, Enum):
    """What happens to the dictation burst that is open when a pause arrives."""

    NONE = "none"
    DISCARD = "discard"  # still recording: drop the audio, transcribe and type nothing
    FINISH = "finish"  # the user already ended it: let it be transcribed and typed


def in_flight_action(state: TrayState, *, ready: bool) -> InFlight:
    """The fate of the open burst, judged from the daemon's state when the pause lands.

    ``LOADING`` with ``ready`` is a finished burst waiting for an idle-unloaded model to come
    back; without it the daemon is starting up and there is no burst. A recording that does
    not move the state (``ask_human``, Punch-In) is stopped by its stale :class:`Admission`.
    """
    if state is TrayState.RECORDING:
        return InFlight.DISCARD
    if state in (TrayState.TRANSCRIBING, TrayState.INJECTING):
        return InFlight.FINISH
    if state is TrayState.LOADING and ready:
        return InFlight.FINISH
    return InFlight.NONE


def visible_state(state: TrayState, *, paused: bool) -> TrayState:
    """The state to report. ``PAUSED`` replaces ``IDLE`` and nothing else.

    Every other state names something still happening (a meeting being recorded, text being
    typed, a remote session, an error) that a pause must not hide.
    """
    if paused and state is TrayState.IDLE:
        return TrayState.PAUSED
    return state


@dataclass(frozen=True)
class Admission:
    """The answer to one :meth:`DictationPause.admit`."""

    path: CapturePath
    allowed: bool
    #: True for the first refusal of this pause that the user should be told about.
    announce: bool
    #: How many pauses had begun when this was decided.
    epoch: int


class DictationPause:
    """Whether dictation is paused. Held in memory: a restarted daemon is not paused.

    Nothing resumes by itself, and :meth:`resume` starts nothing: a key held across a resume
    was refused when it went down, so the user presses it again.
    """

    def __init__(self, clock: Callable[[], float] = monotonic_including_suspend) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._since: float | None = None
        self._epoch = 0
        self._announced = False

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._since is not None

    def paused_for_s(self) -> float | None:
        """Seconds since the pause began, or None while not paused."""
        with self._lock:
            if self._since is None:
                return None
            return max(0.0, self._clock() - self._since)

    def pause(self) -> bool:
        """Pause. True if this call changed anything; a repeat keeps the first start time."""
        with self._lock:
            if self._since is not None:
                return False
            self._since = self._clock()
            self._epoch += 1
            self._announced = False
            return True

    def resume(self) -> bool:
        """Resume. True if this call changed anything."""
        with self._lock:
            if self._since is None:
                return False
            self._since = None
            return True

    def admit(self, path: CapturePath) -> Admission:
        """May ``path`` start now?"""
        with self._lock:
            allowed = self._since is None or path not in REFUSED_WHILE_PAUSED
            announce = not allowed and path in _ANNOUNCED and not self._announced
            if announce:
                self._announced = True
            return Admission(path, allowed, announce, self._epoch)

    def still_allowed(self, admission: Admission) -> bool:
        """May what ``admission`` started still be used? False once a pause has begun since.

        Asked after the microphone opens and again when the burst is claimed for
        transcription. Always True for an admitted path that a pause does not cover.
        """
        if not admission.allowed:
            return False
        if admission.path not in REFUSED_WHILE_PAUSED:
            return True
        with self._lock:
            return admission.epoch == self._epoch
