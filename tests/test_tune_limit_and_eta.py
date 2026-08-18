"""`yazses tune` had two speeds: about an hour, or skip the useful pass entirely.

Measured on a real corpus: 1621 clips through `small.en` on CPU at roughly 2.2 s
each — **about an hour** — and the only escape was `--no-retranscribe`, which drops
the pass that finds the actual mis-transcriptions. There was no middle.

`retranscribe(limit=)` had existed the whole time and **nothing called it**, and no
test referenced it either. Wiring it as written would have shipped the wrong feature:
`store.events()` is `ORDER BY id`, so a limit took the **oldest** clips — the least
relevant half, recorded with a model, microphone, threshold and vocabulary the user
may since have changed. Tuning exists to improve what dictation does *now*.

The other half is the estimate. "A large corpus can take a while" is honest and
useless: an hour is a decision — run it overnight, or use `--limit` — and "a while"
is not.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from yazses.learning.analysis import retranscribe
from yazses.learning.tuner import _eta, _format_eta


@dataclass
class _Rec:
    """Mirrors `store.EventRecord`'s fields.

    Complete rather than minimal on purpose: `run_tune` continues past
    re-transcription into `compute_edit_signals`, which reads the later text stages,
    so a stub carrying only what `retranscribe` touches fails several layers away
    from anything this file is testing.
    """

    id: int
    raw_text: str = "hello"
    has_audio: bool = True
    retx_text: str = ""
    ts: float = 0.0
    audio_secs: float | None = 1.0
    decode_ms: float | None = 100.0
    model: str | None = "base.en"
    level: float | None = 0.01
    sample_rate: int | None = 16000
    intent_type: str | None = "DICTATE"
    intent_action: str | None = None
    injected: bool = True
    discard_reason: str | None = None
    wrong_flag: bool = False
    edit_signal: float | None = None
    retx_distance: float | None = None
    cleaned_text: str = "hello"
    filtered_text: str = "hello"
    final_text: str = "hello"
    correction_text: str = ""


class _Store:
    """Just enough corpus for `retranscribe`. Records what was actually processed."""

    def __init__(self, n: int) -> None:
        # `ORDER BY id` — oldest first, exactly as the real store returns them.
        self._events = [_Rec(id=i) for i in range(1, n + 1)]
        self.processed: list[int] = []

    def events(self):
        return list(self._events)

    def load_audio(self, event_id: int):
        return (object(), 16000)

    def set_retx(self, event_id: int, text: str, distance: int) -> None:
        self.processed.append(event_id)


def _transcribe(audio, sr):
    return "hello"


# ---- the limit, and the direction that makes it worth having ---------------


def test_no_limit_processes_everything():
    store = _Store(10)
    assert retranscribe(store, _transcribe) == 10
    assert store.processed == list(range(1, 11))


def test_a_limit_takes_the_most_recent_clips_not_the_oldest():
    """The defect that would have shipped if the parameter had been wired as written.

    Oldest-first is the natural order of the table and the wrong half of the corpus:
    a month-old clip from a since-replaced microphone proposes fixes for a problem
    the user no longer has.
    """
    store = _Store(10)
    assert retranscribe(store, _transcribe, limit=3) == 3
    assert store.processed == [8, 9, 10], "must be the newest three, not 1-2-3"


def test_a_limit_larger_than_the_corpus_is_harmless():
    store = _Store(4)
    assert retranscribe(store, _transcribe, limit=99) == 4
    assert store.processed == [1, 2, 3, 4]


def test_a_zero_limit_processes_nothing():
    """Distinct from None. The CLI maps `--limit 0` to None ("all") precisely
    because a literal 0 here means "no clips", which as a flag would be a silent
    no-op that looks like a broken command."""
    store = _Store(5)
    assert retranscribe(store, _transcribe, limit=0) == 0
    assert store.processed == []


def test_the_total_reported_to_progress_matches_what_is_processed():
    """A progress bar that counts to a total it will never reach reads as a hang.

    Before the limit was honoured in the candidate list, `total` was clamped
    separately from the loop — two places to keep in step.
    """
    seen: list[tuple[int, int]] = []
    store = _Store(10)
    retranscribe(store, _transcribe, limit=4, progress=lambda d, t: seen.append((d, t)))
    assert seen[0] == (0, 4)
    assert seen[-1] == (4, 4)


def test_clips_already_re_transcribed_are_skipped_before_the_limit_applies():
    """Otherwise a repeat run with --limit would re-do the same newest N for ever
    and never reach anything older."""
    store = _Store(10)
    for rec in store._events[-3:]:
        rec.retx_text = "done"
    retranscribe(store, _transcribe, limit=2)
    assert store.processed == [6, 7], "the newest *unprocessed* two"


# ---- the estimate ----------------------------------------------------------


def test_no_estimate_before_anything_has_been_measured():
    """Silent rather than wrong: a rate needs elapsed time and at least one clip."""
    assert _eta(0, 100, [], lambda: 10.0) == ""
    assert _eta(0, 100, [0.0], lambda: 10.0) == ""
    assert _eta(5, 100, [10.0], lambda: 10.0) == "", "zero elapsed → no rate"


def test_no_estimate_on_the_final_tick():
    """"0 min left" on the last line reads as a fault rather than as completion."""
    assert _eta(100, 100, [0.0], lambda: 500.0) == ""


def test_the_estimate_scales_with_the_measured_rate():
    # 10 clips in 100 s → 10 s/clip → 90 clips remaining → 900 s.
    assert "15 min left" in _eta(10, 100, [0.0], lambda: 100.0)


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (30, "under a minute left"),
        (89, "under a minute left"),
        (600, "~10 min left"),
        (3300, "~55 min left"),
        (4200, "~70 min left"),
        (9000, "~2.5 h left"),
    ],
)
def test_durations_are_rounded_to_something_actionable(seconds, expected):
    """Coarse on purpose: the rate wanders with clip length, so "~52 min" claims a
    precision the measurement does not have. The only decision being supported is
    "wait" versus "come back later"."""
    assert _format_eta(seconds) == expected


# ---- the wiring ------------------------------------------------------------


def test_run_tune_passes_the_limit_through_and_prints_an_estimate():
    """The gap this closes: the parameter existed, was never called, and no test
    referenced it — so nothing would have noticed it being dropped again."""
    from pathlib import Path

    from yazses.config import Config
    from yazses.learning.tuner import run_tune

    store = _Store(60)
    lines: list[str] = []
    ticks = iter([0.0] + [float(i) for i in range(1, 400)])

    run_tune(
        store,  # type: ignore[arg-type]
        Config(),
        Path("/nonexistent/config.toml"),
        Path("/nonexistent/few_shots.toml"),
        do_apply=False,
        do_retranscribe=True,
        transcribe_fn=_transcribe,
        echo=lines.append,
        confirm=lambda _q: False,
        limit=30,
        clock=lambda: next(ticks),
    )

    assert store.processed == list(range(31, 61)), "the newest 30"
    announced = [ln for ln in lines if "Re-transcribing" in ln]
    assert announced and "30 captured clip(s)" in announced[0]
    counted = [ln for ln in lines if "clip(s)…" in ln]
    assert counted, "no progress line"
    assert "left" in counted[0], f"no estimate on the first count: {counted[0]!r}"


def test_the_cli_maps_limit_zero_to_all_rather_than_to_nothing():
    """`--limit 0` is the default and must mean "the whole corpus".

    Passing the literal 0 down would mean "re-transcribe nothing", which as a
    default would silently disable the pass this command exists for.
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "src" / "yazses" / "cli.py").read_text(
        encoding="utf-8"
    )
    assert "limit=limit or None," in source
