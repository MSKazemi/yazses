"""The chord engine: tokens in, at most one abstract action out (pure) -- EYE-GESTURE-001.

The properties the programme is judged on, each pinned:

* **empty mapping is the safe default**, and an unmapped token reaches no action;
* **collisions and near-misses fire nothing** -- only the exact bound set fires;
* **one engagement, one action**, however long the tokens are held;
* **the global hands-free gate suppresses chord actions** (the stop path excepted), and what
  was pending is dropped, never replayed on resume;
* **the pointer is asked to hold still** for the gesture, and released after;
* the resolver is ``gesture/chords.py``'s own, not a copy.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import pytest

from yazses.gesture import chords
from yazses.gesture.engine import (
    ACTIONS,
    COMMAND_PREFIX,
    TOKENS,
    ChordEngine,
    parse_chords,
)
from yazses.handsfree.safety import HandsFreeSafety

WINDOW = 0.4
REFRACTORY = 1.0
TAIL = 0.3


class Calls:
    def __init__(self) -> None:
        self.log: list[str] = []

    def handler(self, name: str):
        return lambda: self.log.append(name)


def make(bindings, *, gate=None, freeze=None, handlers=None, calls=None):
    calls = calls or Calls()
    table = handlers if handlers is not None else {
        a: calls.handler(a) for a in set(bindings.values())
    }
    engine = ChordEngine(
        bindings, table, window_s=WINDOW, refractory_s=REFRACTORY, freeze_tail_s=TAIL,
        gate=gate, on_freeze=freeze,
    )
    return engine, calls


# --------------------------------------------------------------------------- #
# parse_chords: the mapping is data, validated before it is trusted
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw", [None, {}, [], ()])
def test_an_empty_mapping_is_the_safe_default(raw):
    assert parse_chords(raw) == ({}, [])


def test_chords_are_normalised_by_the_existing_resolver_not_a_copy():
    bound, problems = parse_chords({"Nod + jaw_open".replace(" ", ""): "recenter"})
    assert problems == []
    assert list(bound) == [chords.normalize_chord(["jaw_open", "nod"])]
    assert chords.resolve_chord(["NOD", "jaw_open", "nod"], bound) == "recenter"


def test_an_unknown_token_is_refused_with_a_reason_not_coerced():
    bound, problems = parse_chords({"jaw_open+wink": "recenter", "nod": "pause_pointer"})
    assert bound == {"nod": "pause_pointer"}
    assert len(problems) == 1 and "wink" in problems[0]


@pytest.mark.parametrize("key", ["", "+", "nod+", "+nod", " "])
def test_a_malformed_chord_is_refused(key):
    bound, problems = parse_chords({key: "recenter"})
    assert bound == {} and len(problems) == 1


@pytest.mark.parametrize("action", ["send", "undo", "", "command:", "command:   ", "RECENTER2"])
def test_an_unknown_action_is_refused_not_guessed(action):
    bound, problems = parse_chords({"nod": action})
    assert bound == {} and len(problems) == 1


def test_a_command_phrase_action_is_accepted():
    bound, _ = parse_chords({"nod": "command:undo"})
    assert bound == {"nod": "command:undo"}


def test_two_spellings_of_one_chord_bind_neither():
    bound, problems = parse_chords({
        "jaw_open+nod": "recenter", "nod+jaw_open": "pause_pointer", "tilt": "recenter",
    })
    assert bound == {"tilt": "recenter"}
    assert any("twice" in p for p in problems)


def test_a_bound_chord_is_not_resurrected_by_a_third_spelling():
    bound, _ = parse_chords({"a": "x"})  # a non-token is refused; sanity for the loop below
    assert bound == {}
    bound, _ = parse_chords({
        "jaw_open+nod": "recenter", "nod+jaw_open": "recenter", "Nod+Jaw_Open": "recenter",
    })
    assert bound == {}


@pytest.mark.parametrize("raw", ["nod=recenter", 3, ["nod"]])
def test_a_mapping_of_the_wrong_shape_binds_nothing(raw):
    bound, problems = parse_chords(raw)
    assert bound == {} and problems


def test_non_string_entries_are_refused():
    bound, problems = parse_chords({"nod": 3, 4: "recenter"})
    assert bound == {} and len(problems) == 2


def test_the_action_vocabulary_names_only_what_the_daemon_can_route():
    assert ACTIONS == ("pause_pointer", "recenter", f"{COMMAND_PREFIX}<phrase>")
    assert set(TOKENS) >= {"nod", "shake", "tilt", "jaw_open", "brow_raise"}


# --------------------------------------------------------------------------- #
# Resolution
# --------------------------------------------------------------------------- #
def test_an_empty_mapping_watches_and_fires_nothing():
    engine, calls = make({})
    assert engine.vocabulary == frozenset()
    for t in range(5):
        engine.press("jaw_open", t)
        engine.pulse("nod", t)
        engine.tick(t + 1)
    assert calls.log == []


def test_an_unmapped_token_reaches_no_action():
    engine, calls = make({"jaw_open+nod": "recenter"})
    engine.pulse("shake", 1.0)       # a real token, in no chord
    engine.press("smile", 1.0)
    engine.pulse("bogus", 1.0)       # not a token at all
    engine.tick(5.0)
    assert calls.log == []


def test_a_token_in_no_chord_does_not_spoil_a_chord_made_around_it():
    engine, calls = make({"nod": "recenter"})
    engine.press("smile", 1.0)       # not watched; must neither fire nor block
    engine.pulse("nod", 1.0)
    assert calls.log == ["recenter"]


def test_only_the_exact_bound_set_fires():
    engine, calls = make({"jaw_open+nod": "recenter"})
    engine.pulse("nod", 1.0)
    engine.tick(2.0)
    assert calls.log == []           # a subset is not the chord
    engine2, calls2 = make({"jaw_open+nod": "recenter"})
    engine2.press("jaw_open", 1.0)
    engine2.pulse("nod", 1.1)
    assert calls2.log == ["recenter"]


def test_a_superset_is_not_the_chord_either():
    engine, calls = make({"jaw_open+nod": "recenter"})
    engine.press("jaw_open", 1.0)
    engine.pulse("nod", 1.1)
    assert calls.log == ["recenter"]
    engine, calls = make({"jaw_open+nod": "recenter", "smile": "pause_pointer"})
    engine.press("jaw_open", 1.0)
    engine.press("smile", 1.05)
    engine.pulse("nod", 1.1)         # jaw_open+smile+nod is bound to nothing
    engine.tick(3.0)
    assert calls.log == []


@pytest.mark.parametrize("order", [("jaw_open", "nod"), ("nod", "jaw_open")])
def test_either_order_is_the_same_chord(order):
    engine, calls = make({"jaw_open+nod": "recenter"})
    for i, token in enumerate(order):
        (engine.press if token == "jaw_open" else engine.pulse)(token, 1.0 + 0.1 * i)
    engine.tick(2.0)
    assert calls.log == ["recenter"]


def test_a_chord_that_could_still_grow_waits_for_the_window_then_fires_the_shorter_one():
    engine, calls = make({"nod": "recenter", "jaw_open+nod": "pause_pointer"})
    engine.pulse("nod", 1.0)
    assert calls.log == []           # jaw_open might still be coming
    engine.tick(1.0 + WINDOW + 0.01)
    assert calls.log == ["recenter"]


def test_the_longer_chord_wins_when_its_tokens_arrive_inside_the_window():
    engine, calls = make({"nod": "recenter", "jaw_open+nod": "pause_pointer"})
    engine.pulse("nod", 1.0)
    engine.press("jaw_open", 1.2)
    engine.tick(2.0)
    assert calls.log == ["pause_pointer"]


def test_tokens_outside_the_window_are_two_engagements_not_one_chord():
    engine, calls = make({"jaw_open+nod": "recenter"})
    engine.pulse("nod", 1.0)
    engine.tick(1.0 + WINDOW + 0.01)     # window closes with {nod}: unbound, spent
    engine.press("jaw_open", 1.0 + WINDOW + 0.1)
    engine.tick(5.0)
    assert calls.log == []


# --------------------------------------------------------------------------- #
# Once per engagement
# --------------------------------------------------------------------------- #
def test_a_held_chord_fires_once_however_long_it_is_held():
    engine, calls = make({"tilt": "recenter"})
    engine.press("tilt", 1.0)
    for i in range(1, 100):
        engine.tick(1.0 + i * 0.1)
    assert calls.log == ["recenter"]


def test_it_can_fire_again_after_release_and_the_refractory():
    engine, calls = make({"tilt": "recenter"})
    engine.press("tilt", 1.0)
    engine.release("tilt", 1.5)
    engine.press("tilt", 1.6)            # inside the refractory: not an engagement
    assert calls.log == ["recenter"]
    engine.release("tilt", 1.7)
    engine.tick(3.0)
    engine.press("tilt", 3.1)
    assert calls.log == ["recenter", "recenter"]


def test_pulses_during_the_refractory_are_dropped_not_queued():
    engine, calls = make({"nod": "recenter"})
    engine.pulse("nod", 1.0)
    engine.pulse("nod", 1.2)
    engine.pulse("nod", 1.4)
    engine.tick(1.0 + REFRACTORY + 0.5)
    assert calls.log == ["recenter"]


def test_a_pulse_after_the_refractory_is_a_new_engagement():
    engine, calls = make({"nod": "recenter"})
    engine.pulse("nod", 1.0)
    engine.pulse("nod", 1.0 + REFRACTORY + 0.1)
    assert calls.log == ["recenter", "recenter"]


def test_a_held_token_waits_for_a_pulse_however_long_the_pulse_takes():
    """A nod takes about a second to recognise; the jaw must still count when it lands."""
    engine, calls = make({"jaw_open+nod": "recenter"})
    engine.press("jaw_open", 1.0)
    engine.tick(1.0 + WINDOW + 0.01)     # the window has passed with only the jaw
    assert calls.log == []
    engine.pulse("nod", 2.5)
    assert calls.log == ["recenter"]


def test_letting_go_of_the_held_token_ends_the_wait():
    engine, calls = make({"jaw_open+nod": "recenter"})
    engine.press("jaw_open", 1.0)
    engine.tick(1.0 + WINDOW + 0.01)
    engine.release("jaw_open", 1.6)      # engagement over: {jaw_open} alone is not bound
    engine.pulse("nod", 1.7)             # would have completed it; too late
    engine.tick(5.0)
    assert calls.log == []


def test_waiting_is_only_for_a_chord_that_could_still_complete():
    engine, calls = make({"jaw_open+nod": "recenter"})
    engine.press("smile", 1.0)           # in no chord: not watched, opens nothing
    engine.tick(5.0)
    engine.pulse("nod", 5.1)             # nod alone is not bound
    engine.tick(9.0)
    assert calls.log == []


# --------------------------------------------------------------------------- #
# Handlers
# --------------------------------------------------------------------------- #
def test_a_handler_that_raises_does_not_escape_or_wedge_the_engine():
    calls = Calls()

    def boom():
        raise RuntimeError("handler broke")

    engine, _ = make({"nod": "recenter", "tilt": "pause_pointer"},
                     handlers={"recenter": boom, "pause_pointer": calls.handler("p")})
    engine.pulse("nod", 1.0)              # must not raise
    engine.tick(1.0 + REFRACTORY + 0.1)
    engine.press("tilt", 3.0)
    assert calls.log == ["p"]


def test_an_action_nothing_implements_does_nothing_and_warns_once(caplog):
    engine, calls = make({"nod": "recenter", "tilt": "pause_pointer"}, handlers={})
    assert engine.unwired() == ["pause_pointer", "recenter"]
    with caplog.at_level(logging.WARNING):
        engine.pulse("nod", 1.0)
        engine.pulse("nod", 5.0)
    assert calls.log == []
    assert sum("nothing implements" in r.message for r in caplog.records) == 1


# --------------------------------------------------------------------------- #
# The global hands-free gate
# --------------------------------------------------------------------------- #
class Clock:
    def __init__(self) -> None:
        self.ms = 0.0

    def __call__(self) -> float:
        return self.ms


def armed_gate():
    clock = Clock()
    gate = HandsFreeSafety(["gesture"], clock=clock)
    gate.sample("gesture")
    assert gate.resume(["gesture"]).ok
    return gate, clock


def test_an_armed_gate_lets_a_chord_through():
    gate, _ = armed_gate()
    engine, calls = make({"nod": "recenter"}, gate=gate)
    engine.pulse("nod", 1.0)
    assert calls.log == ["recenter"]


def test_a_gate_that_was_never_armed_suppresses_every_chord():
    gate = HandsFreeSafety(["gesture"])
    gate.sample("gesture")                # a signal, but nobody re-armed the source
    engine, calls = make({"nod": "recenter", "tilt": "pause_pointer"}, gate=gate)
    engine.pulse("nod", 1.0)
    assert calls.log == []


def test_global_pause_suppresses_chord_actions_but_not_the_stop_path():
    gate, _ = armed_gate()
    engine, calls = make({"nod": "recenter", "tilt": "pause_pointer"}, gate=gate)
    gate.pause("test")
    engine.pulse("nod", 1.0)
    engine.press("tilt", 5.0)
    assert calls.log == ["pause_pointer"]  # recenter held back; stopping is never gated


def test_a_stale_signal_suppresses_chord_actions():
    gate, clock = armed_gate()
    engine, calls = make({"nod": "recenter"}, gate=gate)
    clock.ms += 10_000.0                  # the camera went quiet long ago
    engine.pulse("nod", 1.0)
    assert calls.log == []


def test_what_was_pending_when_the_gate_closed_is_not_replayed_after_resume():
    gate, _ = armed_gate()
    engine, calls = make({"jaw_open+nod": "recenter"}, gate=gate)
    engine.press("jaw_open", 1.0)         # half a chord is in flight...
    gate.pause("test")
    engine.frame(True, 1.1)               # ...and the engine notices the gate closed
    gate.sample("gesture")
    assert gate.resume(["gesture"]).ok
    engine.pulse("nod", 1.2)              # jaw_open is still physically held
    engine.tick(5.0)
    assert calls.log == []                # the engagement was discarded, not resumed


def test_the_engine_samples_the_gate_only_when_the_tick_had_a_signal():
    seen: list[str] = []

    @dataclass
    class Gate:
        def gate(self, source):
            return type("D", (), {"allowed": True})()

        def sample(self, source):
            seen.append(source)

    engine, _ = make({"nod": "recenter"}, gate=Gate())
    engine.frame(False, 1.0)
    assert seen == []
    engine.frame(True, 1.1)
    assert seen == ["gesture"]


def test_a_local_pause_suppresses_actions_but_not_the_stop_path():
    engine, calls = make({"nod": "recenter", "tilt": "pause_pointer"})
    engine.set_paused(True)
    engine.pulse("nod", 1.0)
    engine.press("tilt", 5.0)
    assert calls.log == ["pause_pointer"]
    engine.release("tilt", 5.1)
    engine.set_paused(False)
    engine.pulse("nod", 9.0)
    assert calls.log == ["pause_pointer", "recenter"]


# --------------------------------------------------------------------------- #
# The pointer freeze (Project Gameface's failure mode)
# --------------------------------------------------------------------------- #
class Freezes:
    def __init__(self) -> None:
        self.log: list[bool] = []

    def __call__(self, frozen: bool) -> None:
        self.log.append(frozen)


def test_a_held_token_freezes_the_pointer_and_the_tail_outlasts_the_release():
    freeze = Freezes()
    engine, _ = make({"jaw_open+nod": "recenter"}, freeze=freeze)
    engine.press("jaw_open", 1.0)
    assert engine.freeze_pointer and freeze.log == [True]
    engine.release("jaw_open", 2.0)
    assert engine.freeze_pointer           # facial effort fades after the detector says so
    engine.tick(2.0 + TAIL - 0.01)
    assert engine.freeze_pointer
    engine.tick(2.0 + TAIL + 0.01)
    assert not engine.freeze_pointer and freeze.log == [True, False]


def test_an_onset_alone_freezes_the_pointer_before_the_token_exists():
    freeze = Freezes()
    engine, calls = make({"jaw_open+nod": "recenter"}, freeze=freeze)
    engine.onset("jaw_open", True, 1.0)
    assert engine.freeze_pointer and calls.log == []   # a freeze, never an action
    engine.onset("jaw_open", False, 1.1)
    engine.tick(1.1 + TAIL + 0.01)
    assert not engine.freeze_pointer


def test_a_pulse_freezes_for_the_tail():
    freeze = Freezes()
    engine, _ = make({"nod": "recenter"}, freeze=freeze)
    engine.pulse("nod", 1.0)
    assert engine.freeze_pointer
    engine.tick(1.0 + TAIL + 0.01)
    assert not engine.freeze_pointer


def test_an_unwatched_token_never_freezes_the_pointer():
    freeze = Freezes()
    engine, _ = make({"nod": "recenter"}, freeze=freeze)
    engine.press("jaw_open", 1.0)
    engine.onset("jaw_open", True, 1.0)
    assert not engine.freeze_pointer and freeze.log == []


def test_reset_releases_the_freeze_and_every_token():
    freeze = Freezes()
    engine, calls = make({"jaw_open+nod": "recenter"}, freeze=freeze)
    engine.press("jaw_open", 1.0)
    engine.reset(2.0)
    assert not engine.freeze_pointer and freeze.log == [True, False]
    engine.pulse("nod", 2.1)               # jaw_open is forgotten, so this is half a chord
    engine.tick(5.0)
    assert calls.log == []


def test_a_freeze_callback_that_raises_does_not_break_the_engine():
    def boom(_):
        raise RuntimeError("clutch broke")

    engine, calls = make({"nod": "recenter"}, freeze=boom)
    engine.pulse("nod", 1.0)
    assert calls.log == ["recenter"]
