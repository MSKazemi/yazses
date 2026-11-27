"""The first-run setup guide's window: a thin Qt shell over ``first_run.py``.

It adds no daemon call: it reads ``status``, asks for ``recalibrate_mic``, starts or
restarts through the same page context as the Overview page, and saves the key through
the controller's ``set_hotkey``. PySide6 is imported inside functions.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from yazses.hotkeys.names import SETTABLE_HOTKEYS
from yazses.settingsui import first_run, overview
from yazses.settingsui.context import PageContext
from yazses.settingsui.controls import hotkey_note
from yazses.settingsui.widgets import button, compact_combo, label, page_widget, row

log = logging.getLogger(__name__)

_ACTION_WORDS = {"start": "Starting…", "restart": "Restarting…"}


class SetupDialog:
    interval_ms = 150

    def __init__(
        self,
        ctx: PageContext,
        *,
        hotkey: str,
        save_key: Callable[[str], Any],
        platform_default: str = "",
        warning: str = "",
    ) -> None:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import (
            QDialog,
            QFrame,
            QHBoxLayout,
            QPlainTextEdit,
            QProgressBar,
            QScrollArea,
            QStackedWidget,
            QVBoxLayout,
        )

        self._ctx = ctx
        self._saved = hotkey
        self._save_key = save_key
        self._default = platform_default
        self._status: Any = None
        self._mic = first_run.MicCheck()
        self._action = ""
        self._acting = False
        self._failure = ""      # why the last start or restart did not work
        self._open = False
        #: When a recalibration began, and the threshold before it.
        self._recal_started: float | None = None
        self._recal_before: float | None = None
        self.clock: Callable[[], float] = time.monotonic
        self.index = 0

        self.dialog = QDialog(ctx.window)
        self.dialog.setWindowTitle("Set up YazSes")
        self.dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.dialog.resize(640, 520)
        self.dialog.setMinimumSize(520, 420)
        outer = QVBoxLayout(self.dialog)
        outer.setContentsMargins(20, 16, 20, 16)

        self._title = label("", heading=True)
        self._counter = label("", muted=True)
        outer.addWidget(self._title)
        outer.addWidget(self._counter)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack, 1)

        def _page(step: first_run.Step) -> Any:
            body, layout = page_widget()
            layout.addWidget(label(step.text))
            area = QScrollArea()
            area.setWidgetResizable(True)
            area.setFrameShape(QFrame.Shape.NoFrame)
            area.setWidget(body)
            self._stack.addWidget(area)
            return layout

        def _box(name: str, placeholder: str, height: int) -> Any:
            box = QPlainTextEdit()
            box.setAccessibleName(name)
            box.setPlaceholderText(placeholder)
            box.setTabChangesFocus(True)
            box.setMinimumHeight(height)
            return box

        pages = {step.key: _page(step) for step in first_run.STEPS}

        # Microphone. The box also catches the dictated words: typed at a focused button,
        # their spaces would press it.
        mic = pages["microphone"]
        if warning:
            mic.addWidget(label(warning))
        self._mic_daemon = label("Checking…", muted=True)
        self.mic_action = button("", self._act)
        self.mic_action.hide()
        mic.addWidget(self._mic_daemon)
        mic.addLayout(row(self.mic_action))
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setAccessibleName("Input level while recording")
        mic.addWidget(self.level)
        self._mic_verdict = label("")
        mic.addWidget(self._mic_verdict)
        self.heard = _box("What YazSes heard", "What YazSes heard appears here.", 60)
        mic.addWidget(self.heard)
        self.recalibrate_button = button("Recalibrate microphone", self._recalibrate)
        self.recalibrate_button.setEnabled(False)
        self.microphone_button = button("Choose another microphone", self._choose_microphone)
        mic.addLayout(row(self.recalibrate_button, self.microphone_button))
        self._recal_message = label("")
        mic.addWidget(self._recal_message)
        mic.addStretch(1)

        key = pages["key"]
        self.key_box = compact_combo()
        self.key_box.addItems(SETTABLE_HOTKEYS)
        if hotkey and hotkey not in SETTABLE_HOTKEYS:
            self.key_box.insertItem(0, hotkey)
        self.key_box.setCurrentIndex(max(0, self.key_box.findText(hotkey)))
        self.key_box.setAccessibleName("Hold-to-talk key")
        key.addLayout(row(self.key_box))
        self._key_note = label("", muted=True)
        key.addWidget(self._key_note)
        self._key_message = label("")
        key.addWidget(self._key_message)
        key.addStretch(1)

        trial = pages["try"]
        self._try_key = label("")
        self._try_key.setProperty("keycap", "true")
        self._try_key.setWordWrap(False)
        trial.addLayout(row(self._try_key))
        self._try_daemon = label("Checking…", muted=True)
        self.try_action = button("", self._act)
        self.try_action.hide()
        trial.addWidget(self._try_daemon)
        trial.addLayout(row(self.try_action))
        self.practice = _box(
            "Practice dictation box", "Your words appear here when you release the key.", 110
        )
        trial.addWidget(self.practice)
        self._words = label("0 words", muted=True)
        trial.addWidget(self._words)
        trial.addWidget(label(
            "Nothing appears? Run `yazses doctor` in a terminal: it names what is missing.",
            muted=True,
        ))
        trial.addStretch(1)
        self.practice.textChanged.connect(self._counted)

        footer = QHBoxLayout()
        self.skip_button = button("Skip setup", self.dialog.reject)
        self.back_button = button("Back", lambda: self.go(self.index - 1))
        self.next_button = button("Next", self.forward, primary=True)
        # Enter means "go on", never one of these.
        for quiet in (self.skip_button, self.back_button, self.mic_action,
                      self.recalibrate_button, self.microphone_button, self.try_action):
            quiet.setAutoDefault(False)
        self.next_button.setDefault(True)
        footer.addWidget(self.skip_button)
        footer.addStretch(1)
        footer.addWidget(self.back_button)
        footer.addWidget(self.next_button)
        outer.addLayout(footer)

        self.timer = QTimer(self.dialog)
        self.timer.timeout.connect(self.refresh)
        self.key_box.currentTextChanged.connect(self._key_chosen)
        self.dialog.finished.connect(self._closed)

    # --- the frame --------------------------------------------------------------

    @property
    def step(self) -> str:
        return first_run.STEPS[self.index].key

    def is_open(self) -> bool:
        return self._open

    def show(self) -> None:
        self._open = True
        self.dialog.show()
        self.go(0)

    def raise_(self) -> None:
        self.dialog.raise_()
        self.dialog.activateWindow()

    def go(self, index: int) -> None:
        self.index = max(0, min(len(first_run.STEPS) - 1, index))
        step = first_run.STEPS[self.index]
        self._stack.setCurrentIndex(self.index)
        self._title.setText(step.title)
        self._counter.setText(first_run.step_counter(self.index))
        self.back_button.setVisible(self.index > 0)
        self.skip_button.setVisible(not first_run.is_last(self.index))
        self._key_chosen()
        self._paint(self._status)
        if step.key in first_run.LIVE_STEPS:
            self.timer.start(self.interval_ms)
            self.refresh()
        else:
            self.timer.stop()
        self._focus()

    def forward(self) -> None:
        if self.step == "key" and not self._store_key():
            return
        if first_run.is_last(self.index):
            self.dialog.accept()
        else:
            self.go(self.index + 1)

    def _focus(self) -> None:
        target = {"microphone": self.heard, "key": self.key_box, "try": self.practice}.get(
            self.step, self.next_button
        )
        target.setFocus()

    def _closed(self, _result: int = 0) -> None:
        self._open = False
        self.timer.stop()
        self.heard.clear()
        self.practice.clear()

    # --- the key ----------------------------------------------------------------

    def _key_chosen(self, _text: str = "") -> None:
        chosen = self.key_box.currentText()
        self._key_note.setText(hotkey_note(chosen, self._default))
        self._key_message.setText("")
        self.next_button.setText(
            first_run.next_label(self.index, key_changed=chosen != self._saved)
        )

    def _store_key(self) -> bool:
        """Save the chosen key if it moved. ``False`` keeps the step on screen."""
        chosen = self.key_box.currentText()
        if chosen == self._saved:
            return True
        result = self._save_key(chosen)
        if not result.ok:
            self._key_message.setText(result.error or f"Could not set the key to {chosen}.")
            return False
        self._saved = chosen
        return True

    # --- the daemon -------------------------------------------------------------

    def refresh(self) -> None:
        if self._open and self.step in first_run.LIVE_STEPS:
            self._ctx.run("setup", self._ctx.status, self._show)

    def _show(self, status: Any) -> None:
        if not self._open:
            return
        self._status = status
        self._mic = self._mic.update(status)
        self._paint(status, answered=True)
        self._follow_recalibration(status)

    def _paint(self, status: Any, *, answered: bool = False) -> None:
        key = first_run.hold_key_label(status, self._saved, self._default)
        self._try_key.setText(key)
        self.level.setValue(self._mic.position)
        self._mic_verdict.setText(first_run.mic_message(self._mic, key))
        self.recalibrate_button.setEnabled(
            self._recal_started is None and first_run.can_recalibrate(status)
        )
        if not answered:
            return      # "Checking…" stays until the daemon has been asked once
        if self._acting:
            return      # "Starting…" stays until the command returns
        prompt = first_run.daemon_prompt(status, self._saved, self._default)
        self._action = prompt.action
        waiting = bool(prompt.action) and self._restart_elsewhere()
        text = prompt.text
        if waiting:
            text += "\nA restart is already running."
        elif prompt.action and self._failure:
            text += f"\nThat did not work: {self._failure}"
        self._say(text)
        for action in (self.mic_action, self.try_action):
            action.setText(prompt.action_label)
            action.setVisible(bool(prompt.action))
            action.setEnabled(not waiting)

    def _say(self, text: str) -> None:
        self._mic_daemon.setText(text)
        self._try_daemon.setText(text)

    def _restart_elsewhere(self) -> bool:
        """Whether Apply's own restart is running on the window."""
        busy = getattr(self._ctx.window, "_yazses_restarting", None)
        return busy is not None and bool(busy())

    def _act(self) -> None:
        action = self._action
        effect = {"start": self._ctx.start_daemon, "restart": self._ctx.restart_daemon}.get(action)
        if effect is None or self._acting or self._restart_elsewhere():
            return
        self._acting, self._failure = True, ""
        for one in (self.mic_action, self.try_action):
            one.setEnabled(False)
        self._say(_ACTION_WORDS[action])
        if not self._ctx.run(action, effect, self._acted):
            self._acting = False
            self._say("YazSes is already starting.")

    def _acted(self, outcome: Any) -> None:
        self._acting = False
        if not self._open:
            return
        ok, message = outcome if outcome else (False, "No result was reported.")
        self._failure = "" if ok else str(message)
        for one in (self.mic_action, self.try_action):
            one.setEnabled(True)
        if not ok:
            self._say(f"That did not work: {message}")
        self.refresh()
        self._focus()

    # --- the microphone ---------------------------------------------------------

    def _choose_microphone(self) -> None:
        """The Audio page holds the picker; the guide gets out of its way."""
        self.dialog.reject()
        self._ctx.goto("audio")

    def _recalibrate(self) -> None:
        if self._recal_started is not None:
            return
        self._recal_before = first_run.threshold_of(self._status)
        self._recal_started = self.clock()
        self.recalibrate_button.setEnabled(False)
        self._recal_message.setText("Asking YazSes to recalibrate…")
        if not self._ctx.run(
            "recalibrate", lambda: self._ctx.client_call("recalibrate_mic"), self._recalibrating
        ):
            self._recal_started = None
            self._recal_message.setText("A recalibration is already running.")

    def _recalibrating(self, reply: Any) -> None:
        if not self._open:
            return
        if reply and reply.get("ok"):
            self._recal_started = self.clock()
            self._recal_message.setText(first_run.recalibration_prompt(0.0) or "")
        else:
            self._recal_started = None
            reason = (reply or {}).get("reason") or (reply or {}).get("error")
            self._recal_message.setText(str(reason or "YazSes did not answer."))
        self._focus()

    def _follow_recalibration(self, status: Any) -> None:
        if self._recal_started is None:
            return
        text = first_run.recalibration_prompt(self.clock() - self._recal_started)
        if text is None:
            self._recal_started = None
            text = first_run.recalibration_result(
                self._recal_before, first_run.threshold_of(status)
            )
            self.recalibrate_button.setEnabled(first_run.can_recalibrate(status))
        self._recal_message.setText(text)

    def _counted(self) -> None:
        words = overview.word_count(self.practice.toPlainText())
        done = " It works." if words else ""
        self._words.setText(f"{words} word{'' if words == 1 else 's'}.{done}")


