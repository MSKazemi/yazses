"""CPU core-seconds and (optional) energy for a benchmark phase (PAPER2-ENERGY-001, #506).

Wall-clock latency and RTF hide what a fast decode costs across cores: a decode that
finishes in a second on eight busy threads is eight core-seconds of heat and battery.
This module is the *measuring* half of that question; it records numbers and states the
conditions they were taken under, and nothing in it is a result. Library only -- imported
by `bench_latency.py` and `cost_smoke.py`, never imported by the daemon.

Every phase record carries ``schema_version`` (`SCHEMA_VERSION`) and is checked by
`validate_record` before a benchmark writes it, so an artifact that contradicts its own
contract (an energy figure with no source, a ``0`` standing in for "unreadable") fails at
measurement time instead of reaching a table.

**Core-seconds.** ``os.times()`` user + system CPU time of *this process*, plus the
``children_user`` / ``children_system`` fields, read before and after each span.
Properties that a reader has to know, and that are written into every record's
``method`` field:

* Threads are included (the interpreter's, CTranslate2's and ONNX Runtime's pools all live
  in this process, and the kernel bills a thread's time to its process).
* Child processes are included **once they have exited and been waited for** -- that is
  what ``os.times()``'s ``children_*`` fields count. A child still running at the end of a
  span is not, and on Windows the ``children_*`` fields are always 0. None of the
  benchmarked engines spawns one, which is a fact about today's engines, not a guarantee.
* It is CPU *time*, not CPU *work*: it does not normalise for clock frequency, SMT or
  turbo, so core-seconds from two hosts are not comparable without calibration.

**Per-decode records.** Each `CostMeter.span` is one decode; the record lists them under
``spans`` (core-seconds, wall time, real-time factor) and summarises their spread under
``span_summary``, so variation is reported rather than averaged away.

**Energy** is optional. Every reading carries ``source`` (what was read), ``available``,
``energy_joules`` (``float`` or ``None`` -- never ``0`` when unreadable, which would read
as "this decode was free"), ``reason`` (why it is ``None``) and ``uncertainty`` (a
numeric quantisation floor where one is known, plus the error terms that cannot be
bounded here).

* Linux RAPL (``/sys/class/powercap/intel-rapl:N/energy_uj``): CPU *package* energy, a
  hardware counter, but not wall power (no display, DRAM on some parts, SSD, fans, PSU
  loss) and not per-process: it counts everything running on the package, so an idle-box
  baseline is the reader's job. Often readable by root only. The counter wraps at
  ``max_energy_range_uj``; one wrap is corrected, and a run long enough to wrap twice
  cannot be detected, which is why the range is recorded.
* Linux battery (``/sys/class/power_supply/*`` of ``type`` Battery, excluding peripheral
  batteries whose ``scope`` is Device): discharge between two readings, from
  ``energy_now`` or, when a gauge only reports charge, ``charge_now`` x mean
  ``voltage_now``. Coarse -- the gauge moves in steps far larger than one short decode --
  and valid only while the battery reports ``Discharging`` at both ends.
* macOS: ``powermetrics`` needs root, so the harness never runs it. It is a documented
  *manual* path: run it yourself beside the benchmark and feed the log to
  `powermetrics_energy`. Unverified on a real Mac -- tested on synthetic text only.
* Windows: ``unavailable``. Nothing here reads its counters, because there is no machine
  in CI that could prove such a reader right.

The sources sit behind the `EnergyProbe` Protocol so the arithmetic is tested against
fakes, with no hardware.
"""
from __future__ import annotations

import math
import os
import re
import statistics
import sys
import time
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

#: Bump on any change to a field's name, unit or meaning. Version 1 (unversioned, before
#: #506's follow-up) had no ``schema_version``, no per-span list, no RTF, no child-process
#: time and no ``source`` / ``available`` / ``uncertainty`` on an energy reading.
SCHEMA_VERSION = "yazses.bench.cost/2"

CPU_METHOD = (
    "os.times() user+system of this process: threads included; child processes included "
    "only once exited and waited for (children_*; always 0 on Windows); CPU time, not "
    "normalised for frequency or SMT"
)

