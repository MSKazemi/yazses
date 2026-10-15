"""CPU core-seconds and (optional) energy for a benchmark phase (PAPER2-ENERGY-001, #506).

Wall-clock latency and RTF hide what a fast decode costs across cores: a decode that
finishes in a second on eight busy threads is eight core-seconds of heat and battery.
This module is the *measuring* half of that question; it records numbers and states the
conditions they were taken under, and nothing in it is a result. Library only -- imported
by `bench_latency.py`, never run on its own, never imported by the daemon.

**Core-seconds.** ``os.times()`` user + system CPU time of *this process*, read before and
after. Properties that a reader has to know, and that are written into every record's
``method`` field:

* Threads are included (the interpreter's, CTranslate2's and ONNX Runtime's pools all live
  in this process).
* Child processes are **not** included: a decoder that shells out to a subprocess would be
  under-counted. None of the benchmarked engines does, but that is a fact about today's
  engines, not a guarantee, so it is stated rather than assumed.
* It is CPU *time*, not CPU *work*: it does not normalise for clock frequency, SMT or
  turbo, so core-seconds from two hosts are not comparable without calibration.

**Energy** is optional and is ``None`` -- never ``0`` -- whenever it cannot be read, with a
``reason``. A zero would read as "this decode was free".

* Linux RAPL (``/sys/class/powercap/intel-rapl:N/energy_uj``): CPU *package* energy, a
  hardware counter, but not wall power (no display, DRAM on some parts, SSD, fans, PSU
  loss) and not per-process: it counts everything running on the package, so an idle-box
  baseline is the reader's job. Often readable by root only. The counter wraps at
  ``max_energy_range_uj``; one wrap is corrected, and a run long enough to wrap twice
  cannot be detected, which is why the range is recorded.
* Linux battery (``/sys/class/power_supply/BAT*/energy_now``): discharge between two
  readings. Coarse -- the gauge moves in steps far larger than one short decode -- and
  valid only while the battery reports ``Discharging`` at both ends.
* macOS and Windows: ``unavailable``. Nothing here reads their counters, because there is
  no machine in CI that could prove such a reader right.

The sources sit behind the `EnergyProbe` Protocol so the arithmetic is tested against
fakes, with no hardware.
"""
from __future__ import annotations

import os
import re
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

CPU_METHOD = (
    "os.times() user+system of this process: threads included, child processes excluded; "
    "CPU time, not normalised for frequency or SMT"
)

_UWH_TO_J = 3600.0 / 1e6  # 1 uWh = 3.6e-3 J
_UJ_TO_J = 1e-6


def os_cpu_times() -> tuple[float, float]:
    """``(user_s, system_s)`` for this process. Portable: Linux, macOS and Windows."""
    t = os.times()
    return t.user, t.system


class EnergyProbe(Protocol):
    """One energy source: bracket a phase with `begin()` / `end()`.

    `end()` returns a JSON-able dict that always carries ``method``, ``energy_joules``
    (``float`` or ``None``) and ``reason`` (``None`` when the value is present, a string
    when it is not). It never raises: a probe that cannot read must say so, not abort a
    multi-hour benchmark.
    """

    name: str

    def begin(self) -> None: ...

    def end(self) -> dict: ...


def _null(method: str, reason: str, **extra: object) -> dict:
    return {"method": method, "energy_joules": None, "reason": reason, **extra}


def _read_int(path: Path) -> int:
    return int(path.read_text(encoding="utf-8").strip())


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


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

    def __init__(self, root: Path = Path("/sys/class/powercap")) -> None:
        self._root = root
        self._start: dict[Path, int] | None = None
        self._failure: str | None = None

    def _domains(self) -> list[Path]:
        try:
            return sorted(p for p in self._root.iterdir() if self._DOMAIN.match(p.name))
        except OSError:
            return []

    def _snapshot(self) -> tuple[dict[Path, int] | None, str | None]:
        domains = self._domains()
        if not domains:
            return None, f"no intel-rapl package domain under {self._root} (not an Intel/AMD-RAPL host, or powercap not exposed)"
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
            return _null(self.METHOD, self._failure or "begin() was not called")
        stop, failure = self._snapshot()
        if stop is None:
            return _null(self.METHOD, failure or "end read failed")
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
                return _null(self.METHOD, f"{d.name} disappeared during the run")
            delta, w = rapl_delta_uj(s, e, max_range)
            if delta is None:
                return _null(self.METHOD, f"{d.name} counter wrapped and max_energy_range_uj is unreadable")
            total_uj += delta
            wrapped = wrapped or w
            ranges[d.name] = max_range
        if total_uj == 0:
            return _null(self.METHOD, "counter did not advance (stuck, or interval shorter than its resolution)")
        return {
            "method": self.METHOD,
            "energy_joules": total_uj * _UJ_TO_J,
            "reason": None,
            "domains": [d.name for d in self._start],
            "wrapped": wrapped,
            "max_energy_range_uj": ranges,
            "scope": "CPU package only; not wall power; not per-process",
        }


