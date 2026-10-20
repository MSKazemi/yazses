"""The hands-free window's stop-route list and its Apply while packages install (#420).

Headless (Qt offscreen), skipped without PySide6. The decisions are pure and tested in
``test_handsfree_panel_stop_routes.py``; held here is only the shell's part:

* the "Ways to stop without pointing" block shows the model's routes and is reached by Tab
  straight after Pause, Resume and Recenter;
* while the settings window is installing packages or preparing a model, this window's Apply
  is disabled with the reason in visible text and in its accessible description -- and the
  stop controls stay usable;
* pressing Apply shows what the settings window says landed, not a fixed "Applied.".
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.handsfree.observability import HandsFreeFacts  # noqa: E402
from yazses.handsfree.panel import FeatureFact, PanelInputs  # noqa: E402
from yazses.handsfree.panel_io import ActionResult  # noqa: E402
from yazses.handsfree.safety import SafetyState, SafetyStatus  # noqa: E402
from yazses.settingsui.handsfree_panel import HandsFreePanel  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _inputs(phrase: str = "") -> PanelInputs:
    return PanelInputs(
        daemon_reachable=True,
        features=(
            FeatureFact("headpointer", "Head-Pointer", True),
            FeatureFact("facegesture", "Face switch", False),
            FeatureFact("gaze", "Gaze", False, wired=False),
        ),
        safety_configured=True,
        facts=HandsFreeFacts(
            features_requested=("headpointer",), camera_ready=True, safety_configured=True,
            safety=SafetyStatus(SafetyState.ACTIVE, "", False, False, 1, ()),
            head_wired=True, face_wired=True,
        ),
        headpointer={"ok": True, "active": True, "state": "tracking", "calibrated": True,
                     "backend": "x11"},
        stop_phrase=phrase,
    )


class _Rig:
    def __init__(self, qapp, *, busy="", summary=None, busy_raises=False, phrase=""):
        self.inputs = _inputs(phrase)
        self.busy = busy
        self.applied = 0
        self.performed: list = []

        def apply():
            self.applied += 1
            return summary

        def busy_fn():
            if busy_raises:
                raise RuntimeError("settings window went away")
            return self.busy

        def perform(spec):
            self.performed.append(spec)
            return ActionResult(True, "ok")

        self.panel = HandsFreePanel(
            lambda: self.inputs,
            perform,
            toggle_feature=lambda _s, _d: None,
            apply_staged=apply,
            apply_busy=busy_fn,
            poll_ms=0,
            threaded=False,
        )
        self.panel.refresh()

    def button(self, ident):
        return self.panel._buttons[ident]


def test_the_routes_block_shows_the_configured_stop_phrase(qapp):
    rig = _Rig(qapp, phrase="pause hands free")
    text = rig.panel._routes.text()
    assert "“pause hands free”" in text and "`yazses handsfree pause`" in text


def test_the_routes_block_is_the_first_tab_stop_after_the_three_emergency_buttons(qapp):
    rig = _Rig(qapp)
    order = rig.panel.tab_order
    assert order[:4] == [
        rig.button("pause"), rig.button("resume"), rig.button("recenter"), rig.panel._routes,
    ]


def test_while_packages_install_apply_is_disabled_with_the_reason_and_stopping_still_works(qapp):
    rig = _Rig(qapp, busy="Installing mediapipe (about 40 MB)…")
    apply = rig.button("apply")
    assert not apply.isEnabled()
    assert "Installing mediapipe" in rig.panel._apply_why.text()
    assert apply.accessibleDescription().startswith("Busy: Installing mediapipe")
    assert rig.button("pause").isEnabled(), "a running install must never block the stop"
    rig.panel._press_apply()  # e.g. a queued activation that lands anyway
    assert rig.applied == 0
    assert rig.panel._result.text().startswith("Not applied: Busy:")
    rig.button("pause").click()
    assert [s.id for s in rig.performed] == ["pause"]


def test_apply_comes_back_when_the_install_finishes(qapp):
    rig = _Rig(qapp, busy="Installing mediapipe…")
    assert not rig.button("apply").isEnabled()
    rig.busy = ""
    rig.panel.refresh()
    assert rig.button("apply").isEnabled()
    assert rig.panel._apply_why.text() == ""


def test_apply_shows_what_the_settings_window_says_landed(qapp):
    summary = "Head-Pointer: on. Installing mediapipe (about 40 MB)… A restart will be offered."
    rig = _Rig(qapp, summary=summary)
    rig.button("apply").click()
    assert rig.applied == 1
    assert rig.panel._result.text() == summary


def test_apply_without_a_summary_keeps_the_old_sentence(qapp):
    rig = _Rig(qapp, summary=None)
    rig.button("apply").click()
    assert rig.panel._result.text().startswith("Applied.")


def test_a_failing_busy_probe_never_raises_into_the_window(qapp):
    rig = _Rig(qapp, busy_raises=True)
    assert rig.button("apply").isEnabled()
    assert rig.button("pause").isEnabled()


def test_the_settings_window_hands_the_panel_its_own_busy_state_and_summary(qapp, monkeypatch):
    """The wiring in `settingsui/app.py`: busy exactly while the window's own Apply is
    disabled (an install or a language preparation is running), and Apply's summary is the
    window's hint line."""
    from yazses.config import Config
    from yazses.settingsui import handsfree_panel as hp_module
    from yazses.settingsui.app import SettingsWindow
    from yazses.settingsui.controller import SettingsController
    from yazses.settingsui.model import build_settings_model

    captured: dict = {}

    class _Stub:
        def __init__(self, gather, perform, **kw):
            captured.update(kw)

        def show(self):
            pass

    monkeypatch.setattr(hp_module, "HandsFreePanel", _Stub)
    controller = SettingsController(Config, lambda s, k, v, q: None, lambda modules: [])
    win = SettingsWindow(build_settings_model(Config()), controller)
    win._handsfree_button.click()
    busy = captured["apply_busy"]

    assert busy() == ""
    win._apply_button.setEnabled(False)
    win._hint.setText("Installing mediapipe…")
    assert busy() == "Installing mediapipe…"
    win._hint.setText("")
    assert busy() == "Packages are being prepared."  # never "" while the Apply is held
    win._apply_button.setEnabled(True)
    assert busy() == ""

    monkeypatch.setattr(win, "_on_apply", lambda: win._hint.setText("Nothing to apply."))
    assert captured["apply_staged"]() == "Nothing to apply."
