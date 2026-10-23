"""Mouth-Sound Switch Access is reachable -- single-switch scanning, armed by the existing
hands-free toggle (WIRE-MOUTHSWITCH-001, #164, ADR-v2-097).

Six claims:

* **A default install is unchanged.** `[mouthswitch]` ships off, so the daemon imports nothing
  from `yazses.mouthswitch`, asks for no pointer sink, opens no microphone, and `status`
  carries `"mouthswitch": None`.
* **The microphone is open only while armed.** Enabling the feature builds a runner but opens
  nothing; `handsfree resume` opens the stream, `handsfree pause` (and so the spoken stop
  phrase) and a pause of the global gate close it, and so does shutdown.
* **A pop starts the scan; a click runs the item lit when the click began** -- through the
  existing command path (activation policy → grammar → dispatcher) for a command item, one
  call on the existing pointer sink for "click" / "scroll". The scan then carries on with the
  selected item still lit, so a second click repeats it without a pop.
* **A select comes only from a detected click inside a running scan** (ADR-021): a click with
  no scan, a click after a pop stopped the scan, a click while dictation is busy and a
  stretch of the speech stand-in run nothing.
* **Seen or heard, never neither.** Without the overlay that draws the scan, each step is
  announced instead -- an earcon cue and/or the item's name in the offline voice -- from the
  same timeline a click selects from, and an item stays lit until its name has been said,
  then through the detector's post-voice deafness, then for a full dwell to click.
* **No highlight and no announcement, no switch.** With neither, the feature refuses to build
  and `handsfree resume` says why.

Detector thresholds are synthetic-only (`tests/test_mouthswitch_detect.py`); the end-to-end
case below uses the same synthetic click and pop, not recorded sounds.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
import types
from dataclasses import dataclass

import numpy as np
import pytest

from tests.pointer_fake import FakePointerSink, PointerActionKind
from tests.synthetic_voice import SR
from tests.test_dormant_features_stay_unimported import started, tripwire  # noqa: F401
from yazses.config import Config
from yazses.ipc.protocol import Request
from yazses.platform import get_platform
from yazses.platform.base import TrayState
from yazses.pointer.base import PointerButton, PointerCapabilities
from yazses.system.features import feature_status, unwired_slugs


class FakeRecorder:
    """Stands in for `AudioRecorder`: records start/stop, and pushes chunks on request."""

    instances: list[FakeRecorder] = []

    def __init__(self, on_chunk) -> None:
        self.on_chunk = on_chunk
        self.started = 0
        self.stopped = 0
        FakeRecorder.instances.append(self)

    @property
    def open(self) -> bool:
        return self.started > self.stopped

    def start(self) -> None:
        self.started += 1

    def stop(self):
        self.stopped += 1
        return np.zeros(0, dtype=np.float32)


@dataclass(frozen=True)
class Ev:
    """A detector event as the runner reads it: onset in stream seconds, kind, action."""

    t_s: float
    kind: str
    action: str | None


class FakeDetector:
    """Emits the events a test queues on the next ``feed``; a reset drops them."""

    def __init__(self) -> None:
        self.pending: list[Ev] = []
        self.resets = 0

    def emit(self, *events: Ev) -> None:
        self.pending.extend(events)

    def feed(self, chunk):
        out, self.pending = self.pending, []
        return out

    def reset(self) -> None:
        self.resets += 1
        self.pending = []


def pop_at(t: float) -> Ev:
    return Ev(t, "pop", "toggle")


def click_at(t: float) -> Ev:
    return Ev(t, "click", "select")


class Clock:
    """The runner's clock, moved by hand."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


class Drive:
    """Feeds a runner contiguous silence in which clock time equals stream time.

    The runner was started at clock 0, so an event's ``t_s`` is also its clock onset.
    """

    def __init__(self, runner, detector: FakeDetector, clock: Clock) -> None:
        self.runner = runner
        self.detector = detector
        self.clock = clock
        self.fed = 0

    def advance(self, seconds: float, *events: Ev) -> None:
        self.detector.emit(*events)
        n = int(round(seconds * SR))
        self.fed += n
        self.clock.t = self.fed / SR
        self.runner.process(np.zeros(n, dtype=np.float32), self.clock.t)


def _runner(items=None, sink=None, run_command=None, **kwargs):
    from yazses.mouthswitch.runtime import MouthSwitchRunner
    from yazses.mouthswitch.scanner import DEFAULT_SCAN_ITEMS, parse_scan_items

    made: list[FakeRecorder] = []

    def factory(on_chunk):
        rec = FakeRecorder(on_chunk)
        made.append(rec)
        return rec

    ran: list[str] = []

    def record(phrase: str):
        ran.append(phrase)
        return types.SimpleNamespace(executed=True)

    parsed, _ = parse_scan_items(list(items or DEFAULT_SCAN_ITEMS))
    detector = kwargs.pop("detector", None) or FakeDetector()
    sink = sink or FakePointerSink()
    clock = Clock()
    runner = MouthSwitchRunner(
        parsed, recorder_factory=factory, run_command=run_command or record, sink=sink,
        sample_rate=SR, interval_s=1.0, clock=clock, detector=detector, thread=False,
        **kwargs,
    )
    runner.test_clock = clock  # type: ignore[attr-defined]
    return runner, sink, made, ran, detector


def _started(**kwargs):
    runner, sink, made, ran, detector = _runner(**kwargs)
    assert runner.start() == (True, "")
    return runner, sink, made, ran, Drive(runner, detector, runner.test_clock)


def _presses(sink: FakePointerSink):
    return [a for a in sink.actions if a.kind is PointerActionKind.BUTTON_PRESS]


