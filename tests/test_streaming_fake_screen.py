"""Phase R1 of the streaming replay protocol: current classes against a fake screen.

``design/specs/streaming-commit-replay-protocol.md`` section 6, Phase R1: drive the
current ``StreamingEngine`` with a deterministic fake decoder and the current
``StreamingInjector`` with a fake screen that models caret, selection, focus,
partial effects and failure.  Each hazard is written twice:

* a **current-behaviour** test that pins what the code does today, so a change in
  either direction is noticed; and
* where the desired policy (the pure oracle in ``yazses.stt.streaming_replay``)
  forbids that behaviour, a **strict xfail** naming #796.  It turns into an
  XPASS -- and so a failure -- the day the defect is fixed, and must then be
  promoted to an ordinary test.

Evidence class: synthetic, fake-injector only.  Nothing here says anything about a
real editor, X11, Wayland, macOS or Windows.  In particular the fake screen moves
the caret and deletes by an *approximate* grapheme cluster (base + combining marks,
variation selectors and ZWJ joins) and in logical order; real editors differ from
each other, and visual caret movement inside right-to-left text is not modelled.
No sleeps: the engine's decode loop is run on the test thread for an exact number
of cycles.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest

from yazses.inject.streaming import StreamingInjector
from yazses.stt.streaming import StreamingEngine
from yazses.stt.streaming_replay import parse_trace, reduce_trace

FIXTURE = Path(__file__).resolve().parents[1] / "design/research/fixtures/streaming-replay-v1.jsonl"
ORACLE = {
    t.id: t
    for t in (
        parse_trace(json.loads(line))
        for line in FIXTURE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
}

ISSUE = "#796"
ZWJ = "‍"


# ------------------------------------------------------------------ fake screen


def cluster_starts(text: str) -> list[int]:
    """Start offsets of approximate grapheme clusters (model assumption, see module doc)."""
    starts: list[int] = []
    i = 0
    while i < len(text):
        starts.append(i)
        i += 1
        while i < len(text):
            ch = text[i]
            if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me") or (
                "︀" <= ch <= "️"
            ):
                i += 1
            elif ch == ZWJ:
                i += 2  # the joiner glues the next code point onto this cluster
            else:
                break
    return starts


def cluster_count(text: str) -> int:
    return len(cluster_starts(text))


@dataclass
class Field:
    text: str = ""
    caret: int = 0
    anchor: int | None = None  # selection anchor; None = no selection

    def _prev_boundary(self, pos: int) -> int:
        before = [s for s in cluster_starts(self.text) if s < pos]
        return before[-1] if before else 0

    def _delete_selection(self) -> bool:
        if self.anchor is None or self.anchor == self.caret:
            self.anchor = None
            return False
        lo, hi = sorted((self.anchor, self.caret))
        self.text = self.text[:lo] + self.text[hi:]
        self.caret, self.anchor = lo, None
        return True

    def type(self, s: str) -> None:
        self._delete_selection()
        self.text = self.text[: self.caret] + s + self.text[self.caret :]
        self.caret += len(s)

    def shift_left(self) -> None:
        if self.anchor is None:
            self.anchor = self.caret
        self.caret = self._prev_boundary(self.caret)

    def backspace(self) -> None:
        if self._delete_selection():
            return
        start = self._prev_boundary(self.caret)
        self.text = self.text[:start] + self.text[self.caret :]
        self.caret = start


class FakeScreen:
    """An ``InjectorBackend`` that edits whichever fake field has focus."""

    def __init__(self, **fields: str) -> None:
        self.fields = {name: Field(text, len(text)) for name, text in fields.items()}
        self.focused = next(iter(self.fields))
        self.fail_after: int | None = None  # type this many chars of the next inject, then raise

    @property
    def field(self) -> Field:
        return self.fields[self.focused]

    def focus(self, name: str) -> None:
        self.focused = name

    def inject(self, text: str) -> None:
        if self.fail_after is not None:
            done, self.fail_after = text[: self.fail_after], None
            self.field.type(done)
            raise RuntimeError("injector died after a partial effect")
        self.field.type(text)

    def inject_backspaces(self, count: int) -> None:
        for _ in range(count):
            self.field.backspace()

    def inject_key_sequence(self, keys: list[str]) -> None:
        for key in keys:
            if key != "shift+Left":
                raise AssertionError(f"fake screen does not model {key!r}")
            self.field.shift_left()


def test_fake_screen_models_clusters_and_selection():
    f = Field("ab" + "é" + "\U0001f469" + ZWJ + "\U0001f4bb", 0)
    assert cluster_count(f.text) == 4 and len(f.text) == 7
    f.caret = len(f.text)
    f.shift_left()
    f.shift_left()
    f.type("Z")
    assert f.text == "abZ"


# ---------------------------------------------------------- engine single slot


class ScriptedDecoder:
    def __init__(self, responses: list[str]) -> None:
        self._responses = responses
        self.calls = 0

    def decode_window(self, audio) -> str:
        text = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return text


class ScriptedStopToken:
    """Lets exactly ``cycles`` decode cycles of ``_decode_loop`` run, then stops it."""

    def __init__(self, cycles: int) -> None:
        self._left, self._stopped = cycles, False

    def is_set(self) -> bool:
        return self._stopped

    def wait(self, timeout: float | None = None) -> bool:
        if self._left <= 0:
            self._stopped = True
        self._left -= 1
        return self._stopped


def _engine_after_three_unpolled_cycles() -> tuple[StreamingEngine, ScriptedDecoder]:
    decoder = ScriptedDecoder(["a b", "a b c", "a b c d", "a b c d"])
    engine = StreamingEngine(decoder, partial_interval_ms=300)
    engine.push(np.zeros(16000, dtype=np.float32))
    # Cycle 1 confirms nothing, cycle 2 confirms "a b", cycle 3 confirms "a b c".
    # Nobody polls between cycles 2 and 3: the poll thread missed a decode interval.
    engine._decode_loop(ScriptedStopToken(3))  # noqa: SLF001
    return engine, decoder


def test_unpolled_delta_is_overwritten_but_final_text_stays_correct():
    """CURRENT: one pending slot -- the "a b" delta is replaced by " c" and lost.

    The count still advances (char_count says 5 characters were emitted while only
    2 can ever be typed), yet the hold-release correction replaces exactly what was
    typed, so the final text on screen is right.
    """
    engine, decoder = _engine_after_three_unpolled_cycles()
    assert decoder.calls == 3
    partial = engine.get_partial()
    assert partial is not None
    assert (partial.text, partial.char_count) == (" c", len("a b c"))
    assert engine.get_partial() is None

    screen = FakeScreen(editor="")
    si = StreamingInjector(screen)
    si.inject_partial(partial.text)
    assert screen.field.text == " c"  # the preview skipped "a b"
    si.commit(engine.commit())
    assert screen.field.text == "a b c d"


@pytest.mark.xfail(
    strict=True,
    reason=(
        f"{ISSUE}: StreamingEngine keeps one pending partial; a delta not polled before the "
        "next decode cycle is overwritten while _last_emitted still advances, so the preview "
        "misses confirmed words. How often the daemon's poll misses a cycle is unmeasured."
    ),
)
def test_desired_every_confirmed_delta_reaches_the_reader():
    engine, _ = _engine_after_three_unpolled_cycles()
    seen = []
    while (p := engine.get_partial()) is not None:
        seen.append(p.text)
    assert "".join(seen) == "a b c"


# ------------------------------------------------- focus or caret change (SR-006)


def _preview_then_switch_focus() -> tuple[FakeScreen, StreamingInjector]:
    screen = FakeScreen(editor_a="", editor_b="foreign text")
    si = StreamingInjector(screen)
    si.inject_partial("draft")
    screen.focus("editor_b")  # the user (or a notification) moved focus mid-dictation
    return screen, si


def _cleanup(si: StreamingInjector, how: str) -> None:
    if how == "commit":
        si.commit("final")
    else:
        si.cancel()


def test_oracle_forbids_writes_and_deletions_after_focus_change():
    r = reduce_trace(ORACLE["SR-006"])
    assert r.target_writes == () and r.no_forbidden_deletions


@pytest.mark.parametrize(
    ("how", "current_b"),
    [("commit", "foreignfinal"), ("cancel", "foreign")],
)
def test_cleanup_after_focus_change_current_behaviour(how, current_b):
    """CURRENT: N = chars typed in editor A are selected/deleted blindly in editor B."""
    screen, si = _preview_then_switch_focus()
    _cleanup(si, how)
    assert screen.fields["editor_b"].text == current_b
    assert screen.fields["editor_a"].text == "draft"  # the preview is orphaned


@pytest.mark.xfail(
    strict=True,
    reason=(
        f"{ISSUE} (SR-006): StreamingInjector.commit()/cancel() send shift+Left / BackSpace x "
        "chars_injected without checking focus, deleting foreign text in the new window "
        "(fake-screen evidence only)."
    ),
)
@pytest.mark.parametrize("how", ["commit", "cancel"])
def test_desired_cleanup_after_focus_change_leaves_foreign_text(how):
    screen, si = _preview_then_switch_focus()
    _cleanup(si, how)
    assert screen.fields["editor_b"].text.startswith("foreign text")


def _preview_then_move_caret() -> tuple[FakeScreen, StreamingInjector]:
    screen = FakeScreen(editor="abc ")
    si = StreamingInjector(screen)
    si.inject_partial("draft")
    screen.field.caret = 3  # the user clicked between "abc" and " draft"
    return screen, si


def test_cancel_after_caret_move_current_behaviour():
    """CURRENT: 5 backspaces eat the user's "abc" and leave the preview behind."""
    screen, si = _preview_then_move_caret()
    si.cancel()
    assert screen.field.text == " draft"


