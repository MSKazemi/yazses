"""`AutoStopTurn(endpoint=...)`: the seam Hesitation-Hold Endpointing plugs into (#164).

`WIRE-HESITATION-001` needs the hands-free turn to ask "commit or hold?" instead of
comparing trailing silence to one fixed number, so an "umm..." gets more time than a
finished sentence (ADR-v2-101). The judge is a plain callable with the shape of
`HesitationMonitor.decision`: `endpoint(silence_ms) -> "commit" | "hold"`.

Four claims:

* **Unset is unchanged.** `endpoint=None` (the default) gives the exact plain-threshold
  machine: same tick-by-tick answers on a long scripted trace, and a judge that
  reproduces the plain threshold reproduces it tick for tick too.
* **Set, it decides the silence.** It is asked only after speech, only once the
  `MIN_SILENCE_TIMEOUT_MS` floor is reached, and its "hold" outlasts `silence_timeout_ms`.
* **The cap is still first.** A judge that always holds cannot keep a turn past
  `max_duration_ms`, and the no-speech grace still ends a stray tap.
* **A faulty judge degrades, it does not wedge.** If it raises, that tick uses the plain
  threshold.

numpy only (a base dependency) for the one test that drives the real monitor; nothing
here opens a microphone or a thread.
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from tests.synthetic_voice import hum, silence
from yazses.endpoint.autostop import (
    MIN_SILENCE_TIMEOUT_MS,
    NO_SPEECH_GRACE_MS,
    AutoStopTurn,
)
from yazses.hesitation.stream import HesitationMonitor

STEP = 0.05  # the daemon's watcher polls every 50 ms


@dataclass
class _Cfg:
    enabled: bool = True
    mode: str = "silence"
    silence_timeout_ms: int = 800
    max_duration_ms: int = 30000


class _Judge:
    """A scripted endpoint that records what it was asked."""

    def __init__(self, answer) -> None:
        self.answer = answer
        self.asked: list[float] = []

    def __call__(self, silence_ms: float) -> str:
        self.asked.append(silence_ms)
        return self.answer(silence_ms) if callable(self.answer) else self.answer


def _tapped(turn: AutoStopTurn, t: float = 0.0) -> float:
    assert turn.press(t) is False
    assert turn.release(t + 0.1) is True
    return t + 0.1


def _trace(turn: AutoStopTurn, speech: list[bool], t0: float = 0.0) -> list[bool]:
    """Tap, then tick once per STEP with ``speech[i]``; re-tap after every end."""
    out: list[bool] = []
    now = _tapped(turn, t0)
    for voiced in speech:
        now += STEP
        ended = turn.tick(now, voiced)
        out.append(ended)
        if ended:
            now = _tapped(turn, now + STEP)
    return out


def _random_speech(seed: int, n: int = 4000) -> list[bool]:
    """Bursts of speech and silence of random length -- long pauses, short gaps, none."""
    rng = random.Random(seed)
    out: list[bool] = []
    while len(out) < n:
        out.extend([rng.random() < 0.5] * rng.randint(1, 40))
    return out[:n]


# ---- unset is unchanged ----------------------------------------------------------

def test_endpoint_none_is_tick_for_tick_the_plain_machine():
    for seed in range(5):
        speech = _random_speech(seed)
        cfg = _Cfg(max_duration_ms=12000)
        plain = _trace(AutoStopTurn(cfg, tap_ms=500), speech)
        explicit = _trace(AutoStopTurn(cfg, tap_ms=500, endpoint=None), speech)
        assert explicit == plain
        assert any(plain), "non-vacuity: the trace must contain turn ends"


def test_a_judge_that_is_the_plain_threshold_reproduces_the_plain_machine():
    """The judge replaces exactly the silence comparison and nothing else."""
    for timeout in (300, 800, 1500):
        cfg = _Cfg(silence_timeout_ms=timeout, max_duration_ms=9000)
        for seed in range(3):
            speech = _random_speech(seed)
            plain = _trace(AutoStopTurn(cfg, tap_ms=500), speech)
            judged = _trace(
                AutoStopTurn(
                    cfg,
                    tap_ms=500,
                    endpoint=lambda s, timeout=timeout: "commit" if s >= timeout else "hold",
                ),
                speech,
            )
            assert judged == plain


# ---- set, it decides the silence -------------------------------------------------

def test_a_hold_outlasts_the_silence_timeout_and_a_commit_ends_the_turn():
    judge = _Judge(lambda s: "commit" if s >= 2000 else "hold")
    turn = AutoStopTurn(_Cfg(silence_timeout_ms=800), tap_ms=500, endpoint=judge)
    t = _tapped(turn)
    assert turn.tick(t + 0.5, True) is False
    assert turn.tick(t + 1.0, False) is False  # silence begins
    assert turn.tick(t + 1.8, False) is False  # 800 ms: the plain machine would end here
    assert turn.tick(t + 2.9, False) is False  # 1900 ms
    assert turn.tick(t + 3.0, False) is True  # 2000 ms: the judge commits
    assert turn.latched is False
    assert judge.asked and judge.asked[-1] == 2000.0


def test_the_judge_is_not_asked_before_speech_or_inside_the_floor():
    judge = _Judge("commit")
    turn = AutoStopTurn(_Cfg(), tap_ms=500, endpoint=judge)
    t = _tapped(turn)
    for step in range(1, 30):  # 2.9 s of silence before the first word
        assert turn.tick(t + step * 0.1, False) is False
    assert judge.asked == []
    assert turn.tick(t + 3.0, True) is False  # speech
    assert turn.tick(t + 3.1, False) is False  # silence begins
    floor = MIN_SILENCE_TIMEOUT_MS / 1000.0
    assert turn.tick(t + 3.1 + floor - 0.05, False) is False  # an ordinary between-word gap
    assert judge.asked == []
    assert turn.tick(t + 3.1 + floor + 0.001, False) is True
    assert len(judge.asked) == 1
    assert MIN_SILENCE_TIMEOUT_MS <= judge.asked[0] < MIN_SILENCE_TIMEOUT_MS + 2


# ---- the cap is still first -----------------------------------------------------

def test_a_judge_that_always_holds_cannot_outlast_the_duration_cap():
    judge = _Judge("hold")
    turn = AutoStopTurn(_Cfg(max_duration_ms=10000), tap_ms=500, endpoint=judge)
    t = _tapped(turn)
    assert turn.tick(t + 0.5, True) is False
    assert turn.tick(t + 1.0, False) is False  # silence begins
    assert turn.tick(t + 9.99, False) is False  # 8.99 s of silence: the judge still holds
    asked = len(judge.asked)
    assert asked == 1
    assert turn.tick(t + 10.0, False) is True  # the cap
    assert len(judge.asked) == asked, "the cap is checked before the judge"


def test_the_no_speech_grace_still_ends_a_stray_tap():
    judge = _Judge("hold")
    turn = AutoStopTurn(_Cfg(), tap_ms=500, endpoint=judge)
    t = _tapped(turn)
    grace = NO_SPEECH_GRACE_MS / 1000.0
    assert turn.tick(t + grace - 0.1, False) is False
    assert turn.tick(t + grace, False) is True
    assert judge.asked == []


def test_a_disabled_config_never_stops_even_if_the_judge_commits():
    turn = AutoStopTurn(_Cfg(enabled=False, max_duration_ms=1000), tap_ms=500,
                        endpoint=_Judge("commit"))
    t = _tapped(turn)
    assert turn.tick(t + 0.2, True) is False
    assert turn.tick(t + 3.0, False) is False


# ---- a faulty judge ----------------------------------------------------------------

def test_a_judge_that_raises_falls_back_to_the_plain_threshold():
    def broken(_silence_ms: float) -> str:
        raise RuntimeError("analysis failed")

    turn = AutoStopTurn(_Cfg(silence_timeout_ms=800), tap_ms=500, endpoint=broken)
    t = _tapped(turn)
    assert turn.tick(t + 0.5, True) is False
    assert turn.tick(t + 1.0, False) is False
    assert turn.tick(t + 1.7, False) is False  # 700 ms
    assert turn.tick(t + 1.8, False) is True  # 800 ms, as without a judge


# ---- the real producer fits the seam --------------------------------------------

def test_hesitation_monitor_decision_holds_after_an_umm_and_commits_later():
    """`HesitationMonitor.decision` plugs in unchanged, and an "umm" buys the extra time."""
    monitor = HesitationMonitor(commit_ms=800.0, hold_extra_ms=1200.0)
    monitor.push(hum(118.0, 0.6, noise=5e-4))
    monitor.push(silence(0.2))
    turn = AutoStopTurn(_Cfg(silence_timeout_ms=800), tap_ms=500, endpoint=monitor.decision)
    t = _tapped(turn)
    assert turn.tick(t + 0.5, True) is False
    assert turn.tick(t + 1.0, False) is False
    assert turn.tick(t + 1.8, False) is False  # 800 ms: held, because it was a filled pause
    assert turn.tick(t + 2.9, False) is False  # 1900 ms
    assert turn.tick(t + 3.0, False) is True  # 800 + 1200 ms