def _scrolls(sink: FakePointerSink):
    return [a for a in sink.actions if a.kind is PointerActionKind.SCROLL]


# --------------------------------------------------------------------------- #
# Registry honesty
# --------------------------------------------------------------------------- #
def test_mouthswitch_is_no_longer_advertised_as_unwired():
    assert "mouthswitch" not in unwired_slugs()
    feature = next(f for f in feature_status(Config()) if f.slug == "mouthswitch")
    assert feature.wired is True


def test_the_registry_describes_single_switch_scanning_not_pop_to_advance():
    from yazses.system.features import _EXAMPLES, _registry

    definition = next(d for d in _registry() if d.slug == "mouthswitch")
    assert "'pop' = advance" not in definition.why
    assert "handsfree resume" in definition.why and "overlay" in definition.why
    assert "synthetic" in definition.why
    assert "move the highlight" not in _EXAMPLES["mouthswitch"]
    # What it does now: keeps scanning after a select, and is heard where it cannot be seen.
    assert "repeats" in definition.why
    assert "announced" in definition.why and "needs the overlay" not in definition.why


# --------------------------------------------------------------------------- #
# The scan and the select, on the runner alone
# --------------------------------------------------------------------------- #
def test_a_pop_starts_the_scan_and_a_click_runs_the_lit_command():
    runner, _sink, _made, ran, d = _started()
    d.advance(0.3, pop_at(0.1))              # the scan starts at 0.3 s, "enter" lit
    assert runner.view()["scanning"] is True
    d.advance(1.5)                        # now 1.8 s: one step on, "undo" lit
    assert runner.view()["index"] == 1
    d.advance(0.3, click_at(1.9))
    assert ran == ["undo"]
    # The scan carries on, with the highlight still on what was just selected.
    view = runner.view()
    assert view["scanning"] is True and view["index"] == 1
    assert runner.selections == 1 and runner.last_selected == "undo"


def test_after_a_selection_a_second_click_repeats_it_without_a_pop():
    """Scrolling down twice used to need pop, click, pop, click."""
    runner, sink, _made, ran, d = _started(items=["enter", "scroll down"])
    d.advance(0.3, pop_at(0.1))              # scan from 0.3 s: "enter", then "scroll down"
    d.advance(1.2)                        # now 1.5 s: "scroll down" lit (from 1.3 s)
    d.advance(0.3, click_at(1.6))            # selected at 1.8 s; it stays lit until 2.8 s
    d.advance(0.5, click_at(2.1))            # a second click, no pop: scrolls again
    assert [(a.x, a.y) for a in _scrolls(sink)] == [(0.0, 3.0), (0.0, 3.0)]
    assert runner.selections == 2 and runner.view()["scanning"] is True
    assert ran == []


def test_a_continuing_scan_stops_after_three_passes_with_no_selection():
    runner, _sink, _made, ran, d = _started()
    d.advance(0.3, pop_at(0.1))
    d.advance(1.5)
    d.advance(0.3, click_at(1.9))            # "undo", selected at 2.1 s
    span = 3 * 5 * 1.0                     # 3 passes x 5 items x 1.0 s
    d.advance(span - 0.2)                   # now 2.1 + span - 0.2: still scanning
    assert runner.view()["scanning"] is True
    d.advance(0.3)                          # past three passes since the selection
    assert runner.view()["scanning"] is False
    assert ran == ["undo"]


def test_a_pop_stops_a_scan_that_has_already_selected():
    runner, _sink, _made, ran, d = _started()
    d.advance(0.3, pop_at(0.1))
    d.advance(1.5)
    d.advance(0.3, click_at(1.9))
    d.advance(0.5, pop_at(2.3))
    assert runner.view()["scanning"] is False
    d.advance(0.5, click_at(2.9))
    assert ran == ["undo"]


def test_the_click_selects_what_was_lit_when_it_began_not_when_it_was_heard():
    runner, _sink, _made, ran, d = _started()
    d.advance(0.3, pop_at(0.1))              # scan from 0.3 s
    d.advance(1.9)                        # now 2.2 s
    # The click began at 2.25 s ("undo" lit: 1.95 s into the scan) and the detector reports
    # it at 2.4 s, when "scroll up" is already lit.
    d.advance(0.2, click_at(2.25))
    assert ran == ["undo"]


def test_a_second_pop_stops_the_scan_and_a_later_click_runs_nothing():
    runner, _sink, _made, ran, d = _started()
    d.advance(0.3, pop_at(0.1))
    d.advance(0.5, pop_at(0.6))
    assert runner.view()["scanning"] is False
    d.advance(0.5, click_at(1.0))
    assert ran == []


def test_a_click_with_no_scan_running_does_nothing():
    """The keyboard-tap case: a stray impulse outside a scan must cost nothing."""
    runner, sink, _made, ran, d = _started()
    d.advance(0.5, click_at(0.2))
    d.advance(0.5, click_at(0.7))
    assert ran == [] and sink.actions == []
    assert runner.selections == 0


def test_a_sound_the_switch_does_not_map_does_nothing():
    runner, sink, _made, ran, d = _started()
    d.advance(0.5, Ev(0.2, "sh", None), Ev(0.3, "pop", "advance"))
    assert runner.view()["scanning"] is False
    assert ran == [] and sink.actions == []


