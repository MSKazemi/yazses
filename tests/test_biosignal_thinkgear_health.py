"""ThinkGear source health: the fail-closed contact/transport state (ADR-v2-155, #828).

Every case here is a fake serial port fed hand-built bytes and a fake monotonic clock, so
no headset, pyserial or wall-clock sleeping is involved. The cases follow the TG matrix of
``design/specs/thinkgear-hardware-qualification.md`` (TG-01..TG-11, G1). The thresholds
are the ones the maintainer froze at G0 (#827): any nonzero POOR_SIGNAL is unhealthy, a
report older than 3.0 s closes the gate, and rearming needs two separate zero reports plus
1.0 s (512 samples) of contiguous clean raw data, with the completing batch still vetoed.

The trace bytes are built from the protocol document's framing (``packet`` / ``raw_row``
in ``test_biosignal_thinkgear``), never from the production parser, so a parser regression
cannot hide behind its own fixture.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import math

import numpy as np
import pytest

from tests.test_biosignal_thinkgear import FakeSerial, packet, raw_row
from yazses.biosignal import thinkgear_health as th
from yazses.biosignal.thinkgear import (
    THINKGEAR_FS,
    THINKGEAR_RAW_TO_UV,
    ThinkGearPacket,
    ThinkGearParser,
    ThinkGearSource,
)
from yazses.biosignal.thinkgear_health import (
    CONTACT_TTL_S,
    REARM_CLEAN_SAMPLE_S,
    REARM_GOOD_REPORTS,
    BatchHealth,
    HealthReason,
    HealthState,
    PacketReport,
    ThinkGearHealth,
)

REARM_SAMPLES = 512


# ---------------------------------------------------------------- wire + clock helpers


def raw_packets(n: int, value: int = 0) -> bytes:
    """``n`` single-sample raw packets (the TGAM's 512 Hz stream shape)."""
    return packet(raw_row(value)) * n


def quality(value: int) -> bytes:
    """A POOR_SIGNAL (0x02) report packet with no raw rows (the 1 Hz "big packet" shape)."""
    return packet(bytes([0x02, value]))


def bad_checksum_raw(value: int = 9) -> bytes:
    bad = bytearray(packet(raw_row(value)))
    bad[-1] ^= 0x01
    return bytes(bad)


class FakeClock:
    """Monotonic clock under the test's control."""

    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def make_source(chunks: list[bytes] | None = None, clock: FakeClock | None = None,
                ) -> tuple[ThinkGearSource, FakeSerial, FakeClock]:
    fake = FakeSerial(list(chunks or []))
    clk = clock or FakeClock()
    src = ThinkGearSource("/dev/fake-tg", serial_factory=lambda: fake, clock=clk)
    src.start()
    assert src.available
    return src, fake, clk


def feed(src: ThinkGearSource, fake: FakeSerial, clk: FakeClock, chunk: bytes,
         *, dt: float = 0.1):
    """Advance the clock by ``dt``, put one chunk on the wire, read it as one batch."""
    clk.t += dt
    fake.chunks.append(chunk)
    block = src.read()
    return block, src.last_health


def rearm(src: ThinkGearSource, fake: FakeSerial, clk: FakeClock) -> None:
    """Drive a fresh source to READY: two separate zero reports and 512 clean samples,
    then the completing batch (still vetoed); the *next* clean batch is admissible."""
    feed(src, fake, clk, quality(0) + raw_packets(256))                 # REARMING
    _, h = feed(src, fake, clk, quality(0) + raw_packets(256))          # completes
    assert h is not None and h.state is HealthState.READY and not h.trusted


# ---------------------------------------------------------------- the pure module


def test_health_module_is_stdlib_only_and_never_touches_a_transport() -> None:
    """Spec §3: the state machine must not import serial, brainflow, pylsl, Qt or OS
    modules (nor numpy): it is the part that has to be provably correct."""
    tree = ast.parse(inspect.getsource(th))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "dataclasses", "enum", "math", "collections", "typing"}


def test_the_g0_thresholds_are_the_frozen_ones() -> None:
    """#827 G0: changing these needs a reviewed follow-up with measured evidence."""
    assert CONTACT_TTL_S == 3.0
    assert REARM_GOOD_REPORTS == 2
    assert REARM_CLEAN_SAMPLE_S == 1.0
    assert th.THINKGEAR_FS == THINKGEAR_FS == 512.0
    assert ThinkGearHealth().rearm_samples == REARM_SAMPLES


