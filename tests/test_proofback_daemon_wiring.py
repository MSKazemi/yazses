"""Interruptible Proofreading wired through the daemon (ADR-v2-108), with fakes only.

Drives the real ``_on_hold_start`` / ``_on_hold_end`` / ``_maybe_read_back`` /
``_speak_readback`` with a fake TTS backend that reports its playback to the listener
and lets the test press the key mid-playback. No audio, model, or keyboard.

The end-to-end shape pinned here: dictate "send the wrong file", hear it read back,
press the key while "wrong" is playing, say "right file" — the screen ends up holding
"send the right file", typed as 10 backspaces then "right file". Every refusal types
the second burst as ordinary dictation and erases nothing.
"""
from __future__ import annotations

import threading

import numpy as np
import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.inject.replace import RESTORED, Wording
from yazses.platform import TrayState, get_platform
from yazses.proofback.bargein import ProofbackController
from yazses.system.features import EXPERIMENTAL, _registry, enable_caveat, unwired_slugs

SR = 1000  # 1 sample == 1 ms
FIRST = "send the wrong file"


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _FakeRecorder:
    def __init__(self) -> None:
        self.audio = np.full(16000, 0.5, dtype="float32")

    def start(self) -> None:
        pass

    def stop(self):
        return self.audio


class _FakeEngine:
    def __init__(self) -> None:
        self.text = ""

    def transcribe(self, *a, **k):
        return self.text


class _Injector:
    def __init__(self) -> None:
        self.ops: list[tuple[str, object]] = []

    def inject(self, text):
        self.ops.append(("type", text))

    def inject_backspaces(self, n):
        self.ops.append(("backspace", n))

    def inject_key_sequence(self, keys):
        self.ops.append(("keys", tuple(keys)))


class _ProofTts:
    """Reports one chunk to the playback listener, then runs `during` mid-playback."""

    name = "fake"

    def __init__(self) -> None:
        self.listener = None
        self.listener_sets: list = []
        self.spoken: list[str] = []
        self.cancels = 0
        self.during = None

    def begin(self) -> None:
        pass

    def set_playback_listener(self, fn) -> None:
        self.listener = fn
        self.listener_sets.append(fn)

    def speak(self, text: str) -> None:
        self.spoken.append(text)
        if self.listener is not None:
            # One chunk starting at t=100 s, 100 ms per character-weight unit.
            self.listener(text, 100 * sum(ch.isalnum() for ch in text), SR, 100.0)
        if self.during is not None:
            during, self.during = self.during, None
            during()

    def synthesize(self, text):
        return iter(())

    def cancel(self) -> None:
        self.cancels += 1


_RealThread = threading.Thread


class _DeferReadback:
    """Defers only the read-back worker so the test decides when playback happens."""

    pending: list = []

    def __new__(cls, *args, **kwargs):
        if kwargs.get("name") == "readback":
            obj = object.__new__(cls)
            obj._target = kwargs.get("target")
            return obj
        return _RealThread(*args, **kwargs)

    def __init__(self, *args, **kwargs) -> None:
        pass  # state was set in __new__; only reached for the deferred read-back

    def start(self) -> None:
        _DeferReadback.pending.append(self._target)


class _ThreadingProxy:
    """`threading` as the daemon module sees it, with only `Thread` replaced.

    Patching the attribute on the real `threading` module would also change what any
    module imported mid-test subclasses; this keeps the substitution to the daemon.
    """

    Thread = _DeferReadback

    def __getattr__(self, name):
        return getattr(threading, name)


def _daemon(monkeypatch, *, proofback=True, **cfg_overrides):
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    cfg.accessibility.speech_presence_check = False
    cfg.tts.enabled = True
    cfg.accessibility.read_back = "final"
    cfg.revise.enabled = True
    cfg.proofback.enabled = proofback
    for dotted, value in cfg_overrides.items():
        section, key = dotted.split("__")
        setattr(getattr(cfg, section), key, value)
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder()
    d._engine = _FakeEngine()
    d._padding_buffer = None
    d._injector = _Injector()
    tts = _ProofTts()
    d._tts = tts
    monkeypatch.setattr(d, "_detect_target_async", lambda: None)
    _DeferReadback.pending = []
    monkeypatch.setattr("yazses.core.daemon.threading", _ThreadingProxy())
    clock = _Clock()
    if proofback:
        d._proofback = ProofbackController(clock=clock)
    return d, tts, clock


