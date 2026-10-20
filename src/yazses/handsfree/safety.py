"""Global hands-free stop state + stale-signal watchdog (pure) — ADR-v2-148, R-05/R-06/R-24.

The failure this module exists to prevent is the one a hands-free user cannot escape from: a
runaway pointer or a stuck activation, driven by a camera signal that has gone quiet, for
someone who cannot reach the keyboard to stop it. Every continuous camera-driven consumer —
Head-Pointer motion, dwell click, face switch, gaze routing — asks :meth:`HandsFreeSafety.gate`
before it acts, and acts only on an ``allowed`` decision.

Pure and dependency-free by contract (AGENT_TASKS EYE-ARCH-001, AGENTS.md rule 5): no camera, no
backend, no thread of its own, and time arrives through a caller-supplied clock so a whole
timeline can be fabricated in a unit test. It holds a lock because :meth:`pause` must be callable
from whichever thread the stop path arrives on (tray click, voice command, hotkey); a lock is not
a thread.

**Three states, from the ADR.** ``ACTIVE`` — configured inputs may emit actions. ``PAUSED`` —
actions suppressed by user intent, by shutdown, or because nothing has armed yet. ``FAULTED`` — a
source that was delivering has gone stale, or a backend fault was reported. There is deliberately
no fourth "killed" state: the ADR names a kill *path*, not a kill state, and :meth:`shutdown`
enters PAUSED terminally rather than inventing vocabulary the ADR does not have.

**Two things this design refuses to do.** It never acts on the last known value — a source that
has aged out is denied until a *new* sample arrives, so no pose, switch event or gaze target is
ever replayed (R-06, R-24). And it never recovers silently: a source that falls stale is
disarmed, and only an explicit :meth:`resume` re-arms it, so a camera that flickers back cannot
resume driving a cursor without the user asking for it.

**One opt-in exception, per source** (:meth:`allow_auto_rearm`, ADR-v2-148 amendment of
2026-10-18). A face switch whose every binding is a *hold* (hold to dictate / to command) loses
the face each time its user looks at the keyboard, and was left disarmed after every glance --
eyes-closed dictation stopped working within minutes of the first live run. Such a source may
re-arm itself after a continuous run of fresh samples, *only* from a staleness disarm: a user
:meth:`pause`, a reported :meth:`fault` and :meth:`shutdown` all still wait for :meth:`resume`.
It cannot replay anything (a hold still needs the gesture made anew, and the re-arm bumps the
epoch), and a lost face already forces the hold closed. Pointer and click sources never opt in.

**Containment.** Arming is per source. A stale face switch stops the face switch; it does not
stop the Head-Pointer, and neither stops speech. That is ADR-v2-148's recovery hierarchy —
"losing face tracking should not disable speech" — and it is why :class:`SafetyStatus` reports a
worst-case summary state *and* per-source health: the summary is for the human, the per-source
decision is the authority.

**Clearing pending state without callbacks.** Entering suppression must clear a half-accumulated
dwell and a half-detected gesture, or the first frame after recovery completes an activation the
user never intended. Rather than firing callbacks from whichever thread tripped the watchdog,
each source carries an epoch that is bumped on every entry into suppression and on every re-arm;
the next :meth:`gate` call for that source returns ``clear_pending=True`` exactly once. The
consumer pulls; nothing is pushed into it.

**On the staleness window.** ``SafetyLimits.stale_after_ms`` is **not a measured value.** No
frame-interval or tracking-loss distribution has been collected for this programme
(``design/eye-control/GOVERNANCE.md`` requires measurement before a threshold becomes a
recommended default, and ``TEST_PLAN.md`` has the slot but no data). 500 ms is a deliberately
generous placeholder: roughly fifteen frames at 30 fps, far outside ordinary scheduler jitter or
a dropped frame or two, and still short enough that a pointer driven by dead data stops before it
can cross a screen. ADR-021 judges a guard on how rarely it fires, and this guard's false trip
costs a hands-free user their input method until they re-arm, so the window errs long. It is a
placeholder to be replaced by measurement, not a recommendation.
"""
from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

