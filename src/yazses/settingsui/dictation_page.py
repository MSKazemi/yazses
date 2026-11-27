"""The Dictation page: the key, what the daemon hears, and a box to try it in."""
from __future__ import annotations

from typing import Any

from yazses.settingsui import overview
from yazses.settingsui.context import PageContext
from yazses.settingsui.controls import meter_reading
from yazses.settingsui.widgets import button, card, label, page_widget, row, waveform

#: The writing options offered here, by capability slug. All are Features rows too.
OPTION_SLUGS = ("voice-punctuation", "undo", "llm-cleanup", "overlay")


class DictationPage:
    interval_ms = 150

    def __init__(self, ctx: PageContext, hotkey: str) -> None:
        from PySide6.QtWidgets import QPlainTextEdit, QProgressBar

        self._ctx = ctx
        self.widget, layout = page_widget()

        hero, inner = card(hero=True)
        self._key = label(overview.key_label(hotkey))
        self._key.setProperty("keycap", "true")
        self._key.setWordWrap(False)
        inner.addLayout(row(self._key))
        self._state = label("Checking…")
        inner.addWidget(self._state)
        self._wave = waveform(56)
        inner.addWidget(self._wave)
        self.level = QProgressBar()
        self.level.setRange(0, 100)
        self.level.setTextVisible(False)
        self.level.setAccessibleName("Input level while recording")
        inner.addWidget(self.level)
        self._mic = label("", muted=True)
        inner.addWidget(self._mic)
        inner.addLayout(row(
            button("Choose microphone", lambda: ctx.goto("audio")),
            button("Model and language", lambda: ctx.goto("speech")),
        ))
        layout.addWidget(hero)

        trial, body = card()
        body.addWidget(label("Try it here", heading=True))
        body.addWidget(label(
            "Click in the box, hold your key and speak. This window does not save "
            "what appears here.", muted=True,
        ))
        self.practice = QPlainTextEdit()
        self.practice.setPlaceholderText("Your words appear here when you release the key.")
        self.practice.setAccessibleName("Practice dictation box")
        self.practice.setTabChangesFocus(True)
        self.practice.setMinimumHeight(110)
        body.addWidget(self.practice)
        self._count = label("0 words", muted=True)
        body.addLayout(row(self._count, button("Clear", self.practice.clear)))
        self.practice.textChanged.connect(self._counted)
        layout.addWidget(trial)

        layout.addWidget(label("Writing options", heading=True))
        for slug in OPTION_SLUGS:
            switch = ctx.switches.card(slug)
            if switch is not None:
                layout.addWidget(switch)
        layout.addStretch(1)

    def _counted(self) -> None:
        words = overview.word_count(self.practice.toPlainText())
        self._count.setText(f"{words} word{'' if words == 1 else 's'}")

    def refresh(self) -> None:
        self._ctx.run("dictation", self._ctx.status, self._show)

    def _show(self, status: Any) -> None:
        health = overview.health(status)
        self._state.setText(f"{health.title}. {health.detail}")
        recording = bool(status) and str(status.get("state") or "").lower() == "recording"
        if status and status.get("hotkey"):
            self._key.setText(overview.key_label(status["hotkey"]))
        checks = {c.name: c.value for c in overview.system_checks(status)}
        self._mic.setText(
            f"Microphone: {checks['Microphone']}" if checks else ""
        )
        # The daemon reports a level only during a hold; idle it says 0, which is not a
        # statement about the microphone.
        position = 0
        if recording:
            try:
                position, _clears = meter_reading(
                    float(status.get("audio_level") or 0.0),
                    float(status.get("vad_threshold") or 0.01),
                )
            except (TypeError, ValueError):
                position = 0
            self._wave.push(position / 100)
        else:
            self._wave.rest()
        self.level.setValue(position)
