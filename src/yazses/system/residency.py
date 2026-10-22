"""Runtime residency: which models stay in memory, for how long, and in which process.

ADR-016 made a feature that is *off* cost nothing in bytes and imports, and the guards
hold (`tests/test_base_weight_budget.py`, `tests/test_dormant_features_stay_unimported.py`).
A feature that has run once is a different matter. On ``origin/main`` ``fa058766`` the
dictation model loads at daemon start and is never unloaded (base.en: 188 MB resident,
216 MB after the first decode, a 343 MB peak during the load); the latency governor's
second model loads the first time the CPU is busy and then stays (tiny.en: about
116 MB); diarization, the camera models, TTS, the LLM and the voiceprint stack each
stay for the life of the daemon once touched, and nothing bounds how many of them are
resident together. ADR-029 is the decision that RAM and CPU should be proportional to
what is *in use*, not to what has ever been used. This module is that decision as
arithmetic, with no engine, no thread and no clock of its own, so the daemon's loader,
`yazses status`, the settings window and the nightly budget job all read **one** policy
and every rule is tested on a number.

Three rules, each a class:

* :class:`IdleTracker` — *unload after idle*. Each **residency unit** has a keep-alive;
  :meth:`IdleTracker.due_for_unload` names the loaded units whose last use is at least
  that long ago. ``None`` means "resident while enabled", which is the core engine's
  default, because first-word latency is the product.
* :class:`ResidencyBudget` — *at most N heavy models at once*. Ollama's
  ``OLLAMA_MAX_LOADED_MODELS`` with least-recently-used eviction; a pinned unit (the
  dictation engine) is never the one evicted.
* :func:`placement` — *the heaviest stacks run out of process*. Native allocators
  (ONNX Runtime, CTranslate2, torch) do not reliably hand freed pages back to the OS, so
  for those a worker's exit is the only release that is guaranteed. The table is
  :data:`WORKER_UNITS`.

A residency unit is coarser than a registry slug on purpose: ``gaze``, ``facegesture``,
``headpointer`` and ``gesture`` share one MediaPipe model through the shared perception
source, so they are one unit, and unloading it is one decision. :data:`UNIT_OF_SLUG` is
the mapping and :func:`unit_for` the lookup; a slug with no heavy model has no unit.

:func:`check_rss` is the nightly job's verdict: measured peak RSS per unit against a
committed budget, each breach with the amount over, and a run that measured nothing is a
failure rather than a clean pass (a guard that iterates an empty set is green for the
wrong reason). The seconds and the megabytes here are the ADR's proposals, labelled in
its text as engineering judgement; the nightly table is what will replace them with
measurements. This module defines no config key; :func:`with_stt_idle_unload` is how
``[stt] idle_unload_s`` (the one key wired so far, the dictation engine's opt-in) becomes
a policy row, and :func:`unload_tick_s` how often the daemon asks.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Literal

Placement = Literal["in_process", "worker"]

#: Residency units that must run in a worker process (ADR-029 §2). Each is a native
#: stack whose allocator keeps freed memory mapped: MediaPipe + OpenCV (``gaze``),
#: llama.cpp (``llm``), torch (``voiceprint``) and sherpa-onnx (``diarize``). A crash in
#: any of them must not take dictation down with it, and ADR-018 §3 names "a separate
#: process with no network namespace and no injector handle" as the only boundary that
#: could ever reopen the plug-in question. The core engine and TTS stay in process: the
#: engine because an IPC hop on every burst is first-word latency, TTS because it is
#: small and its ONNX session is the same runtime the base already holds.
WORKER_UNITS: frozenset[str] = frozenset({"gaze", "llm", "voiceprint", "diarize"})

#: Capability-registry slug → residency unit, for every slug that loads a heavy model.
#: A slug absent here loads nothing the policy needs to manage.
UNIT_OF_SLUG: Mapping[str, str] = {
    "gaze": "gaze",
    "facegesture": "gaze",
    "headpointer": "gaze",
    "gesture": "gaze",
    "llm-cleanup": "llm",
    "cocktail": "voiceprint",
    "voiceguard": "voiceprint",
    "multiprofile": "voiceprint",
    "diarize": "diarize",
    "recimport": "diarize",
    "meeting": "diarize",
    "read-back": "tts",
    "latency": "latency",
}

#: What was measured on ``origin/main`` ``fa058766`` (Linux x86_64, CPython 3.12, a
#: base-only install), in MB of RSS. These are the ADR's baseline figures and the first
#: numbers the nightly budget is checked against; they are **[M] measured**, not targets.
MEASURED_FA058766_MB: Mapping[str, float] = {
    "stt.base.en.loaded": 188.0,
    "stt.base.en.after_first_decode": 216.0,
    "stt.base.en.load_peak": 343.0,
    "latency.tiny.en": 116.0,
}


def _finite_non_negative(value: float, what: str) -> float:
    """Reject NaN, infinity and negatives once, with the field named.

    Every number this module takes is a duration or a size. A NaN compares false
    against everything, so a NaN keep-alive would never fire and a NaN measurement
    would never breach — the policy would silently stop applying. Fail instead.
    """
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"{what} must be a number, not {type(value).__name__}")
    if math.isnan(value) or math.isinf(value):
        raise ValueError(f"{what} must be finite, not {value!r}")
    if value < 0:
        raise ValueError(f"{what} must not be negative, got {value!r}")
    return float(value)


def unit_for(slug: str) -> str | None:
    """The residency unit a registry slug belongs to, or ``None`` when it holds no model."""
    return UNIT_OF_SLUG.get(slug)


def placement(unit: str) -> Placement:
    """Where a unit's model runs. Unknown units raise: a typo must not mean 'in process'."""
    if unit not in DEFAULT_POLICY.units():
        raise KeyError(f"unknown residency unit {unit!r}")
    return "worker" if unit in WORKER_UNITS else "in_process"