_UWH_TO_J = 3600.0 / 1e6  # 1 uWh = 3.6e-3 J
_UJ_TO_J = 1e-6

CpuTimes = tuple[float, float] | tuple[float, float, float, float]


def os_cpu_times() -> tuple[float, float, float, float]:
    """``(user_s, system_s, children_user_s, children_system_s)`` for this process.

    Portable: Linux, macOS and Windows (where the two ``children`` fields are 0).
    """
    t = os.times()
    return t.user, t.system, t.children_user, t.children_system


def _four(t: CpuTimes) -> tuple[float, float, float, float]:
    """Accept a 2-tuple (no child accounting) or a 4-tuple clock reading."""
    if len(t) == 2:
        return t[0], t[1], 0.0, 0.0
    return t[0], t[1], t[2], t[3]  # type: ignore[misc]


class EnergyProbe(Protocol):
    """One energy source: bracket a phase with `begin()` / `end()`.

    `end()` returns a JSON-able reading that always carries ``source``, ``method``,
    ``available``, ``energy_joules`` (``float`` or ``None``), ``reason`` (``None`` when
    the value is present, a string when it is not) and ``uncertainty``. It never raises:
    a probe that cannot read must say so, not abort a multi-hour benchmark.
    """

    name: str

    def begin(self) -> None: ...

    def end(self) -> dict: ...


def uncertainty(quantisation_joules: float | None, *notes: str) -> dict:
    """An uncertainty block: a numeric floor where one is known, and the rest in words.

    ``quantisation_joules`` is the reading's resolution (the error from the counter
    being an integer), a *lower* bound on the error; ``None`` when even that is unknown.
    The notes name the error terms that cannot be bounded from the reading itself.
    """
    return {"quantisation_joules": quantisation_joules, "notes": list(notes)}


def _null(source: str, method: str, reason: str, *notes: str, **extra: object) -> dict:
    return {
        "source": source, "method": method, "available": False, "energy_joules": None,
        "reason": reason, "uncertainty": uncertainty(None, *notes), **extra,
    }


def _read_int(path: Path) -> int:
    return int(path.read_text(encoding="utf-8").strip())


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


# --- pure arithmetic ---------------------------------------------------------------------

def rapl_delta_uj(start: int, end: int, max_range: int | None) -> tuple[int | None, bool]:
    """Energy between two counter readings, correcting one wraparound.

    Returns ``(delta_uj, wrapped)``; ``delta_uj`` is ``None`` when the counter went
    backwards and the range needed to correct it is unknown.
    """
    if end >= start:
        return end - start, False
    if max_range is None or max_range <= 0:
        return None, True
    return end + max_range - start, True


def counter_trace_delta(trace: Sequence[int], max_range: int | None) -> tuple[int | None, int]:
    """Total advance of a wrapping counter sampled at several points.

    A phase sampled more often than the counter's wrap period can wrap any number of
    times and still be measured exactly; each step is corrected with `rapl_delta_uj`.
    Returns ``(delta, wraps)``; ``delta`` is ``None`` if any step went backwards with no
    known range. Fewer than two samples is a delta of ``None``: nothing was bracketed.
    """
    if len(trace) < 2:
        return None, 0
    total = 0
    wraps = 0
    for a, b in zip(trace, trace[1:], strict=False):
        d, w = rapl_delta_uj(a, b, max_range)
        if d is None:
            return None, wraps + 1
        total += d
        wraps += int(w)
    return total, wraps


def battery_discharge_uwh(
    start: tuple[int | None, int | None, int | None],
    end: tuple[int | None, int | None, int | None],
) -> tuple[float | None, str | None, str]:
    """Discharge in uWh between two ``(energy_now_uwh, charge_now_uah, voltage_now_uv)``.

    Prefers ``energy_now``. Falls back to ``charge_now`` x the mean of the two
    ``voltage_now`` readings, an approximation (voltage sags under load and the mean of
    two instants is not the integral). Returns ``(uwh, reason, basis)``; ``uwh`` is
    ``None`` with a reason when neither basis is readable at both ends.
    """
    e0, c0, v0 = start
    e1, c1, v1 = end
    if e0 is not None and e1 is not None:
        return float(e0 - e1), None, "energy_now"
    if c0 is not None and c1 is not None and v0 is not None and v1 is not None:
        v_mean = (v0 + v1) / 2.0
        return (c0 - c1) * v_mean / 1e6, None, "charge_now*voltage_now"
    return None, "neither energy_now nor charge_now with voltage_now is readable at both ends", "none"


