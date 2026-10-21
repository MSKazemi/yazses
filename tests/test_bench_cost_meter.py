"""CPU core-seconds and energy for a benchmark phase (`paper/benchmark/cost_meter.py`, #506).

Pure logic against fakes: a fake clock, a fake sysfs tree under `tmp_path`, a fake probe.
Nothing here reads the host's `/sys`, so the result does not depend on the laptop it runs
on (the suite has been bitten by tests that did).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

BENCH = Path(__file__).resolve().parent.parent / "paper" / "benchmark"


@pytest.fixture(scope="module")
def cm():
    spec = importlib.util.spec_from_file_location("cost_meter", BENCH / "cost_meter.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules["cost_meter"] = module
    spec.loader.exec_module(module)
    return module


class FakeClock:
    """CPU (user, system) and wall advance only when the test says so."""

    def __init__(self) -> None:
        self.user = 0.0
        self.system = 0.0
        self.t = 100.0

    def cpu(self) -> tuple[float, float]:
        return self.user, self.system

    def wall(self) -> float:
        return self.t

    def tick(self, *, user: float = 0.0, system: float = 0.0, wall: float = 0.0) -> None:
        self.user += user
        self.system += system
        self.t += wall


class FakeProbe:
    name = "fake"

    def __init__(self, result: dict) -> None:
        self.result = result
        self.calls: list[str] = []

    def begin(self) -> None:
        self.calls.append("begin")

    def end(self) -> dict:
        self.calls.append("end")
        return self.result


# --- core-seconds arithmetic ---------------------------------------------------------

def test_core_seconds_sum_user_and_system_over_spans_only(cm) -> None:
    clk = FakeClock()
    m = cm.CostMeter(cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    with m.span(audio_s=10.0):
        clk.tick(user=6.0, system=2.0, wall=2.0)
    clk.tick(user=50.0, system=50.0, wall=5.0)  # between spans: must NOT be billed
    with m.span(audio_s=5.0):
        clk.tick(user=3.0, system=1.0, wall=1.0)
    rec = m.end()
    assert rec["cpu_user_s"] == 9.0
    assert rec["cpu_system_s"] == 3.0
    assert rec["cpu_core_seconds"] == 12.0
    assert rec["audio_s"] == 15.0
    assert rec["cpu_core_seconds_per_audio_s"] == pytest.approx(12.0 / 15.0, abs=1e-4)
    assert rec["span_wall_s"] == 3.0
    assert rec["bracket_wall_s"] == 8.0
    assert rec["mean_cores_busy"] == 4.0  # 12 core-s over 3 s of wall inside spans
    assert rec["n_spans"] == 2


def test_a_span_that_raises_is_still_accounted(cm) -> None:
    clk = FakeClock()
    m = cm.CostMeter(cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    with pytest.raises(ValueError), m.span(audio_s=1.0):
        clk.tick(user=1.0, wall=1.0)
        raise ValueError("decoder died")
    assert m.end()["cpu_core_seconds"] == 1.0


def test_no_audio_means_null_not_zero(cm) -> None:
    """The model-load phase has no audio; a 0 would read as 'free per second'."""
    clk = FakeClock()
    m = cm.CostMeter(cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    with m.span():
        clk.tick(user=1.0, wall=1.0)
    assert m.end()["cpu_core_seconds_per_audio_s"] is None


def test_a_meter_with_no_spans_reports_null_rates(cm) -> None:
    rec = cm.build_record(user_s=0, system_s=0, span_wall_s=0, bracket_wall_s=1,
                          audio_s=0, spans=0, energy={})
    assert rec["mean_cores_busy"] is None
    assert rec["cpu_core_seconds_per_audio_s"] is None


def test_end_before_begin_is_an_error(cm) -> None:
    with pytest.raises(RuntimeError):
        cm.CostMeter().end()


def test_the_real_cpu_clock_is_monotonic_and_nonnegative(cm) -> None:
    u0, s0, _, _ = cm.os_cpu_times()
    sum(i * i for i in range(20000))
    u1, s1, _, _ = cm.os_cpu_times()
    assert u1 >= u0 >= 0 and s1 >= s0 >= 0


def test_cpu_burned_in_a_worker_thread_is_billed_to_the_span(cm) -> None:
    """The "threads included" claim in CPU_METHOD, checked on the real clock.

    Decoder thread pools (CTranslate2, ONNX Runtime) run off the main thread; a meter
    that only saw the calling thread would under-count them by the pool size. The worker
    burns 0.2 s of its *own* CPU time (`time.thread_time`), so the bound does not depend
    on how busy the machine is.
    """
    import threading
    import time

    def burn() -> None:
        t0 = time.thread_time()
        while time.thread_time() - t0 < 0.2:
            sum(i * i for i in range(1000))

    m = cm.CostMeter()
    m.begin()
    with m.span(audio_s=1.0):
        worker = threading.Thread(target=burn)
        worker.start()
        worker.join()
    rec = m.end()
    assert rec["cpu_core_seconds"] >= 0.15, rec


# --- artifact schema ------------------------------------------------------------------

def test_record_has_the_documented_fields_and_is_json_serialisable(cm) -> None:
    clk = FakeClock()
    probe = FakeProbe({"method": "x", "energy_joules": None, "reason": "r"})
    m = cm.CostMeter([probe], cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    with m.span(audio_s=1.0):
        clk.tick(user=1.0, wall=1.0)
    rec = m.end()
    assert set(rec) == {
        "schema_version", "method", "cpu_user_s", "cpu_system_s", "cpu_children_user_s",
        "cpu_children_system_s", "cpu_core_seconds", "span_wall_s", "bracket_wall_s",
        "audio_s", "n_spans", "cpu_core_seconds_per_audio_s", "mean_cores_busy", "rtf",
        "spans", "span_summary", "energy",
    }
    assert rec["schema_version"] == cm.SCHEMA_VERSION
    assert rec["method"] == cm.CPU_METHOD
    assert "threads included" in rec["method"]
    assert "child processes included only once exited and waited for" in rec["method"]
    assert rec["energy"]["fake"]["energy_joules"] is None
    assert probe.calls == ["begin", "end"]
    json.dumps(rec)  # the artifact must serialise


# --- RAPL ----------------------------------------------------------------------------

def _rapl(root: Path, name: str, start: int | None, max_range: int | None = 1000) -> Path:
    if os.name == "nt":
        # RAPL zones are named like `intel-rapl:0`, and NTFS refuses `:` in a file name
        # (WinError 267). RAPL is a Linux sysfs interface, so there is nothing to fake here.
        pytest.skip("RAPL sysfs names contain ':', which Windows cannot create; RAPL is Linux-only")
    d = root / name
    d.mkdir(parents=True)
    if start is not None:
        (d / "energy_uj").write_text(f"{start}\n", encoding="utf-8")
    if max_range is not None:
        (d / "max_energy_range_uj").write_text(f"{max_range}\n", encoding="utf-8")
    return d


def _set(d: Path, value: int) -> None:
    (d / "energy_uj").write_text(f"{value}\n", encoding="utf-8")


def test_rapl_delta_in_joules(cm, tmp_path) -> None:
    d = _rapl(tmp_path, "intel-rapl:0", 1_000_000)
    p = cm.RaplProbe(tmp_path)
    p.begin()
    _set(d, 3_500_000)
    out = p.end()
    assert out["energy_joules"] == pytest.approx(2.5)
    assert out["reason"] is None and out["wrapped"] is False
    assert out["available"] is True
    assert out["source"].endswith("/intel-rapl:N/energy_uj")
    assert out["uncertainty"]["quantisation_joules"] == pytest.approx(2e-6)
    assert any("not per-process" in n for n in out["uncertainty"]["notes"])


def test_rapl_wraparound_is_corrected(cm) -> None:
    assert cm.rapl_delta_uj(900, 100, 1000) == (200, True)
    assert cm.rapl_delta_uj(100, 900, 1000) == (800, False)


def test_rapl_wraparound_without_a_range_is_null(cm, tmp_path) -> None:
    d = _rapl(tmp_path, "intel-rapl:0", 900, max_range=None)
    p = cm.RaplProbe(tmp_path)
    p.begin()
    _set(d, 100)
    out = p.end()
    assert out["energy_joules"] is None
    assert "wrapped" in out["reason"]


def test_rapl_wrap_through_the_probe(cm, tmp_path) -> None:
    d = _rapl(tmp_path, "intel-rapl:0", 900_000, max_range=1_000_000)
    p = cm.RaplProbe(tmp_path)
    p.begin()
    _set(d, 100_000)
    out = p.end()
    assert out["energy_joules"] == pytest.approx(0.2)
    assert out["wrapped"] is True


def test_rapl_sums_packages_but_not_subdomains_or_the_mmio_mirror(cm, tmp_path) -> None:
    a = _rapl(tmp_path, "intel-rapl:0", 0)
    b = _rapl(tmp_path, "intel-rapl:1", 0)
    sub = _rapl(tmp_path, "intel-rapl:0:0", 0)  # core domain, nested inside package 0
    mmio = _rapl(tmp_path, "intel-rapl-mmio:0", 0)  # duplicate of package 0
    p = cm.RaplProbe(tmp_path)
    p.begin()
    for d, v in ((a, 1_000_000), (b, 2_000_000), (sub, 900_000), (mmio, 1_000_000)):
        _set(d, v)
    out = p.end()
    assert out["energy_joules"] == pytest.approx(3.0)
    assert out["domains"] == ["intel-rapl:0", "intel-rapl:1"]


def test_rapl_absent_is_null_with_a_reason_never_zero(cm, tmp_path) -> None:
    p = cm.RaplProbe(tmp_path / "does-not-exist")
    p.begin()
    out = p.end()
    assert out["energy_joules"] is None
    assert "intel-rapl" in out["reason"]


def test_rapl_permission_error_is_null_with_a_reason(cm, tmp_path, monkeypatch) -> None:
    _rapl(tmp_path, "intel-rapl:0", 5)
    real = Path.read_text

    def deny(self, *a, **k):
        if self.name == "energy_uj":
            raise PermissionError(13, "Permission denied")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", deny)
    p = cm.RaplProbe(tmp_path)
    p.begin()
    out = p.end()
    assert out["energy_joules"] is None
    assert "permission denied" in out["reason"]


def test_rapl_unreadable_package_voids_the_whole_probe(cm, tmp_path) -> None:
    """A two-socket host with one unreadable socket must not report the other's energy."""
    _rapl(tmp_path, "intel-rapl:0", 0)
    _rapl(tmp_path, "intel-rapl:1", None)  # no energy_uj
    p = cm.RaplProbe(tmp_path)
    p.begin()
    assert p.end()["energy_joules"] is None


