"""Which companion-app route reaches which device, and what each can give the binder.

Pure and static, like :mod:`yazses.xr.devices`. A *route* is one way a headset app gets
pointing data to the desktop: the native OpenXR runtime, a WebXR page, or Apple's
visionOS APIs. :mod:`yazses.xr.engines` is not a route; it converts the axes of whatever
engine the app is built in, on top of any of them.

``continuous_pointing`` says whether the route offers a pointing ray *between* gestures.
Deixis binding (:mod:`yazses.xr.binding`) needs a rolling ray history around the word
onset, so a route that exposes a ray only at the pinch moment cannot bind on its own and
the binder abstains rather than guesses. That is a property of the platform, not a bug.

A route's claims come from the integrator pages named in ``guide``, each of which marks
what it could not verify; ``None`` means unknown and is never read as "no".
"""
from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType

from yazses.xr import engines, openxr, visionos, webxr
from yazses.xr.types import RaySource


@dataclass(frozen=True)
class Route:
    """One way a companion app can reach the adapter."""

    key: str
    display_name: str
    module: ModuleType
    guide: str  # docs/ page, relative to docs/
    ray_sources: tuple[RaySource, ...]
    continuous_pointing: bool | None
    devices: tuple[str, ...]  # keys in :mod:`yazses.xr.devices`
    caveat: str


_ROUTES: tuple[Route, ...] = (
    Route(
        key="openxr",
        display_name="OpenXR runtime (native companion app)",
        module=openxr,
        guide="xr-openxr.md",
        ray_sources=(RaySource.EYE, RaySource.HAND, RaySource.CONTROLLER),
        continuous_pointing=True,
        devices=("generic-openxr", "meta-quest", "android-xr"),
        caveat=(
            "Eye gaze is an optional extension the runtime may not grant; Android XR as an "
            "OpenXR runtime is an unverified assumption."
        ),
    ),
    Route(
        key="webxr",
        display_name="WebXR page in the headset browser",
        module=webxr,
        guide="xr-webxr.md",
        ray_sources=(RaySource.HEAD, RaySource.HAND, RaySource.CONTROLLER),
        continuous_pointing=None,
        devices=("meta-quest", "vision-pro", "android-xr"),
        caveat=(
            "The `transient-pointer` mode (Safari on visionOS) lists no input source until a "
            "pinch, so there is no ray history; `gaze` mode is a head ray, not an eye ray."
        ),
    ),
    Route(
        key="visionos",
        display_name="visionOS native app (ARKit hands, system pinch events)",
        module=visionos,
        guide="xr-visionos.md",
        ray_sources=(RaySource.HAND, RaySource.HEAD, RaySource.EYE),
        continuous_pointing=False,
        devices=("vision-pro",),
        caveat=(
            "Apps are not given continuous eye gaze; the only gaze-derived ray arrives at the "
            "pinch moment (tagged EYE here, but it is one sample, not a stream)."
        ),
    ),
)

_BY_KEY: dict[str, Route] = {r.key: r for r in _ROUTES}

#: The converter layer that sits on top of any route; documented in ``xr-engines.md``.
ENGINE_CONVERTERS = engines


def keys() -> tuple[str, ...]:
    """Route keys in registry order."""
    return tuple(r.key for r in _ROUTES)


def get(key: str) -> Route:
    """Look a route up by key; the KeyError lists the valid keys."""
    try:
        return _BY_KEY[key]
    except (KeyError, TypeError):
        raise KeyError(f"unknown XR route {key!r}; known routes: {', '.join(keys())}") from None


def routes_for_device(device_key: str) -> tuple[Route, ...]:
    """Routes that can reach a device profile (may be empty, e.g. a phone companion)."""
    return tuple(r for r in _ROUTES if device_key in r.devices)
