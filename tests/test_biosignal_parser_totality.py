"""Totality of the biosignal wire-format parsers under hostile input.

Every byte stream here comes from a device or a file this project does not control, so
each parser must (a) raise only its documented exception types, (b) never allocate from an
attacker-controlled length field, (c) resynchronise after garbage and still decode the
next valid frame, and (d) decode the same result however the stream is chunked.

Inputs are generated from a fixed seed, so a failure reproduces exactly. Nothing here
opens a socket, a serial port or a Bluetooth link: the Myo source is driven through its
notification callback with an injected clock and no client.
"""

from __future__ import annotations

import io
import random
import sys
import tracemalloc
import types
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from yazses.biosignal import bitalino as bit
from yazses.biosignal.edf import _parse_tals, load_edf, read_edf_header
from yazses.biosignal.myo import (
    MyoSource,
    decode_emg_notification,
    parse_myo_spec,
    set_mode_command,
)
from yazses.biosignal.sources import FileReplaySource
from yazses.biosignal.thinkgear import ThinkGearParser, parse_thinkgear_spec, thinkgear_checksum
from yazses.biosignal.xdf import load_xdf

# A parser that loops forever must fail this file, not stall the suite.
pytestmark = pytest.mark.timeout(120)

SEED = 20261103
ITERATIONS = 150          # mutants per family: enough to hit every mutation operator
MAX_HEAP_BYTES = 32 << 20  # a 64 KiB hostile input must never cost more than this
LOADER_ERRORS = (ValueError, FileNotFoundError)


def rng(tag: str) -> random.Random:
    """A generator whose stream depends only on ``tag`` (str seeds are stable across runs)."""
    return random.Random(f"{SEED}:{tag}")


def mutate(r: random.Random, data: bytes) -> bytes:
    """One hostile edit: bit flips, a byte overwrite, truncation, insertion, duplication."""
    b = bytearray(data)
    op = r.randrange(6) if b else 5
    if op == 0:
        for _ in range(r.randint(1, 4)):
            b[r.randrange(len(b))] ^= 1 << r.randrange(8)
    elif op == 1:
        b[r.randrange(len(b))] = r.randrange(256)
    elif op == 2:
        del b[r.randrange(len(b) + 1):]
    elif op == 3:
        at = r.randrange(len(b) + 1)
        b[at:at] = bytes(r.randrange(256) for _ in range(r.randint(1, 40)))
    elif op == 4:
        i = r.randrange(len(b))
        j = r.randrange(i, len(b) + 1)
        b[i:i] = b[i:j]
    else:
        return bytes(r.randrange(256) for _ in range(r.randint(0, 64)))
    return bytes(b)


def cut_points(r: random.Random, n: int) -> list[int]:
    """Random chunk boundaries over ``n`` bytes (may be empty; always sorted, unique)."""
    return sorted({r.randrange(n + 1) for _ in range(r.randint(0, 12))} if n else set())


def chunks(data: bytes, cuts: list[int]) -> Iterator[bytes]:
    prev = 0
    for c in [*cuts, len(data)]:
        yield data[prev:c]
        prev = c


# ====================================================================================
# ThinkGear: 0xAA 0xAA [PLENGTH] payload CHKSUM
# ====================================================================================


def tg_packet(payload: bytes, *, plength: int | None = None, checksum: int | None = None) -> bytes:
    length = len(payload) if plength is None else plength
    check = thinkgear_checksum(payload) if checksum is None else checksum
    return b"\xaa\xaa" + bytes([length]) + payload + bytes([check])


def tg_raw_packet(value: int) -> bytes:
    return tg_packet(bytes([0x80, 0x02]) + value.to_bytes(2, "big", signed=True))


def tg_stream(r: random.Random, n: int) -> tuple[bytes, list[int]]:
    values = [r.randint(-32768, 32767) for _ in range(n)]
    return b"".join(tg_raw_packet(v) for v in values), values


def tg_feed_all(data: bytes, cuts: list[int]) -> tuple[list, Any]:
    parser = ThinkGearParser()
    out: list = []
    for part in chunks(data, cuts):
        out.extend(parser.feed(part))
    return out, parser.stats