def _dictate(d, text: str) -> None:
    d._engine.text = text
    d._on_hold_start(0)
    d._on_hold_end()


def _play_readback_and_press_at(d, tts, clock, t: float) -> None:
    """Run the deferred read-back; the key goes down at monotonic time *t*."""
    def press():
        clock.t = t
        d._on_hold_start(0)

    tts.during = press
    worker = _DeferReadback.pending.pop(0)
    worker()


# "send the wrong file": weights 4,3,5,4 (x100 ms) from t=100 → "wrong" is [100.7, 101.2).
WRONG_AT = 100.9


def test_proofback_is_wired_experimental_and_explains_its_prerequisite():
    assert "proofback" not in unwired_slugs()
    definition = next(d for d in _registry() if d.slug == "proofback")
    assert definition.tier == EXPERIMENTAL
    assert "Read-Back" in definition.why
    off = Config()
    assert enable_caveat("proofback", off) is not None
    on = Config()
    on.tts.enabled = True
    on.accessibility.read_back = "final"
    assert enable_caveat("proofback", on) is None


def test_off_by_default_and_the_read_back_call_is_unchanged(monkeypatch):
    assert Config().proofback.enabled is False
    d, tts, _clock = _daemon(monkeypatch, proofback=False)
    assert d._proofback is None
    calls = []
    # The one-argument shape existing callers and tests replace it with.
    d._speak_readback = lambda text: calls.append(text)
    d._maybe_read_back("hello world")
    assert calls == ["hello world"]


