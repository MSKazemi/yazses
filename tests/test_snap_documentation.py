"""Keep the public Snap instructions within strict-confinement limits."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CURRENT_DOCS = (ROOT / "README.md", *(ROOT / "docs").rglob("*.md"))


def test_snap_install_code_blocks_never_run_host_setup() -> None:
    """A strict snap cannot execute the host provisioning done by `setup`."""
    for path in CURRENT_DOCS:
        if "releases" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for block in re.findall(r"```[^\n]*\n(.*?)```", text, flags=re.DOTALL):
            if "snap install yazses" in block:
                snap_commands = block.split("snap install yazses", 1)[1]
                assert "yazses setup" not in snap_commands, (
                    f"{path.relative_to(ROOT)} tells a confined Snap install to run "
                    "host setup"
                )


def test_wayland_guide_never_recommends_the_snap() -> None:
    guide = (ROOT / "docs/use-cases/voice-dictation-wayland.md").read_text(
        encoding="utf-8"
    )
    assert "snap install yazses" not in guide


def test_snap_store_description_states_the_two_required_connections() -> None:
    """The store page must carry the commands, because nothing else reaches the user.

    This used to pin the sentence "supports hold-to-talk dictation on X11 only",
    which was the honest boundary until the RemoteDesktop portal backend shipped
    and stopped being true. What has to stay guarded is the part that is still
    true and still costs users: both interfaces are manual-connect, a snap
    cannot connect its own, and a reader who misses that gets an install that
    starts cleanly and never hears them.
    """
    manifest = (ROOT / "snap/snapcraft.yaml").read_text(encoding="utf-8")
    assert "sudo snap connect yazses:audio-record" in manifest
    assert "sudo snap connect yazses:raw-input" in manifest
    assert "cannot grant itself permissions" in manifest, (
        "the description must say WHY the user has to run the connect commands"
    )
    install_block = manifest.split("sudo snap install yazses", 1)[1].split("\n\n", 1)[0]
    assert "yazses setup" not in install_block


def test_snap_store_description_keeps_the_offline_claim_qualified() -> None:
    """"Offline" without "by default" is a claim the app does not make.

    A default install downloads model weights once, and the optional update
    check can be switched on. The qualifier is what keeps the store page true;
    it has been lost to a rewrite before.
    """
    manifest = (ROOT / "snap/snapcraft.yaml").read_text(encoding="utf-8")
    description = manifest.split("description: |", 1)[1].split("\ntitle:", 1)[0]
    assert "by default" in description


def test_snap_store_description_does_not_claim_untested_wayland_compositors() -> None:
    """The portal covers GNOME and KDE. It is not a blanket "any Wayland" claim.

    wlroots compositors implement `virtual-keyboard-manager-v1` and are served by
    wtype; other compositors may implement neither. Naming the two desktops that
    were reasoned about keeps the page from promising the ones that were not.
    """
    manifest = (ROOT / "snap/snapcraft.yaml").read_text(encoding="utf-8")
    description = manifest.split("description: |", 1)[1].split("\ntitle:", 1)[0].lower()
    assert "works on any wayland" not in description
    assert "all wayland" not in description