@dataclass(frozen=True)
class KeepAlive:
    """One residency unit's policy row.

    ``keep_alive_s`` is how long the unit stays loaded after its last use; ``None`` is
    "while enabled". ``resident_default`` says whether it loads at daemon start (the
    core engine) or on first use (everything else). ``worker_required`` is the
    out-of-process rule for this unit, kept on the row so a reader of the table sees
    the whole decision in one line; a test holds it equal to :data:`WORKER_UNITS`.
    """

    feature: str
    keep_alive_s: float | None
    resident_default: bool
    worker_required: bool

    def __post_init__(self) -> None:
        if not self.feature or not self.feature.strip():
            raise ValueError("a KeepAlive row needs a feature name")
        if self.keep_alive_s is not None:
            object.__setattr__(
                self, "keep_alive_s",
                _finite_non_negative(self.keep_alive_s, f"keep_alive_s for {self.feature!r}"),
            )


@dataclass(frozen=True)
class ResidencyPolicy:
    """The whole table plus the cap on how many heavy models may be resident at once."""

    entries: tuple[KeepAlive, ...]
    max_resident: int
    _by_unit: Mapping[str, KeepAlive] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.max_resident < 1:
            raise ValueError(f"max_resident must be at least 1, got {self.max_resident!r}")
        by_unit: dict[str, KeepAlive] = {}
        for entry in self.entries:
            if entry.feature in by_unit:
                raise ValueError(f"duplicate residency unit {entry.feature!r}")
            by_unit[entry.feature] = entry
        object.__setattr__(self, "_by_unit", by_unit)

    def get(self, unit: str) -> KeepAlive:
        """The row for *unit*. Raises ``KeyError`` for an unknown unit, never a default."""
        try:
            return self._by_unit[unit]
        except KeyError:
            raise KeyError(f"unknown residency unit {unit!r}") from None

    def units(self) -> frozenset[str]:
        return frozenset(self._by_unit)

    def pinned(self) -> frozenset[str]:
        """Units with no keep-alive: resident while enabled, never evicted by the cap."""
        return frozenset(e.feature for e in self.entries if e.keep_alive_s is None)


