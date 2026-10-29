"""Tests for ``yazses.biosignal.sources``: synthetic, replay, recording tap, BrainFlow, factory.

Everything is offline and deterministic: fixed seeds, injected clocks, ``tmp_path`` files, and
a fake board in place of BrainFlow (which is never required, or even imported).
"""

from __future__ import annotations

import logging
import os
import sys
import types
from pathlib import Path

import numpy as np
import pytest

from yazses.biosignal.sources import (
    SYNTHETIC_BOARD_ID,
    BoardDescription,
    BrainFlowBlockSource,
    FileReplaySource,
    RecordingTap,
    SyntheticSource,
    describe_board,
    iter_blocks,
    open_source,
    write_csv,
    write_npz,
)
from yazses.biosignal.types import (
    BlockSource,
    ChannelInfo,
    EventKind,
    SampleBlock,
    SignalKind,
)

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")

SRC_LOG = "yazses.biosignal.sources"


# ------------------------------------------------------------------ helpers


def drain(source: BlockSource) -> list[SampleBlock]:
    """Every block of a finite source."""
    return list(iter_blocks(source, sleep=lambda _s: None))


def stack(blocks: list[SampleBlock]) -> np.ndarray:
    return np.concatenate([b.data for b in blocks], axis=1)


def make_blocks(
    n_blocks: int = 3, n: int = 50, fs: float = 250.0, t0: float = 0.0, seed: int = 1,
    kinds: tuple[SignalKind, ...] = (SignalKind.EEG, SignalKind.EMG),
) -> list[SampleBlock]:
    rng = np.random.default_rng(seed)
    chans = tuple(ChannelInfo(f"C{i}", k) for i, k in enumerate(kinds))
    return [
        SampleBlock(data=rng.normal(0, 40, (len(chans), n)), fs=fs, channels=chans,
                    t0=t0 + i * n / fs)
        for i in range(n_blocks)
    ]


class ScriptedSource:
    """A BlockSource that replays a list of items (block, None, or an exception)."""

    def __init__(self, items, fs=250.0, channels=()):
        self.items = list(items)
        self.fs = fs
        self.channels = tuple(channels)
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def read(self):
        if not self.items:
            raise EOFError
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x))))


def window(block_data: np.ndarray, fs: float, lo: float, hi: float) -> np.ndarray:
    return block_data[..., int(lo * fs):int(hi * fs)]


# ------------------------------------------------------------------ SyntheticSource


def test_synthetic_same_seed_is_bit_identical():
    """Same constructor arguments give identical samples."""
    a = stack(drain(SyntheticSource("mixed", seed=7, duration=1.0)))
    b = stack(drain(SyntheticSource("mixed", seed=7, duration=1.0)))
    assert np.array_equal(a, b)


def test_synthetic_different_seed_differs():
    a = stack(drain(SyntheticSource("mixed", seed=1, duration=1.0)))
    b = stack(drain(SyntheticSource("mixed", seed=2, duration=1.0)))
    assert not np.array_equal(a, b)


@pytest.mark.parametrize(
    ("kind", "fs", "names", "kinds"),
    [
        ("emg", 1000.0, ["EMG1", "EMG2"], {SignalKind.EMG}),
        ("eeg", 250.0, ["Fp1", "Fp2", "C3", "C4"], {SignalKind.EEG}),
        ("eog", 250.0, ["EOG_V", "EOG_H"], {SignalKind.EOG}),
        ("mixed", 500.0, ["Fp1", "Fp2", "EMG1", "EMG2"], {SignalKind.EEG, SignalKind.EMG}),
    ],
)
def test_synthetic_block_metadata(kind, fs, names, kinds):
    """Shape, dtype, fs and channel metadata agree with the montage."""
    src = SyntheticSource(kind, duration=0.5)
    assert src.fs == fs
    assert [c.name for c in src.channels] == names
    assert {c.kind for c in src.channels} == kinds
    block = src.read()
    assert block is not None
    assert block.data.shape == (len(names), round(fs * 0.04))
    assert block.data.dtype == np.float64
    assert block.fs == fs
    assert block.channels == src.channels
    assert np.isfinite(block.data).all()


def test_synthetic_satisfies_block_source_protocol():
    assert isinstance(SyntheticSource("emg"), BlockSource)


def test_synthetic_explicit_fs_and_block_samples():
    src = SyntheticSource("eeg", fs=125.0, block_samples=10)
    block = src.read()
    assert block is not None
    assert block.fs == 125.0
    assert block.n_samples == 10


def test_synthetic_duration_ends_with_eoferror_and_exact_sample_count():
    src = SyntheticSource("emg", duration=0.1, block_samples=40)
    sizes = []
    with pytest.raises(EOFError):
        while True:
            block = src.read()
            assert block is not None
            sizes.append(block.n_samples)
    assert sizes == [40, 40, 20]
    with pytest.raises(EOFError):          # stays finished
        src.read()


def test_synthetic_t0_is_contiguous():
    blocks = drain(SyntheticSource("eeg", duration=1.0, block_samples=30))
    expected = 0
    for b in blocks:
        assert b.t0 == pytest.approx(expected / b.fs)
        expected += b.n_samples
    assert expected == 250


def test_synthetic_zero_duration_is_immediately_finished():
    with pytest.raises(EOFError):
        SyntheticSource("emg", duration=0.0).read()


def test_synthetic_read_before_start_starts_implicitly():
    src = SyntheticSource("emg")
    assert src.read() is not None


def test_synthetic_stop_makes_read_return_none_and_start_resumes():
    src = SyntheticSource("emg", block_samples=10)
    first = src.read()
    src.stop()
    assert src.read() is None
    src.start()
    nxt = src.read()
    assert nxt is not None and first is not None
    assert nxt.t0 == pytest.approx(first.t0 + first.n_samples / first.fs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "nope"},
        {"kind": "emg", "seed": -1},
        {"kind": "emg", "fs": 0.0},
        {"kind": "emg", "duration": -1.0},
        {"kind": "emg", "pop_rate": -1.0},
        {"kind": "emg", "mains_uv": -1.0},
    ],
)
def test_synthetic_rejects_bad_constructor_arguments(kwargs):
    with pytest.raises(ValueError):
        SyntheticSource(**kwargs)


def test_synthetic_kind_is_case_insensitive():
    assert SyntheticSource("  EMG ").kind == "emg"


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.schedule_squeeze(-1.0, 0.5),
        lambda s: s.schedule_squeeze(1.0, 0.0),
        lambda s: s.schedule_squeeze(1.0, -0.5),
        lambda s: s.schedule_squeeze(1.0, 0.5, amp=float("nan")),
        lambda s: s.schedule_blink(-0.1),
        lambda s: s.schedule_clench(1.0, 0.0),
        lambda s: s.schedule_dropout(1.0, 0.5, channel="nope"),
        lambda s: s.schedule_dropout(1.0, 0.5, channel=9),
        lambda s: s.schedule_pop(1.0, channel=-1),
    ],
)
def test_synthetic_scheduling_validates_input(call):
    with pytest.raises(ValueError):
        call(SyntheticSource("emg"))


def test_synthetic_scheduling_is_chainable():
    src = SyntheticSource("mixed")
    assert src.schedule_squeeze(1.0, 0.5) is src
    assert src.schedule_blink(2.0) is src
    assert src.schedule_clench(3.0, 0.5) is src


