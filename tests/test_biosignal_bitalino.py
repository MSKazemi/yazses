"""Tests for ``yazses.biosignal.bitalino``: frame codec, CRC-4, parser and serial source.

The oracles are independent of the module under test:

* frames are *encoded* here from the bit layout in PLUX's MCU Block Data Sheet (Fig. 5:
  S, CRC, I1 I2 O1 O2, then the channels top-down, padding at the low end, read as a
  little-endian integer) — the module *decodes* with the byte formulas from PLUX's APIs;
* the CRC is checked against PLUX's ``bitalino.cpp`` nibble table AND a literal copy of
  ``bitalino.py``'s bit loop.

The port is a fake object; neither pyserial nor a board is needed.
"""

from __future__ import annotations

import logging
import sys
from collections import deque

import numpy as np
import pytest

from yazses.biosignal.bitalino import (
    BITALINO_BAUD,
    BITalinoFrame,
    BITalinoParser,
    BITalinoSource,
    adc_to_uv,
    bitalino_from_spec,
    channel_bits,
    crc4,
    decode_frame,
    frame_size,
    parse_bitalino_spec,
    sampling_rate_command,
    start_command,
)
from yazses.biosignal.types import BlockSource, SignalKind

# ---------------------------------------------------------------- independent oracles

_CPP_CRC4_TAB = (0, 3, 6, 5, 12, 15, 10, 9, 11, 8, 13, 14, 7, 4, 1, 2)
_SIZES = {1: 3, 2: 4, 3: 6, 4: 7, 5: 8, 6: 8}       # bitalino.cpp: n + 2 (+1 for 3..5)


def crc_cpp(frame: bytes) -> int:
    """``checkCRC4`` from PLUX's bitalino.cpp (table-driven, nibble at a time)."""
    crc = 0
    for b in frame[:-1]:
        crc = _CPP_CRC4_TAB[crc] ^ (b >> 4)
        crc = _CPP_CRC4_TAB[crc] ^ (b & 0x0F)
    crc = _CPP_CRC4_TAB[crc] ^ (frame[-1] >> 4)
    return _CPP_CRC4_TAB[crc]


def crc_py(frame: bytes) -> int:
    """The bit loop from PLUX's revolution-python-api ``read()``, copied literally."""
    decoded = list(frame)
    decoded[-1] = decoded[-1] & 0xF0
    x = 0
    for i in range(len(decoded)):
        for bit in range(7, -1, -1):
            x = x << 1
            if x & 0x10:
                x = x ^ 0x03
            x = x ^ ((decoded[i] >> bit) & 0x01)
    return x & 0x0F


def encode(seq: int, analog: list[int], digital: tuple[int, int, int, int] = (0, 0, 0, 0),
           *, good_crc: bool = True) -> bytes:
    """Pack a frame from the datasheet's field layout (not from the module's decoder)."""
    n = len(analog)
    size = _SIZES[n]
    widths = [10 if pos < 4 else 6 for pos in range(n)]
    pos = 8 * size
    x = 0
    for value, width in [(seq, 4), (0, 4), *[(d, 1) for d in digital], *zip(analog, widths)]:
        pos -= width
        assert 0 <= value < (1 << width)
        x |= value << pos
    assert pos >= 0                                  # the rest is low-end padding
    frame = bytearray(x.to_bytes(size, "little"))
    crc = crc_cpp(bytes(frame))
    frame[-1] |= crc if good_crc else (crc ^ 0x05)
    return bytes(frame)


def frames_stream(n_ch: int, seqs: list[int], *, seed: int = 0) -> tuple[bytes, list[list[int]]]:
    rng = np.random.default_rng(seed)
    widths = [10 if pos < 4 else 6 for pos in range(n_ch)]
    values = [[int(rng.integers(0, 1 << w)) for w in widths] for _ in seqs]
    return b"".join(encode(s & 0x0F, v) for s, v in zip(seqs, values)), values


