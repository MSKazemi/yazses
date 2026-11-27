"""The Overview page: a thin Qt shell over ``overview.py``."""
from __future__ import annotations

from typing import Any

from yazses.settingsui import overview
from yazses.settingsui.context import PageContext
from yazses.settingsui.widgets import button, card, label, page_widget, restyle, row, waveform

_LEVEL_NAMES = {"ok": "Ready", "warn": "Attention", "bad": "Problem"}

_JOBS = (
    ("dictation", "Dictation", "Try your key and choose how text is written."),
    ("meetings", "Record a meeting", "Hands-free, with speakers labelled after you stop."),
    ("files", "Transcribe a file", "Audio or video to text or subtitles."),
)


class OverviewPage:
    interval_ms = 1000

    def __init__(self, ctx: PageContext, hotkey: str) -> None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QHBoxLayout

        self._ctx = ctx
        self._hotkey = hotkey
        self._action = ""
        self.widget, layout = page_widget()

        self._health, health = card(level="ok")
        self._badge = label("")
        self._title = label("Checking…", heading=True)
        self._detail = label("")
        self._message = label("", muted=True)
        self.action_button = button("", self._act, primary=True)
        self.action_button.hide()
        health.addLayout(row(self._badge, stretch=True))
        for item in (self._title, self._detail):
            health.addWidget(item)
        health.addLayout(row(self.action_button))
        health.addWidget(self._message)
        self._message.hide()
        layout.addWidget(self._health)

        hero, inner = card(hero=True)
        line = QHBoxLayout()
        self._wave = waveform(24)
        self._wave.levels = _resting_shape(24)
        right = waveform(24)
        right.levels = list(reversed(self._wave.levels))
        self._key = label(overview.key_label(hotkey))
        self._key.setProperty("keycap", "true")
        self._key.setWordWrap(False)
        line.addWidget(self._wave, 1)
        line.addWidget(self._key)
        line.addWidget(right, 1)
        inner.addLayout(line)
        caption = label("Hold to speak · release to stop", muted=True)
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        inner.addWidget(caption)
        layout.addWidget(hero)

        for key, title, text in _JOBS:
            tile, body = card()
            line = QHBoxLayout()
            line.addWidget(label(f"{title}\n{text}"), 1)
            opener = button("Open", lambda k=key: ctx.goto(k))
            opener.setAccessibleName(f"Open {title}")
            line.addWidget(opener)
            body.addLayout(line)
            layout.addWidget(tile)

        self._checks, checks = card()
        self._checks.hide()
        checks.addWidget(label("System check", heading=True))
        self._check_text = label("")
        checks.addWidget(self._check_text)
        layout.addWidget(self._checks)
        if ctx.open_setup is not None:
            self.setup_button = button("Run the setup guide", ctx.open_setup)
            layout.addLayout(row(self.setup_button))
        layout.addStretch(1)

    def refresh(self) -> None:
        self._ctx.run("overview", self._ctx.status, self._show)

    def _show(self, status: Any) -> None:
        health = overview.health(status)
        self._badge.setText(f"● {_LEVEL_NAMES[health.level]}")
        restyle(self._badge, level=health.level)
        restyle(self._health, level=health.level)
        self._title.setText(health.title)
        self._detail.setText(health.detail)
        self._action = health.action
        self.action_button.setText(health.action_label)
        self.action_button.setVisible(bool(health.action))
        if status and status.get("hotkey"):
            self._key.setText(overview.key_label(status["hotkey"]))
        checks = overview.system_checks(status)
        self._checks.setVisible(bool(checks))
        self._check_text.setText(
            "\n".join(f"{'✓' if c.ok else '!'}  {c.name}: {c.value}" for c in checks)
        )

    def _say(self, text: str) -> None:
        self._message.setText(text)
        self._message.setVisible(bool(text))

    def _act(self) -> None:
        action = self._action
        if action == "recalibrate":
            self._say("")
            self._ctx.run(
                "recalibrate",
                lambda: self._ctx.client_call("recalibrate_mic"),
                self._recalibrating,
            )
            return
        effect = {"start": self._ctx.start_daemon, "restart": self._ctx.restart_daemon}.get(action)
        if effect is None:
            return
        busy = getattr(self._ctx.window, "_yazses_restarting", None)
        if busy is not None and busy():
            self._say("A restart is already running.")
            return
        self.action_button.setEnabled(False)
        self._say("Starting…" if action == "start" else "Restarting…")
        self._ctx.run(action, effect, self._finished)

    def _recalibrating(self, reply: Any) -> None:
        if reply is None:
            self._say("YazSes did not answer.")
        elif not reply.get("ok"):
            self._say(str(reply.get("reason") or reply.get("error") or "It did not start."))
        else:
            self._say("Recalibrating: speak normally for about three seconds.")

    def _finished(self, outcome: Any) -> None:
        self.action_button.setEnabled(True)
        ok, message = outcome if outcome else (False, "No result was reported.")
        self._say("" if ok else f"That did not work: {message}")
        self.refresh()


def _resting_shape(bars: int) -> list[float]:
    """A fixed, decorative wave for the page's heading panel."""
    shape = (0.1, 0.3, 0.2, 0.55, 0.85, 0.45, 1.0, 0.7, 0.35, 0.6, 0.25, 0.15)
    return [shape[i % len(shape)] * 0.8 for i in range(bars)]
