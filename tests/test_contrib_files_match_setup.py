"""`contrib/` ships copies of what `yazses setup` writes — they must be identical.

`setup.py` has claimed since it was written that `contrib/ydotoold.service` is "kept
in sync". Nothing checked, and it had already drifted: the shipped copy carried two
extra comment lines the constant did not, and both described `/dev/uinput` access as
coming from `input`-group membership alone — which is false without the udev rule,
and is precisely the wrong premise that left Wayland users on the portal.

A comment asserting a property is not a test of it. This is.
"""

from __future__ import annotations

import pathlib

import pytest

from yazses.system import setup

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    ("shipped", "constant"),
    [
        ("contrib/ydotoold.service", "YDOTOOLD_SERVICE"),
        ("contrib/60-yazses-uinput.rules", "UINPUT_UDEV_RULE"),
    ],
)
def test_the_shipped_copy_is_byte_identical_to_what_setup_writes(shipped, constant):
    path = ROOT / shipped
    assert path.exists(), f"{shipped} is missing; setup.py writes it from {constant}"
    assert path.read_text(encoding="utf-8") == getattr(setup, constant), (
        f"{shipped} has drifted from setup.{constant}. Regenerate it from the "
        "constant rather than editing the copy — a package built from contrib/ "
        "would otherwise install something the daemon does not expect."
    )


def test_the_service_does_not_repeat_the_group_is_enough_claim():
    """The premise that cost Wayland users a working injector.

    /dev/uinput ships 0600 root:root, so `input` membership grants nothing on its
    own. Any file telling a reader otherwise sends them away believing the machine
    is provisioned when it is not.
    """
    text = setup.YDOTOOLD_SERVICE
    assert "udev" in text, "the unit must name the rule its device access depends on"


def test_the_rule_grants_the_group_the_daemon_actually_runs_as():
    rule = setup.UINPUT_UDEV_RULE
    assert 'KERNEL=="uinput"' in rule
    assert 'GROUP="input"' in rule
    assert 'MODE="0660"' in rule
    # Without static_node the mode is applied only on a hotplug event; uinput is
    # usually module-autoloaded, which is not one.
    assert "static_node=uinput" in rule