class FakeSerial:
    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks: deque[bytes] = deque(chunks or [])
        self.written = bytearray()
        self.closed = False
        self.resets = 0
        self.fail_read = False

    @property
    def in_waiting(self) -> int:
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, size: int) -> bytes:
        if self.fail_read:
            raise OSError("bluetooth link dropped")
        if not self.chunks:
            return b""
        chunk = self.chunks.popleft()
        if len(chunk) > size:
            self.chunks.appendleft(chunk[size:])
            chunk = chunk[:size]
        return chunk

    def write(self, data: bytes) -> int:
        self.written.extend(data)
        return len(data)

    def reset_input_buffer(self) -> None:
        self.resets += 1

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------- commands + layout


def test_frame_sizes_and_bit_widths() -> None:
    assert [frame_size(n) for n in range(1, 7)] == [3, 4, 6, 7, 8, 8]
    assert channel_bits(4) == (10, 10, 10, 10)
    assert channel_bits(5) == (10, 10, 10, 10, 6)
    assert channel_bits(6) == (10, 10, 10, 10, 6, 6)
    for bad in (0, 7):
        with pytest.raises(ValueError):
            frame_size(bad)


def test_sampling_rate_commands_match_the_vendor_bytes() -> None:
    # bitalino.cpp: 0x03, 0x43, 0x83, 0xC3
    assert [sampling_rate_command(f) for f in (1, 10, 100, 1000)] == [0x03, 0x43, 0x83, 0xC3]
    with pytest.raises(ValueError):
        sampling_rate_command(500)


def test_start_commands_match_the_datasheet() -> None:
    assert start_command(range(6)) == 0xFD          # A6..A1 = 111111, then 0 1 (live)
    assert start_command([0]) == 0x05
    assert start_command([5]) == 0x81
    assert start_command([0], simulated=True) == 0x06  # ... 1 0 (simulated)
    with pytest.raises(ValueError):
        start_command([])
    with pytest.raises(ValueError):
        start_command([6])


def test_crc4_agrees_with_both_vendor_implementations() -> None:
    rng = np.random.default_rng(1)
    for n in range(1, 7):
        for _ in range(300):
            frame = bytes(rng.integers(0, 256, frame_size(n), dtype=np.uint8))
            assert crc4(frame) == crc_cpp(frame) == crc_py(frame)


@pytest.mark.parametrize("n_ch", range(1, 7))
def test_decode_round_trips_the_datasheet_layout(n_ch: int) -> None:
    widths = [10 if pos < 4 else 6 for pos in range(n_ch)]
    rng = np.random.default_rng(n_ch)
    cases = [[(1 << w) - 1 for w in widths], [0] * n_ch,
             *[[int(rng.integers(0, 1 << w)) for w in widths] for _ in range(50)]]
    for k, analog in enumerate(cases):
        digital = ((k >> 0) & 1, (k >> 1) & 1, (k >> 2) & 1, (k >> 3) & 1)
        frame = encode(k & 0x0F, analog, digital)
        assert crc4(frame) == frame[-1] & 0x0F
        got = decode_frame(frame, n_ch)
        assert got == BITalinoFrame(seq=k & 0x0F, digital=digital, analog=tuple(analog))


def test_decode_rejects_wrong_length() -> None:
    with pytest.raises(ValueError):
        decode_frame(b"\x00\x00\x00\x00", 1)


def test_transfer_functions_match_the_datasheets() -> None:
    # (ADC / 2**n - 1/2) * 3.3 / G, in µV
    assert adc_to_uv(512, 10, "emg") == pytest.approx(0.0)
    assert adc_to_uv(1023, 10, "emg") == pytest.approx((1023 / 1024 - 0.5) * 3.3 / 1009 * 1e6)
    assert adc_to_uv(0, 10, "emg") == pytest.approx(-1635.28, abs=0.01)   # ±1.64 mV range
    assert adc_to_uv(0, 10, "eeg") == pytest.approx(-39.49, abs=0.01)     # ±39.49 µV range
    assert adc_to_uv(0, 10, "eog") == pytest.approx(-809.62, abs=0.01)    # ±0.81 mV range
    assert adc_to_uv(63, 6, "emg") == pytest.approx((63 / 64 - 0.5) * 3.3 / 1009 * 1e6)
    for refused in ("ecg", "eda", "acc", "banana"):
        with pytest.raises(ValueError):
            adc_to_uv(0, 10, refused)


# ---------------------------------------------------------------- parser