#: Shipped staleness window, in milliseconds. Unmeasured — see the module docstring.
DEFAULT_STALE_AFTER_MS = 500.0


class SafetyState(Enum):
    """The three states ADR-v2-148 requires. Values are the strings status/doctor print."""

    ACTIVE = "active"
    PAUSED = "paused"
    FAULTED = "faulted"


@dataclass(frozen=True)
class SafetyLimits:
    """Watchdog limits.

    ``stale_after_ms`` is the age at which a source's newest sample stops being allowed to
    produce an action. A non-positive window cannot express a freshness judgement at all, so it
    falls back to the shipped default rather than being honoured into a guard that either fires
    constantly or never — the same "repair, do not obey nonsense" posture as the config loader.
    """

    stale_after_ms: float = DEFAULT_STALE_AFTER_MS

    def window_ms(self) -> float:
        """The staleness window actually applied. Pure."""
        value = float(self.stale_after_ms)
        if not (value > 0.0 and math.isfinite(value)):
            # NaN and +inf are as meaningless as zero: an infinite window would be a guard
            # that can never fire, which is the one failure this module exists to prevent.
            return DEFAULT_STALE_AFTER_MS
        return value


@dataclass(frozen=True)
class SourceHealth:
    """What the gate knows about one signal source. Contains no sample values — ADR-019."""

    name: str
    armed: bool
    stale: bool
    faulted: bool
    reason: str
    age_ms: float | None
    epoch: int

    @property
    def suppressed(self) -> bool:
        """Is this source barred from acting, for any reason? Pure."""
        return not self.armed or self.stale or self.faulted


@dataclass(frozen=True)
class SafetyStatus:
    """An observable snapshot, for `doctor`/status (#416) and the settings surface (#420).

    Carries names, ages and flags only: no landmark, pose, gaze point or switch value ever
    reaches it, so it is safe to print.
    """

    state: SafetyState
    reason: str
    terminal: bool
    user_paused: bool
    epoch: int
    sources: tuple[SourceHealth, ...]

    @property
    def suppressed(self) -> bool:
        """Is any action suppressed right now? Pure."""
        return self.state is not SafetyState.ACTIVE

    def source(self, name: str) -> SourceHealth | None:
        """The health of one source, or None if the gate has never heard of it. Pure."""
        for health in self.sources:
            if health.name == name:
                return health
        return None


@dataclass(frozen=True)
class Decision:
    """The answer to "may this source act right now?".

    ``clear_pending`` is a one-shot latch: it is True on the first decision after the source
    entered suppression and again on the first decision after it was re-armed. A consumer that
    sees it must drop its half-accumulated dwell / half-detected gesture before using
    ``allowed``.
    """

    allowed: bool
    clear_pending: bool
    state: SafetyState
    reason: str


@dataclass(frozen=True)
class RearmResult:
    """The outcome of an explicit re-arm."""

    ok: bool
    armed: tuple[str, ...]
    refused: tuple[str, ...]
    reason: str
    state: SafetyState


@dataclass
class _Source:
    """Mutable per-source book-keeping. Private; :class:`SourceHealth` is the public view."""

    name: str
    armed: bool = False
    last_sample_ms: float | None = None
    fault: str = ""
    epoch: int = 0
    seen_epoch: int = -1
    #: Disarmed by the watchdog alone (no pause, fault or shutdown since): the only kind of
    #: disarm :meth:`HandsFreeSafety.allow_auto_rearm` may undo.
    stale_disarmed: bool = False
    #: Start of the current unbroken run of fresh samples while ``stale_disarmed``.
    fresh_since_ms: float | None = None


def monotonic_ms() -> float:
    """Milliseconds from an arbitrary monotonic origin — the default clock. Not for wall time."""
    return time.monotonic() * 1000.0


