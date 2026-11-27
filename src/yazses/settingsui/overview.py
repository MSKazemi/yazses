"""What the Overview page says about the daemon: one state, at most one fix. Pure.

Reads the same ``status`` reply the tray reads and borrows its rules for the no-text-field
warning and the engine fallback, so the window and the tray cannot disagree.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yazses.bidi import wrap_user_text

#: Stands for a ``status`` reply from a daemon that is alive but did not answer in time.
UNRESPONSIVE: Mapping[str, Any] = {"unresponsive": True}

#: The daemon's ``silent_streak_threshold`` when a reply does not carry one.
_DEFAULT_SILENT_LIMIT = 3

#: Shown once a recalibration has started. The seconds are the daemon's own
#: (``core/daemon.py::_recalibrate_mic``: 1.5 s pause, 2 s of the room, 1.5 s pause, 4 s of
#: speech); ``tests/test_settingsui_single_window.py`` holds them together.
RECALIBRATING = (
    "Recalibrating: stay quiet for about 5 seconds, then speak a sentence at your usual "
    "volume for about 4 seconds."
)


@dataclass(frozen=True)
class Health:
    level: str          # "ok" | "warn" | "bad"
    title: str
    detail: str
    action: str = ""    # "" | "start" | "restart" | "recalibrate"
    action_label: str = ""


@dataclass(frozen=True)
class Check:
    name: str
    value: str
    ok: bool = True


def key_label(key: object) -> str:
    """``right_alt`` → ``Right Alt``; a phrase when no key is known.

    ``auto`` is a setting, not a key anyone can press, so it counts as not known.
    """
    text = str(key or "").replace("_", " ").strip()
    return text.title() if text and text != "auto" else "Your hold-to-talk key"


def word_count(text: str) -> int:
    """As the daemon counts: each Chinese or Japanese character is one."""
    from yazses.postprocess.cjk import count_words

    return count_words(text)


def _count(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return fallback


def _silent(status: Mapping[str, Any]) -> tuple[int, bool]:
    streak = _count(status.get("silent_streak"), 0)
    limit = _count(status.get("silent_streak_threshold"), _DEFAULT_SILENT_LIMIT)
    return streak, streak >= max(1, limit)


def health(status: Mapping[str, Any] | None) -> Health:
    """The one thing worth saying, most important first. Never raises."""
    if status is None:
        return Health(
            "warn", "YazSes is not running",
            "Start it to dictate. Your settings can be changed either way.",
            "start", "Start YazSes",
        )
    if status.get("unresponsive"):
        return Health(
            "warn", "YazSes is busy",
            "It is running but has not answered yet. This page keeps asking.",
        )
    state = str(status.get("state") or "idle").lower()
    if state == "error":
        reason = str(status.get("last_error") or "No reason was reported.")
        return Health(
            "bad", "Something is wrong", wrap_user_text(reason), "restart", "Restart YazSes"
        )
    if status.get("ready") is False:
        return Health(
            "warn", "Loading the speech model",
            "Dictation starts as soon as the model is in memory.",
        )
    streak, silent = _silent(status)
    if silent:
        return Health(
            "bad", "I can’t hear you",
            f"The last {streak} recordings were silent. The microphone may be muted or "
            "set too quiet. Recalibrating takes about ten seconds: first quiet, then "
            "your voice.",
            "recalibrate", "Recalibrate microphone",
        )
    from yazses.tray.menu import no_target_warning

    if no_target_warning(dict(status)) is not None:
        return Health(
            "warn", "No text field is focused",
            "These words will be saved to the clipboard. Click into a text field to "
            "have them typed.",
        )
    if status.get("meeting_active"):
        return Health("ok", "Recording a meeting", "Stop it on the Meetings page.")
    if status.get("meeting_finalizing"):
        return Health("ok", "Finishing a meeting", "The transcript is being written.")
    if state == "recording":
        return Health("ok", "Listening", "Release the key to finish.")
    if state in ("transcribing", "injecting"):
        return Health("ok", "Transcribing", "Your text is on its way.")
    from yazses.stt.factory import fallback_phrase

    fallback = fallback_phrase(dict(status))
    if fallback:
        return Health("warn", "Using a different speech engine", str(fallback))
    return Health(
        "ok", "Ready to dictate",
        "Click into any text field, hold your key, speak, and release.",
    )


def system_checks(status: Mapping[str, Any] | None) -> tuple[Check, ...]:
    """What is in use right now; empty when there is no daemon to ask."""
    if status is None or status.get("unresponsive"):
        return ()
    _streak, silent = _silent(status)
    device = status.get("input_device")
    model = status.get("engine_model") or status.get("model") or "unknown"
    engine = status.get("engine")
    return (
        Check(
            "Microphone",
            wrap_user_text(str(device)) if device else "System default",
            not silent,
        ),
        Check(
            "Speech model",
            f"{model} ({engine})" if engine else str(model),
            status.get("ready") is not False,
        ),
        Check("Typing into apps", str(status.get("injection_backend") or "unknown")),
        Check("Version", str(status.get("version") or "unknown")),
    )