def test_the_pointer_items_use_the_existing_sink():
    runner, sink, _made, ran, d = _started()
    d.advance(0.3, pop_at(0.1))              # scan from 0.3 s; "click" is item 4
    d.advance(4.4)                        # now 4.7 s
    d.advance(0.3, click_at(4.8))            # 4.5 s into the scan: "click" (reported at 5.0 s)
    assert ran == []
    assert [a.button for a in _presses(sink)] == [PointerButton.LEFT]

    # The scan carries on from "click", re-lit at 5.0 s for one step: then "enter" (6.0 s),
    # "undo" (7.0 s), "scroll up" (8.0 s), "scroll down" (9.0 s).
    d.advance(4.3)                        # now 9.3 s
    d.advance(0.3, click_at(9.4))            # began on "scroll down" (reported at 9.6 s)
    assert [(a.x, a.y) for a in _scrolls(sink)] == [(0.0, 3.0)]


def test_scroll_up_scrolls_toward_the_top():
    runner, sink, _made, _ran, d = _started(items=["scroll up"])
    d.advance(0.3, pop_at(0.1))
    d.advance(0.3, click_at(0.4))
    assert [(a.x, a.y) for a in _scrolls(sink)] == [(0.0, -3.0)]


def test_nothing_is_heard_while_dictation_is_busy():
    busy = {"on": False}
    runner, _sink, _made, ran, d = _started(busy=lambda: busy["on"])
    d.advance(0.3, pop_at(0.1))
    assert runner.view()["scanning"] is True
    busy["on"] = True
    d.advance(0.3, click_at(0.4))            # dropped with the chunk, and the scan stops
    assert runner.view()["scanning"] is False
    busy["on"] = False
    d.advance(0.3, click_at(0.7))
    assert ran == []


def test_a_pause_of_the_global_gate_closes_the_microphone_quietly():
    paused = {"on": False}
    told: list[str] = []
    runner, _sink, _made, ran, d = _started(stop_requested=lambda: paused["on"],
                                           on_fault=told.append)
    d.advance(0.3, pop_at(0.1))
    paused["on"] = True
    d.advance(0.3, click_at(0.4))
    assert runner.active is False and runner.view()["scanning"] is False
    assert ran == [] and told == []      # a pause is not a fault to complain about
    assert runner.start() == (True, "")  # and an explicit resume brings it back


def test_a_broken_pointer_backend_stops_the_switch_and_says_so_once():
    told: list[str] = []
    runner, sink, _made, _ran, d = _started(items=["click"], on_fault=told.append)
    sink.fail_with()
    d.advance(0.3, pop_at(0.1))
    d.advance(0.3, click_at(0.4))
    assert runner.fault.startswith("pointer output failed")
    assert len(told) == 1


def test_a_command_that_raises_does_not_stop_the_switch():
    def boom(_phrase):
        raise RuntimeError("dispatch failed")

    runner, _sink, _made, _ran, d = _started(run_command=boom)
    d.advance(0.3, pop_at(0.1))
    d.advance(0.3, click_at(0.4))
    assert runner.fault == "" and runner.active


def test_stop_closes_the_stream_and_ends_the_scan():
    runner, sink, made, _ran, d = _started()
    d.advance(0.3, pop_at(0.1))
    runner.close()
    assert not made[0].open and runner.view()["scanning"] is False
    assert sink.closed


# --------------------------------------------------------------------------- #
# Heard, not seen: the scan announced where the overlay cannot draw it
# --------------------------------------------------------------------------- #
class Ears:
    """A fake earcon player and voice. Records what was heard, when, and what was lit then."""

    def __init__(self) -> None:
        self.runner = None
        self.cues: list[str] = []
        self.names: list[tuple[str, float, int]] = []
        self.cancels = 0

    def cue(self, event: str) -> None:
        self.cues.append(event)

    def speak(self, text: str) -> None:
        # Asked from inside the announcement: the same scanner a click selects from.
        view = self.runner.view()
        self.names.append((text, self.runner.test_clock.t, view["index"]))

    def cancel(self) -> None:
        self.cancels += 1

    def heard_before(self, t: float) -> str:
        """The last name heard at or before ``t``."""
        return [name for name, when, _ in self.names if when <= t][-1]


def _audible(duration=lambda text: 0.0, **kwargs):
    from yazses.mouthswitch.announce import ScanAnnouncer

    ears = Ears()
    announcer = ScanAnnouncer(cue=ears.cue, speak=ears.speak, cancel=ears.cancel,
                              duration_s=duration, thread=False)
    runner, _sink, _made, ran, d = _started(announcer=announcer, **kwargs)
    ears.runner = runner
    return runner, ears, ran, d


def _walk(d: Drive, until: float, chunk: float = 0.05) -> None:
    while d.clock.t + chunk <= until + 1e-9:
        d.advance(chunk)


def _deaf() -> float:
    from yazses.mouthswitch.runtime import post_voice_deaf_s

    return post_voice_deaf_s()


def _step() -> float:
    """A heard step with no long name: the 1.0 s dwell plus the detector's deafness."""
    return 1.0 + _deaf()


def test_without_the_overlay_each_step_is_announced_as_it_lights():
    runner, ears, _ran, d = _audible()
    d.advance(0.3, pop_at(0.1))           # the scan starts at 0.3 s: "enter" is heard at once
    _walk(d, 0.3 + 3 * _step() + 0.1)
    assert [name for name, _, _ in ears.names] == ["enter", "undo", "scroll up", "scroll down"]
    # Every name was said while that very item was the lit one.
    labels = [item.label for item in runner.items]
    assert all(labels[index] == name for name, _, index in ears.names)
    # A distinct cue on the first item, so the steps can be counted without a voice too.
    assert ears.cues[:4] == ["scan_first", "scan_step", "scan_step", "scan_step"]
    assert runner.view()["announce"] == "speech"