def test_thinkgear_mutated_streams_never_raise_and_stay_consistent() -> None:
    r = rng("tg-mutants")
    for _ in range(ITERATIONS):
        stream, _ = tg_stream(r, r.randint(0, 6))
        data = mutate(r, mutate(r, stream))
        out, stats = tg_feed_all(data, cut_points(r, len(data)))
        assert stats.packets == len(out)
        assert stats.skipped_bytes <= len(data)
        assert all(-32768 <= v <= 32767 for p in out for v in p.raw)


def test_thinkgear_random_noise_never_raises() -> None:
    r = rng("tg-noise")
    for _ in range(ITERATIONS):
        noise = bytes(r.randrange(256) for _ in range(r.randint(0, 600)))
        out, stats = tg_feed_all(noise, cut_points(r, len(noise)))
        assert stats.packets == len(out)


def test_thinkgear_extreme_plength_is_bounded_not_buffered() -> None:
    """PLENGTH 171..255 is rejected at once; PLENGTH 169 may wait for at most 172 bytes.

    170 (0xAA) is not a length: it is an extra sync byte, skipped by design.
    """
    parser = ThinkGearParser()
    for plength in range(171, 256):
        assert parser.feed(b"\xaa\xaa" + bytes([plength]) + b"\x00" * 300) == []
    assert parser.stats.bad_length == 85

    parser = ThinkGearParser()
    peak = 0
    stream = b"\xaa\xaa" + bytes([169]) + b"\x00" * 5000
    for i in range(len(stream)):
        parser.feed(stream[i:i + 1])
        peak = max(peak, len(parser._buf))
    assert peak <= 2 + 1 + 169 + 1


def test_thinkgear_zero_length_payload_is_a_valid_empty_packet() -> None:
    out, stats = tg_feed_all(tg_packet(b"") + tg_raw_packet(7), [])
    assert [p.raw for p in out] == [(), (7,)]
    assert stats.bad_checksum == 0
    bad, bad_stats = tg_feed_all(tg_packet(b"", checksum=0x00), [])
    assert bad == [] and bad_stats.bad_checksum == 1


def test_thinkgear_clean_stream_decodes_every_packet() -> None:
    """Non-vacuity guard: the packets these tests mutate really are checksum-valid."""
    stream, values = tg_stream(rng("tg-clean"), 8)
    out, stats = tg_feed_all(stream, [])
    assert [p.raw for p in out] == [(v,) for v in values]
    assert stats.rejected_packets == 0 and stats.skipped_bytes == 0


def test_thinkgear_empty_input_is_a_no_op() -> None:
    parser = ThinkGearParser()
    assert parser.feed(b"") == []
    assert parser.stats.packets == 0 and parser.stats.skipped_bytes == 0


def test_thinkgear_resynchronises_after_garbage() -> None:
    r = rng("tg-resync")
    no_sync = [b for b in range(256) if b != 0xAA]
    for _ in range(ITERATIONS):
        garbage = bytes(r.choice(no_sync) for _ in range(r.randint(0, 200)))
        if r.random() < 0.5:
            garbage += b"\xaa"   # a trailing half of a sync pair must not eat the packet
        value = r.randint(-32768, 32767)
        out, _ = tg_feed_all(garbage + tg_raw_packet(value) + tg_raw_packet(value ^ 1), [])
        assert [p.raw for p in out][-2:] == [(value,), (value ^ 1,)]


def test_thinkgear_split_at_every_boundary_equals_whole_buffer() -> None:
    r = rng("tg-split")
    stream, _ = tg_stream(r, 5)
    corrupt = mutate(r, stream)
    for data in (stream, corrupt, b"\xaa" * 3 + stream):
        whole_out, whole_stats = tg_feed_all(data, [])
        for cut in range(len(data) + 1):
            out, stats = tg_feed_all(data, [cut])
            assert out == whole_out and stats == whole_stats, f"split at {cut}"
        out, stats = tg_feed_all(data, list(range(1, len(data))))
        assert out == whole_out and stats == whole_stats, "byte at a time"


# ====================================================================================
# BITalino: framing by CRC4 and a sequence counter; no length field on the wire
# ====================================================================================


def bit_frame(r: random.Random, n_ch: int, seq: int) -> bytes:
    f = bytearray(r.randrange(256) for _ in range(bit.frame_size(n_ch)))
    f[-1] = (seq & 0x0F) << 4           # the CRC is computed over the frame with its low nibble 0
    f[-1] |= bit.crc4(f)
    return bytes(f)