def per_unit(value: float | None, denominator: float) -> float | None:
    """``value / denominator``, or ``None`` when either is not applicable.

    A rate over zero audio, or of an unreadable quantity, is "not applicable", not 0.
    """
    if value is None or denominator <= 0:
        return None
    return value / denominator


def normalise_energy(joules: float | None, audio_s: float, n_utterances: int) -> dict:
    """Joules per decoded audio-second and per utterance, ``None`` where meaningless."""
    jps = per_unit(joules, audio_s)
    jpu = per_unit(joules, n_utterances)
    return {
        "joules_per_audio_s": None if jps is None else round(jps, 6),
        "joules_per_utterance": None if jpu is None else round(jpu, 6),
    }


def summarise(values: Iterable[float | None]) -> dict:
    """Spread of a per-decode quantity. ``None`` entries (not applicable) are skipped.

    ``stdev`` is the sample standard deviation, ``None`` below two values -- one decode
    has no spread, and 0 would claim it had been measured as perfectly stable.
    """
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return {"n": 0, "mean": None, "stdev": None, "min": None, "median": None, "max": None}
    return {
        "n": len(xs),
        "mean": round(statistics.fmean(xs), 6),
        "stdev": round(statistics.stdev(xs), 6) if len(xs) >= 2 else None,
        "min": round(xs[0], 6),
        "median": round(statistics.median(xs), 6),
        "max": round(xs[-1], 6),
    }


# --- probes ------------------------------------------------------------------------------

class RaplProbe:
    """Linux RAPL package energy. Package domains only (``intel-rapl:N``).

    Sub-domains (``intel-rapl:N:M``: cores, uncore, DRAM) are nested inside the package
    figure on the parts that expose both, and the ``intel-rapl-mmio`` mirror duplicates it,
    so summing them would double-count. If any package cannot be read the whole probe is
    ``None``: a partial sum of a two-socket machine is an under-count presented as a value.
    """

    name = "rapl"
    METHOD = "linux_rapl_package_energy_uj"
    _DOMAIN = re.compile(r"^intel-rapl:\d+$")
    _NOTES = (
        "CPU package only: excludes display, SSD, fans and PSU loss",
        "not per-process: counts every task on the package; idle baseline not subtracted",
        "hardware update granularity ~1 ms on Intel parts (Intel SDM vol. 3B, RAPL); "
        "unverified on other vendors",
        "a second wrap within one bracket is undetectable",
    )

    def __init__(self, root: Path = Path("/sys/class/powercap")) -> None:
        self._root = root
        self._start: dict[Path, int] | None = None
        self._failure: str | None = None

    @property
    def source(self) -> str:
        return f"{self._root.as_posix()}/intel-rapl:N/energy_uj"

    def _domains(self) -> list[Path]:
        try:
            return sorted(p for p in self._root.iterdir() if self._DOMAIN.match(p.name))
        except OSError:
            return []

    def _snapshot(self) -> tuple[dict[Path, int] | None, str | None]:
        domains = self._domains()
        if not domains:
            return None, f"no intel-rapl package domain under {self._root.as_posix()} (not an Intel/AMD-RAPL host, or powercap not exposed)"
        out: dict[Path, int] = {}
        for d in domains:
            f = d / "energy_uj"
            try:
                out[d] = _read_int(f)
            except PermissionError:
                return None, f"permission denied reading {f.name} (readable by root only on many kernels; the harness does not escalate)"
            except (OSError, ValueError) as exc:
                return None, f"could not read {f.name}: {type(exc).__name__}"
        return out, None

    def begin(self) -> None:
        self._start, self._failure = self._snapshot()

    def end(self) -> dict:
        if self._start is None:
            return _null(self.source, self.METHOD, self._failure or "begin() was not called", *self._NOTES)
        stop, failure = self._snapshot()
        if stop is None:
            return _null(self.source, self.METHOD, failure or "end read failed", *self._NOTES)
        total_uj = 0
        wrapped = False
        ranges: dict[str, int | None] = {}
        for d, s in self._start.items():
            try:
                max_range: int | None = _read_int(d / "max_energy_range_uj")
            except (OSError, ValueError):
                max_range = None
            e = stop.get(d)
            if e is None:
                return _null(self.source, self.METHOD, f"{d.name} disappeared during the run", *self._NOTES)
            delta, w = rapl_delta_uj(s, e, max_range)
            if delta is None:
                return _null(self.source, self.METHOD,
                             f"{d.name} counter wrapped and max_energy_range_uj is unreadable", *self._NOTES)
            total_uj += delta
            wrapped = wrapped or w
            ranges[d.name] = max_range
        if total_uj == 0:
            return _null(self.source, self.METHOD,
                         "counter did not advance (stuck, or interval shorter than its resolution)", *self._NOTES)
        return {
            "source": self.source,
            "method": self.METHOD,
            "available": True,
            "energy_joules": total_uj * _UJ_TO_J,
            "reason": None,
            # Two integer-microjoule reads per domain: +/- 1 uJ at each end.
            "uncertainty": uncertainty(2 * len(self._start) * _UJ_TO_J, *self._NOTES),
            "domains": [d.name for d in self._start],
            "wrapped": wrapped,
            "max_energy_range_uj": ranges,
            "scope": "CPU package only; not wall power; not per-process",
        }


