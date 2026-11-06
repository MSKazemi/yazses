"""What the overlay's windows say to assistive technology. Pure; nothing here imports Qt.

Every overlay window (the sonar glow, the Voice Mouse Grid, the Mouth-Sound Switch scan
strip) is frameless, click-through and never takes focus -- correctly, since a click or a
keystroke aimed at the application underneath must not land on them. The cost of that is
that they used to be *anonymous* to a screen reader: an unnamed top-level window with no
description, and the scan strip said which item was lit only by painting it in the accent
colour. A user who drives the scan with a mouth sound and listens rather than looks (low
vision, or simply sitting far from the screen) had no way to learn what a "select" would
pick.

The widgets stay thin painters; the words live here so they can be tested without Qt.
Names are short and stable (a screen reader announces them on every focus change);
descriptions carry the state and change only when the state does.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # the sonar window imports this module; it must not pull the grid in
    from yazses.overlay.grid import GridSnapshot

__all__ = [
    "GRID_NAME",
    "SCAN_NAME",
    "SONAR_DESCRIPTION",
    "SONAR_NAME",
    "grid_description",
    "scan_description",
]

#: The window title and accessible name of each overlay window.
SONAR_NAME = "YazSes listening indicator"
GRID_NAME = "YazSes mouse grid"
SCAN_NAME = "YazSes switch scan"

#: The sonar's state is "visible = listening"; a hidden window is never announced, so a
#: fixed description is enough and never goes stale.
SONAR_DESCRIPTION = (
    "Shown while YazSes is listening. The rings grow with your voice. "
    "It does not take focus or clicks."
)


def scan_description(labels: tuple[str, ...], index: int) -> str:
    """``"Click selected, 2 of 4: Copy, Click, Paste, Stop"`` -- or ``""`` with no scan.

    Says the lit item first (it is what changes, and what a "select" would pick), then
    its position and the whole list, so the state reaches the user in words and not only
    as a coloured cell. Labels are capitalised exactly as ``scan_widget`` paints them, so
    the spoken and the drawn text agree. ``""`` for the same inputs ``strip_layout``
    treats as nothing to draw.
    """
    n = len(labels)
    if n == 0 or not 0 <= index < n:
        return ""
    shown = [str(label).capitalize() for label in labels]
    return f"{shown[index]} selected, {index + 1} of {n}: {', '.join(shown)}"


def grid_description(snap: GridSnapshot) -> str:
    """``"3 by 3 grid, cells 1 to 9. Say a number to move the pointer there."`` or ``""``."""
    if not snap.active or snap.region is None:
        return ""
    total = snap.cols * snap.rows
    return (
        f"{snap.cols} by {snap.rows} grid, cells 1 to {total}. "
        "Say a number to move the pointer there."
    )
