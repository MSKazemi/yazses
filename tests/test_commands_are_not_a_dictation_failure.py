"""Holding the command key is not an attempt to dictate, so it must not score as one.

Found running the product, 2026-08-20. `yazses status --json` on a healthy daemon:

    "outcomes": {"total": 6, "typed": 0,
                 "counts": {"empty": 1, "command_unmatched": 4, "silent": 1}}

and the line a person actually reads, immediately above a microphone warning:

    typed:    0 of 6 recent bursts (0%)
    ⚠ mic:    2 silent clips in a row — run `yazses audio status`

Four of those six bursts were the dedicated command key held on purpose. Command mode
**never types literal text** — an unrecognised phrase is ignored by design — so those
bursts were counted as failures of a thing they were not attempting.

The conflation ran both ways, and the other direction is the one that would have hidden
a real fault: a command that *matched* dispatches a key sequence, sets no discard
reason, and therefore scored as `typed`. A gauge documented as "how often dictation
actually produced text" could be held at 100% by commands while dictation typed nothing.

`docs/cli-reference.md` enumerates what counts against the rate — "silence, an empty
transcription, no text target" — every one a dictation-path failure. The daemon already
stamped `event["command_mode"]` at classification time. The gauge one module away never
asked for it.
"""
from __future__ import annotations

from yazses.system.outcomes import MIN_SAMPLES, OutcomeWindow, describe_outcomes


def _lines(window: OutcomeWindow) -> str:
    return "\n".join(describe_outcomes(window.as_dict()))


def test_the_measured_machine_no_longer_reports_zero_percent():
    """Replay the six real bursts. Two dictation bursts cannot support a rate."""
    w = OutcomeWindow()
    w.record("empty")                                  # 19:41, level 0.0042
    w.record("command_unmatched", command=True)        # 20:37, level 0.0118
    w.record("command_unmatched", command=True)        # 20:38, level 0.0057
    w.record("silent")                                 # 20:38, level 0.0000
    w.record("command_unmatched", command=True)        # 21:12, level 0.0092
    w.record("command_unmatched", command=True)

    out = _lines(w)
    assert "0%" not in out, f"still averaging commands into the dictation rate: {out!r}"
    assert "of 6" not in out, f"six bursts, but only two were dictation: {out!r}"
    # The commands are still reported — an outcome nobody counts is how a failure
    # mode stays invisible, which is the rule this fix must not break.
    assert "4 recent command burst(s), 4 unrecognised" in out, out


def test_a_matched_command_does_not_flatter_the_dictation_rate():
    """The other direction, and the one that could hide a real fault."""
    w = OutcomeWindow()
    for _ in range(20):
        w.record("typed", command=True)   # commands that worked: no discard reason
    for _ in range(MIN_SAMPLES):
        w.record("empty")                 # dictation typing nothing at all

    out = _lines(w)
    assert "0%" in out, f"dictation typed nothing and the rate must say so: {out!r}"
    assert "100%" not in out, f"commands were counted as dictation successes: {out!r}"


def test_the_dictation_rate_is_computed_over_dictation_only():
    w = OutcomeWindow()
    for _ in range(9):
        w.record("typed")
    w.record("empty")
    for _ in range(40):
        w.record("command_unmatched", command=True)

    out = _lines(w)
    assert "9 of 10 recent dictation bursts (90%)" in out, out


def test_commands_are_reported_even_when_the_rate_is_withheld():
    """Below MIN_SAMPLES the rate is silent; a run of bad commands must not be."""
    w = OutcomeWindow()
    w.record("typed")
    for _ in range(6):
        w.record("command_unmatched", command=True)

    out = _lines(w)
    assert "typed:" not in out, f"one dictation burst cannot support a rate: {out!r}"
    assert "6 recent command burst(s), 6 unrecognised" in out, out


def test_no_command_bursts_means_no_command_line():
    """The line must not appear on a machine that never uses the command key."""
    w = OutcomeWindow()
    for _ in range(MIN_SAMPLES):
        w.record("typed")

    out = _lines(w)
    assert "commands:" not in out, out
    assert "100%" in out, out


def test_a_recognised_command_is_not_counted_as_unrecognised():
    w = OutcomeWindow()
    for _ in range(3):
        w.record("typed", command=True)
    w.record("command_unmatched", command=True)

    out = _lines(w)
    assert "4 recent command burst(s), 1 unrecognised" in out, out


def test_a_command_refused_for_want_of_a_target_counts_as_unrecognised():
    """`command_no_text_target` is the other way a command produces nothing."""
    w = OutcomeWindow()
    w.record("command_no_text_target", command=True)
    assert "1 recent command burst(s), 1 unrecognised" in _lines(w)


def test_the_combined_totals_keep_their_old_meaning():
    """A status bar reading `total`/`typed`/`counts` must not shift under it."""
    w = OutcomeWindow()
    w.record("typed")
    w.record("empty")
    w.record("command_unmatched", command=True)

    data = w.as_dict()
    assert data["total"] == 3, data
    assert data["typed"] == 1, data
    assert data["counts"] == {"typed": 1, "empty": 1, "command_unmatched": 1}, data
    assert data["dictation_total"] == 2 and data["dictation_typed"] == 1, data
    assert data["command_total"] == 1 and data["command_unrecognised"] == 1, data


def test_an_older_daemon_gets_the_old_line_and_no_invented_claim():
    """A new CLI against a daemon that cannot tell the two kinds apart.

    It must not label the result a *dictation* rate — the payload cannot support that
    — and it must not go silent, which would look like a broken CLI.
    """
    legacy = {"total": 10, "typed": 7, "counts": {"typed": 7, "empty": 3}}
    out = "\n".join(describe_outcomes(legacy))
    assert "7 of 10 recent bursts (70%)" in out, out
    assert "dictation" not in out, f"claimed more than the old payload knows: {out!r}"


def test_the_window_bounds_commands_too():
    """Both deques are bounded, or a long session grows without limit."""
    w = OutcomeWindow(window=3)
    for _ in range(10):
        w.record("command_unmatched", command=True)
    assert w.as_dict()["command_total"] == 3


# --- the daemon actually passing the flag -------------------------------------------

import numpy as np  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.core.daemon import Daemon  # noqa: E402
from yazses.platform import get_platform  # noqa: E402


class _FakeRecorder:
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


def test_the_daemon_records_a_command_burst_as_a_command():
    """Reverting `command=bool(event.get("command_mode"))` must turn this red."""
    d = _daemon()
    d._command_mode = True
    d._engine.text = "the quick brown fox jumped over it"
    d._on_hold_end()

    data = d._outcomes.as_dict()
    assert data["command_total"] == 1, data
    assert data["dictation_total"] == 0, (
        "a command-key burst was counted as a dictation attempt", data
    )
    assert data["command_unrecognised"] == 1, data


def test_the_daemon_records_a_dictation_burst_as_dictation():
    """The control: without the command key, nothing changes."""
    d = _daemon()
    d._command_mode = False
    d._engine.text = "hello there this is ordinary dictation"
    d._on_hold_end()

    data = d._outcomes.as_dict()
    assert data["dictation_total"] == 1, data
    assert data["command_total"] == 0, data