def collect(parser: BITalinoParser, data: bytes, *, step: int | None = None) -> list[BITalinoFrame]:
    if step is None:
        return parser.feed(data)
    out: list[BITalinoFrame] = []
    for i in range(0, len(data), step):
        out.extend(parser.feed(data[i:i + step]))
    return out


@pytest.mark.parametrize("n_ch", range(1, 7))
@pytest.mark.parametrize("step", [None, 1, 5])
def test_clean_stream_any_chunking(n_ch: int, step: int | None) -> None:
    data, values = frames_stream(n_ch, list(range(40)))
    p = BITalinoParser(n_ch)
    got = collect(p, data, step=step)
    assert [list(f.analog) for f in got] == values
    assert [f.seq for f in got] == [s & 0x0F for s in range(40)]   # wraps 15 -> 0
    assert p.stats.dropped_frames == p.stats.crc_errors == p.stats.skipped_bytes == 0


def test_first_frame_needs_a_confirming_second_frame() -> None:
    data, _ = frames_stream(2, [0, 1])
    p = BITalinoParser(2)
    size = frame_size(2)
    assert p.feed(data[:size]) == []                 # one CRC-valid window is not a lock
    assert len(p.feed(data[size:])) == 2


def test_garbage_before_the_first_frame_is_skipped() -> None:
    garbage = b"BITalino_v5.2\n\x00\xff"            # e.g. a stale version reply
    data, values = frames_stream(4, list(range(10)), seed=3)
    p = BITalinoParser(4)
    got = p.feed(garbage + data)
    assert [list(f.analog) for f in got] == values
    assert p.stats.skipped_bytes == len(garbage)
    assert p.stats.dropped_frames == 0


def test_corrupted_crc_drops_that_frame_and_reports_it() -> None:
    data, values = frames_stream(6, list(range(12)), seed=4)
    size = frame_size(6)
    bad = bytearray(data)
    bad[5 * size + 2] ^= 0x10                        # corrupt one bit of frame 5
    p = BITalinoParser(6)
    got = p.feed(bytes(bad))
    assert [list(f.analog) for f in got] == values[:5] + values[6:]
    assert p.stats.crc_errors == 1
    assert p.stats.dropped_frames == 1 and p.stats.seq_gaps == 1
    assert got[5].seq == 6 and got[5].lost_before == 1
    assert all(f.lost_before == 0 for i, f in enumerate(got) if i != 5)


def test_garbage_between_frames_costs_no_samples() -> None:
    data, values = frames_stream(3, list(range(8)), seed=5)
    size = frame_size(3)
    junk = b"\x13\x37\x00"
    spliced = data[:4 * size] + junk + data[4 * size:]
    p = BITalinoParser(3)
    got = collect(p, spliced, step=7)
    assert [list(f.analog) for f in got] == values
    assert p.stats.crc_errors == 1
    assert p.stats.skipped_bytes == len(junk)
    assert p.stats.dropped_frames == 0


def test_sequence_gap_is_counted_not_filled() -> None:
    seqs = [0, 1, 2, 3, 4, 7, 8, 9]                  # frames 5 and 6 never arrived
    data, values = frames_stream(1, seqs, seed=6)
    p = BITalinoParser(1)
    got = p.feed(data)
    assert len(got) == 8                             # nothing fabricated
    assert p.stats.dropped_frames == 2 and p.stats.seq_gaps == 1
    assert got[5].lost_before == 2


def test_sequence_gap_across_the_wrap() -> None:
    data, _ = frames_stream(2, [13, 14, 15, 2, 3])   # 0 and 1 lost across 15 -> 0
    p = BITalinoParser(2)
    got = p.feed(data)
    assert [f.lost_before for f in got] == [0, 0, 0, 2, 0]
    assert p.stats.dropped_frames == 2


def test_reset_forgets_lock_and_history() -> None:
    data, _ = frames_stream(2, [0, 1, 2])
    p = BITalinoParser(2)
    p.feed(data)
    p.reset()
    data2, _ = frames_stream(2, [9, 10])
    got = p.feed(data2)
    assert [f.lost_before for f in got] == [0, 0]    # no bogus gap from the old stream


# ---------------------------------------------------------------- source


