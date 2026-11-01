"""Tests for ``yazses.biosignal.myo``: the Myo armband raw-EMG source over Bluetooth LE.

Offline and deterministic: bleak is replaced by a fake module in ``sys.modules`` (or an
injected client factory), arrival times come from an injected clock, and every byte-level
fixture is built from ``myohw.h`` (https://github.com/thalmiclabs/myo-bluetooth), not from
a capture of a real band. No Bluetooth adapter, band or bleak install is needed.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import types
from pathlib import Path

import numpy as np
import pytest

from yazses.biosignal import myo
from yazses.biosignal.emg_onset import EmgOnsetDetector, OnsetThresholds, bandlimited_rms
from yazses.biosignal.myo import (
    COMMAND_UUID,
    EMG_DATA_UUIDS,
    MYO_EMG_FS,
    MyoSource,
    decode_emg_notification,
    myo_uuid,
    parse_myo_spec,
    set_mode_command,
    sleep_mode_command,
    source_from_spec,
)
from yazses.biosignal.types import BlockSource, EventKind, SignalKind

ADDRESS = "AA:BB:CC:DD:EE:FF"
DT = 1.0 / MYO_EMG_FS


# ------------------------------------------------------------------------------------
# fixtures
# ------------------------------------------------------------------------------------


def payload(sample1: list[int], sample2: list[int]) -> bytes:
    """A ``myohw_emg_data_t``: int8 sample1[8] then int8 sample2[8]."""
    return np.array(sample1 + sample2, dtype=np.int8).tobytes()


class FakeClient:
    """Just enough of ``bleak.BleakClient`` (3.x signatures) to drive ``MyoSource``."""

    instances: list[FakeClient] = []
    fail_on_enter: BaseException | None = None
    enter_delay_s: float = 0.0

    def __init__(self, address, disconnected_callback=None, services=None, *,
                 timeout: float = 30.0, **kwargs) -> None:
        self.address = address
        self.disconnected_callback = disconnected_callback
        self.timeout = timeout
        self.writes: list[tuple[str, bytes]] = []
        self.callbacks: dict[str, object] = {}
        self.stopped: list[str] = []
        self.exited = False
        self.ready = threading.Event()
        type(self).instances.append(self)

    async def __aenter__(self) -> FakeClient:
        if self.enter_delay_s:
            await asyncio.sleep(self.enter_delay_s)
        if self.fail_on_enter is not None:
            raise self.fail_on_enter
        return self

    async def __aexit__(self, *exc) -> None:
        self.exited = True
        if self.disconnected_callback is not None:
            self.disconnected_callback(self)

    async def write_gatt_char(self, char_specifier, data, response=None) -> None:
        self.writes.append((str(char_specifier), bytes(data)))

    async def start_notify(self, char_specifier, callback, **kwargs) -> None:
        self.callbacks[str(char_specifier)] = callback
        if len(self.callbacks) == len(EMG_DATA_UUIDS):
            self.ready.set()

    async def stop_notify(self, char_specifier) -> None:
        self.stopped.append(str(char_specifier))

    def emit(self, k: int, data: bytes) -> None:
        """Deliver notification ``k`` on EMG characteristic ``k % 4`` (as bleak would)."""
        self.callbacks[EMG_DATA_UUIDS[k % 4]](object(), bytearray(data))


@pytest.fixture
def fake_bleak(monkeypatch):
    """Install a fake ``bleak`` module; yields the FakeClient class (fresh per test)."""
    cls = type("FakeBleakClient", (FakeClient,), {"instances": []})
    module = types.ModuleType("bleak")
    module.BleakClient = cls  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "bleak", module)
    return cls


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def started(fake_cls, **kw) -> tuple[MyoSource, FakeClient, Clock]:
    clock = Clock()
    src = MyoSource(ADDRESS, clock=clock, **kw)
    src.start()
    assert src.available, src.last_error
    client = fake_cls.instances[-1]
    assert client.ready.wait(2.0)
    return src, client, clock


def emit_samples(client: FakeClient, clock: Clock, x: np.ndarray, *, k0: int = 0,
                 extra_delay: dict[int, float] | None = None) -> int:
    """Send ``x`` (8, n) int8 as notifications; arrival = time of each packet's last sample."""
    n = x.shape[1] // 2
    for j in range(n):
        k = k0 + j
        clock.now = 100.0 + (2 * k + 1) * DT + (extra_delay or {}).get(k, 0.0)
        client.emit(k, payload(x[:, 2 * j].tolist(), x[:, 2 * j + 1].tolist()))
    return k0 + n


