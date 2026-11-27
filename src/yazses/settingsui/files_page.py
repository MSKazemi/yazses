"""The File transcription page: a thin Qt shell over ``files.py`` and a child process."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from yazses.settingsui import files
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

_MODELS = (
    ("Your configured model", ""),
    ("tiny.en: fastest", "tiny.en"),
    ("base.en", "base.en"),
    ("small.en: more accurate", "small.en"),
    ("base: multilingual", "base"),
    ("small: multilingual", "small"),
)

_FORMATS = (
    ("Plain text (.txt)", "txt"),
    ("Markdown (.md)", "md"),
    ("Subtitles (.srt)", "srt"),
    ("Subtitles (.vtt)", "vtt"),
    ("JSON (.json)", "json"),
)


_SPEAKERS_READY = "Label who said what (the first use downloads about 45 MB)"
_SPEAKERS_MISSING = "Label who said what (needs the diarization extra)"


def _qt_process(parent: Any) -> Any:
    """A ``yazses transcribe`` child: ``start(argv, done)`` and ``kill()``."""
    from PySide6.QtCore import QProcess, QProcessEnvironment

    class _Child:
        def __init__(self) -> None:
            self._process = QProcess(parent)
            self._done: Callable[[int, str], None] | None = None
            environment = QProcessEnvironment.systemEnvironment()
            environment.insert("PYTHONIOENCODING", "utf-8")
            self._process.setProcessEnvironment(environment)

        def start(self, argv: list[str], done: Callable[[int, str], None]) -> None:
            self._done = done
            self._process.finished.connect(self._finished)
            self._process.errorOccurred.connect(self._error)
            self._process.start(argv[0], argv[1:])

        def _report(self, code: int, text: str) -> None:
            done, self._done = self._done, None
            if done is not None:
                done(code, text)

        def _finished(self, code: int, status: Any) -> None:
            text = bytes(self._process.readAllStandardError().data()).decode(
                "utf-8", "replace"
            )
            crashed = status == QProcess.ExitStatus.CrashExit
            self._report(-1 if crashed else code, text)

        def _error(self, error: Any) -> None:
            # Only a failure to start has no `finished` signal to follow it.
            if error == QProcess.ProcessError.FailedToStart:
                self._report(-1, self._process.errorString())

        def kill(self) -> None:
            self._done = None
            self._process.kill()
            self._process.waitForFinished(3000)

    return _Child()


class FilesPage:
    interval_ms = 2000

    def __init__(self, ctx: PageContext) -> None:
        from PySide6.QtWidgets import (
            QCheckBox,
            QFormLayout,
            QListWidget,
            QPlainTextEdit,
            QProgressBar,
            QSpinBox,
        )

        self._ctx = ctx
        self.source: Path | None = None
        #: The running child, or ``None``.
        self.process: Any = None
        self.process_factory: Callable[[], Any] = lambda: _qt_process(ctx.window)
        self.confirm_overwrite: Callable[[Path], bool] = self._ask_overwrite
        self.confirm_abandon: Callable[[], bool] = self._ask_abandon
        #: Whether speaker labelling can run here; replaced in tests.
        self.extra_installed: Callable[[], bool] = self._diarization_installed
        self._written: list[tuple[Path, str]] = []
        self.widget, layout = page_widget()

        drop, inner = card(hero=True)
        self._chosen = label("Drop an audio or video file here", heading=True)
        inner.addWidget(self._chosen)
        inner.addWidget(label(
            "MP3, WAV, M4A, FLAC, OGG, OPUS, MP4 and most other media.", muted=True
        ))
        inner.addLayout(row(button("Browse…", self._browse)))
        self._accept_drops(drop)
        layout.addWidget(drop)

        options, body = card()
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        self.format_box = compact_combo()
        for text, value in _FORMATS:
            self.format_box.addItem(text, value)
        self.model_box = compact_combo()
        for text, value in _MODELS:
            self.model_box.addItem(text, value)
        self.speakers = QCheckBox(_SPEAKERS_READY)
        self.count = QSpinBox()
        self.count.setRange(0, 20)
        self.count.setSpecialValueText("Detect automatically")
        self.count.setEnabled(False)
        self.speakers.toggled.connect(self.count.setEnabled)
        self.translate = QCheckBox("Translate into English (needs a multilingual model)")
        self.format_box.setAccessibleName("Format")
        self.model_box.setAccessibleName("Model")
        self.count.setAccessibleName("Number of speakers")
        form.addRow(label("Format"), self.format_box)
        form.addRow(label("Model"), self.model_box)
        form.addRow(self.speakers)
        form.addRow(label("Speakers"), self.count)
        form.addRow(self.translate)
        body.addLayout(form)
        #: The install switch, shown only while the libraries are missing.
        self._install = ctx.switches.card("recimport")
        if self._install is not None:
            body.addWidget(self._install)
        self.run_button = button("Transcribe", self._run, primary=True)
        self.run_button.setEnabled(False)
        self.cancel_button = button("Cancel", self.cancel)
        self.cancel_button.hide()
        body.addLayout(row(self.run_button, self.cancel_button))
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)  # the command reports no percentage
        self._progress.setAccessibleName("Transcription in progress")
        self._progress.hide()
        body.addWidget(self._progress)
        layout.addWidget(options)

        view, body = card()
        self._heading = label("Result", heading=True)
        body.addWidget(self._heading)
        self.note = label("")
        restyle(self.note, level="warn")
        self.note.hide()
        body.addWidget(self.note)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("The transcript appears here.")
        self.result.setAccessibleName("Transcription result")
        self.result.setMinimumHeight(180)
        body.addWidget(self.result)
        # Shown once there is something in it: an empty box reads as something broken.
        self._session = (
            label("This session", heading=True),
            label("The list clears when this window closes. The saved files stay.", muted=True),
        )
        for item in self._session:
            body.addWidget(item)
        self.history = QListWidget()
        self.history.setObjectName("yzList")
        self.history.setAccessibleName("Files transcribed in this session")
        self.history.setMaximumHeight(120)
        self.history.currentRowChanged.connect(self._show_written)
        body.addWidget(self.history)
        self.folder_button = button("Open folder", self._open_folder)
        self.folder_button.setEnabled(False)
        body.addLayout(row(self.folder_button))
        for item in (*self._session, self.history, self.folder_button):
            item.hide()
        layout.addWidget(view)
        layout.addStretch(1)
        self.refresh()

    def refresh(self) -> None:
        """Offer speaker labels only where they can run; an install can change that."""
        ready = self.extra_installed()
        self.speakers.setEnabled(ready)
        if not ready:
            self.speakers.setChecked(False)
        self.speakers.setText(_SPEAKERS_READY if ready else _SPEAKERS_MISSING)
        if self._install is not None:
            self._install.setVisible(not ready)

    def _diarization_installed(self) -> bool:
        from yazses.recimport.factory import diarization_status

        try:
            return bool(diarization_status(self._ctx.load_config().recimport)["extra_installed"])
        except Exception:  # noqa: BLE001 - offer it; the command explains what is missing
            return True

    # --- choosing ---------------------------------------------------------------

    def _accept_drops(self, target: Any) -> None:
        from PySide6.QtCore import QEvent, QObject

        page = self

        class _Drop(QObject):
            def eventFilter(self, _obj: Any, event: Any) -> bool:  # noqa: N802
                kind = event.type()
                if kind in (QEvent.Type.DragEnter, QEvent.Type.Drop):
                    local = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
                    if local:
                        event.acceptProposedAction()
                        if kind == QEvent.Type.Drop:
                            page.choose(Path(local[0]))
                        return True
                return False

        target.setAcceptDrops(True)
        self._drop_filter = _Drop(target)
        target.installEventFilter(self._drop_filter)

    def choose(self, path: Path) -> None:
        if not path.is_file():
            self._chosen.setText(f"That is not a file: {path.name}")
            return
        self.source = path
        self._chosen.setText(path.name)
        self.run_button.setEnabled(self.process is None)

    def _browse(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        chosen, _filter = QFileDialog.getOpenFileName(
            self._ctx.window, "Choose a recording", str(Path.home())
        )
        if chosen:
            self.choose(Path(chosen))

    # --- running ----------------------------------------------------------------

    def _job(self) -> files.Job:
        assert self.source is not None
        return files.Job(
            source=self.source,
            fmt=str(self.format_box.currentData()),
            model=str(self.model_box.currentData()),
            speakers=self.speakers.isChecked(),
            count=self.count.value(),
            translate=self.translate.isChecked(),
        )

    def _run(self) -> None:
        if self.source is None or self.process is not None:
            return
        job = self._job()
        out = files.output_path(job)
        if out.exists() and not self.confirm_overwrite(out):
            return
        process = self.process_factory()
        self.process = process
        self._busy(True)
        self._show_note("")
        self._heading.setText(f"Transcribing {job.source.name}…")
        self.result.setPlainText("")
        process.start(
            files.command(job),
            lambda code, errors, p=process: self._done(p, out, code, errors),
        )

    def _done(self, process: Any, out: Path, code: int, errors: str) -> None:
        if process is not self.process:
            return  # cancelled, or an older run
        self.process = None
        self._busy(False)
        if code == 0 and out.is_file():
            self._written.append((out, files.notes(errors)))
            self.history.addItem(out.name)
            for item in (*self._session, self.history, self.folder_button):
                item.show()
            self.history.setCurrentRow(self.history.count() - 1)
        else:
            self._heading.setText("Transcription failed")
            self.result.setPlainText(files.failure_text(errors))

    def cancel(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        process.kill()
        self._busy(False)
        self._heading.setText("Result")
        self.result.setPlainText("Cancelled.")

    def _busy(self, busy: bool) -> None:
        self.run_button.setEnabled(not busy and self.source is not None)
        self.cancel_button.setVisible(busy)
        self._progress.setVisible(busy)

    def may_close(self) -> bool:
        """Whether the window may close: asks, then ends the job, while one runs."""
        if self.process is None:
            return True
        if not self.confirm_abandon():
            return False
        self.cancel()
        return True

    # --- results ----------------------------------------------------------------

    def _show_written(self, index: int) -> None:
        if not 0 <= index < len(self._written):
            return
        path, note = self._written[index]
        self._show_note(note)
        self._heading.setText(f"Saved to {path}")
        self.result.setPlainText(files.preview(path))
        self.folder_button.setEnabled(True)

    def _show_note(self, text: str) -> None:
        self.note.setText(text)
        self.note.setVisible(bool(text))

    def _open_folder(self) -> None:
        index = self.history.currentRow()
        if 0 <= index < len(self._written):
            self._ctx.open_path(str(self._written[index][0].parent))

    # --- dialogs ----------------------------------------------------------------

    def _ask_overwrite(self, path: Path) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self._ctx.window, "Replace the existing file?",
            f"{path} already exists. Replace it with a new transcript?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _ask_abandon(self) -> bool:
        from PySide6.QtWidgets import QMessageBox

        answer = QMessageBox.question(
            self._ctx.window, "Stop the transcription?",
            "A file is still being transcribed. Closing the window stops it.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes
