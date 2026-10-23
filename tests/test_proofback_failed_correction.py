"""A proofreading correction that cannot be typed must not cost the user their words.

Interruptible Proofreading (ADR-v2-108) replaces the tail of the last burst with two
keyboard steps: backspaces, then the correction. Before this fix a correction that
failed *after* the backspaces left the dictated words erased with nothing in their
place, and the "scratch that" / [timeline] records still described the erased text, so
the next undo pressed backspaces into whatever came before the burst.

The decision is pure (``settle_replacement``): erase result x type result x restore
result x clipboard result -> what is on screen, what the undo records say, and what
the user is told. Pinned here for every combination:

* the correction landed -> records are the kept prefix (the correction is recorded
  as its own burst by the caller), no notice;
* it failed and the erased words were typed back -> records unchanged, a notice;
* the restore failed too (or the erase itself failed) -> the erased words go to the
  clipboard, records claim only the kept prefix, and the notice says where they are;
* the clipboard failed as well -> the notice says nothing was saved and points at the
  application's own undo — never silence.

And for every outcome: the records never claim a longer burst than the screen holds,
and no notice quotes the dictated words.
"""
from __future__ import annotations

import itertools

import pytest

from yazses.proofback.bargein import (
    REPLACED,
    RESCUED,
    RESTORED,
    UNSAVED,
    InjectionTally,
    ProofTarget,
    rescue_text,
    resolve_barge_in,
    settle_replacement,
)

ORIGINAL = "send the wrong file"
CORRECTION = "right file"


def _target() -> ProofTarget:
    t = resolve_barge_in(ORIGINAL, ORIGINAL, 2, stamp=7.0)
    assert t is not None
    return t


def test_the_erased_text_is_the_tail_of_the_burst():
    t = _target()
    assert t.kept == "send the "
    assert t.erased == "wrong file"
    assert len(t.erased) == t.erase_count
    assert t.kept + t.erased == t.original


# ---- each outcome -----------------------------------------------------------------

def test_a_correction_that_lands_replaces_the_tail_and_tells_nobody():
    out = settle_replacement(_target(), CORRECTION, erased=True, typed=True)
    assert out.result == REPLACED
    assert out.typed is True
    assert out.screen == "send the right file" and out.screen_known is True
    # The caller records the correction as a burst of its own after this one.
    assert out.record == "send the "
    assert out.notice is None


def test_a_failed_correction_with_a_successful_restore_leaves_the_records_alone():
    out = settle_replacement(_target(), CORRECTION, erased=True, typed=False, restored=True)
    assert out.result == RESTORED
    assert out.typed is False
    assert out.screen == ORIGINAL
    assert out.record == ORIGINAL
    assert out.notice is not None
    title, body = out.notice
    assert "not typed" in title.lower()
    assert "typed back" in body and "again" in body


def test_a_failed_restore_puts_the_erased_words_on_the_clipboard_and_says_so():
    t = _target()
    assert rescue_text(t, erased=True, typed=False, restored=False) == "wrong file"
    out = settle_replacement(t, CORRECTION, erased=True, typed=False, restored=False,
                             copied=True)
    assert out.result == RESCUED
    assert out.typed is False
    assert out.screen == "send the " and out.screen_known is False
    assert out.record == "send the "
    assert out.notice is not None
    title, body = out.notice
    assert "clipboard" in title.lower()
    assert "on the clipboard" in body and "paste" in body.lower()


def test_a_failed_clipboard_copy_is_reported_never_silent():
    out = settle_replacement(_target(), CORRECTION, erased=True, typed=False,
                             restored=False, copied=False)
    assert out.result == UNSAVED
    assert out.notice is not None
    title, body = out.notice
    assert "could not be saved" in title
    assert "clipboard copy failed" in body
    assert "undo" in body.lower()  # the one recovery left: the application's own undo


def test_a_failed_erase_never_types_the_correction_and_rescues_the_tail():
    t = _target()
    # The erase stopped at an unknown point, so typing over it would land in the wrong
    # place; and no restore is tried, because nobody knows how much is gone.
    assert rescue_text(t, erased=False, typed=False, restored=False) == "wrong file"
    out = settle_replacement(t, CORRECTION, erased=False, typed=True, restored=True,
                             copied=True)
    assert out.result == RESCUED
    assert out.typed is False
    assert out.record == "send the "
    assert out.notice is not None
    assert "could not finish erasing" in out.notice[1]


@pytest.mark.parametrize("typed,restored", [(True, False), (False, True)])
def test_no_rescue_is_needed_when_the_screen_is_whole(typed, restored):
    assert rescue_text(_target(), erased=True, typed=typed, restored=restored) is None


def test_a_target_at_the_first_word_drops_the_record_when_the_tail_is_lost():
    t = resolve_barge_in("wrong file", "wrong file", 0, stamp=1.0)
    assert t is not None and t.kept == ""
    out = settle_replacement(t, CORRECTION, erased=True, copied=True)
    assert out.result == RESCUED
    assert out.record == ""  # "" drops the burst: nothing of it is certainly on screen


# ---- properties over every combination --------------------------------------------

_COMBOS = list(itertools.product([False, True], repeat=4))


@pytest.mark.parametrize("erased,typed,restored,copied", _COMBOS)
def test_the_records_never_claim_more_than_the_screen_holds(erased, typed, restored, copied):
    t = _target()
    out = settle_replacement(t, CORRECTION, erased=erased, typed=typed,
                             restored=restored, copied=copied)
    assert len(out.record) <= len(out.screen)
    assert out.screen.startswith(t.kept)
    # The correction counts as typed only after an erase that landed.
    assert out.typed == (erased and typed)
    assert (out.notice is None) == (out.result == REPLACED)


@pytest.mark.parametrize("erased,typed,restored,copied", _COMBOS)
def test_no_notice_quotes_the_dictated_words(erased, typed, restored, copied):
    out = settle_replacement(_target(), CORRECTION, erased=erased, typed=typed,
                             restored=restored, copied=copied)
    if out.notice is not None:
        text = " ".join(out.notice)
        for word in ("wrong", "right", "send"):
            assert word not in text


# ---- InjectionTally ---------------------------------------------------------------

class _Backend:
    def __init__(self, result=None, raises=False) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple[str, object]] = []

    def inject(self, text):
        self.calls.append(("type", text))
        if self.raises:
            raise OSError("refused")
        return self.result

    def inject_backspaces(self, n):
        self.calls.append(("backspace", n))
        if self.raises:
            raise OSError("refused")
        return self.result

    def inject_key_sequence(self, keys):
        self.calls.append(("keys", tuple(keys)))
        return self.result


def test_the_tally_counts_only_calls_that_returned():
    backend = _Backend()
    tally = InjectionTally(backend)
    tally.inject("right")
    tally.inject(" file")
    assert tally.typed == len("right file")
    backend.raises = True
    with pytest.raises(OSError):
        tally.inject(" more")
    assert tally.typed == len("right file")


@pytest.mark.parametrize("call", ["inject", "inject_backspaces", "inject_key_sequence"])
def test_a_backend_that_returns_false_is_a_failure(call):
    tally = InjectionTally(_Backend(result=False))
    arg = {"inject": "x", "inject_backspaces": 3, "inject_key_sequence": ["ctrl+z"]}[call]
    with pytest.raises(RuntimeError):
        getattr(tally, call)(arg)
    assert tally.typed == 0


def test_a_backend_that_returns_none_is_a_success():
    tally = InjectionTally(_Backend(result=None))
    tally.inject("abc")
    tally.inject_backspaces(2)
    assert tally.typed == 3