# --- the settings window ------------------------------------------------------------


def _platform_default() -> str:
    try:
        from yazses.platform import get_platform

        return str(get_platform().default_hotkey)
    except Exception:  # noqa: BLE001 - the guide then says "your hold-to-talk key"
        return ""


def _snap_warning() -> str:
    try:
        from yazses.settingsui.controls import snap_interface_banner

        return snap_interface_banner() or ""
    except Exception:  # noqa: BLE001 - a diagnostic must not stop the guide
        return ""


def _save_window_key(window: Any, key: str) -> Any:
    """``set_hotkey``, then show the saved key on the General page as well."""
    result = window._controller.set_hotkey(key)
    if result.ok:
        window._hotkey_baseline = key
        box = window._hotkey_box
        index = box.findText(key)
        if index >= 0:
            box.setCurrentIndex(index)
        window._refresh_markers()
        window._hint.setText("Hold-to-talk key saved. YazSes uses it after a restart.")
    return result


def open_setup(window: Any) -> SetupDialog:
    """Show the guide over the settings *window*; one at a time."""
    current = getattr(window, "_setup_dialog", None)
    if current is not None:
        if current.is_open():
            current.raise_()
            return current
        current.dialog.deleteLater()
    guide = SetupDialog(
        window._page_context,
        hotkey=window._hotkey_baseline,
        save_key=lambda key: _save_window_key(window, key),
        platform_default=_platform_default(),
        warning=_snap_warning(),
    )
    window._setup_dialog = guide
    guide.show()
    seen = getattr(window, "_setup_seen", None)
    if seen is not None:
        seen()
    return guide


def offer_on_open(window: Any, config_file: Path) -> SetupDialog | None:
    """Open the guide on a new install, unless the window was opened at another page.

    Showing it, now or later from the Overview page, is what marks it seen.
    """
    window._setup_seen = lambda: first_run.mark_seen(config_file)
    if window._shell.current_key() != "overview":
        return None
    try:
        return open_setup(window)
    except Exception:  # noqa: BLE001 - the settings window must stay usable without it
        log.exception("could not open the setup guide")
        return None