def test_the_item_heard_when_the_click_began_is_the_item_selected():
    runner, ears, ran, d = _audible()
    d.advance(0.3, pop_at(0.1))
    scroll_up_at = 0.3 + 2 * _step()       # when "scroll up" lights and is announced
    _walk(d, scroll_up_at + 0.1)
    # The click began just before that -- after "undo" was announced, before "scroll up"
    # was -- and is reported a quarter-second later, with "scroll up" lit by then.
    onset = scroll_up_at - 0.05
    d.advance(0.1, click_at(onset))
    assert ears.heard_before(onset) == "undo"
    assert ran == ["undo"]


def test_a_name_longer_than_the_dwell_holds_the_highlight_until_it_is_said():
    runner, ears, ran, d = _audible(duration=lambda text: 1.6 if text == "undo" else 0.0)
    d.advance(0.3, pop_at(0.1))
    undo_step = 1.6 + _deaf() + 1.0        # the name, the deafness, then the whole dwell
    _walk(d, 0.3 + _step() + undo_step + 0.1)
    times = {name: when for name, when, _ in ears.names}
    assert times["scroll up"] - times["undo"] >= undo_step - 0.05
    # A click that began near the end of that step -- long past the plain one -- means "undo".
    d.advance(0.1, click_at(times["undo"] + undo_step - 0.1))
    assert ran == ["undo"]


def test_a_heard_step_still_runs_after_the_name_and_the_deafness_behind_it():
    """A name shorter than the dwell: after it and the deafness, the whole dwell is left.

    The step is lit for 0.5 + deafness + 1.0, so a click most of a dwell after the
    detector hears again still selects the announced item.
    """
    runner, ears, ran, d = _audible(duration=lambda text: 0.5 if text == "undo" else 0.0)
    d.advance(0.3, pop_at(0.1))
    _walk(d, 0.3 + _step() + 0.05)
    undo_at = {name: when for name, when, _ in ears.names}["undo"]
    heard_again = undo_at + 0.5 + _deaf()  # the name has ended and the detector hears again
    _walk(d, heard_again + 0.8)
    assert runner.view()["index"] == 1     # "undo" is still the lit item
    d.advance(0.1, click_at(heard_again + 0.75))
    assert ran == ["undo"]


def test_a_long_name_still_leaves_a_full_dwell_to_click():
    """"scroll down" takes longer to say than this 1.0 s dwell: the scan slows down instead.

    After the name (the real estimate) and the deaf window behind it, a whole dwell is left,
    and a click that begins just before that dwell runs out still selects "scroll down".
    """
    from yazses.mouthswitch.announce import speech_duration_s

    runner, ears, ran, d = _audible(duration=speech_duration_s)
    dwells = runner._scanner.dwells
    k = [item.label for item in runner.items].index("scroll down")
    name_s = speech_duration_s("scroll down")
    assert name_s > 1.0                    # longer than the dwell: the case this pins
    assert dwells[k] - name_s - _deaf() == pytest.approx(1.0)
    d.advance(0.3, pop_at(0.1))            # the scan starts at 0.3 s
    lit_at = 0.3 + sum(dwells[:k])
    window_end = lit_at + dwells[k]        # the full dwell after the deafness ends here
    _walk(d, window_end - 0.05)
    assert ears.heard_before(window_end - 0.05) == "scroll down"
    d.advance(0.1, click_at(window_end - 0.03))
    assert ran == ["scroll down"]


def test_the_post_voice_window_is_the_detectors_own_constant(monkeypatch):
    """Derived, never restated: change the detector's window and the heard step follows."""
    import yazses.mouthswitch.detect as detect_mod
    from yazses.mouthswitch.runtime import post_voice_deaf_s

    assert post_voice_deaf_s() == pytest.approx(detect_mod.CONTEXT_MS / 1000.0)
    monkeypatch.setattr(detect_mod, "CONTEXT_MS", detect_mod.CONTEXT_MS + 200)
    runner, _ears, _ran, _d = _audible()
    assert runner._scanner.dwells[0] == pytest.approx(1.0 + detect_mod.CONTEXT_MS / 1000.0)


def test_a_seen_scan_keeps_its_plain_steps():
    """The overlay's scan makes no sound, so no deafness is added: dwell_s, exactly."""
    runner, _sink, _made, _ran, _d = _started()
    assert runner._scanner.dwells == (1.0,) * len(runner.items)


def test_after_a_selection_the_item_is_announced_again_and_stays_for_a_step():
    runner, ears, ran, d = _audible()
    d.advance(0.3, pop_at(0.1))
    undo_at = 0.3 + _step()                # "enter" at 0.3 s, "undo" one heard step later
    _walk(d, undo_at + 0.2)
    d.advance(0.1, click_at(undo_at + 0.15))  # selects "undo" 0.3 s after it lit
    _walk(d, undo_at + 0.3 + _step() + 0.1)
    assert ran == ["undo"]
    assert [name for name, _, _ in ears.names] == ["enter", "undo", "undo", "scroll up"]
    times = [when for name, when, _ in ears.names]
    assert times[3] - times[2] >= _step() - 1e-9  # the re-lit "undo" kept its whole step


class FakeAnnouncer:
    """Stands in for `ScanAnnouncer`; records the calls the runner makes."""

    mode = "earcon"
    can_announce = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def announcement_s(self, item) -> float:
        return 0.0

    def announce(self, item, *, first: bool) -> None:
        self.calls.append(f"announce {item.label}")

    def stop(self) -> None:
        self.calls.append("stop")

    def close(self) -> None:
        self.calls.append("close")


def test_stopping_the_scan_silences_the_announcement():
    announcer = FakeAnnouncer()
    _r, _sink, _made, _ran, d = _started(announcer=announcer)
    d.advance(0.3, pop_at(0.1))
    d.advance(0.2, pop_at(0.4))            # a second pop stops the scan
    assert announcer.calls == ["announce enter", "stop"]
    d.advance(0.5)
    assert announcer.calls == ["announce enter", "stop"]  # silence, not a stop per chunk


