"""The Settings window's Check-for-updates and Install-now buttons, headless (offscreen Qt).

Every effect is a fake (``maintenance_panel.Services``): no network, no installer, no
daemon. Most cases use a synchronous runner so the flow is deterministic; the cases that
prove the work leaves the UI thread use the real ``QtRunner``.
"""

from __future__ import annotations

import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui import maintenance as m  # noqa: E402
from yazses.settingsui import maintenance_panel as mp  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402
from yazses.system.dormant import DormantFeature  # noqa: E402
from yazses.system.installer_update import ALL_USERS_NOTE, HandoffResult, Offer  # noqa: E402
from yazses.system.updater import UpdateStatus, UpgradeOutcome, manual_update_steps  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class _SyncRunner:
    """Runs the task inline: the flow, without the thread."""

    def __init__(self):
        self.ran = 0

    def run(self, fn, on_progress, on_done):
        self.ran += 1
        try:
            result = fn(on_progress)
        except Exception as exc:  # noqa: BLE001 - mirrors the real runner
            result = exc
        on_done(result)


def _window(qapp):
    controller = SettingsController(lambda: Config(), lambda *a: None, lambda mods: [])
    win = SettingsWindow(build_settings_model(Config()), controller)
    win._daemon_running = lambda: False  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    win._run_restart = lambda: (False, "not in a test")  # type: ignore[method-assign]
    win.warned = []  # type: ignore[attr-defined]
    win._warn = lambda title, body: win.warned.append((title, body))  # type: ignore[method-assign]
    win.restarts = []  # type: ignore[attr-defined]
    win._offer_restart = lambda summary="": win.restarts.append(summary)  # type: ignore[method-assign]
    return win


def _status(method="windows-installer", **kw):
    base = dict(method=method, current="2.43.2", latest="2.44.0", available=True,
                command=None, note="", steps=manual_update_steps(method))
    base.update(kw)
    return UpdateStatus(**base)


class _Fakes:
    def __init__(self, *, check=None, rows=(), confirm=True):
        self.check_result = check
        self.rows = list(rows)
        self.handed_off: list = []
        self.upgraded: list = []
        self.installed: list = []
        self.opened = 0
        self.quits = 0
        self.scans = 0
        self.hand_off_result = HandoffResult(ok=True, title="Updating",
                                             message="Closing to install 2.44.0.")
        self.upgrade_result = UpgradeOutcome(code=0, before="2.43.2", after="2.44.0",
                                             expected="2.44.0", method="uv")
        self.pip_ok = True
        self.pip_lines: list[str] = ["Installing dependencies: kokoro-onnx"]
        self.pack_result = None
        self.addons: tuple = ()
        self.consents: list = []

    def services(self):
        def hand_off(status, launcher, progress):
            progress("Downloading the installer…", 0.5)
            self.handed_off.append((status, launcher))
            return self.hand_off_result

        def upgrade(status):
            self.upgraded.append(status)
            return self.upgrade_result

        def scan(controller):
            self.scans += 1
            return list(self.rows)

        def install_pip(row, echo):
            for line in self.pip_lines:
                echo(line)
            self.installed.append(("pip", row.slug))
            return self.pip_ok

        def install_pack(row, progress):
            progress("Downloading the add-on…", 0.25)
            self.installed.append(("pack", row.slug))
            return self.pack_result

        def open_page():
            self.opened += 1
            return True

        def quit_app():
            self.quits += 1

        def consent(status, addons):
            self.consents.append((status.latest, tuple(addons)))
            return True

        return mp.Services(
            version=lambda: "2.43.2",
            check=lambda: self.check_result,
            hand_off=hand_off, upgrade=upgrade, open_page=open_page, scan=scan,
            install_pip=install_pip, install_pack=install_pack, quit_app=quit_app,
            addons=lambda: self.addons, consent=consent,
        )


def _panel(qapp, fakes, *, confirm=True, runner=None, win=None):
    win = win or _window(qapp)
    panel = mp.MaintenancePanel(win, services=fakes.services(), runner=runner or _SyncRunner())
    panel.asked = []  # type: ignore[attr-defined]

    def _confirm(title, text):
        panel.asked.append((title, text))  # type: ignore[attr-defined]
        return confirm

    panel.confirm = _confirm  # type: ignore[method-assign]
    return win, panel