class BatteryProbe:
    """Linux battery discharge between two ``energy_now`` readings. Coarse by nature."""

    name = "battery"
    METHOD = "linux_battery_energy_now_discharge"

    def __init__(self, root: Path = Path("/sys/class/power_supply")) -> None:
        self._root = root
        self._start: dict[Path, tuple[int, str]] | None = None
        self._failure: str | None = None

    def _batteries(self) -> list[Path]:
        try:
            cands = sorted(p for p in self._root.iterdir() if p.name.startswith("BAT"))
        except OSError:
            return []
        out = []
        for p in cands:
            try:
                if _read_text(p / "type").lower() == "battery":
                    out.append(p)
            except OSError:
                continue
        return out

    def _snapshot(self) -> tuple[dict[Path, tuple[int, str]] | None, str | None]:
        bats = self._batteries()
        if not bats:
            return None, f"no battery under {self._root}"
        out: dict[Path, tuple[int, str]] = {}
        for b in bats:
            try:
                energy = _read_int(b / "energy_now")
            except FileNotFoundError:
                return None, f"{b.name} has no energy_now (charge_now-only gauges are not converted)"
            except PermissionError:
                return None, f"permission denied reading {b.name}/energy_now"
            except (OSError, ValueError) as exc:
                return None, f"could not read {b.name}/energy_now: {type(exc).__name__}"
            try:
                status = _read_text(b / "status")
            except OSError:
                status = "unknown"
            out[b] = (energy, status)
        return out, None

    def begin(self) -> None:
        self._start, self._failure = self._snapshot()

    def end(self) -> dict:
        if self._start is None:
            return _null(self.METHOD, self._failure or "begin() was not called")
        stop, failure = self._snapshot()
        if stop is None:
            return _null(self.METHOD, failure or "end read failed")
        total_uwh = 0
        readings = {}
        for b, (e0, s0) in self._start.items():
            if b not in stop:
                return _null(self.METHOD, f"{b.name} disappeared during the run")
            e1, s1 = stop[b]
            readings[b.name] = {
                "energy_now_start_uwh": e0, "energy_now_end_uwh": e1,
                "status_start": s0, "status_end": s1,
            }
            if s0.lower() != "discharging" or s1.lower() != "discharging":
                return _null(
                    self.METHOD,
                    f"{b.name} was not discharging at both ends ({s0} -> {s1})",
                    batteries=readings,
                )
            total_uwh += e0 - e1
        if total_uwh <= 0:
            return _null(
                self.METHOD,
                "battery gauge did not drop (resolution is coarser than this interval, or it rose)",
                batteries=readings,
            )
        return {
            "method": self.METHOD,
            "energy_joules": total_uwh * _UWH_TO_J,
            "reason": None,
            "batteries": readings,
            "scope": "whole-system discharge; coarse, quantised by the fuel gauge",
        }


class UnavailableProbe:
    """A platform where no reader exists (or none can be tested). Always ``None``."""

    def __init__(self, name: str, method: str, reason: str) -> None:
        self.name = name
        self._method = method
        self._reason = reason

    def begin(self) -> None:
        return None

    def end(self) -> dict:
        return _null(self._method, self._reason)


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
        return [UnavailableProbe("energy", "macos_unavailable",
                                 "unavailable: no macOS energy reader is implemented")]
    if platform == "win32":
        return [UnavailableProbe("energy", "windows_unavailable",
                                 "unavailable: no Windows energy reader is implemented")]
    return [UnavailableProbe("energy", "unsupported_platform",
                             f"unavailable: no energy reader for {platform!r}")]


@dataclass
class _Acc:
    user: float = 0.0
    system: float = 0.0
    wall: float = 0.0
    audio: float = 0.0
    spans: int = 0


def build_record(
    *,
    user_s: float,
    system_s: float,
    span_wall_s: float,
    bracket_wall_s: float,
    audio_s: float,
    spans: int,
    energy: dict[str, dict],
) -> dict:
    """The artifact fields for one phase. Pure: all arithmetic is here, fully tested."""
    cpu = user_s + system_s
    return {
        "method": CPU_METHOD,
        "cpu_user_s": round(user_s, 4),
        "cpu_system_s": round(system_s, 4),
        "cpu_core_seconds": round(cpu, 4),
        "span_wall_s": round(span_wall_s, 4),
        "bracket_wall_s": round(bracket_wall_s, 4),
        "audio_s": round(audio_s, 3),
        "n_spans": spans,
        # Core-seconds spent per second of audio decoded. None when there was no audio
        # (the model-load phase), so a reader cannot mistake "not applicable" for 0.
        "cpu_core_seconds_per_audio_s": round(cpu / audio_s, 4) if audio_s > 0 else None,
        # Average number of cores kept busy while inside a span.
        "mean_cores_busy": round(cpu / span_wall_s, 3) if span_wall_s > 0 else None,
        "energy": energy,
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
        cpu_times: Callable[[], tuple[float, float]] = os_cpu_times,
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
        u0, s0 = self._cpu_times()
        w0 = self._wall()
        try:
            yield
        finally:
            u1, s1 = self._cpu_times()
            w1 = self._wall()
            a = self._acc
            a.user += u1 - u0
            a.system += s1 - s0
            a.wall += w1 - w0
            a.audio += audio_s
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
        )
