"""The Windows/macOS tray's update balloon shows the command that will really run.

``tray.updates.describe_update`` is what *Check for updates…* shows on the Windows and
macOS trays. It printed ``status.command`` as ``check_update`` built it -- the plain
``uv tool upgrade yazses`` -- while ``yazses update``, the Settings window and the Linux
tray show ``updater.resolve_upgrade_command``'s composition: the step that keeps enabled
features' libraries, and ``--reinstall-package opencv-contrib-python`` so an upgrade
cannot leave ``cv2`` half-deleted. Someone who copied the balloon's command ran exactly
the upgrade the composition exists to prevent.

The composition is long, and the balloon is not: Windows drops a body over 255
characters whole (``tray.about.BALLOON_LIMIT``), and ``fit_balloon`` trims from the end,
which would cut the command and keep the line that introduces it. So the body is
measured: the command when it fits, and otherwise a shorter wording that sends the user
to ``yazses update``, which composes the same command itself.
"""
from __future__ import annotations

import dataclasses

import pytest

from yazses.system import updater
from yazses.system.features import _FEATURE_DEPS
from yazses.system.remedy import render_command
from yazses.tray.about import BALLOON_LIMIT, fit_balloon
from yazses.tray.updates import describe_update

PLAIN = ["uv", "tool", "upgrade", "yazses"]

#: What `resolve_upgrade_command` gives a uv-tool user with gaze on and both OpenCV
#: builds installed: the shape `deps.uv_tool_upgrade_command` and `keep_cv2_whole`
#: produce (see tests/test_upgrade_keeps_cv2_whole.py).
GAZE = [
    "uv", "tool", "install", "--upgrade",
    "--with", "mediapipe>=0.10.35", "--with", "opencv-python>=5.0",
    "--reinstall-package", "opencv-contrib-python", "yazses[desktop]",
]


def _longest_realistic() -> list[str]:
    """Every requirement of every optional feature in the registry kept through the
    upgrade, plus the OpenCV flag: the upper bound of what the composition can print."""
    reqs = list(dict.fromkeys(p for _mods, pkgs in _FEATURE_DEPS.values() for p in pkgs))
    withs = [a for r in reqs for a in ("--with", r)]
    return [
        "uv", "tool", "install", "--upgrade", *withs,
        "--reinstall-package", "opencv-contrib-python", "yazses[desktop]",
    ]


def _status(command, *, current="2.43.2", latest="2.44.0", method="uv"):
    return updater.UpdateStatus(
        method=method, current=current, latest=latest, available=True, command=command
    )


@pytest.fixture
def composes(monkeypatch):
    """`resolve_upgrade_command` answers with *argv*; records that it was asked."""
    asked = []

    def use(argv):
        def resolve(status, *, opencv=None):
            asked.append(list(status.command))
            return dataclasses.replace(status, command=list(argv))

        monkeypatch.setattr(updater, "resolve_upgrade_command", resolve)
        return asked

    return use


def _never_open(_url):
    raise AssertionError("a status with a command must not open the download page")


def test_the_balloon_shows_the_composed_command_not_the_plain_one(composes):
    asked = composes(GAZE)
    _title, body = describe_update(status=_status(PLAIN), opener=_never_open)
    assert asked == [PLAIN]
    assert render_command(GAZE) in body
    assert "--reinstall-package opencv-contrib-python" in body
    assert len(body) <= BALLOON_LIMIT


def test_the_command_is_quoted_so_it_pastes(composes):
    """`>=` is a redirection and `[desktop]` a glob in a shell, unquoted."""
    composes(GAZE)
    _title, body = describe_update(status=_status(PLAIN), opener=_never_open)
    assert '"mediapipe>=0.10.35"' in body and '"yazses[desktop]"' in body


@pytest.mark.parametrize(
    "argv",
    [PLAIN, GAZE, _longest_realistic()],
    ids=["plain", "gaze", "every-feature"],
)
@pytest.mark.parametrize(
    "versions", [("2.43.2", "2.44.0"), ("2.43.10", "2.44.0rc12")], ids=["short", "long"]
)
def test_every_body_fits_the_balloon_untrimmed(composes, argv, versions):
    """Measured, not assumed: fit_balloon must have nothing to cut, because what it
    would cut first is the command."""
    composes(argv)
    current, latest = versions
    _title, body = describe_update(
        status=_status(PLAIN, current=current, latest=latest), opener=_never_open
    )
    assert len(body) <= BALLOON_LIMIT, (len(body), body)
    assert fit_balloon(body) == body
    assert f"{current} → {latest}" in body.splitlines()[0]


def test_the_longest_command_really_does_not_fit():
    """The premise of the fallback. If this stops being true the fallback is untested."""
    assert len(render_command(_longest_realistic())) > BALLOON_LIMIT


def test_a_command_too_long_for_the_balloon_points_at_yazses_update(composes):
    composes(_longest_realistic())
    _title, body = describe_update(status=_status(PLAIN), opener=_never_open)
    assert "yazses update" in body
    assert "--with" not in body, "half a command is worse than none"


def test_a_resolver_that_raises_still_shows_the_plain_command(monkeypatch):
    def boom(status, *, opencv=None):
        raise RuntimeError("config unreadable")

    monkeypatch.setattr(updater, "resolve_upgrade_command", boom)
    _title, body = describe_update(status=_status(PLAIN), opener=_never_open)
    assert "uv tool upgrade yazses" in body


def test_no_update_is_not_resolved(composes):
    asked = composes(GAZE)
    status = dataclasses.replace(_status(PLAIN), available=False)
    title, _body = describe_update(status=status, opener=_never_open)
    assert asked == [] and "up to date" in title
