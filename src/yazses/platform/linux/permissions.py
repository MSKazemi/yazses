"""Linux permissions — evdev access (input group) and microphone availability."""

from __future__ import annotations

import os
from pathlib import Path

from yazses.platform.base import PermissionState


class LinuxPermissions:
    """PermissionsBackend implementation for Linux."""

    def check_keyboard_capture(self) -> PermissionState:
        input_devs = list(Path("/dev/input").glob("event*"))
        if not input_devs:
            return PermissionState.UNKNOWN
        if any(os.access(str(d), os.R_OK) for d in input_devs):
            return PermissionState.OK
        return PermissionState.DENIED

    def check_microphone(self) -> PermissionState:
        # Linux has no per-app microphone gating; if PortAudio sees a device,
        # the daemon can use it.
        try:
            import sounddevice as sd

            inputs = [d for d in sd.query_devices() if d["max_input_channels"] > 0]
            return PermissionState.OK if inputs else PermissionState.UNKNOWN
        except Exception:
            return PermissionState.UNKNOWN

    def request_keyboard_capture(self) -> None:
        # No interactive prompt on Linux — the user must add themselves to the
        # input group manually, then re-login.
        return

    def how_to_grant(self) -> str:
        return (
            "Add yourself to the input group and re-login:\n"
            "    sudo usermod -aG input $USER\n"
            "Then log out and back in (or reboot) for the change to take effect."
        )

    def how_to_grant_microphone(self) -> str:
        """Linux has no per-app microphone gate, so this is never a *permission*.

        `check_microphone` answers UNKNOWN for two different machines: one with no
        input device at all, and one where PortAudio could not even load. Doctor
        handles the second case separately (it names the package), so what is left
        here is genuinely "the OS can see no input", and the useful answer is which
        commands show what it *can* see rather than a settings pane that does not
        exist.
        """
        return (
            "Linux does not gate the microphone per application, so this is not a\n"
            "permission to grant -- no input device was found. Check in this order:\n"
            "  yazses audio devices    # what YazSes can see (pinned mic marked)\n"
            "  yazses doctor --mic     # record a short clip and report its level\n"
            "  pactl list short sources   # or: wpctl status\n"
            "If the device is listed but silent, it is muted or its input volume is\n"
            "at zero in the desktop sound settings."
        )