def make_source(chunks: list[bytes], **kw: object) -> tuple[BITalinoSource, FakeSerial]:
    fake = FakeSerial(chunks)
    src = BITalinoSource("/dev/rfcomm0", serial_factory=lambda: fake, **kw)  # type: ignore[arg-type]
    return src, fake


def test_source_layout_is_known_before_start_and_sorted_by_input() -> None:
    src, _ = make_source([], channels=("A4", 0), sensors=["eeg", "emg"], fs=100)
    assert isinstance(src, BlockSource)
    assert src.fs == 100.0
    assert [(c.name, c.kind) for c in src.channels] == [("A1", SignalKind.EMG),
                                                        ("A4", SignalKind.EEG)]
    assert src.sensors == ("emg", "eeg")
    assert src.bits == (10, 10)
    assert src.baudrate == BITALINO_BAUD == 115200


def test_start_sends_rate_then_start_command_and_stop_goes_idle() -> None:
    src, fake = make_source([], channels=[0, 3], sensors={"A1": "emg", 3: "eeg"}, fs=1000)
    src.start()
    assert src.available
    assert fake.resets == 1
    assert bytes(fake.written) == bytes([0xC3, (0b001001 << 2) | 0x01])
    src.stop()
    assert bytes(fake.written)[-1] == 0x00 and fake.closed
    assert not src.available


def test_simulated_mode_command() -> None:
    src, fake = make_source([], channels=[1], simulated=True, fs=10)
    src.start()
    assert bytes(fake.written) == bytes([0x43, (0b000010 << 2) | 0x02])


def test_source_converts_to_microvolts_per_sensor() -> None:
    frames = [encode(s, [512, 1023, 0]) for s in range(4)]
    src, _ = make_source([b"".join(frames)], channels=[0, 1, 2],
                         sensors=["emg", "eeg", "eog"], fs=1000)
    src.start()
    block = src.read()
    assert block is not None and block.data.shape == (3, 4)
    np.testing.assert_allclose(block.data[0], 0.0, atol=1e-9)
    np.testing.assert_allclose(block.data[1], (1023 / 1024 - 0.5) * 3.3 / 41782 * 1e6)
    np.testing.assert_allclose(block.data[2], (0 / 1024 - 0.5) * 3.3 / 2038 * 1e6)
    assert block.t0 == 0.0 and block.fs == 1000.0
    assert src.read() is None


def test_six_bit_slot_uses_six_bit_transfer_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="yazses.biosignal.bitalino"):
        src, _ = make_source([b"".join(encode(s, [512] * 4 + [32, 63]) for s in range(3))],
                             channels=range(6), sensors="emg")
    assert src.bits == (10, 10, 10, 10, 6, 6)
    assert "6-bit" in caplog.text and "A5" in caplog.text and "A6" in caplog.text
    src.start()
    block = src.read()
    assert block is not None
    np.testing.assert_allclose(block.data[4], 0.0, atol=1e-9)            # 32/64 = mid-scale
    np.testing.assert_allclose(block.data[5], (63 / 64 - 0.5) * 3.3 / 1009 * 1e6)


def test_gap_splits_blocks_and_moves_the_clock(caplog: pytest.LogCaptureFixture) -> None:
    seqs = [0, 1, 2, 3, 4, 7, 8, 9]
    data, values = frames_stream(1, seqs, seed=8)
    src, _ = make_source([data], channels=[0], sensors="emg", fs=1000)
    src.start()
    with caplog.at_level(logging.WARNING, logger="yazses.biosignal.bitalino"):
        b1 = src.read()
    b2 = src.read()
    assert b1 is not None and b2 is not None
    assert b1.n_samples == 5 and b1.t0 == 0.0
    assert b2.n_samples == 3 and b2.t0 == pytest.approx(7 / 1000)        # 2 frames skipped
    assert b1.n_samples + b2.n_samples == len(values)                   # nothing fabricated
    assert src.dropped_frames == 2
    assert "lost" in caplog.text
    assert src.read() is None


def test_clock_continues_across_reads() -> None:
    data, _ = frames_stream(2, list(range(10)), seed=9)
    size = frame_size(2)
    src, _ = make_source([data[:4 * size + 1], b"", data[4 * size + 1:]], channels=[0, 1],
                         sensors="emg", fs=100)
    src.start()
    b1 = src.read()
    assert src.read() is None
    b2 = src.read()
    assert b1 is not None and b2 is not None
    assert b2.t0 == pytest.approx(b1.n_samples / 100)
    assert b1.n_samples + b2.n_samples == 10


