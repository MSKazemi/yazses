"""The Meetings page: a thin Qt shell over ``meetings.py`` and the meeting IPC calls."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from yazses.recimport.render import VALID_FORMATS
from yazses.settingsui import meetings
from yazses.settingsui.context import PageContext
from yazses.settingsui.widgets import (
    button,
    card,
    compact_combo,
    label,
    page_widget,
    restyle,
    row,
)

#: How long to wait for the daemon to start or stop a meeting.
_SLOW_CALL_S = 60.0


class MeetingsPage:
    interval_ms = 1000

    def __init__(self, ctx: PageContext) -> None:
        from PySide6.QtWidgets import (
            QFormLayout,
            QListWidget,
            QPlainTextEdit,
            QSpinBox,
        )

        self._ctx = ctx
        self._active = False
        self._rows: list[meetings.MeetingRow] = []
        self._shown_dir = ""
        self._format = "md"
        self.name_fields: dict[str, Any] = {}
        #: ``(default file name) -> chosen path or ""``; replaced in tests.
        self.choose_export: Callable[[str], str] = self._ask_export_path
        self.widget, layout = page_widget()

        self._enable = ctx.switches.card("meeting")
        if self._enable is not None:
            layout.addWidget(self._enable)

        recorder, inner = card(hero=True)
        self._clock = label("00:00:00")
        self._clock.setProperty("keycap", "true")
        self._clock.setWordWrap(False)
        inner.addLayout(row(self._clock))
        self._state = label("Checking…")
        inner.addWidget(self._state)
        self._warning = label("")
        restyle(self._warning, level="warn")
        self._warning.hide()
        inner.addWidget(self._warning)
        self.people = QSpinBox()
        self.people.setRange(0, 20)
        self.people.setSpecialValueText("Detect automatically")
        self.people.setAccessibleName("People in the room")
        self.record_button = button("Start meeting", self._record, primary=True)
        self.record_button.setEnabled(False)
        inner.addLayout(row(label("People in the room"), self.people, self.record_button))
        self._message = label("", muted=True)
        self._message.hide()
        inner.addWidget(self._message)
        layout.addWidget(recorder)

        stored, body = card()
        body.addWidget(label("Meetings on this computer", heading=True))
        self.list = QListWidget()
        self.list.setObjectName("yzList")
        self.list.setAccessibleName("Stored meetings")
        self.list.currentRowChanged.connect(self._select)
        body.addWidget(self.list)
        self._none = label("No meetings yet.", muted=True)
        body.addWidget(self._none)
        layout.addWidget(stored)

        view, body = card()
        self._heading = label("Transcript", heading=True)
        body.addWidget(self._heading)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setAccessibleName("Meeting transcript")
        self.transcript.setMinimumHeight(200)
        body.addWidget(self.transcript)
        self._names = QFormLayout()
        body.addLayout(self._names)
        self.rename_button = button("Save speaker names", self._rename)
        self.export_format = compact_combo()
        self.export_format.addItems(list(VALID_FORMATS))
        self.export_format.setAccessibleName("Export format")
        self.export_button = button("Export…", self._export)
        self.folder_button = button("Open folder", self._open_folder)
        body.addLayout(row(self.rename_button))
        body.addLayout(row(self.export_format, self.export_button, self.folder_button))
        layout.addWidget(view)
        layout.addStretch(1)
        self._show_selection_controls(None)

    def _say(self, text: str) -> None:
        self._message.setText(text)
        self._message.setVisible(bool(text))

    # --- polling ----------------------------------------------------------------

    def refresh(self) -> None:
        self._ctx.run("meetings", self._gather, self._show)

    def _gather(self) -> tuple[Any, Any, list[meetings.MeetingRow]]:
        from yazses.meeting import store

        cfg = self._ctx.load_config().meeting
        reply = self._ctx.ask("meeting_status")
        return cfg, reply, meetings.meeting_rows(store.list_meetings(cfg))

    def _show(self, gathered: Any) -> None:
        if gathered is None:
            self._state.setText("The meetings could not be read.")
            return
        cfg, reply, rows = gathered
        self._format = cfg.output_format
        view = meetings.live_view(reply)
        if view.busy:
            # One missed answer says nothing about the meeting: keep what is on screen.
            self._state.setText("YazSes is busy. This page keeps asking.")
            self._list_rows(rows)
            return
        was_active, self._active = self._active, view.active
        if self._enable is not None:
            self._enable.setVisible(not cfg.enabled)

        if view.active:
            text, can = "Recording. Speaker names are added after you stop.", True
        elif view.finalizing:
            text, can = "Finishing: the transcript is being written.", False
        elif not cfg.enabled:
            text, can = "Meeting Mode is off. Turn it on above, then click Apply.", False
        elif not view.running:
            text, can = "Start YazSes to record a meeting.", False
        elif not view.enabled:
            text, can = "Restart YazSes to finish turning Meeting Mode on.", False
        else:
            text, can = "Ready to record. No key to hold.", True
        self._state.setText(text)
        self.record_button.setText("Stop meeting" if view.active else "Start meeting")
        self.record_button.setEnabled(can)
        self.people.setEnabled(can and not view.active)
        self._clock.setText(view.clock)
        self._warning.setText(view.warning)
        self._warning.setVisible(bool(view.warning))
        self._list_rows(rows)

        self.list.setEnabled(not view.active)
        if view.active:
            self._shown_dir = ""
            self._heading.setText("Live draft")
            self._show_selection_controls(None)
            draft = "\n".join(view.lines) or "Listening…"
            if self.transcript.toPlainText() != draft:
                self.transcript.setPlainText(draft)
        elif was_active:
            self._open(self._current_row())

    def _list_rows(self, rows: list[meetings.MeetingRow]) -> None:
        self._none.setVisible(not rows)
        self.list.setVisible(bool(rows))
        if rows == self._rows:
            return
        selected = self._current_row()
        was_finished = selected.finished if selected else None
        self._rows = rows
        self.list.blockSignals(True)
        self.list.clear()
        for item in rows:
            self.list.addItem(f"{item.title}   {item.detail}")
        if selected is not None:
            for index, item in enumerate(rows):
                if item.id == selected.id:
                    self.list.setCurrentRow(index)
        self.list.blockSignals(False)
        self._fit_list()
        current = self._current_row()
        if selected is not None and (current is None or current.finished != was_finished):
            self._open(current)

    def _fit_list(self) -> None:
        """As tall as its rows, up to six, then it scrolls."""
        shown = min(max(self.list.count(), 1), 6)
        height = max(self.list.sizeHintForRow(0), 20)
        self.list.setFixedHeight(shown * height + 18)

    # --- selection --------------------------------------------------------------

    def _current_row(self) -> meetings.MeetingRow | None:
        index = self.list.currentRow()
        return self._rows[index] if 0 <= index < len(self._rows) else None

    def _select(self, _index: int) -> None:
        self._open(self._current_row())

    def _open(self, item: meetings.MeetingRow | None) -> None:
        self._heading.setText(f"Transcript: {item.title}" if item else "Transcript")
        self._shown_dir = item.dir if item else ""
        self.transcript.setPlainText(
            meetings.transcript_text(item.dir) if item else ""
        )
        self._show_selection_controls(item)

    def _show_selection_controls(self, item: meetings.MeetingRow | None) -> None:
        from PySide6.QtWidgets import QLineEdit

        while self._names.rowCount():
            self._names.removeRow(0)
        self.name_fields = {}
        found = meetings.speakers(item.dir) if item else {}
        for key, name in found.items():
            field = QLineEdit(name)
            field.setAccessibleName(f"Name for {name}")
            self.name_fields[key] = field
            self._names.addRow(label(f"{name} is"), field)
        self.rename_button.setVisible(bool(found))
        for widget in (self.export_format, self.export_button):
            widget.setVisible(bool(item and item.finished))
        self.folder_button.setVisible(item is not None)

    # --- actions ----------------------------------------------------------------

    def _record(self) -> None:
        method = "meeting_stop" if self._active else "meeting_start"
        params: dict[str, Any] = {}
        if not self._active and self.people.value():
            params["speakers"] = self.people.value()
        # Stopping waits for the current decode, and starting loads models: both
        # routinely outlast the client's two-second default.
        params["wait_s"] = _SLOW_CALL_S
        self.record_button.setEnabled(False)
        self._say("Stopping…" if self._active else "Starting…")
        self._ctx.run(
            method, lambda: self._ctx.ask(method, **params), self._recorded
        )

    def _recorded(self, reply: Any) -> None:
        if reply is None:
            self._say("YazSes did not answer.")
        elif reply.get("unresponsive"):
            self._say(
                "YazSes is still working on it. The meeting will appear below; there is "
                "no need to press the button again."
            )
        elif not reply.get("ok"):
            self._say(str(reply.get("reason") or "It was refused."))
        else:
            # The daemon's start warning is the only place a user learns a transcript
            # will come back without speaker names, so it is shown as sent.
            notes = (reply.get("warning"), reply.get("hint"))
            self._say("\n".join(str(n) for n in notes if n))
        self.refresh()

    def _rename(self) -> None:
        if not self._shown_dir:
            return
        names = {key: field.text() for key, field in self.name_fields.items()}
        try:
            meetings.rename(self._shown_dir, names, self._format)
        except (OSError, ValueError, KeyError) as exc:
            self._say(f"The names were not saved: {exc}")
            return
        self._say("Speaker names saved.")
        self._open(self._current_row())

    def _export(self) -> None:
        item = self._current_row()
        if item is None:
            return
        fmt = self.export_format.currentText()
        chosen = self.choose_export(f"meeting-{item.id}.{fmt}")
        if not chosen:
            return
        try:
            written = meetings.export(item.dir, fmt, Path(chosen))
        except (OSError, ValueError) as exc:
            self._say(f"Not exported: {exc}")
            return
        self._say(f"Exported to {written}")

    def _ask_export_path(self, name: str) -> str:
        from PySide6.QtWidgets import QFileDialog

        chosen, _filter = QFileDialog.getSaveFileName(
            self._ctx.window, "Export the transcript", str(Path.home() / name)
        )
        return chosen

    def _open_folder(self) -> None:
        if self._shown_dir:
            self._ctx.open_path(self._shown_dir)
