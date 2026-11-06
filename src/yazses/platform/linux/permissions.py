"""Linux permissions — evdev access (input group), microphone, and camera."""

from __future__ import annotations

import os
import struct
from pathlib import Path

from yazses.cameraperm.contract import CameraPermission
from yazses.platform.base import PermissionState

#: Where evdev nodes live, and where the kernel describes each one. Module-level
#: so a test can point both at a temporary tree.
_DEV_INPUT = Path("/dev/input")
_SYS_INPUT = Path("/sys/class/input")

# linux/input-event-codes.h. The same "full keyboard" definition the evdev
# listener uses (`hotkeys/evdev_hold.py::_looks_like_keyboard`): the whole letter
# row plus Enter. Spelled as numbers so this module needs no `evdev` import.
_KEY_ENTER = 28
_KEY_LETTERS = frozenset({
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25,  # Q W E R T Y U I O P
    30, 31, 32, 33, 34, 35, 36, 37, 38,  # A S D F G H J K L
    44, 45, 46, 47, 48, 49, 50,  # Z X C V B N M
})


def parse_key_bitmap(text: str, word_bits: int | None = None) -> frozenset[int] | None:
    """The key codes set in a sysfs ``capabilities/key`` bitmap, or None.

    The kernel prints the bitmap as space-separated hex words, most significant
    first, each one the kernel's ``unsigned long`` wide and printed *unpadded*
    (``%lx``: a zero word is ``0``), so the text does not carry the width. It is
    taken from this process's C ``long``, raised to 64 when any word is too long
    to fit 32 bits -- which covers a 32-bit userland on a 64-bit kernel whenever
    the bitmap has a busy word, as every full keyboard's low word is.
    ``word_bits`` overrides the native width (tests). Anything unparsable
    answers None ("unknown"), never an empty set.
    """
    words = text.split()
    if not words:
        return None
    try:
        values = [int(w, 16) for w in words]
    except ValueError:
        return None
    width = word_bits or 8 * struct.calcsize("l")
    if any(len(w) > 8 for w in words):
        width = 64
    if any(len(w) > width // 4 for w in words):
        return None
    codes: set[int] = set()
    for index, value in enumerate(reversed(values)):
        base = index * width
        bit = 0
        while value:
            if value & 1:
                codes.add(base + bit)
            value >>= 1
            bit += 1
    return frozenset(codes)


def is_full_keyboard(codes: frozenset[int]) -> bool:
    """True when ``codes`` carries the letter row and Enter."""
    return _KEY_ENTER in codes and _KEY_LETTERS <= codes


def _node_keys(node: Path) -> frozenset[int] | None:
    """The key capability of one ``/dev/input/eventN`` node, or None if unknown."""
    try:
        text = (_SYS_INPUT / node.name / "device" / "capabilities" / "key").read_text(
            encoding="ascii"
        )
    except (OSError, UnicodeDecodeError):
        return None
    return parse_key_bitmap(text)


def _readable(node: Path) -> bool:
    return os.access(str(node), os.R_OK)


class LinuxPermissions:
    """PermissionsBackend implementation for Linux."""

    def check_keyboard_capture(self) -> PermissionState:
        """Can this user read a *keyboard* -- not merely some input node?

        "Any ``event*`` is readable" is not the same question. systemd's stock
        ``70-uaccess.rules`` gives the active seat user an ACL on every joystick
        node (``ENV{ID_INPUT_JOYSTICK}=="?*", TAG+="uaccess"``), so a user who is
        *not* in the ``input`` group but has a gamepad plugged in can read that
        one node -- and the old check answered OK while the listener, which wants
        a keyboard exposing the hotkey (``hotkeys/evdev_hold.py``), found none.

        DENIED is answered only on a specific, checkable signal (ADR-021): the
        kernel names at least one full keyboard, and none of the full keyboards
        is readable. A readable node whose kind cannot be read from sysfs still
        counts, and a machine with no full keyboard at all keeps the old
        any-readable-node answer -- so a missing ``/sys``, a container, or a
        keypad-only setup is never turned into a false DENIED.
        """
        input_devs = sorted(_DEV_INPUT.glob("event*"))
        if not input_devs:
            return PermissionState.UNKNOWN
        readable = [d for d in input_devs if _readable(d)]
        if not readable:
            return PermissionState.DENIED
        kinds = {d: _node_keys(d) for d in input_devs}
        keyboards = [d for d, keys in kinds.items() if keys is not None and is_full_keyboard(keys)]
        if not keyboards:
            return PermissionState.OK
        if any(d in readable for d in keyboards):
            return PermissionState.OK
        if any(kinds[d] is None for d in readable):
            # A readable node we could not classify might be the keyboard.
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