def test_dictation_starting_silences_the_announcement():
    busy = {"on": False}
    announcer = FakeAnnouncer()
    _r, _sink, _made, _ran, d = _started(announcer=announcer, busy=lambda: busy["on"])
    d.advance(0.3, pop_at(0.1))
    busy["on"] = True
    d.advance(0.1)
    assert announcer.calls == ["announce enter", "stop"]


def test_closing_the_switch_closes_the_announcer():
    announcer = FakeAnnouncer()
    runner, _sink, _made, _ran, d = _started(announcer=announcer)
    d.advance(0.3, pop_at(0.1))
    runner.close()
    assert announcer.calls[-2:] == ["stop", "close"]


def test_with_no_announcer_the_view_says_so():
    runner, _sink, _made, _ran, _d = _started()
    assert runner.view()["announce"] == ""


# --------------------------------------------------------------------------- #
# The real detector, end to end, on synthetic sounds
# --------------------------------------------------------------------------- #
def _feed(runner, signal: np.ndarray, fed: int = 0, chunk: int = 512) -> int:
    """Feed ``signal`` in stream chunks after ``fed`` samples; the clock follows the stream."""
    for i in range(0, signal.size, chunk):
        part = signal[i:i + chunk].astype(np.float32)
        fed += part.size
        runner.test_clock.t = fed / SR
        runner.process(part, fed / SR)
    return fed


def test_a_synthetic_pop_then_click_runs_the_first_item_through_the_real_detector():
    from tests.test_mouthswitch_detect import click, placed, pop
    from yazses.mouthswitch.detect import MouthSoundDetector
    from yazses.mouthswitch.runtime import SWITCH_ACTIONS

    runner, _sink, _made, ran, _detector = _runner(
        detector=MouthSoundDetector(SR, actions=SWITCH_ACTIONS)
    )
    runner.start()
    # 0.6 s quiet, pop, 0.6 s quiet, click, 0.6 s quiet: the click begins well inside the
    # first 1.0 s step of the scan the pop started, so "enter" is the lit item.
    _feed(runner, placed(pop(), click(), gap_s=0.6))
    assert ran == ["enter"]


def test_the_speech_stand_in_selects_nothing_from_a_running_scan():
    from tests.test_mouthswitch_detect import placed, pop, speechlike
    from yazses.mouthswitch.detect import MouthSoundDetector
    from yazses.mouthswitch.runtime import SWITCH_ACTIONS

    runner, sink, _made, ran, _detector = _runner(
        detector=MouthSoundDetector(SR, actions=SWITCH_ACTIONS)
    )
    runner.start()
    fed = _feed(runner, placed(pop(), gap_s=0.6))
    # A scan is running (5 items x 1.0 s x 3 loops = 15 s) for the whole stretch of speech.
    assert runner.view()["scanning"] is True
    _feed(runner, speechlike(8.0, seed=0), fed)
    assert ran == [] and sink.actions == []


# --------------------------------------------------------------------------- #
# Build rules
# --------------------------------------------------------------------------- #
def _classify(phrase: str):
    from yazses.commands.grammar import classify

    return classify(phrase, "default", language="en")


def _build(config, **kwargs):
    from yazses.mouthswitch.runtime import build_mouthswitch

    defaults = dict(
        pointer_factory=FakePointerSink,
        recorder_factory=lambda on_chunk: FakeRecorder(on_chunk),
        run_command=lambda phrase: None,
        classify=_classify,
        highlight_available=True,
        thread=False,
    )
    defaults.update(kwargs)
    return build_mouthswitch(config, **defaults)


def _cfg(**overrides):
    cfg = Config().mouthswitch
    cfg.enabled = True
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def test_off_builds_nothing_and_asks_for_no_sink():
    asked: list[int] = []
    runtime = _build(Config().mouthswitch, pointer_factory=lambda: asked.append(1))
    assert runtime.runner is None and runtime.reason == "" and asked == []


def test_without_the_overlay_there_is_no_switch_and_the_reason_says_why():
    runtime = _build(_cfg(), highlight_available=False)
    assert runtime.runner is None
    assert "overlay" in runtime.reason and "cannot see" in runtime.reason
    assert "[earcon]" in runtime.reason and "[tts]" in runtime.reason


def test_without_the_overlay_an_announcement_lets_the_switch_run():
    from yazses.mouthswitch.announce import ScanAnnouncer

    cues: list[str] = []
    runtime = _build(_cfg(), highlight_available=False,
                     announcer=ScanAnnouncer(cue=cues.append, thread=False))
    assert runtime.available
    assert runtime.status_payload()["announce"] == "earcon"
    runtime.stop()


def test_an_announcer_that_can_make_no_sound_does_not_count():
    from yazses.mouthswitch.announce import ScanAnnouncer

    runtime = _build(_cfg(), highlight_available=False, announcer=ScanAnnouncer(thread=False))
    assert runtime.runner is None and "cannot see or hear" in runtime.reason


def test_with_the_overlay_the_announcer_is_not_used():
    from yazses.mouthswitch.announce import ScanAnnouncer

    runtime = _build(_cfg(), highlight_available=True,
                     announcer=ScanAnnouncer(cue=lambda event: None, thread=False))
    assert runtime.available and runtime.status_payload()["announce"] == ""
    runtime.stop()


def test_the_default_items_all_build_with_a_full_pointer_backend():
    runtime = _build(_cfg())
    assert runtime.available and runtime.notice == ""
    assert [i.label for i in runtime.runner.items] == [
        "enter", "undo", "scroll up", "scroll down", "click"]