class HandsFreeSafety:
    """One stop/pause state shared by every camera-driven input source.

    Construct it with the names of the sources that will drive actions::

        gate = HandsFreeSafety(("headpointer", "facegesture"))
        gate.sample("headpointer")          # a fresh pose arrived
        gate.resume()                       # explicit arm; nothing acts before this
        decision = gate.gate("headpointer")
        if decision.clear_pending:
            dwell.reset()
        if decision.allowed:
            move_cursor(...)

    Every source starts disarmed and without a sample, so a freshly built gate suppresses
    everything: ADR-v2-148's startup order requires staying PAUSED rather than partially firing.
    Note the order — :meth:`resume` refuses to arm a source that has no fresh signal, so a camera
    still warming up is armed by the resume *after* its first frame, not before. The refusal
    names the source rather than failing silently.

    ``limits`` comes from ``[handsfree_safety]`` at the call site; this module imports no config,
    so the pure layer stays pure. ``clock`` returns monotonic milliseconds and exists so a test
    can fabricate an entire timeline.
    """

    def __init__(
        self,
        sources: Iterable[str] = (),
        *,
        limits: SafetyLimits | None = None,
        clock: Callable[[], float] = monotonic_ms,
    ) -> None:
        self._limits = limits or SafetyLimits()
        self._clock = clock
        self._lock = threading.RLock()
        self._sources: dict[str, _Source] = {}
        self._user_paused = False
        self._pause_reason = ""
        self._terminal = False
        self._epoch = 0
        self._auto_rearm: dict[str, float] = {}
        for name in sources:
            self._sources.setdefault(name, _Source(name))

    # ---------------------------------------------------------------- signal intake

    def sample(self, source: str, *, at_ms: float | None = None) -> None:
        """Record that ``source`` delivered a fresh signal.

        An unknown name registers itself rather than raising: this is called from a capture loop,
        and a gate that throws there is a worse failure than a gate that learns a name. A source
        that has never sampled is suppressed anyway, so registration cannot open a hole.

        **A sample is also a watchdog tick.** If the source was armed and its previous sample is
        older than the window as of this one, it went stale in the gap and is disarmed *before*
        the new sample is recorded, so the watchdog's verdict does not depend on whether any
        consumer happened to call :meth:`gate` or :meth:`poll` during the silence.
        """
        now = self._clock() if at_ms is None else at_ms
        with self._lock:
            entry = self._sources.setdefault(source, _Source(source))
            if not math.isfinite(now):
                # A timestamp that is not a number is not evidence of life. Recording it would
                # make every later age NaN, and NaN compares False against any window: a dead
                # camera would read as fresh for ever. Ignoring it lets the source age out.
                return
            gap = self._is_stale(entry, now)
            if entry.armed and gap:
                # The signal was gone for longer than the window *before* this sample arrived.
                # Nobody may have asked the gate in the meantime (the face switch only asks on
                # a press; a suspended laptop asks nothing), so the lapse has to be judged
                # here, against the moment the new sample was taken. Recording the sample
                # first would erase the gap and let a returning camera silently resume.
                self._suppress(entry, stale=True)
            entry.last_sample_ms = now
            self._maybe_rearm_locked(entry, now, gap)

    def allow_auto_rearm(self, source: str, after_ms: float) -> None:
        """Let ``source`` re-arm itself after ``after_ms`` of unbroken fresh signal following a
        *staleness* disarm. Opt-in per source; see the module docstring for who may use it."""
        with self._lock:
            self._sources.setdefault(source, _Source(source))
            self._auto_rearm[source] = max(0.0, float(after_ms))

    def _maybe_rearm_locked(self, entry: _Source, now: float, gap: bool) -> None:
        after = self._auto_rearm.get(entry.name)
        if after is None or entry.armed or not entry.stale_disarmed:
            return
        if self._globally_suppressed() or entry.fault:
            entry.stale_disarmed = False  # a pause or fault took over: recovery is explicit again
            entry.fresh_since_ms = None
            return
        if gap or entry.fresh_since_ms is None:
            entry.fresh_since_ms = now  # the run of fresh samples (re)starts here
            return
        if now - entry.fresh_since_ms >= after:
            entry.armed = True
            entry.stale_disarmed = False
            entry.fresh_since_ms = None
            entry.epoch += 1
            self._epoch += 1

    def fault(self, source: str, reason: str) -> None:
        """Report a source/backend fault (permission denied, backend closed, model missing).

        Suppresses that source until :meth:`clear_fault` *and* an explicit :meth:`resume`, so a
        fault that clears on its own cannot quietly put a cursor back in motion (R-24).
        """
        with self._lock:
            entry = self._sources.setdefault(source, _Source(source))
            entry.fault = reason or "faulted"
            self._suppress(entry)

    def clear_fault(self, source: str) -> None:
        """Clear a reported fault. Does **not** re-arm: recovery stays explicit."""
        with self._lock:
            entry = self._sources.get(source)
            if entry is not None:
                entry.fault = ""

    # ---------------------------------------------------------------- stop / recover

    def pause(self, reason: str = "paused") -> None:
        """Enter PAUSED. Idempotent, and safe to call from any thread.

        This is the emergency stop behind every stop path ADR-v2-148 lists — voice command,
        keyboard key, configured switch, tray item — none of which may require pointing
        accurately with the pointer that is misbehaving. Calling it twice changes nothing: the
        second call does not re-bump the epochs, so a consumer is not told to clear state it has
        already cleared.
        """
        with self._lock:
            if self._user_paused:
                return
            self._user_paused = True
            self._pause_reason = reason or "paused"
            for entry in self._sources.values():
                self._suppress(entry)

    def shutdown(self, reason: str = "shutting down") -> None:
        """Enter the terminal suppressed state, before any backend is closed.

        ADR-v2-148's shutdown order suppresses actions first and releases backends afterwards, so
        nothing can fire into a half-closed pointer backend. Terminal: :meth:`resume` refuses
        afterwards, because a stopped daemon must not be re-armable from a stale reference.
        """
        with self._lock:
            self._terminal = True
            self._pause_reason = reason or "shutting down"
            self._user_paused = True
            for entry in self._sources.values():
                self._suppress(entry)

    def resume(self, sources: Iterable[str] | None = None) -> RearmResult:
        """Explicitly re-arm — the only way out of PAUSED or FAULTED.

        Refuses outright once :meth:`shutdown` has run. Refuses per source for anything still
        faulted or still stale, because arming a source whose data has not come back would only
        disarm it again on the next frame; the caller fixes the cause and asks again. Arming
        bumps the source's epoch, so the first decision after recovery carries
        ``clear_pending`` and no pose, switch or gaze target from before the interruption can be
        replayed.
        """
        with self._lock:
            if self._terminal:
                return RearmResult(
                    False, (), tuple(sorted(self._sources)), "shut down", self._state_locked()[0]
                )
            names = list(self._sources) if sources is None else list(sources)
            armed: list[str] = []
            refused: list[str] = []
            for name in names:
                entry = self._sources.setdefault(name, _Source(name))
                if entry.fault:
                    refused.append(name)
                    continue
                if self._is_stale(entry, self._clock()):
                    refused.append(name)
                    continue
                entry.armed = True
                entry.stale_disarmed = False
                entry.fresh_since_ms = None
                entry.epoch += 1
                self._epoch += 1
                armed.append(name)
            if armed:
                self._user_paused = False
                self._pause_reason = ""
            state, reason = self._state_locked()
            ok = bool(armed) and not refused
            return RearmResult(ok, tuple(armed), tuple(refused), reason, state)

    # ---------------------------------------------------------------- the hot path

    def gate(self, source: str, *, at_ms: float | None = None) -> Decision:
        """May ``source`` act right now? The one call every continuous consumer must make.

        Evaluates staleness first, so a source that aged out since the last frame is disarmed and
        denied on this one rather than one frame later.
        """
        now = self._clock() if at_ms is None else at_ms
        with self._lock:
            entry = self._sources.setdefault(source, _Source(source))
            self._evaluate_locked(now)
            state, reason = self._state_locked(now)
            clear_pending = entry.seen_epoch != entry.epoch
            entry.seen_epoch = entry.epoch
            allowed = not self._globally_suppressed() and self._source_ok(entry, now)
            if allowed:
                return Decision(True, clear_pending, state, "")
            return Decision(False, clear_pending, state, self._deny_reason(entry, now, reason))

    def poll(self, *, at_ms: float | None = None) -> SafetyStatus:
        """Run the watchdog without asking about a particular source, and report.

        A consumer that has stopped calling :meth:`gate` — because its own loop stalled — is
        exactly the case where nothing else would notice the signal had died, so the daemon may
        call this on its ordinary tick.
        """
        now = self._clock() if at_ms is None else at_ms
        with self._lock:
            self._evaluate_locked(now)
            return self._status_locked(now)

    def status(self, *, at_ms: float | None = None) -> SafetyStatus:
        """A snapshot for status/doctor. Same evaluation as :meth:`poll`; the name is the seam."""
        return self.poll(at_ms=at_ms)

    @property
    def state(self) -> SafetyState:
        """The current summary state. Pure read (it still runs the watchdog)."""
        return self.poll().state

    # ---------------------------------------------------------------- internals

    def _suppress(self, entry: _Source, *, stale: bool = False) -> None:
        """Disarm ``entry`` and bump its epoch iff this is an *entry* into suppression.

        The guard on ``armed`` is what makes :meth:`pause` idempotent all the way down: a second
        stop does not tell a consumer to clear state it cleared on the first. ``stale`` marks a
        watchdog disarm; any other suppression (pause, fault, shutdown) revokes auto re-arm.
        """
        if stale:
            if entry.armed:
                entry.stale_disarmed = True
                entry.fresh_since_ms = None
        else:
            entry.stale_disarmed = False
            entry.fresh_since_ms = None
        if entry.armed:
            entry.armed = False
            entry.epoch += 1
            self._epoch += 1

    def _is_stale(self, entry: _Source, now: float) -> bool:
        """Has ``entry``'s newest sample aged past the window, or never arrived? Pure.

        Fails *closed* on anything that is not a plain, plausible age. A non-finite clock
        reading, or a sample that appears to come from further in the future than the window
        (the clock went backwards, or the sample was stamped on a different clock), cannot be
        shown to be fresh, so it is treated as stale. Comparing such an age with ``>`` alone
        is the failure: NaN is never greater than anything, and a large negative age is never
        greater than the window, so a dead camera would look alive until the clock caught up.
        A small negative age (a frame stamped a moment after this thread read the clock) is
        ordinary scheduling and stays fresh.
        """
        if entry.last_sample_ms is None:
            return True
        age = now - entry.last_sample_ms
        if not math.isfinite(age):
            return True
        window = self._limits.window_ms()
        return age > window or age < -window

    def _age_ms(self, entry: _Source, now: float) -> float | None:
        if entry.last_sample_ms is None:
            return None
        age = now - entry.last_sample_ms
        return age if math.isfinite(age) else None

    def _stale_text(self, entry: _Source, now: float) -> str:
        """Why ``entry`` is stale, in words. An age that is not a plain positive one is a
        clock problem, and says so rather than printing a negative or missing age."""
        age = self._age_ms(entry, now)
        if age is None or age < 0.0:
            return "signal is stale (clock inconsistent)"
        return f"signal is stale ({age:.0f} ms old)"

    def _evaluate_locked(self, now: float) -> None:
        """The watchdog: disarm every source whose signal has gone quiet.

        Disarming rather than merely denying is the whole point. Denial alone would let the
        source act again the instant a sample reappeared — recovery would be automatic and
        silent, which is exactly what ADR-v2-148 forbids. Disarmed, it waits for :meth:`resume`.
        """
        for entry in self._sources.values():
            if entry.armed and self._is_stale(entry, now):
                self._suppress(entry, stale=True)

    def _globally_suppressed(self) -> bool:
        return self._terminal or self._user_paused

    def _source_ok(self, entry: _Source, now: float) -> bool:
        return entry.armed and not entry.fault and not self._is_stale(entry, now)

    def _deny_reason(self, entry: _Source, now: float, state_reason: str) -> str:
        if self._globally_suppressed():
            return self._pause_reason or state_reason or "suppressed"
        if entry.fault:
            return f"{entry.name}: {entry.fault}"
        if entry.last_sample_ms is None:
            return f"{entry.name}: no signal yet"
        if self._is_stale(entry, now):
            return f"{entry.name}: {self._stale_text(entry, now)}"
        return f"{entry.name}: awaiting re-arm"

    def _state_locked(self, now: float | None = None) -> tuple[SafetyState, str]:
        """Summary state + one human reason. Order is deliberate; see the module docstring."""
        moment = self._clock() if now is None else now
        if self._terminal:
            return SafetyState.PAUSED, self._pause_reason or "shut down"
        if self._user_paused:
            return SafetyState.PAUSED, self._pause_reason or "paused"
        for entry in self._sources.values():
            if entry.fault:
                return SafetyState.FAULTED, f"{entry.name}: {entry.fault}"
        for entry in self._sources.values():
            if entry.last_sample_ms is not None and self._is_stale(entry, moment):
                return SafetyState.FAULTED, f"{entry.name}: {self._stale_text(entry, moment)}"
        for entry in self._sources.values():
            if entry.last_sample_ms is None:
                return SafetyState.PAUSED, f"{entry.name}: no signal yet"
        for entry in self._sources.values():
            if not entry.armed:
                return SafetyState.PAUSED, f"{entry.name}: awaiting re-arm"
        if not self._sources:
            return SafetyState.PAUSED, "no input sources"
        return SafetyState.ACTIVE, ""

    def _status_locked(self, now: float) -> SafetyStatus:
        state, reason = self._state_locked(now)
        healths = tuple(
            SourceHealth(
                name=entry.name,
                armed=entry.armed,
                stale=self._is_stale(entry, now),
                faulted=bool(entry.fault),
                reason=entry.fault,
                age_ms=self._age_ms(entry, now),
                epoch=entry.epoch,
            )
            for entry in sorted(self._sources.values(), key=lambda s: s.name)
        )
        return SafetyStatus(
            state=state,
            reason=reason,
            terminal=self._terminal,
            user_paused=self._user_paused,
            epoch=self._epoch,
            sources=healths,
        )


