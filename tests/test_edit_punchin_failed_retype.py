"""Spoken Edit and Punch-In must not cost the user their words when the retype fails.

Both retype the whole last burst with two keyboard steps: backspaces over it, then the
edited text. Before this fix a retype that failed *after* the backspaces was reported
and nothing more — the dictated words were gone — and the "scratch that" ledger still
held the whole erased burst, so the next "scratch that" pressed that many backspaces
into the text *before* the dictation: the user's own.

They now follow Interruptible Proofreading's recovery rule (``inject/replace.py``):

* the new text landed -> the ledger and [timeline] hold it;
* it failed -> the erased words are typed back, and the records stand;
* the restore failed too, or the erase stopped part-way -> the erased words go to the
  clipboard and the records are dropped (what is on screen is uncertain);
* the clipboard failed as well -> the notice says nothing was saved and points at the
  application's own undo;
* a partial erase is never typed over.

``_ScreenInjector`` is a text field — copied from ``test_proofback_daemon_wiring.py``
and extended with the ``BackSpace`` key sequence "scratch that" sends — whose calls can
be scripted to fail. The field starts with text the USER typed, which no outcome and no
later "scratch that" may touch.
"""
from __future__ import annotations

import re

import numpy as np
import pytest

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.inject.replace import (
    REPLACED,
    RESCUED,
    RESTORED,
    UNSAVED,
    InjectionTally,
    Span,
    Wording,
    run_replacement,
    settle_replacement,
)
from yazses.platform import get_platform

USER = "Dear Ana, "            # typed by the user, never by YazSes
BURST = "the quick brown fox"  # the dictation YazSes typed
EDITS = {
    # feature -> the text it retypes BURST as
    "spoken_edit": "the quick brown cat",
    "punch_in": "the quick brown ox",
}
# Words of the dictation (old and new). No notice may contain any of them.
DICTATED_WORDS = ("quick", "brown", "fox", "cat")


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def start(self):
        pass

    def stop(self):
        return self._audio


class _FakeEngine:
    def __init__(self, text=""):
        self.text = text

    def transcribe(self, *args, **kwargs):
        return self.text


class _ScreenInjector:
    """A text field. ``fail[(kind, n)]`` scripts the n-th call of ``kind`` (0-based).

    ``"raise"`` raises having delivered nothing, ``"false"`` returns False having
    delivered nothing, and an int delivers that many characters (or backspaces) and
    then raises — a backend cut off part-way. ``inject_key_sequence`` deletes one
    character per ``"BackSpace"``, as "scratch that" sends them.
    """

    def __init__(self, screen: str = "", fail: dict | None = None) -> None:
        self.screen = screen
        self.fail = dict(fail or {})
        self.ops: list[tuple[str, object]] = []
        self._calls = {"type": 0, "backspace": 0}

    def _mode(self, kind: str):
        n = self._calls[kind]
        self._calls[kind] += 1
        return self.fail.get((kind, n))

    def inject(self, text):
        mode = self._mode("type")
        self.ops.append(("type", text))
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
        if mode == "raise":
            raise RuntimeError("backspaces refused")
        if mode == "false":
            return False
        count = mode if isinstance(mode, int) else n
        self.screen = self.screen[: max(0, len(self.screen) - count)]
        if isinstance(mode, int):
            raise RuntimeError("backspaces cut off")
        return None

    def inject_key_sequence(self, keys):
        self.ops.append(("keys", tuple(keys)))
        count = sum(1 for k in keys if k == "BackSpace")
        self.screen = self.screen[: max(0, len(self.screen) - count)]


