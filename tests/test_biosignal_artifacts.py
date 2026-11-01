"""Properties of the artifact-grade switches in ``yazses.biosignal.artifacts``.

Blink, double-blink and jaw clench are *switches that open a microphone*, so the tests
are written around the failure modes that matter for them: a phantom trigger on a quiet
signal, a lost event because of block boundaries or warm-up, a jaw clench while the user
talks, and a threshold-scaling knob that moves the wrong way.

Signals are numpy bumps or ``SyntheticSource`` output passed through ``build_eeg_chain``
like the pipeline does. Everything is seeded; nothing touches hardware, the network or the
real data directory.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np
import pytest

from yazses.biosignal.artifacts import (
    ArtifactBank,
    BlinkDetector,
    JawClenchDetector,
    chewing_rhythm_suppressed,
)
from yazses.biosignal.filters import build_eeg_chain
from yazses.biosignal.sources import SyntheticSource
from yazses.biosignal.types import BioEvent, ChannelInfo, EventKind, SampleBlock, SignalKind

BLINK_FS = 250.0
JAW_FS = 500.0
SEEDS = (0, 1, 2, 3, 4)

# --------------------------------------------------------------------------- builders


def _block(data: np.ndarray, fs: float, names: Sequence[str] = ("Fp1",),
           kind: SignalKind = SignalKind.EEG, t0: float = 0.0) -> SampleBlock:
    return SampleBlock(
        np.atleast_2d(data), fs, tuple(ChannelInfo(n, kind) for n in names), t0,
    )


def _bumps(dur: float, bumps: Sequence[tuple[float, float, float]], *, fs: float = BLINK_FS,
           noise: float = 2.0, seed: int = 0) -> SampleBlock:
    """One EEG channel: white noise plus raised-cosine bumps ``(start_s, width_s, amp_uv)``.

    A bump of total width ``w`` has a full width at half maximum of ``w / 2``.
    """
    rng = np.random.default_rng(seed)
    n = int(dur * fs)
    x = rng.standard_normal(n) * noise
    t = np.arange(n) / fs
    for start, width, amp in bumps:
        u = (t - start) / width
        x += amp * np.where((u >= 0) & (u <= 1), 0.5 - 0.5 * np.cos(2 * np.pi * u), 0.0)
    return _block(x, fs)


def _read_all(src: SyntheticSource) -> SampleBlock:
    blocks = []
    while True:
        try:
            blocks.append(src.read())
        except EOFError:
            break
    data = np.concatenate([b.data for b in blocks if b is not None], axis=1)
    return SampleBlock(data, src.fs, src.channels, 0.0)


def _blink_stream(seed: int, dur: float, blinks: Sequence[float] = (), amp: float = 150.0,
                  ) -> SampleBlock:
    """SyntheticSource EEG with scheduled blinks, band-passed like the pipeline does."""
    src = SyntheticSource("eeg", seed=seed, duration=dur)
    for t in blinks:
        src.schedule_blink(t, amp)
    raw = _read_all(src)
    chain = build_eeg_chain(raw.fs)
    return SampleBlock(chain.process(raw.data), raw.fs, raw.channels, 0.0)


def _jaw_stream(seed: int, dur: float, clenches: Sequence[tuple[float, float]] = (),
                amp: float = 80.0) -> SampleBlock:
    """SyntheticSource EEG at 500 Hz (so the 20-100 Hz band is intact) with clenches."""
    src = SyntheticSource("eeg", fs=JAW_FS, seed=seed, duration=dur)
    for t, d in clenches:
        src.schedule_clench(t, d, amp)
    return _read_all(src)


def _feed(det, blk: SampleBlock, n: int) -> list[BioEvent]:
    """Feed ``blk`` to ``det`` in blocks of ``n`` samples, keeping absolute timestamps."""
    out: list[BioEvent] = []
    for i in range(0, blk.n_samples, n):
        out += det.process(
            SampleBlock(blk.data[:, i:i + n], blk.fs, blk.channels, blk.t0 + i / blk.fs))
    return out


def _feed_clocked(det, blk: SampleBlock, now: list[float], n: int = 50) -> list[BioEvent]:
    """Like ``_feed`` but publishes the end of each block as the speech guard's clock."""
    out: list[BioEvent] = []
    for i in range(0, blk.n_samples, n):
        t0 = blk.t0 + i / blk.fs
        now[0] = t0 + min(n, blk.n_samples - i) / blk.fs
        out += det.process(SampleBlock(blk.data[:, i:i + n], blk.fs, blk.channels, t0))
    return out


def _kinds(events: Sequence[BioEvent]) -> list[EventKind]:
    return [e.kind for e in events]


def _signature(events: Sequence[BioEvent]) -> list[tuple[str, float, float]]:
    return [(e.kind.name, round(e.t, 9), round(e.confidence, 9)) for e in events]


def _window_guard(now: list[float], *windows: tuple[float, float]) -> Callable[[], bool]:
    return lambda: any(lo <= now[0] <= hi for lo, hi in windows)


# ============================================================================ blink


def test_lone_blink_is_silent_when_double_only() -> None:
    """With ``double_only=True`` a lone (involuntary) blink emits nothing."""
    det = BlinkDetector(BLINK_FS)
    assert _feed(det, _bumps(10, [(5.0, 0.3, 100.0)]), 250) == []
    assert det.stats["blinks"] == 1  # it was seen ...
    assert det.stats["double_blinks"] == 0  # ... and deliberately not reported


def test_lone_blink_emits_blink_when_not_double_only() -> None:
    """With ``double_only=False`` one blink yields exactly one BLINK at its peak."""
    det = BlinkDetector(BLINK_FS, double_only=False)
    events = _feed(det, _bumps(10, [(5.0, 0.3, 100.0)]), 250)
    assert _kinds(events) == [EventKind.BLINK]
    assert abs(events[0].t - 5.15) < 0.1  # bump peak is mid-bump
    assert 0.0 < events[0].confidence <= 1.0
    detail = events[0].detail
    assert detail["amplitude_uv"] > 0
    assert 0.10 <= detail["width_s"] <= 0.40
    assert detail["z_score"] >= det.amplitude_k


def test_negative_polarity_blink_is_accepted() -> None:
    """The sign of a blink depends on the montage, so either polarity counts."""
    det = BlinkDetector(BLINK_FS, double_only=False)
    events = _feed(det, _bumps(10, [(5.0, 0.3, -100.0)]), 250)
    assert _kinds(events) == [EventKind.BLINK]
    assert events[0].detail["amplitude_uv"] < 0


def test_pair_within_window_emits_one_double_blink_at_second_peak() -> None:
    """Two blinks inside ``double_window_s``: one DOUBLE_BLINK stamped at the second peak."""
    blk = _bumps(10, [(5.0, 0.3, 100.0), (5.5, 0.3, 100.0)])
    events = _feed(BlinkDetector(BLINK_FS), blk, 250)
    assert _kinds(events) == [EventKind.DOUBLE_BLINK]
    both = _feed(BlinkDetector(BLINK_FS, double_only=False), blk, 250)
    blinks = [e for e in both if e.kind is EventKind.BLINK]
    assert len(blinks) == 2
    assert events[0].t == blinks[1].t  # stamped at the second peak, not the first
    assert events[0].detail["interval_s"] == pytest.approx(blinks[1].t - blinks[0].t)
    assert events[0].confidence <= min(b.confidence for b in blinks) + 1e-12