def test_an_item_the_grammar_does_not_know_or_that_needs_confirmation_is_dropped():
    runtime = _build(_cfg(scan_items=["enter", "save", "make me a sandwich", "page down"]))
    assert [i.label for i in runtime.runner.items] == ["enter", "page down"]
    assert "'save' dropped" in runtime.notice and "confirmation" in runtime.notice
    assert "'make me a sandwich' dropped" in runtime.notice


def test_no_pointer_backend_drops_only_the_pointer_items():
    runtime = _build(_cfg(), pointer_factory=None)
    assert [i.label for i in runtime.runner.items] == ["enter", "undo"]
    assert "no pointer backend" in runtime.notice


def test_a_backend_without_scroll_keeps_click_and_drops_scroll():
    caps = PointerCapabilities(backend="clicky", buttons=frozenset({PointerButton.LEFT}))
    runtime = _build(_cfg(), pointer_factory=lambda: FakePointerSink(caps))
    assert [i.label for i in runtime.runner.items] == ["enter", "undo", "click"]
    assert "cannot scroll" in runtime.notice


def test_when_nothing_can_run_there_is_no_runner_and_the_sink_is_released():
    sinks: list[FakePointerSink] = []

    def factory():
        sinks.append(FakePointerSink(PointerCapabilities(backend="mute")))
        return sinks[-1]

    runtime = _build(_cfg(scan_items=["click", "save"]), pointer_factory=factory)
    assert runtime.runner is None
    assert runtime.reason.startswith("no scan item can run here")
    assert sinks and sinks[0].closed


def test_dwell_s_sets_the_scan_interval():
    runtime = _build(_cfg(dwell_s=2.0))
    assert runtime.runner.view()["interval_s"] == 2.0


# --------------------------------------------------------------------------- #
# The daemon
# --------------------------------------------------------------------------- #
def test_a_default_daemon_never_imports_the_mouth_switch(tripwire, started):  # noqa: F811
    daemon = started(Config())
    assert "mouthswitch" not in tripwire.packages()
    assert daemon._mouthswitch is None
    assert daemon._mouthswitch_payload() is None


def _overlay_on(monkeypatch) -> None:
    import yazses.core.daemon as daemon_mod

    monkeypatch.setattr(daemon_mod, "should_launch_overlay", lambda cfg, env: True)
    monkeypatch.setattr(daemon_mod, "overlay_dependency_available", lambda: True)


def test_an_enabled_daemon_imports_and_builds_it(tripwire, started, monkeypatch):  # noqa: F811
    """The positive control for the test above: the tripwire does see the import."""
    _overlay_on(monkeypatch)
    cfg = Config()
    cfg.mouthswitch.enabled = True
    daemon = started(cfg, pipeline=False)
    daemon._platform = dataclasses.replace(daemon._platform, pointer_factory=FakePointerSink)
    runtime = daemon._build_mouthswitch(cfg)
    assert "mouthswitch" in tripwire.packages()
    assert runtime is not None and runtime.available
    runtime.stop()


def _daemon(cfg: Config, sink=None):
    from yazses.core.daemon import Daemon

    platform = get_platform()
    if sink is not None:
        platform = dataclasses.replace(platform, pointer_factory=lambda: sink)
    return Daemon(config=cfg, platform=platform)


@pytest.fixture
def armed_daemon(monkeypatch):
    import yazses.core.daemon as daemon_mod

    FakeRecorder.instances.clear()
    monkeypatch.setattr(daemon_mod, "AudioRecorder", lambda **kw: FakeRecorder(kw["on_chunk"]))
    _overlay_on(monkeypatch)
    sink = FakePointerSink()
    cfg = Config()
    cfg.mouthswitch.enabled = True
    daemon = _daemon(cfg, sink)
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    daemon._state.state = TrayState.IDLE
    yield daemon, sink
    daemon._mouthswitch.stop()


def test_enabling_it_opens_no_microphone(armed_daemon):
    daemon, sink = armed_daemon
    assert daemon._mouthswitch.available
    assert FakeRecorder.instances == []
    assert sink.actions == []


def test_handsfree_resume_opens_the_microphone_and_pause_closes_it(armed_daemon):
    daemon, _sink = armed_daemon
    reply = daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    assert reply == {"ok": True, "scope": ["Mouth-Sound Switch"]}
    (rec,) = FakeRecorder.instances
    assert rec.open
    payload = daemon._mouthswitch_payload()
    assert payload is not None
    assert payload["armed"] is True and payload["scanning"] is False
    assert payload["items"] == ["enter", "undo", "scroll up", "scroll down", "click"]

    reply = daemon._handle_handsfree(Request("handsfree", {"action": "pause"}))
    assert reply == {"ok": True, "scope": ["Mouth-Sound Switch"]}
    assert not rec.open


def test_the_spoken_stop_phrase_closes_the_microphone(armed_daemon):
    daemon, _sink = armed_daemon
    daemon._config.handsfree_safety.stop_phrase = "stop pointer"  # opt-in; ships empty
    daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    (rec,) = FakeRecorder.instances
    assert daemon._try_voice_stop("stop pointer", {}) is True
    assert not rec.open


def test_the_device_monitor_never_reinits_portaudio_under_the_open_stream(armed_daemon):
    daemon, _sink = armed_daemon
    assert daemon._audio_idle() is True
    daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    assert daemon._audio_idle() is False
    daemon._handle_handsfree(Request("handsfree", {"action": "pause"}))
    assert daemon._audio_idle() is True


def test_shutdown_closes_the_stream_and_releases_the_sink(armed_daemon):
    daemon, sink = armed_daemon
    daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    (rec,) = FakeRecorder.instances
    daemon._mouthswitch.stop()
    assert not rec.open and sink.closed