_Gauge = tuple[int | None, int | None, int | None]


def _opt_int(path: Path) -> int | None:
    try:
        return _read_int(path)
    except FileNotFoundError:
        return None


class BatteryProbe:
    """Linux battery discharge between two readings. Coarse by nature."""

    name = "battery"
    METHOD = "linux_battery_discharge"
    _NOTES = (
        "whole-system draw, not the decoder's: everything running is billed",
        "fuel-gauge step is device-specific and usually far coarser than the sysfs unit",
    )

    def __init__(self, root: Path = Path("/sys/class/power_supply")) -> None:
        self._root = root
        self._start: dict[Path, tuple[_Gauge, str]] | None = None
        self._failure: str | None = None

    @property
    def source(self) -> str:
        return f"{self._root.as_posix()}/*/{{energy_now,charge_now,voltage_now}}"

    def _batteries(self) -> list[Path]:
        try:
            cands = sorted(self._root.iterdir())
        except OSError:
            return []
        out = []
        for p in cands:
            try:
                if _read_text(p / "type").lower() != "battery":
                    continue
            except OSError:
                continue
            try:
                # A wireless mouse or headset is a Battery with scope Device; its
                # discharge is not the laptop's.
                if _read_text(p / "scope").lower() == "device":
                    continue
            except OSError:
                pass
            out.append(p)
        return out

    def _snapshot(self) -> tuple[dict[Path, tuple[_Gauge, str]] | None, str | None]:
        bats = self._batteries()
        if not bats:
            return None, f"no system battery under {self._root.as_posix()}"
        out: dict[Path, tuple[_Gauge, str]] = {}
        for b in bats:
            try:
                gauge = (
                    _opt_int(b / "energy_now"),
                    _opt_int(b / "charge_now"),
                    _opt_int(b / "voltage_now"),
                )
            except PermissionError:
                return None, f"permission denied reading {b.name}'s gauge"
            except (OSError, ValueError) as exc:
                return None, f"could not read {b.name}'s gauge: {type(exc).__name__}"
            if gauge[0] is None and (gauge[1] is None or gauge[2] is None):
                return None, f"{b.name} has neither energy_now nor charge_now with voltage_now"
            try:
                status = _read_text(b / "status")
            except OSError:
                status = "unknown"
            out[b] = (gauge, status)
        return out, None

    def begin(self) -> None:
        self._start, self._failure = self._snapshot()

    def end(self) -> dict:
        if self._start is None:
            return _null(self.source, self.METHOD, self._failure or "begin() was not called", *self._NOTES)
        stop, failure = self._snapshot()
        if stop is None:
            return _null(self.source, self.METHOD, failure or "end read failed", *self._NOTES)
        total_uwh = 0.0
        quantum_uwh = 0.0
        readings: dict[str, dict] = {}
        bases: set[str] = set()
        for b, (g0, s0) in self._start.items():
            if b not in stop:
                return _null(self.source, self.METHOD, f"{b.name} disappeared during the run", *self._NOTES)
            g1, s1 = stop[b]
            readings[b.name] = {
                "energy_now_uwh": [g0[0], g1[0]], "charge_now_uah": [g0[1], g1[1]],
                "voltage_now_uv": [g0[2], g1[2]], "status": [s0, s1],
            }
            if s0.lower() != "discharging" or s1.lower() != "discharging":
                return _null(self.source, self.METHOD,
                             f"{b.name} was not discharging at both ends ({s0} -> {s1})",
                             *self._NOTES, batteries=readings)
            uwh, why, basis = battery_discharge_uwh(g0, g1)
            if uwh is None:
                return _null(self.source, self.METHOD, f"{b.name}: {why}", *self._NOTES, batteries=readings)
            bases.add(basis)
            total_uwh += uwh
            # One sysfs unit at each end: 1 uWh, or 1 uAh at the mean voltage.
            if basis == "energy_now":
                quantum_uwh += 2.0
            else:
                quantum_uwh += 2.0 * ((g0[2] or 0) + (g1[2] or 0)) / 2.0 / 1e6
        if total_uwh <= 0:
            return _null(self.source, self.METHOD,
                         "battery gauge did not drop (resolution is coarser than this interval, or it rose)",
                         *self._NOTES, batteries=readings)
        notes = list(self._NOTES)
        if "charge_now*voltage_now" in bases:
            notes.append("charge-only gauge: energy = charge x mean of two voltage_now "
                         "instants, an approximation of the voltage integral")
        return {
            "source": self.source,
            "method": self.METHOD,
            "available": True,
            "energy_joules": total_uwh * _UWH_TO_J,
            "reason": None,
            "uncertainty": uncertainty(quantum_uwh * _UWH_TO_J, *notes),
            "basis": sorted(bases),
            "batteries": readings,
            "scope": "whole-system discharge; coarse, quantised by the fuel gauge",
        }


