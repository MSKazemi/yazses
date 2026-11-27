"""Squeeze detector for the YazSes EMG example: samples in, YESP events out.

Pure Python with no imports, so the same file runs on MicroPython (the board) and on
CPython (the unit tests in ``tests/test_emg_xiao_firmware_example.py``). Keep it that way:
no ``typing``, no ``dataclasses``, no ``time`` -- time is counted in samples, which also
means a ``ticks_ms`` wrap-around cannot confuse it.

Feed it one ADC reading per call to :meth:`EmgDetector.update`. It returns ``"HOLD_START"``,
``"HOLD_END"`` or ``None``; those are exactly the lines the YazSes serial protocol
(``design/emg-protocol.md``) wants.

How it decides, in order:

1. Warm-up. The first ``warmup_ms`` of samples are averaged into the idle baseline.
   Keep the muscle relaxed during that time. No event is possible yet.
2. Baseline tracking. While idle, the baseline follows slow drift (time constant
   ``baseline_ms``). It stops following as soon as the signal rises toward the start
   threshold, so a held squeeze is never absorbed into the baseline.
3. Envelope. ``sample - baseline`` is capped, then smoothed (``smooth_ms``). By default only a rise
   counts (the Seeed Grove EMG Detector is documented to idle near 1.5 V and rise on
   activity); ``rectify=True`` counts a fall as well, for a sensor that swings both ways.
4. Hysteresis. The envelope must reach ``on_threshold`` to start and fall under the lower
   ``off_threshold`` to end, so a signal hovering near one level does not chatter.
5. Debounce. Start needs ``on_ms`` of continuous activity (a short twitch is ignored);
   end needs ``off_ms`` of continuous quiet (a brief dip mid-squeeze is ignored).
6. Protocol limits. ``HOLD_START`` to ``HOLD_END`` is at least ``min_hold_ms`` and at most
   ``max_hold_ms`` (the 100 ms / 30 s limits in the spec). After a forced end the detector
   waits for the signal to settle, and re-learns the baseline if it never does.

All thresholds are in raw ADC counts (``read_u16()`` on the RP2040: 0..65535 for
0..3.3 V). The defaults are untested placeholders: they were never tried on a real sensor.
"""

HOLD_START = "HOLD_START"
HOLD_END = "HOLD_END"

WARMUP = "warmup"
IDLE = "idle"
ACTIVE = "active"
LOCKED = "locked"  # a forced end happened; waiting for the signal to settle

FULL_SCALE = 65535
VREF = 3.3


def volts_to_counts(volts, vref=VREF, full_scale=FULL_SCALE):
    """Convert a voltage on a ``vref``-referenced ADC to counts (a float)."""
    return volts * full_scale / vref


def _samples(ms, rate_hz):
    """Whole samples in ``ms`` at ``rate_hz``, never fewer than one."""
    n = int(ms * rate_hz / 1000.0 + 0.5)
    return n if n >= 1 else 1