def test_rapl_counter_that_did_not_advance_is_null_not_zero(cm, tmp_path) -> None:
    _rapl(tmp_path, "intel-rapl:0", 42)
    p = cm.RaplProbe(tmp_path)
    p.begin()
    out = p.end()
    assert out["energy_joules"] is None and "did not advance" in out["reason"]


def test_rapl_end_without_begin_is_null(cm, tmp_path) -> None:
    assert cm.RaplProbe(tmp_path).end()["energy_joules"] is None


# --- battery -------------------------------------------------------------------------

def _bat(root: Path, name: str = "BAT0", *, energy: int = 50_000_000,
         status: str = "Discharging", kind: str = "Battery", with_energy: bool = True) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "type").write_text(kind + "\n", encoding="utf-8")
    (d / "status").write_text(status + "\n", encoding="utf-8")
    if with_energy:
        (d / "energy_now").write_text(f"{energy}\n", encoding="utf-8")
    return d


def test_battery_discharge_in_joules(cm, tmp_path) -> None:
    d = _bat(tmp_path, energy=50_000_000)
    p = cm.BatteryProbe(tmp_path)
    p.begin()
    (d / "energy_now").write_text("49999000\n", encoding="utf-8")
    out = p.end()
    assert out["energy_joules"] == pytest.approx(1000 * 3.6e-3)  # 1000 uWh = 3.6 J
    assert out["batteries"]["BAT0"]["energy_now_uwh"] == [50_000_000, 49_999_000]
    assert out["available"] is True and out["basis"] == ["energy_now"]
    assert out["uncertainty"]["quantisation_joules"] == pytest.approx(2 * 3.6e-3)