def test_pair_too_far_apart_emits_no_double_blink() -> None:
    """A second blink after ``double_window_s`` is a new lone blink, not a pair."""
    blk = _bumps(12, [(5.0, 0.3, 100.0), (6.5, 0.3, 100.0)])
    det = BlinkDetector(BLINK_FS)
    assert _feed(det, blk, 250) == []
    assert det.stats["lone_blinks_dropped"] == 1
    loose = _feed(BlinkDetector(BLINK_FS, double_only=False), blk, 250)
    assert _kinds(loose) == [EventKind.BLINK, EventKind.BLINK]


def test_pair_at_exactly_the_window_edge_is_governed_by_the_window() -> None:
    """Shrinking ``double_window_s`` below the real spacing turns a pair into two singles."""
    blk = _bumps(10, [(5.0, 0.3, 100.0), (5.5, 0.3, 100.0)])
    assert _kinds(_feed(BlinkDetector(BLINK_FS, double_window_s=0.6), blk, 250)) == [
        EventKind.DOUBLE_BLINK]
    assert _feed(BlinkDetector(BLINK_FS, double_window_s=0.4), blk, 250) == []


@pytest.mark.parametrize("start", [3.0, 6.0, 8.0, 9.0, 12.0])
def test_pair_through_the_eeg_chain_is_found_at_any_start_time(start: float) -> None:
    """Round-2 regression: a 0.5 s pair is reported wherever it falls and for every seed.

    The old detector judged one blink per excursion, so a pair that arrived as ONE
    ringing excursion lost a blink depending on the noise realisation.
    """
    for seed in SEEDS:
        blk = _blink_stream(seed, start + 6.0, [start, start + 0.5])
        events = _feed(BlinkDetector(blk.fs), blk, 500)
        assert _kinds(events) == [EventKind.DOUBLE_BLINK], (start, seed, events)
        # second blink: scheduled at start + 0.5, peak 0.15 s into its bump
        assert abs(events[0].t - (start + 0.65)) < 0.15, (start, seed)
        assert 0.0 < events[0].detail["interval_s"] <= 0.6


@pytest.mark.parametrize("start", [6.0, 12.0])
def test_pair_through_the_eeg_chain_reports_two_blinks_and_one_pair(start: float) -> None:
    """With ``double_only=False`` the same pair gives BLINK, BLINK and one DOUBLE_BLINK."""
    for seed in (0, 1, 2):
        blk = _blink_stream(seed, start + 6.0, [start, start + 0.5])
        events = _feed(BlinkDetector(blk.fs, double_only=False), blk, 333)
        kinds = _kinds(events)
        assert kinds.count(EventKind.BLINK) == 2, (start, seed, kinds)
        assert kinds.count(EventKind.DOUBLE_BLINK) == 1, (start, seed, kinds)


@pytest.mark.parametrize(
    ("start", "amp"),
    [(8.0, 150.0), (12.0, 150.0), (8.0, 300.0), (8.0, 60.0), (12.0, 60.0)],
)
def test_single_blink_never_becomes_a_pair(start: float, amp: float) -> None:
    """A single blink, however large (and however much it rings), is not a double blink."""
    for seed in SEEDS:
        blk = _blink_stream(seed, start + 6.0, [start], amp=amp)
        assert _feed(BlinkDetector(blk.fs), blk, 500) == [], (start, amp, seed)
        loose = _feed(BlinkDetector(blk.fs, double_only=False), blk, 500)
        if amp >= 150.0:  # well above the EEG background: it must be found, exactly once
            assert _kinds(loose) == [EventKind.BLINK], (start, amp, seed, loose)
        else:             # marginal against alpha + noise: may be missed, never doubled
            assert _kinds(loose) in ([], [EventKind.BLINK]), (start, amp, seed, loose)


def test_pair_through_the_chain_too_far_apart_gives_two_singles() -> None:
    """Through the real chain, a 1.5 s gap stays two BLINKs and no DOUBLE_BLINK."""
    for seed in (0, 1, 2):
        blk = _blink_stream(seed, 14.0, [6.0, 7.5])
        assert _feed(BlinkDetector(blk.fs), blk, 500) == []
        loose = _feed(BlinkDetector(blk.fs, double_only=False), blk, 500)
        assert _kinds(loose) == [EventKind.BLINK, EventKind.BLINK], (seed, loose)


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_no_phantom_blink_on_45_s_of_eeg_background(seed: int) -> None:
    """No-phantom-trigger: alpha, mains, drift and noise alone give zero events."""
    blk = _blink_stream(seed, 45.0)
    for double_only in (True, False):
        det = BlinkDetector(blk.fs, double_only=double_only)
        assert _feed(det, blk, 125) == [], (seed, double_only)


def test_no_phantom_blink_on_flatline_and_constant_offset() -> None:
    """A flat or constant signal never triggers (and never divides by zero)."""
    for level in (0.0, 5000.0):
        blk = _block(np.full(int(30 * BLINK_FS), level), BLINK_FS)
        det = BlinkDetector(BLINK_FS, double_only=False)
        assert _feed(det, blk, 100) == []


def test_blink_block_size_independence() -> None:
    """Blocks of 7, 100 and 5000 samples yield identical events."""
    blk = _bumps(14, [(3.0, 0.3, 100.0), (3.5, 0.3, 100.0), (8.0, 0.3, 80.0),
                      (11.0, 0.3, -90.0), (11.5, 0.3, -90.0)])
    results = [
        _signature(_feed(BlinkDetector(BLINK_FS, double_only=False), blk, n))
        for n in (7, 100, 5000)
    ]
    assert len(results[0]) >= 5  # 5 blinks + 2 pairs would be 7; at least the five blinks
    assert results[0] == results[1] == results[2]
    through_chain = _blink_stream(1, 14.0, [4.0, 4.5, 9.0])
    chain_results = [
        _signature(_feed(BlinkDetector(through_chain.fs, double_only=False),
                         through_chain, n))
        for n in (7, 100, 5000)
    ]
    assert chain_results[0] == chain_results[1] == chain_results[2]


def test_blink_refractory_rejects_a_second_blink_too_soon() -> None:
    """A second blink inside ``refractory_s`` of the first is rejected, not paired."""
    blk = _bumps(10, [(5.0, 0.3, 100.0), (5.5, 0.3, 100.0)])
    det = BlinkDetector(BLINK_FS, refractory_s=0.9, double_window_s=1.5, double_only=False)
    events = _feed(det, blk, 250)
    assert _kinds(events) == [EventKind.BLINK]
    assert det.stats["rejected_refractory"] == 1
    # the same signal with a short refractory does see two
    short = BlinkDetector(BLINK_FS, refractory_s=0.2, double_only=False)
    assert _kinds(_feed(short, blk, 250)).count(EventKind.BLINK) == 2


def test_small_rebound_after_a_big_blink_is_not_a_second_blink() -> None:
    """A weak hump just after a much bigger blink is filter rebound, not a pair."""
    blk = _bumps(10, [(5.0, 0.3, 100.0), (5.5, 0.3, 25.0)])
    det = BlinkDetector(BLINK_FS)
    assert _feed(det, blk, 250) == []
    assert det.stats["rejected_ringing"] == 1


def test_too_narrow_blink_is_rejected_by_the_width_window() -> None:
    """A spike narrower than ``min_width_s`` is not a blink."""
    det = BlinkDetector(BLINK_FS, double_only=False)
    assert _feed(det, _bumps(10, [(5.0, 0.08, 100.0)]), 250) == []
    assert det.stats["rejected_width"] == 1