def test_synthetic_squeeze_is_visible_in_emg_rms():
    """RMS inside the scheduled squeeze window is far above the resting RMS."""
    src = SyntheticSource("emg", seed=3, duration=3.0, mains_uv=0.0, drift_uv=0.0)
    src.schedule_squeeze(1.0, 1.0, amp=200.0)
    data = stack(drain(src))
    inside = rms(window(data[0], src.fs, 1.1, 1.9))
    before = rms(window(data[0], src.fs, 0.1, 0.9))
    after = rms(window(data[0], src.fs, 2.1, 2.9))
    assert inside > 10 * before
    assert inside > 10 * after
    # the second channel is driven at 0.8x, so it also rises but less
    inside2 = rms(window(data[1], src.fs, 1.1, 1.9))
    assert inside2 > 5 * rms(window(data[1], src.fs, 0.1, 0.9))
    assert inside2 < inside


def test_synthetic_squeeze_does_not_touch_eeg_channels():
    """In the mixed montage a squeeze drives EMG channels only."""
    src = SyntheticSource("mixed", seed=3, duration=3.0, mains_uv=0.0, drift_uv=0.0)
    src.schedule_squeeze(1.0, 1.0, amp=200.0)
    data = stack(drain(src))
    fp1_in = rms(window(data[0], src.fs, 1.1, 1.9))
    fp1_out = rms(window(data[0], src.fs, 0.1, 0.9))
    emg_in = rms(window(data[2], src.fs, 1.1, 1.9))
    assert fp1_in == pytest.approx(fp1_out, rel=0.5)
    assert emg_in > 10 * fp1_in


def test_synthetic_blink_is_visible_on_frontal_channel_more_than_central():
    src = SyntheticSource("eeg", seed=4, duration=2.0, mains_uv=0.0, drift_uv=0.0)
    src.schedule_blink(1.0, amp=150.0)
    data = stack(drain(src))
    fs = src.fs
    fp1_in = rms(window(data[0], fs, 1.0, 1.3))
    fp1_out = rms(window(data[0], fs, 0.2, 0.9))
    c3_in = rms(window(data[2], fs, 1.0, 1.3))
    assert fp1_in > 3 * fp1_out
    assert fp1_in > 3 * c3_in
    # one smooth bump: peak lands inside the 300 ms window
    peak = int(np.argmax(data[0, int(0.9 * fs):int(1.5 * fs)])) / fs + 0.9
    assert 1.0 <= peak <= 1.3


def test_synthetic_clench_is_visible_on_emg():
    src = SyntheticSource("mixed", seed=5, duration=3.0, mains_uv=0.0, drift_uv=0.0)
    src.schedule_clench(1.0, 1.0, amp=80.0)
    data = stack(drain(src))
    fs = src.fs
    assert rms(window(data[2], fs, 1.1, 1.9)) > 5 * rms(window(data[2], fs, 0.1, 0.9))


def test_synthetic_event_in_the_past_does_not_rewrite_history():
    """Scheduling inside already-emitted samples leaves those samples unchanged."""
    a = SyntheticSource("emg", seed=8, block_samples=100)
    b = SyntheticSource("emg", seed=8, block_samples=100)
    first_a = a.read()
    first_b = b.read()
    assert first_a is not None and first_b is not None
    a.schedule_squeeze(0.0, 0.05, amp=500.0)    # entirely inside the block already emitted
    assert np.array_equal(first_a.data, first_b.data)


def test_synthetic_ground_truth_contents_and_order():
    src = SyntheticSource("mixed")
    src.schedule_clench(4.0, 0.5, amp=60.0)
    src.schedule_squeeze(1.0, 0.5, amp=210.0)
    src.schedule_blink(0.5, amp=120.0)
    src.schedule_dropout(2.0, 0.2)
    src.schedule_pop(3.0)
    truth = src.ground_truth()
    kinds = [e.kind for e in truth]
    assert kinds == [EventKind.BLINK, EventKind.SQUEEZE_ON, EventKind.SQUEEZE_OFF,
                     EventKind.JAW_CLENCH]
    times = [e.t for e in truth]
    assert times == sorted(times)
    blink, on, off, clench = truth
    assert blink.t == pytest.approx(0.5 + 0.15)         # reported at its peak, mid-bump
    assert on.t == pytest.approx(1.0)
    assert off.t == pytest.approx(1.5)
    assert clench.t == pytest.approx(4.0)
    assert blink.detail["synthetic"] is True
    assert blink.detail["amp"] == 120.0
    assert on.detail["amp"] == 210.0
    assert clench.detail["amp"] == 60.0


def test_synthetic_ground_truth_empty_without_events_and_detail_not_shared():
    src = SyntheticSource("emg")
    assert src.ground_truth() == []
    src.schedule_squeeze(1.0, 0.5)
    on, off = src.ground_truth()
    on.detail["x"] = 1
    assert "x" not in off.detail
    assert "x" not in src.ground_truth()[0].detail


def test_synthetic_dropout_flatlines_only_the_named_channel():
    src = SyntheticSource("emg", seed=2, duration=1.0, block_samples=37)
    src.schedule_dropout(0.4, 0.2, channel="EMG1")
    data = stack(drain(src))
    fs = src.fs
    dead = window(data[0], fs, 0.41, 0.59)
    assert np.all(dead == 0.0)
    assert np.any(window(data[1], fs, 0.41, 0.59) != 0.0)
    assert np.any(window(data[0], fs, 0.0, 0.39) != 0.0)
    assert np.any(window(data[0], fs, 0.61, 0.99) != 0.0)


def test_synthetic_pop_adds_exactly_its_decaying_step():
    """Compared against an identical fault-free source, the difference is amp * exp(-t/tau)."""
    plain = stack(drain(SyntheticSource("emg", seed=6, duration=1.0, block_samples=50)))
    popped_src = SyntheticSource("emg", seed=6, duration=1.0, block_samples=50)
    popped_src.schedule_pop(0.5, amp=1000.0, channel=1)
    popped = stack(drain(popped_src))
    diff = popped - plain
    fs = popped_src.fs
    i0 = int(0.5 * fs)
    assert np.allclose(diff[0], 0.0)                    # other channel untouched
    assert np.allclose(diff[1, :i0], 0.0)               # nothing before the pop
    assert diff[1, i0] == pytest.approx(1000.0)
    assert diff[1, i0 + 150] == pytest.approx(1000.0 * np.exp(-0.15 / 0.15), rel=1e-6)
    assert diff[1, i0 + 400] < diff[1, i0 + 150] < diff[1, i0]


def test_synthetic_negative_pop_is_signed():
    plain = stack(drain(SyntheticSource("emg", seed=6, duration=0.6)))
    src = SyntheticSource("emg", seed=6, duration=0.6)
    src.schedule_pop(0.3, amp=-800.0)
    diff = stack(drain(src)) - plain
    assert diff[0, int(0.3 * src.fs)] == pytest.approx(-800.0)


@pytest.mark.parametrize("kind", ["emg", "eeg", "mixed"])
def test_synthetic_random_faults_never_produce_nan_or_inf(kind):
    src = SyntheticSource(kind, seed=11, duration=6.0, dropout_rate=3.0, pop_rate=3.0)
    src.schedule_dropout(0.5, 0.3).schedule_pop(1.0)
    data = stack(drain(src))
    assert np.isfinite(data).all()
    assert data.shape[1] == round(6.0 * src.fs)


