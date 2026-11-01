"""Tests for ``yazses.biosignal.thinkgear``: the NeuroSky ThinkGear parser and serial source.

Byte fixtures are built by hand from NeuroSky's "ThinkGear Communications Protocol"; the
port is a fake object, so neither pyserial nor a headset is needed.
"""

from __future__ import annotations

import dataclasses
import logging
import sys
from collections import deque

import numpy as np
import pytest

from yazses.biosignal.thinkgear import (
    THINKGEAR_BAUD,
    THINKGEAR_FS,
    THINKGEAR_RAW_TO_UV,
    ThinkGearPacket,
    ThinkGearParser,
    ThinkGearSource,
    import_serial,
    parse_thinkgear_spec,
    thinkgear_checksum,
    thinkgear_from_spec,
)
from yazses.biosignal.types import BlockSource, SignalKind

# The worked example in NeuroSky's protocol document: POOR_SIGNAL 0x20, BATTERY 0x7E,
# ATTENTION 0x12, MEDITATION 0x60, checksum 0xE3.
DOC_EXAMPLE = bytes.fromhex("AAAA08022001 7E04120560E3".replace(" ", ""))


def packet(payload: bytes) -> bytes:
    """A well-formed packet around ``payload`` (independent checksum: ~sum & 0xFF)."""
    chk = (~sum(payload)) & 0xFF
    return b"\xaa\xaa" + bytes([len(payload)]) + payload + bytes([chk])


def raw_row(value: int) -> bytes:
    return b"\x80\x02" + int(value).to_bytes(2, "big", signed=True)


def raw_packet(value: int) -> bytes:
    return packet(raw_row(value))


class FakeSerial:
    """Hands out queued chunks; records writes and close."""

    def __init__(self, chunks: list[bytes] | None = None) -> None:
        self.chunks: deque[bytes] = deque(chunks or [])
        self.closed = False
        self.fail_read = False

    @property
    def in_waiting(self) -> int:
        return len(self.chunks[0]) if self.chunks else 0

    def read(self, size: int) -> bytes:
        if self.fail_read:
            raise OSError("device disconnected")
        if not self.chunks:
            return b""
        chunk = self.chunks.popleft()
        if len(chunk) > size:
            self.chunks.appendleft(chunk[size:])
            chunk = chunk[:size]
        return chunk

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------- checksum + rows


def test_checksum_matches_the_protocol_documents_example() -> None:
    payload = DOC_EXAMPLE[3:-1]
    assert thinkgear_checksum(payload) == 0xE3 == DOC_EXAMPLE[-1]


def test_doc_example_yields_poor_signal_and_no_vendor_scores() -> None:
    parser = ThinkGearParser()
    out = parser.feed(DOC_EXAMPLE)
    assert out == [ThinkGearPacket(raw=(), poor_signal=0x20)]
    assert parser.stats.packets == 1
    assert parser.stats.rejected_packets == 0


def test_esense_attention_meditation_are_never_exposed() -> None:
    # ATTENTION 0x04 = 90, MEDITATION 0x05 = 80, plus an undocumented 0x16 row
    out = ThinkGearParser().feed(packet(b"\x04\x5a\x05\x50\x16\x40" + raw_row(7)))
    assert out == [ThinkGearPacket(raw=(7,), poor_signal=None)]
    assert [f.name for f in dataclasses.fields(out[0])] == ["raw", "poor_signal"]


@pytest.mark.parametrize(("hi_lo", "expected"), [
    (b"\x00\x00", 0),
    (b"\x00\x01", 1),
    (b"\xff\xfe", -2),
    (b"\x7f\xff", 32767),
    (b"\x80\x00", -32768),
    (b"\x07\xff", 2047),
    (b"\xf8\x00", -2048),
])
def test_raw_value_is_big_endian_twos_complement(hi_lo: bytes, expected: int) -> None:
    out = ThinkGearParser().feed(packet(b"\x80\x02" + hi_lo))
    assert out[0].raw == (expected,)


def test_multiple_raw_rows_in_one_packet_keep_their_order() -> None:
    out = ThinkGearParser().feed(packet(raw_row(1) + raw_row(-1) + b"\x02\x00" + raw_row(300)))
    assert out == [ThinkGearPacket(raw=(1, -1, 300), poor_signal=0)]


def test_extended_code_rows_are_skipped_not_misread_as_raw() -> None:
    # EXCODE 0x55 then CODE 0x80: an extended-level code, NOT the level-0 raw value
    out = ThinkGearParser().feed(packet(b"\x55\x80\x02\x12\x34" + raw_row(5)))
    assert out[0].raw == (5,)


def test_unknown_multibyte_code_is_skipped_by_its_vlength() -> None:
    # 0x83 ASIC_EEG_POWER: 24 bytes whose content includes 0x80 0x02 lookalikes
    filler = b"\x80\x02\x00\x09" * 6
    out = ThinkGearParser().feed(packet(b"\x83\x18" + filler + raw_row(42)))
    assert out[0].raw == (42,)