def _daemon(monkeypatch, fail=None, *, clipboard_ok=True):
    """A daemon that has dictated BURST after the user's own USER text."""
    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.commands.enabled = False
    cfg.commands.spoken_edit = True
    cfg.punch_in.enabled = True
    cfg.streaming.enabled = False
    cfg.revise.enabled = True
    cfg.timeline.enabled = True
    cfg.injection.continuation_window_ms = 0
    d = Daemon(config=cfg, platform=get_platform())
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _ScreenInjector(USER, fail)
    d._injector = inj
    d._state.target_ok = True

    notes: list[tuple[str, str]] = []
    monkeypatch.setattr(d, "_notify_mic", lambda title, body, **kw: notes.append((title, body)))
    reported: list[str] = []
    monkeypatch.setattr(d, "_report_failure", lambda exc, where: reported.append(where))
    copied: list[str] = []

    def _set_clipboard(text, **kw):
        copied.append(text)
        return clipboard_ok

    monkeypatch.setattr("yazses.system.clipboard.set_clipboard", _set_clipboard)

    _dictate(d, BURST)  # type #0
    assert inj.screen == USER + BURST, "precondition: the burst was typed verbatim"
    assert d._ledger.last_text() == BURST
    assert d._timeline is not None and d._timeline.text() == BURST
    return d, inj, notes, reported, copied


def _dictate(d, text: str) -> None:
    d._engine.text = text
    d._on_hold_end()


def _apply(d, feature: str):
    """Run the feature against BURST; return (event, punch-in result or None)."""
    event: dict = {}
    if feature == "spoken_edit":
        assert d._try_spoken_edit("change fox to cat", event) is True
        return event, None
    return event, d._apply_punch_in("brown ox")


def _no_notice_quotes_the_dictation(notes) -> None:
    for title, body in notes:
        text = f"{title} {body}".lower()
        for word in DICTATED_WORDS:
            # Whole words: "cat" is inside "application", which the undo hint names.
            assert not re.search(rf"\b{word}\b", text), f"a notice quoted: {word!r}"


FEATURES = ["spoken_edit", "punch_in"]


# ---- each outcome, on each path ---------------------------------------------------


@pytest.mark.parametrize("feature", FEATURES)
def test_a_retype_that_lands_keeps_screen_and_records_in_step(monkeypatch, feature):
    d, inj, notes, reported, copied = _daemon(monkeypatch)
    event, result = _apply(d, feature)
    new = EDITS[feature]
    assert inj.screen == USER + new
    assert d._ledger.last_text() == new and len(d._ledger) == 1
    # The [timeline] used to keep the pre-edit burst here: "undo burst" would then
    # have pressed len(BURST) backspaces over a burst of a different length.
    assert d._timeline.text() == new
    assert notes == [] and copied == [] and reported == []
    if result is not None:
        assert result["ok"] is True
    else:
        assert "discard_reason" not in event


@pytest.mark.parametrize("mode", ["raise", "false"])
@pytest.mark.parametrize("feature", FEATURES)
def test_a_failed_retype_types_the_erased_words_back(monkeypatch, feature, mode):
    # type #0 was BURST; type #1 is the new text; type #2 the restore.
    d, inj, notes, reported, copied = _daemon(monkeypatch, {("type", 1): mode})
    event, result = _apply(d, feature)
    assert inj.ops[-3:] == [
        ("backspace", len(BURST)),
        ("type", EDITS[feature]),
        ("type", BURST),
    ]
    assert inj.screen == USER + BURST, "the user's dictated words are back"
    assert d._ledger.last_text() == BURST and len(d._ledger) == 1
    assert d._timeline.text() == BURST
    assert copied == []
    assert reported == ["inject"], "the cause is still diagnosed"
    assert len(notes) == 1 and "not typed" in notes[0][0].lower()
    assert "typed back" in notes[0][1]
    assert d._state.last_error and RESTORED in d._state.last_error
    _no_notice_quotes_the_dictation(notes)
    if result is not None:
        assert result["ok"] is False and result["applied"] is False
        assert result["result"] == RESTORED
        assert "typed back" in result["reason"]
    else:
        assert event["discard_reason"] == "spoken_edit_not_typed"
        assert event["spoken_edit_result"] == RESTORED