def test_synthetic_random_faults_are_deterministic_and_actually_happen():
    def run(rate: float) -> np.ndarray:
        return stack(drain(SyntheticSource("emg", seed=11, duration=5.0, pop_rate=rate)))

    assert np.array_equal(run(2.0), run(2.0))
    assert not np.array_equal(run(2.0), run(0.0))
    assert np.abs(run(2.0)).max() > 400.0               # pops are 600-1500 uV


def test_synthetic_realtime_pacing_with_injected_clock():
    """No block is due until the clock says a whole block of samples has elapsed."""
    now = [100.0]
    src = SyntheticSource("emg", block_samples=40, realtime=True, clock=lambda: now[0])
    src.start()                                          # fs 1000 -> a block is 0.04 s
    assert src.read() is None
    now[0] += 0.039
    assert src.read() is None
    now[0] += 0.001
    block = src.read()
    assert block is not None and block.n_samples == 40
    assert src.read() is None                            # that block was paid for
    now[0] += 0.08
    assert src.read() is not None
    assert src.read() is not None
    assert src.read() is None


def test_synthetic_non_realtime_never_returns_none():
    src = SyntheticSource("emg", block_samples=10)
    assert all(src.read() is not None for _ in range(20))


# ------------------------------------------------------------------ iter_blocks


def test_iter_blocks_starts_yields_and_stops():
    blocks = make_blocks(2)
    src = ScriptedSource(blocks)
    assert list(iter_blocks(src)) == blocks
    assert src.started == 1
    assert src.stopped == 1


def test_iter_blocks_backs_off_on_none_without_real_sleep():
    blocks = make_blocks(1)
    src = ScriptedSource([None, None, blocks[0]])
    slept: list[float] = []
    out = list(iter_blocks(src, idle_sleep=0.123, sleep=slept.append))
    assert out == blocks
    assert slept == [0.123, 0.123]


def test_iter_blocks_stops_source_when_consumer_abandons():
    src = ScriptedSource(make_blocks(5))
    it = iter_blocks(src)
    next(it)
    it.close()
    assert src.stopped == 1


def test_iter_blocks_stops_source_when_read_raises():
    src = ScriptedSource([RuntimeError("boom")])
    with pytest.raises(RuntimeError):
        list(iter_blocks(src))
    assert src.stopped == 1


# ------------------------------------------------------------------ write_csv / FileReplaySource


def test_csv_round_trip_values_channels_fs_t0(tmp_path: Path):
    blocks = make_blocks(4, n=60, fs=250.0, t0=12.5)
    path = tmp_path / "rec.csv"
    assert write_csv(path, blocks) == 240
    rep = FileReplaySource(path)
    assert rep.fs == 250.0
    assert rep.channels == blocks[0].channels
    assert rep.n_samples == 240
    assert rep.duration == pytest.approx(240 / 250.0)
    out = drain(rep)
    assert out[0].t0 == pytest.approx(12.5)
    assert np.allclose(stack(out), stack(blocks), atol=5e-5)     # CSV keeps 4 decimals
    for b in out:
        assert b.fs == 250.0
        assert b.channels == blocks[0].channels
    t0s = [b.t0 for b in out]
    assert t0s == sorted(t0s)
    assert t0s[1] == pytest.approx(12.5 + out[0].n_samples / 250.0)


def test_npz_round_trip_is_exact(tmp_path: Path):
    blocks = make_blocks(3, n=40, fs=200.0, t0=3.0)
    path = tmp_path / "rec.npz"
    assert write_npz(path, blocks) == 120
    rep = FileReplaySource(path)
    assert rep.fs == 200.0
    assert rep.channels == blocks[0].channels
    out = drain(rep)
    assert out[0].t0 == pytest.approx(3.0)
    assert np.array_equal(stack(out), stack(blocks))


def test_replay_of_synthetic_session_via_both_formats(tmp_path: Path):
    src = SyntheticSource("mixed", seed=9, duration=1.0)
    original = drain(src)
    write_csv(tmp_path / "a.csv", original)
    write_npz(tmp_path / "a.npz", original)
    for name in ("a.csv", "a.npz"):
        rep = FileReplaySource(tmp_path / name)
        assert rep.fs == src.fs
        assert [c.name for c in rep.channels] == [c.name for c in src.channels]
        assert [c.kind for c in rep.channels] == [c.kind for c in src.channels]
        assert np.allclose(stack(drain(rep)), stack(original), atol=5e-5)


def test_replay_block_size_and_ragged_last_block(tmp_path: Path):
    write_npz(tmp_path / "r.npz", make_blocks(1, n=105))
    rep = FileReplaySource(tmp_path / "r.npz", block_samples=40)
    assert [b.n_samples for b in drain(rep)] == [40, 40, 25]


def test_replay_default_block_is_about_40ms(tmp_path: Path):
    write_npz(tmp_path / "r.npz", make_blocks(1, n=100, fs=250.0))
    rep = FileReplaySource(tmp_path / "r.npz")
    first = rep.read()
    assert first is not None and first.n_samples == 10


def test_replay_ends_with_eoferror_and_start_rewinds(tmp_path: Path):
    blocks = make_blocks(2, n=30)
    write_npz(tmp_path / "r.npz", blocks)
    rep = FileReplaySource(tmp_path / "r.npz", block_samples=30)
    rep.start()
    first = rep.read()
    assert first is not None
    rep.read()
    with pytest.raises(EOFError):
        rep.read()
    with pytest.raises(EOFError):
        rep.read()
    rep.start()
    again = rep.read()
    assert again is not None
    assert np.array_equal(first.data, again.data)
    assert first.t0 == again.t0


def test_replay_blocks_are_copies(tmp_path: Path):
    write_npz(tmp_path / "r.npz", make_blocks(1, n=30))
    rep = FileReplaySource(tmp_path / "r.npz", block_samples=30)
    first = rep.read()
    assert first is not None
    first.data[:] = 12345.0
    rep.start()
    again = rep.read()
    assert again is not None
    assert not np.any(again.data == 12345.0)


def test_replay_realtime_pacing_with_injected_clock(tmp_path: Path):
    write_npz(tmp_path / "r.npz", make_blocks(1, n=100, fs=100.0))
    now = [0.0]
    rep = FileReplaySource(tmp_path / "r.npz", block_samples=10, realtime=True,
                           clock=lambda: now[0])
    rep.start()
    assert rep.read() is None
    now[0] = 0.099
    assert rep.read() is None
    now[0] = 0.1
    assert rep.read() is not None
    assert rep.read() is None


