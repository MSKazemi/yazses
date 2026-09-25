"""Linux permissions — evdev access (input group), microphone, and camera."""

from __future__ import annotations

import os
from pathlib import Path

from yazses.cameraperm.contract import CameraPermission
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

    def check_camera(self) -> CameraPermission:
        """V4L2 has no per-application gate, so this is a *device* question.

        Three outcomes, and they are three different problems:

        * no ``/dev/video*`` at all -> ``UNAVAILABLE``. There is nothing to grant;
          the machine has no camera, or its module is not loaded.
        * a node this user can open -> ``GRANTED``. V4L2 capture needs read **and**
          write on the node (ioctls are writes), so ``R_OK`` alone would answer
          yes on a device that then fails to stream -- the optimistic default this
          contract exists to refuse.
        * a node that exists and cannot be opened -> ``DENIED``, which on Linux
          almost always means the user is not in the ``video`` group.

        Confinement is deliberately *not* probed here. A snap and a flatpak are
        answered one layer earlier, by ``cameraperm.matrix``: neither can install
        mediapipe or opencv, so the camera features are unreachable in those
        formats whatever the device permissions say, and asking the question at
        all would produce a green row for a feature that cannot run.
        """
        nodes = sorted(Path("/dev").glob("video*"))
        if not nodes:
            return CameraPermission.UNAVAILABLE
        if any(os.access(str(node), os.R_OK | os.W_OK) for node in nodes):
            return CameraPermission.GRANTED
        return CameraPermission.DENIED

    def how_to_grant_camera(self) -> str:
        """Linux has no camera permission to grant, so say what it *is* instead.

        Written the way `how_to_grant_microphone` is written, and for the same
        reason: sending a Linux user to a privacy pane that does not exist is
        worse than saying nothing. The three commands below distinguish the three
        states `check_camera` can report, in the order they should be tried.
        """
        return (
            "Linux does not gate the camera per application, so there is no\n"
            "permission to grant -- either no camera device is present, or this\n"
            "user cannot open it. Check in this order:\n"
            "  ls -l /dev/video*        # is there a camera node at all?\n"
            "  groups | grep -w video   # can this user open it?\n"
            "If the node exists but you are not in the `video` group:\n"
            "    sudo usermod -aG video $USER\n"
            "then log out and back in. If the node exists and you ARE in the\n"
            "group, another program is probably holding the camera -- close it\n"
            "(`fuser -v /dev/video0` names the process)."
        )
