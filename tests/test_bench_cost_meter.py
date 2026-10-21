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
    u0, s0 = cm.os_cpu_times()
    sum(i * i for i in range(20000))
    u1, s1 = cm.os_cpu_times()
    assert u1 >= u0 >= 0 and s1 >= s0 >= 0


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
        "method", "cpu_user_s", "cpu_system_s", "cpu_core_seconds", "span_wall_s",
        "bracket_wall_s", "audio_s", "n_spans", "cpu_core_seconds_per_audio_s",
        "mean_cores_busy", "energy",
    }
    assert rec["method"] == cm.CPU_METHOD
    assert "child processes excluded" in rec["method"] and "threads included" in rec["method"]
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
    assert out["batteries"]["BAT0"]["energy_now_start_uwh"] == 50_000_000


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
    assert "no battery" in p.end()["reason"]


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
