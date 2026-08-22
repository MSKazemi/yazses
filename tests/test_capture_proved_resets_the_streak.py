"""A burst the recogniser understood proves the mic works, even when nothing is typed.

Found running the product (2026-08-20). `yazses status` on a daemon up nine hours:

    typed:    0 of 5 recent bursts (0%)
    ⚠ mic:    2 silent clips in a row — run `yazses audio status`

The microphone was fine. `daemon.log` for those five bursts reads: one empty decode
(19:41), then three bursts transcribed at levels 0.0118 / 0.0057 / 0.0092 while the
command key was held — each ending `Command mode: no command matched N-char phrase;
ignoring (not typed)` — and one silent discard (20:38). Three demonstrations that
capture works, an hour apart, and the streak never noticed any of them.

The reset fired only for a burst with `raw_text` **and no discard reason at all**. A
command-mode burst sets `discard_reason = "command_unmatched"`, so it counted as
neither a success nor a discard: the streak froze rather than clearing. The two real
discards were therefore reported as consecutive across an hour that contained three
good captures.

That is not cosmetic. At `silent_streak_threshold` (default 3) the next discard pops a
desktop toast telling the user their microphone stopped working, and with
`auto_heal_device` on the daemon switches the capture device — acting on evidence that
is stale and already contradicted.

The fix is to ask the question the streak actually asks. Most discard reasons are set
*after* a transcript exists and decide only where the text goes; those prove capture as
well as typing does. `silent`/`empty`/`hallucination`/`post_filter`/`cocktail_gated` are
the ones that say something about the audio itself, and they stay out.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from yazses.audio.device_monitor import (
    CAPTURE_DOUBTING_DISCARDS,
    CAPTURE_PROVING_DISCARDS,
    SilentStreakTracker,
    capture_proved,
)

DAEMON_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "yazses" / "core" / "daemon.py"


def _discard_reasons_in_source() -> set[str]:
    """Every literal assigned to ``event["discard_reason"]`` in the daemon.

    Derived from the source rather than listed here on purpose: a hand-written copy of
    a set is the thing that goes stale, and this suite exists because two sets one
    condition apart disagreed.
    """
    tree = ast.parse(DAEMON_SRC.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Constant) or not isinstance(node.value.value, str):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.value, ast.Name)
                and target.value.id == "event"
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "discard_reason"
            ):
                found.add(node.value.value)
    return found


def test_the_source_scan_actually_finds_something():
    """A guard that iterates is green on an empty collection; prove it is not empty."""
    reasons = _discard_reasons_in_source()
    assert len(reasons) >= 10, reasons
    assert "command_unmatched" in reasons
    assert "silent" in reasons


def test_every_discard_reason_is_classified():
    """A new discard reason must be judged, not silently default to one side."""
    unclassified = _discard_reasons_in_source() - CAPTURE_PROVING_DISCARDS - CAPTURE_DOUBTING_DISCARDS
    assert not unclassified, (
        f"{sorted(unclassified)} is set in daemon.py but classified in neither "
        "CAPTURE_PROVING_DISCARDS nor CAPTURE_DOUBTING_DISCARDS. Decide whether it "
        "proves the microphone worked (a transcript existed and a policy declined to "
        "type it) or casts doubt on the audio, and add it to that set."
    )


def test_the_two_sets_are_disjoint():
    assert not (CAPTURE_PROVING_DISCARDS & CAPTURE_DOUBTING_DISCARDS)


def test_typed_is_proof():
    assert capture_proved(None) is True
    assert capture_proved("") is True


@pytest.mark.parametrize("reason", sorted(CAPTURE_PROVING_DISCARDS))
def test_a_transcribed_burst_that_was_not_typed_still_proves_capture(reason):
    assert capture_proved(reason) is True


@pytest.mark.parametrize("reason", sorted(CAPTURE_DOUBTING_DISCARDS))
def test_the_audio_quality_reasons_are_not_proof(reason):
    assert capture_proved(reason) is False


def test_an_unknown_reason_defaults_to_not_proof():
    """The safe direction: a forgotten reason leaves the guard sensitive."""
    assert capture_proved("something_invented_next_year") is False


def test_the_hallucination_guard_is_not_proof():
    """Explicit, because it is the tempting one: it *has* a transcript.

    The hallucination guard fires precisely when non-speech decoded to fabricated
    words, which is the symptom a silent streak exists to catch. Counting it as proof
    would let a dead microphone reset the guard watching it.
    """
    assert capture_proved("hallucination") is False


def test_the_measured_sequence_from_the_machine_that_found_this():
    """Replay the five real bursts; the streak must read 1, not 2.

    Order and levels from `daemon.log`, 2026-08-20 19:41 → 21:12.
    """
    tracker = SilentStreakTracker()

    # 19:41:44 — Transcribed 2.2s audio, level 0.0042, then "Empty transcription".
    tracker.record_silent()
    assert tracker.streak == 1

    # 20:37:33 (level 0.0118), 20:38:26 (0.0057), 21:12:09 (0.0092) — all transcribed
    # under the command key, none matched a command, none typed.
    for reason in ("command_unmatched", "command_unmatched"):
        if capture_proved(reason):
            tracker.record_success()
    assert tracker.streak == 0, "a burst the recogniser understood must clear the streak"

    # 20:38:26 — Silent audio, level 0.0000.
    tracker.record_silent()

    if capture_proved("command_unmatched"):  # 21:12:09, the last burst
        tracker.record_success()

    assert tracker.streak == 0
    assert not tracker.should_notify(3)


# --- the wiring, not just the classifier -------------------------------------------
#
# The pure tests above pass whether or not `core/daemon.py` ever calls `capture_proved`.
# These drive a real burst through `_on_hold_end` so the reset site is covered too.

import numpy as np  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.core.daemon import Daemon  # noqa: E402
from yazses.platform import get_platform  # noqa: E402


class _FakeRecorder:
    """Loud enough to clear any gate: the audio path is not what is under test."""

    current_device_name = "AT Translated Set 2 microphone"

    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *args, **kwargs):
        return self.text


class _Injector:
    def __init__(self):
        self.injected: list[str] = []

    def inject(self, text):
        self.injected.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _daemon():
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = True
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    d._injector = _Injector()
    d._state.target_ok = True
    return d


def _command_burst(d, text):
    d._command_mode = True
    d._engine.text = text
    d._on_hold_end()


def test_an_unmatched_command_burst_clears_a_standing_streak():
    """The live regression, end to end through `_on_hold_end`.

    Reverting the reset condition to `not event.get("discard_reason")` must turn this
    red — that is the whole point of driving the daemon rather than the classifier.
    """
    d = _daemon()
    d._note_silent_discard()
    d._note_silent_discard()
    assert d._silent_streak.streak == 2

    # A phrase the recogniser understood perfectly and no command grammar matches.
    _command_burst(d, "the quick brown fox jumped over it")

    assert d._silent_streak.streak == 0, (
        "a burst transcribed under the command key left the streak standing — "
        "`yazses status` would go on reporting silent clips with a working mic"
    )
    assert d._state.silent_streak == 0, "the IPC-visible copy must clear too"


def test_a_silent_burst_still_counts():
    """The guard must stay sensitive; this is the failure it exists for."""
    d = _daemon()
    d._recorder = _FakeRecorder(np.zeros(16000, dtype="float32"))

    _command_burst(d, "")

    assert d._silent_streak.streak == 1