def test_single_sample_pop_is_not_a_blink() -> None:
    """A one-sample pop has no measurable edges and is rejected."""
    blk = _bumps(10, [])
    blk.data[0, 1250] += 400.0
    det = BlinkDetector(BLINK_FS, double_only=False)
    assert _feed(det, blk, 250) == []


def test_too_wide_deflection_is_rejected_by_the_width_window() -> None:
    """A slow deflection (head movement) wider than ``max_width_s`` is not a blink."""
    det = BlinkDetector(BLINK_FS, double_only=False)
    assert _feed(det, _bumps(12, [(5.0, 1.4, 100.0)]), 250) == []
    assert det.stats["rejected_width"] == 1


def test_a_step_that_never_returns_is_not_a_blink() -> None:
    """An electrode/eye-position step never falls back and is aborted by length."""
    blk = _bumps(10, [])
    blk.data[0, 1250:] += 100.0
    det = BlinkDetector(BLINK_FS, double_only=False)
    assert _feed(det, blk, 250) == []
    assert det.stats["rejected_too_long"] == 1


def test_width_window_bounds_follow_the_constructor() -> None:
    """The same bump is accepted or rejected as the width window is moved around it."""
    blk = _bumps(10, [(5.0, 0.3, 100.0)])  # FWHM 0.15 s
    accept = BlinkDetector(BLINK_FS, double_only=False, min_width_s=0.10, max_width_s=0.40)
    assert len(_feed(accept, blk, 250)) == 1
    too_narrow_window = BlinkDetector(BLINK_FS, double_only=False,
                                      min_width_s=0.02, max_width_s=0.08)
    assert _feed(too_narrow_window, blk, 250) == []
    too_wide_window = BlinkDetector(BLINK_FS, double_only=False,
                                    min_width_s=0.25, max_width_s=0.60)
    assert _feed(too_wide_window, blk, 250) == []


def test_nothing_is_emitted_inside_the_warm_up() -> None:
    """Blinks that peak before ``warmup_s`` of signal has been seen emit nothing."""
    blk = _bumps(10, [(0.3, 0.3, 100.0), (0.9, 0.3, 100.0), (1.3, 0.3, 100.0)])
    det = BlinkDetector(BLINK_FS, double_only=False)
    assert _feed(det, blk, 100) == []


@pytest.mark.parametrize("block", [7, 100, 5000])
@pytest.mark.parametrize("start", [2.05, 2.3, 3.7, 5.1, 8.9])
def test_blink_after_warm_up_is_found_for_any_block_size_and_delay(
    start: float, block: int,
) -> None:
    """A blink after the warm-up is reported whatever precedes it and however it is chunked."""
    blk = _bumps(12, [(start, 0.3, 100.0)], seed=3)
    events = _feed(BlinkDetector(BLINK_FS, double_only=False), blk, block)
    assert _kinds(events) == [EventKind.BLINK], (start, block, events)
    assert abs(events[0].t - (start + 0.15)) < 0.1


def test_channels_are_median_combined_so_one_bad_electrode_is_outvoted() -> None:
    """One railed channel out of three does not create events or hide a real blink."""
    clean = _bumps(10, [(5.0, 0.3, 100.0)], seed=1).data[0]
    quiet = _bumps(10, [], seed=2).data[0]
    rng = np.random.default_rng(9)
    railed = 3000.0 + rng.standard_normal(clean.size) * 400.0
    blk = _block(np.vstack([clean, quiet, railed]), BLINK_FS, ("Fp1", "Fp2", "AF7"))
    # median of (blink, flat, railed) follows the middle value: no phantom from the rail
    det = BlinkDetector(BLINK_FS, double_only=False)
    assert all(e.kind is EventKind.BLINK for e in _feed(det, blk, 250))
    both = _block(np.vstack([clean, clean * 0 + _bumps(10, [(5.0, 0.3, 100.0)], seed=4).data[0],
                             railed]), BLINK_FS, ("Fp1", "Fp2", "AF7"))
    got = _feed(BlinkDetector(BLINK_FS, double_only=False), both, 250)
    assert _kinds(got) == [EventKind.BLINK]
    assert got[0].channel == "Fp1,Fp2,AF7"


def test_non_finite_samples_do_not_create_a_blink() -> None:
    """NaN/inf dropouts are held as a flat spot, not read as a deflection."""
    blk = _bumps(10, [])
    blk.data[0, 1000:1030] = np.nan
    blk.data[0, 1500:1510] = np.inf
    det = BlinkDetector(BLINK_FS, double_only=False)
    assert _feed(det, blk, 125) == []


def test_unrelated_channels_are_ignored_but_eog_kind_is_always_read() -> None:
    """Names outside the blink list are not read; an EOG-kind channel always is."""
    blk = _bumps(10, [(5.0, 0.3, 100.0)])
    c3 = _block(blk.data, BLINK_FS, ("C3",))
    assert _feed(BlinkDetector(BLINK_FS, double_only=False), c3, 250) == []
    eog = _block(blk.data, BLINK_FS, ("EOG_V",), kind=SignalKind.EOG)
    assert _kinds(_feed(BlinkDetector(BLINK_FS, double_only=False), eog, 250)) == [
        EventKind.BLINK]
    anything = _block(blk.data, BLINK_FS, ("C3",))
    open_det = BlinkDetector(BLINK_FS, channels=None, double_only=False)
    assert _kinds(_feed(open_det, anything, 250)) == [EventKind.BLINK]


def test_blink_rejects_a_block_with_a_different_sample_rate() -> None:
    """``block.fs`` must equal the detector's ``fs``."""
    det = BlinkDetector(250.0)
    with pytest.raises(ValueError, match="fs"):
        det.process(_block(np.zeros(100), 500.0))


def test_blink_rejects_data_that_does_not_match_its_channels() -> None:
    """A block whose rows disagree with its channel list is a ValueError."""
    det = BlinkDetector(250.0)
    bad = SampleBlock(np.zeros((1, 100)), 250.0,
                      (ChannelInfo("Fp1", SignalKind.EEG), ChannelInfo("Fp2", SignalKind.EEG)))
    with pytest.raises(ValueError):
        det.process(bad)


def test_blink_locks_its_channels_and_resets_when_one_vanishes() -> None:
    """After a locked channel disappears the detector starts over (warm-up included)."""
    det = BlinkDetector(BLINK_FS, double_only=False)
    first = _bumps(8, [(5.0, 0.3, 100.0)])
    assert _kinds(_feed(det, first, 250)) == [EventKind.BLINK]
    assert det.stats["blinks"] == 1
    # same stream but the locked electrode is gone
    gone = _block(np.zeros(100), BLINK_FS, ("AF8",))
    assert det.process(gone) == []
    assert det.stats["blinks"] == 1  # the counters are an audit trail and survive a loss
    assert det.stats["channel_lost"] == 1
    assert not det.health()["warmed_up"]  # ... but the baseline was reset
    # a blink 1 s after the restart falls inside the new warm-up: nothing
    again = _bumps(6, [(1.0, 0.3, 100.0)], seed=5)
    again = SampleBlock(again.data, BLINK_FS, again.channels, 8.0)
    assert _feed(det, again, 250) == []


def test_blink_reset_returns_to_the_just_constructed_state() -> None:
    """Processing, ``reset()``, then processing again reproduces the first run exactly."""
    blk = _bumps(12, [(4.0, 0.3, 100.0), (4.5, 0.3, 100.0), (8.0, 0.3, 100.0)])
    det = BlinkDetector(BLINK_FS, double_only=False)
    first = _signature(_feed(det, blk, 100))
    first_stats = dict(det.stats)
    det.reset()
    assert all(v == 0 for v in det.stats.values())
    assert _signature(_feed(det, blk, 100)) == first
    assert det.stats == first_stats