@pytest.mark.parametrize("status", ["Charging", "Full", "Not charging"])
def test_battery_not_discharging_is_null(cm, tmp_path, status) -> None:
    d = _bat(tmp_path)
    p = cm.BatteryProbe(tmp_path)
    p.begin()
    (d / "status").write_text(status + "\n", encoding="utf-8")
    (d / "energy_now").write_text("49000000\n", encoding="utf-8")
    out = p.end()
    assert out["energy_joules"] is None and "not discharging" in out["reason"]


def test_battery_gauge_that_did_not_move_is_null(cm, tmp_path) -> None:
    _bat(tmp_path)
    p = cm.BatteryProbe(tmp_path)
    p.begin()
    out = p.end()
    assert out["energy_joules"] is None and "did not drop" in out["reason"]


def test_battery_absent_and_charge_only_are_null(cm, tmp_path) -> None:
    empty = tmp_path / "none"
    empty.mkdir()
    p = cm.BatteryProbe(empty)
    p.begin()
    assert p.end()["energy_joules"] is None
    only_charge = tmp_path / "chg"
    only_charge.mkdir()
    _bat(only_charge, with_energy=False)
    q = cm.BatteryProbe(only_charge)
    q.begin()
    out = q.end()
    assert out["energy_joules"] is None and "charge_now" in out["reason"]


