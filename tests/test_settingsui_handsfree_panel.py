"""Headless tests for the hands-free controls window (#420).

Skipped without PySide6; runs on Qt's offscreen platform so no window is ever shown on a real
display. The view-model is tested exhaustively in ``test_handsfree_panel.py``; what is held
here is the thin shell's own contract: large targets, a deliberate tab order, state in words
rather than colour, refreshes that never move focus, a disabled button that says why, and a
panel that is displayed without touching the camera or blocking.

**What these tests cannot see** is how it looks: layout, spacing, font rendering, how a real
screen reader announces it. Those need a human at a screen.
"""
from __future__ import annotations

import ast
import os
import threading
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QComboBox, QPushButton  # noqa: E402

from yazses.handsfree.observability import HandsFreeFacts  # noqa: E402
from yazses.handsfree.panel import (  # noqa: E402
    ConfigTableArray,
    FeatureFact,
    PanelInputs,
)
from yazses.handsfree.panel_io import ActionResult  # noqa: E402
from yazses.handsfree.safety import SafetyState, SafetyStatus  # noqa: E402
from yazses.settingsui.handsfree_panel import MIN_TARGET_PX, HandsFreePanel, mnemonic  # noqa: E402

SRC = Path(__file__).resolve().parents[1] / "src" / "yazses"


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


def _status(state: SafetyState, reason: str = "") -> SafetyStatus:
    return SafetyStatus(state, reason, False, state is SafetyState.PAUSED, 1, ())


def _hp(**kw):
    base = {"ok": True, "active": True, "state": "tracking", "reason": "", "paused": False,
            "clutched": False, "calibrated": True, "dwell_enabled": False, "fault": "",
            "backend": "x11"}
    base.update(kw)
    return base


def _inputs(state: SafetyState | None = SafetyState.ACTIVE, *, reachable=True, hp=None,
            reason="", hp_on=True, face_on=False, safety_cfg=True) -> PanelInputs:
    return PanelInputs(
        daemon_reachable=reachable,
        features=(
            FeatureFact("headpointer", "Head-Pointer", hp_on),
            FeatureFact("facegesture", "Face switch", face_on),
            FeatureFact("gaze", "Gaze", False, wired=False),
        ),
        safety_configured=safety_cfg,
        facts=HandsFreeFacts(
            features_requested=tuple(
                n for n, on in (("headpointer", hp_on), ("facegesture", face_on)) if on
            ),
            camera_ready=True, safety_configured=safety_cfg,
            safety=_status(state, reason) if state is not None else None,
            head_wired=True, face_wired=True,
        ),
        headpointer=hp if hp is not None else (_hp() if hp_on and reachable else None),
    )


class _Rig:
    """A panel wired to a mutable input and a recording performer."""

    def __init__(self, qapp, inputs=None, **kw):
        self.inputs = inputs or _inputs()
        self.performed = []
        self.toggled = []
        self.applied = 0
        self.gathers = 0
        self.result = ActionResult(True, "ok")

        def gather():
            self.gathers += 1
            return self.inputs

        def perform(spec):
            self.performed.append(spec)
            return self.result

        self.panel = HandsFreePanel(
            gather, perform,
            toggle_feature=lambda s, d: self.toggled.append((s, d)),
            apply_staged=lambda: setattr(self, "applied", self.applied + 1),
            poll_ms=0, threaded=False, **kw,
        )
        self.panel.refresh()

    def button(self, ident):
        return self.panel._buttons[ident]


# ---------------------------------------------------------------------- targets, order, words


def test_every_button_and_combo_is_a_large_target(qapp):
    rig = _Rig(qapp)
    widgets = rig.panel.dialog.findChildren(QPushButton) + rig.panel.dialog.findChildren(QComboBox)
    assert len(widgets) >= 15
    for w in widgets:
        assert w.minimumHeight() >= MIN_TARGET_PX, w.objectName() or w.text()


def test_pause_resume_recenter_are_first_in_the_tab_order_and_nothing_is_left_out(qapp):
    rig = _Rig(qapp)
    order = rig.panel.tab_order
    assert order[:3] == [rig.button("pause"), rig.button("resume"), rig.button("recenter")]
    interactive = set(rig.panel.dialog.findChildren(QPushButton)) | set(
        rig.panel.dialog.findChildren(QComboBox)
    )
    missing = [w.objectName() or w.text() for w in interactive if w not in order]
    assert missing == [], f"reachable by pointer but not by Tab: {missing}"
    assert len(order) == len(set(map(id, order)))