def test_blink_constructor_validation() -> None:
    """Nonsense parameters are refused up front."""
    with pytest.raises(ValueError):
        BlinkDetector(0.0)
    with pytest.raises(ValueError):
        BlinkDetector(250.0, min_width_s=0.5, max_width_s=0.4)
    with pytest.raises(ValueError):
        BlinkDetector(250.0, warmup_s=9.0, baseline_s=8.0)
    with pytest.raises(ValueError):
        BlinkDetector(250.0, min_amplitude_uv=-1.0)
    with pytest.raises(ValueError):
        BlinkDetector(250.0, amplitude_k=float("nan"))


# ----------------------------------------------------------------- blink calibration


@pytest.mark.parametrize("bad", [None, float("nan"), 0.0, -5.0, float("inf"), "abc", True])
def test_blink_from_calibration_with_unusable_amplitude_is_the_plain_detector(bad) -> None:
    """None/NaN/<=0/non-numbers give exactly ``BlinkDetector(fs, **kw)``."""
    cal = BlinkDetector.from_calibration(BLINK_FS, bad, double_only=False)
    plain = BlinkDetector(BLINK_FS, double_only=False)
    assert cal.min_amplitude_uv == plain.min_amplitude_uv == 0.0
    assert cal.amplitude_k == plain.amplitude_k
    blk = _bumps(10, [(5.0, 0.3, 30.0)])
    assert _signature(_feed(cal, blk, 250)) == _signature(_feed(plain, blk, 250))


@pytest.mark.parametrize("amp", [4.0, 19.0, 20.0, 60.0, 400.0])
def test_blink_from_calibration_floor_only_raises_the_bar(amp: float) -> None:
    """``min_amplitude_uv = max(0.5 * amp, 10)``; the z-score threshold is untouched."""
    det = BlinkDetector.from_calibration(BLINK_FS, amp)
    assert det.min_amplitude_uv == pytest.approx(max(0.5 * amp, 10.0))
    assert det.amplitude_k == BlinkDetector(BLINK_FS).amplitude_k
    assert det.min_amplitude_uv >= BlinkDetector(BLINK_FS).min_amplitude_uv


def test_blink_from_calibration_changes_behaviour_monotonically() -> None:
    """A bigger calibrated blink demands a bigger blink; a small one changes nothing."""
    blk = _bumps(10, [(5.0, 0.3, 30.0)])
    plain = BlinkDetector(BLINK_FS, double_only=False)
    small_cal = BlinkDetector.from_calibration(BLINK_FS, 20.0, double_only=False)   # floor 10
    big_cal = BlinkDetector.from_calibration(BLINK_FS, 100.0, double_only=False)    # floor 50
    assert len(_feed(plain, blk, 250)) == 1
    assert len(_feed(small_cal, blk, 250)) == 1
    assert _feed(big_cal, blk, 250) == []
    assert big_cal.stats["rejected_amplitude"] > small_cal.stats["rejected_amplitude"]


def test_blink_from_calibration_explicit_kw_wins_and_fraction_floor_apply() -> None:
    """An explicit ``min_amplitude_uv`` overrides the calibration; fraction/floor are knobs."""
    assert BlinkDetector.from_calibration(
        BLINK_FS, 100.0, min_amplitude_uv=3.0).min_amplitude_uv == 3.0
    assert BlinkDetector.from_calibration(
        BLINK_FS, 100.0, fraction=1.0).min_amplitude_uv == pytest.approx(100.0)
    assert BlinkDetector.from_calibration(
        BLINK_FS, 4.0, floor_uv=25.0).min_amplitude_uv == pytest.approx(25.0)
    with pytest.raises(ValueError):
        BlinkDetector.from_calibration(BLINK_FS, 50.0, fraction=0.0)
    with pytest.raises(ValueError):
        BlinkDetector.from_calibration(BLINK_FS, 50.0, fraction=1.5)
    with pytest.raises(ValueError):
        BlinkDetector.from_calibration(BLINK_FS, 50.0, floor_uv=-1.0)


# ----------------------------------------------------------------- blink sensitivity


def test_blink_sensitivity_scale_is_clamped_to_one_to_four() -> None:
    """Scales below 1 restore the configured thresholds; above 4 stop at 4x."""
    det = BlinkDetector(BLINK_FS, amplitude_k=6.0, min_amplitude_uv=5.0)
    assert det.sensitivity_scale == 1.0
    det.set_sensitivity_scale(0.1)
    assert det.sensitivity_scale == 1.0 and det.amplitude_k == 6.0
    det.set_sensitivity_scale(-3.0)
    assert det.sensitivity_scale == 1.0
    det.set_sensitivity_scale(100.0)
    assert det.sensitivity_scale == 4.0
    assert det.amplitude_k == pytest.approx(24.0)
    assert det.min_amplitude_uv == pytest.approx(20.0)


def test_blink_sensitivity_scale_is_not_cumulative() -> None:
    """Calling it twice with 2.0 gives 2x, not 4x; 1.0 restores the original exactly."""
    det = BlinkDetector(BLINK_FS, amplitude_k=6.0, min_amplitude_uv=5.0)
    det.set_sensitivity_scale(2.0)
    det.set_sensitivity_scale(2.0)
    assert det.amplitude_k == pytest.approx(12.0)
    assert det.min_amplitude_uv == pytest.approx(10.0)
    det.set_sensitivity_scale(1.0)
    assert det.amplitude_k == 6.0 and det.min_amplitude_uv == 5.0


def test_blink_sensitivity_scale_survives_reset() -> None:
    """``reset()`` forgets the signal state, not the governor's desensitisation."""
    det = BlinkDetector(BLINK_FS)
    det.set_sensitivity_scale(3.0)
    det.reset()
    assert det.sensitivity_scale == 3.0
    assert det.amplitude_k == pytest.approx(18.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "loud", None])
def test_blink_sensitivity_scale_rejects_non_finite_or_non_numeric(bad) -> None:
    """A non-finite or non-numeric scale is a ValueError and leaves the detector unchanged."""
    det = BlinkDetector(BLINK_FS)
    det.set_sensitivity_scale(2.0)
    with pytest.raises(ValueError):
        det.set_sensitivity_scale(bad)
    assert det.sensitivity_scale == 2.0


def test_blink_sensitivity_scale_stops_a_marginal_blink_and_is_monotone() -> None:
    """A marginal blink fires at 1x and not at 4x; the count never rises with the scale."""
    blk = _bumps(10, [(5.0, 0.3, 25.0)])
    counts = []
    for scale in (1.0, 1.5, 2.0, 3.0, 4.0):
        det = BlinkDetector(BLINK_FS, double_only=False)
        det.set_sensitivity_scale(scale)
        counts.append(len(_feed(det, blk, 250)))
    assert counts[0] == 1 and counts[-1] == 0
    assert counts == sorted(counts, reverse=True)
    # a large blink still fires at the loosest setting
    strong = _bumps(10, [(5.0, 0.3, 400.0)])
    det = BlinkDetector(BLINK_FS, double_only=False)
    det.set_sensitivity_scale(4.0)
    assert len(_feed(det, strong, 250)) == 1