@pytest.mark.parametrize("feature", FEATURES)
def test_a_failed_restore_puts_the_erased_words_on_the_clipboard(monkeypatch, feature):
    d, inj, notes, reported, copied = _daemon(
        monkeypatch, {("type", 1): "raise", ("type", 2): "raise"}
    )
    _, result = _apply(d, feature)
    assert copied == [BURST]
    assert inj.screen == USER
    # The record is dropped: "scratch that" now presses no backspaces, not 19 into
    # the user's own text.
    assert d._ledger.last_text() == "" and len(d._ledger) == 0
    assert d._timeline.text() == ""
    assert len(notes) == 1
    title, body = notes[0]
    assert "clipboard" in title.lower() and "on the clipboard" in body
    _no_notice_quotes_the_dictation(notes)
    if result is not None:
        assert result["result"] == RESCUED and "on the clipboard" in result["reason"]


@pytest.mark.parametrize("feature", FEATURES)
def test_a_failed_clipboard_copy_points_at_the_apps_undo(monkeypatch, feature):
    d, inj, notes, reported, copied = _daemon(
        monkeypatch, {("type", 1): "raise", ("type", 2): "raise"}, clipboard_ok=False
    )
    _, result = _apply(d, feature)
    assert copied == [BURST]
    assert len(notes) == 1
    title, body = notes[0]
    assert "could not be saved" in title
    assert "clipboard copy failed" in body and "undo" in body.lower()
    assert len(d._ledger) == 0 and d._timeline.text() == ""
    _no_notice_quotes_the_dictation(notes)
    if result is not None:
        assert result["result"] == UNSAVED and "could not be saved" in result["reason"]


@pytest.mark.parametrize("feature", FEATURES)
def test_an_erase_cut_off_part_way_is_never_typed_over(monkeypatch, feature):
    # Four of the nineteen backspaces land, then the backend fails.
    d, inj, notes, reported, copied = _daemon(monkeypatch, {("backspace", 0): 4})
    _apply(d, feature)
    assert inj.screen == USER + BURST[:-4]
    assert ("type", EDITS[feature]) not in inj.ops, "never type over a partial erase"
    assert ("type", BURST) not in inj.ops[1:], "nor restore over it"
    assert copied == [BURST]
    assert len(d._ledger) == 0 and d._timeline.text() == ""
    assert len(notes) == 1 and "could not finish erasing" in notes[0][1]
    assert reported == ["inject"]


@pytest.mark.parametrize("feature", FEATURES)
def test_a_retype_cut_off_part_way_never_loses_the_erased_words(monkeypatch, feature):
    # The new-text call delivers three characters and fails. Whether a failing call
    # typed anything is invisible to the daemon, so the fragment stays and the erased
    # words are typed back after it: visible and editable, where erasing them was not.
    d, inj, notes, reported, copied = _daemon(monkeypatch, {("type", 1): 3})
    _apply(d, feature)
    new = EDITS[feature]
    assert inj.screen == USER + new[:3] + BURST
    # Undo deletes by count: the record may under-count the burst, never over-count.
    assert d._ledger.last_text() == BURST
    assert len(notes) == 1


# ---- "scratch that" after a failure deletes nothing outside the dictation ---------

SCRIPTS = {
    "restored": ({("type", 1): "raise"}, True),
    "clipboard": ({("type", 1): "raise", ("type", 2): "raise"}, True),
    "clipboard_failed": ({("type", 1): "raise", ("type", 2): "raise"}, False),
    "partial_erase": ({("backspace", 0): 4}, True),
    "cut_off": ({("type", 1): 3}, True),
}


@pytest.mark.parametrize("script", sorted(SCRIPTS))
@pytest.mark.parametrize("feature", FEATURES)
def test_scratch_that_after_a_failure_never_reaches_the_users_text(
    monkeypatch, feature, script
):
    fail, clipboard_ok = SCRIPTS[script]
    d, inj, notes, reported, copied = _daemon(monkeypatch, fail, clipboard_ok=clipboard_ok)
    _apply(d, feature)
    before = inj.screen
    _dictate(d, "scratch that")
    assert inj.screen.startswith(USER), (
        f"'scratch that' deleted the user's own text: {inj.screen!r}"
    )
    # It deletes only from what this failure left on screen.
    assert before.startswith(inj.screen)
    if script == "restored":
        assert inj.screen == USER, "the restored burst is still one undoable burst"