def test_the_transport_stall_threshold_is_the_stream_guards_own() -> None:
    from yazses.biosignal.integrity import STALL_S

    assert th.TRANSPORT_STALL_S == STALL_S


def test_batch_health_carries_no_signal_address_or_timestamps() -> None:
    names = {f.name for f in dataclasses.fields(BatchHealth)}
    assert names == {
        "session", "epoch", "trusted", "state", "reason", "raw_samples",
        "nonzero_quality_reports", "zero_quality_reports", "rejected_packet_delta",
        "skipped_byte_delta", "last_poor_signal", "consecutive_good_reports",
        "continuous_good_samples", "sample_gap_unknown",
    }
    h = ThinkGearHealth().observe_batch(1.0, (PacketReport(1, 0),), 0, 0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.trusted = True  # type: ignore[misc]
    assert set(h.as_dict()) == names


# ---------------------------------------------------------------- TG-01


def test_tg01_valid_packet_scaling_and_payload_unchanged_no_vendor_scores() -> None:
    # ATTENTION 0x04 / MEDITATION 0x05 / undocumented 0x16 ride along and stay invisible
    wire = packet(b"\x02\x00\x04\x5a\x05\x50\x16\x40" + raw_row(-2048) + raw_row(2047))
    assert ThinkGearParser().feed(wire) == [ThinkGearPacket(raw=(-2048, 2047), poor_signal=0)]
    src, fake, clk = make_source()
    block, health = feed(src, fake, clk, wire)
    assert block is not None
    np.testing.assert_allclose(block.data[0], np.array([-2048, 2047]) * THINKGEAR_RAW_TO_UV)
    assert block.t0 == 0.0 and block.fs == 512.0
    assert health is not None and src.health_for(block) is health
    assert "attention" not in repr(health).lower() and "meditation" not in repr(health).lower()


def test_tg01_several_poor_signal_rows_in_one_packet_report_the_worst() -> None:
    """A packet that says 200 then 0 must not read as clean (a final good value never
    rescues an earlier bad one, even inside one packet)."""
    out = ThinkGearParser().feed(packet(b"\x02\xc8\x02\x00" + raw_row(1)))
    assert out == [ThinkGearPacket(raw=(1,), poor_signal=200)]


# ---------------------------------------------------------------- TG-02


def test_tg02_raw_before_any_quality_report_is_never_trusted() -> None:
    src, fake, clk = make_source()
    for _ in range(10):
        block, health = feed(src, fake, clk, raw_packets(64, 500))
        assert block is not None and health is not None
        assert not health.trusted
        assert health.state is HealthState.UNKNOWN
        assert health.reason is HealthReason.UNKNOWN_CONTACT
    # A waveform-clean stream with no 0x02 never qualifies on its own (spec §3).
    assert src.health.state is HealthState.UNKNOWN


def test_tg02_first_zero_report_starts_rearming_not_trust() -> None:
    src, fake, clk = make_source()
    _, health = feed(src, fake, clk, quality(0) + raw_packets(64))
    assert health is not None and not health.trusted
    assert health.state is HealthState.REARMING
    assert health.reason is HealthReason.REARMING


# ---------------------------------------------------------------- TG-03


def test_tg03_zero_200_zero_in_one_read_vetoes_the_whole_batch() -> None:
    src, fake, clk = make_source()
    rearm(src, fake, clk)
    _, ok = feed(src, fake, clk, raw_packets(32))
    assert ok is not None and ok.trusted
    batch = quality(0) + raw_packets(16) + quality(200) + raw_packets(16) + quality(0)
    block, health = feed(src, fake, clk, batch + raw_packets(16))
    assert block is not None and block.n_samples == 48
    assert health is not None and not health.trusted
    assert health.reason is HealthReason.NO_CONTACT
    assert health.nonzero_quality_reports == 1 and health.zero_quality_reports == 2
    assert health.last_poor_signal == 0                 # the final good value...
    assert health.state is HealthState.UNTRUSTED        # ...rescues nothing
    assert health.consecutive_good_reports == 0         # tainted zeros are not rearm evidence
    assert health.continuous_good_samples == 0
    # The next clean batch starts the rearm from scratch: still vetoed.
    _, nxt = feed(src, fake, clk, quality(0) + raw_packets(16))
    assert nxt is not None and not nxt.trusted and nxt.state is HealthState.REARMING
    assert nxt.consecutive_good_reports == 1


# ---------------------------------------------------------------- TG-04


@pytest.mark.parametrize(("value", "reason"), [
    (1, HealthReason.CONTACT_CONTAMINATED),
    (25, HealthReason.CONTACT_CONTAMINATED),
    (199, HealthReason.CONTACT_CONTAMINATED),
    (200, HealthReason.NO_CONTACT),
    (255, HealthReason.CONTACT_CONTAMINATED),
])
def test_tg04_every_nonzero_poor_signal_suppresses_with_its_own_reason(value, reason) -> None:
    src, fake, clk = make_source()
    rearm(src, fake, clk)
    _, health = feed(src, fake, clk, quality(value) + raw_packets(32))
    assert health is not None and not health.trusted
    assert health.reason is reason
    assert health.state is HealthState.UNTRUSTED


def test_tg04_contact_quality_is_distinguished_from_frame_validity() -> None:
    reasons = set()
    for wire in (quality(1), quality(200), bad_checksum_raw()):
        src, fake, clk = make_source()
        rearm(src, fake, clk)
        _, h = feed(src, fake, clk, wire + raw_packets(8))
        assert h is not None and not h.trusted
        reasons.add(h.reason)
    assert reasons == {HealthReason.CONTACT_CONTAMINATED, HealthReason.NO_CONTACT,
                       HealthReason.CORRUPT_PACKET}


# ---------------------------------------------------------------- TG-05


def test_tg05_bad_checksum_beside_valid_raw_vetoes_without_inventing_samples() -> None:
    src, fake, clk = make_source()
    rearm(src, fake, clk)
    _, ok = feed(src, fake, clk, raw_packets(10))
    assert ok is not None and ok.trusted
    t_next = src._emitted / src.fs
    block, health = feed(src, fake, clk, raw_packets(5, 7) + bad_checksum_raw() + raw_packets(5, 7))
    assert block is not None
    assert block.n_samples == 10                       # no sample stands in for the lost one
    assert block.t0 == pytest.approx(t_next)           # and the clock is not moved for it
    np.testing.assert_allclose(block.data[0], 7 * THINKGEAR_RAW_TO_UV)
    assert health is not None and not health.trusted
    assert health.reason is HealthReason.CORRUPT_PACKET
    assert health.rejected_packet_delta == 1
    assert health.sample_gap_unknown is True           # the lost count is unknowable


# ---------------------------------------------------------------- TG-06


@pytest.mark.parametrize("bad", [
    pytest.param(packet(b"\x80\x05\x01"), id="malformed-row"),
    pytest.param(b"\xaa\xaa\xb0" + b"\x00" * 5, id="plength-above-169"),
    pytest.param(b"\x13\x37\x00", id="skipped-framing-bytes"),
])
def test_tg06_malformed_or_resynced_frames_invalidate_and_resync_bounded(bad) -> None:
    src, fake, clk = make_source()
    rearm(src, fake, clk)
    before = src.parser.stats.rejected_packets + src.parser.stats.skipped_bytes
    block, health = feed(src, fake, clk, raw_packets(4, 3) + bad + raw_packets(4, 3))
    after = src.parser.stats.rejected_packets + src.parser.stats.skipped_bytes
    assert after > before                              # the parser counted it
    assert block is not None and block.n_samples == 8  # and resynchronised onto the next
    assert health is not None and not health.trusted
    assert health.reason is HealthReason.CORRUPT_PACKET
    assert health.state is HealthState.UNTRUSTED
    assert health.epoch == 1


# ---------------------------------------------------------------- TG-07


def test_tg07_reports_stop_for_more_than_3s_events_cease() -> None:
    src, fake, clk = make_source()
    rearm(src, fake, clk)
    trusted = []
    for _ in range(25):                                 # 2.5 s of raw, no new report
        _, h = feed(src, fake, clk, raw_packets(51), dt=0.1)
        assert h is not None
        trusted.append(h.trusted)
    assert all(trusted)                                 # fresh until the TTL passes
    _, stale = feed(src, fake, clk, raw_packets(51), dt=0.75)   # 3.25 s since the report
    assert stale is not None and not stale.trusted
    assert stale.reason is HealthReason.CONTACT_STALE
    assert stale.state is HealthState.UNTRUSTED


def test_tg07_exactly_at_the_ttl_is_still_fresh() -> None:
    h = ThinkGearHealth()
    for t in (0.0, 0.5):                                # exact binary fractions
        h.observe_batch(t, (PacketReport(0, 0), PacketReport(256, None)), 0, 0)
    assert h.observe_batch(1.0, (PacketReport(1, None),), 0, 0).trusted
    assert h.observe_batch(0.5 + CONTACT_TTL_S, (PacketReport(1, None),), 0, 0).trusted
    late = h.observe_batch(0.5 + CONTACT_TTL_S + 1e-6, (PacketReport(1, None),), 0, 0)
    assert not late.trusted and late.reason is HealthReason.CONTACT_STALE


def test_tg07_staleness_is_seen_on_an_idle_poll_too() -> None:
    src, fake, clk = make_source()
    rearm(src, fake, clk)
    clk.t += CONTACT_TTL_S + 0.5
    assert src.read() is None                           # nothing on the wire
    assert src.health.state is HealthState.UNTRUSTED
    assert src.health.reason is HealthReason.CONTACT_STALE


def test_tg07_recovery_after_staleness_needs_fresh_reports() -> None:
    src, fake, clk = make_source()
    rearm(src, fake, clk)
    _, stale = feed(src, fake, clk, raw_packets(64), dt=CONTACT_TTL_S + 1.0)
    assert stale is not None and not stale.trusted
    for _ in range(5):                                  # clean raw, no report: stays shut
        _, h = feed(src, fake, clk, raw_packets(128))
        assert h is not None and not h.trusted and h.state is HealthState.UNTRUSTED
    rearm(src, fake, clk)
    _, ok = feed(src, fake, clk, raw_packets(8))
    assert ok is not None and ok.trusted


# ---------------------------------------------------------------- TG-08


def test_tg08_two_good_reports_and_512_samples_vetoes_the_candidate_batch() -> None:
    src, fake, clk = make_source()
    _, a = feed(src, fake, clk, quality(0) + raw_packets(300))
    assert a is not None and a.state is HealthState.REARMING and not a.trusted
    _, b = feed(src, fake, clk, quality(0) + raw_packets(300))
    assert b is not None and b.state is HealthState.READY
    assert not b.trusted and b.reason is HealthReason.REARMING        # candidate: vetoed
    assert b.consecutive_good_reports >= REARM_GOOD_REPORTS
    assert b.continuous_good_samples >= REARM_SAMPLES
    _, c = feed(src, fake, clk, raw_packets(16))
    assert c is not None and c.trusted and c.reason is HealthReason.TRUSTED


def test_tg08_two_reports_in_one_large_batch_still_veto_that_batch() -> None:
    src, fake, clk = make_source()
    _, h = feed(src, fake, clk, quality(0) + raw_packets(600) + quality(0) + raw_packets(10))
    assert h is not None and h.state is HealthState.READY and not h.trusted
    _, nxt = feed(src, fake, clk, raw_packets(4))
    assert nxt is not None and nxt.trusted


def test_tg08_samples_before_the_first_zero_report_do_not_count() -> None:
    """Rule 4: clean samples accumulate only while the latest known quality is zero."""
    src, fake, clk = make_source()
    _, h = feed(src, fake, clk, raw_packets(600) + quality(0) + raw_packets(10))
    assert h is not None and h.continuous_good_samples == 10
    _, h2 = feed(src, fake, clk, quality(0) + raw_packets(100))
    assert h2 is not None and h2.state is HealthState.REARMING     # 110 < 512


def test_tg08_one_report_is_not_enough_however_long_the_clean_run() -> None:
    src, fake, clk = make_source()
    feed(src, fake, clk, quality(0) + raw_packets(100))
    for _ in range(6):
        _, h = feed(src, fake, clk, raw_packets(200), dt=0.4)
        assert h is not None and not h.trusted and h.state is HealthState.REARMING


def test_tg08_a_stall_while_rearming_restarts_the_count() -> None:
    h = ThinkGearHealth()
    h.observe_batch(0.0, (PacketReport(0, 0), PacketReport(300, None)), 0, 0)
    h.observe_idle(0.5)
    h.observe_idle(th.TRANSPORT_STALL_S + 0.01)
    assert h.state is HealthState.UNTRUSTED and h.reason is HealthReason.TRANSPORT_STALLED


# ---------------------------------------------------------------- TG-09


def test_tg09_a_blink_pair_straddling_contact_loss_is_never_in_trusted_batches() -> None:
    """The pipeline-level proof (no DOUBLE_BLINK) is in the gate tests (#829); here, the
    source facts it rests on: every batch from the loss until the next clean batch after a
    full rearm is untrusted, and the loss starts a new fault epoch even when the batch that
    carries it has no raw samples at all."""
    src, fake, clk = make_source()
    rearm(src, fake, clk)
    first, h1 = feed(src, fake, clk, raw_packets(100, 900))         # first blink: trusted
    assert first is not None and h1 is not None and h1.trusted and h1.epoch == 0
    block, loss = feed(src, fake, clk, quality(200))                 # health-only packet
    assert block is None                                             # no block to carry it
    assert loss is not None and loss.epoch == 1 and not loss.trusted
    second, h2 = feed(src, fake, clk, raw_packets(100, 900))         # second blink
    assert second is not None and h2 is not None and not h2.trusted
    assert src.health_for(second) is h2 and h2.epoch == 1


# ---------------------------------------------------------------- TG-10


def test_tg10_huge_garbage_is_bounded_and_never_raises() -> None:
    src, fake, clk = make_source()
    rng = np.random.default_rng(10)
    garbage = bytes(rng.integers(0, 256, size=1 << 20, dtype=np.uint8))
    fake.chunks.append(garbage)
    reads = 0
    while fake.chunks and reads < 1000:
        clk.t += 0.01
        src.read()
        reads += 1
        assert len(src.parser._buf) <= (1 << 16) + 256
    assert not fake.chunks                          # drained in bounded reads, not one
    assert reads > 1
    assert src.health.state is HealthState.UNTRUSTED
    h = src.last_health
    assert h is not None and not h.trusted


def test_tg10_a_bounded_read_size_even_when_the_port_reports_a_flood() -> None:
    sizes: list[int] = []

    class Flood(FakeSerial):
        in_waiting = 50_000_000                                       # type: ignore[assignment]

        def read(self, size: int) -> bytes:
            sizes.append(size)
            return b""

    src = ThinkGearSource("x", serial_factory=Flood, clock=FakeClock())
    src.start()
    src.read()
    assert sizes and max(sizes) <= 1 << 16


def test_tg10_partial_packets_wait_and_unreadable_port_is_a_no_op() -> None:
    src, fake, clk = make_source()
    wire = quality(0) + raw_packets(3)
    block, _ = feed(src, fake, clk, wire[:5])
    assert block is None
    block, _ = feed(src, fake, clk, wire[5:])
    assert block is not None and block.n_samples == 3
    fake.fail_read = True
    clk.t += 0.1
    assert src.read() is None                      # unreadable: logged, never raised
    assert not src.available
    assert src.health.state is HealthState.UNKNOWN
    assert src.health_for(block) is None           # provenance cleared with the transport


def test_tg10_a_clock_that_raises_or_goes_back_fails_closed() -> None:
    h = ThinkGearHealth()
    h.observe_batch(10.0, (PacketReport(0, 0), PacketReport(600, None), PacketReport(0, 0)),
                    0, 0)
    assert h.observe_batch(10.1, (PacketReport(1, None),), 0, 0).trusted
    back = h.observe_batch(9.0, (PacketReport(1, None),), 0, 0)
    assert not back.trusted and back.reason is HealthReason.CLOCK_INVALID
    nan = ThinkGearHealth().observe_batch(math.nan, (PacketReport(0, 0),), 0, 0)
    assert not nan.trusted and nan.reason is HealthReason.CLOCK_INVALID

    def boom() -> float:
        raise RuntimeError("clock")

    fake = FakeSerial([quality(0) + raw_packets(4)])
    src = ThinkGearSource("x", serial_factory=lambda: fake, clock=boom)
    src.start()
    block = src.read()
    assert block is not None
    health = src.health_for(block)
    assert health is not None and not health.trusted
    assert health.reason is HealthReason.CLOCK_INVALID


# ---------------------------------------------------------------- TG-11


def test_tg11_stop_start_cannot_carry_trust_into_a_new_session() -> None:
    fakes = [FakeSerial(), FakeSerial()]
    clk = FakeClock()
    src = ThinkGearSource("x", serial_factory=lambda: fakes.pop(0), clock=clk)
    src.start()
    fake = src._ser
    rearm(src, fake, clk)
    old, ok = feed(src, fake, clk, raw_packets(8))
    assert old is not None and ok is not None and ok.trusted
    session = ok.session
    src.stop()
    assert src.health.state is HealthState.UNKNOWN
    assert src.health_for(old) is None
    src.start()                                    # reconnect: a fresh port
    fake2 = src._ser
    assert fake2 is not fake
    new, h = feed(src, fake2, clk, raw_packets(8))
    assert new is not None and h is not None
    assert not h.trusted and h.state is HealthState.UNKNOWN
    assert h.session == session + 1


def test_tg11_a_second_start_on_an_open_port_is_a_no_op() -> None:
    """``monitor`` starts the source and then the guard starts it again; the second call
    must not throw away a rearm in progress (nor mint a new session)."""
    src, fake, clk = make_source()
    _, h = feed(src, fake, clk, quality(0) + raw_packets(100))
    assert h is not None and h.state is HealthState.REARMING
    src.start()
    assert src.health.state is HealthState.REARMING and src.health.session == h.session


def test_tg11_failed_start_leaves_no_trust() -> None:
    def boom() -> FakeSerial:
        raise OSError("no such port")

    src = ThinkGearSource("x", serial_factory=boom, clock=FakeClock())
    src.start()
    assert not src.available
    assert src.health.state is HealthState.UNKNOWN and src.last_health is None


# ---------------------------------------------------------------- provenance


def test_provenance_is_bounded_and_unknown_blocks_have_none() -> None:
    src, fake, clk = make_source()
    blocks = []
    for _ in range(20):
        b, _ = feed(src, fake, clk, raw_packets(2))
        blocks.append(b)
    assert src.health_for(blocks[-1]) is not None
    assert src.health_for(blocks[0]) is None            # aged out of the bounded map
    stranger = dataclasses.replace(blocks[-1])          # equal content, not the same block
    assert src.health_for(stranger) is None


def test_health_state_table_from_unknown_through_ready() -> None:
    """The spec §3 state table, row by row, on the pure machine."""
    h = ThinkGearHealth()
    assert h.state is HealthState.UNKNOWN and h.session == 1 and h.epoch == 0
    assert h.observe_batch(0.0, (PacketReport(50, None),), 0, 0).state is HealthState.UNKNOWN
    r = h.observe_batch(0.1, (PacketReport(0, 0), PacketReport(50, None)), 0, 0)
    assert r.state is HealthState.REARMING and not r.trusted
    bad = h.observe_batch(0.2, (PacketReport(0, 3),), 0, 0)
    assert bad.state is HealthState.UNTRUSTED and bad.epoch == 1
    again = h.observe_batch(0.3, (PacketReport(0, 3),), 0, 0)
    assert again.epoch == 1                              # a fault epoch continues
    h.observe_batch(0.4, (PacketReport(0, 0), PacketReport(300, None)), 0, 0)
    done = h.observe_batch(0.5, (PacketReport(0, 0), PacketReport(300, None)), 0, 0)
    assert done.state is HealthState.READY and not done.trusted
    assert h.observe_batch(0.6, (PacketReport(10, None),), 0, 0).trusted
    corrupt = h.observe_batch(0.7, (PacketReport(10, None),), 1, 0)
    assert corrupt.state is HealthState.UNTRUSTED and corrupt.epoch == 2
    h.invalidate()
    assert h.state is HealthState.UNKNOWN and h.session == 1
    h.reset()
    assert h.state is HealthState.UNKNOWN and h.session == 2 and h.epoch == 0


def test_negative_or_junk_counts_are_treated_as_faults() -> None:
    h = ThinkGearHealth()
    assert h.observe_batch(0.0, (PacketReport(-1, 0),), 0, 0).reason is HealthReason.CORRUPT_PACKET
    h2 = ThinkGearHealth()
    assert h2.observe_batch(0.0, (PacketReport(1, 0),), -1, 0).reason is HealthReason.CORRUPT_PACKET