def test_a_mains_supply_is_not_a_battery(cm, tmp_path) -> None:
    _bat(tmp_path, name="BAT0", kind="Mains")
    p = cm.BatteryProbe(tmp_path)
    p.begin()
    assert "no system battery" in p.end()["reason"]


# --- platforms -----------------------------------------------------------------------

def test_linux_gets_rapl_and_battery(cm, tmp_path) -> None:
    probes = cm.default_probes("linux", rapl_root=tmp_path, battery_root=tmp_path)
    assert [p.name for p in probes] == ["rapl", "battery"]


@pytest.mark.parametrize("plat", ["darwin", "win32", "freebsd14"])
def test_other_platforms_record_unavailable_not_zero(cm, plat) -> None:
    (probe,) = cm.default_probes(plat)
    probe.begin()
    out = probe.end()
    assert out["energy_joules"] is None
    assert out["reason"].startswith("unavailable")


def test_a_full_record_with_unavailable_energy(cm) -> None:
    clk = FakeClock()
    m = cm.CostMeter(cm.default_probes("darwin"), cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    with m.span(audio_s=2.0):
        clk.tick(user=1.0, wall=1.0)
    rec = m.end()
    assert rec["cpu_core_seconds"] == 1.0
    assert rec["energy"]["energy"]["energy_joules"] is None


# --- schema v2: children, per-decode spans, RTF, normalisation ------------------------

class FakeClock4(FakeClock):
    """A clock that also reports exited-child CPU time, as `os.times()` does."""

    def __init__(self) -> None:
        super().__init__()
        self.cu = 0.0
        self.cs = 0.0

    def cpu4(self) -> tuple[float, float, float, float]:
        return self.user, self.system, self.cu, self.cs


def test_exited_child_cpu_time_is_counted(cm) -> None:
    clk = FakeClock4()
    m = cm.CostMeter(cpu_times=clk.cpu4, wall=clk.wall)
    m.begin()
    with m.span(audio_s=4.0):
        clk.tick(user=1.0, system=0.5, wall=1.0)
        clk.cu += 2.0
        clk.cs += 0.5
    rec = m.end()
    assert rec["cpu_children_user_s"] == 2.0 and rec["cpu_children_system_s"] == 0.5
    assert rec["cpu_core_seconds"] == 4.0
    assert rec["spans"][0]["cpu_core_seconds"] == 4.0
    assert cm.validate_record(rec) == []


def test_the_real_clock_reports_children_fields(cm) -> None:
    t = cm.os_cpu_times()
    assert len(t) == 4 and all(v >= 0 for v in t)


def test_each_decode_is_recorded_with_its_rtf(cm) -> None:
    clk = FakeClock()
    m = cm.CostMeter(cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    for core, wall, audio in ((2.0, 0.5, 5.0), (4.0, 1.0, 5.0), (3.0, 1.5, 10.0)):
        with m.span(audio_s=audio):
            clk.tick(user=core, wall=wall)
    rec = m.end()
    assert [s["index"] for s in rec["spans"]] == [0, 1, 2]
    assert [s["rtf"] for s in rec["spans"]] == [0.1, 0.2, 0.15]
    assert [s["cpu_core_seconds_per_audio_s"] for s in rec["spans"]] == [0.4, 0.8, 0.3]
    assert rec["rtf"] == pytest.approx(3.0 / 20.0)
    summ = rec["span_summary"]["cpu_core_seconds"]
    assert summ["n"] == 3 and summ["median"] == 3.0 and summ["min"] == 2.0 and summ["max"] == 4.0
    assert summ["stdev"] == pytest.approx(1.0)


def test_the_load_phase_has_no_rtf_and_no_spread(cm) -> None:
    clk = FakeClock()
    m = cm.CostMeter(cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    with m.span():
        clk.tick(user=1.0, wall=2.0)
    rec = m.end()
    assert rec["rtf"] is None and rec["spans"][0]["rtf"] is None
    assert rec["span_summary"]["rtf"]["n"] == 0
    assert rec["span_summary"]["wall_s"]["stdev"] is None  # one sample has no spread


def test_summarise_skips_not_applicable_and_handles_empty(cm) -> None:
    assert cm.summarise([])["mean"] is None
    out = cm.summarise([None, 1.0, 3.0])
    assert out["n"] == 2 and out["mean"] == 2.0


def test_energy_is_normalised_per_audio_second_and_per_utterance(cm) -> None:
    probe = FakeProbe({"source": "s", "method": "m", "available": True, "energy_joules": 30.0,
                       "reason": None, "uncertainty": cm.uncertainty(1e-6)})
    clk = FakeClock()
    m = cm.CostMeter([probe], cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    for _ in range(3):
        with m.span(audio_s=5.0):
            clk.tick(user=1.0, wall=1.0)
    e = m.end()["energy"]["fake"]
    assert e["joules_per_audio_s"] == 2.0  # 30 J over 15 s of audio
    assert e["joules_per_utterance"] == 10.0


def test_unreadable_energy_normalises_to_null_not_zero(cm) -> None:
    nulls = {"joules_per_audio_s": None, "joules_per_utterance": None}
    assert cm.normalise_energy(None, 10.0, 3) == nulls
    assert cm.normalise_energy(5.0, 0.0, 0) == nulls
    assert cm.per_unit(0.0, 2.0) == 0.0  # a measured zero stays a zero


# --- counter traces ---------------------------------------------------------------------

def test_a_densely_sampled_trace_survives_several_wraps(cm) -> None:
    # range 1000: 900 -> 100 (+200) -> 600 (+500) -> 50 (+450) -> 980 (+930)
    assert cm.counter_trace_delta([900, 100, 600, 50, 980], 1000) == (2080, 2)


def test_a_trace_needs_two_samples_and_a_range_to_wrap(cm) -> None:
    assert cm.counter_trace_delta([5], 1000) == (None, 0)
    assert cm.counter_trace_delta([], 1000) == (None, 0)
    assert cm.counter_trace_delta([10, 20, 5], None)[0] is None
    assert cm.counter_trace_delta([10, 20, 30], None) == (20, 0)


# --- battery: any supply name, charge-only gauges, peripherals ---------------------------

def test_battery_discharge_arithmetic(cm) -> None:
    assert cm.battery_discharge_uwh((1000, None, None), (900, None, None)) == (100.0, None, "energy_now")
    uwh, why, basis = cm.battery_discharge_uwh((None, 5000, 12_000_000), (None, 4000, 11_000_000))
    assert basis == "charge_now*voltage_now" and why is None
    assert uwh == pytest.approx(1000 * 11.5)  # 1000 uAh at a mean 11.5 V
    assert cm.battery_discharge_uwh((None, 5000, None), (None, 4000, None))[0] is None


def test_a_charge_only_gauge_is_converted_with_a_stated_approximation(cm, tmp_path) -> None:
    d = _bat(tmp_path, name="CMB0", with_energy=False)  # not named BAT*: still a battery
    (d / "charge_now").write_text("5000000\n", encoding="utf-8")
    (d / "voltage_now").write_text("12000000\n", encoding="utf-8")
    p = cm.BatteryProbe(tmp_path)
    p.begin()
    (d / "charge_now").write_text("4999000\n", encoding="utf-8")
    (d / "voltage_now").write_text("11800000\n", encoding="utf-8")
    out = p.end()
    assert out["available"] is True and out["basis"] == ["charge_now*voltage_now"]
    assert out["energy_joules"] == pytest.approx(1000 * 11.9 * 3.6e-3)
    assert any("approximation" in n for n in out["uncertainty"]["notes"])


def test_a_peripheral_battery_is_not_the_laptops(cm, tmp_path) -> None:
    d = _bat(tmp_path, name="hidpp_battery_0")
    (d / "scope").write_text("Device\n", encoding="utf-8")
    p = cm.BatteryProbe(tmp_path)
    p.begin()
    out = p.end()
    assert out["energy_joules"] is None and "no system battery" in out["reason"]


# --- macOS powermetrics (manual path, synthetic logs) ----------------------------------

_PM_APPLE = """Machine model: Mac14,2
*** Sampled system activity (Tue Oct 20 10:00:00 2026 +0200) (100.00ms elapsed) ***
**** Processor usage ****
CPU Power: 2000 mW
GPU Power: 10 mW
Combined Power (CPU + GPU + ANE): 2010 mW
*** Sampled system activity (Tue Oct 20 10:00:00 2026 +0200) (200.00ms elapsed) ***
CPU Power: 1000 mW
"""

_PM_INTEL = """*** Sampled system activity (Tue Oct 20 10:00:00 2026 +0200) (500.0ms elapsed) ***
Intel energy model derived package power (CPUs+GT+SA): 4.00W
"""


def test_powermetrics_apple_silicon_log_is_integrated(cm) -> None:
    out = cm.powermetrics_energy(_PM_APPLE)
    assert out["energy_joules"] == pytest.approx(2.0 * 0.1 + 1.0 * 0.2)  # GPU line ignored
    assert out["available"] is True and out["samples"] == 2
    full = {**out, **cm.normalise_energy(out["energy_joules"], 1.0, 1)}
    assert cm.validate_reading("pm", full) == []


def test_powermetrics_intel_log_is_integrated(cm) -> None:
    assert cm.powermetrics_energy(_PM_INTEL)["energy_joules"] == pytest.approx(2.0)


@pytest.mark.parametrize("text, reason", [
    ("", "no '*** Sampled"),
    ("*** Sampled system activity (x) (100.0ms elapsed) ***\nGPU Power: 3 mW\n", "no CPU power"),
])
def test_powermetrics_without_power_is_null(cm, text, reason) -> None:
    out = cm.powermetrics_energy(text)
    assert out["energy_joules"] is None and reason in out["reason"]


def test_macos_reason_points_at_the_manual_path(cm) -> None:
    (probe,) = cm.default_probes("darwin")
    out = probe.end()
    assert "powermetrics" in out["reason"] and out["available"] is False


# --- validation: the record cannot contradict its own contract -------------------------

def _valid(cm) -> dict:
    clk = FakeClock()
    m = cm.CostMeter(cm.default_probes("win32"), cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    with m.span(audio_s=2.0):
        clk.tick(user=1.0, wall=1.0)
    rec = m.end()
    assert cm.validate_record(rec) == []
    return rec


def test_every_probe_output_validates(cm, tmp_path) -> None:
    """Every reading a real probe can produce -- null or not -- satisfies the contract."""
    d = _rapl(tmp_path / "pc", "intel-rapl:0", 0)
    b = _bat(tmp_path / "ps")
    probes = [cm.RaplProbe(tmp_path / "pc"), cm.BatteryProbe(tmp_path / "ps"),
              cm.RaplProbe(tmp_path / "absent"), *cm.default_probes("darwin")]
    probes[2].name = "rapl_absent"
    clk = FakeClock()
    m = cm.CostMeter(probes, cpu_times=clk.cpu, wall=clk.wall)
    m.begin()
    with m.span(audio_s=1.0):
        clk.tick(user=1.0, wall=1.0)
    _set(d, 1_000_000)
    (b / "energy_now").write_text("49990000\n", encoding="utf-8")
    rec = m.end()
    assert cm.validate_record(rec) == []
    assert rec["energy"]["rapl"]["available"] and rec["energy"]["battery"]["available"]
    assert rec["energy"]["rapl_absent"]["available"] is False
    json.dumps(rec)


@pytest.mark.parametrize("mutate, needle", [
    (lambda r: r["energy"]["energy"].update(energy_joules=0.0), "never a number"),
    (lambda r: r["energy"]["energy"].update(available=True, reason=None, energy_joules=0.0), "> 0"),
    (lambda r: r["energy"]["energy"].update(source=""), "source"),
    (lambda r: r["energy"]["energy"].pop("uncertainty"), "uncertainty"),
    (lambda r: r["energy"]["energy"].update(joules_per_audio_s=1.0), "must be null"),
    (lambda r: r.update(schema_version="yazses.bench.cost/1"), "schema_version"),
    (lambda r: r.update(cpu_core_seconds=99.0), "sum of its"),
    (lambda r: r.update(cpu_user_s=-1.0), "cpu_user_s"),
    (lambda r: r.update(n_spans=5), "n_spans"),
    (lambda r: r.update(audio_s=0.0), "no audio"),
    (lambda r: r.update(rtf=float("nan")), "rtf"),
])
def test_validation_rejects_a_record_that_lies(cm, mutate, needle) -> None:
    rec = _valid(cm)
    mutate(rec)
    errs = cm.validate_record(rec)
    assert any(needle in e for e in errs), errs
    with pytest.raises(ValueError):
        cm.check_record(rec)


def test_validation_is_not_vacuous_on_a_non_record(cm) -> None:
    assert cm.validate_record(None) and cm.validate_record({})


# --- the smoke driver --------------------------------------------------------------------

@pytest.fixture
def smoke(cm, monkeypatch):
    monkeypatch.syspath_prepend(str(BENCH))
    spec = importlib.util.spec_from_file_location("cost_smoke", BENCH / "cost_smoke.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    # Hermetic: no host /sys, no psutil (the benchmark group is not in a plain sync).
    monkeypatch.setattr(module, "default_probes", lambda: cm.default_probes("win32"))
    monkeypatch.setattr(module, "provenance", lambda ts: {"timestamp": ts})
    return module


def test_the_smoke_driver_writes_a_valid_fake_run(cm, smoke, tmp_path) -> None:
    out = tmp_path / "smoke.json"
    argv = ["--out", str(out), "--synthetic", "0.5", "--repeats", "2", "--fake-decoder"]
    assert smoke.main(argv) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["decoder"]["kind"] == "fake"
    assert data["cost_schema_version"] == cm.SCHEMA_VERSION
    assert cm.validate_record(data["load_cost"]) == []
    assert cm.validate_record(data["decode_cost"]) == []
    assert data["decode_cost"]["n_spans"] == 2 and data["decode_cost"]["audio_s"] == 1.0
    assert data["load_cost"]["rtf"] is None


def test_the_smoke_driver_falls_back_to_fake_and_says_why(smoke, monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "yazses.stt.faster_whisper", None)  # import -> ImportError
    monkeypatch.setenv("HF_HUB_OFFLINE", "0")
    meter = smoke.CostMeter()
    meter.begin()
    _, info = smoke._load_engine("tiny.en", False, meter)
    assert info["kind"] == "fake" and "could not be loaded offline" in info["why"]
    assert os.environ["HF_HUB_OFFLINE"] == "1"  # cache only: the driver never downloads