class UnavailableProbe:
    """A platform where no reader exists (or none can be tested). Always ``None``."""

    def __init__(self, name: str, method: str, reason: str, source: str = "none") -> None:
        self.name = name
        self._method = method
        self._reason = reason
        self._source = source

    def begin(self) -> None:
        return None

    def end(self) -> dict:
        return _null(self._source, self._method, self._reason)


MACOS_REASON = (
    "unavailable: macOS energy needs `sudo powermetrics`, which the harness never runs; "
    "see the manual path in paper/benchmark/README.md"
)


def default_probes(
    platform: str | None = None,
    *,
    rapl_root: Path = Path("/sys/class/powercap"),
    battery_root: Path = Path("/sys/class/power_supply"),
) -> list[EnergyProbe]:
    """The probes for this OS. Reads nothing from the host until a probe's `begin()`."""
    platform = platform or sys.platform
    if platform.startswith("linux"):
        return [RaplProbe(rapl_root), BatteryProbe(battery_root)]
    if platform == "darwin":
        return [UnavailableProbe("energy", "macos_unavailable", MACOS_REASON, "powermetrics (manual, root)")]
    if platform == "win32":
        return [UnavailableProbe("energy", "windows_unavailable",
                                 "unavailable: no Windows energy reader is implemented")]
    return [UnavailableProbe("energy", "unsupported_platform",
                             f"unavailable: no energy reader for {platform!r}")]


# --- macOS powermetrics (manual path) ----------------------------------------------------

_PM_SAMPLE = re.compile(r"^\*\*\* Sampled system activity .*\(([\d.]+)ms elapsed\) \*\*\*", re.M)
_PM_CPU_MW = re.compile(r"^CPU Power:\s*([\d.]+)\s*mW", re.M)
_PM_PKG_W = re.compile(r"^Intel energy model derived package power \(CPUs\+GT\+SA\):\s*([\d.]+)\s*W", re.M)