def test_blink_scale_of_one_restores_original_behaviour_exactly() -> None:
    """After 4x then back to 1x, events match a detector that was never touched."""
    blk = _bumps(14, [(4.0, 0.3, 100.0), (4.5, 0.3, 100.0), (9.0, 0.3, 30.0)])
    baseline = _signature(_feed(BlinkDetector(BLINK_FS, double_only=False), blk, 250))
    det = BlinkDetector(BLINK_FS, double_only=False)
    det.set_sensitivity_scale(4.0)
    det.set_sensitivity_scale(1.0)
    assert _signature(_feed(det, blk, 250)) == baseline


# ============================================================================== jaw


def test_sustained_burst_emits_exactly_one_jaw_clench() -> None:
    """A sustained HF burst is one JAW_CLENCH near its onset, with a sane payload."""
    for seed in (0, 1, 2):
        blk = _jaw_stream(seed, 14.0, [(6.0, 0.8)])
        det = JawClenchDetector(JAW_FS)
        events = _feed(det, blk, 500)
        assert _kinds(events) == [EventKind.JAW_CLENCH], (seed, events)
        ev = events[0]
        assert abs(ev.t - 6.0) < 0.3
        assert 0.0 <= ev.confidence <= 1.0
        assert ev.channel == "Fp1,Fp2"
        assert ev.detail["peak_db"] > det.on_db
        assert ev.detail["sustained_s"] >= det.min_duration_s - 1.0 / JAW_FS
        assert ev.detail["confirmed_t"] >= ev.t
        assert det.stats["clenches"] == 1


def test_a_very_long_burst_is_still_one_event() -> None:
    """Hysteresis: one continuous burst never re-fires while it lasts."""
    blk = _jaw_stream(0, 16.0, [(6.0, 2.5)])
    assert _kinds(_feed(JawClenchDetector(JAW_FS), blk, 500)) == [EventKind.JAW_CLENCH]


def test_two_separated_bursts_are_two_clenches() -> None:
    """Release-before-rearm: isolated bursts each give one event."""
    blk = _jaw_stream(0, 16.0, [(6.0, 0.6), (10.0, 0.6)])
    events = _feed(JawClenchDetector(JAW_FS), blk, 500)
    assert _kinds(events) == [EventKind.JAW_CLENCH] * 2
    assert events[1].t - events[0].t == pytest.approx(4.0, abs=0.3)


def test_burst_shorter_than_min_duration_emits_nothing() -> None:
    """A burst that ends before ``min_duration_s`` is counted as short and not reported."""
    blk = _jaw_stream(0, 14.0, [(6.0, 0.4)])
    det = JawClenchDetector(JAW_FS, min_duration_s=0.8)
    assert _feed(det, blk, 500) == []
    assert det.stats["clenches"] == 0
    assert det.stats["short_bursts"] == 1
    # the same burst is accepted once the minimum is lowered below it
    assert len(_feed(JawClenchDetector(JAW_FS, min_duration_s=0.2), blk, 500)) == 1


def test_min_duration_gate_is_monotone() -> None:
    """A longer ``min_duration_s`` can only remove events."""
    blk = _jaw_stream(1, 14.0, [(6.0, 0.5)])
    counts = [len(_feed(JawClenchDetector(JAW_FS, min_duration_s=m), blk, 500))
              for m in (0.1, 0.2, 0.4, 0.8, 1.5)]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 1 and counts[-1] == 0


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_no_phantom_clench_on_45_s_of_background(seed: int) -> None:
    """No-phantom-trigger: noise, alpha, mains and drift alone give zero events."""
    blk = _jaw_stream(seed, 45.0)
    det = JawClenchDetector(JAW_FS)
    assert _feed(det, blk, 250) == []
    assert det.stats["clenches"] == 0


def test_no_phantom_clench_on_flatline_and_constant_offset() -> None:
    """A flat or constant signal never triggers (log of zero power is handled)."""
    for level in (0.0, 5000.0):
        flat = np.full((2, int(20 * JAW_FS)), level)
        blk = SampleBlock(flat, JAW_FS, (ChannelInfo("Fp1", SignalKind.EEG),
                                         ChannelInfo("Fp2", SignalKind.EEG)))
        assert _feed(JawClenchDetector(JAW_FS), blk, 100) == []


def test_jaw_block_size_independence() -> None:
    """Blocks of 7, 100 and 5000 samples yield identical events."""
    blk = _jaw_stream(0, 14.0, [(6.0, 0.7), (10.0, 0.5)])
    results = [_signature(_feed(JawClenchDetector(JAW_FS), blk, n)) for n in (7, 100, 5000)]
    assert len(results[0]) == 2
    assert results[0] == results[1] == results[2]


def test_nothing_is_emitted_inside_the_jaw_warm_up() -> None:
    """The first seconds are the resting calibration: a burst there is not reported."""
    blk = _jaw_stream(0, 12.0, [(1.0, 0.8)])
    assert _feed(JawClenchDetector(JAW_FS), blk, 500) == []


@pytest.mark.parametrize("start", [5.0, 6.3, 9.1])
@pytest.mark.parametrize("block", [7, 100, 5000])
def test_clench_after_warm_up_is_found_for_any_block_size_and_delay(
    start: float, block: int,
) -> None:
    """A clench after the warm-up is reported whatever precedes it."""
    blk = _jaw_stream(2, 13.0, [(start, 0.7)])
    events = _feed(JawClenchDetector(JAW_FS), blk, block)
    assert _kinds(events) == [EventKind.JAW_CLENCH], (start, block)
    assert abs(events[0].t - start) < 0.3


def test_jaw_refractory_suppresses_a_burst_too_soon_after_an_event() -> None:
    """A second burst inside ``refractory_s`` of an event is suppressed and counted."""
    blk = _jaw_stream(0, 16.0, [(6.0, 0.6), (8.0, 0.6)])
    det = JawClenchDetector(JAW_FS, refractory_s=3.0)
    events = _feed(det, blk, 500)
    assert _kinds(events) == [EventKind.JAW_CLENCH]
    assert det.stats["suppressed_refractory"] == 1
    assert len(_feed(JawClenchDetector(JAW_FS, refractory_s=0.3), blk, 500)) == 2


def test_jaw_rejects_a_block_with_a_different_sample_rate() -> None:
    """``block.fs`` must equal the detector's ``fs``."""
    with pytest.raises(ValueError, match="fs"):
        JawClenchDetector(JAW_FS).process(_block(np.zeros(100), 250.0, ("Fp1",)))


def test_jaw_reads_only_eeg_channels() -> None:
    """EMG/EOG-kind rows are not jaw input; EEG rows outside the default list are, if asked."""
    blk = _jaw_stream(0, 14.0, [(6.0, 0.8)], amp=300.0)
    emg = SampleBlock(blk.data, JAW_FS,
                      tuple(ChannelInfo(c.name, SignalKind.EMG) for c in blk.channels))
    assert _feed(JawClenchDetector(JAW_FS, channels=None), emg, 500) == []
    open_det = JawClenchDetector(JAW_FS, channels=None)
    assert _kinds(_feed(open_det, blk, 500)) == [EventKind.JAW_CLENCH]
    assert open_det.stats["clenches"] == 1


def test_jaw_locks_its_channels_and_resets_when_one_vanishes() -> None:
    """After a locked channel disappears the detector starts over, warm-up included."""
    det = JawClenchDetector(JAW_FS)
    blk = _jaw_stream(0, 12.0, [(6.0, 0.7)])
    assert len(_feed(det, blk, 500)) == 1
    assert det.process(_block(np.zeros(100), JAW_FS, ("Fp9",))) == []
    assert det.stats["clenches"] == 1  # the counters are an audit trail and survive a loss
    assert det.stats["channel_lost"] == 1
    assert not det.health()["warmed_up"]  # ... but the baseline was reset
    again = _jaw_stream(0, 6.0, [(1.0, 0.7)])
    again = SampleBlock(again.data, JAW_FS, again.channels, 12.0)
    assert _feed(det, again, 500) == []  # inside the fresh warm-up