# ---------------------------------------------------------------- resync + rejection


def stream(values: list[int]) -> bytes:
    return b"".join(raw_packet(v) for v in values)


def test_byte_at_a_time_equals_one_shot() -> None:
    data = stream(list(range(-20, 20))) + DOC_EXAMPLE
    one = ThinkGearParser().feed(data)
    p = ThinkGearParser()
    many: list[ThinkGearPacket] = []
    for b in data:
        many.extend(p.feed(bytes([b])))
    assert many == one
    assert sum(len(x.raw) for x in many) == 40
    assert p.stats.skipped_bytes == 0


def test_split_at_every_boundary_position() -> None:
    data = stream([1, 2, 3])
    for cut in range(len(data) + 1):
        p = ThinkGearParser()
        got = p.feed(data[:cut]) + p.feed(data[cut:])
        assert [v for pk in got for v in pk.raw] == [1, 2, 3], cut


def test_garbage_between_packets_is_skipped_and_counted() -> None:
    garbage = b"\x00\x55\xaa\x13\x80\x02"          # includes a lone SYNC byte
    data = garbage + raw_packet(10) + garbage + raw_packet(20) + b"\xaa"
    p = ThinkGearParser()
    got = p.feed(data)
    assert [v for pk in got for v in pk.raw] == [10, 20]
    assert p.stats.skipped_bytes == 2 * len(garbage)
    assert p.stats.rejected_packets == 0


def test_corrupted_checksum_is_rejected_and_counted() -> None:
    bad = bytearray(raw_packet(99))
    bad[-1] ^= 0x01
    p = ThinkGearParser()
    got = p.feed(raw_packet(1) + bytes(bad) + raw_packet(2))
    assert [v for pk in got for v in pk.raw] == [1, 2]
    assert p.stats.bad_checksum == 1


def test_corrupted_payload_byte_is_rejected() -> None:
    bad = bytearray(raw_packet(99))
    bad[5] ^= 0x40                                   # a value byte, checksum now wrong
    p = ThinkGearParser()
    got = p.feed(bytes(bad) + raw_packet(3))
    assert [v for pk in got for v in pk.raw] == [3]
    assert p.stats.bad_checksum == 1


def test_plength_above_169_is_an_error() -> None:
    p = ThinkGearParser()
    got = p.feed(b"\xaa\xaa\xaa\xb0" + b"\x00" * 5 + raw_packet(4))
    # 0xAA after the sync pair is skipped ("repeat step 3"), then 0xB0 = 176 > 169
    assert [v for pk in got for v in pk.raw] == [4]
    assert p.stats.bad_length == 1


def test_extra_sync_bytes_before_plength_are_tolerated() -> None:
    got = ThinkGearParser().feed(b"\xaa" + raw_packet(8))   # AA AA AA 04 ...
    assert got[0].raw == (8,)


def test_truncated_packet_does_not_swallow_the_next_one() -> None:
    truncated = raw_packet(5)[:5]                    # AA AA 04 80 02 — cut off
    p = ThinkGearParser()
    got = p.feed(truncated + raw_packet(6))
    assert [v for pk in got for v in pk.raw] == [6]
    assert p.stats.bad_checksum == 1


def test_checksum_valid_but_overrunning_row_is_malformed() -> None:
    p = ThinkGearParser()
    got = p.feed(packet(b"\x80\x05\x01") + raw_packet(1))
    assert [v for pk in got for v in pk.raw] == [1]
    assert p.stats.malformed == 1


def test_incomplete_packet_waits_for_more_bytes() -> None:
    p = ThinkGearParser()
    data = raw_packet(77)
    assert p.feed(data[:-1]) == []
    assert p.feed(data[-1:])[0].raw == (77,)


# ---------------------------------------------------------------- source


def test_source_satisfies_blocksource_and_knows_layout_before_start() -> None:
    src = ThinkGearSource("/dev/null", serial_factory=FakeSerial)
    assert isinstance(src, BlockSource)
    assert src.fs == THINKGEAR_FS == 512.0
    assert len(src.channels) == 1
    assert src.channels[0].name == "Fp1" and src.channels[0].kind is SignalKind.EEG
    assert src.baudrate == THINKGEAR_BAUD == 57600


def test_raw_to_microvolt_constant_is_neurosky_formula() -> None:
    # raw * (1.8 / 4096) / 2000 volts
    assert THINKGEAR_RAW_TO_UV == pytest.approx(0.2197265625)
    assert 1000 * THINKGEAR_RAW_TO_UV == pytest.approx(1000 * 1.8 / 4096 / 2000 * 1e6)