class EmgDetector:
    """Threshold + hysteresis + debounce + baseline tracking on one ADC channel."""

    def __init__(
        self,
        sample_rate_hz=200,
        on_threshold=None,
        off_threshold=None,
        on_ms=40,
        off_ms=150,
        min_hold_ms=100,
        max_hold_ms=30000,
        smooth_ms=40,
        baseline_ms=5000,
        warmup_ms=1000,
        rebase_ms=5000,
        saturation=64000,
        rectify=False,
    ):
        if on_threshold is None:
            on_threshold = volts_to_counts(0.15)
        if off_threshold is None:
            off_threshold = volts_to_counts(0.08)
        if sample_rate_hz <= 0:
            raise ValueError("sample_rate_hz must be positive")
        if off_threshold <= 0 or on_threshold <= off_threshold:
            raise ValueError("need 0 < off_threshold < on_threshold (that gap is the hysteresis)")
        if max_hold_ms < min_hold_ms:
            raise ValueError("max_hold_ms must be at least min_hold_ms")
        rate = sample_rate_hz
        self._on = float(on_threshold)
        self._off = float(off_threshold)
        self._clip = 2.0 * self._on
        self._on_n = _samples(on_ms, rate)
        self._off_n = _samples(off_ms, rate)
        self._min_hold_n = _samples(min_hold_ms, rate)
        self._max_hold_n = _samples(max_hold_ms, rate)
        self._warmup_n = _samples(warmup_ms, rate)
        self._rebase_n = _samples(rebase_ms, rate)
        self._recover_n = _samples(30000, rate)  # how long after a re-learn to chase the idle level down
        self._a_env = 1.0 / _samples(smooth_ms, rate)
        self._a_base = 1.0 / _samples(baseline_ms, rate)
        self._a_down = 1.0 / _samples(500, rate)  # re-find a baseline that was left too high
        self._saturation = saturation
        self._rectify = rectify
        self.reset()

    def reset(self):
        """Forget everything and warm up again (call after the sensor is re-seated)."""
        self.state = WARMUP
        self.baseline = 0.0
        self.envelope = 0.0
        self.saturated = False
        self._acc = 0.0
        self._n = 0
        self._on_count = 0
        self._off_count = 0
        self._hold_n = 0
        self._lock_n = 0
        self._recover = 0

    def update(self, sample):
        """Consume one ADC reading. Returns ``"HOLD_START"``, ``"HOLD_END"`` or ``None``."""
        s = float(sample)
        self.saturated = s >= self._saturation

        if self.state == WARMUP:
            self._acc += s
            self._n += 1
            if self._n >= self._warmup_n:
                self.baseline = self._acc / self._n
                self.envelope = 0.0
                self.state = IDLE
            return None

        dev = s - self.baseline
        if self._rectify and dev < 0:
            level = -dev
        else:
            level = dev
        # The input to the smoother is capped at twice the start threshold. Without the cap
        # a brief but huge spike fills the smoother and keeps the envelope above the
        # threshold for longer than the debounce, so the debounce would measure energy
        # instead of duration. A sustained squeeze still settles above the threshold.
        x = level if level < self._clip else self._clip
        self.envelope += self._a_env * ((x if x > 0 else 0.0) - self.envelope)
        quiet = level < self._off and self.envelope < self._off
        event = None

        if self.state == IDLE:
            if self.envelope >= self._on:
                self._on_count += 1
            else:
                self._on_count = 0
            if self._on_count >= self._on_n:
                self.state = ACTIVE
                self._hold_n = 0
                self._off_count = 0
                event = HOLD_START
            elif self._recover > 0 and dev < -self._on:
                # Shortly after a stuck-high episode the re-learned baseline may sit far
                # above the real idle level. Follow it down quickly; a one-sample glitch
                # cannot drag it far at this rate. Ordinary dips never take this path.
                self.baseline += self._a_down * dev
            elif quiet:
                self.baseline += self._a_base * dev
            if self._recover > 0:
                self._recover -= 1

        elif self.state == ACTIVE:
            self._hold_n += 1
            if self.envelope < self._off:
                self._off_count += 1
            else:
                self._off_count = 0
            if self._off_count >= self._off_n and self._hold_n >= self._min_hold_n:
                self.state = IDLE
                self._on_count = 0
                event = HOLD_END
            elif self._hold_n >= self._max_hold_n:
                self.state = LOCKED
                self._lock_n = 0
                self._off_count = 0
                event = HOLD_END

        else:  # LOCKED
            self._lock_n += 1
            if self.envelope < self._off:
                self._off_count += 1
            else:
                self._off_count = 0
            if self._off_count >= self._off_n:
                self.state = IDLE
                self._on_count = 0
            elif self._lock_n >= self._rebase_n:
                # Never settled: treat the new level as the new idle level.
                self.baseline = s
                self.envelope = 0.0
                self._recover = self._recover_n
                self.state = IDLE
                self._on_count = 0

        return event