def test_digital_state_is_tracked() -> None:
    src, _ = make_source([encode(0, [1], (1, 0, 0, 1)) + encode(1, [2], (0, 1, 1, 0))])
    src.start()
    assert src.read() is not None
    assert src.digital == (0, 1, 1, 0)


def test_unavailable_port_is_a_logged_no_op() -> None:
    def boom() -> FakeSerial:
        raise OSError("could not open port /dev/rfcomm4")

    src = BITalinoSource("/dev/rfcomm4", serial_factory=boom)
    src.start()
    assert not src.available and "rfcomm4" in src.last_error
    assert src.read() is None
    src.stop()


def test_read_failure_marks_unavailable() -> None:
    src, fake = make_source([])
    src.start()
    fake.fail_read = True
    assert src.read() is None
    assert not src.available and fake.closed
    assert "stopped streaming" in src.last_error


def test_missing_pyserial_names_the_emg_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "serial", None)
    import yazses.system.remedy as remedy

    monkeypatch.setattr(remedy, "install_hint", lambda *a, **k: "")
    src = BITalinoSource("/dev/rfcomm0")
    src.start()
    assert not src.available
    assert "emg" in src.last_error
    assert src.read() is None


@pytest.mark.parametrize("kw", [
    {"fs": 500},
    {"channels": []},
    {"channels": [0, "A1"]},
    {"channels": ["B1"]},
    {"channels": [6]},
    {"channels": [True]},
    {"sensors": "ecg"},
    {"channels": [0, 1], "sensors": ["emg"]},
    {"channels": [0, 1], "sensors": {"A1": "emg"}},
    {"names": ["only-one"], "channels": [0, 1]},
    {"read_chunk": 0},
])
def test_constructor_validation(kw: dict) -> None:
    with pytest.raises(ValueError):
        BITalinoSource("x", **kw)


def test_custom_names_follow_ascending_order() -> None:
    src = BITalinoSource("x", channels=[3, 0], sensors="emg", names=["forearm", "jaw"])
    assert [c.name for c in src.channels] == ["forearm", "jaw"]


# ---------------------------------------------------------------- spec


@pytest.mark.parametrize(("spec", "expected"), [
    ("bitalino:/dev/rfcomm0", {"port": "/dev/rfcomm0"}),
    ("COM5", {"port": "COM5"}),
    ("bitalino:/dev/tty.BITalino-12-34-DevB:A2=eog",
     {"port": "/dev/tty.BITalino-12-34-DevB", "channels": ("A2",), "sensors": {"A2": "eog"}}),
    ("bitalino:COM5:A1=EMG,a4=eeg,fs=100,simulated,baud=115200",
     {"port": "COM5", "channels": ("A1", "A4"), "sensors": {"A1": "emg", "A4": "eeg"},
      "fs": 100, "simulated": True, "baudrate": 115200}),
    ("bitalino:/dev/ttyUSB0:simulated", {"port": "/dev/ttyUSB0", "simulated": True}),
])
def test_parse_bitalino_spec(spec: str, expected: dict) -> None:
    assert parse_bitalino_spec(spec) == expected


@pytest.mark.parametrize("spec", [
    "bitalino:",
    "bitalino::fs=100",
    "bitalino:COM5:fs=500",
    "bitalino:COM5:fs=fast",
    "bitalino:COM5:A1=ecg",
    "bitalino:COM5:A1=",
    "bitalino:COM5:A7=emg",
    "bitalino:COM5:baud=x",
])
def test_parse_bitalino_spec_rejects(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_bitalino_spec(spec)


def test_bitalino_from_spec_builds_an_unstarted_source() -> None:
    src = bitalino_from_spec("bitalino:COM5:A3=eeg,A1=emg,fs=10", serial_factory=FakeSerial)
    assert isinstance(src, BITalinoSource)
    assert src.port == "COM5" and src.fs == 10.0
    assert [(c.name, c.kind) for c in src.channels] == [("A1", SignalKind.EMG),
                                                        ("A3", SignalKind.EEG)]
    assert not src.available