def test_a_selected_command_goes_through_the_activation_policy_and_the_grammar(armed_daemon):
    daemon, _sink = armed_daemon
    dispatched: list[object] = []
    daemon._gesture_dispatch = dispatched.append  # the existing dispatcher, recorded
    runner = daemon._mouthswitch.runner
    outcome = runner._run_command("undo")
    assert outcome.executed is True
    assert [getattr(c, "action", None) for c in dispatched] == ["undo"]
    # An irreversible command is refused by the policy even if it reached the runner.
    outcome = runner._run_command("save")
    assert outcome.executed is False
    assert len(dispatched) == 1


def test_without_the_overlay_resume_says_why(monkeypatch):
    import yazses.core.daemon as daemon_mod

    monkeypatch.setattr(daemon_mod, "should_launch_overlay", lambda cfg, env: False)
    cfg = Config()
    cfg.mouthswitch.enabled = True
    daemon = _daemon(cfg, FakePointerSink())
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    reply = daemon._handle_handsfree(Request("handsfree", {"action": "resume"}))
    assert reply["ok"] is False
    assert "overlay" in str(reply["reason"])
    assert daemon._mouthswitch_payload() is None


# --------------------------------------------------------------------------- #
# The daemon's announcer: built from the earcon player and read-back voice it has
# --------------------------------------------------------------------------- #
class FakeEarcon:
    enabled = True

    def __init__(self) -> None:
        self.played: list[str] = []

    def play(self, event: str, confidence: float | None = None) -> None:
        self.played.append(event)


class FakeVoice:
    name = "fake"

    def __init__(self) -> None:
        self.said: list[str] = []

    def speak(self, text: str) -> None:
        self.said.append(text)

    def cancel(self) -> None:
        pass


def _no_overlay_daemon(monkeypatch):
    import yazses.core.daemon as daemon_mod

    monkeypatch.setattr(daemon_mod, "should_launch_overlay", lambda cfg, env: False)
    cfg = Config()
    cfg.mouthswitch.enabled = True
    return _daemon(cfg, FakePointerSink()), cfg


def test_without_the_overlay_the_daemon_announces_with_its_earcons(monkeypatch):
    daemon, cfg = _no_overlay_daemon(monkeypatch)
    daemon._earcon = FakeEarcon()
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    try:
        assert daemon._mouthswitch is not None and daemon._mouthswitch.available
        assert daemon._mouthswitch_payload()["announce"] == "earcon"
    finally:
        daemon._mouthswitch.stop()


def test_a_cue_only_step_counts_the_tick_the_deafness_and_a_full_dwell(monkeypatch):
    from yazses.mouthswitch.announce import cue_duration_s
    from yazses.mouthswitch.runtime import post_voice_deaf_s

    daemon, cfg = _no_overlay_daemon(monkeypatch)
    daemon._earcon = FakeEarcon()
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    try:
        dwells = daemon._mouthswitch.runner._scanner.dwells
        step = cue_duration_s() + post_voice_deaf_s() + cfg.mouthswitch.dwell_s
        assert cue_duration_s() > 0.0
        assert dwells == pytest.approx((step,) * len(dwells))
    finally:
        daemon._mouthswitch.stop()


def test_without_the_overlay_the_daemon_speaks_the_names_with_its_voice(monkeypatch):
    daemon, cfg = _no_overlay_daemon(monkeypatch)
    daemon._tts = FakeVoice()
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    try:
        assert daemon._mouthswitch.available
        assert daemon._mouthswitch_payload()["announce"] == "speech"
    finally:
        daemon._mouthswitch.stop()


def test_a_read_back_voice_that_degraded_to_silence_announces_nothing(monkeypatch):
    from yazses.tts.null import NullTtsBackend

    daemon, cfg = _no_overlay_daemon(monkeypatch)
    daemon._tts = NullTtsBackend()
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    assert daemon._mouthswitch.runner is None
    assert "overlay" in daemon._mouthswitch.reason


class SwitchVoice(FakeVoice):
    """The voice the factory hands `speak_names`; signals when it has said something."""

    name = "kokoro"

    def __init__(self) -> None:
        super().__init__()
        self.spoke = threading.Event()

    def speak(self, text: str) -> None:
        super().speak(text)
        self.spoke.set()


def _speak_names_daemon(monkeypatch, *, voice=None, model_on_disk=True):
    """No overlay, read-back off, `speak_names` on; the TTS factory and model check faked.

    Returns the daemon, its config, the voice the factory hands out, and the factory's calls
    as ``(config it was given, purpose)``.
    """
    import yazses.tts.factory as factory

    daemon, cfg = _no_overlay_daemon(monkeypatch)
    cfg.mouthswitch.speak_names = True
    voice = SwitchVoice() if voice is None else voice
    calls: list[tuple[object, str]] = []

    def build_tts(tts_cfg, *, purpose="Read-back"):
        calls.append((tts_cfg, purpose))
        return voice

    monkeypatch.setattr(factory, "build_tts", build_tts)
    monkeypatch.setattr(daemon, "_tts_model_on_disk", lambda tts_cfg: model_on_disk)
    return daemon, cfg, voice, calls


def test_speak_names_says_the_names_with_read_back_off(monkeypatch):
    from yazses.mouthswitch.announce import SWITCH_VOICE_PURPOSE
    from yazses.mouthswitch.scanner import ScanItem

    daemon, cfg, voice, calls = _speak_names_daemon(monkeypatch)
    assert cfg.tts.enabled is False and daemon._tts is None  # read-back is off
    announcer = daemon._mouthswitch_announcer(cfg)
    assert announcer is not None and announcer.mode == "speech"
    announcer.announce(ScanItem("undo", "command"), first=False)
    assert voice.spoke.wait(timeout=2.0)
    announcer.close()
    assert voice.said == ["undo"]
    # Built through the read-back factory, from [tts] with `enabled` on, under its own name.
    ((built, purpose),) = calls
    assert built.enabled is True and purpose == SWITCH_VOICE_PURPOSE