def bit_stream(r: random.Random, n_ch: int, count: int) -> tuple[bytes, list[bytes]]:
    frames = [bit_frame(r, n_ch, k) for k in range(count)]
    return b"".join(frames), frames


def bit_feed_all(n_ch: int, data: bytes, cuts: list[int]) -> tuple[list, Any]:
    parser = bit.BITalinoParser(n_ch)
    out: list = []
    for part in chunks(data, cuts):
        out.extend(parser.feed(part))
    return out, parser.stats


@pytest.mark.parametrize("n_ch", [1, 2, 3, 4, 5, 6])
def test_bitalino_mutants_never_raise_and_stay_in_range(n_ch: int) -> None:
    r = rng(f"bit-mutants-{n_ch}")
    for _ in range(ITERATIONS):
        stream, _ = bit_stream(r, n_ch, r.randint(0, 6))
        data = mutate(r, stream)
        out, stats = bit_feed_all(n_ch, data, cut_points(r, len(data)))
        assert stats.frames == len(out)
        for f in out:
            assert len(f.analog) == n_ch
            assert all(v < (1 << (10 if pos < 4 else 6)) for pos, v in enumerate(f.analog))
            assert 0 <= f.seq <= 15 and 0 <= f.lost_before <= 15


@pytest.mark.parametrize("n_ch", [1, 3, 6])
def test_bitalino_split_at_every_boundary_equals_whole_buffer(n_ch: int) -> None:
    r = rng(f"bit-split-{n_ch}")
    stream, _ = bit_stream(r, n_ch, 4)
    for data in (stream, b"\x55" + stream, mutate(r, stream)):
        whole_out, whole_stats = bit_feed_all(n_ch, data, [])
        for cut in range(len(data) + 1):
            out, stats = bit_feed_all(n_ch, data, [cut])
            assert out == whole_out and stats == whole_stats, f"split at {cut}"


@pytest.mark.parametrize("n_ch", [1, 3, 6])
def test_bitalino_clean_stream_decodes_every_frame_after_the_lock(n_ch: int) -> None:
    """Non-vacuity guard: the frames these tests build must really pass the CRC."""
    stream, frames = bit_stream(rng(f"bit-clean-{n_ch}"), n_ch, 6)
    out, stats = bit_feed_all(n_ch, stream, [])
    assert [f.analog for f in out] == [bit.decode_frame(f, n_ch).analog for f in frames]
    assert stats.crc_errors == 0 and stats.dropped_frames == 0


