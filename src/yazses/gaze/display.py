"""Read the live display topology from the display server (ADR-v2-149 backend seam).

The decision -- is this calibration still valid? -- lives in :mod:`yazses.gaze.topology`
and is pure. This module is the other half of the house split: the part that has to talk
to something real, kept behind a Protocol so every test fabricates a topology instead of
needing two monitors.

Two pieces, and the split is deliberate:

* :func:`parse_xrandr` is a **pure text function**. The interesting failure modes of a
  topology reader are parsing ones -- a negative origin, a disconnected output, a rotated
  panel -- and all of them are reachable from a captured string, with no X server.
* :class:`XrandrTopology` is the thin part that spawns ``xrandr`` and hands its stdout to
  that function. Its command runner is injectable, exactly as ``XdotoolDesktop`` does it.

:func:`build_topology_provider` follows ``gaze/desktop.py``: it returns ``None`` off X11 or
when the tool is absent, and the caller then reports an *unverified* calibration rather
than a stale one -- not being able to read the layout is not evidence that it changed.

**Known limitation, stated rather than faked.** X11's framebuffer coordinates already are
the logical space applications see, and ``xrandr`` exposes no per-output HiDPI factor that
means what Wayland/macOS/Windows mean by "scale". So this provider reports ``scale=1.0``
for every output. The *model* carries scale, the fixtures exercise non-1.0 values, and a
Wayland/macOS/Windows provider can fill it in; inventing a number here from the physical
millimetre size would produce a fingerprint that flickers with a monitor's EDID rather
than with anything the user changed.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from typing import Callable, Protocol, runtime_checkable

from yazses.gaze.topology import (
    CALIBRATION_MODEL,
    CANONICAL_SPACE,
    CalibrationContext,
    Display,
    DisplayTopology,
)

log = logging.getLogger(__name__)

#: ``<name> connected [primary] 1920x1080+0+0 ...`` -- the sign is captured because a
#: monitor placed left of or above the primary one has a negative origin.
_OUTPUT_RE = re.compile(
    r"^(?P<name>\S+)\s+connected\s+(?P<primary>primary\s+)?"
    r"(?P<w>\d+)x(?P<h>\d+)(?P<x>[+-]\d+)(?P<y>[+-]\d+)"
)


@runtime_checkable
class DisplayTopologyProvider(Protocol):
    """Read the current display topology in canonical desktop coordinates."""

    def current_topology(self) -> DisplayTopology:
        """Return the live topology, or an empty (unknown) one if it cannot be read."""
        ...


def parse_xrandr(text: str) -> DisplayTopology:
    """Parse ``xrandr --query`` output into a :class:`DisplayTopology`. Pure.

    Only *connected outputs with an active mode* become displays: an output can be
    connected and switched off, in which case xrandr prints no geometry and it
    occupies no desktop coordinates. Unparseable input yields an empty topology,
    which reads as "unknown" and never as "the monitors went away".
    """
    displays: list[Display] = []
    for line in text.splitlines():
        m = _OUTPUT_RE.match(line.strip())
        if m is None:
            continue
        try:
            displays.append(
                Display(
                    identifier=m.group("name"),
                    x=int(m.group("x")),
                    y=int(m.group("y")),
                    width=int(m.group("w")),
                    height=int(m.group("h")),
                    scale=1.0,
                    primary=bool(m.group("primary")),
                )
            )
        except ValueError:
            continue  # a zero-size mode is not a display
    return DisplayTopology(displays=tuple(displays))


class XrandrTopology:
    """:class:`DisplayTopologyProvider` over the ``xrandr`` CLI (X11)."""

    def __init__(self, runner: Callable[[list[str]], str] | None = None) -> None:
        self._run = runner or self._default_runner

    @staticmethod
    def _default_runner(argv: list[str]) -> str:
        return subprocess.run(
            argv, capture_output=True, text=True, timeout=2.0, check=True
        ).stdout

    def current_topology(self) -> DisplayTopology:
        try:
            out = self._run(["xrandr", "--query"])
        except Exception:
            log.debug("xrandr --query failed; display topology unknown", exc_info=True)
            return DisplayTopology()
        return parse_xrandr(out)


def build_topology_provider() -> DisplayTopologyProvider | None:
    """Return an X11 topology provider, or ``None`` when unavailable.

    None off X11 or without ``xrandr``. Callers treat that as *unknown*, not as a
    changed layout -- see :func:`yazses.gaze.topology.check_context`.
    """
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    if session and session != "x11":
        log.debug("Display topology needs X11 (session=%r); calibration unverified.", session)
        return None
    if shutil.which("xrandr") is None:
        log.debug("Display topology needs xrandr; not found. Calibration unverified.")
        return None
    return XrandrTopology()


def current_context(
    *,
    camera_id: str = "",
    camera_size: tuple[int, int] = (0, 0),
    provider: DisplayTopologyProvider | None = None,
) -> CalibrationContext:
    """Build the calibration context describing *this* machine right now.

    ``provider=None`` asks :func:`build_topology_provider` for one; if there is none,
    the context carries an empty topology and the comparison reports *unverified*.
    """
    if provider is None:
        provider = build_topology_provider()
    topology = provider.current_topology() if provider is not None else DisplayTopology()
    return CalibrationContext(
        topology=topology,
        camera_id=camera_id,
        camera_width=camera_size[0],
        camera_height=camera_size[1],
        model=CALIBRATION_MODEL,
        space=CANONICAL_SPACE,
    )
