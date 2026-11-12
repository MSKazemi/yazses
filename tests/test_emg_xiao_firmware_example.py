"""Guards for the XIAO RP2040 + Grove EMG Detector firmware example.

Everything here is SIMULATED. No sensor, board or serial port is involved, and none of
these tests says the example works on hardware: it has never run there. What they pin is
the detector's logic on synthetic signals, and that the firmware glue emits lines the real
host consumer (``yazses.platform.emg.backend.EMGBackend``) understands.

The detector is imported the way the firmware imports it: as the top-level module
``emg_detector`` from the example directory, so a rename or a stray import fails here.
"""
from __future__ import annotations

import ast
import importlib.util
import random
import sys
import time
import types
from pathlib import Path

import pytest

from yazses.platform.emg.backend import EMGBackend

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "emg-xiao-rp2040"
RATE = 200
FULL = 65535
VREF = 3.3
IDLE_V = 1.5


def counts(volts: float) -> int:
    return max(0, min(FULL, round(volts * FULL / VREF)))


@pytest.fixture()
def det_mod(monkeypatch):
    """``emg_detector`` imported as the firmware imports it, without leaking into sys.modules."""
    monkeypatch.syspath_prepend(str(EXAMPLE))
    monkeypatch.delitem(sys.modules, "emg_detector", raising=False)
    import emg_detector

    yield emg_detector
    sys.modules.pop("emg_detector", None)


def trace(*segments, seed=1, noise_v=0.01):
    """Concatenate (seconds, volts) or (seconds, start_v, end_v) segments into ADC counts."""
    rng = random.Random(seed)
    out = []
    for seg in segments:
        secs, v0 = seg[0], seg[1]
        v1 = seg[2] if len(seg) > 2 else v0
        n = round(secs * RATE)
        for i in range(n):
            v = v0 + (v1 - v0) * (i / n if n else 0)
            out.append(counts(v + rng.gauss(0.0, noise_v)))
    return out


def run(det, samples):
    """Feed samples; return [(sample_index, event)]."""
    events = []
    for i, s in enumerate(samples):
        e = det.update(s)
        if e:
            events.append((i, e))
    return events


def names(events):
    return [e for _, e in events]


def ms(n_samples):
    return n_samples * 1000 / RATE


@pytest.fixture()
def det(det_mod):
    return det_mod.EmgDetector(sample_rate_hz=RATE)


# --------------------------------------------------------------------------- idle / squeeze


def test_idle_band_produces_no_events(det):
    ev = run(det, trace((60, IDLE_V)))
    assert ev == []
    assert det.state == "idle"
    assert abs(det.baseline - counts(IDLE_V)) < counts(0.02)


def test_no_event_is_possible_during_warmup(det):
    # Even a rail-high signal during the first second only sets the baseline.
    ev = run(det, trace((0.9, 3.0)))
    assert ev == []
    assert det.state == "warmup"


def test_deliberate_squeeze_gives_exactly_start_then_end(det):
    sig = trace((2, IDLE_V), (1.5, 2.6), (2, IDLE_V))
    ev = run(det, sig)
    assert names(ev) == ["HOLD_START", "HOLD_END"]
    onset, release = 2 * RATE, 3.5 * RATE
    start_i, end_i = ev[0][0], ev[1][0]
    assert 0 <= ms(start_i - onset) <= 200  # debounce + smoothing, not seconds
    assert 0 <= ms(end_i - release) <= 450  # off-debounce + smoothing


def test_two_squeezes_give_two_pairs(det):
    sig = trace((2, IDLE_V), (1, 2.5), (1.5, IDLE_V), (1, 2.5), (1.5, IDLE_V))
    assert names(run(det, sig)) == ["HOLD_START", "HOLD_END"] * 2


def test_small_deflection_just_above_idle_is_ignored(det):
    # 0.1 V above idle sits between the off and on thresholds: never enough to start.
    ev = run(det, trace((2, IDLE_V), (5, IDLE_V + 0.10), (1, IDLE_V)))
    assert ev == []


# --------------------------------------------------------------------------- debounce


@pytest.mark.parametrize("twitch_ms", [10, 20, 30])
def test_twitch_shorter_than_debounce_is_ignored(det, twitch_ms):
    sig = trace((2, IDLE_V), (twitch_ms / 1000, 3.0), (2, IDLE_V))
    assert run(det, sig) == []