def test_the_emergency_buttons_have_alt_mnemonics_and_plain_accessible_names(qapp):
    rig = _Rig(qapp)
    assert rig.button("pause").text() == "&Pause hands-free input"
    assert rig.button("resume").text().count("&") == 1
    assert rig.button("recenter").text() == "Re&center Head-Pointer"
    assert rig.button("pause").accessibleName() == "Pause hands-free input"  # no ampersand
    assert mnemonic("Pause", "x") == "Pause"  # a letter that is absent is dropped, not invented


def test_state_is_a_word_and_no_colour_is_used_anywhere(qapp):
    rig = _Rig(qapp, _inputs(SafetyState.FAULTED, reason="headpointer: signal is stale"))
    panel = rig.panel
    assert panel._headline.text().startswith("Faulted")
    health = panel._health.text()
    assert any(f"[{word}]" in health for word in ("OK", "PROBLEM", "NEEDS ATTENTION")), health
    from PySide6.QtWidgets import QWidget

    for w in panel.dialog.findChildren(QWidget):
        assert "color" not in w.styleSheet(), w.objectName()


def test_features_are_described_with_their_state_word(qapp):
    rig = _Rig(qapp)
    text = rig.panel._feature_widgets["headpointer"][0].text()
    assert text.startswith("[OK] Head-Pointer")
    gaze = rig.panel._feature_widgets["gaze"][0].text()
    assert gaze.startswith("[NOT AVAILABLE]") and "not connected" in gaze


# ---------------------------------------------------------------------- the three states


def test_a_faulted_state_enables_recovery_and_pressing_it_performs_resume(qapp):
    rig = _Rig(qapp, _inputs(SafetyState.FAULTED, reason="headpointer: signal is stale (900 ms old)"))
    resume = rig.button("resume")
    assert resume.isEnabled(), "FAULTED must offer a way out"
    assert resume.text().replace("&", "").startswith("Recover")
    resume.click()
    assert rig.performed[-1].id == "resume"
    assert dict(rig.performed[-1].ipc.params) == {"action": "resume"}


def test_pressing_pause_sends_the_global_pause_and_shows_the_result(qapp):
    rig = _Rig(qapp)
    rig.button("pause").click()
    assert rig.performed[-1].ipc.method == "handsfree"
    assert dict(rig.performed[-1].ipc.params) == {"action": "pause"}
    assert rig.panel._result.text().startswith("Done:")


def test_a_failed_action_says_so_in_words(qapp):
    rig = _Rig(qapp)
    rig.result = ActionResult(False, "not ready to re-arm: facegesture")
    rig.button("pause").click()
    assert rig.panel._result.text() == "Did not work: not ready to re-arm: facegesture"


def test_a_disabled_button_says_why_in_visible_text_and_to_a_screen_reader(qapp):
    rig = _Rig(qapp, _inputs(None, reachable=False, safety_cfg=False))
    pause = rig.button("pause")
    assert not pause.isEnabled()
    assert "YazSes is not running" in rig.panel._why_box.text()
    assert pause.accessibleDescription() == "YazSes is not running."


def test_stopping_stays_available_while_controls_are_active(qapp):
    rig = _Rig(qapp, _inputs(SafetyState.ACTIVE))
    assert rig.button("pause").isEnabled() and not rig.button("resume").isEnabled()


# ---------------------------------------------------------------------- refresh discipline


def test_refreshing_never_recreates_a_widget_or_rewrites_unchanged_text(qapp, monkeypatch):
    rig = _Rig(qapp)
    before = {id(w) for w in rig.panel.dialog.findChildren(QPushButton)}
    sets: list[str] = []
    original = type(rig.panel._headline).setText

    def counting(self, text):
        sets.append(text)
        return original(self, text)

    monkeypatch.setattr(type(rig.panel._headline), "setText", counting)
    rig.panel.refresh()
    rig.panel.refresh()
    assert sets == [], "an unchanged sentence must not be set again (a screen reader re-reads it)"
    rig.inputs = _inputs(SafetyState.PAUSED, reason="paused by the user")
    rig.panel.refresh()
    assert {id(w) for w in rig.panel.dialog.findChildren(QPushButton)} == before
    assert rig.panel._headline.text().startswith("Paused")


