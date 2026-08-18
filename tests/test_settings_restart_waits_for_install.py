"""Apply must not restart the daemon while it is still downloading the packages.

`_on_apply` does two things at the end, in this order:

    self._install_missing(report.missing_packages)   # QThread, "can take a few minutes"
    ...
    self._offer_restart(summary)                     # modal -> subprocess.run(timeout=90)

They were unsequenced, so enabling a capability with heavy optional dependencies —
`stt-parakeet`, `gaze` — offered the restart *while pip was still running*:

* the daemon restarts before the packages land, so it comes up with the capability
  switched **on** in config and its import still failing. The user was told it applied.
  It does not work, and nothing says so.
* `_run_restart` is a synchronous ``subprocess.run(..., timeout=90)`` on the **UI
  thread**, so accepting the prompt freezes the window for up to a minute and a half
  while the install thread streams progress into it. A frozen window is what a desktop
  offers to force-close — which is how "applying a feature from the GUI closes it"
  happens with nothing in this code closing anything.

The restart is now held until `_on_install_finished`, including when packages failed:
the rest of the change did land and still needs a restart, and `describe_summary` has
already reported the failure.

## Why it drives the real thing

The bug is an ordering between two real methods, so a test that stubs either of them
proves nothing. This runs the actual `_on_apply` against the actual feature registry,
picking a slug that genuinely has pip packages — the first attempt at this used a
feature whose "packages" were module names, no install started, and the run was green
while the defect was untouched.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402
from yazses.system.features import feature_status  # noqa: E402

#: A capability whose install is a real download, i.e. one where the ordering bites.
HEAVY_SLUG = "stt-parakeet"


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _window(cfg):
    win = SettingsWindow(
        build_settings_model(cfg),
        SettingsController(lambda: cfg, lambda s, k, v, q: None, lambda mods: list(mods)),
    )
    win._warn = lambda title, body: None  # type: ignore[method-assign]
    win._confirm_experimental = lambda row: True  # type: ignore[method-assign]
    return win


def test_the_heavy_feature_really_installs_something() -> None:
    """The premise. Without real packages this whole file tests nothing.

    Checked against the registry rather than assumed: an earlier version of this test
    picked a feature whose `pip_packages` were module names, so no worker ever started
    and the assertions below passed on an untouched bug.
    """
    feature = next(
        (f for f in feature_status(Config()) if f.slug == HEAVY_SLUG), None
    )
    assert feature is not None, f"{HEAVY_SLUG} left the registry"
    assert feature.pip_packages, f"{HEAVY_SLUG} no longer declares pip packages"
    # `feature_packages()` is a different accessor entirely -- it returns module
    # paths ('stt'), not installables. Reaching for it is what made the first
    # version of this file green against an untouched bug.
    assert any(
        ">=" in p or "==" in p or "[" in p for p in feature.pip_packages
    ), f"{HEAVY_SLUG} packages look like module names: {feature.pip_packages}"


def test_apply_defers_the_restart_until_the_install_finishes(qapp, monkeypatch) -> None:
    cfg = Config()
    win = _window(cfg)
    assert HEAVY_SLUG in win._checkboxes, f"{HEAVY_SLUG} has no row in the window"

    offers: list[str] = []
    win._offer_restart = lambda summary="": offers.append(summary)  # type: ignore[method-assign]

    # Freeze the worker mid-install: `_install_thread` stays set, which is exactly the
    # state Apply used to ignore. Nothing is downloaded.
    started: list[object] = []
    monkeypatch.setattr(
        SettingsWindow, "_start_install_worker",
        lambda self, plans: (started.append(plans), setattr(self, "_install_thread", object()))[0],
    )

    win._checkboxes[HEAVY_SLUG].setChecked(True)
    win._on_apply()

    assert started, "no install was started — the ordering under test never happened"
    assert offers == [], (
        "the restart was offered while packages were still installing; the daemon would "
        "come up with the capability on and its dependency missing"
    )
    assert win._restart_when_installed is not None, "the restart was dropped, not deferred"


def test_the_deferred_restart_is_offered_when_the_install_finishes(qapp, monkeypatch) -> None:
    """Deferred, not cancelled — dropping it silently would be a worse bug."""
    from yazses.settingsui.deps import InstallOutcome, InstallSummary

    cfg = Config()
    win = _window(cfg)
    offers: list[str] = []
    win._offer_restart = lambda summary="": offers.append(summary)  # type: ignore[method-assign]
    monkeypatch.setattr(
        SettingsWindow, "_start_install_worker",
        lambda self, plans: setattr(self, "_install_thread", object()),
    )

    win._checkboxes[HEAVY_SLUG].setChecked(True)
    win._on_apply()
    assert offers == []

    win._on_install_finished(
        InstallSummary(outcomes=[InstallOutcome(HEAVY_SLUG, ("onnx-asr",), ok=True)])
    )
    assert len(offers) == 1, "the deferred restart never arrived"
    assert win._restart_when_installed is None, "a second finish would re-offer it"


def test_a_failed_install_still_offers_the_restart(qapp, monkeypatch) -> None:
    """The rest of the change landed and still needs a restart to take effect."""
    from yazses.settingsui.deps import InstallOutcome, InstallSummary

    cfg = Config()
    win = _window(cfg)
    offers: list[str] = []
    win._offer_restart = lambda summary="": offers.append(summary)  # type: ignore[method-assign]
    monkeypatch.setattr(
        SettingsWindow, "_start_install_worker",
        lambda self, plans: setattr(self, "_install_thread", object()),
    )

    win._checkboxes[HEAVY_SLUG].setChecked(True)
    win._on_apply()
    # Asserted before the finish too: without this the test passed against the old
    # code, which offered the restart immediately — right answer, wrong reason.
    assert offers == [], "offered during the install"
    win._on_install_finished(
        InstallSummary(outcomes=[
            InstallOutcome(HEAVY_SLUG, ("onnx-asr",), ok=False, error="no network")
        ])
    )
    assert len(offers) == 1


def test_a_change_needing_no_packages_still_restarts_immediately(qapp) -> None:
    """A guard that delays every restart would be a regression of its own."""
    cfg = Config()
    win = _window(cfg)
    offers: list[str] = []
    win._offer_restart = lambda summary="": offers.append(summary)  # type: ignore[method-assign]

    plain = next(
        f.slug for f in feature_status(cfg)
        if not f.on and f.wired and not f.pip_packages and f.slug in win._checkboxes
    )
    win._checkboxes[plain].setChecked(True)
    win._on_apply()

    assert win._install_thread is None, f"{plain} unexpectedly started an install"
    assert len(offers) == 1, "a no-download change must still offer the restart at once"
    assert win._restart_when_installed is None