#: ADR-029 §1. The seconds are proposals [O], with the reasoning in the ADR:
#:
#: * ``stt`` — no timeout, loaded at start. First-word latency is the product. The ADR
#:   proposes an opt-in ``[stt] idle_unload_s`` for low-RAM machines; off by default.
#: * ``latency`` — 600 s. The governor's light model is only asked for while the 1-minute
#:   load average is high; ten idle minutes outlive that average many times over, and the
#:   governor already reloads in the background off the hot path.
#: * ``diarize`` — 300 s, Ollama's default. A meeting is continuous use; a five-minute gap
#:   after it is the meeting having ended.
#: * ``gaze`` — 120 s. The shared perception source already closes the camera on the last
#:   lease; the FaceLandmarker is small and reloads in about a second, so a short timer
#:   buys RAM cheaply. The camera features are session-shaped: idle gaps are seconds.
#: * ``tts`` — 300 s. Read-back follows a dictation; dictations are minutes apart.
#: * ``llm`` — 300 s. The same class of model Ollama applies its five minutes to.
#: * ``voiceprint`` — 600 s. The torch stack is the slowest to bring back (a worker
#:   spawn plus ``import torch``), and it is consulted per burst, so a short timer thrashes.
DEFAULT_POLICY = ResidencyPolicy(
    entries=(
        KeepAlive("stt", None, resident_default=True, worker_required=False),
        KeepAlive("latency", 600.0, resident_default=False, worker_required=False),
        KeepAlive("diarize", 300.0, resident_default=False, worker_required=True),
        KeepAlive("gaze", 120.0, resident_default=False, worker_required=True),
        KeepAlive("tts", 300.0, resident_default=False, worker_required=False),
        KeepAlive("llm", 300.0, resident_default=False, worker_required=True),
        KeepAlive("voiceprint", 600.0, resident_default=False, worker_required=True),
    ),
    # The dictation engine plus two heavy features. A laptop that runs eye control and
    # read-back together keeps both; a third asks the least recently used one to leave.
    max_resident=3,
)


#: The dictation engine's residency unit, named once for the daemon and the engine wrapper.
STT_UNIT = "stt"


def with_stt_idle_unload(
    idle_unload_s: float, policy: ResidencyPolicy = DEFAULT_POLICY,
) -> ResidencyPolicy:
    """*policy* with the dictation engine's keep-alive taken from ``[stt] idle_unload_s``.

    ``0`` is "never unload" and returns *policy* unchanged, so the engine stays pinned —
    the default, and the behaviour before the key existed. A positive value replaces the
    ``stt`` row's ``None`` with that many seconds, which also takes the engine out of
    :meth:`ResidencyPolicy.pinned`: an engine that may unload is no longer one the cap
    must never choose. Negative, NaN and infinite values raise, like every other number
    here; the config loader has already refused a negative before it gets this far.
    """
    seconds = _finite_non_negative(idle_unload_s, "[stt] idle_unload_s")
    if seconds == 0:
        return policy
    entries = tuple(
        replace(e, keep_alive_s=seconds) if e.feature == STT_UNIT else e
        for e in policy.entries
    )
    return ResidencyPolicy(entries=entries, max_resident=policy.max_resident)


def unload_tick_s(keep_alive_s: float) -> float:
    """How often a housekeeping thread should ask :meth:`IdleTracker.due_for_unload`.

    A quarter of the keep-alive, so an unload lands at most 25 % late, clamped to
    [1 s, 30 s]: under a second is polling for nothing, and over thirty would leave a
    ten-minute keep-alive's memory held minutes past its time. The same quarter-period
    shape as the portal idle reaper in ``core/daemon.py``.
    """
    seconds = _finite_non_negative(keep_alive_s, "keep_alive_s")
    return min(30.0, max(1.0, seconds / 4))


class _MonotonicInput:
    """Shared validation of the ``now`` each method takes.

    The clock is monotonic by contract (``time.monotonic()``); a wall clock handed in by
    mistake would, on a DST change or an NTP step, make a keep-alive fire early or
    never. So a ``now`` earlier than the last one seen is an error, not a quirk to
    absorb. The clock is injected (or ``now`` is passed) so every rule is tested on a
    number and no test sleeps.
    """

    def __init__(self, clock: Callable[[], float] | None) -> None:
        self._clock = clock
        self._last_now: float | None = None

    def _now(self, now: float | None) -> float:
        if now is None:
            if self._clock is None:
                raise ValueError("no clock was injected, so `now` must be passed")
            now = self._clock()
        now = _finite_non_negative(now, "now")
        if self._last_now is not None and now < self._last_now:
            raise ValueError(
                f"time ran backwards ({now!r} after {self._last_now!r}); "
                "the clock must be monotonic"
            )
        self._last_now = now
        return now


