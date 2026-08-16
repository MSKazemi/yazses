"""Reduced-motion policy for the overlay.

The overlay's default look is expanding rings that travel outward from near the
pointer, sixty times a second, for as long as you are speaking. That is the exact
pattern people with vestibular disorders and motion sensitivity ask software to
stop doing, and every desktop already carries a setting where they have said so —
GNOME's ``enable-animations``, macOS's *Reduce motion*, Windows's *Play animations
in Windows*. YazSes honoured none of them. The documentation site honours
``prefers-reduced-motion``; the accessibility product it documents did not.

Reduced motion must remove **motion, not information**. The overlay answers one
question — *am I being heard, and how loudly* — and a user who has asked for less
animation has not asked to stop being told. So the reduced form keeps the ring and
drops the travel: one steady circle while recording, its brightness following your
voice in a few discrete steps.

The steps matter. A brightness recomputed every frame from a live microphone level
shimmers, and a shimmer at 60 Hz is its own accessibility problem rather than a fix
for one. Quantising means the ring changes only when your voice genuinely changes
band.

Detection is best-effort and honest about it: :func:`detect_os_preference` returns
``None`` where it cannot tell rather than guessing "no", which is why the setting
has an explicit ``on`` for the desktops nobody has taught it to read.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys

from yazses.overlay.animation import Ripple

log = logging.getLogger(__name__)

#: Where the steady ring sits, as a fraction of the half-window radius. Mid-way
#: out: large enough to read at a glance, far enough from the edge that the
#: stroke and its glow are not clipped.
STEADY_RADIUS_FRAC = 0.55

#: Discrete brightness bands. Four is enough to tell silence from quiet from loud
#: without the ring reacting to every frame of microphone noise.
ALPHA_STEPS = 4

#: Floor brightness, used at zero intensity. Deliberately not 0: while recording,
#: a silent microphone must still show *something*, or the overlay stops answering
#: "am I recording?" at precisely the moment the user is wondering.
MIN_ALPHA = 0.3

#: How long to wait on a desktop settings command before giving up. This runs once
#: at overlay start, and a hung settings daemon must not delay the indicator.
_PROBE_TIMEOUT_S = 1.0

VALID_SETTINGS = ("auto", "on", "off")


def resolve_reduced_motion(setting: str, os_prefers_reduced: bool | None) -> bool:
    """Decide whether to draw the reduced form.

    ``on``/``off`` are the user overriding the desktop, which is the whole reason
    they exist: the probe below cannot read every desktop, so someone on one it
    does not know must be able to say so once and be believed.

    ``auto`` follows the desktop, and an *undetectable* desktop resolves to full
    motion — matching what the overlay did before this existed. Erring the other
    way would silently change the look for everyone whose desktop the probe cannot
    read, which is most of them.
    """
    normalized = (setting or "").strip().lower()
    if normalized == "on":
        return True
    if normalized == "off":
        return False
    if normalized != "auto":
        log.warning(
            "[overlay] reduced_motion=%r is not one of %s -- treating it as 'auto'.",
            setting, ", ".join(VALID_SETTINGS),
        )
    return bool(os_prefers_reduced)


def band(intensity: float) -> float:
    """Snap a live microphone level to one of :data:`ALPHA_STEPS` bands.

    Everything the reduced overlay draws is sized or lit from this rather than
    from the raw level, and that is not only about the ring. The widget also
    draws a centre glow whose *radius* follows the level — ``half * (0.10 + 0.10
    * intensity)`` — so leaving the raw value in place would stop the rings
    travelling while the core carried on breathing sixty times a second, which is
    the same class of motion in a smaller place.
    """
    return round(min(1.0, max(0.0, intensity)) * ALPHA_STEPS) / ALPHA_STEPS


def steady_ripples(intensity: float) -> list[Ripple]:
    """The reduced form: one ring that does not travel.

    Returns a list because that is what the widget paints, not because more than
    one is ever produced.
    """
    level = band(intensity)
    return [
        Ripple(
            radius_frac=STEADY_RADIUS_FRAC,
            alpha=MIN_ALPHA + (1.0 - MIN_ALPHA) * level,
            intensity=level,
        )
    ]


def _run(argv: list[str]) -> str | None:
    """Best-effort text from a desktop settings command; ``None`` on any trouble."""
    try:
        out = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip()


_PORTAL_ANIMATIONS = re.compile(r"'enable-animations':\s*<(true|false)>")


def _portal_prefers_reduced() -> bool | None:
    """Ask the XDG desktop portal, which is not a GNOME-only route.

    Two reasons this is tried before ``gsettings``, and the second is the one that
    actually bites:

    * The portal is a freedesktop interface with backends beyond GNOME, so a
      desktop that implements one answers here without this module needing to know
      how that desktop stores the setting.
    * **YazSes ships as a snap.** A confined process reading ``gsettings`` may be
      talking to the sandbox rather than to the user's session, in which case the
      answer is not wrong so much as about the wrong machine. The portal is the
      sanctioned way out of confinement, and it is how a sandboxed app is supposed
      to learn anything about its host.

    The key lives under the ``org.gnome.desktop.interface`` namespace for historical
    reasons; portal backends map their own settings into it, which is the same
    mechanism that gets GTK apps the right theme on a non-GNOME desktop.
    """
    out = _run([
        "gdbus", "call", "--session",
        "--dest", "org.freedesktop.portal.Desktop",
        "--object-path", "/org/freedesktop/portal/desktop",
        "--method", "org.freedesktop.portal.Settings.ReadAll",
        "['org.gnome.desktop.interface']",
    ])
    if not out:
        return None
    match = _PORTAL_ANIMATIONS.search(out)
    if match is None:
        return None  # a portal that answers but does not carry this key
    return match.group(1) == "false"


def _linux_prefers_reduced() -> bool | None:
    """Portal first, then GNOME's own key; ``None`` rather than a guess.

    If neither answers -- a desktop with no portal backend and no GNOME schema --
    the result is "cannot tell", not "no". KDE, Xfce and the rest each store this
    differently where the portal is absent, and inventing a reading for a key that
    is not there would produce a confident wrong answer. Those users set
    ``reduced_motion = "on"`` and no probe is consulted at all.
    """
    portal = _portal_prefers_reduced()
    if portal is not None:
        return portal

    value = _run(["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"])
    if value is None:
        return None
    return value.strip().strip("'\"").lower() == "false"


def _macos_prefers_reduced() -> bool | None:
    """AppKit first, `defaults` only as a fallback.

    ``NSWorkspace.accessibilityDisplayShouldReduceMotion`` is the supported API —
    *"a Boolean value that indicates whether the accessibility option to reduce
    motion is in an enabled state"*, macOS 10.12+ — and pyobjc-framework-Cocoa is
    already a hard dependency on darwin, so it costs nothing to ask properly.

    The `defaults` path reads `com.apple.universalaccess reduceMotion`, which is an
    **undocumented** preference key: it is not part of any published interface, it is
    absent until the user has toggled the setting at least once, and Apple is free to
    rename it. It stays as a fallback rather than the primary because a probe that
    silently stops working looks exactly like a desktop with no such setting.

    Unlike the Windows flag, this one is not inverted: true means reduce.
    """
    try:
        from AppKit import NSWorkspace  # type: ignore[import-not-found]

        return bool(NSWorkspace.sharedWorkspace().accessibilityDisplayShouldReduceMotion())
    except Exception:
        # ImportError off macOS or on a stripped install; anything else means the
        # selector was unavailable. Either way there is still the older route.
        log.debug("NSWorkspace reduce-motion probe unavailable", exc_info=True)

    value = _run(["defaults", "read", "com.apple.universalaccess", "reduceMotion"])
    if value is None:
        return None
    return value.strip() == "1"


#: `SPI_GETCLIENTAREAANIMATION`, the flag behind *Settings → Accessibility → Visual
#: effects → Animation effects*. Value and semantics taken from the Win32
#: `SystemParametersInfoW` reference, not from memory, because nothing on a Linux or
#: macOS developer machine can catch a wrong constant: the call would simply fail and
#: this module would report "cannot tell" forever, which looks exactly like a desktop
#: with no such setting.
_SPI_GETCLIENTAREAANIMATION = 0x1042


def _windows_prefers_reduced() -> bool | None:
    """Does Windows say animations are off?

    **The returned value is inverted, deliberately.** `SystemParametersInfoW` fills
    `pvParam` with TRUE when animations are *enabled*; this function answers the
    opposite question, so animations-enabled means "does not prefer reduced". An
    inverted boolean is where a later tidy-up introduces a bug, so the polarity is
    written down rather than left to be re-derived.

    Microsoft's own justification for the flag is stronger than the vestibular one
    this module leads with: *"flashing, blinking, flickering, and moving content can
    cause seizures in users with photo-sensitive epilepsy."* That is also why the
    reduced form quantises brightness instead of tracking a live level.
    """
    try:
        import ctypes
    except ImportError:  # pragma: no cover - ctypes is stdlib everywhere we ship
        return None
    try:
        # Win32 BOOL is a 32-bit int, which is what c_int is on every platform we ship.
        animations_enabled = ctypes.c_int(0)
        ok = ctypes.windll.user32.SystemParametersInfoW(  # type: ignore[attr-defined]
            _SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(animations_enabled), 0
        )
    except (AttributeError, OSError):
        return None
    if not ok:
        return None
    return animations_enabled.value == 0


def detect_os_preference() -> bool | None:
    """Does this desktop say the user wants less animation? ``None`` if unknown.

    Never raises: it is called once while the overlay is starting, and an
    indicator that fails to appear because it could not read a settings key would
    be a worse bug than the one this file fixes.
    """
    try:
        if sys.platform == "darwin":
            return _macos_prefers_reduced()
        if sys.platform.startswith("win"):
            return _windows_prefers_reduced()
        return _linux_prefers_reduced()
    except Exception:  # pragma: no cover - defensive; the helpers already swallow
        log.debug("reduced-motion probe failed", exc_info=True)
        return None