def powermetrics_energy(text: str) -> dict:
    """Integrate a ``powermetrics --samplers cpu_power`` log into a reading.

    Each sample is a ``*** Sampled system activity ... (N ms elapsed) ***`` header followed
    by ``CPU Power: P mW`` (Apple silicon) or ``Intel energy model derived package power
    (CPUs+GT+SA): P W`` (Intel Macs); energy is the sum of P x elapsed. The log must cover
    exactly the phase (start powermetrics before it, stop after) -- the parser cannot
    know which samples belong to it. Tested on synthetic text only: no Mac is available
    to check it against a real log.
    """
    method = "macos_powermetrics_cpu_power_manual"
    source = "powermetrics log (manual, root)"
    notes = (
        "integrates a sampled power estimate, not an energy counter",
        "model-estimated CPU power, not wall power; not per-process",
        "sample boundaries are not aligned with the phase being measured",
        "parser checked on synthetic logs only, not on a real Mac",
    )
    headers = list(_PM_SAMPLE.finditer(text))
    if not headers:
        return _null(source, method, "no '*** Sampled system activity' sample found in the log", *notes)
    joules = 0.0
    used = 0
    for i, h in enumerate(headers):
        body = text[h.end(): headers[i + 1].start() if i + 1 < len(headers) else len(text)]
        elapsed_s = float(h.group(1)) / 1000.0
        m = _PM_CPU_MW.search(body)
        if m is not None:
            joules += float(m.group(1)) / 1000.0 * elapsed_s
            used += 1
            continue
        m = _PM_PKG_W.search(body)
        if m is not None:
            joules += float(m.group(1)) * elapsed_s
            used += 1
    if used == 0:
        return _null(source, method, "samples carry no CPU power line (was --samplers cpu_power given?)", *notes)
    if joules <= 0:
        return _null(source, method, "integrated CPU power is zero", *notes)
    return {
        "source": source, "method": method, "available": True,
        "energy_joules": joules, "reason": None,
        "uncertainty": uncertainty(None, *notes),
        "samples": used, "samples_in_log": len(headers),
    }


# --- records -----------------------------------------------------------------------------

@dataclass
class _Acc:
    user: float = 0.0
    system: float = 0.0
    child_user: float = 0.0
    child_system: float = 0.0
    wall: float = 0.0
    audio: float = 0.0
    spans: int = 0
    per_span: list[dict] = field(default_factory=list)


def span_record(index: int, *, core_s: float, wall_s: float, audio_s: float) -> dict:
    """One decode: its core-seconds, wall time and real-time factor. Pure."""
    rtf = per_unit(wall_s, audio_s)
    cps = per_unit(core_s, audio_s)
    return {
        "index": index,
        "audio_s": round(audio_s, 3),
        "wall_s": round(wall_s, 6),
        "cpu_core_seconds": round(core_s, 6),
        "rtf": None if rtf is None else round(rtf, 6),
        "cpu_core_seconds_per_audio_s": None if cps is None else round(cps, 6),
    }


