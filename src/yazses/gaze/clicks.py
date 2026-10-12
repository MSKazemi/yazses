"""A desktop click, as implicit calibration may see it — and nothing more (#397).

Implicit gaze calibration (#101) treats an ordinary mouse click as ground truth for
"where the user was looking a moment ago". The only thing the estimator needs from the
desktop is therefore *where* and *when*: two coordinates and a timestamp. This module
is that boundary, and it is deliberately the narrowest one a click can be.

:class:`ClickEvent` has no field for which button, which window, which application or
what was under the pointer. That is not an omission to be filled in later: a click
observer that could report a window title or a typed character would be a keylogger with
extra steps, and the spec for this feature (``design/specs/eye-implicit-calibration.md``)
forbids raw click text, screenshots and frames in so many words. A field that does not
exist cannot be filled in by a backend that has more access than it should, which is why
privacy here is structural rather than a review habit — the same rule
``yazses.eyeeval.schema`` applies to result documents.

:class:`ClickObserver` is the Protocol a platform backend implements. It lives beside the
value (as ``yazses.pointer.base`` does for the pointer) rather than in
``yazses.platform.base`` so that this file stays standard-library-only; ``platform.base``
imports it and carries the optional factory, and CI drives the estimator with a fake
observer that needs no desktop.

Nothing here observes anything. A backend that does must listen **only while started**,
deliver an event per click, and never retain one: the callback is the sole consumer.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

__all__ = ["ClickEvent", "ClickObserver", "ClickObserverError"]


class ClickObserverError(RuntimeError):
    """A click observer could not start (no permission, no display, unsupported session).

    Raised from :meth:`ClickObserver.start` so the caller can say *why* implicit
    refinement is dormant instead of silently never receiving a click. A message must
    describe the failure, never carry pointer or window content.
    """


@dataclass(frozen=True)
class ClickEvent:
    """One click: when, and where on the desktop.

    ``timestamp_s`` is a :func:`time.monotonic` reading — the **same clock** the shared
    perception source stamps gaze samples with, because association is a difference
    between the two. ``x``/``y`` are in the canonical desktop space of ADR-v2-149 (logical
    pixels; negative values are legitimate on a monitor left of or above the primary).

    Both are validated finite: a NaN coordinate would compare false against every
    residual gate and slip through as a "close" click.
    """

    timestamp_s: float
    x: float
    y: float

    def __post_init__(self) -> None:
        for name in ("timestamp_s", "x", "y"):
            number = float(getattr(self, name))
            if not math.isfinite(number):
                raise ValueError(f"ClickEvent.{name} must be a finite number, got {number!r}")
            object.__setattr__(self, name, number)


@runtime_checkable
class ClickObserver(Protocol):
    """Reports desktop clicks while started. One implementation per display server."""

    def start(self, on_click: Callable[[ClickEvent], None]) -> None:
        """Begin delivering clicks to *on_click*; raise :class:`ClickObserverError` if unable.

        The callback is invoked from the observer's own thread, must be quick, and must
        not raise into the observer — an exception there is the callback's to contain.
        Starting an already-started observer is a no-op.
        """
        ...

    def stop(self) -> None:
        """Stop delivering clicks and release the OS hook. Idempotent; never raises."""
        ...