@pytest.mark.xfail(
    strict=True,
    reason=f"{ISSUE}: cancel() backspaces blindly from wherever the caret now is",
)
def test_desired_cancel_after_caret_move_keeps_user_text():
    screen, si = _preview_then_move_caret()
    si.cancel()
    assert screen.field.text.startswith("abc")


# ---------------------------------------------- unit mismatch (SR-011 family)

EMOJI_COMBINING = "\U0001f469" + ZWJ + "\U0001f4bb café"  # 9 code points, 6 clusters
ARABIC_HARAKAT = "سَلام"  # 5 code points, 4 clusters
ARABIC_PLAIN = "مرحبا"  # 5 code points, 5 clusters (control)

UNIT_CASES = [
    pytest.param(EMOJI_COMBINING, "keX", id="zwj-emoji+combining"),
    pytest.param(ARABIC_HARAKAT, "keepX", id="rtl-with-harakat"),
    pytest.param(ARABIC_PLAIN, "keep|X", id="rtl-plain-control"),
    pytest.param("hello", "keep|X", id="ascii-control"),
]


def test_oracle_never_types_the_unicode_preview():
    r = reduce_trace(ORACLE["SR-011"])
    assert r.target_writes == () and r.no_forbidden_deletions


@pytest.mark.parametrize(("partial", "current"), UNIT_CASES)
def test_commit_counts_code_points_current_behaviour(partial, current):
    """CURRENT: chars_injected is len() in code points; the caret moves per cluster."""
    screen = FakeScreen(editor="keep|")
    si = StreamingInjector(screen)
    si.inject_partial(partial)
    assert si.chars_injected == len(partial)
    si.commit("X")
    assert screen.field.text == current
    assert len("keep|") - len(current.removesuffix("X")) == len(partial) - cluster_count(partial)