class SafetySection(Protocol):
    """The shape of ``[handsfree_safety]``, structurally — not an import of the config module."""

    enabled: bool
    stale_after_ms: int


class SafetyConfig(Protocol):
    """Anything carrying a ``handsfree_safety`` section — in practice ``yazses.config.Config``.

    Stated as a Protocol rather than imported so the pure layer can read the user's settings
    without depending on the config module: structural typing gives the call site and mypy the
    real shape, and this file still never learns what a `Config` is.
    """

    handsfree_safety: SafetySection


def gate_from_config(
    cfg: SafetyConfig,
    sources: Iterable[str] = (),
    *,
    clock: Callable[[], float] = monotonic_ms,
) -> HandsFreeSafety | None:
    """Build the gate from ``[handsfree_safety]``, or None when the user has not opted in.

    The one place the off-by-default rule is enforced, so no consumer has to remember it. A
    ``None`` gate means the hands-free safety state is not in play at all and the existing
    camera features behave exactly as they did before this section existed — which is what
    "an existing install is unchanged until the user opts in" has to mean for a *suppression*
    feature: it cannot be the thing that silently stops an already-working pointer.
    """
    section = cfg.handsfree_safety
    if not section.enabled:
        return None
    return HandsFreeSafety(
        sources,
        limits=SafetyLimits(stale_after_ms=float(section.stale_after_ms)),
        clock=clock,
    )