def test_twitch_longer_than_debounce_fires(det):
    sig = trace((2, IDLE_V), (0.25, 3.0), (2, IDLE_V))
    assert names(run(det, sig)) == ["HOLD_START", "HOLD_END"]


def test_single_sample_spike_is_ignored(det):
    sig = trace((2, IDLE_V), (2, IDLE_V))
    sig[300] = FULL
    assert run(det, sig) == []


def test_brief_dropout_inside_a_squeeze_does_not_split_it(det):
    sig = trace((2, IDLE_V), (1, 2.6), (0.06, IDLE_V), (1, 2.6), (2, IDLE_V))
    assert names(run(det, sig)) == ["HOLD_START", "HOLD_END"]


def test_long_pause_inside_a_squeeze_does_split_it(det):
    sig = trace((2, IDLE_V), (1, 2.6), (1.0, IDLE_V), (1, 2.6), (2, IDLE_V))
    assert names(run(det, sig)) == ["HOLD_START", "HOLD_END"] * 2


# --------------------------------------------------------------------------- hysteresis


def test_active_signal_that_sags_between_the_thresholds_stays_active(det):
    # Starts above the on threshold, then rests at +0.10 V: above off (0.08), below on (0.15).
    sig = trace((2, IDLE_V), (1, 2.6), (3, IDLE_V + 0.10), (2, IDLE_V))
    ev = run(det, sig)
    assert names(ev) == ["HOLD_START", "HOLD_END"]
    sag_start, sag_end = 3 * RATE, 6 * RATE
    assert sag_start < ev[1][0]  # not ended by the sag...
    assert ev[1][0] > sag_end - 1  # ...only after it was over


def test_signal_hovering_around_the_on_threshold_does_not_chatter(det_mod):
    d = det_mod.EmgDetector(sample_rate_hz=RATE, on_threshold=3000, off_threshold=1600)
    base = counts(IDLE_V)
    rng = random.Random(7)
    sig = [base] * 300
    # Wanders between the thresholds with occasional excursions over "on".
    sig += [base + int(rng.uniform(1800, 3400)) for _ in range(2000)]
    sig += [base] * 300
    ev = run(d, sig)
    assert len(ev) <= 2
    assert names(ev) in ([], ["HOLD_START", "HOLD_END"])


# --------------------------------------------------------------------------- drift


@pytest.mark.parametrize("end_v", [1.75, 1.25])
def test_slow_drift_does_not_trigger_and_is_tracked(det, end_v):
    ev = run(det, trace((2, IDLE_V), (240, IDLE_V, end_v), (10, end_v)))
    assert ev == []
    assert abs(det.baseline - counts(end_v)) < counts(0.05)


def test_squeeze_is_still_detected_after_the_baseline_has_drifted(det):
    sig = trace((2, IDLE_V), (240, IDLE_V, 1.75), (5, 1.75), (1, 2.5), (2, 1.75))
    assert names(run(det, sig)) == ["HOLD_START", "HOLD_END"]


def test_the_same_rise_made_quickly_is_a_squeeze_not_drift(det):
    sig = trace((2, IDLE_V), (0.5, IDLE_V, 1.75), (1.5, 1.75), (2, IDLE_V))
    assert "HOLD_START" in names(run(det, sig))


def test_a_held_squeeze_is_not_absorbed_into_the_baseline(det):
    d = det
    run(d, trace((2, IDLE_V)))
    before = d.baseline
    run(d, trace((20, 2.4)))
    assert abs(d.baseline - before) < counts(0.02)


# --------------------------------------------------------------------------- saturation


def test_squeeze_to_the_rail_works_and_leaves_the_baseline_alone(det):
    sig = trace((2, IDLE_V), (1.5, VREF, VREF), (3, IDLE_V))
    ev = run(det, sig)
    assert names(ev) == ["HOLD_START", "HOLD_END"]
    assert abs(det.baseline - counts(IDLE_V)) < counts(0.02)


def test_saturated_flag_follows_the_signal(det):
    run(det, trace((2, IDLE_V)))
    assert det.saturated is False
    det.update(FULL)
    assert det.saturated is True
    det.update(counts(IDLE_V))
    assert det.saturated is False


