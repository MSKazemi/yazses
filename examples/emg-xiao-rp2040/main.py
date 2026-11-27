"""YazSes EMG example for a Seeed XIAO RP2040 + Grove EMG Detector (MicroPython).

NOT TESTED ON HARDWARE. The detector in emg_detector.py is unit-tested on simulated
signals; this file, the wiring and the default thresholds have never run on a board.

Copy BOTH files (main.py and emg_detector.py) to the board, for example with
``mpremote cp emg_detector.py main.py :``. It then writes YESP lines over the USB serial
port (``design/emg-protocol.md``):

    HOLD_START / HOLD_END    the squeeze, as hold-to-talk
    HEARTBEAT                once a second
    DEBUG level=.. ...       only when DEBUG is True; the daemon ignores unknown lines

Sensor signal pin -> A0 (GP26). Power the sensor from the board's 3.3 V pin, so its output
can never exceed what the ADC allows (it is documented for 3.3 V or 5 V).
"""
from emg_detector import EmgDetector, volts_to_counts

SAMPLE_RATE_HZ = 200
ADC_PIN = 26  # A0 / D0 on the XIAO RP2040
HEARTBEAT_EVERY = SAMPLE_RATE_HZ  # one second
DEBUG = False  # True: print the live level so you can choose thresholds
DEBUG_EVERY = SAMPLE_RATE_HZ // 5

# Placeholders, never tried on a real sensor. Volts above the idle level; see
# docs/how-to/emg-xiao-rp2040.md for how to choose them.
ON_THRESHOLD = volts_to_counts(0.15)
OFF_THRESHOLD = volts_to_counts(0.08)


def run(read, emit, pace, detector=None, max_samples=None):
    """Sample, detect, emit. ``read``/``emit``/``pace`` are injected so CPython can drive it."""
    if detector is None:
        detector = EmgDetector(SAMPLE_RATE_HZ, ON_THRESHOLD, OFF_THRESHOLD)
    n = 0
    while max_samples is None or n < max_samples:
        n += 1
        event = detector.update(read())
        if event:
            emit(event)
        if n % HEARTBEAT_EVERY == 0:
            emit("HEARTBEAT")
        if DEBUG and n % DEBUG_EVERY == 0:
            emit("DEBUG level=%d baseline=%d state=%s"
                 % (detector.envelope, detector.baseline, detector.state))
        pace()


def main():
    import time

    from machine import ADC, Pin

    adc = ADC(Pin(ADC_PIN))
    period_us = 1000000 // SAMPLE_RATE_HZ
    due = [time.ticks_add(time.ticks_us(), period_us)]

    def pace():
        wait = time.ticks_diff(due[0], time.ticks_us())
        if wait > 0:
            time.sleep_us(wait)
        due[0] = time.ticks_add(due[0], period_us)

    run(adc.read_u16, print, pace)


if __name__ == "__main__":
    main()