def test_replay_missing_file_raises_filenotfound(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        FileReplaySource(tmp_path / "nope.csv")
    with pytest.raises(FileNotFoundError):
        FileReplaySource(tmp_path)                      # a directory is not a recording


def test_replay_expands_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    write_npz(tmp_path / "r.npz", make_blocks(1))
    assert FileReplaySource("~/r.npz").n_samples == 50


def _write_csv_text(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_csv_header_grammar_name_kind(tmp_path: Path):
    p = _write_csv_text(tmp_path / "h.csv", "# fs=100\nFp1:eeg, EMG1:EMG ,EOG_V:eog\n1,2,3\n4,5,6\n")
    rep = FileReplaySource(p)
    assert rep.channels == (
        ChannelInfo("Fp1", SignalKind.EEG),
        ChannelInfo("EMG1", SignalKind.EMG),
        ChannelInfo("EOG_V", SignalKind.EOG),
    )
    block = rep.read()
    assert block is not None
    assert block.data.tolist() == [[1.0, 4.0], [2.0, 5.0], [3.0, 6.0]]


def test_csv_kind_is_text_after_last_colon(tmp_path: Path):
    p = _write_csv_text(tmp_path / "h.csv", "# fs=100\nA:B:emg\n1\n")
    assert FileReplaySource(p).channels == (ChannelInfo("A:B", SignalKind.EMG),)


@pytest.mark.parametrize("header", ["Fp1", "Fp1:bogus", ":eeg", "Fp1:"])
def test_csv_bad_channel_spec_is_valueerror(tmp_path: Path, header: str):
    p = _write_csv_text(tmp_path / "bad.csv", f"# fs=100\n{header}\n1\n")
    with pytest.raises(ValueError):
        FileReplaySource(p)


def test_csv_without_fs_or_time_column_is_valueerror(tmp_path: Path):
    p = _write_csv_text(tmp_path / "nofs.csv", "Fp1:eeg\n1\n2\n")
    with pytest.raises(ValueError, match="sampling rate"):
        FileReplaySource(p)


def test_csv_fs_argument_supplies_or_overrides_rate(tmp_path: Path):
    p = _write_csv_text(tmp_path / "nofs.csv", "Fp1:eeg\n1\n2\n")
    assert FileReplaySource(p, fs=500.0).fs == 500.0
    q = _write_csv_text(tmp_path / "fs.csv", "# fs=100\nFp1:eeg\n1\n2\n")
    assert FileReplaySource(q).fs == 100.0
    assert FileReplaySource(q, fs=250.0).fs == 250.0


def test_csv_time_column_infers_fs_and_t0(tmp_path: Path):
    times = 5.0 + np.arange(20) * 0.004
    body = "\n".join(f"{float(t)!r},{i},{-i}" for i, t in enumerate(times))
    for name in ("t", "time", "Timestamp"):
        p = _write_csv_text(tmp_path / f"{name}.csv", f"{name},Fp1:eeg,Fp2:eeg\n{body}\n")
        rep = FileReplaySource(p)
        assert rep.fs == pytest.approx(250.0)
        assert [c.name for c in rep.channels] == ["Fp1", "Fp2"]      # time column dropped
        assert rep.n_samples == 20
        block = rep.read()
        assert block is not None
        assert block.t0 == pytest.approx(5.0)
        assert block.data.shape[0] == 2


def test_csv_explicit_fs_beats_time_column_inference(tmp_path: Path):
    p = _write_csv_text(tmp_path / "t.csv", "# fs=100\nt,Fp1:eeg\n0.0,1\n0.004,2\n")
    assert FileReplaySource(p).fs == 100.0


def test_csv_t0_comment(tmp_path: Path):
    p = _write_csv_text(tmp_path / "t0.csv", "# fs=100\n# t0=42.5\nFp1:eeg\n1\n2\n")
    block = FileReplaySource(p, block_samples=1).read()
    assert block is not None and block.t0 == pytest.approx(42.5)


def test_csv_comment_lines_and_blank_lines_are_tolerated(tmp_path: Path):
    p = _write_csv_text(tmp_path / "c.csv", "# recorded by hand\n\n# fs=100\n\nFp1:eeg\n1\n2\n")
    assert FileReplaySource(p).n_samples == 2


def test_csv_empty_or_comment_only_file_is_valueerror(tmp_path: Path):
    with pytest.raises(ValueError):
        FileReplaySource(_write_csv_text(tmp_path / "e.csv", ""))
    with pytest.raises(ValueError):
        FileReplaySource(_write_csv_text(tmp_path / "e2.csv", "# fs=100\n"))


def test_csv_header_only_is_a_zero_length_recording(tmp_path: Path):
    rep = FileReplaySource(_write_csv_text(tmp_path / "h.csv", "# fs=100\nFp1:eeg\n"))
    assert rep.n_samples == 0
    with pytest.raises(EOFError):
        rep.read()


def test_csv_time_column_only_header_is_valueerror(tmp_path: Path):
    with pytest.raises(ValueError):
        FileReplaySource(_write_csv_text(tmp_path / "t.csv", "# fs=100\nt\n0.0\n"))


def test_csv_column_count_mismatch_is_valueerror(tmp_path: Path):
    p = _write_csv_text(tmp_path / "m.csv", "# fs=100\nFp1:eeg,Fp2:eeg\n1,2,3\n")
    with pytest.raises(ValueError):
        FileReplaySource(p)


def test_csv_non_numeric_row_is_valueerror(tmp_path: Path):
    p = _write_csv_text(tmp_path / "n.csv", "# fs=100\nFp1:eeg\nabc\n")
    with pytest.raises(ValueError):
        FileReplaySource(p)


def test_csv_non_finite_samples_become_zero_with_warning(tmp_path: Path, caplog):
    p = _write_csv_text(tmp_path / "nan.csv", "# fs=100\nFp1:eeg,Fp2:eeg\n1,nan\ninf,4\n")
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        rep = FileReplaySource(p, block_samples=10)
    block = rep.read()
    assert block is not None
    assert block.data.tolist() == [[1.0, 0.0], [0.0, 4.0]]
    assert "non-finite" in caplog.text


def test_csv_single_sample_single_channel(tmp_path: Path):
    p = _write_csv_text(tmp_path / "one.csv", "# fs=100\nFp1:eeg\n7\n")
    block = FileReplaySource(p).read()
    assert block is not None and block.data.shape == (1, 1)


def test_npz_missing_arrays_is_valueerror(tmp_path: Path):
    np.savez(tmp_path / "bad.npz", data=np.zeros((1, 5)))
    with pytest.raises(ValueError):
        FileReplaySource(tmp_path / "bad.npz")


def test_npz_shape_mismatch_is_valueerror(tmp_path: Path):
    np.savez(tmp_path / "bad.npz", data=np.zeros((2, 5)), channels=np.array(["A:eeg"]),
             fs=np.float64(100))
    with pytest.raises(ValueError):
        FileReplaySource(tmp_path / "bad.npz")
    np.savez(tmp_path / "bad1d.npz", data=np.zeros(5), channels=np.array(["A:eeg"]),
             fs=np.float64(100))
    with pytest.raises(ValueError):
        FileReplaySource(tmp_path / "bad1d.npz")


def test_npz_missing_fs_needs_argument(tmp_path: Path):
    np.savez(tmp_path / "nofs.npz", data=np.zeros((1, 5)), channels=np.array(["A:eeg"]))
    with pytest.raises(ValueError, match="sampling rate"):
        FileReplaySource(tmp_path / "nofs.npz")
    assert FileReplaySource(tmp_path / "nofs.npz", fs=125.0).fs == 125.0


def test_npz_without_t0_starts_at_zero(tmp_path: Path):
    np.savez(tmp_path / "x.npz", data=np.ones((1, 5)), channels=np.array(["A:emg"]),
             fs=np.float64(100))
    block = FileReplaySource(tmp_path / "x.npz").read()
    assert block is not None and block.t0 == 0.0


def test_npz_bad_kind_is_valueerror(tmp_path: Path):
    np.savez(tmp_path / "k.npz", data=np.zeros((1, 5)), channels=np.array(["A:nope"]),
             fs=np.float64(100))
    with pytest.raises(ValueError):
        FileReplaySource(tmp_path / "k.npz")


def test_npz_pickled_object_arrays_are_refused(tmp_path: Path):
    """allow_pickle=False: an object array cannot smuggle code in."""
    np.savez(tmp_path / "p.npz", data=np.array([{"a": 1}], dtype=object),
             channels=np.array(["A:eeg"]), fs=np.float64(100))
    with pytest.raises(ValueError):
        FileReplaySource(tmp_path / "p.npz")


def test_npz_garbage_file_is_valueerror(tmp_path: Path):
    p = tmp_path / "junk.npz"
    p.write_bytes(b"this is not a zip archive at all" * 8)
    with pytest.raises(ValueError):
        FileReplaySource(p)


def test_write_helpers_reject_empty_input(tmp_path: Path):
    with pytest.raises(ValueError):
        write_csv(tmp_path / "e.csv", [])
    with pytest.raises(ValueError):
        write_npz(tmp_path / "e.npz", [])
    assert not (tmp_path / "e.npz").exists()


def test_write_helpers_reject_changed_channels_or_fs(tmp_path: Path):
    a, b = make_blocks(2, kinds=(SignalKind.EEG,))[:2], make_blocks(1, fs=500.0, kinds=(SignalKind.EEG,))
    for writer, name in ((write_csv, "m.csv"), (write_npz, "m.npz")):
        with pytest.raises(ValueError):
            writer(tmp_path / name, [*a, *b])
    c = make_blocks(1, kinds=(SignalKind.EMG,))
    with pytest.raises(ValueError):
        write_npz(tmp_path / "m2.npz", [*a, *c])


@pytest.mark.parametrize("bad", ["a,b", "a\nb", " "])
def test_write_csv_rejects_unwritable_channel_names(tmp_path: Path, bad: str):
    block = SampleBlock(np.zeros((1, 4)), 100.0, (ChannelInfo(bad, SignalKind.EEG),))
    with pytest.raises(ValueError):
        write_csv(tmp_path / "x.csv", [block])


@posix_only
@pytest.mark.parametrize("name", ["m.csv", "m.npz"])
def test_written_recordings_are_owner_only(tmp_path: Path, name: str):
    writer = write_npz if name.endswith(".npz") else write_csv
    writer(tmp_path / name, make_blocks(1))
    assert (tmp_path / name).stat().st_mode & 0o777 == 0o600


@posix_only
def test_write_tightens_a_preexisting_loose_file(tmp_path: Path):
    p = tmp_path / "loose.csv"
    p.write_text("old", encoding="utf-8")
    p.chmod(0o644)
    write_csv(p, make_blocks(1))
    assert p.stat().st_mode & 0o777 == 0o600
    assert "old" not in p.read_text(encoding="utf-8")


def test_write_creates_parent_directories(tmp_path: Path):
    p = tmp_path / "a" / "b" / "rec.csv"
    write_csv(p, make_blocks(1))
    assert p.is_file()


def test_write_csv_warns_once_on_gap_and_closes_it_on_replay(tmp_path: Path, caplog):
    b = make_blocks(3, n=50)
    gappy = [b[0], SampleBlock(b[1].data, b[1].fs, b[1].channels, t0=b[1].t0 + 5.0), b[2]]
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        assert write_csv(tmp_path / "g.csv", gappy) == 150
    assert caplog.text.count("not contiguous") == 1
    assert FileReplaySource(tmp_path / "g.csv").n_samples == 150


# ------------------------------------------------------------------ RecordingTap


def test_tap_records_exactly_what_the_inner_source_emitted(tmp_path: Path):
    inner = SyntheticSource("mixed", seed=12, duration=1.0)
    tap = RecordingTap(inner, tmp_path / "tap.csv")
    emitted = drain(tap)
    assert sum(b.n_samples for b in emitted) == round(inner.fs * 1.0)
    rep = FileReplaySource(tmp_path / "tap.csv")
    assert rep.fs == inner.fs
    assert rep.channels == inner.channels
    assert np.allclose(stack(drain(rep)), stack(emitted), atol=5e-5)


def test_tap_returns_the_very_same_blocks(tmp_path: Path):
    blocks = make_blocks(2)
    tap = RecordingTap(ScriptedSource([blocks[0], None, blocks[1]]), tmp_path / "t.csv")
    tap.start()
    assert tap.read() is blocks[0]
    assert tap.read() is None
    assert tap.read() is blocks[1]
    assert tap.fs == blocks[1].fs
    assert tap.channels == blocks[1].channels
    tap.stop()


def test_tap_propagates_start_stop_and_eof(tmp_path: Path):
    inner = ScriptedSource([])
    tap = RecordingTap(inner, tmp_path / "t.csv")
    tap.start()
    with pytest.raises(EOFError):
        tap.read()
    tap.stop()
    assert (inner.started, inner.stopped) == (1, 1)


def test_tap_exposes_inner_metadata_before_first_block(tmp_path: Path):
    inner = SyntheticSource("eeg")
    tap = RecordingTap(inner, tmp_path / "t.csv")
    assert tap.fs == inner.fs
    assert tap.channels == inner.channels
    assert isinstance(tap, BlockSource)


def test_tap_writes_nothing_until_a_block_arrives(tmp_path: Path):
    tap = RecordingTap(ScriptedSource([None]), tmp_path / "t.csv")
    tap.start()
    assert tap.read() is None
    tap.stop()
    assert not (tmp_path / "t.csv").exists()


@posix_only
@pytest.mark.parametrize("name", ["t.csv", "t.npz"])
def test_tap_file_mode_is_0600(tmp_path: Path, name: str):
    drain(RecordingTap(SyntheticSource("emg", duration=0.2), tmp_path / name))
    assert (tmp_path / name).stat().st_mode & 0o777 == 0o600


def test_tap_csv_is_streamed_while_running(tmp_path: Path):
    tap = RecordingTap(SyntheticSource("emg", block_samples=20), tmp_path / "t.csv")
    tap.start()
    assert tap.read() is not None
    assert (tmp_path / "t.csv").is_file()               # created on first block, not on stop
    tap.stop()


def test_tap_npz_buffers_until_stop(tmp_path: Path):
    path = tmp_path / "t.npz"
    tap = RecordingTap(SyntheticSource("emg", seed=1, block_samples=20), path)
    tap.start()
    emitted = [b for b in (tap.read() for _ in range(3)) if b is not None]
    assert not path.exists()
    tap.stop()
    assert path.is_file()
    assert np.array_equal(stack(drain(FileReplaySource(path))), stack(emitted))


def test_tap_npz_is_finished_at_end_of_stream(tmp_path: Path):
    path = tmp_path / "t.npz"
    emitted = drain(RecordingTap(SyntheticSource("emg", seed=1, duration=0.2), path))
    assert np.array_equal(stack(drain(FileReplaySource(path))), stack(emitted))


def test_tap_stop_twice_does_not_rewrite_or_fail(tmp_path: Path):
    path = tmp_path / "t.npz"
    tap = RecordingTap(ScriptedSource(make_blocks(1)), path)
    tap.start()
    tap.read()
    tap.stop()
    stamp = path.stat().st_mtime_ns
    tap.stop()
    assert path.stat().st_mtime_ns == stamp


def test_tap_warns_that_recording_is_sensitive(tmp_path: Path, caplog):
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        drain(RecordingTap(ScriptedSource(make_blocks(3)), tmp_path / "t.csv"))
    assert caplog.text.count("Recording raw biosignal samples") == 1


def test_tap_write_failure_is_logged_and_stream_continues(tmp_path: Path, caplog):
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    blocks = make_blocks(4)
    tap = RecordingTap(ScriptedSource(blocks), blocker / "rec.csv")   # parent is a file
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        out = drain(tap)
    assert out == blocks                                 # every block still delivered
    assert caplog.text.count("failed; the stream continues") == 1
    assert blocker.read_text(encoding="utf-8") == "x"


def test_tap_npz_write_failure_at_stop_is_logged_not_raised(tmp_path: Path, caplog):
    blocker = tmp_path / "a-file"
    blocker.write_text("x", encoding="utf-8")
    blocks = make_blocks(2)
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        out = drain(RecordingTap(ScriptedSource(blocks), blocker / "rec.npz"))
    assert out == blocks
    assert "Writing" in caplog.text


def test_tap_mid_stream_format_change_stops_recording_but_not_the_stream(tmp_path: Path, caplog):
    good = make_blocks(2, kinds=(SignalKind.EEG,))
    other = make_blocks(1, kinds=(SignalKind.EMG,))
    tap = RecordingTap(ScriptedSource([good[0], other[0], good[1]]), tmp_path / "t.csv")
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        out = drain(tap)
    assert out == [good[0], other[0], good[1]]
    assert "failed" in caplog.text
    assert FileReplaySource(tmp_path / "t.csv").n_samples == good[0].n_samples


def test_tap_stops_inner_even_if_finish_is_noop(tmp_path: Path):
    inner = ScriptedSource([])
    RecordingTap(inner, tmp_path / "t.csv").stop()
    assert inner.stopped == 1


# ------------------------------------------------------------------ BrainFlow fake board


class FakeBoard:
    """A BrainFlow-shaped board: row 0 timestamps, rows 1..n_eeg EEG, then EMG rows."""

    def __init__(
        self, *, fs=250.0, eeg=(1, 2), emg=(), eog=(), eeg_names=("Fz", "Cz"),
        ts_row=0, n_rows=4, name="Fake Board",
        prepare_error=None, start_error=None, read_error=None,
    ):
        self.fs, self.eeg, self.emg, self.eog = fs, list(eeg), list(emg), list(eog)
        self.eeg_names, self.ts_row, self.n_rows, self.name = list(eeg_names), ts_row, n_rows, name
        self.prepare_error, self.start_error, self.read_error = (
            prepare_error, start_error, read_error)
        self.calls: list[str] = []
        self.pending: list[np.ndarray] = []
        self.current: np.ndarray = np.zeros((n_rows, 0))

    # static-style getters (called on the instance by the source)
    def get_sampling_rate(self, board_id):
        return self.fs

    def get_eeg_channels(self, board_id):
        return self.eeg

    def get_emg_channels(self, board_id):
        return self.emg

    def get_eog_channels(self, board_id):
        return self.eog

    def get_eeg_names(self, board_id):
        return self.eeg_names

    def get_timestamp_channel(self, board_id):
        if self.ts_row is None:
            raise RuntimeError("no timestamp channel")
        return self.ts_row

    # lifecycle
    def prepare_session(self):
        self.calls.append("prepare_session")
        if self.prepare_error:
            raise self.prepare_error

    def start_stream(self):
        self.calls.append("start_stream")
        if self.start_error:
            raise self.start_error

    def get_board_data(self):
        self.calls.append("get_board_data")
        if self.read_error:
            raise self.read_error
        if not self.pending:
            return np.zeros((self.n_rows, 0))
        return self.pending.pop(0)

    def get_current_board_data(self, n):
        self.calls.append(f"get_current_board_data({n})")
        return self.current[:, -n:]

    def stop_stream(self):
        self.calls.append("stop_stream")

    def release_session(self):
        self.calls.append("release_session")

    # test helper
    def push(self, n, *, t_start=1000.0, fill=None):
        """Queue one batch of ``n`` samples whose first timestamp is ``t_start``."""
        raw = np.zeros((self.n_rows, n))
        if self.ts_row is not None:
            raw[self.ts_row] = t_start + np.arange(n) / self.fs
        for r in range(self.n_rows):
            if r != self.ts_row:
                raw[r] = (r * 10.0 + np.arange(n)) if fill is None else fill
        self.pending.append(raw)
        return raw


def started(board: FakeBoard, **kw) -> BrainFlowBlockSource:
    src = BrainFlowBlockSource(0, board_factory=lambda: board, **kw)
    src.start()
    return src


def test_brainflow_lifecycle_calls_and_metadata():
    board = FakeBoard()
    src = BrainFlowBlockSource(0, board_factory=lambda: board)
    assert (src.available, src.fs, src.channels) == (False, 0.0, ())
    src.start()
    assert board.calls == ["prepare_session", "start_stream"]
    assert src.available is True
    assert src.fs == 250.0
    assert src.channels == (ChannelInfo("Fz", SignalKind.EEG), ChannelInfo("Cz", SignalKind.EEG))
    src.stop()
    assert board.calls[-2:] == ["stop_stream", "release_session"]
    assert src.available is False
    assert src.read() is None


def test_brainflow_start_is_idempotent_and_stop_twice_is_safe():
    board = FakeBoard()
    src = started(board)
    src.start()
    assert board.calls.count("prepare_session") == 1
    src.stop()
    src.stop()
    assert board.calls.count("release_session") == 1


def test_brainflow_rows_map_to_channels_in_order_and_values_pass_through():
    board = FakeBoard()
    raw = board.push(8)
    src = started(board)
    block = src.read()
    assert block is not None
    assert block.data.shape == (2, 8)
    assert np.array_equal(block.data, raw[[1, 2], :])
    assert block.fs == 250.0
    assert block.channels == src.channels


def test_brainflow_uv_scale_multiplies_rows():
    board = FakeBoard()
    raw = board.push(5)
    block = started(board, uv_scale=0.5).read()
    assert block is not None
    assert np.allclose(block.data, raw[[1, 2], :] * 0.5)


def test_brainflow_default_classification_eeg_emg_eog_without_double_counting():
    board = FakeBoard(eeg=(1, 2), emg=(2, 3), eog=(4,), eeg_names=("Fp1", "Fp2"), n_rows=6)
    src = started(board)
    assert src.channels == (
        ChannelInfo("Fp1", SignalKind.EEG),
        ChannelInfo("Fp2", SignalKind.EEG),
        ChannelInfo("EMG1", SignalKind.EMG),       # row 2 is EEG, so only row 3 is EMG
        ChannelInfo("EOG1", SignalKind.EOG),
    )
    board.push(4)
    block = src.read()
    assert block is not None and block.data.shape == (4, 4)


def test_brainflow_unnamed_eeg_rows_get_generic_names():
    src = started(FakeBoard(eeg_names=("only-one",)))        # misaligned names are not guessed
    assert [c.name for c in src.channels] == ["EEG1", "EEG2"]


def test_brainflow_channel_kinds_selects_and_overrides(caplog):
    board = FakeBoard(eeg=(1, 2, 3), eeg_names=("A", "B", "C"), n_rows=5)
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        src = started(board, channel_kinds={"B": "emg", "C": SignalKind.EOG, "ghost": "eeg"})
    assert src.channels == (ChannelInfo("B", SignalKind.EMG), ChannelInfo("C", SignalKind.EOG))
    assert "ghost" in caplog.text
    raw = board.push(6)
    block = src.read()
    assert block is not None
    assert np.array_equal(block.data, raw[[2, 3], :])


def test_brainflow_no_channels_is_a_logged_failure(caplog):
    board = FakeBoard(eeg=(), emg=(), eog=(), eeg_names=())
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        src = started(board)
    assert src.available is False
    assert "no usable channels" in src.last_error
    assert "release_session" in board.calls
    assert src.read() is None


def test_brainflow_empty_read_returns_none():
    src = started(FakeBoard())
    assert src.read() is None                               # nothing buffered
    assert src.available is True


def test_brainflow_t0_is_zero_based_and_contiguous():
    board = FakeBoard(fs=250.0)
    board.push(10, t_start=1000.0)
    board.push(25, t_start=1000.0 + 10 / 250.0)
    board.push(5, t_start=1000.0 + 35 / 250.0)
    src = started(board)
    blocks = [src.read() for _ in range(3)]
    assert all(b is not None for b in blocks)
    t0s = [b.t0 for b in blocks if b is not None]
    assert t0s[0] == pytest.approx(0.0)
    assert t0s[1] == pytest.approx(10 / 250.0)
    assert t0s[2] == pytest.approx(35 / 250.0)
    assert src.gap_samples == 0


def test_brainflow_small_timestamp_jitter_is_snapped_to_continuous_clock():
    board = FakeBoard(fs=250.0)
    board.push(10, t_start=1000.0)
    board.push(10, t_start=1000.0 + 10 / 250.0 + 0.02)      # 20 ms late, under tolerance
    src = started(board)
    src.read()
    second = src.read()
    assert second is not None
    assert second.t0 == pytest.approx(10 / 250.0)
    assert src.gap_samples == 0


def test_brainflow_real_gap_resynchronises_and_counts_lost_samples(caplog):
    board = FakeBoard(fs=250.0)
    board.push(10, t_start=1000.0)
    board.push(10, t_start=1000.0 + 10 / 250.0 + 1.0)       # one second missing
    src = started(board)
    src.read()
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        second = src.read()
    assert second is not None
    assert second.t0 == pytest.approx(10 / 250.0 + 1.0)
    assert src.gap_samples == 250
    assert "missing" in caplog.text


def test_brainflow_clock_never_goes_backwards():
    board = FakeBoard(fs=250.0)
    board.push(10, t_start=1000.0)
    board.push(10, t_start=999.0)                           # board clock stepped back
    src = started(board)
    src.read()
    second = src.read()
    assert second is not None
    assert second.t0 == pytest.approx(10 / 250.0)


def test_brainflow_without_timestamp_row_is_contiguous_from_zero():
    board = FakeBoard(ts_row=None, eeg=(0, 1), n_rows=3)
    board.push(10)
    board.push(10)
    src = started(board)
    first, second = src.read(), src.read()
    assert first is not None and second is not None
    assert first.t0 == 0.0
    assert second.t0 == pytest.approx(10 / 250.0)


def test_brainflow_non_finite_samples_become_zero():
    board = FakeBoard()
    raw = board.push(4)
    raw[1, 2] = np.nan
    raw[2, 0] = np.inf
    block = started(board).read()
    assert block is not None
    assert np.isfinite(block.data).all()
    assert block.data[0, 2] == 0.0 and block.data[1, 0] == 0.0


def test_brainflow_peek_uses_current_data_and_does_not_advance():
    board = FakeBoard(fs=250.0)
    src = started(board)
    board.current = board.push(20, t_start=2000.0)
    board.pending.clear()
    first = src.peek(8)
    second = src.peek(8)
    assert first is not None and second is not None
    assert "get_current_board_data(8)" in board.calls
    assert "get_board_data" not in board.calls
    assert first.n_samples == 8
    assert first.t0 == second.t0                            # peeking leaves the clock alone
    assert src.gap_samples == 0


def test_brainflow_unplugged_device_is_a_logged_noop(caplog):
    board = FakeBoard(prepare_error=RuntimeError("UNABLE_TO_OPEN_PORT_ERROR:2"))
    src = BrainFlowBlockSource(0, "/dev/ttyUSB0", board_factory=lambda: board)
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        src.start()                                         # must not raise
    assert src.available is False
    assert "UNABLE_TO_OPEN_PORT" in src.last_error
    assert "UNABLE_TO_OPEN_PORT" in caplog.text
    assert src.read() is None
    assert src.read() is None
    src.stop()


def test_brainflow_factory_that_raises_is_a_logged_noop(caplog):
    def boom():
        raise OSError("device busy")

    src = BrainFlowBlockSource(0, board_factory=boom)
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        src.start()
    assert src.available is False
    assert "device busy" in caplog.text
    assert src.read() is None


def test_brainflow_start_stream_failure_releases_the_board(caplog):
    board = FakeBoard(start_error=RuntimeError("stream failed"))
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        src = started(board)
    assert src.available is False
    assert "stream failed" in src.last_error
    assert board.calls[-2:] == ["stop_stream", "release_session"]


def test_brainflow_can_retry_start_after_a_failure():
    board = FakeBoard(prepare_error=RuntimeError("busy"))
    src = BrainFlowBlockSource(0, board_factory=lambda: board)
    src.start()
    assert not src.available
    board.prepare_error = None
    src.start()
    assert src.available
    assert src.last_error == ""


def test_brainflow_read_error_mid_stream_stops_without_raising(caplog):
    board = FakeBoard()
    src = started(board)
    board.read_error = RuntimeError("device vanished")
    with caplog.at_level(logging.WARNING, logger=SRC_LOG):
        assert src.read() is None
    assert src.available is False
    assert "device vanished" in src.last_error
    assert "release_session" in board.calls
    assert src.read() is None


def test_brainflow_too_few_rows_is_a_failure_not_a_crash():
    board = FakeBoard(n_rows=4)
    src = started(board)
    board.pending.append(np.zeros((2, 5)))                   # board suddenly returns 2 rows
    assert src.read() is None
    assert src.available is False
    assert "rows" in src.last_error


def test_brainflow_missing_package_is_a_logged_noop_with_install_hint(
    monkeypatch: pytest.MonkeyPatch, caplog,
):
    monkeypatch.setitem(sys.modules, "brainflow", None)
    monkeypatch.setitem(sys.modules, "brainflow.board_shim", None)
    src = BrainFlowBlockSource(0)
    with caplog.at_level(logging.INFO, logger=SRC_LOG):
        src.start()                                         # must not raise
        assert src.read() is None
    assert src.available is False
    assert "not installed" in src.last_error
    assert "BrainFlow not installed" in caplog.text
    assert "emg-band" in caplog.text or "pip" in caplog.text or "uv" in caplog.text
    src.stop()


def _install_fake_brainflow(monkeypatch: pytest.MonkeyPatch, board: FakeBoard) -> dict:
    """Put a minimal ``brainflow.board_shim`` into sys.modules (function-scoped)."""
    record: dict = {}

    class InputParams:
        serial_port = ""

    class Shim:
        def __init__(self, board_id, params):
            record["board_id"] = board_id
            record["serial_port"] = params.serial_port

        def __getattr__(self, item):
            return getattr(board, item)

        @staticmethod
        def get_sampling_rate(board_id):
            if board_id == 999:
                raise ValueError("UNSUPPORTED_BOARD_ERROR")
            return board.fs

        @staticmethod
        def get_eeg_channels(board_id):
            return board.eeg

        @staticmethod
        def get_emg_channels(board_id):
            return board.emg

        @staticmethod
        def get_eog_channels(board_id):
            return board.eog

        @staticmethod
        def get_eeg_names(board_id):
            return board.eeg_names

        @staticmethod
        def get_timestamp_channel(board_id):
            return board.ts_row

        @staticmethod
        def get_device_name(board_id):
            return board.name

    pkg = types.ModuleType("brainflow")
    mod = types.ModuleType("brainflow.board_shim")
    mod.BoardShim = Shim                                    # type: ignore[attr-defined]
    mod.BrainFlowInputParams = InputParams                  # type: ignore[attr-defined]
    pkg.board_shim = mod                                    # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "brainflow", pkg)
    monkeypatch.setitem(sys.modules, "brainflow.board_shim", mod)
    return record


def test_brainflow_real_construction_path_passes_board_id_and_serial_port(
    monkeypatch: pytest.MonkeyPatch,
):
    board = FakeBoard()
    record = _install_fake_brainflow(monkeypatch, board)
    src = BrainFlowBlockSource(0, "/dev/ttyUSB0")
    src.start()
    assert src.available is True
    assert record == {"board_id": 0, "serial_port": "/dev/ttyUSB0"}
    assert "start_stream" in board.calls
    src.stop()


def test_describe_board_without_brainflow_never_raises(monkeypatch: pytest.MonkeyPatch, caplog):
    monkeypatch.setitem(sys.modules, "brainflow", None)
    monkeypatch.setitem(sys.modules, "brainflow.board_shim", None)
    with caplog.at_level(logging.INFO, logger=SRC_LOG):
        desc = describe_board(SYNTHETIC_BOARD_ID)
    assert isinstance(desc, BoardDescription)
    assert desc.available is False
    assert desc.board_id == SYNTHETIC_BOARD_ID
    assert desc.note
    assert "unavailable" in desc.format()


def test_describe_board_with_fake_brainflow(monkeypatch: pytest.MonkeyPatch):
    board = FakeBoard(emg=(3,), n_rows=5, name="Fake Board")
    _install_fake_brainflow(monkeypatch, board)
    desc = describe_board(0)
    assert desc.available is True
    assert desc.name == "Fake Board"
    assert desc.fs == 250.0
    assert [c.name for c in desc.channels] == ["Fz", "Cz", "EMG1"]
    assert desc.rows == (1, 2, 3)
    assert desc.timestamp_row == 0
    text = desc.format()
    assert "Fake Board" in text and "250 Hz" in text and "Fz:eeg@row1" in text


def test_describe_board_unknown_id_is_unavailable_not_an_exception(
    monkeypatch: pytest.MonkeyPatch,
):
    _install_fake_brainflow(monkeypatch, FakeBoard())
    desc = describe_board(999)
    assert desc.available is False
    assert "unknown board" in desc.note
    assert "unavailable" in desc.format()


def test_describe_board_survives_a_broken_device_name(monkeypatch: pytest.MonkeyPatch):
    board = FakeBoard()
    _install_fake_brainflow(monkeypatch, board)
    shim = sys.modules["brainflow.board_shim"].BoardShim

    def explode(board_id):
        raise RuntimeError("no name")

    monkeypatch.setattr(shim, "get_device_name", staticmethod(explode), raising=False)
    desc = describe_board(0)
    assert desc.available is True
    assert desc.name == ""
    assert "unnamed" in desc.format()


def test_describe_board_channel_kinds_override(monkeypatch: pytest.MonkeyPatch):
    _install_fake_brainflow(monkeypatch, FakeBoard())
    desc = describe_board(0, channel_kinds={"Cz": "emg"})
    assert desc.channels == (ChannelInfo("Cz", SignalKind.EMG),)
    assert desc.rows == (2,)


# ------------------------------------------------------------------ open_source


@pytest.mark.parametrize(
    ("spec", "kind"),
    [
        ("synthetic", "mixed"),
        ("synthetic:emg", "emg"),
        ("synthetic:eeg", "eeg"),
        ("synthetic:eog", "eog"),
        ("synthetic:mixed", "mixed"),
        ("  Synthetic : EMG ", "emg"),
    ],
)
def test_open_source_synthetic_specs(spec: str, kind: str):
    src = open_source(spec)
    assert isinstance(src, SyntheticSource)
    assert src.kind == kind


def test_open_source_forwards_keyword_arguments():
    src = open_source("synthetic:emg", seed=5, duration=0.2)
    assert isinstance(src, SyntheticSource)
    assert len(drain(src)) > 0
    a = stack(drain(open_source("synthetic:emg", seed=5, duration=0.2)))
    b = stack(drain(open_source("synthetic:emg", seed=6, duration=0.2)))
    assert not np.array_equal(a, b)


def test_open_source_file_spec(tmp_path: Path):
    write_npz(tmp_path / "r.npz", make_blocks(1))
    src = open_source(f"file:{tmp_path / 'r.npz'}")
    assert isinstance(src, FileReplaySource)
    assert src.n_samples == 50


def test_open_source_file_path_may_contain_colons(tmp_path: Path):
    d = tmp_path / "a:b"
    try:
        d.mkdir()
    except OSError:
        pytest.skip("filesystem rejects ':' in names")
    write_npz(d / "r.npz", make_blocks(1))
    assert isinstance(open_source(f"file:{d / 'r.npz'}"), FileReplaySource)


def test_open_source_file_missing_raises_filenotfound(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        open_source(f"file:{tmp_path / 'missing.csv'}")


@pytest.mark.parametrize(
    ("spec", "board_id", "port"),
    [
        ("brainflow:-1", -1, ""),
        ("brainflow:0", 0, ""),
        ("brainflow:0:/dev/ttyUSB0", 0, "/dev/ttyUSB0"),
        (" BrainFlow : 38 : COM3 ", 38, "COM3"),
    ],
)
def test_open_source_brainflow_specs_parse_without_opening_hardware(spec, board_id, port):
    src = open_source(spec)
    assert isinstance(src, BrainFlowBlockSource)
    assert src._board_id == board_id
    assert src._serial_port == port
    assert src.available is False                        # constructed, never started
    assert src._board is None


def test_open_source_brainflow_forwards_keyword_arguments():
    board = FakeBoard()
    src = open_source("brainflow:0", board_factory=lambda: board, uv_scale=2.0)
    src.start()
    board.push(3)
    block = src.read()
    assert block is not None
    assert np.array_equal(block.data[:, 0], np.array([10.0, 20.0]) * 2.0)


@pytest.mark.parametrize(
    "spec",
    [
        "", "   ", "nope", "nope:thing", "serial:/dev/ttyUSB0",
        "synthetic:bogus", "file", "file:", "file:   ",
        "brainflow", "brainflow:", "brainflow:abc", "brainflow:1.5",
    ],
)
def test_open_source_rejects_unknown_or_malformed_specs(spec: str):
    with pytest.raises(ValueError):
        open_source(spec)


def test_open_source_error_lists_the_valid_forms():
    with pytest.raises(ValueError) as exc:
        open_source("bogus:1")
    message = str(exc.value)
    for form in ("synthetic", "file:", "brainflow:"):
        assert form in message


def test_synthetic_board_id_constant():
    assert SYNTHETIC_BOARD_ID == -1


@posix_only
def test_recording_never_touches_the_real_home(tmp_path: Path):
    """A tap with a tmp_path target creates nothing outside it (sanity for the suite)."""
    before = set(os.listdir(tmp_path))
    drain(RecordingTap(SyntheticSource("emg", duration=0.1), tmp_path / "x.csv"))
    assert set(os.listdir(tmp_path)) - before == {"x.csv"}