def test_signal_stuck_at_the_rail_is_cut_off_at_max_hold_and_does_not_retrigger(det):
    sig = trace((2, IDLE_V), (40, VREF, VREF))
    ev = run(det, sig)
    assert names(ev) == ["HOLD_START", "HOLD_END"]
    held = ms(ev[1][0] - ev[0][0])
    assert 29900 <= held <= 30100  # the protocol's 30 s maximum


def test_detector_recovers_after_a_stuck_episode(det):
    sig = trace(
        (2, IDLE_V), (40, VREF, VREF), (20, IDLE_V), (1, 2.5), (2, IDLE_V),
    )
    ev = run(det, sig)
    assert names(ev) == ["HOLD_START", "HOLD_END", "HOLD_START", "HOLD_END"]


def test_a_permanent_level_shift_is_relearned_not_locked_out_forever(det):
    # The idle level moves to 2.2 V for good (say the sensor was re-seated). The detector
    # cuts the first hold off at 30 s, then re-learns 2.2 V as idle, and a squeeze from
    # there is detected again.
    sig = trace((2, IDLE_V), (45, 2.2), (2, 2.2), (1, 2.9), (2, 2.2))
    ev = run(det, sig)
    assert names(ev) == ["HOLD_START", "HOLD_END", "HOLD_START", "HOLD_END"]
    assert ev[2][0] > (2 + 45 + 2) * RATE  # the second start is the real squeeze


def test_baseline_found_again_quickly_after_a_rail_episode(det):
    # Re-learned at the rail, then the signal returns to idle. Three seconds later a squeeze
    # to only 2.0 V must be seen, which a baseline still sliding down from 3.3 V would miss.
    sig = trace((2, IDLE_V), (40, VREF, VREF), (3, IDLE_V), (1, 2.0), (2, IDLE_V))
    ev = run(det, sig)
    assert names(ev) == ["HOLD_START", "HOLD_END", "HOLD_START", "HOLD_END"]


def test_forced_end_waits_for_the_signal_to_settle(det_mod):
    d = det_mod.EmgDetector(sample_rate_hz=RATE, max_hold_ms=2000, rebase_ms=60000)
    ev = run(d, trace((2, IDLE_V), (10, 2.5), (2, IDLE_V), (1, 2.5), (2, IDLE_V)))
    # One forced end at 2 s, no restart while still high, then a normal second squeeze.
    assert names(ev) == ["HOLD_START", "HOLD_END", "HOLD_START", "HOLD_END"]


# --------------------------------------------------------------------------- noise / glitches


def test_noise_well_below_threshold_gives_no_events_over_five_minutes(det):
    assert run(det, trace((300, IDLE_V), noise_v=0.03, seed=11)) == []


def test_a_single_glitch_to_zero_does_not_disturb_detection(det):
    sig = trace((2, IDLE_V), (5, IDLE_V), (1, 2.5), (2, IDLE_V))
    sig[2 * RATE + 100] = 0
    assert names(run(det, sig)) == ["HOLD_START", "HOLD_END"]


def test_noisy_squeeze_is_still_one_clean_hold(det):
    sig = trace((2, IDLE_V), (1.5, 2.4), (2, IDLE_V), noise_v=0.06, seed=5)
    assert names(run(det, sig)) == ["HOLD_START", "HOLD_END"]


