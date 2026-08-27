"""Every Windows tray balloon goes through the fitting helper.

``NOTIFYICONDATA.szInfo`` is a 256-wide-character buffer. pystray's win32 backend
writes the body straight into it, and Windows **discards an oversized balloon whole**
— no truncation, no exception, nothing written to a log. The click looks like it did
nothing at all.

That has now shipped as a user-visible bug twice in one file, and the second time the
fix was already six lines above:

* **About** overran at 347 characters and "appeared to do nothing"; fixed by routing
  through ``balloon_body()``.
* **Check for updates…** was not fixed. Measured against the real ``update_message``
  output, an "update available" body on a ``windows-installer`` install is **512**
  characters and an offline one **623** — so the two cases that carry information were
  precisely the two that vanished, and the only message able to render was *"YazSes is
  up to date"*. Reported from a Windows desktop as "check for update never shows a new
  update".

A test pinning the update path would have passed on the About bug, and vice versa. So
this checks the **structure** instead: every call that reaches the Windows notification
API must hand it a ``fit_balloon(...)`` result, wherever in the file it appears. A new
menu entry then inherits the fix rather than repeating the bug — which is the only
property worth testing here, because the failure has no symptom at the call site.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from yazses.system.updater import UpdateStatus, manual_update_steps, upgrade_command
from yazses.tray.about import BALLOON_LIMIT, fit_balloon, update_message

TRAY = Path(__file__).resolve().parents[1] / "src" / "yazses" / "platform" / "windows" / "tray.py"


def _notify_calls() -> list[ast.Call]:
    """Every ``<something>.notify(...)`` call in the Windows tray."""
    tree = ast.parse(TRAY.read_text(encoding="utf-8"), filename=str(TRAY))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "notify"
    ]


def test_there_is_something_to_check():
    """A structural sweep that finds nothing passes vacuously."""
    assert len(_notify_calls()) >= 2, (
        "no `.notify(...)` calls found in the Windows tray — the sweep below would "
        "pass while checking nothing"
    )


def test_every_balloon_body_is_fitted():
    for call in _notify_calls():
        assert call.args, f"{TRAY.name}:{call.lineno} calls .notify() with no body"
        body = call.args[0]
        ok = (
            isinstance(body, ast.Call)
            and isinstance(body.func, ast.Name)
            and body.func.id == "fit_balloon"
        )
        assert ok, (
            f"{TRAY.name}:{call.lineno} passes a body straight to the Windows "
            "notification API. Over 255 characters Windows drops the balloon silently, "
            "so the body must go through fit_balloon() — or through the local _notify() "
            "helper, which does it for you."
        )


@pytest.mark.parametrize(
    "method", ["windows-installer", "choco", "winget", "scoop", "snap", "pip"]
)
def test_a_real_update_message_fits_once_fitted(method):
    """The bodies that actually broke, measured end to end rather than in the abstract."""
    status = UpdateStatus(
        method=method, current="2.33.0", latest="2.34.0", available=True,
        command=upgrade_command(method), note="", steps=manual_update_steps(method),
    )
    body = update_message(status)[1]
    assert len(fit_balloon(body)) <= BALLOON_LIMIT


def test_the_offline_message_fits_too():
    """The "could not check" body is the longest of the lot at 623 characters."""
    status = UpdateStatus(
        method="windows-installer", current="2.33.0", latest=None, available=False,
        command=None,
        note="could not reach github.com — offline, or a firewall is blocking it",
        steps=manual_update_steps("windows-installer"),
    )
    body = update_message(status)[1]
    assert len(body) > BALLOON_LIMIT, "the case this guards has stopped being oversized"
    assert len(fit_balloon(body)) <= BALLOON_LIMIT


def test_the_headline_survives_the_trim():
    """Losing "2.33.0 → 2.34.0" would leave a balloon that says nothing."""
    status = UpdateStatus(
        method="windows-installer", current="2.33.0", latest="2.34.0", available=True,
        command=None, note="", steps=manual_update_steps("windows-installer"),
    )
    fitted = fit_balloon(update_message(status)[1])
    assert fitted.splitlines()[0] == "YazSes 2.33.0 → 2.34.0"


def test_fitting_never_ends_in_dangling_whitespace():
    """A body trimmed back to a blank separator would render as an empty balloon."""
    fitted = fit_balloon("headline\n\n" + "x" * 400)
    assert fitted == "headline"


def test_a_short_body_is_returned_unchanged():
    assert fit_balloon("YazSes is up to date") == "YazSes is up to date"


def test_a_single_oversized_line_is_truncated_rather_than_dropped():
    fitted = fit_balloon("y" * 400)
    assert len(fitted) <= BALLOON_LIMIT
    assert fitted.endswith("…")