def build_record(
    *,
    user_s: float,
    system_s: float,
    span_wall_s: float,
    bracket_wall_s: float,
    audio_s: float,
    spans: int,
    energy: dict[str, dict],
    children_user_s: float = 0.0,
    children_system_s: float = 0.0,
    per_span: Sequence[dict] | None = None,
) -> dict:
    """The artifact fields for one phase. Pure: all arithmetic is here, fully tested.

    Energy is normalised by the phase's audio and span count. Note what that divides:
    the probes cover the whole *bracket*, so ``joules_per_audio_s`` includes the work
    between spans (FLAC reads), unlike ``cpu_core_seconds_per_audio_s``.
    """
    cpu = user_s + system_s + children_user_s + children_system_s
    cps = per_unit(cpu, audio_s)
    busy = per_unit(cpu, span_wall_s)
    rtf = per_unit(span_wall_s, audio_s)
    normalised = {
        name: {**reading, **normalise_energy(reading.get("energy_joules"), audio_s, spans)}
        for name, reading in energy.items()
    }
    spans_list = list(per_span) if per_span is not None else []
    return {
        "schema_version": SCHEMA_VERSION,
        "method": CPU_METHOD,
        "cpu_user_s": round(user_s, 4),
        "cpu_system_s": round(system_s, 4),
        "cpu_children_user_s": round(children_user_s, 4),
        "cpu_children_system_s": round(children_system_s, 4),
        "cpu_core_seconds": round(cpu, 4),
        "span_wall_s": round(span_wall_s, 4),
        "bracket_wall_s": round(bracket_wall_s, 4),
        "audio_s": round(audio_s, 3),
        "n_spans": spans,
        # Core-seconds spent per second of audio decoded. None when there was no audio
        # (the model-load phase), so a reader cannot mistake "not applicable" for 0.
        "cpu_core_seconds_per_audio_s": None if cps is None else round(cps, 4),
        # Average number of cores kept busy while inside a span.
        "mean_cores_busy": None if busy is None else round(busy, 3),
        # Wall time inside spans over audio decoded; None for a phase with no audio.
        "rtf": None if rtf is None else round(rtf, 4),
        "spans": spans_list,
        "span_summary": {
            "cpu_core_seconds": summarise(s["cpu_core_seconds"] for s in spans_list),
            "wall_s": summarise(s["wall_s"] for s in spans_list),
            "rtf": summarise(s["rtf"] for s in spans_list),
        },
        "energy": normalised,
    }


