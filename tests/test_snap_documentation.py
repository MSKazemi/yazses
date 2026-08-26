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


def test_snap_store_description_sets_the_supported_boundary() -> None:
    manifest = (ROOT / "snap/snapcraft.yaml").read_text(encoding="utf-8")
    assert "supports hold-to-talk dictation on X11\n  only" in manifest
    assert "sudo snap connect yazses:audio-record" in manifest
    assert "sudo snap connect yazses:raw-input" in manifest
    install_block = manifest.split("sudo snap install yazses", 1)[1].split("\n\n", 1)[0]
    assert "yazses setup" not in install_block
