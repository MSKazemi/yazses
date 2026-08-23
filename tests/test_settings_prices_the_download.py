"""The settings window started a 3.1 GB download and called it "a few minutes".

`yazses features enable <slug>` says what an install costs *before* it spends it
(ADR-018): `_install_feature_deps` prints the marginal download note, and for a large
one prefixes it with "⚠ Large download —" and "Ctrl-C now to stop". The comment there
states the reason outright: "a download that turns out to be gigabytes is one the user
should have been able to cancel".

The settings window did none of it. `grep depsize src/yazses/settingsui/` found nothing,
`_auto_install` defaults to **True**, and `_start_install_worker` set one hardcoded line:

    Installing packages for cocktail… this can take a few minutes.

Measured against the real registry: 19 capabilities have a priceable install and **9**
are ones the CLI shouts about — `multiprofile`, `cocktail` and `voiceguard` are each
**~3.1 GB**, and `stt-parakeet` fetches ~600 MB of model files.

It is worse in the window than in the terminal, not better. There is no cancel: the
worker has no interrupt path and Apply is disabled while it runs, so the CLI's "Ctrl-C
now to stop" has no equivalent to offer. The one thing left that can help is telling the
user the number before the click, which is exactly what was missing — and the GUI is the
surface the settings epic exists to serve, i.e. the user least likely to have a terminal
open to notice a disk filling.
"""
from __future__ import annotations

import inspect

from yazses.settingsui.deps import InstallPlan, describe_install_start


def _price(table):
    """A stand-in for `system.depsize`, so these run with no catalogue lookup."""

    def price(slug, packages):
        return table.get(slug, ("", False))

    return price


def test_a_large_download_is_named_and_marked_large():
    plans = [InstallPlan(slug="cocktail", packages=("speechbrain", "torch"))]

    msg = describe_install_start(
        plans, price=_price({"cocktail": ("downloads up to ~3.1 GB (37 packages)", True)})
    )

    assert "3.1 GB" in msg
    assert "Large download" in msg
    assert "cocktail" in msg


def test_a_large_download_says_it_cannot_be_stopped():
    """The CLI can offer Ctrl-C. This window cannot offer anything, and saying so is
    the only honest substitute -- the worker has no interrupt and Apply is disabled."""
    plans = [InstallPlan(slug="voiceguard", packages=("speechbrain",))]

    msg = describe_install_start(
        plans, price=_price({"voiceguard": ("downloads up to ~3.1 GB (37 packages)", True)})
    )

    assert "cannot be stopped" in msg or "cannot be cancelled" in msg


def test_an_ordinary_download_is_still_priced_without_the_alarm():
    plans = [InstallPlan(slug="gaze", packages=("mediapipe",))]

    msg = describe_install_start(
        plans, price=_price({"gaze": ("downloads up to ~219 MB (12 packages)", False)})
    )

    assert "219 MB" in msg
    assert "Large download" not in msg


def test_an_unpriceable_install_keeps_the_plain_line():
    """A size is a courtesy. No size must not mean no message."""
    plans = [InstallPlan(slug="chinese-script", packages=("hanzidentifier",))]

    msg = describe_install_start(plans, price=_price({}))

    assert "chinese-script" in msg
    assert "Installing" in msg


def test_every_capability_in_the_run_is_named():
    plans = [
        InstallPlan(slug="gaze", packages=("mediapipe",)),
        InstallPlan(slug="cocktail", packages=("speechbrain",)),
    ]

    msg = describe_install_start(
        plans,
        price=_price(
            {
                "gaze": ("downloads up to ~219 MB", False),
                "cocktail": ("downloads up to ~3.1 GB", True),
            }
        ),
    )

    assert "gaze" in msg and "cocktail" in msg
    assert "Large download" in msg, "one loud member makes the whole run loud"


def test_a_pricing_lookup_that_raises_never_breaks_the_message():
    """`depsize` reads a committed table and can be absent or malformed. The CLI's own
    rule is that a size must never break the thing it annotates."""

    def explode(slug, packages):
        raise RuntimeError("catalogue unreadable")

    msg = describe_install_start(
        [InstallPlan(slug="gaze", packages=("mediapipe",))], price=explode
    )

    assert "gaze" in msg
    assert "Installing" in msg


def test_no_plans_says_nothing():
    assert describe_install_start([], price=_price({})) == ""


def test_the_window_shows_this_message_rather_than_one_of_its_own():
    """The guard against the two drifting apart again -- the defect was a second,
    hardcoded sentence living in the Qt layer where no test could reach it."""
    from yazses.settingsui.app import SettingsWindow

    src = inspect.getsource(SettingsWindow._start_install_worker)

    assert "describe_install_start" in src
    assert "this can take a few minutes" not in src, "the hardcoded line is back"
