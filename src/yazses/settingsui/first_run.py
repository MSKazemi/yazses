"""The first-run setup guide: when to offer it, and what each step says. Qt-free.

The guide appears on its own only on a **new** install, at most once:

* nothing was ever configured here (no config file, current or pre-#330, and no marker), or
* the daemon's first start wrote the config a few days ago and left the marker ``pending``.

A config with no marker is an install that predates the guide, so it is never offered
there. Anything unreadable answers "do not offer": the guide can always be opened from
the Overview page, but a window that nags an existing install cannot be taken back.

``setup_dialog.py`` paints these decisions.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from yazses.hotkeys.names import AUTO, canonical
from yazses.settingsui import overview
from yazses.settingsui.controls import meter_reading
from yazses.system.firstrun import (
    SETUP_PENDING,
    SETUP_SEEN,
    ensure_recommended_config,
    setup_marker_path,
    write_setup_marker,
)

log = logging.getLogger(__name__)

#: How long a ``pending`` marker still means "new". Someone who has dictated for weeks and
#: only then opens the window is not setting YazSes up.
OFFER_WINDOW_S = 7 * 24 * 3600


def should_offer(
    marker: str | None,
    *,
    marker_age_s: float,
    config_exists: bool,
    legacy_config_exists: bool,
) -> bool:
    """Whether the guide opens by itself. *marker* is ``None`` when there is no file."""
    if marker is None:
        return not config_exists and not legacy_config_exists
    return marker == SETUP_PENDING and marker_age_s <= OFFER_WINDOW_S


def prepare(
    config_file: Path,
    legacy_config_file: Path,
    *,
    now: float | None = None,
    seed: Callable[[Path], Any] = ensure_recommended_config,
) -> bool:
    """Decide whether to offer the guide. Call before the window loads the config.

    On an install nothing has configured yet, this also writes the config the daemon's
    first start would write. Otherwise saving a key in the guide would create a config
    holding only that key, and the daemon, finding a file, would never add the
    recommended features. Never raises.
    """
    try:
        marker_file = setup_marker_path(config_file)
        try:
            marker: str | None = marker_file.read_text(encoding="utf-8").strip()
            age = (time.time() if now is None else now) - marker_file.stat().st_mtime
        except FileNotFoundError:
            marker, age = None, 0.0
        config_exists = config_file.exists()
        offer = should_offer(
            marker,
            marker_age_s=age,
            config_exists=config_exists,
            legacy_config_exists=legacy_config_file.exists(),
        )
        if offer and not config_exists:
            seed(config_file)
        return offer
    except Exception:  # noqa: BLE001 - the window must open, and "no" is the safe answer
        log.debug("could not decide whether to offer the setup guide", exc_info=True)
        return False


def mark_seen(config_file: Path) -> bool:
    """Record that the guide has been shown, so it never opens by itself again."""
    return write_setup_marker(config_file, SETUP_SEEN)


# --- the steps ----------------------------------------------------------------------


@dataclass(frozen=True)
class Step:
    key: str
    title: str
    text: str


STEPS: tuple[Step, ...] = (
    Step(
        "welcome", "Welcome to YazSes",
        "Hold a key, speak, release: your words are typed into the app you are using.\n\n"
        "Speech is turned into text on this computer. The first start may download the "
        "speech model. The General page lists any setting that can send text elsewhere.\n\n"
        "The next three steps check your microphone, choose your key and let you try "
        "it. You can skip this, and open it again from the Overview page.",
    ),
    Step(
        "microphone", "Check your microphone",
        "Hold your key, say a few words and release. The bar moves while the key is held.",
    ),
    Step(
        "key", "Choose your hold-to-talk key",
        "Pick a key you can hold comfortably and do not need for typing. "
        "“auto” means the usual key for this operating system.",
    ),
    Step(
        "try", "Try it",
        "Click in the box, hold your key, speak and release. This window does not save "
        "what appears here.",
    ),
)

#: The steps that ask the daemon for its status while they are on screen.
LIVE_STEPS = frozenset({"microphone", "try"})


def step_counter(index: int) -> str:
    return f"Step {index + 1} of {len(STEPS)}"


def is_last(index: int) -> bool:
    return index >= len(STEPS) - 1


def next_label(index: int, *, key_changed: bool) -> str:
    """The forward button. On the key step it says that moving on saves the choice."""
    if is_last(index):
        return "Finish"
    if STEPS[index].key == "key" and key_changed:
        return "Save key and continue"
    return "Next"


# --- the daemon ---------------------------------------------------------------------


@dataclass(frozen=True)
class Prompt:
    """One line about the daemon, and at most one button."""

    text: str
    action: str = ""            # "" | "start" | "restart"
    action_label: str = ""


def key_in_effect(configured: str, platform_default: str) -> str:
    """The key behind *configured*; ``auto`` is the platform's default."""
    return platform_default if configured.strip() == AUTO else configured.strip()