@pytest.mark.parametrize("n_ch", [1, 4, 6])
def test_bitalino_resynchronises_after_garbage(n_ch: int) -> None:
    """Two CRC-valid frames with consecutive counters lock the stream; every real frame
    after the garbage must come out, the first included (the lock is confirmed on it)."""
    r = rng(f"bit-resync-{n_ch}")
    for _ in range(ITERATIONS // 3):
        garbage = bytes(r.randrange(256) for _ in range(r.randint(0, 120)))
        stream, frames = bit_stream(r, n_ch, 5)
        out, _ = bit_feed_all(n_ch, garbage + stream, [])
        decoded = [bit.decode_frame(f, n_ch).analog for f in frames]
        assert [f.analog for f in out][-len(decoded):] == decoded, "lost real frames"


def test_bitalino_unlocked_buffer_is_bounded_by_two_frames() -> None:
    r = rng("bit-bounded")
    parser = bit.BITalinoParser(6)
    limit = 2 * bit.frame_size(6)
    for _ in range(ITERATIONS):
        parser.feed(bytes(r.randrange(256) for _ in range(r.randint(1, 97))))
        assert len(parser._buf) < limit


@pytest.mark.parametrize("bad", [0, 7, -1, 2**40])
def test_bitalino_channel_count_rejects_out_of_range(bad: object) -> None:
    with pytest.raises(ValueError):
        bit.frame_size(bad)  # type: ignore[arg-type]


def test_bitalino_decode_frame_rejects_every_wrong_length() -> None:
    r = rng("bit-length")
    for n_ch in range(1, 7):
        good = bit.frame_size(n_ch)
        for size in range(0, good * 2):
            if size == good:
                continue
            with pytest.raises(ValueError):
                bit.decode_frame(bytes(r.randrange(256) for _ in range(size)), n_ch)


# ====================================================================================
# Myo: fixed 16-byte EMG notifications over BLE, and the ``myo:`` address spec
# ====================================================================================


def test_myo_decode_is_total_over_any_length() -> None:
    r = rng("myo-decode")
    for size in range(0, 80):
        payload = bytes(r.randrange(256) for _ in range(size))
        if size == 16:
            assert decode_emg_notification(payload).shape == (8, 2)
        else:
            with pytest.raises(ValueError):
                decode_emg_notification(payload)


def test_myo_notify_callback_never_raises_and_counts_bad_packets() -> None:
    r = rng("myo-notify")
    source = MyoSource("AA:BB:CC:DD:EE:FF", clock=lambda: 0.0)
    bad = 0
    for _ in range(ITERATIONS):
        size = r.choice([0, 1, 15, 16, 16, 17, 64])
        source._on_notify(None, bytes(r.randrange(256) for _ in range(size)))
        bad += size != 16
    assert source.bad_packets == bad
    assert len(source._queue) <= source._capacity


def test_myo_address_spec_is_total() -> None:
    r = rng("myo-spec")
    alphabet = "0123456789ABCDEFabcdefmyo:- ;"
    for _ in range(ITERATIONS * 4):
        text = "".join(r.choice(alphabet) for _ in range(r.randint(0, 30)))
        try:
            parse_myo_spec(text)
        except ValueError:
            pass
    good = "myo:AA:BB:CC:DD:EE:FF"
    for _ in range(ITERATIONS):
        try:
            parse_myo_spec(mutate(r, good.encode()).decode("latin-1"))
        except ValueError:
            pass


def test_myo_mode_command_rejects_unknown_modes_only() -> None:
    for bad in (-1, 4, 999, "bogus", None, 2.5):
        with pytest.raises(ValueError):
            set_mode_command(bad)  # type: ignore[arg-type]


# ====================================================================================
# ThinkGear / BITalino spec strings (pure; no port is opened)
# ====================================================================================


@pytest.mark.parametrize("parser_fn", [parse_thinkgear_spec, parse_myo_spec])
def test_device_spec_parsers_are_total(parser_fn: Callable[[str], object]) -> None:
    r = rng(f"spec-{parser_fn.__name__}")
    alphabet = "thinkgearmyo:/COM0123456789=,ABab -_simulated"
    for _ in range(ITERATIONS * 4):
        text = "".join(r.choice(alphabet) for _ in range(r.randint(0, 40)))
        try:
            parser_fn(text)
        except ValueError:
            pass


# ====================================================================================
# EDF / BDF: fixed header, per-signal header, data records, TAL annotations
# ====================================================================================


def _field(text: str | bytes, width: int) -> bytes:
    raw = text.encode("latin-1") if isinstance(text, str) else text
    return raw[:width].ljust(width, b" ")


def edf_file(
    *, bdf: bool = False, n_records: int = 2, duration: str = "1",
    spr: tuple[int, ...] = (4, 4), labels: tuple[str, ...] = ("EEG Fp1", "EEG Fp2"),
    dmin: str = "-32768", dmax: str = "32767", pmin: str = "-100", pmax: str = "100",
    reserved: str = "EDF+C", r: random.Random | None = None,
) -> bytes:
    ns = len(spr)
    bps = 3 if bdf else 2
    header_bytes = 256 * (ns + 1)
    head = (
        (b"\xffBIOSEMI" if bdf else b"0       ")
        + _field("patient", 80) + _field("recording", 80)
        + _field("01.01.01", 8) + _field("00.00.00", 8)
        + _field(str(header_bytes), 8) + _field(reserved, 44)
        + _field(str(n_records), 8) + _field(duration, 8) + _field(str(ns), 4)
    )
    sig = b""
    for name, width in (("label", 16), ("transducer", 80), ("dim", 8), ("pmin", 8),
                        ("pmax", 8), ("dmin", 8), ("dmax", 8), ("prefilter", 80),
                        ("spr", 8), ("reserved", 32)):
        for i in range(ns):
            value = {
                "label": labels[i], "transducer": "", "dim": "uV", "pmin": pmin,
                "pmax": pmax, "dmin": dmin, "dmax": dmax, "prefilter": "",
                "spr": str(spr[i]), "reserved": "",
            }[name]
            sig += _field(value, width)
    records = bytes((r or random.Random(0)).randrange(256)
                    for _ in range(n_records * sum(spr) * bps)) if n_records > 0 else b""
    return head + sig + records


def _write(tmp: Path, blob: bytes) -> Path:
    path = tmp / "hostile.edf"
    path.write_bytes(blob)
    return path


def _load_or_reject(path: Path) -> None:
    """Load a hostile EDF: it must either succeed with finite output or raise a ValueError."""
    tracemalloc.start()
    try:
        try:
            rec = load_edf(path)
        except LOADER_ERRORS:
            rec = None
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < MAX_HEAP_BYTES, f"loader allocated {peak} bytes for a {path.stat().st_size} B file"
    if rec is not None:
        assert np.isfinite(rec.fs) and rec.fs > 0, f"non-finite rate {rec.fs}"
        assert np.all(np.isfinite(rec.data)), "non-finite samples returned as success"


def test_edf_every_truncation_of_a_valid_file_is_a_clean_rejection(tmp_path: Path) -> None:
    blob = edf_file(r=rng("edf-trunc"))
    for cut in range(len(blob) + 1):
        path = _write(tmp_path, blob[:cut])
        if cut == len(blob):
            assert load_edf(path).data.shape[0] == 2
            continue
        with pytest.raises(LOADER_ERRORS):
            load_edf(path)


_EDF_JUNK = ["", "0", "-1", "1e400", "nan", "inf", "99999999", "-99999999", "1.5",
             "-0", "+", "9" * 8, " " * 8, "\x00\x00", "abc", "1e-300", "2e300"]


def test_edf_hostile_header_fields_never_escape_as_other_exceptions(tmp_path: Path) -> None:
    r = rng("edf-fields")
    spans = [(8, 80), (168, 8), (176, 8), (184, 8), (236, 8), (244, 8), (252, 4),
             (256 + 216, 8), (256 + 224, 8), (256 + 232, 8)]
    for _ in range(ITERATIONS):
        blob = bytearray(edf_file(bdf=r.random() < 0.3, n_records=r.randint(0, 3),
                                  r=r, duration=r.choice(["1", "0", "1e-300", "0.5"])))
        offset, width = r.choice(spans)
        blob[offset:offset + width] = _field(r.choice(_EDF_JUNK), width)
        path = _write(tmp_path, bytes(blob))
        try:
            read_edf_header(path)
        except LOADER_ERRORS:
            pass
        _load_or_reject(path)


def test_edf_random_bytes_after_a_valid_prefix_never_escape(tmp_path: Path) -> None:
    r = rng("edf-bytes")
    base = edf_file(r=r)
    for _ in range(ITERATIONS):
        blob = mutate(r, mutate(r, base))
        path = _write(tmp_path, blob)
        _load_or_reject(path)


def test_edf_lying_record_count_is_rejected_before_any_allocation(tmp_path: Path) -> None:
    blob = bytearray(edf_file(n_records=2))
    blob[236:244] = _field("99999999", 8)
    path = _write(tmp_path, bytes(blob))
    with pytest.raises(ValueError):
        load_edf(path)
    tracemalloc.start()
    try:
        with pytest.raises(ValueError):
            read_edf_header(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < MAX_HEAP_BYTES


def test_edf_empty_and_tiny_files_are_rejected(tmp_path: Path) -> None:
    for blob in (b"", b"0", b"0" * 255, b"\xff" * 300):
        path = _write(tmp_path, blob)
        with pytest.raises(LOADER_ERRORS):
            load_edf(path)


def _tal_bytes(r: random.Random) -> bytes:
    """Random annotation-signal bytes, weighted toward TAL punctuation."""
    alphabet = b"\x00\x14\x14\x15\x15+-0123456789. abc\xff"
    return bytes(r.choice(alphabet) for _ in range(r.randint(0, 96)))


def test_tal_parser_is_total_over_random_annotation_bytes() -> None:
    r = rng("tal")
    for _ in range(ITERATIONS * 4):
        annotations, keeping, bad = _parse_tals(_tal_bytes(r))
        assert bad >= 0
        assert keeping is None or isinstance(keeping, float)
        assert all(isinstance(a.text, str) for a in annotations)


def test_edf_annotation_channel_with_hostile_tal_never_escapes(tmp_path: Path) -> None:
    """Two records of (4 EEG + 16 annotation) int16 words: 40 bytes each, header is 768 B."""
    r = rng("edf-tal")
    labels = ("EEG Fp1", "EDF Annotations")
    header_bytes = 256 * 3
    for _ in range(ITERATIONS // 2):
        base = bytearray(edf_file(labels=labels, spr=(4, 16), n_records=2, r=r))
        for record in range(2):
            ann = header_bytes + record * 40 + 8
            base[ann:ann + 32] = _tal_bytes(r).ljust(32, b"\x00")[:32]
        _load_or_reject(_write(tmp_path, bytes(base)))


# ====================================================================================
# XDF: pyxdf does the file I/O; everything after it is ours and sees hostile dicts
# ====================================================================================


def _xdf_info(**over: Any) -> dict:
    info: dict[str, Any] = {"name": ["OpenBCI"], "type": ["EEG"], "channel_count": ["2"],
                            "nominal_srate": ["250.0"], "channel_format": ["float32"],
                            "desc": [None], "stream_id": 1, "effective_srate": 250.0}
    info.update(over)
    return info


def _hostile_xdf_stream(r: random.Random) -> dict:
    """A stream whose XML-derived metadata and array shapes are hostile but producible."""
    info = _xdf_info(name=[r.choice(_XDF_TEXT)], type=[r.choice(_XDF_TEXT)],
                     channel_count=[r.choice(_XDF_TEXT)],
                     nominal_srate=[r.choice(_XDF_TEXT)],
                     desc=[r.choice(_XDF_DESC)])
    n = r.randint(0, 12)
    width = r.choice([0, 1, 2, 3])
    series = np.zeros((n, width)) if width else np.zeros(n)
    if r.random() < 0.3:
        series[...] = r.choice([float("nan"), float("inf"), 1e308])
    stamps = np.array([r.choice([0.0, 1.0, float("nan"), float("inf"), 1e308])
                       for _ in range(r.randint(0, 12))], dtype=np.float64)
    return {"info": info, "time_series": series, "time_stamps": stamps}


# pyxdf turns the XML header into text (inside one-element lists) and nested dicts, and the
# samples into float arrays; these are the values a hostile file can actually produce.
_XDF_TEXT: list[Any] = ["", "abc", "1e400", "nan", "inf", "-1", "0", "1e-300", " 250 ",
                        "9" * 40, "EEG", "EMG", "microvolts", "mV", "\x00"]
_XDF_DESC: list[Any] = [None, {}, {"channels": None}, {"channels": [{"channel": []}]},
                        {"channels": [{"channel": [{"label": []}]}]},
                        {"channels": [{"channel": [{"label": ["Fp1"], "unit": ["mV"]}]}]},
                        {"channels": [{"channel": [{"label": ["Fp1"], "type": ["EMG"]}]}]}]


@pytest.fixture
def fake_pyxdf(monkeypatch: pytest.MonkeyPatch) -> types.ModuleType:
    mod = types.ModuleType("pyxdf")
    mod.streams = []  # type: ignore[attr-defined]

    def load_xdf_fn(filename: str, *a: Any, **k: Any) -> tuple[list, dict]:
        return mod.streams, {}  # type: ignore[attr-defined]

    mod.load_xdf = load_xdf_fn  # type: ignore[attr-defined]
    mod.resolve_streams = lambda filename: []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyxdf", mod)
    return mod


def test_xdf_hostile_stream_metadata_only_raises_value_error(
        fake_pyxdf: types.ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "s.xdf"
    path.write_bytes(b"XDF:")
    r = rng("xdf")
    for _ in range(ITERATIONS):
        stream = _hostile_xdf_stream(r)
        fake_pyxdf.streams = [stream]  # type: ignore[attr-defined]
        try:
            rec = load_xdf(path)
        except ValueError:
            continue
        assert np.isfinite(rec.fs) and rec.fs > 0, f"non-finite rate {rec.fs}"
        assert np.all(np.isfinite(rec.data)), "non-finite samples returned as success"


def test_xdf_clean_stream_loads_so_the_hostile_cases_are_not_vacuous(
        fake_pyxdf: types.ModuleType, tmp_path: Path) -> None:
    path = tmp_path / "ok.xdf"
    path.write_bytes(b"XDF:")
    fake_pyxdf.streams = [{"info": _xdf_info(), "time_series": np.zeros((20, 2)),  # type: ignore[attr-defined]
                           "time_stamps": np.arange(20, dtype=np.float64) / 250.0}]
    assert load_xdf(path).fs == 250.0


def test_xdf_zero_sample_signal_stream_is_a_clean_result_not_an_index_error(
        fake_pyxdf: types.ModuleType, tmp_path: Path) -> None:
    """A signal stream opened and closed with no samples is a legitimate file."""
    path = tmp_path / "empty.xdf"
    path.write_bytes(b"XDF:")
    fake_pyxdf.streams = [{"info": _xdf_info(), "time_series": [],  # type: ignore[attr-defined]
                           "time_stamps": []}]
    try:
        load_xdf(path)
    except ValueError:
        pass  # a clear rejection is acceptable; an IndexError is not


# ====================================================================================
# Recording files replayed as sources: CSV and NPZ
# ====================================================================================


_CSV_BASE = b"# fs=250\n# t0=3.5\nFp1:eeg,Fp2:emg\n1,2\n3,4\n5,6\n"


def _npz_bytes(**arrays: np.ndarray) -> bytes:
    buf = io.BytesIO()
    np.savez(buf, **arrays)
    return buf.getvalue()


_NPZ_BASE = _npz_bytes(data=np.arange(8, dtype=np.float64).reshape(2, 4),
                       channels=np.array(["Fp1:eeg", "Fp2:emg"]), fs=np.array(250.0))


def _drain(source: FileReplaySource) -> None:
    """Read until EOFError; the loop itself must end within a bounded number of blocks."""
    source.start()
    for _ in range(10_000):
        try:
            block = source.read()
        except EOFError:
            return
        if block is not None:
            assert np.all(np.isfinite(block.data))
    raise AssertionError("replay did not reach end of recording")


def _load_recording_file(path: Path) -> None:
    tracemalloc.start()
    try:
        try:
            source = FileReplaySource(path)
        except LOADER_ERRORS:
            return
        _drain(source)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < MAX_HEAP_BYTES


def test_csv_hostile_bytes_only_raise_value_error(tmp_path: Path) -> None:
    r = rng("csv")
    for _ in range(ITERATIONS):
        path = tmp_path / "rec.csv"
        path.write_bytes(mutate(r, mutate(r, _CSV_BASE)))
        _load_recording_file(path)


@pytest.mark.parametrize("text", ["# fs=1e400\nFp1:eeg\n1\n2\n", "# fs=nan\nFp1:eeg\n1\n",
                                  "# fs=-5\nFp1:eeg\n1\n", "# fs=inf\nFp1:eeg\n1\n"])
def test_csv_non_finite_sample_rate_is_rejected(tmp_path: Path, text: str) -> None:
    path = tmp_path / "rate.csv"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        FileReplaySource(path)


def test_npz_every_truncation_is_a_clean_rejection(tmp_path: Path) -> None:
    for cut in range(len(_NPZ_BASE)):
        path = tmp_path / "cut.npz"
        path.write_bytes(_NPZ_BASE[:cut])
        with pytest.raises(ValueError):
            FileReplaySource(path)


def test_npz_random_mutations_only_raise_value_error(tmp_path: Path) -> None:
    r = rng("npz")
    for _ in range(ITERATIONS):
        path = tmp_path / "rec.npz"
        path.write_bytes(mutate(r, mutate(r, _NPZ_BASE)))
        _load_recording_file(path)


def test_npz_lying_array_header_does_not_allocate_its_claimed_size(tmp_path: Path) -> None:
    """A .npy header claiming 10**9 float64 must fail on the short data, not allocate 8 GB."""
    header = "{'descr': '<f8', 'fortran_order': False, 'shape': (1000000000,), }"
    header = header.ljust(127) + "\n"
    npy = b"\x93NUMPY\x01\x00" + len(header).to_bytes(2, "little") + header.encode("latin-1")
    npy += np.zeros(4, dtype="<f8").tobytes()
    channels = io.BytesIO()
    np.lib.format.write_array(channels, np.array(["Fp1:eeg"]))
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("data.npy", npy)
        z.writestr("channels.npy", channels.getvalue())
    path = tmp_path / "lying.npz"
    path.write_bytes(zbuf.getvalue())
    tracemalloc.start()
    try:
        with pytest.raises(ValueError):
            FileReplaySource(path)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < MAX_HEAP_BYTES
