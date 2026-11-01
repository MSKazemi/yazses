---
title: Add a biosignal device driver
description: How to add a new electrode device to YazSes as a block source. The contract a driver must keep, a pure parser with lazy transport, registering the scheme, running check-source, and what a pull request must show.
---

# Add a biosignal device driver

A driver turns one electrode device into a stream of sample blocks. The experimental biosignal
switches read any source that keeps the contract on this page. This page covers the contract, the
NeuroSky ThinkGear driver as the worked example, the conformance check, and what to put in the pull
request.

A driver for a device nobody has tried yet is useful. A driver that claims support for a device nobody
has tested is not. Read [what not to do](#what-not-to-do) before you start.

## What a source must do

The contract is the `BlockSource` protocol in `src/yazses/biosignal/types.py`:

```python
@runtime_checkable
class BlockSource(Protocol):
    """Anything that produces SampleBlocks: a board, a file replay, a synthetic generator."""

    fs: float
    channels: tuple[ChannelInfo, ...]

    def start(self) -> None: ...
    def read(self) -> SampleBlock | None:
        """Next block, or None if nothing new yet. Raises EOFError when a finite source ends."""
        ...
    def stop(self) -> None: ...
```

A source has five parts:

* **`fs`**: the sampling rate in hertz, as a float. The device fixes it. A source must know it by the
  time `start()` returns (a Lab Streaming Layer stream only learns its rate then) and keep it the same
  for the whole run.
* **`channels`**: a tuple of `ChannelInfo(name, kind)`. The kind is one of `SignalKind.EMG`,
  `SignalKind.EEG` or `SignalKind.EOG`. Channel names must be unique and not empty.
* **`start()`**: opens the device. A missing or busy device must not raise out of `start()`. Leave
  the source unavailable, keep the reason in an attribute such as `last_error`, and let `read()`
  return `None`. An optional headset must never stop the dictation daemon.
* **`read()`**: returns the next `SampleBlock`, or `None` when no new data is ready. It should not
  block the caller. Read the port without waiting for it to fill. The only exception it may raise is
  `EOFError`, and only for a finite source such as a recording that has reached its end. A live
  device should never raise it.
* **`stop()`**: releases the device. It must be safe to call before `start()` and a second time.

Each block is a `SampleBlock`. Its `data` has shape `(n_channels, n_samples)` and is in
**microvolts**. Convert raw device counts to microvolts in the driver. The ThinkGear driver does this
with a constant that cites the vendor's conversion. If the vendor publishes no gain, do not guess
one: the Myo driver reports raw counts with a `scale` option and its docs say the values are counts.

```python
# NeuroSky: V = raw * (1.8 / 4096) / 2000  ->  µV per count
THINKGEAR_RAW_TO_UV = 1.8 / 4096.0 / 2000.0 * 1e6
```

Three more rules come from the same contract:

* **`t0`** is the time of the first sample of the block, in seconds on the source's own clock. The
  ThinkGear driver counts delivered samples and divides by `fs`. It does not read a clock.
* **Lost data is not replaced.** If a packet fails its checksum and its time cannot be placed,
  do not invent samples to fill the gap. Count the loss and expose it. The ThinkGear driver keeps
  `lost_packets` and does not move its clock for a rejected packet.
* **Empty reads return `None`.** Do not return a block with zero samples. The conformance check
  warns about empty blocks.

## Keep the parser pure and the transport lazy

Split a driver in two.

1. **A pure parser.** It turns bytes into packets. It does no I/O and reads no clock, so you can
   test it with bytes you build yourself. The ThinkGear parser is a class with one `feed` method:

   ```python
   @dataclass
   class ThinkGearParser:
       """Incremental bytes -> :class:`ThinkGearPacket` parser. Pure: no I/O, no clock."""

       def feed(self, data: bytes | bytearray) -> list[ThinkGearPacket]:
   ```

   Feed it any chunks. A packet can arrive split across several reads.

2. **A transport.** It opens the port and calls the parser. In the ThinkGear driver, the source takes
   a `serial_factory` argument. Production passes nothing and pyserial opens the port. Tests pass a
   fake port. Injection like this lets the transport be tested without hardware.

Optional libraries are imported **inside the function that needs them**, never at the top of a
module. Here is the lazy import the ThinkGear driver uses:

```python
def import_serial() -> Any:
    """The ``serial`` (pyserial) module, imported lazily.

    Raises ``ImportError`` naming the ``emg`` extra that ships it.
    """
    try:
        import serial  # type: ignore[import-untyped]
    except ImportError as exc:
        ...  # re-raises ImportError with the install hint for the emg extra
```

A fresh install with no extras must still import YazSes and run. A new library goes in an optional
extra in `pyproject.toml`, and its import goes inside the function that uses it.

### Test the parser with bytes you build

The ThinkGear packet format is a sync pair, a length byte, a payload and a checksum. A test can build
one by hand. This test is a complete example that passes against the shipped parser:

```python
from yazses.biosignal.thinkgear import ThinkGearParser, thinkgear_checksum


def test_one_raw_sample_round_trip():
    payload = bytes([0x80, 0x02, 0x00, 0x10])   # one RAW row: 0x0010 = 16 counts
    packet = bytes([0xAA, 0xAA, len(payload)]) + payload + bytes([thinkgear_checksum(payload)])
    parser = ThinkGearParser()
    packets = parser.feed(packet)
    assert packets[0].raw == (16,)


def test_bad_checksum_is_counted_not_emitted():
    payload = bytes([0x80, 0x02, 0x00, 0x10])
    packet = bytearray([0xAA, 0xAA, len(payload)]) + payload + bytes([thinkgear_checksum(payload)])
    packet[-1] ^= 0xFF                          # corrupt the checksum
    parser = ThinkGearParser()
    assert parser.feed(bytes(packet)) == []
    assert parser.stats.bad_checksum == 1
```

Also feed the same bytes one at a time in a test. A parser that works only for whole packets is a
bug that shows up on a real serial port.

Test the transport with a fake port that returns bytes from a list. Test the failure paths too: a
missing library, a port that cannot be opened, and a port that stops answering in the middle of a
run.

## Register the scheme

A driver is reached by a one-line spec such as `thinkgear:/dev/rfcomm0`. The spec is read by
`open_source` in `src/yazses/biosignal/sources.py`. Each scheme has one branch, and the device module
is imported only inside that branch:

```python
    if scheme == "thinkgear":
        from yazses.biosignal.thinkgear import thinkgear_from_spec
        return thinkgear_from_spec(rest, **kw)
```

When you add a scheme:

* Add one branch in the same style. Import the device module inside the branch.
* Add the scheme to the list in the `open_source` docstring.
* Add it to `_SPEC_HELP` in the same file. That text is what a user sees for a malformed spec.
* Return a source that is **not started**. `open_source` does not call `start()`.

Parse the options of your spec in a function that raises `ValueError` for a missing port or an unknown
option. The ThinkGear spec parser does this and is a good model.

## Run the conformance check

Before you open a pull request, run the conformance check against your spec:

```sh
uv run yazses biosignal check-source thinkgear:/dev/rfcomm0
```

`check-source` opens the source for a few seconds and judges each clause of the contract. Its options:

* `-s` or `--seconds`: how long to drive the source, as a float. The default is 5.0. The rate checks
  need at least 2 seconds of stream, so keep the default for a real verdict.
* `--json`: print one JSON object with `passed` and one entry per clause, instead of the report.
* `-h` or `--help`: show the help.

The check covers:

* the lifecycle: `stop()` before `start()`, `start()` itself, and `stop()` after the run, twice
* the declared `fs` and `channels`, after `start()`
* that `read()` returns a block or `None`, and raises only `EOFError`
* that the first block arrives, and that no silence is longer than the integrity stall limit (1.5 s)
* the block shape, the block layout (the same `fs` and channels on every block), and finite values
* that `t0` is increasing and contiguous, with no gap or overlap
* the sample rate, measured from `t0` and from the arrival clock, for a live source
* that `read()` after `stop()` returns `None` (a driver that still delivers data is a warning)

Each clause prints one line, `pass`, `warn`, `fail` or `skip`, with a reason. Warnings and skips do
not fail a source. A skip is usually a run that was too short for a rate check or a source that did
not reach its end.

Exit codes:

* **0**: every clause passed.
* **1**: at least one clause failed. The report names the clause. Fix the driver and run it again.
* **2**: the source could not be built, for example a malformed spec or a missing library.

Here is the real output for the built-in synthetic source over 2 seconds:

```text
Source conformance: SyntheticSource — PASS (15 pass, 0 warn, 0 fail, 3 skip)
  ran 1.96 s of stream in 2.00 s; 49 block(s), 980 sample(s); end of stream: no
  [PASS] protocol
  [PASS] stop_before_start
  [PASS] start
  [PASS] declared_fs        500 Hz
  [PASS] declared_channels  Fp1:eeg, Fp2:eeg, EMG1:emg, EMG2:emg
  ...
  [SKIP] rate_t0            only 1.92 s of t0 (needs 2 s)
  [SKIP] rate_arrival       only 1.92 s between the first and last block (needs 2 s)
  [SKIP] read_after_eof     the run ended before the stream did
  [PASS] stop
  [PASS] stop_twice
  [PASS] read_after_stop    returns None
```

A pass means the driver keeps the contract. It does not mean the signal is good. A driver can pass
with a flat or noisy waveform. Check the signal with `yazses biosignal doctor` and a short
`yazses biosignal calibrate` on the real device.

## What not to do

* **No network.** A driver talks only to a local device, a local file or a local stream. Do not add a
  cloud call, telemetry, analytics, or a download on first run. YazSes has a test,
  `tests/test_egress_inventory.py`, that fails when a module under `src/yazses/` gains an outbound
  network call that is not registered and classified.
* **Never use a vendor's opaque score as an event.** Some headsets send attention, meditation or
  blink-strength values with no published definition. The ThinkGear driver skips them on purpose and
  keeps only the raw waveform and the poor-signal flag. A detector that uses a vendor score cannot be
  tested or explained.
* **Never invent samples for lost packets.** Count the loss and report it. A made-up sample looks like
  a real signal to the detector.
* **Never claim hardware support you did not test.** Until a pull request shows a real device with
  real output, the device is untested. The hardware guide says so for every device it lists. Keep
  that wording until your evidence supports a change.
* **No medical claims.** YazSes is not a medical device. Do not describe a driver or a switch as a
  diagnostic or monitoring tool.
* **Do not put a person's recording in a pull request.** A recording of a real person is personal data.
  Use a synthetic file or a de-identified fixture.

## What to put in the pull request

A driver pull request must show:

* **The device.** Model, firmware or version, the operating system, and the spec you used.
* **Whether it was real hardware.** Say so in one line. If you tested with a replay file or only with
  bytes you built, say that.
* **The `check-source` output.** Paste the full report from the real device, with the `--seconds`
  value you used. Include the exit code.
* **The tests you ran.** The parser tests and the transport tests, and the commands you used. The
  project gates are `uv run python -m pytest tests/ -v` and `uv run ruff check src tests scripts
  paper/benchmark`. Report any gate that fails. Do not leave it out.
* **The docs you changed.** A driver that users can reach needs an entry in `CHANGELOG.md` under
  `[Unreleased]`, and a line in the [hardware guide](../how-to/biosignal-hardware.md) that says
  whether the device was tested.

A pull request that adds a driver without hardware evidence is welcome, but its docs must say the
device is untested.
