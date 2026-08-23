"""`yazses fileopen` must open a file on the BSDs, not declare them unsupported.

`platform/factory.py` builds a real backend bundle for FreeBSD/OpenBSD/NetBSD/DragonFly,
so "Unsupported platform: freebsd14" from the launcher was a false statement about a
platform the project ships support for — and it was the only such gate left in `src/`
outside `platform/linux/`.

Every case drives the *running* `sys.platform` rather than passing a name in, because
that is the thing that was wrong: the check has to be a prefix match, since `sys.platform`
carries the major version and never the bare OS name.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from yazses.fileopen.launcher import launch_file
from yazses.platform.bsd import BSD_PREFIXES

# Derived from the tuple the BSD backend declares as its single source of truth, so a
# fifth BSD added there is covered here the day it is added rather than the day someone
# remembers this file. The digits matter: an equality test against "freebsd" passes a
# bare-name fixture and still fails on every real machine.
BSD_PLATFORMS = [f"{prefix}{n}" for n, prefix in enumerate(BSD_PREFIXES, start=6)]


@pytest.mark.parametrize("platform_name", BSD_PLATFORMS)
def test_a_bsd_opens_the_file_with_xdg_open(platform_name):
    with patch.object(sys, "platform", platform_name), patch("subprocess.run") as run:
        launch_file("/tmp/notes.md")

    run.assert_called_once_with(["xdg-open", "/tmp/notes.md"], check=True)


@pytest.mark.parametrize("platform_name", BSD_PLATFORMS)
def test_a_bsd_used_to_be_refused_outright(platform_name):
    """Pins what the fix changed: the BSD branch is the regression, not the wiring."""
    with patch.object(sys, "platform", platform_name), patch("subprocess.run"):
        # Would have raised NotImplementedError before the BSD prefixes were honoured.
        launch_file("/tmp/notes.md")


def test_an_os_with_no_backend_is_still_refused():
    """The branch was widened to the BSDs, not to everything."""
    with patch.object(sys, "platform", "aix7"), patch("subprocess.run") as run:
        with pytest.raises(NotImplementedError, match="aix7"):
            launch_file("/tmp/notes.md")

    run.assert_not_called()


def test_linux_and_macos_are_unchanged():
    for platform_name, argv0 in (("linux", "xdg-open"), ("darwin", "open")):
        with patch.object(sys, "platform", platform_name), patch("subprocess.run") as run:
            launch_file("/tmp/notes.md")
        run.assert_called_once_with([argv0, "/tmp/notes.md"], check=True)