def test_when_the_focused_button_becomes_unavailable_focus_moves_to_the_one_the_state_wants(qapp):
    rig = _Rig(qapp)
    dialog = rig.panel.dialog
    dialog.show()
    dialog.activateWindow()
    qapp.processEvents()
    rig.button("pause").setFocus()
    qapp.processEvents()
    if QApplication.focusWidget() is not rig.button("pause"):
        pytest.skip("this Qt platform plugin does not grant focus to an offscreen window")
    rig.inputs = _inputs(SafetyState.PAUSED, reason="paused by the user")
    rig.panel.refresh()
    qapp.processEvents()
    assert not rig.button("pause").isEnabled()
    assert QApplication.focusWidget() is rig.button("resume")
    dialog.close()


def test_a_gather_that_fails_is_reported_and_changes_nothing(qapp):
    rig = _Rig(qapp)
    rig.panel._gather = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    rig.panel.refresh()
    assert rig.panel._headline.text() == "Could not read the hands-free state."
    assert rig.button("pause").isEnabled()  # the last good model's controls are not torn down


def test_gathering_runs_off_the_ui_thread_and_overlapping_refreshes_collapse(qapp):
    release = threading.Event()
    seen_threads: list[str] = []
    calls = []

    def gather():
        seen_threads.append(threading.current_thread().name)
        calls.append(1)
        release.wait(5)
        return _inputs()

    panel = HandsFreePanel(
        gather, lambda spec: ActionResult(True, "ok"), poll_ms=0, threaded=True
    )
    started = time.monotonic()
    panel.refresh()
    panel.refresh()
    panel.refresh()
    assert time.monotonic() - started < 1.0, "refresh() must not wait for the gather"
    release.set()
    deadline = time.monotonic() + 5
    while panel._model is None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert panel._model is not None
    assert len(calls) == 1, "three overlapping refreshes should have collapsed into one"
    assert seen_threads == ["handsfree-panel"]


def test_displaying_the_panel_gathers_and_performs_nothing(qapp):
    rig = _Rig(qapp)
    rig.panel.show()
    assert rig.gathers >= 1 and rig.performed == []
    rig.panel.dialog.close()


# ---------------------------------------------------------------------- camera controls


def test_a_feature_button_stages_the_change_through_the_settings_window_path(qapp):
    rig = _Rig(qapp)
    rig.button("feature_headpointer").click()
    assert rig.toggled == [("headpointer", False)]
    assert "staged" in rig.panel._result.text()
    assert not rig.button("feature_gaze").isEnabled(), "a feature that cannot work is not clickable"
    rig.button("apply").click()
    assert rig.applied == 1


# ---------------------------------------------------------------------- dwell and mapping


def test_dwell_off_is_its_own_button(qapp):
    rig = _Rig(qapp, _inputs(hp=_hp(dwell_enabled=True)))
    assert rig.button("dwell_off").isEnabled() and not rig.button("dwell_on").isEnabled()
    rig.button("dwell_off").click()
    assert dict(rig.performed[-1].ipc.params) == {"action": "dwell", "enabled": False}


def test_mapping_choices_that_do_nothing_are_disabled_and_explained(qapp):
    # No global stop and no running Head-Pointer: pause_pointer has nothing to pause (#407).
    rig = _Rig(qapp, _inputs(face_on=True, safety_cfg=False, hp_on=False))
    combo = rig.panel._map_widgets["smile"][1]
    items = {combo.itemData(i): combo.model().item(i) for i in range(combo.count())}
    assert items["hold_to_command"].isEnabled()
    for key in ("select", "confirm", "cancel"):
        assert items[key].isEnabled(), key
    assert not items["pause_pointer"].isEnabled()
    assert items["pause_pointer"].toolTip()

    # With the global stop off but a Head-Pointer running, pause_pointer pauses that
    # pointer, as `handsfree pause` does, so the panel offers it (#407).
    rig = _Rig(qapp, _inputs(face_on=True, safety_cfg=False))
    combo = rig.panel._map_widgets["smile"][1]
    items = {combo.itemData(i): combo.model().item(i) for i in range(combo.count())}
    assert items["pause_pointer"].isEnabled()