@pytest.mark.parametrize("seed", range(10))
def test_events_always_alternate_start_end(det_mod, seed):
    d = det_mod.EmgDetector(sample_rate_hz=RATE)
    rng = random.Random(seed)
    sig = []
    for _ in range(60):
        sig += trace((rng.uniform(0.02, 1.5), rng.choice([IDLE_V, 2.0, 2.8, VREF])),
                     seed=rng.randrange(10**6), noise_v=0.04)
    got = names(run(d, trace((2, IDLE_V)) + sig))
    assert got == ["HOLD_START", "HOLD_END"] * (len(got) // 2) + (["HOLD_START"] if len(got) % 2 else [])


# --------------------------------------------------------------------------- protocol limits


def test_hold_is_never_shorter_than_min_hold(det_mod):
    d = det_mod.EmgDetector(sample_rate_hz=RATE, off_ms=5, smooth_ms=5, on_ms=5,
                            min_hold_ms=100)
    ev = run(d, trace((2, IDLE_V), (0.03, 2.8), (2, IDLE_V), noise_v=0.0))
    assert names(ev) == ["HOLD_START", "HOLD_END"]
    assert ms(ev[1][0] - ev[0][0]) >= 100 - 1


def test_default_holds_respect_the_spec_limits(det):
    ev = run(det, trace((2, IDLE_V), (0.2, 2.6), (2, IDLE_V), (40, 2.6), (3, IDLE_V)))
    holds = [ms(b[0] - a[0]) for a, b in zip(ev[::2], ev[1::2])]
    assert holds and all(100 <= h <= 30000 + 5 for h in holds)


# --------------------------------------------------------------------------- options


def test_rectify_counts_a_dip_as_activity_only_when_asked(det_mod):
    sig = trace((2, IDLE_V), (1, 1.0), (2, IDLE_V))
    plain = det_mod.EmgDetector(sample_rate_hz=RATE)
    rect = det_mod.EmgDetector(sample_rate_hz=RATE, rectify=True)
    assert run(plain, sig) == []
    assert names(run(rect, sig)) == ["HOLD_START", "HOLD_END"]


def test_reset_relearns_the_baseline(det):
    run(det, trace((5, IDLE_V)))
    det.reset()
    assert det.state == "warmup"
    run(det, trace((5, 2.0)))
    assert abs(det.baseline - counts(2.0)) < counts(0.03)


def test_thresholds_and_rates_are_validated(det_mod):
    E = det_mod.EmgDetector
    with pytest.raises(ValueError):
        E(on_threshold=1000, off_threshold=1000)
    with pytest.raises(ValueError):
        E(on_threshold=1000, off_threshold=2000)
    with pytest.raises(ValueError):
        E(off_threshold=0)
    with pytest.raises(ValueError):
        E(sample_rate_hz=0)
    with pytest.raises(ValueError):
        E(min_hold_ms=500, max_hold_ms=100)


def test_volts_to_counts(det_mod):
    assert det_mod.volts_to_counts(3.3) == pytest.approx(65535)
    assert det_mod.volts_to_counts(0) == 0
    assert det_mod.volts_to_counts(1.65) == pytest.approx(65535 / 2)


# --------------------------------------------------------------------------- MicroPython-safe


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return tree, [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]


def test_detector_has_no_imports_at_all():
    _, imps = _imports(EXAMPLE / "emg_detector.py")
    assert imps == []  # nothing to be missing on the board, no typing-only import


def test_firmware_sources_use_no_syntax_micropython_may_lack():
    for name in ("emg_detector.py", "main.py"):
        tree = ast.parse((EXAMPLE / name).read_text(encoding="utf-8"))
        bad = [type(n).__name__ for n in ast.walk(tree)
               if isinstance(n, (ast.AnnAssign, ast.Match, ast.NamedExpr, ast.TypeAlias))]
        assert bad == [], f"{name}: {bad}"
        # No function annotations: MicroPython ignores them, but the example stays plain.
        for n in ast.walk(tree):
            if isinstance(n, ast.FunctionDef):
                assert n.returns is None and all(a.annotation is None for a in n.args.args)


def test_main_imports_only_what_exists(det_mod):
    _, imps = _imports(EXAMPLE / "main.py")
    for imp in imps:
        if isinstance(imp, ast.ImportFrom) and imp.module == "emg_detector":
            for alias in imp.names:
                assert hasattr(det_mod, alias.name)
        else:
            mods = [imp.module] if isinstance(imp, ast.ImportFrom) else [a.name for a in imp.names]
            assert set(mods) <= {"machine", "time"}


# --------------------------------------------------------------------------- the firmware glue


@pytest.fixture()
def firmware(det_mod, monkeypatch):
    spec = importlib.util.spec_from_file_location("emg_xiao_main", EXAMPLE / "main.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _drive(firmware, samples, **kw):
    out = []
    it = iter(samples)
    firmware.run(lambda: next(it), out.append, lambda: None, max_samples=len(samples), **kw)
    return out


def _consume(lines):
    """Hand lines to the real host consumer and record what the daemon would be told."""
    calls = []
    backend = EMGBackend("unused", on_hold_start=lambda n: calls.append("start"),
                         on_hold_end=lambda: calls.append("end"))
    for line in lines:
        backend._dispatch(line)
    return calls


def test_glue_emits_protocol_lines_the_real_consumer_understands(firmware):
    sig = trace((2, IDLE_V), (1.5, 2.6), (2, IDLE_V))
    lines = _drive(firmware, sig)
    assert [ln for ln in lines if ln != "HEARTBEAT"] == ["HOLD_START", "HOLD_END"]
    assert _consume(lines) == ["start", "end"]
    for ln in lines:
        assert ln.isascii() and len(ln.encode()) + 1 <= 256


def test_glue_heartbeats_once_per_second_of_samples(firmware):
    lines = _drive(firmware, trace((5, IDLE_V)))
    assert lines.count("HEARTBEAT") == 5


def test_glue_debug_lines_are_off_by_default_and_ignored_by_the_daemon(firmware, monkeypatch):
    assert _drive(firmware, trace((3, IDLE_V))).count("HEARTBEAT") == 3
    assert not any(ln.startswith("DEBUG") for ln in _drive(firmware, trace((3, IDLE_V))))
    monkeypatch.setattr(firmware, "DEBUG", True)
    lines = _drive(firmware, trace((3, IDLE_V)))
    dbg = [ln for ln in lines if ln.startswith("DEBUG ")]
    assert dbg and all(ln.isascii() and len(ln) < 200 for ln in dbg)
    assert _consume(lines) == []


def test_main_wires_the_adc_pin_and_paces_the_loop(firmware, monkeypatch, capsys):
    made = {}

    class Pin:
        def __init__(self, n):
            made["pin"] = n

    class ADC:
        def __init__(self, pin):
            made["adc_pin"] = pin

        def read_u16(self):
            made["reads"] = made.get("reads", 0) + 1
            if made["reads"] > 500:
                raise KeyboardInterrupt
            return counts(IDLE_V)

    machine = types.ModuleType("machine")
    machine.ADC, machine.Pin = ADC, Pin
    monkeypatch.setitem(sys.modules, "machine", machine)
    sleeps = []
    clock = [0]
    monkeypatch.setattr(time, "ticks_us", lambda: clock[0], raising=False)
    monkeypatch.setattr(time, "ticks_add", lambda a, b: a + b, raising=False)
    monkeypatch.setattr(time, "ticks_diff", lambda a, b: a - b, raising=False)
    monkeypatch.setattr(time, "sleep_us", lambda us: (sleeps.append(us), clock.__setitem__(0, clock[0] + us)),
                        raising=False)
    with pytest.raises(KeyboardInterrupt):
        firmware.main()
    assert made["pin"] == 26 and isinstance(made["adc_pin"], Pin)
    assert sleeps and all(0 < s <= 1_000_000 // firmware.SAMPLE_RATE_HZ for s in sleeps)
    assert capsys.readouterr().out.count("HEARTBEAT") == 2  # 500 reads at 200 Hz


def test_firmware_thresholds_are_a_valid_hysteresis_pair(firmware):
    assert 0 < firmware.OFF_THRESHOLD < firmware.ON_THRESHOLD < FULL / 2


# --------------------------------------------------------------------------- the docs page


PAGE = Path(__file__).resolve().parents[1] / "docs" / "how-to" / "emg-xiao-rp2040.md"


def test_docs_page_says_plainly_it_is_untested_and_not_medical_and_not_endorsed():
    text = PAGE.read_text(encoding="utf-8")
    low = text.lower()
    assert "never run on a board" in low
    assert "not tested" in low
    assert "cannot be used for medical purposes" in low
    assert "not made, reviewed or endorsed by seeed" in low
    assert "not a statement from seeed" in low
    assert "mains" in low


def test_docs_page_config_and_pin_match_the_code(firmware):
    text = PAGE.read_text(encoding="utf-8")
    assert 'mode = "full_text"' in text
    assert f"GPIO{firmware.ADC_PIN}" in text
    assert "`ON_THRESHOLD`" in text and "`OFF_THRESHOLD`" in text
    assert "DEBUG" in text