def hold_key_label(status: Mapping[str, Any] | None, saved: str, platform_default: str) -> str:
    """The key to hold now: what the daemon listens for, else what is saved."""
    running = status.get("hotkey") if status else None
    return overview.key_label(running or key_in_effect(saved, platform_default))


def daemon_prompt(
    status: Mapping[str, Any] | None, saved_key: str, platform_default: str
) -> Prompt:
    """The Overview page's verdict, plus a restart while the daemon uses another key."""
    health = overview.health(status)
    text = f"{health.title}. {health.detail}"
    if health.action in ("start", "restart"):
        return Prompt(text, health.action, health.action_label)
    running = str(status.get("hotkey") or "") if status else ""
    wanted = key_in_effect(saved_key, platform_default)
    if running and wanted and canonical(running) != canonical(wanted):
        return Prompt(
            f"YazSes is still listening for {overview.key_label(running)}. Restart it to "
            f"use {overview.key_label(wanted)}.",
            "restart", "Restart YazSes",
        )
    return Prompt(text)


def can_recalibrate(status: Mapping[str, Any] | None) -> bool:
    """The daemon measures the microphone only while it is loaded and idle."""
    if not status or status.get("unresponsive") or status.get("ready") is False:
        return False
    return str(status.get("state") or "").lower() == "idle"


# --- the microphone -----------------------------------------------------------------


@dataclass(frozen=True)
class MicCheck:
    """What the status replies have shown about the microphone, one hold at a time."""

    recording: bool = False
    cleared: bool = False       # the current hold has reached the silence threshold
    position: int = 0           # the level bar, 0..100
    verdict: str = ""           # "" | "heard" | "quiet", for the last finished hold

    def update(self, status: Mapping[str, Any] | None) -> MicCheck:
        """The next state. A missing or late reply says nothing about the microphone."""
        if not status or status.get("unresponsive"):
            return replace(self, position=0)
        if str(status.get("state") or "").lower() != "recording":
            if not self.recording:
                return replace(self, position=0)
            return MicCheck(verdict="heard" if self.cleared else "quiet")
        try:
            position, above = meter_reading(
                float(status.get("audio_level") or 0.0),
                float(status.get("vad_threshold") or 0.01),
            )
        except (TypeError, ValueError):
            position, above = 0, False
        before = self.cleared if self.recording else False
        return MicCheck(True, before or above, position, self.verdict)


def mic_message(check: MicCheck, key: str) -> str:
    if check.recording:
        return "Listening…"
    if check.verdict == "heard":
        return "The microphone hears you."
    if check.verdict == "quiet":
        return (
            "Only very quiet sound arrived. Check that the microphone is not muted, "
            "speak closer to it, or recalibrate."
        )
    return f"Hold {key}, say a few words, then release."


#: Seconds into ``recalibrate_mic`` at which the daemon stops measuring the room, and at
#: which it has finished measuring speech. A test holds them to the daemon's own timings.
RECAL_ROOM_END_S = 3.5
RECAL_END_S = 9.0
#: Slack for opening the microphone before the result is read.
_RECAL_SLACK_S = 1.0


def recalibration_prompt(elapsed_s: float) -> str | None:
    """What to do *elapsed_s* into a recalibration; ``None`` once it should be over."""
    if elapsed_s < RECAL_ROOM_END_S:
        return "Stay quiet: YazSes is measuring the room."
    if elapsed_s < RECAL_END_S + _RECAL_SLACK_S:
        return "Now speak normally until this message changes. No need to hold the key."
    return None


def threshold_of(status: Mapping[str, Any] | None) -> float | None:
    value = status.get("vad_threshold") if status else None
    return float(value) if isinstance(value, (int, float)) else None


def recalibration_result(before: float | None, after: float | None) -> str:
    """The daemon reports no outcome over IPC, so this reads the threshold it wrote."""
    if after is None:
        return "YazSes did not report the result. Hold your key and speak to check."
    if before is not None and after == before:
        return (
            "The silence threshold did not change. If a notification said the check "
            "failed, try again in a quieter place, speaking at your usual volume."
        )
    return f"Recalibrated: the silence threshold is now {after:.4g}. Hold your key to check."