def test_source_reads_blocks_in_microvolts_with_a_continuous_clock() -> None:
    first = stream([1000, -1000, 0])
    second = stream([10]) + packet(b"\x02\xc8")      # POOR_SIGNAL 200: no skin contact
    fake = FakeSerial([first, b"", second])
    src = ThinkGearSource("COM7", serial_factory=lambda: fake)
    src.start()
    assert src.available
    b1 = src.read()
    assert b1 is not None and b1.data.shape == (1, 3)
    np.testing.assert_allclose(b1.data[0], np.array([1000, -1000, 0]) * THINKGEAR_RAW_TO_UV)
    assert b1.t0 == 0.0 and b1.fs == 512.0
    assert src.poor_signal is None
    assert src.read() is None                        # nothing on the wire this time
    b2 = src.read()
    assert b2 is not None and b2.n_samples == 1
    assert b2.t0 == pytest.approx(3 / 512.0)
    assert src.poor_signal == 200
    src.stop()
    assert fake.closed and not src.available


def test_source_counts_lost_packets_and_does_not_fabricate(caplog: pytest.LogCaptureFixture) -> None:
    bad = bytearray(raw_packet(500))
    bad[-1] ^= 0xFF
    fake = FakeSerial([raw_packet(1) + bytes(bad) + raw_packet(2)])
    src = ThinkGearSource("x", serial_factory=lambda: fake)
    src.start()
    with caplog.at_level(logging.WARNING, logger="yazses.biosignal.thinkgear"):
        block = src.read()
    assert block is not None and block.n_samples == 2      # no sample for the bad packet
    assert src.lost_packets == 1
    assert "rejected" in caplog.text


def test_custom_uv_scale_and_channel_name() -> None:
    fake = FakeSerial([stream([4])])
    src = ThinkGearSource("x", serial_factory=lambda: fake, uv_scale=0.25, channel_name="FP1x")
    src.start()
    block = src.read()
    assert block is not None and block.data[0, 0] == 1.0
    assert block.channels[0].name == "FP1x"


def test_unavailable_port_is_a_logged_no_op() -> None:
    def boom() -> FakeSerial:
        raise OSError("could not open port /dev/rfcomm9")

    src = ThinkGearSource("/dev/rfcomm9", serial_factory=boom)
    src.start()
    assert not src.available
    assert "rfcomm9" in src.last_error
    assert src.read() is None
    src.stop()


def test_read_failure_marks_unavailable_and_closes() -> None:
    fake = FakeSerial([stream([1])])
    src = ThinkGearSource("x", serial_factory=lambda: fake)
    src.start()
    fake.fail_read = True
    assert src.read() is None
    assert not src.available and fake.closed
    assert "stopped streaming" in src.last_error


def test_missing_pyserial_raises_importerror_naming_the_emg_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, "serial", None)
    import yazses.system.remedy as remedy

    monkeypatch.setattr(remedy, "install_hint", lambda *a, **k: "")
    with pytest.raises(ImportError, match="emg"):
        import_serial()
    src = ThinkGearSource("/dev/rfcomm0")
    src.start()                                      # no raise: a logged no-op
    assert not src.available
    assert "emg" in src.last_error
    assert src.read() is None


def test_constructor_validation() -> None:
    with pytest.raises(ValueError):
        ThinkGearSource("x", channel_name="  ")
    with pytest.raises(ValueError):
        ThinkGearSource("x", read_chunk=0)


# ---------------------------------------------------------------- spec


@pytest.mark.parametrize(("spec", "expected"), [
    ("thinkgear:/dev/rfcomm0", {"port": "/dev/rfcomm0"}),
    ("/dev/rfcomm0", {"port": "/dev/rfcomm0"}),
    ("thinkgear:COM5", {"port": "COM5"}),
    ("thinkgear:/dev/tty.MindWaveMobile-SerialPo", {"port": "/dev/tty.MindWaveMobile-SerialPo"}),
    ("thinkgear:COM5:baud=9600,name=Fp1L",
     {"port": "COM5", "baudrate": 9600, "channel_name": "Fp1L"}),
])
def test_parse_thinkgear_spec(spec: str, expected: dict) -> None:
    assert parse_thinkgear_spec(spec) == expected


@pytest.mark.parametrize("spec", [
    "thinkgear:",
    "thinkgear::baud=9600",
    "thinkgear:COM5:baud=fast",
    "thinkgear:COM5:name=",
    "thinkgear:COM5:color=blue",
    "thinkgear:COM5:simulated",
])
def test_parse_thinkgear_spec_rejects(spec: str) -> None:
    with pytest.raises(ValueError):
        parse_thinkgear_spec(spec)


def test_thinkgear_from_spec_builds_an_unstarted_source() -> None:
    src = thinkgear_from_spec("thinkgear:COM3:baud=115200", serial_factory=FakeSerial)
    assert isinstance(src, ThinkGearSource)
    assert src.port == "COM3" and src.baudrate == 115200
    assert not src.available