@pytest.mark.xfail(
    strict=True,
    reason=(
        f"{ISSUE} (SR-011): selection length is len(text) code points, not caret units, so "
        "a cluster-moving editor loses foreign text (fake-screen model, not a real editor)"
    ),
)
@pytest.mark.parametrize(
    "partial", [EMOJI_COMBINING, ARABIC_HARAKAT], ids=["zwj-emoji+combining", "rtl-with-harakat"]
)
def test_desired_commit_keeps_text_before_a_multi_unit_preview(partial):
    screen = FakeScreen(editor="keep|")
    si = StreamingInjector(screen)
    si.inject_partial(partial)
    si.commit("X")
    assert screen.field.text == "keep|X"


# ------------------------------------------------------- late partial (SR-005)


def test_late_partial_after_seal_is_dropped_like_the_oracle():
    screen = FakeScreen(editor="")
    si = StreamingInjector(screen)
    si.inject_partial("do")
    si.commit("done")
    si.inject_partial("stale")  # the poll thread delivers after hold-release sealed it
    assert screen.field.text == "done"
    assert reduce_trace(ORACLE["SR-005"]).target_writes == (screen.field.text,)


# ------------------------------------------------- injector partial effect


def test_partial_effect_failure_leaves_untracked_text_current_behaviour():
    """CURRENT: a preview inject that types "dr" then raises is never counted.

    The failure propagates, chars_injected stays 0 and the injector is not sealed,
    so the later commit types the final text behind two orphan characters.  The
    oracle's answer for a partial-effect failure is "indeterminate, never retry
    blindly" (SR-008); no current state represents that.
    """
    screen = FakeScreen(editor="")
    si = StreamingInjector(screen)
    screen.fail_after = 2
    with pytest.raises(RuntimeError):
        si.inject_partial("draft")
    assert (si.chars_injected, si.sealed) == (0, False)
    si.commit("final")
    assert screen.field.text == "drfinal"
    assert reduce_trace(ORACLE["SR-008"]).indeterminate