def ramp(n: int, start: int = 0) -> np.ndarray:
    """(8, n) int8: channel c, sample i = (start + i + 10*c) wrapped to int8."""
    i = np.arange(start, start + n)[None, :] + 10 * np.arange(8)[:, None]
    return ((i + 128) % 256 - 128).astype(np.int8)


# ------------------------------------------------------------------------------------
# protocol constants and the pure decoder (byte-level, from myohw.h)
# ------------------------------------------------------------------------------------


def test_uuid_matches_the_headers_worked_example():
    # myohw.h line 55: "the full service UUID for GCControlService would be d5060001-..."
    assert myo_uuid(0x0001) == "d5060001-a904-deb9-4748-2c7f4a124842"
    assert COMMAND_UUID == "d5060401-a904-deb9-4748-2c7f4a124842"
    assert EMG_DATA_UUIDS == (
        "d5060105-a904-deb9-4748-2c7f4a124842",
        "d5060205-a904-deb9-4748-2c7f4a124842",
        "d5060305-a904-deb9-4748-2c7f4a124842",
        "d5060405-a904-deb9-4748-2c7f4a124842",
    )
    with pytest.raises(ValueError):
        myo_uuid(0x10000)


def test_command_bytes():
    # myohw_command_set_mode_t: command 0x01, payload_size 3, emg, imu, classifier
    assert set_mode_command("raw") == bytes([0x01, 0x03, 0x03, 0x00, 0x00])
    assert set_mode_command("filtered") == bytes([0x01, 0x03, 0x02, 0x00, 0x00])
    assert set_mode_command("none") == bytes([0x01, 0x03, 0x00, 0x00, 0x00])
    assert set_mode_command(0x03) == set_mode_command("RAW ")
    # myohw_command_set_sleep_mode_t: command 0x09, payload_size 1, mode
    assert sleep_mode_command(never_sleep=True) == bytes([0x09, 0x01, 0x01])
    assert sleep_mode_command(never_sleep=False) == bytes([0x09, 0x01, 0x00])
    for bad in ("loud", 0x01, True, None):
        with pytest.raises(ValueError):
            set_mode_command(bad)  # type: ignore[arg-type]


def test_decode_splits_two_samples_of_eight_signed_bytes():
    raw = bytes([0x00, 0x01, 0x7F, 0x80, 0xFF, 0x10, 0xF0, 0x05,
                 0x02, 0x03, 0x81, 0x7E, 0xFE, 0x20, 0xE0, 0x06])
    x = decode_emg_notification(raw)
    assert x.shape == (8, 2) and x.dtype == np.int8
    assert x[:, 0].tolist() == [0, 1, 127, -128, -1, 16, -16, 5]
    assert x[:, 1].tolist() == [2, 3, -127, 126, -2, 32, -32, 6]
    assert np.array_equal(decode_emg_notification(memoryview(bytearray(raw))), x)


@pytest.mark.parametrize("n", [0, 15, 17, 20])
def test_decode_refuses_a_payload_that_is_not_16_bytes(n):
    with pytest.raises(ValueError, match="16 bytes"):
        decode_emg_notification(bytes(n))


# ------------------------------------------------------------------------------------
# the spec
# ------------------------------------------------------------------------------------


@pytest.mark.parametrize("spec,address", [
    ("myo:AA:BB:CC:DD:EE:FF", "AA:BB:CC:DD:EE:FF"),
    ("  MYO: aa:bb:cc:dd:ee:ff ", "aa:bb:cc:dd:ee:ff"),
    ("myo:12345678-9ABC-DEF0-1234-56789ABCDEF0", "12345678-9ABC-DEF0-1234-56789ABCDEF0"),
])
def test_parse_spec(spec, address):
    assert parse_myo_spec(spec) == address


@pytest.mark.parametrize("spec", [
    "myo", "myo:", "myo:AA:BB:CC:DD:EE", "myo:AA:BB:CC:DD:EE:GG", "brainflow:0",
    "file:AA:BB:CC:DD:EE:FF", "myo:AA:BB:CC:DD:EE:FF:00",
])
def test_parse_spec_rejects(spec):
    with pytest.raises(ValueError):
        parse_myo_spec(spec)


