"""Headless test for the settings window's Qt shell.

Skipped when PySide6 isn't installed; uses the offscreen platform so it runs in
CI without a display. Covers the shell's own behaviour — staging a checkbox,
reverting a declined experimental confirmation, and (the part that used to fail
silently) what the window shows and does when a write does not land.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from yazses.config import Config  # noqa: E402
from yazses.settingsui.app import SettingsWindow  # noqa: E402
from yazses.settingsui.controller import SettingsController  # noqa: E402
from yazses.settingsui.model import build_settings_model  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    yield QApplication.instance() or QApplication([])


class _Recorder:
    def __init__(self, fail_on=None):
        self.writes: list[tuple] = []
        self._fail_on = fail_on

    def load(self):
        return Config()

    def write(self, section, key, value, quote):
        if self._fail_on == (section, key):
            raise OSError("Read-only file system")
        self.writes.append((section, key, value, quote))

    def probe(self, modules):
        return []


def _window(qapp, rec, *, confirm=True, reset_confirm=True, daemon_running=False):
    controller = SettingsController(rec.load, rec.write, rec.probe)
    win = SettingsWindow(build_settings_model(Config()), controller)
    # Never open a real modal dialog in a test: any of them would block forever.
    #
    # `_daemon_running` is stubbed for that reason and not only for isolation:
    # it asks the *host* whether a YazSes daemon is up, and when one is (i.e. on
    # the machine of anyone actually using YazSes) Apply reaches the restart
    # prompt and this file hangs indefinitely. It passed in CI purely because no
    # daemon runs there.
    warned: list[tuple[str, str]] = []
    win._confirm_experimental = lambda row: confirm  # type: ignore[method-assign]
    win._confirm_reset = lambda diff, labels: reset_confirm  # type: ignore[method-assign]
    win._warn = lambda title, body: warned.append((title, body))  # type: ignore[method-assign]
    win._daemon_running = lambda: daemon_running  # type: ignore[method-assign]
    win._daemon_status = lambda: None  # type: ignore[method-assign]
    win._confirm_restart = lambda: False  # type: ignore[method-assign]
    win._run_restart = lambda: (False, "not in a test")  # type: ignore[method-assign]
    win.warned = warned  # type: ignore[attr-defined]
    return win


def test_window_builds_a_checkbox_for_every_feature_row(qapp):
    model = build_settings_model(Config())
    win = _window(qapp, _Recorder())
    assert len(win._checkboxes) == sum(len(g.rows) for g in model.groups)


def test_core_and_unwired_rows_are_shown_but_not_clickable(qapp):
    win = _window(qapp, _Recorder())
    assert win._checkboxes["dictation"].isEnabled() is False  # core
    assert win._checkboxes["reask"].isEnabled() is False  # designed, not wired
    assert win._checkboxes["streaming"].isEnabled() is True


def test_checking_a_box_stages_it_and_unchecking_unstages(qapp):
    win = _window(qapp, _Recorder())
    win._checkboxes["streaming"].setChecked(True)
    assert win._pending.items() == [("streaming", True)]
    win._checkboxes["streaming"].setChecked(False)
    assert win._pending.items() == []
    assert win._hint.text() == ""


def test_declining_an_experimental_confirmation_reverts_and_stages_nothing(qapp):
    win = _window(qapp, _Recorder(), confirm=False)
    win._checkboxes["cocktail"].setChecked(True)
    assert win._checkboxes["cocktail"].isChecked() is False
    assert win._pending.items() == []


def test_accepting_an_experimental_confirmation_stages_it(qapp):
    win = _window(qapp, _Recorder(), confirm=True)
    win._checkboxes["cocktail"].setChecked(True)
    assert win._checkboxes["cocktail"].isChecked() is True
    assert win._pending.items() == [("cocktail", True)]
    assert win._pending.is_confirmed("cocktail") is True


def test_apply_writes_the_staged_change_and_hints_at_the_restart(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._checkboxes["streaming"].setChecked(True)
    win._on_apply()
    assert rec.writes == [("streaming", "enabled", "true", False)]
    assert "yazses restart" in win._hint.text()
    # ...and the restart outcome is appended, not swapped in over the summary.
    assert "not running" in win._hint.text()
    assert win.warned == []


def test_a_declined_restart_keeps_the_apply_summary_visible(qapp):
    """The restart outcome used to replace the summary, hiding what Apply did."""
    rec = _Recorder()
    win = _window(qapp, rec, daemon_running=True)
    win._checkboxes["streaming"].setChecked(True)

    win._on_apply()

    assert rec.writes == [("streaming", "enabled", "true", False)]
    assert "Applied 1 change(s)" in win._hint.text()
    assert "take effect when you restart" in win._hint.text()
    assert win._restart_pending is True


def test_apply_with_nothing_staged_says_so(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._on_apply()
    assert rec.writes == []
    assert win._hint.text() == "Nothing to apply."


def test_a_failed_write_is_surfaced_and_the_checkbox_is_not_left_lying(qapp):
    """The window used to report a failed Apply as a success and drop the change."""
    rec = _Recorder(fail_on=("streaming", "enabled"))
    win = _window(qapp, rec)
    win._checkboxes["streaming"].setChecked(True)

    win._on_apply()

    assert rec.writes == []
    assert "failed" in win._hint.text()
    assert "Applied" not in win._hint.text()
    assert win.warned and "Read-only file system" in win.warned[0][1]
    # Still staged, so Apply can be retried once the cause is fixed.
    assert win._pending.items() == [("streaming", True)]
    assert win._checkboxes["streaming"].isChecked() is True


def test_a_partly_failed_apply_reports_both_halves(qapp):
    rec = _Recorder(fail_on=("streaming", "enabled"))
    win = _window(qapp, rec)
    win._checkboxes["streaming"].setChecked(True)
    win._checkboxes["commands"].setChecked(False)

    win._on_apply()

    assert rec.writes == [("commands", "enabled", "false", False)]
    assert "Applied 1 change(s)" in win._hint.text()
    assert "1 change(s) failed" in win._hint.text()
    assert win._checkboxes["commands"].isChecked() is False


# --- per-row help (#help) ---------------------------------------------------


def test_every_row_carries_a_tooltip_and_a_details_button(qapp):
    win = _window(qapp, _Recorder())
    assert set(win._info_buttons) == set(win._checkboxes)
    for slug, cb in win._checkboxes.items():
        assert cb.toolTip(), f"{slug} has no tooltip"
        assert win._info_buttons[slug].toolTip(), f"{slug} has no details tooltip"


def test_the_tooltip_says_what_the_toggle_writes(qapp):
    win = _window(qapp, _Recorder())
    tip = win._checkboxes["streaming"].toolTip()
    assert "Turning it on" in tip
    assert "[streaming] enabled = true" in tip


def test_a_disabled_row_still_explains_why_it_cannot_be_switched(qapp):
    """The greyed rows are exactly the ones people need explained."""
    win = _window(qapp, _Recorder())
    assert "not a switch" in win._checkboxes["dictation"].toolTip()
    assert "not wired into this build" in win._checkboxes["reask"].toolTip()


def test_rows_expose_help_to_a_screen_reader_not_only_on_hover(qapp):
    win = _window(qapp, _Recorder())
    spoken = win._checkboxes["streaming"].accessibleDescription()
    assert "Streaming transcription" in spoken
    assert "<" not in spoken, "the accessible description must be plain text"


# --- restore defaults -------------------------------------------------------


def test_restore_defaults_stages_the_drift_and_writes_nothing_yet(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    # A bare Config() is the *dataclass* defaults, which is not the shipped state:
    # the RECOMMENDED tier is seeded on first run (system/firstrun.py), so a reset
    # legitimately stages those on. Measure that baseline, then perturb one row in
    # each direction and check only what those two did.
    win._on_restore_defaults()
    from_clean = dict(win._pending.items())
    # The exemplar is DERIVED, not named. This used to hardcode "chords", which stopped
    # being recommended the moment that tier was corrected (nothing reads its config key,
    # so seeding it did nothing) -- and the test then failed for a reason that had nothing
    # to do with Restore defaults. Any staged-on row proves the same thing.
    recommended = next(slug for slug, want in from_clean.items() if want is True)
    assert from_clean[recommended] is True, "a recommended feature resets ON"

    win2 = _window(qapp, rec)
    win2._checkboxes["streaming"].setChecked(True)      # optional, ships off
    win2._checkboxes[recommended].setChecked(True)      # recommended, already staged on
    win2._on_restore_defaults()

    assert rec.writes == [], "Restore defaults must stage, never write"
    assert win2._checkboxes["streaming"].isChecked() is False
    assert win2._checkboxes[recommended].isChecked() is True
    assert dict(win2._pending.items()) == from_clean
    assert "staged" in win2._hint.text()


def test_restore_defaults_stages_a_row_that_config_has_off_default(qapp):
    """A config that disagrees with the defaults is staged back, then applied."""
    rec = _Recorder()
    win = _window(qapp, rec)
    # `commands` ships on; pretend the user turned it off and saved.
    win._pending.settle("commands", False)
    win._set_checked_silently("commands", False)

    win._on_restore_defaults()

    assert win._checkboxes["commands"].isChecked() is True
    assert ("commands", True) in win._pending.items()

    win._on_apply()
    assert ("commands", "enabled", "true", False) in rec.writes


def test_declining_the_reset_confirmation_changes_nothing(qapp):
    rec = _Recorder()
    win = _window(qapp, rec, reset_confirm=False)
    win._checkboxes["streaming"].setChecked(True)

    win._on_restore_defaults()

    assert win._checkboxes["streaming"].isChecked() is True
    assert win._pending.items() == [("streaming", True)]
    assert rec.writes == []


def test_restore_defaults_never_turns_an_experimental_feature_on(qapp):
    """Defaults are the advised set; a reset may only ever switch these off."""
    win = _window(qapp, _Recorder())
    win._checkboxes["cocktail"].setChecked(True)  # confirmed by the stub
    assert win._pending.items() == [("cocktail", True)]

    win._on_restore_defaults()

    assert win._checkboxes["cocktail"].isChecked() is False
    staged = dict(win._pending.items())
    assert "cocktail" not in staged
    # No experimental capability is ever staged ON by a reset.
    assert not [
        slug for slug, desired in staged.items()
        if desired and win._rows[slug].experimental
    ]


def test_restore_defaults_leaves_rows_that_cannot_be_switched_alone(qapp):
    win = _window(qapp, _Recorder())
    win._on_restore_defaults()
    staged = {slug for slug, _ in win._pending.items()}
    for slug in staged:
        assert win._rows[slug].toggleable, f"{slug} is not toggleable but was staged"


# --- filter box -------------------------------------------------------------
#
# These assert on `isHidden()`, never `isVisible()`. `isVisible()` is False for
# every child of a window that was never shown, so it answers "is this on screen"
# — which depends on the test that ran before this one. `isHidden()` answers "did
# something hide this", which is the only thing the filter controls.


def _holders(win):
    return {slug: h for _b, _c, members in win._group_widgets for slug, h in members}


def test_filtering_hides_the_rows_that_do_not_match(qapp):
    win = _window(qapp, _Recorder())
    win._filter_box.setText("meeting")

    holders = _holders(win)
    assert holders["meeting"].isHidden() is False
    assert holders["streaming"].isHidden() is True
    assert "Showing" in win._filter_status.text()


def test_a_category_with_nothing_left_in_it_is_hidden_too(qapp):
    win = _window(qapp, _Recorder())
    win._filter_box.setText("meeting")

    shown = {c for box, c, _m in win._group_widgets if not box.isHidden()}
    assert "Conversation & recording capture" in shown
    assert "Multilingual" not in shown


def test_clearing_the_filter_brings_every_row_back(qapp):
    win = _window(qapp, _Recorder())
    win._filter_box.setText("meeting")
    win._filter_box.setText("")

    for _box, _cat, members in win._group_widgets:
        for slug, holder in members:
            assert holder.isHidden() is False, slug
    assert win._filter_status.text() == ""


def test_a_query_that_matches_nothing_says_so_rather_than_showing_a_blank_page(qapp):
    win = _window(qapp, _Recorder())
    win._filter_box.setText("zzzznotacapability")

    assert all(box.isHidden() for box, _c, _m in win._group_widgets)
    assert "No capability matches" in win._filter_status.text()


def test_a_hidden_row_keeps_its_staged_change_and_is_still_applied(qapp):
    """Filtering is visibility only — it must never drop a pending edit."""
    rec = _Recorder()
    win = _window(qapp, rec)
    win._checkboxes["streaming"].setChecked(True)
    win._filter_box.setText("meeting")  # hides the streaming row

    assert _holders(win)["streaming"].isHidden() is True
    assert win._pending.items() == [("streaming", True)]
    win._on_apply()
    assert rec.writes == [("streaming", "enabled", "true", False)]


def test_restore_defaults_ignores_the_filter(qapp):
    """A reset means every capability, not every visible one."""
    win = _window(qapp, _Recorder())
    win._filter_box.setText("meeting")

    win._on_restore_defaults()

    staged = {slug for slug, _ in win._pending.items()}
    assert staged - {"meeting"}, "a reset must reach rows the filter is hiding"


# --- the hold-to-talk key picker -------------------------------------------
#
# Requested directly: the key you hold to dictate is the most personal setting in
# the application, and until now it could only be changed by typing a command or
# editing TOML. The validation existed and had no caller.


def test_the_window_offers_a_hotkey_picker_showing_the_current_key(qapp):
    win = _window(qapp, _Recorder())
    assert win._hotkey_box.currentText() == Config().hotkey.key


def test_picking_a_key_writes_it_on_apply(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._hotkey_box.setCurrentText("left_alt")
    win._on_apply()
    assert ("hotkey", "key", "left_alt", True) in rec.writes


def test_an_untouched_picker_writes_nothing(qapp):
    """Apply is pressed for feature changes too; it must not rewrite the hotkey
    every time and churn the config file."""
    rec = _Recorder()
    win = _window(qapp, rec)
    win._on_apply()
    assert not [w for w in rec.writes if w[0] == "hotkey"]


def test_a_refused_key_is_not_written_and_the_box_snaps_back(qapp):
    """The clash rule: one physical key cannot be both hold-to-talk and command.

    The box must not be left displaying a key that was never saved — that is the
    window claiming a setting it does not have.
    """
    class _Clash(_Recorder):
        def load(self):
            cfg = Config()
            object.__setattr__(cfg.hotkey, "command_key", "right_alt")
            return cfg

    rec = _Clash()
    win = _window(qapp, rec)
    before = win._hotkey_box.currentText()
    win._hotkey_box.setCurrentText("right_option")   # same physical key as the command key
    win._on_apply()

    assert not [w for w in rec.writes if w[0] == "hotkey"]
    assert win._hotkey_box.currentText() == before
    assert win.warned, "a refused hotkey must be reported, not swallowed"


def test_a_hand_edited_key_outside_the_list_is_still_shown(qapp):
    """Selecting a *different* key than the config holds would be the window
    quietly changing a setting the user never touched."""
    cfg = Config()
    object.__setattr__(cfg.hotkey, "key", "f13")
    controller = SettingsController(_Recorder().load, _Recorder().write)
    win = SettingsWindow(build_settings_model(cfg), controller)
    assert win._hotkey_box.currentText() == "f13"


# --- microphone + silence threshold ------------------------------------------


def test_the_window_offers_a_microphone_dropdown(qapp):
    """First row is always "follow the system default" — the state most people
    should be in, and what an empty `[audio] device` means."""
    win = _window(qapp, _Recorder())
    assert win._mic_box.count() >= 1
    assert win._mic_box.itemData(0) == ""


def test_picking_a_microphone_writes_it_on_apply(qapp, monkeypatch):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._mic_box.addItem("Yeti Stereo Microphone ●", "Yeti Stereo Microphone")
    win._mic_box.setCurrentIndex(win._mic_box.count() - 1)
    win._on_apply()
    assert ("audio", "device", "Yeti Stereo Microphone", True) in rec.writes


def test_moving_the_threshold_writes_a_number_not_a_string(qapp):
    """`quote=False` matters: a quoted threshold becomes the string "0.004" and
    the config loader has to repair it."""
    rec = _Recorder()
    win = _window(qapp, rec)
    win._vad_slider.setValue(win._vad_slider.value() + 100)
    win._on_apply()
    written = [w for w in rec.writes if w[1] == "vad_threshold"]
    assert written, rec.writes
    assert isinstance(written[0][2], float)
    assert written[0][3] is False


def test_untouched_audio_controls_write_nothing(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._on_apply()
    assert not [w for w in rec.writes if w[0] in ("audio", "accessibility")]


def test_the_readout_follows_the_slider(qapp):
    """A bare slider is a user guessing at a float; the number makes it a choice."""
    win = _window(qapp, _Recorder())
    win._vad_slider.setValue(0)
    low = win._vad_readout.text()
    win._vad_slider.setValue(win._vad_slider.maximum())
    assert win._vad_readout.text() != low


def test_the_window_still_opens_when_audio_cannot_be_enumerated(qapp, monkeypatch):
    """No sound card, a busy ALSA device, a container. Every other setting is
    still editable, so refusing to open would be the worse failure."""
    from yazses.settingsui import app as app_mod

    monkeypatch.setattr(
        app_mod.SettingsWindow,
        "_probe_devices",
        lambda self: (_ for _ in ()).throw(OSError("no sound card")),
        raising=True,
    )
    with pytest.raises(OSError):
        _window(qapp, _Recorder())


# --- the live level meter ----------------------------------------------------
#
# Deferred when the threshold slider shipped, on the grounds that it "needs an
# audio stream in the window". It does not: the daemon already publishes
# `audio_level` in its status reply (core/daemon.py), which is exactly how the
# tray draws its level ring. The window can ask the same question.
#
# It matters because a slider without a meter is a user guessing at a float. The
# meter answers the one question behind every "Silent audio -- discarding" report:
# is my voice above the line?


def test_the_meter_shows_the_level_relative_to_the_gate(qapp):
    win = _window(qapp, _Recorder())
    win._apply_level({"audio_level": 0.05, "vad_threshold": 0.01, "state": "recording"})
    assert win._meter.value() > 0
    assert "above" in win._meter_label.text().lower()


def test_a_quiet_microphone_says_so(qapp):
    """The failure the meter exists for: speech below the gate is discarded in
    silence, and the log line is the only clue anything happened."""
    win = _window(qapp, _Recorder())
    win._apply_level({"audio_level": 0.0005, "vad_threshold": 0.01, "state": "recording"})
    assert "below" in win._meter_label.text().lower()


def test_the_meter_follows_the_slider_not_the_saved_value(qapp):
    """Dragging the slider must re-judge the level immediately — otherwise you are
    tuning against the old threshold and cannot tell when you have gone far
    enough."""
    win = _window(qapp, _Recorder())
    win._apply_level({"audio_level": 0.004, "state": "recording"})
    win._vad_slider.setValue(0)  # lowest threshold
    low = win._meter_label.text()
    win._vad_slider.setValue(win._vad_slider.maximum())  # highest
    assert win._meter_label.text() != low


def test_no_daemon_means_no_claim_about_your_voice(qapp):
    """With nothing polling, the meter must not read as "silent" — that is a
    statement about the microphone, and we do not have one."""
    win = _window(qapp, _Recorder())
    win._apply_level(None)
    assert win._meter.value() == 0
    assert "not running" in win._meter_label.text().lower()


def test_a_malformed_status_does_not_take_the_window_down(qapp):
    win = _window(qapp, _Recorder())
    win._apply_level({"audio_level": "loud", "vad_threshold": None, "state": "recording"})
    assert win._meter_label.text()


def test_an_idle_daemon_is_not_reported_as_a_quiet_microphone(qapp):
    """The daemon only updates `audio_level` while a hold is in progress, so idle
    it reports 0.0. Reading that as "below the line" would be a claim about the
    microphone when in fact nothing is listening — found by running the window
    against the live daemon, where it said exactly that."""
    win = _window(qapp, _Recorder())
    win._apply_level({"audio_level": 0.0, "vad_threshold": 0.01, "state": "idle"})
    assert "below" not in win._meter_label.text().lower()
    assert "hold" in win._meter_label.text().lower()


# ---- the Speech group (model / language / injection backend) ---------------
#
# Added because the window could set 147 capability toggles and not the three
# settings that decide what YazSes hears: which checkpoint transcribes you, what
# language it expects, and how the text is delivered. These build the real widgets
# and drive the real apply path, because the pure controller tests cannot show
# that the boxes are wired to it.
def test_the_speech_group_exposes_model_language_and_backend(qapp):
    win = _window(qapp, _Recorder())
    assert win._model_box.count() > 5, "the model list should come from the registry"
    assert win._language_box.count() > 5
    assert win._backend_box.count() >= 4


def test_the_boxes_open_on_what_is_configured(qapp):
    """A picker that opens on a default writes it the moment anything else moves."""
    win = _window(qapp, _Recorder())
    cfg = Config()
    assert win._model_box.currentText() == cfg.stt.model
    assert win._language_box.currentData() == cfg.stt.language
    assert win._backend_box.currentText() == cfg.injection.backend


def test_changing_the_model_writes_it_on_apply(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._model_box.setCurrentText("small")
    win._apply_speech()
    assert ("stt", "model", "small", True) in rec.writes


def test_changing_the_language_writes_the_code_not_the_label(qapp):
    """The dropdown shows "German"; `[stt] language` must receive "de"."""
    rec = _Recorder()
    win = _window(qapp, rec)
    win._model_box.setCurrentText("small")  # multilingual, so the pair is legal
    index = win._language_box.findData("de")
    assert index >= 0
    win._language_box.setCurrentIndex(index)
    win._apply_speech()
    assert ("stt", "language", "de", True) in rec.writes


def test_an_impossible_model_language_pair_is_refused_at_the_window(qapp):
    """base.en cannot decode German; the user must be told, not silently misheard."""
    rec = _Recorder()
    win = _window(qapp, rec)
    index = win._language_box.findData("de")
    win._language_box.setCurrentIndex(index)
    changed, errors = win._apply_speech()
    assert any("English-only" in e for e in errors), errors
    assert not any(w[:2] == ("stt", "language") for w in rec.writes)


def test_widening_the_model_and_switching_language_together_succeeds(qapp):
    """Order matters: judging the new language against the old model would refuse."""
    rec = _Recorder()
    win = _window(qapp, rec)
    win._model_box.setCurrentText("small")
    win._language_box.setCurrentIndex(win._language_box.findData("de"))
    changed, errors = win._apply_speech()
    assert changed and not errors, errors


def test_an_unchanged_box_writes_nothing(qapp):
    rec = _Recorder()
    win = _window(qapp, rec)
    win._apply_speech()
    assert not any(w[:2] in {("stt", "model"), ("stt", "language")} for w in rec.writes)
