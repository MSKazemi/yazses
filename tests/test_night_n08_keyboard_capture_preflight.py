"""The Linux keyboard-capture preflight must not answer OK for a joystick.

systemd's stock ``70-uaccess.rules`` grants the active seat user an ACL on every
joystick node, so a user outside the ``input`` group with a gamepad plugged in can
read exactly one ``/dev/input/event*`` node. The old check (any readable node ->
OK) then reported keyboard capture as fine while the evdev listener found no
keyboard. Synthetic only: a fake ``/dev/input`` + ``/sys/class/input`` tree and a
fake ``os.access`` -- no claim about any real udev setup or hardware.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from yazses.platform.base import PermissionState
from yazses.platform.linux import permissions as linux_perms

pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win"), reason="POSIX-style fake device tree"
)

# Kernel-style bitmaps (64-bit words, every word printed unpadded with %lx).
# Full keyboard, copied from a laptop's AT keyboard node (2026-11-06): the low
# word has every bit 1..63, so the letter row and Enter are all set.
_KEYBOARD_64 = "402000007 ff803078f800d001 feffffdfffcfffff fffffffffffffffe"
# Gamepad: BTN_SOUTH.. (0x130-0x13e) only, nothing in the keyboard range.
_GAMEPAD_64 = "7fdb000000000000 0 0 0 0"
# Power button: KEY_POWER (116) only.
_POWER_64 = "10000000000000 0"


def _tree(tmp_path: Path, nodes: dict[str, str | None]) -> None:
    dev = tmp_path / "dev"
    sys_ = tmp_path / "sys"
    dev.mkdir()
    for name, bitmap in nodes.items():
        (dev / name).write_bytes(b"")
        if bitmap is not None:
            caps = sys_ / name / "device" / "capabilities"
            caps.mkdir(parents=True)
            (caps / "key").write_text(bitmap + "\n", encoding="ascii", newline="\n")


def _check(tmp_path: Path, monkeypatch, readable: set[str]) -> PermissionState:
    monkeypatch.setattr(linux_perms, "_DEV_INPUT", tmp_path / "dev")
    monkeypatch.setattr(linux_perms, "_SYS_INPUT", tmp_path / "sys")
    monkeypatch.setattr(linux_perms, "_readable", lambda node: node.name in readable)
    return linux_perms.LinuxPermissions().check_keyboard_capture()


def test_bitmap_parser_reads_a_kernel_keyboard_as_a_full_keyboard() -> None:
    keys = linux_perms.parse_key_bitmap(_KEYBOARD_64, word_bits=64)
    assert keys is not None and linux_perms.is_full_keyboard(keys)


def test_bitmap_parser_reads_gamepad_and_power_button_as_not_keyboards() -> None:
    for bitmap in (_GAMEPAD_64, _POWER_64):
        keys = linux_perms.parse_key_bitmap(bitmap, word_bits=64)
        assert keys is not None and not linux_perms.is_full_keyboard(keys)
    assert 116 in (linux_perms.parse_key_bitmap(_POWER_64, word_bits=64) or set())
    assert 0x130 in (linux_perms.parse_key_bitmap(_GAMEPAD_64, word_bits=64) or set())


def test_unpadded_later_words_keep_their_position() -> None:
    """`%lx` prints a busy later word short (`18040000`); it is still word 2."""
    keys = linux_perms.parse_key_bitmap("1 18040000 0", word_bits=64)
    assert keys == frozenset({128, 64 + 18, 64 + 27, 64 + 28})


def test_bitmap_parser_infers_32_bit_words() -> None:
    # Unpadded like the kernel prints it: KEY_ENTER (28) in word 0,
    # KEY_Z (44) -> bit 12 of word 1.
    keys = linux_perms.parse_key_bitmap("1000 10000000", word_bits=32)
    assert keys == frozenset({28, 44})


@pytest.mark.parametrize("bad", ["", "zz", "1 0x"])
def test_bitmap_parser_answers_unknown_for_garbage(bad: str) -> None:
    assert linux_perms.parse_key_bitmap(bad) is None


def test_only_a_readable_gamepad_is_denied_not_ok(tmp_path, monkeypatch) -> None:
    """The defect: on 8a72bbc6 this answered OK."""
    _tree(tmp_path, {"event0": _KEYBOARD_64, "event5": _GAMEPAD_64})
    assert _check(tmp_path, monkeypatch, {"event5"}) is PermissionState.DENIED


def test_a_readable_keyboard_is_ok(tmp_path, monkeypatch) -> None:
    _tree(tmp_path, {"event0": _KEYBOARD_64, "event5": _GAMEPAD_64})
    assert _check(tmp_path, monkeypatch, {"event0", "event5"}) is PermissionState.OK


def test_nothing_readable_is_denied(tmp_path, monkeypatch) -> None:
    _tree(tmp_path, {"event0": _KEYBOARD_64})
    assert _check(tmp_path, monkeypatch, set()) is PermissionState.DENIED


def test_no_nodes_is_unknown(tmp_path, monkeypatch) -> None:
    _tree(tmp_path, {})
    assert _check(tmp_path, monkeypatch, set()) is PermissionState.UNKNOWN


def test_without_sysfs_the_old_answer_stands(tmp_path, monkeypatch) -> None:
    """No /sys (container, sandbox): never turn missing evidence into DENIED."""
    _tree(tmp_path, {"event0": None, "event5": None})
    assert _check(tmp_path, monkeypatch, {"event5"}) is PermissionState.OK


def test_a_readable_unclassifiable_node_still_counts(tmp_path, monkeypatch) -> None:
    _tree(tmp_path, {"event0": _KEYBOARD_64, "event7": None})
    assert _check(tmp_path, monkeypatch, {"event7"}) is PermissionState.OK


def test_a_machine_with_no_full_keyboard_keeps_the_any_node_answer(tmp_path, monkeypatch) -> None:
    """A keypad/foot-pedal-only setup must not be told to join a group it may not need."""
    _tree(tmp_path, {"event2": _POWER_64, "event5": _GAMEPAD_64})
    assert _check(tmp_path, monkeypatch, {"event2"}) is PermissionState.OK