def test_speak_names_leaves_read_back_off(monkeypatch):
    daemon, cfg, voice, _calls = _speak_names_daemon(monkeypatch)
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    try:
        assert daemon._mouthswitch.available
        assert daemon._mouthswitch_payload()["announce"] == "speech"
        # Read-back is still off: no read-back voice, and a dictation is not read back.
        assert daemon._tts is None and cfg.tts.enabled is False
        daemon._maybe_read_back("this dictation must not be spoken")
        assert voice.said == []
        reply = daemon._handle_readback_speak(Request("say", {"text": "hello"}))
        assert reply["ok"] is False and voice.said == []
    finally:
        daemon._mouthswitch.stop()


def test_speak_names_without_the_tts_extra_falls_back_to_earcons(monkeypatch):
    from yazses.tts.null import NullTtsBackend

    daemon, cfg, _voice, calls = _speak_names_daemon(monkeypatch, voice=NullTtsBackend())
    daemon._earcon = FakeEarcon()
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    try:
        assert len(calls) == 1
        assert daemon._mouthswitch.available
        assert daemon._mouthswitch_payload()["announce"] == "earcon"
    finally:
        daemon._mouthswitch.stop()


def test_speak_names_without_the_model_never_builds_a_voice_and_says_why_once(
    monkeypatch, caplog
):
    caplog.set_level(logging.WARNING, logger="yazses.core.daemon")
    daemon, cfg, _voice, calls = _speak_names_daemon(monkeypatch, model_on_disk=False)
    daemon._earcon = FakeEarcon()
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    try:
        assert calls == []                 # never constructed, so never downloaded
        assert daemon._mouthswitch_payload()["announce"] == "earcon"
        lines = [r.getMessage() for r in caplog.records if "speak_names" in r.getMessage()]
        assert len(lines) == 1 and "earcons only" in lines[0]
    finally:
        daemon._mouthswitch.stop()


def test_speak_names_with_no_voice_and_no_earcon_is_still_no_switch(monkeypatch):
    from yazses.tts.null import NullTtsBackend

    daemon, cfg, _voice, _calls = _speak_names_daemon(monkeypatch, voice=NullTtsBackend())
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    assert daemon._mouthswitch.runner is None
    assert "cannot see or hear" in daemon._mouthswitch.reason


def test_speak_names_off_builds_no_voice(monkeypatch):
    """The shipped default: read-back off and speak_names off is exactly what it was."""
    daemon, cfg, _voice, calls = _speak_names_daemon(monkeypatch)
    cfg.mouthswitch.speak_names = False
    assert Config().mouthswitch.speak_names is False
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    assert calls == [] and daemon._mouthswitch.runner is None


def test_speak_names_is_read_from_the_config_file(tmp_path):
    from yazses.config import load_config

    path = tmp_path / "config.toml"
    path.write_text("[mouthswitch]\nenabled = true\nspeak_names = true\n", encoding="utf-8")
    loaded = load_config(path)
    assert loaded.mouthswitch.speak_names is True
    assert loaded.tts.enabled is False  # it does not switch read-back on behind your back


def test_speak_names_with_read_back_on_uses_the_read_back_voice(monkeypatch):
    daemon, cfg, _voice, calls = _speak_names_daemon(monkeypatch)
    daemon._tts = FakeVoice()
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    try:
        assert calls == []                 # no second voice beside read-back's own
        assert daemon._mouthswitch_payload()["announce"] == "speech"
    finally:
        daemon._mouthswitch.stop()


def test_the_model_check_honours_configured_paths_and_other_engines(tmp_path):
    from yazses.config import TtsConfig
    from yazses.core.daemon import Daemon

    model, voices = tmp_path / "m.onnx", tmp_path / "v.bin"
    cfg = TtsConfig(model_path=str(model), voices_path=str(voices))
    assert Daemon._tts_model_on_disk(cfg) is False
    model.write_bytes(b"")
    assert Daemon._tts_model_on_disk(cfg) is False  # both files are needed
    voices.write_bytes(b"")
    assert Daemon._tts_model_on_disk(cfg) is True
    # No model of ours to fetch for another engine: the factory alone decides.
    assert Daemon._tts_model_on_disk(TtsConfig(engine="melo")) is True


def test_the_factory_names_what_the_voice_is_for(caplog):
    from yazses.config import TtsConfig
    from yazses.tts.factory import build_tts

    caplog.set_level(logging.WARNING, logger="yazses.tts.factory")
    assert build_tts(TtsConfig(enabled=True, engine="melo"), purpose="Speaking X").name == "null"
    assert "Speaking X is enabled" in caplog.text and "Read-back" not in caplog.text
    caplog.clear()
    build_tts(TtsConfig(enabled=True, engine="melo"))
    assert "Read-back is enabled" in caplog.text  # the default wording is unchanged


def test_with_the_overlay_the_daemon_builds_no_announcer(monkeypatch):
    _overlay_on(monkeypatch)
    cfg = Config()
    cfg.mouthswitch.enabled = True
    daemon = _daemon(cfg, FakePointerSink())
    daemon._earcon = FakeEarcon()
    daemon._mouthswitch = daemon._build_mouthswitch(cfg)
    try:
        assert daemon._mouthswitch_payload()["announce"] == ""
    finally:
        daemon._mouthswitch.stop()
