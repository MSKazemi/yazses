"""Whether this Linux session can offer an accessibility backend, and the factory (#164).

``build_platform`` calls :func:`accessibility_route` on every start, so this module is
kept light on purpose: it imports neither ``pyatspi`` nor the ``grounding`` package. The
backend itself (``platform/linux/atspi_tree.py``) is imported by the factory, which runs
only when Screen-Grounded Dictation or the Voice Pilot first needs it.
"""

from __future__ import annotations

import importlib.util
import os
from collections.abc import Callable, Mapping
from typing import Any

#: The remedy for a missing binding, in the words `doctor` and the target guard use.
INSTALL_HINT = "apt install python3-pyatspi gir1.2-atspi-2.0"

#: Why the Linux bundle offers no accessibility backend, one sentence each.
ATSPI_MISSING_REASON = (
    "the AT-SPI Python bindings (pyatspi) are not installed, so the focused window cannot "
    f"be read; install them from your distribution ({INSTALL_HINT})"
)
HEADLESS_ACCESSIBILITY_REASON = (
    "no desktop session was detected (neither DISPLAY nor WAYLAND_DISPLAY is set), so "
    "there is no window to read"
)


def build_atspi_accessibility() -> Any:
    """The ``Platform.accessibility_factory`` for Linux. Opens nothing until first use."""
    from yazses.platform.linux.atspi_tree import AtspiAccessibility

    return AtspiAccessibility()


def accessibility_route(
    environ: Mapping[str, str] | None = None,
    *,
    find_spec: Callable[[str], Any] = importlib.util.find_spec,
) -> tuple[Callable[[], Any] | None, str | None]:
    """``(factory, None)`` when AT-SPI can work here; ``(None, reason)`` when it cannot.

    Decided when the bundle is built, without importing ``pyatspi`` -- `find_spec` only
    locates it -- so `get_platform()` stays cheap for the user who never enables either
    feature. Works on X11 and on Wayland: AT-SPI is a D-Bus service, not an X extension.
    A located binding can still find no accessibility bus at runtime; that case reads as
    an empty snapshot, and the consumer says so.
    """
    env = os.environ if environ is None else environ
    has_display = bool((env.get("DISPLAY", "") or "").strip()
                       or (env.get("WAYLAND_DISPLAY", "") or "").strip())
    if not has_display:
        return None, HEADLESS_ACCESSIBILITY_REASON
    try:
        located = find_spec("pyatspi") is not None
    except Exception:
        located = False
    if not located:
        return None, ATSPI_MISSING_REASON
    return build_atspi_accessibility, None


__all__ = [
    "ATSPI_MISSING_REASON",
    "HEADLESS_ACCESSIBILITY_REASON",
    "INSTALL_HINT",
    "accessibility_route",
    "build_atspi_accessibility",
]