def test_jaw_reset_returns_to_the_just_constructed_state() -> None:
    """Processing, ``reset()``, then processing again reproduces the first run exactly."""
    blk = _jaw_stream(1, 14.0, [(6.0, 0.7), (10.0, 0.6)])
    det = JawClenchDetector(JAW_FS)
    first = _signature(_feed(det, blk, 500))
    first_stats = dict(det.stats)
    det.reset()
    assert all(v == 0 for v in det.stats.values())
    assert _signature(_feed(det, blk, 500)) == first
    assert det.stats == first_stats


def test_jaw_constructor_validation() -> None:
    """Nonsense parameters are refused up front."""
    with pytest.raises(ValueError):
        JawClenchDetector(0.0)
    with pytest.raises(ValueError):
        JawClenchDetector(JAW_FS, on_db=3.0, off_db=6.0)
    with pytest.raises(ValueError):
        JawClenchDetector(JAW_FS, on_z=2.0, off_z=4.0)
    with pytest.raises(ValueError):
        JawClenchDetector(JAW_FS, warmup_s=40.0, baseline_s=30.0)
    with pytest.raises(ValueError):
        JawClenchDetector(JAW_FS, speech_hangover_s=-1.0)
    with pytest.raises(ValueError):
        JawClenchDetector(30.0)  # the band would collapse below 0.45 * fs
    with pytest.raises(ValueError):
        JawClenchDetector(JAW_FS, chew_repeats=1)
    with pytest.raises(ValueError):
        JawClenchDetector(JAW_FS, min_burst_power_uv2=-1.0)


# ---------------------------------------------------------------------- speech guard


def test_guard_that_never_speaks_leaves_the_clench_alone() -> None:
    """Control: a guard that always says "silent" does not change the result."""
    blk = _jaw_stream(0, 14.0, [(6.0, 0.8)])
    now = [0.0]
    det = JawClenchDetector(JAW_FS, speech_guard=lambda: False)
    assert _kinds(_feed_clocked(det, blk, now)) == [EventKind.JAW_CLENCH]
    assert det.stats["suppressed_speech"] == 0


def test_speech_during_the_burst_suppresses_the_clench() -> None:
    """A burst entirely inside a speaking window produces no event."""
    blk = _jaw_stream(0, 14.0, [(6.0, 0.8)])
    now = [0.0]
    det = JawClenchDetector(JAW_FS, speech_guard=_window_guard(now, (5.5, 7.5)))
    assert _feed_clocked(det, blk, now) == []
    assert det.stats["suppressed_speech"] == 1


def test_speech_that_starts_after_the_burst_began_still_suppresses_it() -> None:
    """A burst that begins before the guard rises is suppressed if speech arrives first."""
    blk = _jaw_stream(0, 14.0, [(6.0, 1.2)])
    now = [0.0]
    det = JawClenchDetector(JAW_FS, min_duration_s=0.6,
                            speech_guard=_window_guard(now, (6.4, 8.0)))
    assert _feed_clocked(det, blk, now) == []
    assert det.stats["suppressed_speech"] == 1


def test_burst_inside_the_hangover_after_speech_is_suppressed() -> None:
    """Speech that ended 0.2 s before the burst still counts (hangover 0.5 s)."""
    blk = _jaw_stream(0, 14.0, [(6.0, 0.8)])
    now = [0.0]
    det = JawClenchDetector(JAW_FS, speech_hangover_s=0.5,
                            speech_guard=_window_guard(now, (4.5, 5.8)))
    assert _feed_clocked(det, blk, now) == []
    assert det.stats["suppressed_speech"] == 1


def test_burst_after_the_hangover_has_passed_is_reported() -> None:
    """Speech that ended long before the burst does not suppress it."""
    blk = _jaw_stream(0, 16.0, [(9.0, 0.8)])
    now = [0.0]
    det = JawClenchDetector(JAW_FS, speech_hangover_s=0.5,
                            speech_guard=_window_guard(now, (4.5, 6.0)))
    events = _feed_clocked(det, blk, now)
    assert _kinds(events) == [EventKind.JAW_CLENCH]
    assert det.stats["suppressed_speech"] == 0


def test_longer_hangover_suppresses_more_never_less() -> None:
    """Hangover is monotone: a burst suppressed at hangover h stays suppressed at h' > h."""
    blk = _jaw_stream(0, 14.0, [(6.0, 0.8)])
    counts = []
    for hang in (0.0, 0.5, 1.5, 3.0):
        now = [0.0]
        det = JawClenchDetector(JAW_FS, speech_hangover_s=hang,
                                speech_guard=_window_guard(now, (4.5, 5.0)))
        counts.append(len(_feed_clocked(det, blk, now)))
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 1 and counts[-1] == 0


def test_a_raising_speech_guard_fails_closed() -> None:
    """If the guard raises, the user is assumed to be talking: nothing fires, nothing escapes."""
    blk = _jaw_stream(0, 14.0, [(6.0, 0.8)])

    def broken() -> bool:
        raise RuntimeError("vad crashed")

    det = JawClenchDetector(JAW_FS, speech_guard=broken)
    assert _feed(det, blk, 500) == []

    # a guard that only starts failing mid-run suppresses a burst after that point
    now = [0.0]

    def flaky() -> bool:
        if now[0] > 5.0:
            raise RuntimeError("vad crashed")
        return False

    det = JawClenchDetector(JAW_FS, speech_guard=flaky)
    assert _feed_clocked(det, _jaw_stream(0, 14.0, [(8.0, 0.8)]), now) == []
    assert det.stats["suppressed_speech"] == 1


def test_speech_like_activity_never_produces_a_clench() -> None:
    """Speech fixture: bursts of random length while the guard says "speaking"."""
    rng = np.random.default_rng(7)
    starts = np.cumsum(rng.uniform(0.5, 1.1, 8)) + 5.0
    bursts = [(float(s), float(rng.uniform(0.2, 0.5))) for s in starts]
    blk = _jaw_stream(3, 16.0, bursts)
    now = [0.0]
    det = JawClenchDetector(JAW_FS, speech_guard=_window_guard(now, (4.8, 15.5)))
    assert _feed_clocked(det, blk, now) == []
    assert det.stats["clenches"] == 0


def test_speech_guard_is_polled_at_most_once_per_100_ms_of_signal() -> None:
    """The documented cost bound holds even when blocks are tiny."""
    blk = _jaw_stream(0, 6.0)
    calls = {"n": 0}

    def guard() -> bool:
        calls["n"] += 1
        return False

    _feed(JawClenchDetector(JAW_FS, speech_guard=guard), blk, 7)
    assert calls["n"] <= int(6.0 / 0.1) + 1


# ------------------------------------------------------------------ chewing cadence


def test_chewing_rhythm_true_for_regular_one_to_two_hz_onsets() -> None:
    """Three onsets at 1-2 Hz spacing are a chewing cadence."""
    assert chewing_rhythm_suppressed([0.0, 0.7, 1.4])
    assert chewing_rhythm_suppressed([0.0, 1.0, 2.0])      # exactly 1 Hz
    assert chewing_rhythm_suppressed([0.0, 0.5, 1.0])      # exactly 2 Hz
    assert chewing_rhythm_suppressed([0.0, 0.8, 1.7, 2.4, 3.2])