def test_barge_in_replaces_from_the_interrupted_word(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    assert d._injector.ops == [("type", FIRST)]
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert tts.cancels >= 1, "the barge-in must still stop playback"
    armed = d._proofback.armed
    assert armed is not None and armed.word == "wrong"

    d._engine.text = "right file"
    d._on_hold_end()

    assert d._injector.ops == [
        ("type", FIRST),
        ("backspace", len("wrong file")),
        ("type", "right file"),
    ]
    # The undo record follows the screen: "send the " + "right file".
    assert d._ledger.last_text() == "right file"
    assert len(d._ledger) == 2
    assert d._proofback.armed is None


def test_the_listener_is_installed_for_dictation_and_cleared_for_say(monkeypatch):
    d, tts, _clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    _DeferReadback.pending.pop(0)()
    assert tts.listener_sets and tts.listener_sets[-1] is not None
    d._speak_readback("a status line")
    _DeferReadback.pending.pop(0)()
    assert tts.listener_sets[-1] is None


def test_a_press_during_say_arms_nothing(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    d._speak_readback("send the wrong file")  # `yazses say`, not a dictation
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert d._proofback.armed is None


def test_a_hold_outside_read_back_disarms(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert d._proofback.armed is not None
    with d._lock:
        d._state.state = TrayState.IDLE
    d._on_hold_start(0)
    assert d._proofback.armed is None


def test_a_press_before_the_first_word_plays_arms_nothing(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    tts.set_playback_listener = lambda fn: None  # a backend that reports no chunks
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert d._proofback.armed is None
    d._engine.text = "next sentence"
    d._on_hold_end()
    assert ("type", "next sentence") in d._injector.ops
    assert not [op for op in d._injector.ops if op[0] == "backspace"]


def test_text_typed_since_the_read_back_is_never_erased(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    d._last_dictation_monotonic = (d._last_dictation_monotonic or 0.0) + 5.0  # e.g. a punch-in
    d._engine.text = "right file"
    d._on_hold_end()
    assert ("type", "right file") in d._injector.ops
    assert not [op for op in d._injector.ops if op[0] == "backspace"]


def test_no_editable_target_reports_and_erases_nothing(monkeypatch):
    d, tts, clock = _daemon(monkeypatch, injection__target_guard="off")
    _dictate(d, FIRST)
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    with d._lock:
        d._state.target_ok = False
    d._engine.text = "right file"
    d._on_hold_end()
    assert not [op for op in d._injector.ops if op[0] == "backspace"]


def test_an_armed_target_dies_with_the_burst_that_follows(monkeypatch):
    d, tts, clock = _daemon(monkeypatch)
    _dictate(d, FIRST)
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    d._engine.text = ""  # nothing decoded: the burst is discarded
    d._on_hold_end()
    assert d._proofback.armed is None
    assert not [op for op in d._injector.ops if op[0] == "backspace"]


def test_a_truncated_read_back_word_is_reported_not_replaced(monkeypatch):
    d, tts, clock = _daemon(monkeypatch, tts__max_readback_chars=12)
    _dictate(d, FIRST)  # read back as "send the wro…"
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert tts.spoken[-1].endswith("…")
    assert d._proofback.armed is None


# ---- A correction that cannot be typed (the data-loss fix) --------------------------
#
# The erase used to run before the correction was typed, with no way back: a correction
# that failed after the backspaces left the dictated words erased and nothing in their
# place, and the undo records still described the erased text. `_ScreenInjector` is a
# text field (types append, backspaces delete from the end) whose calls can be scripted
# to fail, so each test can compare the screen with what the records claim.

RIGHT = "right file"


class _ScreenInjector(_Injector):
    """A text field. ``fail[(kind, n)]`` scripts the n-th call of ``kind`` (0-based).

    ``"raise"`` raises having delivered nothing, ``"false"`` returns False having
    delivered nothing, ``"denied"`` raises the ``PermissionError`` a ``/dev/uinput``
    denial raises, and an int delivers that many characters (or backspaces) and then
    raises — a backend cut off part-way.
    """

    def __init__(self, fail: dict | None = None) -> None:
        super().__init__()
        self.screen = ""
        self.fail = dict(fail or {})
        self._calls = {"type": 0, "backspace": 0}

    def _mode(self, kind: str):
        n = self._calls[kind]
        self._calls[kind] += 1
        return self.fail.get((kind, n))

    def inject(self, text):
        mode = self._mode("type")
        self.ops.append(("type", text))
        if mode == "denied":
            raise PermissionError(13, "Permission denied", "/dev/uinput")
        if mode == "raise":
            raise RuntimeError("typing refused")
        if mode == "false":
            return False
        if isinstance(mode, int):
            self.screen += text[:mode]
            raise RuntimeError("typing cut off")
        self.screen += text
        return None

    def inject_backspaces(self, n):
        mode = self._mode("backspace")
        self.ops.append(("backspace", n))
        if mode == "denied":
            raise PermissionError(13, "Permission denied", "/dev/uinput")
        if mode == "raise":
            raise RuntimeError("backspaces refused")
        if mode == "false":
            return False
        count = mode if isinstance(mode, int) else n
        self.screen = self.screen[: max(0, len(self.screen) - count)]
        if isinstance(mode, int):
            raise RuntimeError("backspaces cut off")
        return None


def _armed_daemon(monkeypatch, fail=None, *, clipboard_ok=True, paced=None, **cfg):
    """Dictate FIRST, barge in at "wrong", and return before the correction burst."""
    d, tts, clock = _daemon(monkeypatch, timeline__enabled=True, **cfg)
    injector = _ScreenInjector(fail)
    d._injector = injector
    if paced is not None:
        monkeypatch.setattr(d, "_inject_paced", paced)
    notes: list[tuple[str, str]] = []
    monkeypatch.setattr(d, "_notify_mic", lambda title, body, **kw: notes.append((title, body)))
    copied: list[str] = []

    def _set_clipboard(text, **kw):
        copied.append(text)
        return clipboard_ok

    monkeypatch.setattr("yazses.system.clipboard.set_clipboard", _set_clipboard)
    _dictate(d, FIRST)
    assert injector.screen == FIRST
    _play_readback_and_press_at(d, tts, clock, WRONG_AT)
    assert d._proofback.armed is not None
    return d, injector, notes, copied


def _correct(d, text: str = RIGHT) -> None:
    d._engine.text = text
    d._on_hold_end()


def _records(d) -> tuple[str, str]:
    """(the ledger's newest burst, the [timeline]'s whole text)."""
    assert d._timeline is not None
    return d._ledger.last_text(), d._timeline.text()


def test_a_correction_that_lands_keeps_screen_and_records_in_step(monkeypatch):
    d, inj, notes, copied = _armed_daemon(monkeypatch)
    _correct(d)
    assert inj.screen == "send the right file"
    last, timeline = _records(d)
    assert last == RIGHT and len(d._ledger) == 2
    assert timeline == inj.screen
    assert notes == [] and copied == []


@pytest.mark.parametrize("mode", ["raise", "false"])
def test_a_failed_correction_types_the_erased_words_back(monkeypatch, mode):
    # type #0 was FIRST; type #1 is the correction.
    d, inj, notes, copied = _armed_daemon(monkeypatch, {("type", 1): mode})
    _correct(d)
    assert inj.ops[-3:] == [
        ("backspace", len("wrong file")),
        ("type", RIGHT),
        ("type", "wrong file"),
    ]
    assert inj.screen == FIRST, "the user's dictated words are back"
    last, timeline = _records(d)
    assert last == FIRST and len(d._ledger) == 1
    assert timeline == inj.screen
    assert copied == []
    assert len(notes) == 1 and "not typed" in notes[0][0].lower()
    assert d._state.last_error and "restored" in d._state.last_error


def test_a_failed_restore_puts_the_erased_words_on_the_clipboard(monkeypatch):
    d, inj, notes, copied = _armed_daemon(
        monkeypatch, {("type", 1): "raise", ("type", 2): "raise"}
    )
    _correct(d)
    assert copied == ["wrong file"]
    assert inj.screen == "send the "
    last, timeline = _records(d)
    # "scratch that" now presses 9 backspaces, not 19 into the text before the burst.
    assert last == "send the "
    assert timeline == inj.screen
    assert len(notes) == 1
    title, body = notes[0]
    assert "clipboard" in title.lower() and "on the clipboard" in body


def test_a_failed_clipboard_copy_is_still_reported(monkeypatch):
    d, inj, notes, copied = _armed_daemon(
        monkeypatch, {("type", 1): "raise", ("type", 2): "raise"}, clipboard_ok=False
    )
    _correct(d)
    assert copied == ["wrong file"]
    assert len(notes) == 1 and "could not be saved" in notes[0][0]
    last, timeline = _records(d)
    assert last == "send the " and timeline == inj.screen


def test_an_erase_cut_off_part_way_types_nothing_and_never_over_claims(monkeypatch):
    # Four of the ten backspaces land, then the backend fails.
    d, inj, notes, copied = _armed_daemon(monkeypatch, {("backspace", 0): 4})
    _correct(d)
    assert inj.screen == "send the wrong "
    assert ("type", RIGHT) not in inj.ops, "never type over an erase that stopped early"
    assert copied == ["wrong file"]
    last, timeline = _records(d)
    # The records claim no more than is certainly there, so an undo cannot reach
    # past the burst into the user's own text.
    assert inj.screen.startswith(last) and inj.screen.startswith(timeline)
    assert len(notes) == 1 and "could not finish erasing" in notes[0][1]


def test_a_correction_cut_off_part_way_never_loses_the_erased_words(monkeypatch):
    # The correction call delivers "rig" and fails. Whether a failing call typed
    # anything is invisible to the daemon, so the fragment stays and the erased words
    # are typed back after it: visible and editable, where erasing them was not.
    d, inj, notes, copied = _armed_daemon(monkeypatch, {("type", 1): 3})
    _correct(d)
    assert inj.screen == "send the rigwrong file"
    last, timeline = _records(d)
    # Undo deletes by count: the records may under-count the burst, never over-count.
    assert len(last) <= len(inj.screen) and len(timeline) <= len(inj.screen)
    assert len(notes) == 1


def test_a_paced_correction_removes_its_delivered_chunks_before_restoring(monkeypatch):
    def paced(text, injector, event):
        if text != RIGHT:
            injector.inject(text)  # FIRST, as one chunk (type #0)
            return
        # The correction as two clause chunks; the second one (type #2) fails.
        injector.inject("right")
        injector.inject(" file")

    d, inj, notes, copied = _armed_daemon(
        monkeypatch, {("type", 2): "raise"}, paced=paced, srpace__enabled=True
    )
    _correct(d)
    # The chunk that certainly landed is deleted, then the erased words typed back.
    assert inj.ops[-2:] == [("backspace", len("right")), ("type", "wrong file")]
    assert inj.screen == FIRST
    last, timeline = _records(d)
    assert last == FIRST and timeline == FIRST
    assert len(notes) == 1


def test_the_no_text_target_guard_refuses_before_anything_is_erased(monkeypatch):
    # The clipboard guard: a window with no text field gets the correction on the
    # clipboard and loses nothing, because the guard runs before the erase.
    d, inj, notes, copied = _armed_daemon(monkeypatch, injection__target_guard="clipboard")
    with d._lock:
        d._state.target_ok = False
    _correct(d)
    assert not [op for op in inj.ops if op[0] == "backspace"]
    assert inj.screen == FIRST
    assert copied == [RIGHT]


# ---- The cause is named, as Spoken Edit and Punch-In name it --------------------------
#
# Spoken Edit and Punch-In pass a failed retype to `_report_failure`, which diagnoses the
# cause (here: `/dev/uinput` refused -> "YazSes is not allowed to type", with the command
# that fixes it) and rate-limits by diagnosis slug. A failed proofreading correction used
# to show only the outcome notice, so the same denial was named by two of the three
# features that share `inject/replace.py` and not by the third. These run the REAL
# `_report_failure`; only the desktop notifier is replaced, by a recorder.

PERMISSION_TITLE = "YazSes is not allowed to type"


def _record_causes_and_notices(monkeypatch, d) -> list[tuple[str, str]]:
    """One ordered list of ("cause", title) and ("outcome", title) entries."""
    seen: list[tuple[str, str]] = []

    def _toast(title, body, **_kw):
        seen.append(("cause", title))
        # Neither the dictation nor the correction may reach a toast.
        assert "wrong" not in f"{title} {body}".lower()
        assert "right file" not in f"{title} {body}".lower()

    monkeypatch.setattr("yazses.system.notify.notify", _toast)
    monkeypatch.setattr(d, "_notify_mic", lambda title, body, **kw: seen.append(("outcome", title)))
    return seen


@pytest.mark.parametrize(
    "fail",
    [
        {("type", 1): "denied"},       # the correction is refused after the erase
        {("backspace", 0): "denied"},  # the erase itself is refused
    ],
    ids=["typing-denied", "erase-denied"],
)
def test_a_denied_correction_names_the_cause_once_then_the_outcome(monkeypatch, fail):
    d, _inj, _notes, _copied = _armed_daemon(monkeypatch, fail)
    seen = _record_causes_and_notices(monkeypatch, d)
    _correct(d)
    assert [kind for kind, _ in seen] == ["cause", "outcome"], (
        "the cause first, then where the words are — the order Spoken Edit and "
        "Punch-In use"
    )
    assert seen[0][1] == PERMISSION_TITLE
    assert "inject-permission" in d._diagnosed_at


def test_a_correction_that_lands_names_no_cause(monkeypatch):
    d, inj, _notes, _copied = _armed_daemon(monkeypatch)
    seen = _record_causes_and_notices(monkeypatch, d)
    _correct(d)
    assert inj.screen == "send the right file"
    assert seen == []


def test_a_cause_already_named_is_not_repeated_but_the_outcome_still_is(monkeypatch):
    """The rate limit is the daemon's one record, not a per-feature one: the same
    denial just reported for an ordinary burst is not toasted again by proofreading,
    while the outcome notice — where the user's words are — always shows."""
    d, inj, _notes, _copied = _armed_daemon(monkeypatch, {("type", 1): "denied"})
    seen = _record_causes_and_notices(monkeypatch, d)
    assert d._report_failure(PermissionError(13, "Permission denied", "/dev/uinput"),
                             "inject") is not None
    assert seen == [("cause", PERMISSION_TITLE)]
    _correct(d)
    assert [kind for kind, _ in seen] == ["cause", "outcome"]
    assert inj.screen == FIRST, "the erased words were still typed back"


def test_proofback_and_punch_in_share_one_rate_limit(monkeypatch):
    """A denied proofreading correction, then a denied Punch-In on the same daemon:
    one cause toast between them, and an outcome notice for each."""
    # type #0 FIRST, #1 the correction (denied), #2 its restore, #3 the Punch-In
    # retype (denied), #4 its restore.
    d, inj, _notes, _copied = _armed_daemon(
        monkeypatch, {("type", 1): "denied", ("type", 3): "denied"}
    )
    seen = _record_causes_and_notices(monkeypatch, d)
    _correct(d)
    assert inj.screen == FIRST
    outcome = d._replace_last_burst(
        FIRST, "send the right file", inj, label="Punch-In",
        wording=Wording(noun="correction", span="your last dictation",
                        retry="Try the correction again."),
    )
    assert outcome.result == RESTORED
    assert inj.screen == FIRST
    assert [kind for kind, _ in seen] == ["cause", "outcome", "outcome"]
    assert seen[0][1] == PERMISSION_TITLE