# ---- the pure module, directly -----------------------------------------------------

_WORDING = Wording(noun="edit", span="your last dictation", retry="Say the edit again.")


def test_a_whole_burst_span_keeps_nothing():
    span = Span(BURST)
    assert span.kept == "" and span.erased == BURST


def test_a_span_rejects_a_kept_text_that_is_not_a_prefix():
    with pytest.raises(ValueError):
        Span(BURST, kept="quick")


@pytest.mark.parametrize(
    "erased,typed,restored,copied,expected",
    [
        (True, True, False, False, REPLACED),
        (True, False, True, False, RESTORED),
        (True, False, False, True, RESCUED),
        (True, False, False, False, UNSAVED),
        (False, False, False, True, RESCUED),
        (False, True, True, True, RESCUED),  # typed/restored ignored after a bad erase
    ],
)
def test_settle_for_a_whole_burst(erased, typed, restored, copied, expected):
    out = settle_replacement(Span(BURST), "new", erased=erased, typed=typed,
                             restored=restored, copied=copied, wording=_WORDING)
    assert out.result == expected
    assert len(out.record) <= len(out.screen)
    if expected == REPLACED:
        assert out.record == "" and out.typed and out.notice is None
    elif expected == RESTORED:
        assert out.record == BURST and out.notice is not None
        assert out.notice[0] == "⌨ Edit not typed"
    else:
        assert out.record == "", "uncertain screen: the whole-burst record is dropped"
        assert out.notice is not None and "your last dictation" in out.notice[1]


def test_run_replacement_steps_on_a_scripted_field():
    inj = _ScreenInjector(USER + BURST, {("type", 0): "raise"})
    copies: list[str] = []
    steps = run_replacement(Span(BURST), "new", inj, copy=lambda t: copies.append(t) or True)
    assert steps.erased and not steps.typed and steps.restored and not steps.copied
    assert isinstance(steps.type_error, RuntimeError) and steps.error is steps.type_error
    assert steps.restore_error is None and steps.delivered == 0
    assert inj.screen == USER + BURST and copies == []


def test_run_replacement_never_raises_even_when_the_clipboard_does():
    inj = _ScreenInjector(USER + BURST, {("backspace", 0): "raise"})

    def broken_copy(_text):
        raise OSError("no clipboard")

    steps = run_replacement(Span(BURST), "new", inj, copy=broken_copy)
    assert not steps.erased and not steps.copied
    assert isinstance(steps.erase_error, RuntimeError)
    assert inj.screen == USER + BURST
    assert [op for op in inj.ops if op[0] == "type"] == []


def test_run_replacement_passes_its_tally_to_a_paced_typer():
    inj = _ScreenInjector(USER + BURST, {("type", 1): "raise"})

    def paced(text: str, tally: InjectionTally) -> None:
        tally.inject(text[:2])   # lands
        tally.inject(text[2:])   # fails

    steps = run_replacement(Span(BURST), "new", inj, type_text=paced)
    assert steps.delivered == 2 and steps.restored
    # The chunk that certainly landed is deleted before the erased words come back.
    assert inj.ops[-2:] == [("backspace", 2), ("type", BURST)]
    assert inj.screen == USER + BURST


def test_proofback_keeps_its_imports_and_its_wording():
    """The move to inject/replace.py left proofback's public names where they were."""
    from yazses.inject import replace
    from yazses.proofback import bargein

    assert bargein.REPLACED is replace.REPLACED
    assert bargein.RESCUED is replace.RESCUED
    assert bargein.RESTORED is replace.RESTORED
    assert bargein.UNSAVED is replace.UNSAVED
    assert bargein.InjectionTally is replace.InjectionTally
    assert bargein.PROOFBACK_WORDING.noun == "correction"