def test_saving_a_valid_mapping_writes_a_table_and_an_invalid_one_writes_nothing(qapp):
    rig = _Rig(qapp, _inputs(face_on=True))
    combo = rig.panel._map_widgets["smile"][1]
    combo.setCurrentIndex(combo.findData("hold_to_command"))
    rig.button("map_smile").click()
    spec = rig.performed[-1]
    assert isinstance(spec.config[0], ConfigTableArray)
    assert spec.config[0].entries == ((("gesture", "smile"), ("intent", "hold_to_command")),)

    rig = _Rig(qapp, _inputs(face_on=True, safety_cfg=False, hp_on=False))
    combo = rig.panel._map_widgets["smile"][1]
    combo.setCurrentIndex(combo.findData("pause_pointer"))  # programmatic: a disabled item
    rig.button("map_smile").click()
    assert rig.performed == []
    assert rig.panel._result.text().startswith("Not saved:")


def test_the_saved_mapping_is_shown_without_overwriting_a_combo_being_edited(qapp):
    rig = _Rig(qapp, _inputs(face_on=True))
    jaw = rig.panel._map_widgets["jaw_open"][1]
    assert jaw.currentData() == "hold_to_talk"
    smile = rig.panel._map_widgets["smile"][1]
    assert smile.currentData() == "none"


# ---------------------------------------------------------------------- the camera is never opened


@pytest.mark.parametrize("module", ["handsfree/panel.py", "handsfree/panel_io.py",
                                    "settingsui/handsfree_panel.py"])
def test_the_panel_modules_import_no_camera_stack_and_open_no_capture(module):
    path = SRC / module
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = {node.module.split(".")[0]}
        else:
            continue
        assert not names & {"cv2", "mediapipe", "sounddevice"}, (module, names)
    assert "VideoCapture" not in path.read_text(encoding="utf-8")


def test_the_settings_window_has_a_large_labelled_entry_point_and_stages_through_it(qapp, monkeypatch):
    from yazses.config import Config
    from yazses.settingsui import handsfree_panel as hp_module
    from yazses.settingsui.app import SettingsWindow
    from yazses.settingsui.controller import SettingsController
    from yazses.settingsui.model import build_settings_model

    captured = {}

    class _Stub:
        def __init__(self, gather, perform, **kw):
            captured.update(kw, gather=gather, perform=perform)

        def show(self):
            captured["shown"] = True

    monkeypatch.setattr(hp_module, "HandsFreePanel", _Stub)
    writes = []
    controller = SettingsController(
        Config, lambda s, k, v, q: writes.append((s, k, v)), lambda modules: []
    )
    win = SettingsWindow(build_settings_model(Config()), controller)
    button = win._handsfree_button
    assert button.minimumHeight() >= MIN_TARGET_PX
    assert "camera" in button.accessibleDescription()
    button.click()
    assert captured.get("shown") is True
    # the panel's feature button goes through the window's own staged-toggle path
    captured["toggle_feature"]("gaze", False)  # unchanged -> stages nothing
    assert win._staged_snapshot == {}
    win._confirm_experimental = lambda row: True  # type: ignore[method-assign]
    captured["toggle_feature"]("headpointer", True)
    assert win._staged_snapshot == {"headpointer": True}
    assert writes == [], "staging writes nothing until Apply"


def test_mapping_combos_grow_to_their_longest_choice(qapp):
    """The items arrive after the first gather, so a box sized on first show was empty and cut
    every choice to "Not map..." -- seen in a real render of 2.43.0."""
    rig = _Rig(qapp, _inputs(face_on=True))
    for gesture, (_name, combo, _set) in rig.panel._map_widgets.items():
        assert combo.sizeAdjustPolicy() == QComboBox.SizeAdjustPolicy.AdjustToContents, gesture
        widest = max(combo.fontMetrics().horizontalAdvance(combo.itemText(i))
                     for i in range(combo.count()))
        assert combo.sizeHint().width() > widest, gesture


def test_saving_eyes_closed_says_the_hold_was_raised(qapp):
    rig = _Rig(qapp, _inputs(face_on=True))
    combo = rig.panel._map_widgets["eyes_closed"][1]
    combo.setCurrentIndex(combo.findData("hold_to_talk"))
    rig.button("map_eyes_closed").click()
    assert any(getattr(c, "key", "") == "min_hold_frames" for c in rig.performed[-1].config)
    assert "blink" in rig.panel._result.text()


def test_a_saved_mapping_says_saved_once(qapp):
    rig = _Rig(qapp, _inputs(face_on=True))
    rig.result = ActionResult(True, "Saved. It applies after `yazses restart`.")
    combo = rig.panel._map_widgets["smile"][1]
    combo.setCurrentIndex(combo.findData("hold_to_command"))
    rig.button("map_smile").click()
    assert rig.panel._result.text() == "Saved. It applies after `yazses restart`."