def test_chewing_rhythm_false_for_isolated_irregular_or_too_few_onsets() -> None:
    """Irregular, too slow, too fast or too few onsets are not chewing."""
    assert not chewing_rhythm_suppressed([])
    assert not chewing_rhythm_suppressed([0.0, 0.7])        # fewer than `repeats`
    assert not chewing_rhythm_suppressed([0.0, 3.0, 3.2])   # irregular
    assert not chewing_rhythm_suppressed([0.0, 3.0, 6.0])   # 0.33 Hz: too slow
    assert not chewing_rhythm_suppressed([0.0, 0.2, 0.4])   # 5 Hz: too fast
    assert not chewing_rhythm_suppressed([0.0, 0.7, 5.0])   # one interval off cadence


def test_chewing_rhythm_looks_only_at_the_most_recent_onsets() -> None:
    """Old history is irrelevant: only the last ``repeats`` onsets decide."""
    assert chewing_rhythm_suppressed([0.0, 10.0, 11.0, 12.0])
    assert not chewing_rhythm_suppressed([0.0, 1.0, 2.0, 10.0])


def test_chewing_rhythm_tolerance_is_monotone() -> None:
    """Whatever is suppressed at a tolerance stays suppressed at every larger one."""
    onsets_sets = [[0.0, 0.45, 0.9], [0.0, 1.4, 2.8], [0.0, 0.3, 0.6], [0.0, 0.7, 1.4]]
    for onsets in onsets_sets:
        verdicts = [chewing_rhythm_suppressed(onsets, tolerance=t)
                    for t in (0.0, 0.1, 0.3, 0.6, 0.9)]
        assert verdicts == sorted(verdicts), (onsets, verdicts)
    assert not chewing_rhythm_suppressed([0.0, 0.45, 0.9], tolerance=0.0)
    assert chewing_rhythm_suppressed([0.0, 0.45, 0.9], tolerance=0.3)


def test_chewing_rhythm_custom_repeats_and_band() -> None:
    """``repeats`` and the Hz band are honoured."""
    assert chewing_rhythm_suppressed([0.0, 0.7], repeats=2)
    assert not chewing_rhythm_suppressed([0.0, 0.7, 1.4], repeats=4)
    assert chewing_rhythm_suppressed([0.0, 0.2, 0.4], min_hz=4.0, max_hz=6.0)


def test_chewing_rhythm_rejects_bad_arguments() -> None:
    """Invalid parameters raise ValueError."""
    with pytest.raises(ValueError):
        chewing_rhythm_suppressed([0.0], repeats=1)
    with pytest.raises(ValueError):
        chewing_rhythm_suppressed([0.0], min_hz=3.0, max_hz=2.0)
    with pytest.raises(ValueError):
        chewing_rhythm_suppressed([0.0], min_hz=0.0)
    with pytest.raises(ValueError):
        chewing_rhythm_suppressed([0.0], tolerance=1.0)
    with pytest.raises(ValueError):
        chewing_rhythm_suppressed([0.0], tolerance=-0.1)


def test_detector_suppresses_a_chewing_cadence_but_not_slow_deliberate_clenches() -> None:
    """Regular 0.8 s bursts are mostly suppressed; clenches 3 s apart all fire."""
    for seed in (0, 1, 2):
        chew = _jaw_stream(seed, 20.0, [(6.0 + 0.8 * i, 0.35) for i in range(8)])
        det = JawClenchDetector(JAW_FS)
        events = _feed(det, chew, 500)
        assert len(events) <= 2, (seed, events)  # the cadence is unknowable for the first two
        assert det.stats["suppressed_chewing"] >= 3, seed
    slow = _jaw_stream(0, 26.0, [(6.0 + 3.0 * i, 0.6) for i in range(6)])
    det = JawClenchDetector(JAW_FS)
    assert len(_feed(det, slow, 500)) == 6
    assert det.stats["suppressed_chewing"] == 0
    assert not det.chewing_rhythm_suppressed()


def test_chew_holdoff_can_only_remove_events() -> None:
    """A hold-off drops events that turn out to be the start of a chewing run."""
    for seed in (0, 1, 2):
        blk = _jaw_stream(seed, 20.0, [(6.0 + 0.8 * i, 0.35) for i in range(8)])
        plain = _feed(JawClenchDetector(JAW_FS), blk, 500)
        held = _feed(JawClenchDetector(JAW_FS, chew_holdoff_s=2.0), blk, 500)
        assert len(held) <= len(plain), seed
        assert {round(e.t, 6) for e in held} <= {round(e.t, 6) for e in plain}, seed
    # an isolated clench is only delayed, not lost, once the hold-off has elapsed
    blk = _jaw_stream(0, 16.0, [(6.0, 0.8)])
    assert len(_feed(JawClenchDetector(JAW_FS, chew_holdoff_s=1.0), blk, 500)) == 1


# --------------------------------------------------------------- jaw calibration


@pytest.mark.parametrize("bad", [None, float("nan"), 0.0, -3.0, float("inf"), "abc", False])
def test_jaw_from_calibration_with_unusable_power_is_the_plain_detector(bad) -> None:
    """None/NaN/<=0/non-numbers give exactly ``JawClenchDetector(fs, **kw)``."""
    cal = JawClenchDetector.from_calibration(JAW_FS, bad)
    assert cal.min_burst_power_uv2 == 0.0
    blk = _jaw_stream(0, 12.0, [(6.0, 0.7)])
    plain = JawClenchDetector(JAW_FS)
    assert _signature(_feed(cal, blk, 500)) == _signature(_feed(plain, blk, 500))


def test_jaw_from_calibration_floor_follows_the_documented_model() -> None:
    """``floor = fraction * clench_power / 2 * band_share``, linear in the power."""
    for fs, share in ((500.0, 80.0 / 250.0), (250.0, 80.0 / 125.0)):
        det = JawClenchDetector.from_calibration(fs, 100.0)
        assert det.min_burst_power_uv2 == pytest.approx(0.25 * 0.5 * 100.0 * share)
    lo = JawClenchDetector.from_calibration(JAW_FS, 10.0).min_burst_power_uv2
    hi = JawClenchDetector.from_calibration(JAW_FS, 1000.0).min_burst_power_uv2
    assert hi > lo > 0.0


def test_jaw_from_calibration_only_raises_the_bar() -> None:
    """A tiny calibration changes nothing; a huge one silences a normal clench."""
    blk = _jaw_stream(0, 12.0, [(6.0, 0.7)])
    plain = _signature(_feed(JawClenchDetector(JAW_FS), blk, 500))
    tiny = JawClenchDetector.from_calibration(JAW_FS, 1e-6)
    assert _signature(_feed(tiny, blk, 500)) == plain
    huge = JawClenchDetector.from_calibration(JAW_FS, 1e9)
    assert _feed(huge, blk, 500) == []
    assert huge.on_db == JawClenchDetector(JAW_FS).on_db  # relative test untouched


def test_jaw_from_calibration_explicit_kw_wins_and_fraction_validated() -> None:
    """An explicit ``min_burst_power_uv2`` overrides the calibration."""
    det = JawClenchDetector.from_calibration(JAW_FS, 100.0, min_burst_power_uv2=7.0)
    assert det.min_burst_power_uv2 == 7.0
    with pytest.raises(ValueError):
        JawClenchDetector.from_calibration(JAW_FS, 100.0, fraction=0.0)
    with pytest.raises(ValueError):
        JawClenchDetector.from_calibration(JAW_FS, 100.0, fraction=2.0)