class CostMeter:
    """Bracket a phase with `begin()` / `end()`; time CPU inside each `span()`.

    CPU time and wall time accumulate over the spans only, so work between spans (reading
    a FLAC, say) is not billed to the decoder. Energy probes cannot be paused, so they
    cover the whole begin-to-end bracket -- ``bracket_wall_s`` is recorded beside
    ``span_wall_s`` so the gap between the two is visible, not hidden.
    """

    def __init__(
        self,
        probes: Sequence[EnergyProbe] = (),
        *,
        cpu_times: Callable[[], CpuTimes] = os_cpu_times,
        wall: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._probes = list(probes)
        self._cpu_times = cpu_times
        self._wall = wall
        self._acc = _Acc()
        self._t0: float | None = None

    def begin(self) -> None:
        self._acc = _Acc()
        for p in self._probes:
            p.begin()
        self._t0 = self._wall()

    @contextmanager
    def span(self, audio_s: float = 0.0) -> Iterator[None]:
        u0, s0, cu0, cs0 = _four(self._cpu_times())
        w0 = self._wall()
        try:
            yield
        finally:
            u1, s1, cu1, cs1 = _four(self._cpu_times())
            w1 = self._wall()
            a = self._acc
            a.user += u1 - u0
            a.system += s1 - s0
            a.child_user += cu1 - cu0
            a.child_system += cs1 - cs0
            a.wall += w1 - w0
            a.audio += audio_s
            core = (u1 - u0) + (s1 - s0) + (cu1 - cu0) + (cs1 - cs0)
            a.per_span.append(span_record(a.spans, core_s=core, wall_s=w1 - w0, audio_s=audio_s))
            a.spans += 1

    def end(self) -> dict:
        if self._t0 is None:
            raise RuntimeError("CostMeter.end() before begin()")
        bracket = self._wall() - self._t0
        energy = {p.name: p.end() for p in self._probes}
        a = self._acc
        return build_record(
            user_s=a.user, system_s=a.system, span_wall_s=a.wall,
            bracket_wall_s=bracket, audio_s=a.audio, spans=a.spans, energy=energy,
            children_user_s=a.child_user, children_system_s=a.child_system,
            per_span=a.per_span,
        )


# --- validation --------------------------------------------------------------------------

_NUMERIC = (
    "cpu_user_s", "cpu_system_s", "cpu_children_user_s", "cpu_children_system_s",
    "cpu_core_seconds", "span_wall_s", "bracket_wall_s", "audio_s",
)
_RATES = ("cpu_core_seconds_per_audio_s", "mean_cores_busy", "rtf")
_READING_KEYS = ("source", "method", "available", "energy_joules", "reason", "uncertainty",
                 "joules_per_audio_s", "joules_per_utterance")


def _is_num(x: object) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


def validate_reading(name: str, r: object) -> list[str]:
    """Contract for one energy reading. Returns the violations (empty when valid)."""
    if not isinstance(r, dict):
        return [f"energy.{name}: not an object"]
    errs = [f"energy.{name}: missing {k!r}" for k in _READING_KEYS if k not in r]
    if errs:
        return errs
    if not isinstance(r["source"], str) or not r["source"]:
        errs.append(f"energy.{name}: source must be a non-empty string")
    if not isinstance(r["available"], bool):
        errs.append(f"energy.{name}: available must be a bool")
    elif r["available"]:
        if not _is_num(r["energy_joules"]) or r["energy_joules"] <= 0:
            errs.append(f"energy.{name}: available reading needs energy_joules > 0")
        if r["reason"] is not None:
            errs.append(f"energy.{name}: available reading must have reason null")
    else:
        if r["energy_joules"] is not None:
            errs.append(f"energy.{name}: unavailable reading must have energy_joules null, never a number")
        if not isinstance(r["reason"], str) or not r["reason"]:
            errs.append(f"energy.{name}: unavailable reading needs a reason")
        for k in ("joules_per_audio_s", "joules_per_utterance"):
            if r[k] is not None:
                errs.append(f"energy.{name}: {k} must be null when energy is unavailable")
    u = r["uncertainty"]
    if not isinstance(u, dict) or "quantisation_joules" not in u or not isinstance(u.get("notes"), list):
        errs.append(f"energy.{name}: uncertainty must be {{quantisation_joules, notes[]}}")
    elif u["quantisation_joules"] is not None and (not _is_num(u["quantisation_joules"]) or u["quantisation_joules"] < 0):
        errs.append(f"energy.{name}: quantisation_joules must be null or >= 0")
    return errs


def validate_record(rec: object) -> list[str]:
    """Contract for one phase record (`SCHEMA_VERSION`). Returns violations, empty = valid."""
    if not isinstance(rec, dict):
        return ["record is not an object"]
    if rec.get("schema_version") != SCHEMA_VERSION:
        return [f"schema_version is {rec.get('schema_version')!r}, expected {SCHEMA_VERSION!r}"]
    errs: list[str] = []
    for k in _NUMERIC:
        if not _is_num(rec.get(k)) or rec[k] < 0:
            errs.append(f"{k} must be a finite number >= 0")
    for k in _RATES:
        if k not in rec:
            errs.append(f"missing {k!r}")
        elif rec[k] is not None and (not _is_num(rec[k]) or rec[k] < 0):
            errs.append(f"{k} must be null or a finite number >= 0")
    if not isinstance(rec.get("n_spans"), int) or rec["n_spans"] < 0:
        errs.append("n_spans must be an int >= 0")
    if not isinstance(rec.get("method"), str) or not rec["method"]:
        errs.append("method must be a non-empty string")
    if errs:
        return errs
    parts = sum(rec[k] for k in ("cpu_user_s", "cpu_system_s", "cpu_children_user_s", "cpu_children_system_s"))
    if abs(parts - rec["cpu_core_seconds"]) > 1e-3:
        errs.append("cpu_core_seconds is not the sum of its user/system/children parts")
    if rec["audio_s"] == 0 and (rec["rtf"] is not None or rec["cpu_core_seconds_per_audio_s"] is not None):
        errs.append("a phase with no audio must have null per-audio rates, not a number")
    spans = rec.get("spans")
    if not isinstance(spans, list):
        errs.append("spans must be a list")
    elif spans and len(spans) != rec["n_spans"]:
        errs.append(f"spans lists {len(spans)} decodes but n_spans is {rec['n_spans']}")
    energy = rec.get("energy")
    if not isinstance(energy, dict):
        errs.append("energy must be an object")
    else:
        for name, r in energy.items():
            errs.extend(validate_reading(name, r))
    return errs


def check_record(rec: dict) -> dict:
    """`validate_record`, raising ``ValueError`` on any violation; returns ``rec``."""
    errs = validate_record(rec)
    if errs:
        raise ValueError("cost record violates " + SCHEMA_VERSION + ": " + "; ".join(errs))
    return rec