def test_source_from_spec_builds_an_unstarted_block_source():
    src = source_from_spec("myo:AA:BB:CC:DD:EE:FF", emg_mode="filtered", scale=2.0)
    assert isinstance(src, BlockSource)
    assert src.address == ADDRESS and src.emg_mode == "filtered" and src.scale == 2.0
    assert src.fs == 200.0
    assert [c.name for c in src.channels] == [f"EMG{i}" for i in range(1, 9)]
    assert all(c.kind is SignalKind.EMG for c in src.channels)
    assert not src.available and src.read() is None
    src.stop()  # stopping an unstarted source is a no-op


@pytest.mark.parametrize("kw", [
    {"emg_mode": "none"}, {"emg_mode": "bogus"}, {"scale": 0.0}, {"scale": float("nan")},
    {"use_channels": ()}, {"use_channels": (0,)}, {"use_channels": (9,)},
    {"use_channels": (2, 2)}, {"max_buffer_s": 0.0}, {"connect_timeout_s": 0.0},
])
def test_constructor_rejects(kw):
    with pytest.raises(ValueError):
        MyoSource(ADDRESS, **kw)


# ------------------------------------------------------------------------------------
# bleak is optional
# ------------------------------------------------------------------------------------


def test_missing_bleak_is_an_import_error_naming_the_ble_extra(monkeypatch):
    monkeypatch.setitem(sys.modules, "bleak", None)  # makes `import bleak` fail
    src = MyoSource(ADDRESS)
    with pytest.raises(ImportError, match="`ble` extra"):
        src.start()
    assert not src.available
    src.stop()