def _dormant(slug="tts", installable=True, remedy="Install them with:  yazses features enable tts"):
    return DormantFeature(slug=slug, name=slug.upper(), missing=("kokoro_onnx",),
                          packages=("kokoro-onnx",), remedy=remedy,
                          installable=installable, command=f"yazses features enable {slug}")


def _rows(*items):
    return m.install_rows(list(items), size_note=lambda i: ("downloads ~80 MB", "~80 MB"))


def _wait(qapp, predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---- wiring -------------------------------------------------------------------


def test_the_settings_window_carries_the_box_with_its_check_button(qapp):
    win = _window(qapp)
    panel = win._maintenance
    assert isinstance(panel.check_button, QPushButton)
    assert panel.check_button.text() == m.CHECK_LABEL
    assert "Installed: YazSes" in panel.update_label.text()
    # The test window's probe reports nothing missing, so no Install-now rows appear.
    assert panel._row_buttons == {}
    assert not panel.action_button.isVisible()


# ---- Check for updates ----------------------------------------------------------


def test_one_click_confirmed_hands_off_then_quits(qapp, monkeypatch):
    monkeypatch.setattr(mp, "HANDOFF_QUIT_DELAY_MS", 0)
    status, launcher = _status(), object()
    fakes = _Fakes(check=(status, Offer(True), launcher))
    win, panel = _panel(qapp, fakes)
    panel.on_check()
    assert "Available: 2.44.0" in panel.update_label.text()
    assert panel.action_button.text() == m.INSTALL_LABEL
    panel.on_action()
    # The ADR-027 question, word for word, then the shared hand-off with this status.
    assert panel.asked and panel.asked[0][0] == "Install the YazSes update?"
    assert fakes.handed_off == [(status, launcher)]
    assert "closes now" in panel.update_label.text()
    assert _wait(qapp, lambda: fakes.quits == 1)
    # Nothing else may start while the update job waits for this process to exit.
    assert not panel.check_button.isEnabled()


def test_declining_the_question_downloads_nothing(qapp):
    fakes = _Fakes(check=(_status(), Offer(True), object()))
    _win, panel = _panel(qapp, fakes, confirm=False)
    panel.on_check()
    panel.on_action()
    assert fakes.handed_off == [] and fakes.quits == 0
    assert "Nothing was downloaded" in panel.update_label.text()
    assert panel.check_button.isEnabled()


def test_staged_changes_are_named_in_the_one_click_question(qapp):
    fakes = _Fakes(check=(_status(), Offer(True), object()))
    win, panel = _panel(qapp, fakes, confirm=False)
    win._pending.stage("cocktail", not win._pending.current("cocktail"))
    panel.on_check()
    panel.on_action()
    assert "1 staged change" in panel.asked[0][1]


def test_a_failed_hand_off_keeps_the_window_and_offers_the_page(qapp):
    fakes = _Fakes(check=(_status(), Offer(True), object()))
    fakes.hand_off_result = HandoffResult(ok=False, title="Update not installed",
                                          message="checksum mismatch", steps=["Use the page."])
    _win, panel = _panel(qapp, fakes)
    panel.on_check()
    panel.on_action()
    assert fakes.quits == 0
    assert "checksum mismatch" in panel.update_label.text()
    assert panel.action_button.text() == m.OPEN_PAGE_LABEL
    panel.on_action()
    assert fakes.opened == 1
    assert panel.check_button.isEnabled()


def test_the_all_users_question_says_windows_will_ask_for_administrator_permission(qapp):
    # The UAC prompt names Windows PowerShell, not YazSes; the question must say so
    # before the user is asked, as the tray's does.
    fakes = _Fakes(check=(_status(), Offer(True, all_users=True), object()), confirm=False)
    _win, panel = _panel(qapp, fakes)
    panel.on_check()
    panel.on_action()
    assert ALL_USERS_NOTE in panel.asked[0][1]


def test_the_per_user_question_does_not_mention_administrator_permission(qapp):
    fakes = _Fakes(check=(_status(), Offer(True), object()), confirm=False)
    _win, panel = _panel(qapp, fakes)
    panel.on_check()
    panel.on_action()
    assert ALL_USERS_NOTE not in panel.asked[0][1]


def test_the_question_names_the_installed_addons_and_a_started_hand_off_records_the_yes(qapp):
    # ADR-028 Q3: the add-ons come from this (old) build's index; the yes is the consent
    # the new version's first start acts on, recorded only once the hand-off started.
    fakes = _Fakes(check=(_status(), Offer(True, all_users=True), object()))
    fakes.addons = (("diarization", 15_000_000),)
    _win, panel = _panel(qapp, fakes)
    panel.on_check()
    panel.on_action()
    assert "Your add-on (Diarization, 15 MB)" in panel.asked[0][1]
    assert ALL_USERS_NOTE in panel.asked[0][1]
    assert fakes.consents == [("2.44.0", (("diarization", 15_000_000),))]


@pytest.mark.parametrize("confirm, ok", [(False, True), (True, False)])
def test_a_no_or_a_failed_hand_off_records_no_addon_consent(qapp, confirm, ok):
    fakes = _Fakes(check=(_status(), Offer(True), object()))
    fakes.addons = (("diarization", 15_000_000),)
    fakes.hand_off_result = HandoffResult(ok=ok, title="t", message="m")
    _win, panel = _panel(qapp, fakes, confirm=confirm)
    panel.on_check()
    panel.on_action()
    assert fakes.consents == []


def test_no_addons_no_sentence_and_no_consent(qapp):
    fakes = _Fakes(check=(_status(), Offer(True), object()))
    _win, panel = _panel(qapp, fakes)
    panel.on_check()
    panel.on_action()
    assert "add-on" not in panel.asked[0][1] and fakes.consents == []


def test_a_refused_one_click_shows_the_manual_steps_and_the_page_button(qapp):
    status = _status()
    reason = ("Could not tell whether YazSes is installed for this user or for all users. "
              "Run the installer from the releases page: it upgrades in place, no uninstall.")
    fakes = _Fakes(check=(status, Offer(False, reason), object()))
    _win, panel = _panel(qapp, fakes)
    panel.on_check()
    text = panel.update_label.text()
    assert reason in text
    assert any(step in text for step in status.steps if step.strip())
    assert panel.action_button.text() == m.OPEN_PAGE_LABEL
    panel.on_action()
    assert fakes.opened == 1 and fakes.handed_off == [] and panel.asked == []


def test_a_pip_family_upgrade_runs_checked_and_offers_the_restart(qapp):
    status = _status("uv", command=["uv", "tool", "upgrade", "yazses"])
    fakes = _Fakes(check=(status, None, None))
    win, panel = _panel(qapp, fakes)
    panel.on_check()
    assert "uv tool upgrade yazses" in panel.update_label.text()
    panel.on_action()
    assert "uv tool upgrade yazses" in panel.asked[0][1]
    assert fakes.upgraded == [status]
    assert "Updated to 2.44.0" in panel.update_label.text()
    assert len(win.restarts) == 1


def test_an_upgrade_that_did_not_move_the_version_offers_no_restart(qapp):
    status = _status("uv", command=["uv", "tool", "upgrade", "yazses"])
    fakes = _Fakes(check=(status, None, None))
    fakes.upgrade_result = UpgradeOutcome(code=0, before="2.43.2", after="2.43.2",
                                          expected="2.44.0", method="uv",
                                          command=status.command)
    win, panel = _panel(qapp, fakes)
    panel.on_check()
    panel.on_action()
    assert win.restarts == []
    assert "still 2.43.2" in panel.update_label.text()


def test_a_check_that_raises_is_reported_not_raised(qapp):
    fakes = _Fakes()
    services = fakes.services()

    def boom():
        raise OSError("name resolution failed")

    services.check = boom
    win = _window(qapp)
    panel = mp.MaintenancePanel(win, services=services, runner=_SyncRunner())
    panel.on_check()
    assert "name resolution failed" in panel.update_label.text()
    assert panel.check_button.isEnabled()


def test_the_check_leaves_the_ui_thread_and_reports_back_on_it(qapp):
    """With the real QtRunner: on_check returns at once, the work runs elsewhere."""
    release = threading.Event()
    seen: dict = {}
    fakes = _Fakes()
    services = fakes.services()

    def slow_check():
        seen["worker"] = threading.current_thread()
        assert release.wait(5)
        return (_status("uv", latest="2.43.2", available=False), None, None)

    services.check = slow_check
    win = _window(qapp)
    runner = mp.QtRunner(win._win)
    panel = mp.MaintenancePanel(win, services=services, runner=runner)
    original = panel._on_checked

    def on_checked(result):
        seen["delivered"] = threading.current_thread()
        original(result)

    panel._on_checked = on_checked  # type: ignore[method-assign]
    panel.on_check()
    # Returned while the check is still blocked: the UI thread was never held.
    assert "Checking for updates" in panel.update_label.text()
    assert not panel.check_button.isEnabled()
    assert _wait(qapp, lambda: "worker" in seen)
    release.set()
    assert _wait(qapp, lambda: "delivered" in seen and runner.running == 0)
    assert seen["worker"] is not threading.main_thread()
    assert seen["delivered"] is threading.main_thread()
    assert "latest version" in panel.update_label.text()


# ---- Install now ----------------------------------------------------------------


def test_a_dormant_feature_gets_an_install_button_with_its_size(qapp):
    fakes = _Fakes(rows=_rows(_dormant()))
    _win, panel = _panel(qapp, fakes)
    button = panel._row_buttons["tts"]
    assert button.text() == "Install now (~80 MB)"
    assert button.isEnabled()
    assert "1 switched-on feature" in panel.features_label.text()


def test_a_refused_environment_shows_a_disabled_button_with_the_reason(qapp):
    reason = "this is a snap, whose packages are fixed; install from PyPI instead"
    fakes = _Fakes(rows=_rows(_dormant(installable=False, remedy=reason)))
    _win, panel = _panel(qapp, fakes)
    button = panel._row_buttons["tts"]
    assert not button.isEnabled()
    assert reason in button.toolTip()
    panel.on_install(panel._rows[0])
    assert fakes.installed == []


def test_install_now_runs_the_install_rescans_and_offers_the_restart(qapp):
    fakes = _Fakes(rows=_rows(_dormant()))
    win, panel = _panel(qapp, fakes)
    scans = fakes.scans
    panel.on_install(panel._rows[0])
    assert fakes.installed == [("pip", "tts")]
    assert "Restart YazSes" in panel.install_label.text()
    assert fakes.scans == scans + 1  # the row list is rebuilt from a fresh probe
    assert len(win.restarts) == 1 and win.warned == []
    assert win._apply_button.isEnabled()


def test_a_failed_install_reports_the_complete_rollback(qapp):
    fakes = _Fakes(rows=_rows(_dormant()))
    fakes.pip_ok = False
    fakes.pip_lines = [
        "The install failed part-way, after changing: numpy. Undoing it.",
        "Undone: the environment is exactly as it was before the install.",
    ]
    win, panel = _panel(qapp, fakes)
    panel.on_install(panel._rows[0])
    assert "exactly as it was" in panel.install_label.text()
    assert win.restarts == []
    assert win.warned and win.warned[0][0] == "TTS could not be installed"


def test_an_incomplete_rollback_is_a_warning_with_the_restore_commands(qapp):
    fakes = _Fakes(rows=_rows(_dormant()))
    fakes.pip_ok = False
    fakes.pip_lines = [
        "Could NOT fully undo the install — still different: numpy 2.3.0.\n"
        "Restore it by hand:\n  uv pip install numpy==2.1.0",
    ]
    win, panel = _panel(qapp, fakes)
    panel.on_install(panel._rows[0])
    title, body = win.warned[0]
    assert title == "The install was not fully undone"
    assert "uv pip install numpy==2.1.0" in body


def test_a_pack_row_installs_the_add_on(qapp):
    from yazses.packs.install import InstallResult
    from yazses.packs.state import NOT_INSTALLED

    class _S:
        state, message, download_bytes, unpacked_bytes = (
            NOT_INSTALLED, "Needs the Tts add-on.", 220_000_000, 600_000_000)

    rows = m.install_rows([_dormant(installable=False)], size_note=lambda i: ("", ""),
                          pack_status=lambda s: _S(), pack_entry=lambda s: object())
    fakes = _Fakes(rows=rows)
    fakes.pack_result = InstallResult(True, "Installed", "The Tts add-on is installed.")
    win, panel = _panel(qapp, fakes)
    assert panel._row_buttons["tts"].text() == "Install now (220 MB)"
    panel.on_install(panel._rows[0])
    assert fakes.installed == [("pack", "tts")]
    assert len(win.restarts) == 1


def test_install_waits_for_the_windows_own_install(qapp):
    fakes = _Fakes(rows=_rows(_dormant()))
    win, panel = _panel(qapp, fakes)
    win._apply_button.setEnabled(False)  # Apply's own install worker is running
    panel.on_install(panel._rows[0])
    assert fakes.installed == []
    assert "Another install is running" in panel.install_label.text()
    win._apply_button.setEnabled(True)


def test_the_install_runs_off_the_ui_thread_and_disables_apply_meanwhile(qapp):
    release = threading.Event()
    where: dict = {}
    fakes = _Fakes(rows=_rows(_dormant()))
    services = fakes.services()

    def install_pip(row, echo):
        where["worker"] = threading.current_thread()
        echo("Collecting kokoro-onnx")
        assert release.wait(5)
        return True

    services.install_pip = install_pip
    win = _window(qapp)
    runner = mp.QtRunner(win._win)
    panel = mp.MaintenancePanel(win, services=services, runner=runner)
    panel.on_install(panel._rows[0])
    assert not win._apply_button.isEnabled()
    assert not panel._row_buttons["tts"].isEnabled()
    assert _wait(qapp, lambda: "Collecting kokoro-onnx" in panel.install_label.text())
    release.set()
    assert _wait(qapp, lambda: runner.running == 0 and win._apply_button.isEnabled())
    assert where["worker"] is not threading.main_thread()
    assert len(win.restarts) == 1


# ---- the defaults call the shared functions, not copies of them -----------------------


def test_the_default_hand_off_is_the_shared_one_with_the_clis_tray_and_daemon_seams(monkeypatch):
    import yazses.cli as cli
    import yazses.tray.updates as updates

    calls = {}

    def fake(status, launcher, **kw):
        calls.update(kw, status=status, launcher=launcher)
        return "result"

    monkeypatch.setattr(updates, "hand_off_outside_tray", fake)
    assert mp._default_hand_off("S", "L", "P") == "result"
    assert calls["status"] == "S" and calls["launcher"] == "L" and calls["progress"] == "P"
    assert calls["tray_pid"] is cli._running_tray_pid
    assert calls["request_daemon_shutdown"] is cli._request_daemon_shutdown


def test_the_default_check_resolves_the_command_that_keeps_enabled_features(monkeypatch):
    import yazses.cli as cli
    import yazses.system.installer_update as iu
    import yazses.system.updater as updater
    import yazses.tray.updates as updates

    plain = _status("uv", command=["uv", "tool", "upgrade", "yazses"])
    kept = _status("uv", command=["uv", "tool", "upgrade", "yazses", "--with", "x"])
    monkeypatch.setattr(updates, "check_updates", lambda: plain)
    monkeypatch.setattr(cli, "_update_launcher", lambda: None)
    monkeypatch.setattr(iu, "one_click_offer", lambda status, launcher: None)
    monkeypatch.setattr(updater, "preserve_enabled_features", lambda status: kept)
    assert mp._default_check() == (kept, None, None)


def test_the_default_install_is_the_on_demand_transactional_one(monkeypatch):
    import yazses.system.ondemand as ondemand

    seen = {}

    def fake(item, *, install=None, echo=None):
        seen.update(item=item, echo=echo)
        return True

    monkeypatch.setattr(ondemand, "install_one", fake)
    row = _rows(_dormant())[0]
    echo = lambda line: None  # noqa: E731
    assert mp._default_install_pip(row, echo) is True
    assert seen == {"item": row.item, "echo": echo}


def test_the_default_scan_uses_the_windows_own_probes(monkeypatch):
    class _Controller:
        _deps_probe = staticmethod(lambda mods: list(mods))  # everything missing
        _blocked_probe = staticmethod(lambda packages: None)

        def load_config(self):
            cfg = Config()
            cfg.denoise.enabled = True
            return cfg

    rows = {r.slug: r for r in mp.default_scan(_Controller())}
    assert "denoise" in rows  # the real dormant_features, over the window's probes
    assert rows["denoise"].route == m.PIP and rows["denoise"].installable

    class _Nothing(_Controller):
        _deps_probe = staticmethod(lambda mods: [])

    assert mp.default_scan(_Nothing()) == []
