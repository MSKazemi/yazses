"""``yazses-settings`` entry point — the settings window process.

Thin Qt shell around :mod:`yazses.settingsui.model` and
:mod:`yazses.settingsui.controller`: builds one group per feature category with a
checkbox per row, stages checkbox changes in memory, and writes them all when
Apply is clicked — mirroring `yazses features enable/disable`. Experimental
features are confirmed the moment you check them, before anything is staged.

Every row explains itself three ways, because one way always excludes someone:
a one-line summary that is always visible, a hover tooltip with the full card,
and a "?" button that opens the same card in a dialog — reachable by keyboard,
by touch, and by a screen reader, none of which can hover. The wording is
:mod:`yazses.settingsui.help`, rendered from the same registry entries
`yazses features info` prints.

**Restore defaults** stages, it does not write: it moves every switch back to
its shipped state and leaves them staged, so the change is visible and
cancellable before Apply commits it — and so a misclick costs nothing.

All the bookkeeping (what is staged, what was confirmed, what landed) lives in
the pure :class:`~yazses.settingsui.controller.PendingChanges` /
:class:`~yazses.settingsui.controller.SettingsController` pair, so this file only
translates between those and widgets — and reports every outcome, including the
ones that failed.
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Any

from yazses.settingsui.controller import (
    ApplyReport,
    PendingChanges,
    SettingsController,
    defaults_diff,
)
from yazses.settingsui.help import (
    accessible_description,
    help_html,
    reset_message,
    summary_line,
)
from yazses.settingsui.launch import has_display, pyside_available
from yazses.settingsui.model import SettingRow, SettingsModel, build_settings_model
from yazses.settingsui.search import describe_filter, matches, visible_counts
from yazses.settingsui.theme import muted_style_for

log = logging.getLogger(__name__)

# Both fallbacks name the *whole* terminal equivalent, `reset` included: a
# machine that cannot run Qt (an old distribution, a headless box) is exactly the
# one that must not be left without a way to undo a setting.
_TERMINAL_EQUIVALENT = (
    "    yazses features                     list every capability and its state\n"
    "    yazses features info <name>         what one does, when to use it, an example\n"
    "    yazses features enable <name>       turn one on\n"
    "    yazses features disable <name>      turn one off\n"
    "    yazses features reset               restore every capability to its default"
)
_MISSING_PYSIDE_MSG = (
    "The settings window needs PySide6. Install it with:\n"
    "    uv sync --extra overlay      # or: pip install 'yazses[overlay]'\n"
    "Every setting is also available from the terminal:\n" + _TERMINAL_EQUIVALENT
)
_NO_DISPLAY_MSG = (
    "The settings window needs a graphical session — no DISPLAY or WAYLAND_DISPLAY\n"
    "is set, so there is nothing to open it on (an SSH session without X forwarding,\n"
    "or a headless machine).\n"
    "Use the terminal instead:\n" + _TERMINAL_EQUIVALENT
)


def run() -> None:
    """Entry point — the `yazses-settings` GUI script / `yazses settings`."""
    # No console on Windows for a GUI script: sys.stderr is None, which would
    # take down both basicConfig and the print() diagnostics below.
    from yazses.system.wincon import ensure_streams

    ensure_streams()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not pyside_available():
        print(_MISSING_PYSIDE_MSG, file=sys.stderr)
        sys.exit(1)
    if not has_display(os.environ):
        print(_NO_DISPLAY_MSG, file=sys.stderr)
        sys.exit(1)

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:  # installed but unusable (missing Qt libs on old distros)
        print(f"{_MISSING_PYSIDE_MSG}\n\nImport failed: {exc}", file=sys.stderr)
        sys.exit(1)

    from yazses.config import Config, load_config
    from yazses.platform import get_platform
    from yazses.system.configedit import set_config_key

    platform = get_platform()
    config_file = platform.paths.config_file

    def _load() -> Config:
        return load_config(config_file)

    def _write(section: str, key: str, value: object, quote: bool | None) -> None:
        set_config_key(config_file, section, key, value, quote=quote)

    controller = SettingsController(_load, _write)

    app = QApplication.instance() or QApplication(sys.argv)
    window = SettingsWindow(build_settings_model(_load()), controller)
    window.show()
    sys.exit(app.exec())


def _rich_text():
    """``Qt.TextFormat.RichText``, imported at call time like the rest of Qt here."""
    from PySide6.QtCore import Qt

    return Qt.TextFormat.RichText


class SettingsWindow:
    """The settings window itself. Only imports Qt when instantiated."""

    def __init__(self, model: SettingsModel, controller: SettingsController) -> None:
        from PySide6.QtWidgets import (
            QCheckBox,
            QGroupBox,
            QLabel,
            QMainWindow,
            QPushButton,
            QScrollArea,
            QVBoxLayout,
            QWidget,
        )

        self._controller = controller
        self._model = model
        self._checkboxes: dict[str, QCheckBox] = {}
        # Typed Any for the same reason as the QThread refs below: PySide6 ships
        # no stubs in this tree.
        self._info_buttons: dict[str, Any] = {}
        self._rows: dict[str, SettingRow] = {
            row.slug: row for group in model.groups for row in group.rows
        }
        self._defaults = dict(model.defaults)
        self._pending = PendingChanges(
            {slug: row.enabled for slug, row in self._rows.items()}
        )

        self._win = QMainWindow()
        self._win.setWindowTitle("YazSes Settings")
        self._win.resize(680, 760)

        central = QWidget()
        outer = QVBoxLayout(central)

        # Tooltips are invisible until you already suspect they exist, so say so
        # once at the top rather than hoping every user discovers hovering.
        intro = QLabel(
            "Hover any capability for the full description, or click ? for its "
            "details, examples and the exact config keys it writes."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(muted_style_for(intro))
        outer.addWidget(intro)

        outer.addLayout(self._build_hotkey_row(model.hotkey))
        outer.addWidget(self._build_audio_rows(model))
        outer.addLayout(self._build_filter_box())

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body_layout = QVBoxLayout(body)

        # (group_box, category, [(slug, row_widget), ...]) — everything the filter
        # needs to hide a row and, when a whole category empties, its heading too.
        self._group_widgets: list[tuple[Any, str, list[tuple[str, Any]]]] = []
        for group in model.groups:
            box = QGroupBox(group.category)
            box_layout = QVBoxLayout(box)
            if group.blurb:
                blurb = QLabel(group.blurb)
                blurb.setWordWrap(True)
                blurb.setStyleSheet(muted_style_for(blurb))
                box_layout.addWidget(blurb)
            members: list[tuple[str, Any]] = []
            for row in group.rows:
                # A QWidget per row, not a bare layout: Qt can hide a widget, and
                # there is no equivalent for a layout short of walking its items.
                holder = QWidget()
                holder.setLayout(self._build_row(row))
                box_layout.addWidget(holder)
                members.append((row.slug, holder))
            self._group_widgets.append((box, group.category, members))
            body_layout.addWidget(box)
        body_layout.addStretch(1)

        scroll.setWidget(body)
        outer.addWidget(scroll)

        self._hint = QLabel("")
        self._hint.setWordWrap(True)
        self._hint.setStyleSheet(muted_style_for(self._hint))
        outer.addWidget(self._hint)

        from PySide6.QtWidgets import QHBoxLayout

        buttons = QHBoxLayout()
        reset_btn = QPushButton("Restore defaults")
        reset_btn.setToolTip(
            "Move every capability back to the state a fresh install ships with. "
            "Staged only — nothing is written until you click Apply."
        )
        self._reset_button = reset_btn
        reset_btn.clicked.connect(self._on_restore_defaults)
        buttons.addWidget(reset_btn)
        buttons.addStretch(1)

        apply_btn = QPushButton("Apply")
        # Enter applies; the destructive-ish button never gets that for free.
        apply_btn.setDefault(True)
        self._apply_button = apply_btn
        # Dependency-install state (#135). `_auto_install` mirrors the CLI's
        # --no-install; the thread/worker refs keep Qt from collecting a
        # running QThread out from under the install.
        self._auto_install = True
        # Typed as Any: PySide6 has no stubs in this tree (mypy already ignores
        # its imports repo-wide), so a precise QThread annotation would be an
        # error rather than documentation.
        self._restart_pending = False
        self._install_thread: Any = None
        self._install_worker: Any = None
        apply_btn.clicked.connect(self._on_apply)
        buttons.addWidget(apply_btn)
        outer.addLayout(buttons)

        self._win.setCentralWidget(central)

    def _build_hotkey_row(self, current: str):
        """The hold-to-talk key picker — the one setting everybody changes.

        Above the filter box because it is not a capability and filtering it away
        would be surprising: someone typing "hotkey" into a *feature* filter should
        not make the hotkey control vanish.

        A dropdown rather than a "press a key" capture: the platforms bind eleven
        specific keys, and a capture box would happily accept F13 and then leave
        the user unable to dictate. `SUPPORTED_HOTKEYS` is the same list
        `yazses hotkey set` offers, so the two surfaces cannot disagree.
        """
        from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel

        from yazses.hotkeys.names import SETTABLE_HOTKEYS

        line = QHBoxLayout()
        label = QLabel("Hold-to-talk key:")
        line.addWidget(label)

        box = QComboBox()
        box.addItems(SETTABLE_HOTKEYS)
        if current in SETTABLE_HOTKEYS:
            box.setCurrentIndex(SETTABLE_HOTKEYS.index(current))
        elif current:
            # A hand-edited config can hold something not offered. Show it rather
            # than silently selecting a different key the user never chose.
            box.insertItem(0, current)
            box.setCurrentIndex(0)
        box.setAccessibleName("Hold-to-talk key")
        box.setToolTip(
            "The key you hold down to dictate. Same list as `yazses hotkey set`.\n"
            "auto = let YazSes pick the usual key for this operating system.\n"
            "right_option / left_option are the macOS names for the alt keys.\n"
            "Applied when you click Apply, and it takes effect after the restart."
        )
        self._hotkey_box = box
        self._hotkey_baseline = current
        line.addWidget(box, 1)
        return line

    def _build_audio_rows(self, model: SettingsModel):
        """Microphone and silence threshold — the other two value settings.

        Device enumeration is injected and wrapped: it opens PortAudio, which on a
        machine with no sound card, a busy ALSA device or a container raises. The
        settings window must still open there — every *other* setting is still
        editable, and a window that refuses to appear because a microphone is
        missing is a worse failure than a dropdown with one entry in it.
        """
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QComboBox,
            QFormLayout,
            QGroupBox,
            QLabel,
            QSlider,
            QVBoxLayout,
        )

        from yazses.settingsui.controls import (
            VAD_SLIDER_STEPS,
            mic_choices,
            slider_to_threshold,
            threshold_to_slider,
        )

        box = QGroupBox("Audio")
        form = QFormLayout(box)

        devices, default_name = self._probe_devices()
        choices = mic_choices(devices, default_name=default_name, pinned=model.microphone)
        mic = QComboBox()
        for choice in choices:
            mic.addItem(choice.label, choice.value)
        # Select by *value*, not by label: the label carries ● and ★ markers that
        # change with the machine, and matching on it would silently reset the pin.
        for index, choice in enumerate(choices):
            if choice.value == model.microphone:
                mic.setCurrentIndex(index)
                break
        mic.setAccessibleName("Microphone")
        mic.setToolTip(
            "Which microphone to record from. ● is the current system default, "
            "★ is the one pinned here.\n"
            "Pin one only if a device keeps stealing capture — following the "
            "system default is the right state for most people.\n"
            "Same list as `yazses audio devices`."
        )
        self._mic_box = mic
        self._mic_baseline = model.microphone
        form.addRow(QLabel("Microphone:"), mic)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, VAD_SLIDER_STEPS)
        slider.setValue(threshold_to_slider(model.vad_threshold))
        slider.setAccessibleName("Silence threshold")
        slider.setToolTip(
            "Audio quieter than this is discarded as silence — the number behind "
            "'Silent audio -- discarding'.\n"
            "Move it left if your speech is being dropped, right if a noisy room "
            "triggers stray transcripts.\n"
            "`yazses mic-level --set` measures a value for you instead of guessing."
        )
        self._vad_slider = slider
        # The *position*, not the float. threshold_to_slider quantises to 1000
        # integer steps, so round-tripping 0.01 yields 0.01001 — comparing floats
        # made an untouched slider look moved and rewrote the key on every Apply.
        self._vad_baseline_pos = threshold_to_slider(model.vad_threshold)

        readout = QLabel(f"{model.vad_threshold:.4g}")
        readout.setStyleSheet(muted_style_for(readout))
        self._vad_readout = readout
        slider.valueChanged.connect(
            lambda pos: readout.setText(f"{slider_to_threshold(pos):.4g}")
        )

        # The live meter. A slider without one is a user guessing at a float; with
        # one they can *see* their voice sitting under the line, which is the
        # question behind every "Silent audio -- discarding" report.
        #
        # Fed from the daemon's status reply rather than by opening the microphone
        # here: the daemon already publishes `audio_level`, it is the process that
        # owns the device, and a second capture stream in this window would fight
        # the one dictation uses.
        from PySide6.QtWidgets import QProgressBar

        meter = QProgressBar()
        meter.setRange(0, 100)
        meter.setTextVisible(False)
        meter.setAccessibleName("Microphone level")
        self._meter = meter
        self._meter_label = QLabel("")
        self._meter_label.setStyleSheet(muted_style_for(self._meter_label))
        self._latest_level: float | None = None

        # Re-judge on drag: tuning against the *saved* threshold would leave you
        # unable to tell when you had moved it far enough.
        slider.valueChanged.connect(lambda _pos: self._refresh_meter())

        wrap = QVBoxLayout()
        wrap.addWidget(slider)
        wrap.addWidget(readout)
        wrap.addWidget(meter)
        wrap.addWidget(self._meter_label)
        form.addRow(QLabel("Silence threshold:"), wrap)
        self._start_level_polling()
        return box

    def _start_level_polling(self) -> None:
        """Poll the daemon for the live input level, on a Qt timer.

        Never raises into the window: no daemon is the ordinary case (the settings
        window opens fine without one), and an unreachable socket must leave the
        meter saying so rather than taking the dialog down.
        """
        from PySide6.QtCore import QTimer

        def _tick() -> None:
            try:
                from yazses.platform import get_platform

                platform = get_platform()
                client = platform.ipc_client_factory(platform.paths.ipc_socket)
                self._apply_level(client.call("status"))
            except Exception:
                self._apply_level(None)

        self._level_timer = QTimer(self._win)
        self._level_timer.timeout.connect(_tick)
        # 150 ms while the window is open — the same cadence the tray uses while
        # recording, fast enough that the bar tracks a syllable.
        self._level_timer.start(150)

    def _apply_level(self, status: dict | None) -> None:
        """Update the meter from one status reply, or from nothing."""
        if status is None:
            self._latest_level = None
            self._recording = False
        else:
            try:
                self._latest_level = float(status.get("audio_level") or 0.0)
            except (TypeError, ValueError):
                self._latest_level = None
            # The daemon only updates `audio_level` while a hold is in progress —
            # idle it reports 0.0. Without this distinction the meter would say
            # "below the line" whenever you were not speaking, which is a claim
            # about your microphone rather than about the fact that nothing is
            # listening. Caught by running it against the live daemon.
            self._recording = str(status.get("state") or "").lower() == "recording"
        self._refresh_meter()

    def _refresh_meter(self) -> None:
        from yazses.settingsui.controls import meter_reading, slider_to_threshold

        meter = getattr(self, "_meter", None)
        if meter is None:  # pragma: no cover - built together with the slider
            return
        if self._latest_level is None:
            meter.setValue(0)
            # Deliberately not "silent": that would be a claim about the
            # microphone, and with no daemon we do not have one.
            self._meter_label.setText("YazSes is not running, so there is no level to show.")
            return

        if not getattr(self, "_recording", False):
            meter.setValue(0)
            self._meter_label.setText(
                "Hold your dictation key and speak — the bar shows whether you clear the line."
            )
            return

        threshold = slider_to_threshold(self._vad_slider.value())
        position, above = meter_reading(self._latest_level, threshold)
        meter.setValue(position)
        self._meter_label.setText(
            "Your voice is above the line — this would be transcribed."
            if above
            else "Below the line — audio this quiet is discarded as silence."
        )

    def _probe_devices(self):
        """(devices, default_name), or ([], None) when audio cannot be opened."""
        try:
            from yazses.audio.devices import current_default_input_name, list_input_devices

            return list_input_devices(), current_default_input_name()
        except Exception:  # noqa: BLE001 - a missing sound card must not block the window
            log.debug("could not enumerate input devices for the settings window", exc_info=True)
            return [], None

    def _build_filter_box(self):
        """The filter box. Mirrors `yazses features --on/--tier/--category`.

        Two hundred rows in one scroll means the only way to reach a capability
        was to pass every other one — and a row you never reach cannot explain
        itself, however good its help text is.
        """
        from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout

        wrap = QVBoxLayout()
        line = QHBoxLayout()
        line.addWidget(QLabel("Filter:"))

        box = QLineEdit()
        box.setPlaceholderText("name, category, or what it does — e.g. stutter, tier:rec, on:")
        box.setClearButtonEnabled(True)
        box.setToolTip(
            "Matches the name, the toggle name, the category and the description,"
            " so 'stutter' finds Dysfluency-Friendly.\n"
            "on: / off: — only what is currently enabled or disabled\n"
            "tier:core|on|rec|opt|exp — only one recommendation tier"
        )
        box.setAccessibleName("Filter capabilities")
        box.textChanged.connect(self._on_filter_changed)
        self._filter_box = box
        line.addWidget(box, 1)
        wrap.addLayout(line)

        self._filter_status = QLabel("")
        self._filter_status.setWordWrap(True)
        self._filter_status.setStyleSheet(muted_style_for(self._filter_status))
        wrap.addWidget(self._filter_status)
        return wrap

    def _on_filter_changed(self, query: str) -> None:
        """Hide what does not match — and any category left with nothing in it.

        Only visibility changes. A hidden row keeps its staged state, so filtering
        mid-edit can never quietly discard a change or exclude one from Apply.
        """
        for box, category, members in self._group_widgets:
            visible = 0
            for slug, holder in members:
                shown = matches(self._rows[slug], query, category=category)
                holder.setVisible(shown)
                visible += int(shown)
            box.setVisible(visible > 0)
        matching, total = visible_counts(self._model.groups, query)
        self._filter_status.setText(describe_filter(matching, total, query))

    def _build_row(self, row: SettingRow):
        from PySide6.QtWidgets import (
            QCheckBox,
            QHBoxLayout,
            QLabel,
            QToolButton,
            QVBoxLayout,
        )

        card = help_html(row)
        spoken = accessible_description(row)

        line = QVBoxLayout()
        top = QHBoxLayout()
        cb = QCheckBox(row.label)
        cb.setChecked(row.enabled)
        cb.setEnabled(row.toggleable)
        cb.setToolTip(card)
        # A disabled QCheckBox does not show its tooltip on every platform, and a
        # greyed row is exactly the one people need explained ("why can't I turn
        # this on?"). The description is on the row's ? button either way.
        cb.setAccessibleDescription(spoken)
        cb.toggled.connect(lambda checked, r=row: self._on_toggled(r, checked))
        self._checkboxes[row.slug] = cb
        top.addWidget(cb)
        top.addStretch(1)

        info = QToolButton()
        info.setText("?")
        info.setAutoRaise(True)
        info.setToolTip(card)
        info.setAccessibleName(f"Details about {row.label}")
        info.setAccessibleDescription(spoken)
        info.clicked.connect(lambda _checked=False, r=row: self._show_details(r))
        self._info_buttons[row.slug] = info
        top.addWidget(info)
        line.addLayout(top)

        subtitle = QLabel(summary_line(row))
        subtitle.setWordWrap(True)
        subtitle.setToolTip(card)
        subtitle.setStyleSheet(muted_style_for(subtitle, "margin-left: 24px;"))
        line.addWidget(subtitle)
        return line

    def _show_details(self, row: SettingRow) -> None:
        """The same card the tooltip shows, in a dialog you can reach and read.

        Not a tooltip: hover is unreachable by keyboard, unavailable on touch,
        and never announced by a screen reader — and it disappears while you are
        still reading it.
        """
        from PySide6.QtWidgets import QMessageBox

        box = QMessageBox(self._win)
        box.setWindowTitle(row.label)
        box.setTextFormat(_rich_text())
        box.setText(help_html(row))
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    def _on_toggled(self, row: SettingRow, checked: bool) -> None:
        if not row.toggleable:
            return
        if checked and row.experimental and not self._pending.is_confirmed(row.slug):
            if not self._confirm_experimental(row):
                # Declined: put the box back without staging anything.
                self._set_checked_silently(row.slug, self._pending.baseline(row.slug))
                return
            self._pending.confirm(row.slug)
        self._pending.stage(row.slug, checked)
        self._show_staged()

    def _set_checked_silently(self, slug: str, checked: bool) -> None:
        """Move a checkbox without re-entering :meth:`_on_toggled`."""
        cb = self._checkboxes[slug]
        cb.blockSignals(True)
        cb.setChecked(checked)
        cb.blockSignals(False)

    def _show_staged(self) -> None:
        count = len(self._pending)
        self._hint.setText(
            f"{count} change(s) staged — click Apply, then restart the daemon."
            if count else ""
        )

    def _on_restore_defaults(self) -> None:
        """Move every switch back to its shipped state — staged, not written.

        Restricted to rows that are actually toggleable here, so a reset can
        never stage a greyed-out row and hand the user an Apply failure they
        cannot act on.
        """
        diff = defaults_diff(
            self._defaults,
            self._pending,
            toggleable=[slug for slug, row in self._rows.items() if row.toggleable],
        )
        labels = {slug: row.label for slug, row in self._rows.items()}
        if not diff:
            self._hint.setText(reset_message(diff, labels))
            return
        if not self._confirm_reset(diff, labels):
            return

        for slug, desired in diff:
            self._pending.stage(slug, desired)
            self._set_checked_silently(slug, desired)
        # Defaults never include an experimental capability (they are, by
        # definition, not advised), so a reset only ever turns those off and no
        # confirmation is spent here. `PendingChanges.stage` drops rows that are
        # already at their baseline, so a reset stages only genuine changes.
        self._show_staged()

    def _confirm_reset(self, diff, labels) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self._win,
            "Restore default settings?",
            f"{len(diff)} capabilit{'y' if len(diff) == 1 else 'ies'} will go back "
            f"to the state a fresh install ships with.\n\n"
            + reset_message(diff, labels),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _confirm_experimental(self, row: SettingRow) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.warning(
            self._win,
            "Experimental feature",
            f"{row.label} is experimental — {row.why}\n\nEnable it anyway?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _on_apply(self) -> None:
        report = self._controller.apply(self._pending)
        hotkey_changed, hotkey_error = self._apply_hotkey()
        audio_changed, audio_errors = self._apply_audio()

        # Re-sync every checkbox with what actually landed: a row that failed
        # keeps its staged position (so Apply can be retried) but must not be
        # left claiming a state the config file does not have.
        still_staged = {slug for slug, _ in self._pending.items()}
        for slug in self._checkboxes:
            if slug not in still_staged:
                self._set_checked_silently(slug, self._pending.baseline(slug))

        summary = self._summarise(report)
        if hotkey_changed:
            summary = f"Hold-to-talk key set to {self._hotkey_baseline}. {summary}".strip()
        self._hint.setText(summary)

        errors = [*report.errors, *([hotkey_error] if hotkey_error else []), *audio_errors]
        if errors:
            self._warn("Some settings were not saved", "\n".join(errors))

        # Install the optional packages the newly-enabled capabilities need (#135).
        # Off the UI thread: a `mediapipe` or `speechbrain` install takes minutes,
        # and on the main thread that is indistinguishable from a hang.
        self._install_missing(report.missing_packages)

        # Then close the loop: config is read at startup, so until the daemon is
        # restarted the window is showing settings that are not in effect (#61).
        # The hotkey counts: a changed key that has not been rebound is the most
        # confusing of all — the old key stops being advertised and the new one
        # does nothing yet.
        if report.applied or hotkey_changed or audio_changed:
            self._offer_restart(summary)

    def _apply_audio(self) -> tuple[bool, list[str]]:
        """Save the microphone and threshold if they moved. Returns (changed, errors).

        Each is written independently: a failing microphone write must not discard
        a threshold the user also just set.
        """
        changed = False
        errors: list[str] = []

        mic = getattr(self, "_mic_box", None)
        if mic is not None:
            chosen = mic.currentData()
            if chosen is not None and chosen != self._mic_baseline:
                result = self._controller.set_microphone(chosen)
                if result.ok:
                    self._mic_baseline = chosen
                    changed = True
                else:
                    errors.append(result.error or "Could not save the microphone.")

        slider = getattr(self, "_vad_slider", None)
        if slider is not None:
            from yazses.settingsui.controls import slider_to_threshold

            position = slider.value()
            if position != self._vad_baseline_pos:
                result = self._controller.set_vad_threshold(slider_to_threshold(position))
                if result.ok:
                    self._vad_baseline_pos = position
                    changed = True
                else:
                    errors.append(result.error or "Could not save the threshold.")

        return changed, errors

    def _apply_hotkey(self) -> tuple[bool, str | None]:
        """Save the picked hotkey if it moved. Returns (changed, error).

        Separate from the feature apply because it is not a feature: it has its
        own validation, its own failure message, and it must not be silently
        rolled into a report about capability rows.
        """
        box = getattr(self, "_hotkey_box", None)
        if box is None:  # pragma: no cover - the row is always built
            return False, None
        chosen = box.currentText().strip()
        if not chosen or chosen == self._hotkey_baseline:
            return False, None

        result = self._controller.set_hotkey(chosen)
        if not result.ok:
            # Put the box back on the value that is actually in the config, so the
            # window never shows a key it failed to save as though it were set.
            self._restore_hotkey_box()
            return False, result.error or f"Could not set the hotkey to {chosen!r}."
        self._hotkey_baseline = chosen
        return True, None

    def _restore_hotkey_box(self) -> None:
        box = getattr(self, "_hotkey_box", None)
        if box is None:  # pragma: no cover
            return
        index = box.findText(self._hotkey_baseline)
        if index >= 0:
            box.blockSignals(True)
            box.setCurrentIndex(index)
            box.blockSignals(False)

    def _offer_restart(self, summary: str = "") -> None:
        """Ask, restart, and report what the daemon actually says afterwards.

        The decision logic is `settingsui/restart.py`; this method only supplies
        the dialog and the IPC/subprocess effects, so the honest-state rules are
        unit-tested without Qt.

        The restart outcome is *appended* to Apply's summary rather than
        replacing it: on a partly-failed Apply the summary is the only place the
        window says some rows are still staged, and overwriting it left a
        half-applied change looking like a clean save.
        """
        from yazses.settingsui.restart import apply_and_restart

        outcome = apply_and_restart(
            is_running=self._daemon_running,
            confirm=self._confirm_restart,
            restart=self._run_restart,
            status=self._daemon_status,
        )
        self._hint.setText("  ".join(part for part in (summary, outcome.message) if part))
        self._restart_pending = outcome.needs_restart_hint

    def _confirm_restart(self) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self._win,
            "Restart YazSes now?",
            "Your changes are saved. YazSes reads its configuration at startup, so "
            "they take effect after a restart.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _daemon_running(self) -> bool:
        try:
            from yazses.platform import get_platform

            return bool(get_platform().lifecycle.is_running())
        except Exception:
            logging.getLogger(__name__).debug("daemon check failed", exc_info=True)
            return False

    def _daemon_status(self):
        try:
            from yazses.platform import get_platform

            platform = get_platform()
            return platform.ipc_client_factory(platform.paths.ipc_socket).call("status")
        except Exception:
            return None

    @staticmethod
    def _run_restart() -> tuple[bool, str]:
        """The same path as `yazses restart`, as a subprocess.

        Shelling out rather than importing the CLI keeps the window out of the
        daemon's lifecycle: `restart` stops every daemon including detached ones,
        and doing that in-process from a GUI is how you end up killing yourself.
        """
        import subprocess
        import sys

        try:
            result = subprocess.run(
                [sys.executable, "-m", "yazses.cli", "restart"],
                capture_output=True, text=True, timeout=90,
            )
        except Exception as exc:  # noqa: BLE001 - reported to the user
            return False, str(exc)
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "").strip()[:200]
        return True, ""

    def _install_missing(self, missing_by_slug) -> None:
        """Start the dependency install for whatever Apply just enabled.

        Decisions live in `settingsui/deps.py`; this method owns only the thread
        and the widgets, which is the split the rest of `settingsui/` uses.
        """
        from yazses.settingsui.deps import describe_skipped, plan_installs

        if not missing_by_slug:
            return
        if not self._auto_install:
            self._hint.setText(describe_skipped(missing_by_slug))
            return
        plans = plan_installs(missing_by_slug, auto_install=True)
        if not plans:
            return
        if self._install_thread is not None:
            # An install is already running; the button is disabled, but a queued
            # signal could still land here.
            return
        self._start_install_worker(plans)

    def _start_install_worker(self, plans) -> None:
        from PySide6.QtCore import QThread

        from yazses.settingsui.worker import InstallWorker

        self._apply_button.setEnabled(False)
        self._hint.setText(
            f"Installing packages for {', '.join(p.slug for p in plans)}… "
            "this can take a few minutes."
        )

        thread = QThread(self._win)
        worker = InstallWorker(plans)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.progress.connect(self._on_install_progress)
        worker.finished.connect(self._on_install_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        # Keep strong references: a QThread garbage-collected mid-run takes the
        # install with it and Qt warns about a destroyed running thread.
        self._install_thread, self._install_worker = thread, worker
        thread.start()

    def _on_install_progress(self, line: str) -> None:
        self._hint.setText(line)

    def _on_install_finished(self, summary) -> None:
        from yazses.settingsui.deps import describe_summary

        self._install_thread = self._install_worker = None
        self._apply_button.setEnabled(True)
        message = describe_summary(summary)
        if message:
            self._hint.setText(message)
        if summary.failed:
            # The config key stands on a failed install (see settingsui/deps.py);
            # saying so is the whole point, otherwise the toggle looks inert.
            self._warn(
                "Some packages could not be installed",
                "\n".join(f.slug + ": " + (f.error or "install failed")
                           for f in summary.failed),
            )

    def _summarise(self, report: ApplyReport) -> str:
        parts: list[str] = []
        if report.applied:
            parts.append(
                f"Applied {report.applied} change(s). "
                "Restart the daemon to apply: yazses restart"
            )
        elif not report.errors and not report.unconfirmed:
            parts.append("Nothing to apply.")
        if report.errors:
            parts.append(f"{len(report.errors)} change(s) failed — still staged.")
        if report.unconfirmed:
            parts.append(
                f"{len(report.unconfirmed)} experimental change(s) need confirming."
            )
        for slug, packages in report.missing_packages.items():
            parts.append(
                f"{slug} needs packages that are not installed ({' '.join(packages)}). "
                f"Install them with: yazses features enable {slug}"
            )
        return "  ".join(parts)

    def _warn(self, title: str, body: str) -> None:
        from PySide6.QtWidgets import QMessageBox

        QMessageBox.warning(self._win, title, body, QMessageBox.StandardButton.Ok)

    def show(self) -> None:
        self._win.show()
