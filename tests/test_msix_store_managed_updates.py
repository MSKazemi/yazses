"""A packaged (MSIX / Microsoft Store) YazSes never updates itself.

The Store replaces the package, and the install folder under ``C:\\Program Files\\WindowsApps``
is read-only to the app, so a self-update there cannot work and would install a second,
unrelated copy beside the package. ADR-027 already gave the MSIX its own install method
(``msix``) with Store steps and no one-click. This file pins the rest of the contract:

* the update check makes **no network call** for a packaged build and says it is managed by
  the Microsoft Store, on every surface (``yazses update``, the tray/settings message, the
  ``doctor`` row), instead of "could not check -- offline?";
* "am I packaged?" can be answered from the OS's own package identity
  (``GetCurrentPackageFullName``), not only from an ``AppxManifest.xml`` beside the exe;
* a non-packaged install behaves exactly as before.

Everything about real MSIX behaviour is UNTESTED on Windows. These tests prove the logic with
fakes on any OS; they do not prove that a Store install does what the code expects.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
import yazses.system.updater as updater
from yazses.platform.windows import host as winhost
from yazses.system.updater import UpdateStatus

runner = CliRunner()

# winerror.h
APPMODEL_ERROR_NO_PACKAGE = 15700
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_SUCCESS = 0


# ----------------------------------------------------------------- the update check is a no-op


def _no_network(*_a, **_k):
    raise AssertionError("a packaged build must not reach the network to look for an update")


def test_a_packaged_build_checks_nothing_and_says_the_store_manages_it(monkeypatch):
    monkeypatch.setattr(updater, "_latest_for_method", _no_network)
    status = updater.check_update("2.51.0", method="msix")
    assert status.method == "msix"
    assert status.managed_by == "the Microsoft Store"
    assert status.available is False
    assert status.command is None
    assert status.latest is None
    assert "Microsoft Store" in status.note
    # The steps still say how an update arrives, and never send anyone to the .exe.
    joined = "\n".join(status.steps)
    assert "Microsoft Store" in joined and "second copy" in joined


def test_an_unpackaged_install_still_asks_its_source(monkeypatch):
    seen: list[str] = []

    def _latest(method, package):
        seen.append(method)
        return "9.9.9"

    monkeypatch.setattr(updater, "_latest_for_method", _latest)
    for method in ("windows-installer", "pip", "choco"):
        status = updater.check_update("2.51.0", method=method)
        assert status.managed_by == ""
        assert status.available is True and status.latest == "9.9.9"
    assert seen == ["windows-installer", "pip", "choco"]


def test_the_detected_method_drives_it_too(monkeypatch):
    """No ``method=`` argument, as every real caller calls it: the host fact decides."""
    monkeypatch.setattr(updater, "_latest_for_method", _no_network)
    monkeypatch.setattr(updater, "detect_install_method", lambda *a, **k: "msix")
    assert updater.check_update("2.51.0").managed_by == "the Microsoft Store"


# ----------------------------------------------------------------- `yazses update`


def _managed_status() -> UpdateStatus:
    return UpdateStatus(
        method="msix", current="2.51.0", latest=None, available=False, command=None,
        note=updater.MSIX_MANAGED_NOTE, steps=updater.manual_update_steps("msix"),
        managed_by=updater.MSIX_MANAGED_BY,
    )


def test_yazses_update_on_a_packaged_build_explains_and_exits_clean(monkeypatch):
    monkeypatch.setattr(updater, "check_update", lambda current: _managed_status())
    monkeypatch.setattr(cli, "_installed_version", lambda: "2.51.0")
    ran: list[object] = []
    monkeypatch.setattr(updater, "run_upgrade_checked", lambda s: ran.append(s))
    result = runner.invoke(cli.app, ["update"])
    out = result.output
    assert result.exit_code == 0, out
    assert "via msix" in out
    assert "managed by the Microsoft Store" in out
    assert "Could not check" not in out
    assert ran == []


def test_yazses_update_check_flag_on_a_packaged_build_is_also_clean(monkeypatch):
    monkeypatch.setattr(updater, "check_update", lambda current: _managed_status())
    monkeypatch.setattr(cli, "_installed_version", lambda: "2.51.0")
    result = runner.invoke(cli.app, ["update", "--check"])
    assert result.exit_code == 0, result.output
    assert "managed by the Microsoft Store" in result.output


# ----------------------------------------------------------------- tray / settings message


def test_the_tray_message_for_a_packaged_build_is_not_a_failed_check():
    from yazses.tray.about import update_message

    title, body = update_message(_managed_status())
    assert "managed by the Microsoft Store" in body
    assert "Could not check" not in body
    assert "Update available" not in title


def test_the_settings_window_offers_no_update_action_for_a_packaged_build():
    from yazses.settingsui.maintenance import UpdateAction, plan_update

    view = plan_update(_managed_status(), None)
    assert "managed by the Microsoft Store" in view.text
    assert view.action is UpdateAction.NONE


def test_the_background_watcher_has_nothing_to_announce_for_a_packaged_build():
    from yazses.system import update_notify

    assert update_notify.should_notify(_managed_status(), "") is False


# ----------------------------------------------------------------- doctor


def test_doctor_row_says_the_store_manages_updates_whatever_the_watcher_setting():
    from yazses.system.doctor import _update_check_check

    for enabled in (False, True):
        name, status, detail = _update_check_check(enabled, managed_by="the Microsoft Store")
        assert name == "Update check"
        assert status == "SKIP"
        assert "managed by the Microsoft Store" in detail
        assert "features enable update-check" not in detail  # no advice that cannot apply


def test_doctor_row_is_unchanged_for_everyone_else():
    from yazses.system.doctor import _update_check_check

    assert _update_check_check(False)[2].endswith("yazses features enable update-check")
    assert _update_check_check(True)[1] == "OK"


# ----------------------------------------------------------------- package identity (platform seam)


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (ERROR_INSUFFICIENT_BUFFER, True),  # the documented "has identity" answer to a size probe
        (ERROR_SUCCESS, True),
        (APPMODEL_ERROR_NO_PACKAGE, False),
        (5, False),  # any other error is "do not know", which must not claim packaged
        (-1, False),
    ],
)
def test_package_identity_is_read_from_the_documented_return_codes(code, expected):
    assert winhost.has_package_identity(lambda: code) is expected


def test_a_failing_identity_probe_is_not_packaged():
    def boom():
        raise OSError("no kernel32 here")

    assert winhost.has_package_identity(boom) is False


def test_the_real_probe_is_absent_off_windows_and_answers_not_packaged():
    # Linux CI: no ctypes.windll. Must answer False, never raise.
    assert winhost.has_package_identity() is False


def _frozen(monkeypatch, tmp_path: Path) -> Path:
    exe = tmp_path / "YazSesApp.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    return exe


def test_a_frozen_exe_with_package_identity_is_packaged_without_a_manifest_beside_it(
    monkeypatch, tmp_path
):
    _frozen(monkeypatch, tmp_path)
    assert winhost._msix_packaged(identity=lambda: True) is True


def test_a_frozen_exe_with_a_manifest_but_no_identity_is_still_packaged(monkeypatch, tmp_path):
    """The existing signal is kept: identity is an addition, never a replacement."""
    _frozen(monkeypatch, tmp_path)
    (tmp_path / "AppxManifest.xml").write_text("<Package/>", encoding="utf-8")
    assert winhost._msix_packaged(identity=lambda: False) is True


def test_a_frozen_exe_with_neither_is_a_plain_exe(monkeypatch, tmp_path):
    _frozen(monkeypatch, tmp_path)
    assert winhost._msix_packaged(identity=lambda: False) is False


def test_an_unfrozen_interpreter_is_never_packaged_even_with_identity(monkeypatch, tmp_path):
    """A pip install run by the Store's Python has *Python's* package identity, not ours."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "python.exe"))
    assert winhost._msix_packaged(identity=lambda: True) is False


def test_the_doctor_asks_the_same_question_update_does(monkeypatch):
    from yazses.system import doctor

    monkeypatch.setattr(updater, "detect_install_method", lambda *a, **k: "msix")
    assert doctor._update_managed_by() == "the Microsoft Store"
    monkeypatch.setattr(updater, "detect_install_method", lambda *a, **k: "windows-installer")
    assert doctor._update_managed_by() == ""

    def boom(*a, **k):
        raise RuntimeError("probe failed")

    monkeypatch.setattr(updater, "detect_install_method", boom)
    assert doctor._update_managed_by() == ""  # a failed probe is "not packaged", never an error