class IdleTracker(_MonotonicInput):
    """Per-unit last-use bookkeeping and the *unload after idle* rule over it.

    The caller (the daemon's loader) tells it when a unit was loaded, touches it on
    every use, asks :meth:`due_for_unload` on a timer, and tells it when the unload
    happened. It never loads or unloads anything itself.
    """

    def __init__(
        self,
        policy: ResidencyPolicy = DEFAULT_POLICY,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(clock)
        self._policy = policy
        self._loaded: dict[str, float] = {}      # unit -> last use (only while loaded)

    def _check(self, unit: str) -> KeepAlive:
        return self._policy.get(unit)

    def mark_loaded(self, unit: str, now: float | None = None) -> None:
        """The unit's model is resident as of *now*; its keep-alive starts here."""
        self._check(unit)
        self._loaded[unit] = self._now(now)

    def touch(self, unit: str, now: float | None = None) -> None:
        """The unit was used at *now*. Restarts its keep-alive; a no-op when not loaded."""
        self._check(unit)
        t = self._now(now)
        if unit in self._loaded:
            self._loaded[unit] = t

    def mark_unloaded(self, unit: str) -> None:
        self._check(unit)
        self._loaded.pop(unit, None)

    def is_loaded(self, unit: str) -> bool:
        self._check(unit)
        return unit in self._loaded

    def idle_s(self, unit: str, now: float | None = None) -> float | None:
        """Seconds since last use, or ``None`` when the unit is not loaded. For status rows."""
        self._check(unit)
        t = self._now(now)
        last = self._loaded.get(unit)
        return None if last is None else t - last

    def due_for_unload(self, now: float | None = None) -> list[str]:
        """Loaded units idle for at least their keep-alive, longest idle first.

        ``>=`` and not ``>``: a timer that polls every *keep_alive* seconds must see the
        unit due on the tick that lands exactly on the boundary. Units whose row says
        ``None`` are never returned, whatever the idle time.
        """
        t = self._now(now)
        due: list[tuple[float, str]] = []
        for unit, last in self._loaded.items():
            limit = self._policy.get(unit).keep_alive_s
            if limit is None:
                continue
            idle = t - last
            if idle >= limit:
                due.append((-idle, unit))
        return [unit for _idle, unit in sorted(due)]


@dataclass(frozen=True)
class _BudgetView:
    """A read-only snapshot of a :class:`ResidencyBudget`'s settings, for status and tests."""

    max_resident: int
    pinned: frozenset[str]


class ResidencyBudget(_MonotonicInput):
    """At most ``max_resident`` units resident at once; the least recently used leaves.

    Ollama's ``OLLAMA_MAX_LOADED_MODELS``. :meth:`admit` is the whole protocol: call it
    before loading a unit, and it answers with the units that must be unloaded first so
    the cap holds, LRU first. A pinned unit (the dictation engine) is counted against
    the cap — it does use the memory — but is never chosen for eviction, so with a cap
    of one and the engine pinned, the budget can be over by the engine alone; that is
    reported by :meth:`over_budget`, not hidden, and the ADR says a cap below two is a
    configuration `yazses doctor` should question.
    """

    def __init__(
        self,
        max_resident: int,
        *,
        pinned: Iterable[str] = (),
        clock: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(clock)
        if max_resident < 1:
            raise ValueError(f"max_resident must be at least 1, got {max_resident!r}")
        self._cap = int(max_resident)
        self._pinned = frozenset(pinned)
        self._resident: dict[str, float] = {}    # unit -> last use; insertion = LRU order

    def set_cap(self, max_resident: int) -> None:
        """Change the cap. Takes effect at the next :meth:`admit`, which does the evicting."""
        if max_resident < 1:
            raise ValueError(f"max_resident must be at least 1, got {max_resident!r}")
        self._cap = int(max_resident)

    def policy_view(self) -> _BudgetView:
        return _BudgetView(max_resident=self._cap, pinned=self._pinned)

    def _bump(self, unit: str, t: float) -> None:
        # Re-insert so dict order is recency order; the LRU is then the first key.
        self._resident.pop(unit, None)
        self._resident[unit] = t

    def touch(self, unit: str, now: float | None = None) -> None:
        """The unit was used; it becomes the most recently used. A no-op when not resident."""
        t = self._now(now)
        if unit in self._resident:
            self._bump(unit, t)

    def admit(self, unit: str, now: float | None = None) -> list[str]:
        """Make room for *unit* and record it as resident; return what must be evicted.

        The returned units are in eviction order (least recently used first) and are
        already removed from the resident set — the caller's only job is to unload
        them. Admitting a unit that is already resident just refreshes its recency.
        """
        t = self._now(now)
        self._bump(unit, t)
        evicted: list[str] = []
        for candidate in list(self._resident):
            if len(self._resident) <= self._cap:
                break
            if candidate == unit or candidate in self._pinned:
                continue
            del self._resident[candidate]
            evicted.append(candidate)
        return evicted

    def release(self, unit: str) -> None:
        """The unit was unloaded for another reason (idle, disable); it no longer counts."""
        self._resident.pop(unit, None)

    def resident(self) -> tuple[str, ...]:
        """Resident units, least recently used first."""
        return tuple(self._resident)

    def over_budget(self) -> int:
        """How many units above the cap are resident because every candidate was pinned."""
        return max(0, len(self._resident) - self._cap)


@dataclass(frozen=True)
class RuntimeBudget:
    """One unit's committed ceiling for the nightly job: peak RSS and idle CPU.

    ``idle_cpu_s_per_min`` is CPU seconds the daemon may spend per minute with the unit
    loaded and nothing happening; ``None`` leaves that half unbudgeted until measured.
    """

    feature: str
    peak_rss_mb: float
    idle_cpu_s_per_min: float | None = None

    def __post_init__(self) -> None:
        if not self.feature:
            raise ValueError("a RuntimeBudget row needs a feature name")
        object.__setattr__(
            self, "peak_rss_mb", _finite_non_negative(self.peak_rss_mb, "peak_rss_mb"),
        )
        if self.idle_cpu_s_per_min is not None:
            object.__setattr__(
                self, "idle_cpu_s_per_min",
                _finite_non_negative(self.idle_cpu_s_per_min, "idle_cpu_s_per_min"),
            )


@dataclass(frozen=True)
class Breach:
    """A measured peak above its budget, with the amount, for the job's log and its issue."""

    feature: str
    measured_mb: float
    budget_mb: float

    @property
    def over_mb(self) -> float:
        return round(self.measured_mb - self.budget_mb, 3)

    def describe(self) -> str:
        return (
            f"{self.feature}: peak RSS {self.measured_mb:.0f} MB is {self.over_mb:.0f} MB "
            f"over its {self.budget_mb:.0f} MB budget"
        )


def check_rss(
    measured_mb: Mapping[str, float],
    budget_mb: Mapping[str, float],
    *,
    tolerance: float = 1.0,
) -> list[Breach]:
    """Every budgeted unit whose measured peak exceeds ``budget × tolerance``.

    *tolerance* is the import-time gate's idea (1.5× there): a single runner's number
    is noisy and a budget that fails on noise gets deleted. ``1.0`` is exact. An empty
    *measured_mb* raises, because a nightly that measured nothing has not passed — it
    has not run. A measured unit nobody budgeted is not a breach; :func:`unmeasured`
    is the mirror check for a budgeted unit the run skipped.
    """
    if tolerance < 1.0 or math.isnan(tolerance) or math.isinf(tolerance):
        raise ValueError(f"tolerance must be at least 1.0, got {tolerance!r}")
    if not measured_mb:
        raise ValueError("the run measured nothing; refusing to report zero breaches")
    out: list[Breach] = []
    for feature in sorted(budget_mb):
        budget = _finite_non_negative(budget_mb[feature], f"budget for {feature!r}")
        if feature not in measured_mb:
            continue
        measured = _finite_non_negative(measured_mb[feature], f"measurement for {feature!r}")
        if measured > budget * tolerance:
            out.append(Breach(feature=feature, measured_mb=measured, budget_mb=budget))
    # Validate what the loop skipped too, so a NaN in an unbudgeted row is still refused.
    for feature, value in measured_mb.items():
        _finite_non_negative(value, f"measurement for {feature!r}")
    return out


def unmeasured(budget_mb: Mapping[str, float], measured_mb: Mapping[str, float]) -> list[str]:
    """Budgeted units the run produced no figure for — a skipped probe, not a pass."""
    return sorted(feature for feature in budget_mb if feature not in measured_mb)