# -------------------------------------------------------------- jaw sensitivity


def test_jaw_sensitivity_scale_scales_every_threshold_and_keeps_hysteresis() -> None:
    """``on/off`` thresholds and the power floor scale together; ``off <= on`` still holds."""
    det = JawClenchDetector(JAW_FS, on_db=6.0, off_db=3.0, on_z=4.0, off_z=2.0,
                            min_burst_power_uv2=2.0)
    det.set_sensitivity_scale(2.0)
    assert (det.on_db, det.off_db, det.on_z, det.off_z) == (12.0, 6.0, 8.0, 4.0)
    assert det.min_burst_power_uv2 == pytest.approx(4.0)
    assert det.off_db <= det.on_db and det.off_z <= det.on_z


def test_jaw_sensitivity_scale_is_clamped_not_cumulative_and_survives_reset() -> None:
    """Clamped to [1, 4]; applied to the configured values; kept across ``reset()``."""
    det = JawClenchDetector(JAW_FS)
    det.set_sensitivity_scale(0.2)
    assert det.sensitivity_scale == 1.0 and det.on_db == 6.0
    det.set_sensitivity_scale(99.0)
    assert det.sensitivity_scale == 4.0 and det.on_db == pytest.approx(24.0)
    det.set_sensitivity_scale(2.0)
    det.set_sensitivity_scale(2.0)
    assert det.on_db == pytest.approx(12.0)
    det.reset()
    assert det.sensitivity_scale == 2.0 and det.on_db == pytest.approx(12.0)
    det.set_sensitivity_scale(1.0)
    assert (det.on_db, det.off_db, det.on_z, det.off_z) == (6.0, 3.0, 4.0, 2.0)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf"), "loud", None])
def test_jaw_sensitivity_scale_rejects_non_finite_or_non_numeric(bad) -> None:
    """A non-finite or non-numeric scale is a ValueError and leaves the detector unchanged."""
    det = JawClenchDetector(JAW_FS)
    det.set_sensitivity_scale(3.0)
    with pytest.raises(ValueError):
        det.set_sensitivity_scale(bad)
    assert det.sensitivity_scale == 3.0


def test_jaw_sensitivity_scale_stops_a_marginal_clench_and_is_monotone() -> None:
    """A moderate clench fires at 1x and not at 4x; counts never rise with the scale."""
    blk = _jaw_stream(0, 12.0, [(6.0, 0.6)], amp=80.0)
    counts = []
    for scale in (1.0, 1.5, 2.0, 3.0, 4.0):
        det = JawClenchDetector(JAW_FS)
        det.set_sensitivity_scale(scale)
        counts.append(len(_feed(det, blk, 500)))
    assert counts[0] == 1 and counts[-1] == 0
    assert counts == sorted(counts, reverse=True)
    strong = _jaw_stream(0, 12.0, [(6.0, 0.6)], amp=1000.0)
    det = JawClenchDetector(JAW_FS)
    det.set_sensitivity_scale(4.0)
    assert len(_feed(det, strong, 500)) == 1


def test_jaw_scale_of_one_restores_original_behaviour_exactly() -> None:
    """After 4x then back to 1x, events match a detector that was never touched."""
    blk = _jaw_stream(1, 14.0, [(6.0, 0.7), (10.0, 0.6)])
    baseline = _signature(_feed(JawClenchDetector(JAW_FS), blk, 500))
    det = JawClenchDetector(JAW_FS)
    det.set_sensitivity_scale(4.0)
    det.set_sensitivity_scale(1.0)
    assert _signature(_feed(det, blk, 500)) == baseline


# ===================================================================== ArtifactBank


class _Stub:
    """A StreamDetector returning scripted events, to test the bank in isolation."""

    def __init__(self, events: Sequence[BioEvent] = (), *, boom: bool = False) -> None:
        self._events = list(events)
        self._boom = boom
        self.resets = 0
        self.seen = 0

    def process(self, block: SampleBlock) -> list[BioEvent]:
        self.seen += 1
        if self._boom:
            raise RuntimeError("detector failed")
        return list(self._events)

    def reset(self) -> None:
        self.resets += 1


def _ev(kind: EventKind, t: float, tag: str = "") -> BioEvent:
    return BioEvent(kind, t, 1.0, tag)


def test_bank_merges_and_time_sorts_events_from_all_detectors() -> None:
    """Events from several detectors come back in time order, ties in detector order."""
    a = _Stub([_ev(EventKind.BLINK, 3.0, "a"), _ev(EventKind.BLINK, 1.0, "a")])
    b = _Stub([_ev(EventKind.JAW_CLENCH, 2.0, "b"), _ev(EventKind.JAW_CLENCH, 3.0, "b")])
    bank = ArtifactBank([a, b])
    out = bank.process(_block(np.zeros(10), 250.0))
    assert [e.t for e in out] == [1.0, 2.0, 3.0, 3.0]
    assert [e.channel for e in out if e.t == 3.0] == ["a", "b"]  # stable on ties


def test_bank_isolates_a_failing_detector_and_counts_it() -> None:
    """A raising detector is skipped for that block; the others still report."""
    good = _Stub([_ev(EventKind.BLINK, 1.0)])
    bad = _Stub(boom=True)
    bank = ArtifactBank([bad, good])
    out = bank.process(_block(np.zeros(10), 250.0))
    assert [e.t for e in out] == [1.0]
    assert bank.errors == 1
    bank.process(_block(np.zeros(10), 250.0))
    assert bank.errors == 2 and good.seen == 2


def test_bank_reset_resets_every_detector_and_clears_errors() -> None:
    """``reset()`` fans out and zeroes the error counter."""
    a, b = _Stub(), _Stub(boom=True)
    bank = ArtifactBank([a, b])
    bank.process(_block(np.zeros(10), 250.0))
    assert bank.errors == 1
    bank.reset()
    assert (a.resets, b.resets, bank.errors) == (1, 1, 0)


def test_bank_with_no_detectors_and_nested_banks() -> None:
    """An empty bank is a no-op; banks nest because the bank is itself a StreamDetector."""
    assert ArtifactBank([]).process(_block(np.zeros(10), 250.0)) == []
    inner = ArtifactBank([_Stub([_ev(EventKind.BLINK, 5.0)])])
    outer = ArtifactBank([inner, _Stub([_ev(EventKind.JAW_CLENCH, 4.0)])])
    assert [e.t for e in outer.process(_block(np.zeros(10), 250.0))] == [4.0, 5.0]
    outer.reset()
    assert inner.errors == 0


def test_bank_of_real_detectors_returns_time_sorted_events_and_resets() -> None:
    """A blink pair and a jaw clench in one stream come out sorted, then reset cleanly."""
    src = SyntheticSource("eeg", fs=JAW_FS, seed=0, duration=16.0)
    src.schedule_blink(5.0).schedule_blink(5.5).schedule_clench(11.0, 0.8)
    blk = _read_all(src)
    bank = ArtifactBank([JawClenchDetector(JAW_FS), BlinkDetector(JAW_FS)])
    events = _feed(bank, blk, 500)
    assert [e.t for e in events] == sorted(e.t for e in events)
    kinds = _kinds(events)
    assert EventKind.JAW_CLENCH in kinds
    assert bank.errors == 0
    first = _signature(events)
    bank.reset()
    assert _signature(_feed(bank, blk, 500)) == first