def test_bleak_is_imported_lazily_never_at_module_top_level():
    import ast

    tree = ast.parse(Path(myo.__file__).read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    names = {a.name for n in top if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module for n in top if isinstance(n, ast.ImportFrom) and n.module}
    assert not any(name.split(".")[0] in ("bleak", "asyncio") for name in names)


def test_the_myo_source_opens_no_socket():
    # Bluetooth LE is a radio link to a worn device, not an IP network (ADR-019).
    source = Path(myo.__file__).read_text(encoding="utf-8")
    for primitive in ("import socket", "AF_INET", "start_server", "open_connection",
                      "urlopen", "requests.", "httpx."):
        assert primitive not in source


# ------------------------------------------------------------------------------------
# streaming through the fake bleak
# ------------------------------------------------------------------------------------


def test_start_configures_the_band_then_streams(fake_bleak):
    src, client, clock = started(fake_bleak, scale=0.5)
    assert client.address == ADDRESS and client.timeout == 10.0
    # never-sleep first, then raw EMG with IMU and classifier off
    assert client.writes == [(COMMAND_UUID, bytes([0x09, 0x01, 0x01])),
                             (COMMAND_UUID, bytes([0x01, 0x03, 0x03, 0x00, 0x00]))]
    assert sorted(client.callbacks) == sorted(EMG_DATA_UUIDS)

    x = ramp(10)
    emit_samples(client, clock, x)
    block = src.read()
    assert block is not None
    assert block.fs == 200.0 and block.t0 == 0.0 and block.data.shape == (8, 10)
    assert block.data.dtype == np.float64
    np.testing.assert_array_equal(block.data, x.astype(np.float64) * 0.5)
    assert src.read() is None  # drained

    y = ramp(6, start=10)
    emit_samples(client, clock, y, k0=5)
    nxt = src.read()
    assert nxt is not None
    assert nxt.t0 == pytest.approx(10 * DT)  # continuous sample clock
    np.testing.assert_array_equal(nxt.data, y * 0.5)
    assert src.gap_samples == 0 and src.dropped_samples == 0

    src.stop()
    assert not src.available
    assert sorted(client.stopped) == sorted(EMG_DATA_UUIDS)
    assert client.writes[-2:] == [(COMMAND_UUID, bytes([0x01, 0x03, 0x00, 0x00, 0x00])),
                                  (COMMAND_UUID, bytes([0x09, 0x01, 0x00]))]
    assert client.exited
    assert src.last_error == ""  # a requested disconnect is not a failure
    src.stop()  # idempotent


def test_filtered_mode_subset_of_channels_and_no_keep_awake(fake_bleak):
    src, client, clock = started(fake_bleak, emg_mode="filtered", use_channels=(3, 1),
                                 keep_awake=False)
    assert client.writes == [(COMMAND_UUID, bytes([0x01, 0x03, 0x02, 0x00, 0x00]))]
    assert [c.name for c in src.channels] == ["EMG3", "EMG1"]
    x = ramp(4)
    emit_samples(client, clock, x)
    block = src.read()
    assert block is not None
    np.testing.assert_array_equal(block.data, x[[2, 0]].astype(np.float64))
    src.stop()
    assert (COMMAND_UUID, bytes([0x09, 0x01, 0x00])) not in client.writes


def test_a_malformed_notification_is_counted_and_skipped(fake_bleak):
    src, client, clock = started(fake_bleak)
    client.emit(0, b"\x01\x02\x03")
    assert src.bad_packets == 1
    assert src.read() is None
    emit_samples(client, clock, ramp(2))
    block = src.read()
    assert block is not None and block.n_samples == 2
    src.stop()


def test_queue_overflow_drops_the_oldest_and_shows_as_a_gap(fake_bleak):
    # capacity = 0.05 s * 200 Hz / 2 samples per packet = 5 packets
    src, client, clock = started(fake_bleak, max_buffer_s=0.05)
    x = ramp(16)                         # 8 packets, nobody reading
    emit_samples(client, clock, x)
    assert src.dropped_samples == 6      # 3 oldest packets dropped
    with src._lock:
        assert len(src._queue) == 5      # bounded
    block = src.read()
    assert block is not None
    assert block.t0 == pytest.approx(6 * DT)       # the clock skips what was dropped
    np.testing.assert_array_equal(block.data, x[:, 6:].astype(np.float64))  # newest kept
    assert src.gap_samples == 6
    src.stop()


def test_overflow_between_reads_starts_a_new_block_after_the_hole(fake_bleak):
    src, client, clock = started(fake_bleak, max_buffer_s=0.05)
    k = emit_samples(client, clock, ramp(4))
    first = src.read()
    assert first is not None and first.t0 == 0.0 and first.n_samples == 4
    emit_samples(client, clock, ramp(14, start=4), k0=k)   # 7 packets, capacity 5
    block = src.read()
    assert block is not None
    assert block.t0 == pytest.approx((4 + 4) * DT)
    assert block.n_samples == 10
    assert src.dropped_samples == 4 and src.gap_samples == 4
    src.stop()


def test_a_link_loss_resyncs_t0_and_splits_the_block(fake_bleak):
    src, client, clock = started(fake_bleak)
    # packet 2 arrives a full second late: the radio lost ~1 s of notifications
    emit_samples(client, clock, ramp(6), extra_delay={2: 1.0})
    a = src.read()
    assert a is not None and a.t0 == 0.0 and a.n_samples == 4  # stops before the hole
    b = src.read()
    assert b is not None
    assert b.t0 == pytest.approx(4 * DT + 1.0)
    assert b.n_samples == 2
    assert src.gap_samples == 200 and src.dropped_samples == 0
    src.stop()


def test_arrival_jitter_below_tolerance_keeps_the_clock_continuous(fake_bleak):
    src, client, clock = started(fake_bleak)
    emit_samples(client, clock, ramp(20), extra_delay={1: 0.1, 2: 0.08, 5: 0.2})
    block = src.read()
    assert block is not None and block.t0 == 0.0 and block.n_samples == 20
    assert src.gap_samples == 0
    src.stop()


def test_a_constant_latency_is_not_a_gap(fake_bleak):
    src, client, clock = started(fake_bleak)
    k = emit_samples(client, clock, ramp(4))
    assert src.read() is not None
    # every later packet is 0.5 s late: the first late one is a real 0.5 s hole...
    late = {j: 0.5 for j in range(k, k + 20)}
    emit_samples(client, clock, ramp(40, start=4), k0=k, extra_delay=late)
    blocks = [b for b in iter(src.read, None)]
    assert sum(b.n_samples for b in blocks) == 40
    assert len(blocks) == 1 and blocks[0].t0 == pytest.approx(4 * DT + 0.5)
    assert src.gap_samples == 100          # ...counted once, not on every packet
    src.stop()


def test_device_disconnect_makes_the_source_unavailable(fake_bleak):
    src, client, clock = started(fake_bleak)
    emit_samples(client, clock, ramp(4))
    client.disconnected_callback(client)   # the band walked out of range
    src._thread.join(2.0)                  # the BLE thread exits on its own
    assert not src.available
    assert "disconnected" in src.last_error
    block = src.read()                     # what arrived before the drop is still served
    assert block is not None and block.n_samples == 4
    assert src.read() is None
    src.stop()


def test_a_band_that_cannot_be_reached_is_a_logged_no_op(fake_bleak, caplog):
    fake_bleak.fail_on_enter = OSError("device AA:BB:CC:DD:EE:FF not found")
    src = MyoSource(ADDRESS)
    src.start()                            # no exception
    assert not src.available
    assert "not found" in src.last_error
    assert src.read() is None
    src.stop()
    assert any("unavailable" in r.getMessage() for r in caplog.records)


def test_start_gives_up_after_a_bounded_wait(fake_bleak, monkeypatch):
    monkeypatch.setattr(myo, "_START_GRACE_S", 0.0)
    fake_bleak.enter_delay_s = 0.3
    fake_bleak.fail_on_enter = TimeoutError("connect timed out")
    src = MyoSource(ADDRESS, connect_timeout_s=0.05)
    src.start()
    assert not src.available
    assert src.last_error                  # a reason is recorded
    assert src._thread is None             # stop() joined the thread
    src.stop()


def test_restart_after_stop(fake_bleak):
    src, client, clock = started(fake_bleak)
    emit_samples(client, clock, ramp(4))
    src.stop()
    assert src.read() is None              # stop() discards unread samples
    src.start()
    assert src.available
    second = fake_bleak.instances[-1]
    assert second is not client and second.ready.wait(2.0)
    emit_samples(second, clock, ramp(2))
    block = src.read()
    assert block is not None and block.t0 == 0.0  # a fresh session, a fresh clock
    src.stop()


def test_client_factory_bypasses_bleak(monkeypatch):
    monkeypatch.setitem(sys.modules, "bleak", None)
    made: list[FakeClient] = []

    def factory(*args, **kwargs):
        made.append(FakeClient(*args, **kwargs))
        return made[-1]

    src = MyoSource(ADDRESS, client_factory=factory)
    src.start()
    assert src.available and made
    src.stop()


# ------------------------------------------------------------------------------------
# the squeeze detector on 200 Hz int8 counts (calibration-relative thresholds)
# ------------------------------------------------------------------------------------


def _int8_emg(rng: np.random.Generator, sigma: np.ndarray) -> np.ndarray:
    x = rng.normal(0.0, 1.0, size=(8, sigma.size)) * sigma[None, :]
    return np.clip(np.round(x), -127, 127).astype(np.int8)


@pytest.mark.parametrize("seed", range(5))
def test_the_onset_detector_finds_a_squeeze_in_myo_counts(fake_bleak, seed):
    """End to end at 200 Hz in raw counts, thresholds relative to a same-stream calibration.

    ``step_window_s=0.05`` (10 samples) rather than the 10 ms default: at 200 Hz the
    default rounds up to the 4-sample floor, and the mean-shift artifact test then cuts a
    genuine burst on a few seeds (a property of ``emg_onset``, reported, not fixed here).
    The signals are synthetic Gaussian bursts, not recordings of a real band.
    """
    rng = np.random.default_rng(seed)
    fs = int(MYO_EMG_FS)
    # Calibration on the same stream and units: 2 s relaxed (~2 counts), 2 s squeeze.
    relaxed = _int8_emg(rng, np.full(2 * fs, 2.0)).astype(np.float64)
    squeeze = _int8_emg(rng, np.full(2 * fs, 30.0)).astype(np.float64)
    th = OnsetThresholds.from_calibration(bandlimited_rms(relaxed, fs),
                                          bandlimited_rms(squeeze, fs))
    det = EmgOnsetDetector(th, step_window_s=0.05)

    sigma = np.full(6 * fs, 2.0)
    sigma[3 * fs: 4 * fs] = 30.0            # a one-second squeeze from t = 3 s
    src, client, clock = started(fake_bleak, max_buffer_s=10.0)
    emit_samples(client, clock, _int8_emg(rng, sigma))
    events = []
    for block in iter(src.read, None):
        events.extend(det.process(block))
    src.stop()

    kinds = [e.kind for e in events]
    assert kinds == [EventKind.SQUEEZE_ON, EventKind.SQUEEZE_OFF], events
    assert 3.0 < events[0].t < 3.2
    assert 4.0 < events[1].t < 4.4
