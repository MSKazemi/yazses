"""The camera on/off switch: one runtime state for every camera feature (#922, #924).

A webcam is a single exclusive device on most systems. A feature that holds it
blocks every other application, so the user needs one switch that releases the
device *now*, without editing config and without restarting, and that leaves
voice dictation untouched. This module is that switch, and nothing else.

It is a runtime state, not a config key: nothing here is persisted, and the daemon
always starts with the camera ON (the existing behaviour for anyone who enabled a
camera feature). A camera feature that is not enabled never registers, so
switching a camera "on" never starts something the user did not opt into.

A **covered** camera (a privacy shutter, #923) is a second, separate reason to hold
nothing: :meth:`CameraSwitch.cover` releases the owners of one camera index and
:meth:`CameraSwitch.uncover` gives it back, without touching the user's ON/OFF
state. Only ``perception/coverwatch.py`` calls them, and every user transition
(on, off, use) forgets the covered verdict, so ``camera on`` is also "look again".

Pure: no OpenCV, no threads, no I/O. Each camera owner registers a
:class:`CameraConsumer` -- how to let go of the device, how to take it back, and
who holds it right now -- and the switch drives them. A consumer that raises is
contained and reported; one failing never stops the others, and nothing here can
reach the dictation path.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = ["CameraConsumer", "CameraStatus", "CameraSwitch"]

log = logging.getLogger(__name__)

#: Longest failure reason kept; a camera error is a sentence, not a payload.
_MAX_REASON = 200


def _no_holders() -> tuple[str, ...]:
    return ()


def _no_failure() -> str:
    return ""


@dataclass(frozen=True)
class CameraConsumer:
    """One owner of the camera device, as the switch drives it.

    ``pause`` must release the device (or ask the owner's loop to, then return).
    ``resume`` may reopen lazily; a reopen that fails is reported through
    ``failure``. ``holders`` names the features that hold the device *right now*
    (empty when it is closed) and ``failure`` is the reason the last reopen
    failed, or ``""``.
    """

    name: str
    pause: Callable[[], None]
    resume: Callable[[], None]
    holders: Callable[[], tuple[str, ...]] = _no_holders
    failure: Callable[[], str] = _no_failure
    #: Point this owner at another camera index; takes effect at the next open (#924).
    set_index: Callable[[int], None] | None = None
    #: Which camera this owner opens, or None when it opens none of its own. Without
    #: it a covered camera cannot release this owner.
    camera_index: Callable[[], int | None] | None = None


def _index_of(consumer: CameraConsumer) -> int | None:
    if consumer.camera_index is None:
        return None
    try:
        return consumer.camera_index()
    except Exception:
        log.debug("camera_index() raised for %s", consumer.name, exc_info=True)
        return None


@dataclass(frozen=True)
class CameraStatus:
    """What `yazses camera status` reports."""

    on: bool
    holders: tuple[str, ...]
    failures: dict[str, str] = field(default_factory=dict)
    consumers: tuple[str, ...] = ()
    #: The camera chosen at runtime with ``yazses camera use``, or None.
    active: dict[str, object] | None = None
    #: Camera indexes released because they look covered (#923).
    covered: tuple[int, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "active": dict(self.active) if self.active else None,
            "state": "on" if self.on else "off",
            "holders": list(self.holders),
            "failures": dict(self.failures),
            "consumers": list(self.consumers),
            "covered": list(self.covered),
        }


class CameraSwitch:
    """Thread-safe ON/OFF state plus the camera owners it drives."""

    def __init__(self, *, on: bool = True) -> None:
        self._lock = threading.RLock()
        #: Held for a whole on/off/use transition, never while observers run.
        self._transition = threading.RLock()
        self._on = bool(on)
        self._consumers: list[CameraConsumer] = []
        self._observers: list[Callable[[bool], None]] = []
        self._held_logged: tuple[str, ...] = ()
        self._active: dict[str, object] | None = None
        self._covered: set[int] = set()
        self._generation = 0
        self._guards: list[Callable[[], None]] = []

    @property
    def is_on(self) -> bool:
        return self._on

    @property
    def covered(self) -> tuple[int, ...]:
        """Camera indexes released because they look covered (sorted)."""
        with self._lock:
            return tuple(sorted(self._covered))

    @property
    def generation(self) -> int:
        """Counts user transitions; a verdict reached before the last one is stale."""
        return self._generation

    def add_guard(self, guard: Callable[[], None]) -> None:
        """Call *guard* at the start of every user transition, before any owner moves.

        For whoever opens the camera outside the owners (the cover probe): it returns
        once the device is free.
        """
        with self._lock:
            self._guards.append(guard)

    def _user_transition(self) -> None:
        """The caller holds ``_transition``."""
        with self._lock:
            self._generation += 1
            guards = list(self._guards)
        for guard in guards:
            try:
                guard()
            except Exception:
                log.debug("camera switch guard raised", exc_info=True)

    def register(self, consumer: CameraConsumer) -> None:
        """Add a camera owner. If the switch is already OFF it is paused at once."""
        with self._transition:
            with self._lock:
                self._consumers.append(consumer)
                off = not self._on or _index_of(consumer) in self._covered
            if off:
                self._pause_one(consumer)

    def subscribe(self, observer: Callable[[bool], None]) -> Callable[[], None]:
        """Call ``observer(is_on)`` after every change. Returns an unsubscribe function."""
        with self._lock:
            self._observers.append(observer)

        def _unsubscribe() -> None:
            with self._lock:
                if observer in self._observers:
                    self._observers.remove(observer)

        return _unsubscribe

    def set(self, on: bool) -> bool:
        """Switch ON or OFF. Returns True when the state changed.

        The whole transition holds one lock, so concurrent on/off/use calls run one
        after another and the owners always end in the state :attr:`is_on` reports.
        Observers run after it is released. Never raises: a consumer that cannot
        release or reopen is logged and shows up in :meth:`status` as a failure.
        """
        on = bool(on)
        with self._transition:
            self._user_transition()
            changed = self._apply(on)
        if changed:
            self._announce([on])
        return changed

    def _apply(self, on: bool) -> bool:
        """One transition; the caller holds ``_transition``. No observers here."""
        with self._lock:
            covered, self._covered = self._covered, set()
            if on == self._on:
                retry = [
                    c for c in self._consumers
                    if self._failed(c) or _index_of(c) in covered
                ] if on else []
                changed = False
            else:
                self._on = on
                retry = []
                changed = True
            consumers = list(self._consumers)
        if not changed:
            # Already ON: "camera on" is also the retry for an owner whose last
            # reopen failed (a camera another app held), and takes a covered camera
            # back for another look. Healthy owners are untouched.
            for consumer in retry:
                self._resume_one(consumer)
            return False
        if on:
            log.info("Camera switched ON: resuming camera features.")
        else:
            log.info("Camera switched OFF: releasing the camera for other applications.")
        # Let go in reverse registration order, take back in registration order.
        for consumer in consumers if on else reversed(consumers):
            if on:
                self._resume_one(consumer)
            else:
                self._pause_one(consumer)
        return True

    @staticmethod
    def _failed(consumer: CameraConsumer) -> bool:
        try:
            return bool(consumer.failure())
        except Exception:
            return False

    def _announce(self, states: list[bool]) -> None:
        """Tell observers about each state, outside the transition lock."""
        with self._lock:
            observers = list(self._observers)
        for on in states:
            for observer in observers:
                try:
                    observer(on)
                except Exception:
                    log.debug("camera switch observer raised", exc_info=True)
        self.note_holders()

    def use_camera(self, index: int, name: str = "") -> bool:
        """Point every camera owner at *index*, reopening if the switch is ON (#924).

        OFF -> swap the index -> ON, so the device is never held on the old camera
        while the new one opens. If the switch was already OFF, the new index is
        stored and used at the next ``on``. The whole sequence is one transition: a
        concurrent ``on``/``off`` waits for it. Never raises; a failed reopen shows up
        in :meth:`status`. Returns True when the switch ended ON.
        """
        states: list[bool] = []
        with self._transition:
            self._user_transition()
            with self._lock:
                was_on = self._on
                consumers = list(self._consumers)
            if was_on and self._apply(False):
                states.append(False)
            for consumer in consumers:
                if consumer.set_index is None:
                    continue
                try:
                    consumer.set_index(int(index))
                except Exception:
                    log.warning("Camera feature %s could not switch to camera %d.",
                                consumer.name, index, exc_info=True)
            with self._lock:
                self._active = {"index": int(index), "name": str(name)}
            log.info("Camera selected: %s (index %d).", name or "unnamed", index)
            if was_on and self._apply(True):
                states.append(True)
            ended_on = self._on
        if states:
            self._announce(states)
        return ended_on

    @property
    def active(self) -> dict[str, object] | None:
        with self._lock:
            return dict(self._active) if self._active else None

    def toggle(self) -> bool:
        """Flip the state; returns the new state (True = ON)."""
        with self._transition:
            self._user_transition()
            target = not self._on
            changed = self._apply(target)
            ended_on = self._on
        if changed:
            self._announce([target])
        return ended_on

    def cover(self, index: int, generation: int | None = None) -> bool:
        """Release camera *index* because it looks covered. True when newly released.

        Refused while the switch is OFF, when no owner uses that camera, and when the
        user has switched since *generation* was read.
        """
        with self._transition:
            with self._lock:
                if not self._on or index in self._covered:
                    return False
                if generation is not None and generation != self._generation:
                    return False
                owners = [c for c in self._consumers if _index_of(c) == index]
                if not owners:
                    return False
                self._covered.add(index)
            for consumer in reversed(owners):
                self._pause_one(consumer)
        self.note_holders()
        return True

    def uncover(self, index: int, generation: int | None = None) -> bool:
        """Give camera *index* back to its owners. True when it was covered."""
        with self._transition:
            with self._lock:
                if not self._on or index not in self._covered:
                    return False
                if generation is not None and generation != self._generation:
                    return False
                self._covered.discard(index)
                owners = [c for c in self._consumers if _index_of(c) == index]
            for consumer in owners:
                self._resume_one(consumer)
        self.note_holders()
        return True

    def held_indices(self) -> tuple[int, ...]:
        """Camera indexes some owner holds right now (sorted)."""
        with self._lock:
            consumers = list(self._consumers)
        found: set[int] = set()
        for consumer in consumers:
            index = _index_of(consumer)
            if index is None:
                continue
            try:
                if consumer.holders():
                    found.add(index)
            except Exception:
                log.debug("camera holders() raised for %s", consumer.name, exc_info=True)
        return tuple(sorted(found))

    def holders(self) -> tuple[str, ...]:
        """Which camera features hold the device right now (sorted, de-duplicated)."""
        with self._lock:
            consumers = list(self._consumers)
        names: set[str] = set()
        for consumer in consumers:
            try:
                names.update(str(n) for n in consumer.holders())
            except Exception:
                log.debug("camera holders() raised for %s", consumer.name, exc_info=True)
        return tuple(sorted(names))

    def note_holders(self) -> tuple[str, ...]:
        """Log one line when the set of holders changed since the last call (#922 item 4)."""
        current = self.holders()
        with self._lock:
            previous = self._held_logged
            self._held_logged = current
        if current != previous:
            if current:
                log.info("Camera is held by: %s.", ", ".join(current))
            else:
                log.info("Camera is not held by YazSes.")
        return current

    def status(self) -> CameraStatus:
        with self._lock:
            consumers = list(self._consumers)
            on = self._on
        failures: dict[str, str] = {}
        for consumer in consumers:
            try:
                reason = str(consumer.failure() or "")
            except Exception:
                reason = ""
            if reason and on:
                failures[consumer.name] = reason[:_MAX_REASON]
        return CameraStatus(
            on=on,
            holders=self.holders(),
            failures=failures,
            consumers=tuple(c.name for c in consumers),
            active=self.active,
            covered=self.covered,
        )

    @staticmethod
    def _pause_one(consumer: CameraConsumer) -> None:
        try:
            consumer.pause()
        except Exception:
            log.warning("Camera feature %s could not release the camera.",
                        consumer.name, exc_info=True)

    @staticmethod
    def _resume_one(consumer: CameraConsumer) -> None:
        try:
            consumer.resume()
        except Exception:
            log.warning("Camera feature %s could not reopen the camera.",
                        consumer.name, exc_info=True)
