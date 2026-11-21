"""The camera on/off switch: one runtime state for every camera feature (#922, #924).

A webcam is a single exclusive device on most systems. A feature that holds it
blocks every other application, so the user needs one switch that releases the
device *now*, without editing config and without restarting, and that leaves
voice dictation untouched. This module is that switch, and nothing else.

It is a runtime state, not a config key: nothing here is persisted, and the daemon
always starts with the camera ON (the existing behaviour for anyone who enabled a
camera feature). A camera feature that is not enabled never registers, so
switching a camera "on" never starts something the user did not opt into.

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


@dataclass(frozen=True)
class CameraStatus:
    """What `yazses camera status` reports."""

    on: bool
    holders: tuple[str, ...]
    failures: dict[str, str] = field(default_factory=dict)
    consumers: tuple[str, ...] = ()

    def as_payload(self) -> dict[str, object]:
        return {
            "state": "on" if self.on else "off",
            "holders": list(self.holders),
            "failures": dict(self.failures),
            "consumers": list(self.consumers),
        }


class CameraSwitch:
    """Thread-safe ON/OFF state plus the camera owners it drives."""

    def __init__(self, *, on: bool = True) -> None:
        self._lock = threading.RLock()
        self._on = bool(on)
        self._consumers: list[CameraConsumer] = []
        self._observers: list[Callable[[bool], None]] = []
        self._held_logged: tuple[str, ...] = ()

    @property
    def is_on(self) -> bool:
        return self._on

    def register(self, consumer: CameraConsumer) -> None:
        """Add a camera owner. If the switch is already OFF it is paused at once."""
        with self._lock:
            self._consumers.append(consumer)
            off = not self._on
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

        Never raises: a consumer that cannot release or reopen is logged and shows
        up in :meth:`status` as a failure.
        """
        on = bool(on)
        with self._lock:
            if on == self._on:
                return False
            self._on = on
            consumers = list(self._consumers)
            observers = list(self._observers)
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
        for observer in observers:
            try:
                observer(on)
            except Exception:
                log.debug("camera switch observer raised", exc_info=True)
        self.note_holders()
        return True

    def toggle(self) -> bool:
        """Flip the state; returns the new state (True = ON)."""
        with self._lock:
            target = not self._on
        self.set(target)
        return self._on

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
