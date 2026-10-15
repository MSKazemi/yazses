"""The hands-free controls window — a thin Qt shell over `handsfree/panel.py` (#420).

Everything this window *says* and every button's *meaning* is decided by the pure view-model
(:func:`yazses.handsfree.panel.build_panel`); this file only places widgets and forwards
presses. It is deliberately dull, because the people it is for are the ones a clever widget
fails first.

**Design rules, each of which has a test:**

* *State is a word.* Every row begins with its state word (``OK``, ``NEEDS ATTENTION``,
  ``PROBLEM`` …). No colour is used at all, so there is nothing for a colour-blind user to miss
  and nothing a high-contrast theme can erase.
* *Large targets.* Every action button is at least :data:`MIN_TARGET_PX` tall and wide
  enough for its label, and the three that matter in an emergency — Pause, Resume/Recover,
  Recenter — are the first three things in the tab order. They are stacked, not set side by
  side: three long labels in a row overflow the window the moment the system font is enlarged
  (seen at 24 pt, where "Pause hands-free input" was cut to "se hands-free in"), and a
  stacked button always has the window's full width.
* *Text follows the system font.* Sizes are derived from the font the platform hands the
  application, in whichever unit it uses (points or pixels), never set to a fixed number.
* *A screen reader hears the sentence, not a caption.* A label's accessible name is its own
  text. Giving a label a short name ("Hands-free state") replaces the text in what a screen
  reader is told, so the state itself would never be announced; no label is given one.
* *Enter never does something you did not aim at.* The window's default button is Refresh,
  which is harmless, so Enter on text or a combo box refreshes instead of pausing.
* *The Pause button works before anything has been read.* The window appears at once and
  reads the daemon on a worker thread; until that answer arrives every other control is
  disabled and Pause makes its ordinary call.
* *No action needs a pointer position.* Each button is a keyboard mnemonic (Alt+P, Alt+R,
  Alt+C) and Enter on the focused button; the same actions exist as `yazses handsfree pause` /
  `resume` and `yazses headpointer recenter`, so a voice command, a switch or a script reaches
  them too.
* *Refreshing never moves focus.* The window re-reads the daemon every second so a fault
  appears without being asked for, but it updates existing widgets in place — it never
  rebuilds them — and a widget whose text did not change is not touched, so a screen reader
  is not re-announcing a sentence that did not change. If the button you were on becomes
  unavailable (you pressed Pause, so Pause is now moot) focus moves to the button the new
  state calls for rather than falling off the window.
* *A disabled button says why.* The reason sits in visible text beside it and in its
  accessible description; a greyed-out control with no explanation is a dead end for someone
  who cannot hover.
* *Opening it never opens the camera, and never blocks.* The slow part of gathering the facts
  (the display topology behind the calibration check) runs on a worker thread; the window
  appears at once saying it is checking.

Qt is imported inside the class so a base install, and the tests that import this module for
its pure helpers, never load it.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from yazses.handsfree.panel import (
    ActionSpec,
    FeatureRow,
    PanelInputs,
    PanelModel,
    build_panel,
    plan_mapping,
    stop_without_state,
)
from yazses.handsfree.panel_io import ActionResult

log = logging.getLogger(__name__)

__all__ = ["MIN_TARGET_PX", "HandsFreePanel", "mnemonic"]

#: Minimum height (and width) of any button, in pixels. Not a measured value: a conventional
#: large-target floor, set well above the toolkit default (~24 px) because the users of this
#: window are the ones who cannot aim precisely. WCAG 2.2 AAA asks for 44 px.
MIN_TARGET_PX = 48

#: Which letter each emergency action's Alt-mnemonic sits on.
_MNEMONICS = {"pause": "P", "resume": "R", "recenter": "c"}


def mnemonic(label: str, letter: str) -> str:
    """``label`` with an Alt-key mnemonic ``&`` before the first ``letter``. Pure.

    Returns the label unchanged when the letter does not occur — a mnemonic that cannot be
    placed is dropped, never invented on a different letter.
    """
    if not letter:
        return label
    index = label.lower().find(letter.lower())
    if index < 0:
        return label
    return label[:index] + "&" + label[index:]


def _plain(label: str) -> str:
    return label.replace("&", "")


def enlarged(font: Any, extra_pt: float, floor_pt: float = 11.0) -> Any:
    """``font`` made larger, in the unit the platform gave it. Mutates and returns it.

    A point-sized font grows by ``extra_pt`` from at least ``floor_pt``; a pixel-sized one (a
    desktop that scales by pixels, where ``pointSize()`` is ``-1``) grows by the same ratio.
    Setting a point size on a pixel-sized font would replace the user's scale with a constant.
    """
    points = font.pointSizeF()
    if points > 0.0:
        font.setPointSizeF(max(points, floor_pt) + extra_pt)
    elif font.pixelSize() > 0:
        font.setPixelSize(max(1, round(font.pixelSize() * (1.0 + extra_pt / floor_pt))))
    return font


def health_text(model: PanelModel) -> str:
    """The health rows as one block of text — word first, then what to do. Pure."""
    lines = []
    for row in model.health:
        lines.append(f"[{row.word}] {row.label}: {row.text}")
        if row.remedy:
            lines.append(f"    Next: {row.remedy}")
    return "\n".join(lines) if lines else "No camera control is switched on, so there is nothing to report."


class HandsFreePanel:
    """The window. ``gather`` and ``perform`` are injected so tests never touch a daemon."""

    def __init__(
        self,
        gather: Callable[[], PanelInputs],
        perform: Callable[[ActionSpec], ActionResult],
        *,
        toggle_feature: Callable[[str, bool], None] | None = None,
        apply_staged: Callable[[], None] | None = None,
        poll_ms: int = 1000,
        threaded: bool = True,
        parent: Any = None,
    ) -> None:
        from PySide6.QtCore import QObject, QTimer, Signal
        from PySide6.QtWidgets import (
            QComboBox,
            QDialog,
            QGridLayout,
            QGroupBox,
            QHBoxLayout,
            QLabel,
            QPushButton,
            QScrollArea,
            QVBoxLayout,
            QWidget,
        )

        class _Bridge(QObject):  # type: ignore[misc,valid-type]
            ready = Signal(object)

        self._gather = gather
        self._perform = perform
        self._toggle_feature = toggle_feature
        self._apply_staged = apply_staged
        self._threaded = threaded
        self._inputs: PanelInputs | None = None
        self._model: PanelModel | None = None
        self._busy = False
        self._buttons: dict[str, Any] = {}
        self._why: dict[str, Any] = {}
        self._feature_widgets: dict[str, tuple[Any, Any]] = {}
        self._map_widgets: dict[str, tuple[Any, Any, Any]] = {}
        self._bridge = _Bridge()
        self._bridge.ready.connect(self._on_inputs)

        self._dialog = QDialog(parent)
        self._dialog.setWindowTitle("YazSes — Hands-free controls")
        # Wide enough for the widest row (gesture name, choice, Set) at the user's font size:
        # a fixed 720 px was already too narrow at 32 pt, where the window scrolled sideways.
        self._dialog.resize(max(720, 44 * self._dialog.fontMetrics().averageCharWidth()), 820)

        def big_button(text: str, ident: str) -> Any:
            btn = QPushButton(text)
            btn.setMinimumHeight(MIN_TARGET_PX)
            btn.setMinimumWidth(MIN_TARGET_PX)
            btn.setFont(enlarged(btn.font(), 2.0))
            btn.setObjectName(ident)
            self._buttons[ident] = btn
            return btn

        def small_button(text: str, ident: str) -> Any:
            btn = QPushButton(text)
            btn.setMinimumHeight(MIN_TARGET_PX)
            btn.setMinimumWidth(MIN_TARGET_PX)
            btn.setObjectName(ident)
            self._buttons[ident] = btn
            return btn

        def wrapped(text: str = "") -> Any:
            label = QLabel(text)
            label.setWordWrap(True)
            return label

        outer = QVBoxLayout(self._dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        col = QVBoxLayout(body)
        scroll.setWidget(body)
        outer.addWidget(scroll)

        # ---- 1. the state, read first, in words --------------------------------
        self._headline = wrapped("Checking hands-free state…")
        hfont = enlarged(self._headline.font(), 5.0)
        hfont.setBold(True)
        self._headline.setFont(hfont)
        self._detail = wrapped("")
        col.addWidget(self._headline)
        col.addWidget(self._detail)

        # ---- 2. the emergency actions: first in the tab order ------------------
        for ident, text in (
            ("pause", "Pause hands-free input"),
            ("resume", "Resume hands-free input"),
            ("recenter", "Recenter Head-Pointer"),
        ):
            btn = big_button(mnemonic(text, _MNEMONICS[ident]), ident)
            btn.clicked.connect(lambda _=False, i=ident: self._press(i))
            col.addWidget(btn)
        self._why_box = wrapped("")
        col.addWidget(self._why_box)
        self._result = wrapped("")
        col.addWidget(self._result)

        # ---- 3. camera controls (the existing staged-toggle path) --------------
        box = QGroupBox("Camera controls")
        grid = QGridLayout(box)
        for index, ident in enumerate(("headpointer", "facegesture", "gaze")):
            text_label = wrapped("")
            btn = small_button("", f"feature_{ident}")
            btn.clicked.connect(lambda _=False, s=ident: self._press_feature(s))
            grid.addWidget(text_label, index, 0)
            grid.addWidget(btn, index, 1)
            self._feature_widgets[ident] = (text_label, btn)
        grid.setColumnStretch(0, 1)
        col.addWidget(box)
        apply_row = QHBoxLayout()
        apply_btn = small_button("Apply staged changes", "apply")
        apply_btn.clicked.connect(self._press_apply)
        apply_btn.setToolTip(
            "Writes the camera-control changes you staged and installs any missing packages."
        )
        apply_row.addWidget(apply_btn)
        apply_row.addStretch(1)
        col.addLayout(apply_row)

        # ---- 4. dwell, independently of motion ---------------------------------
        dbox = QGroupBox("Dwell-click (clicks when you hold still)")
        dlay = QVBoxLayout(dbox)  # stacked: side by side they clip once the font is large
        for ident in ("dwell_off", "dwell_on"):
            btn = small_button(ident, ident)
            btn.clicked.connect(lambda _=False, i=ident: self._press(i))
            dlay.addWidget(btn)
        col.addWidget(dbox)
        self._dwell_why = wrapped("")
        col.addWidget(self._dwell_why)

        # ---- 5. the global stop -------------------------------------------------
        sbox = QGroupBox("Global stop")
        slay = QVBoxLayout(sbox)
        self._safety_btn = small_button("", "safety_toggle")
        self._safety_btn.clicked.connect(lambda _=False: self._press_safety())
        self._safety_help = wrapped("")
        slay.addWidget(self._safety_btn)
        slay.addWidget(self._safety_help)
        col.addWidget(sbox)

        # ---- 6. health ----------------------------------------------------------
        hbox = QGroupBox("Health")
        hlay = QVBoxLayout(hbox)
        self._health = wrapped("Checking…")
        from PySide6.QtCore import Qt

        self._health.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        # Qt gives a selectable label click-focus only, so Tab skipped it: the one place the
        # health report can be read and copied was unreachable without a pointer.
        self._health.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        hlay.addWidget(self._health)
        col.addWidget(hbox)

        # ---- 7. face-switch mapping --------------------------------------------
        mbox = QGroupBox("Face switch mapping")
        mgrid = QGridLayout(mbox)
        from yazses.facegesture.detector import GESTURES

        for index, gesture in enumerate(GESTURES):
            name = wrapped(gesture.replace("_", " ").capitalize())
            combo = QComboBox()
            combo.setMinimumHeight(MIN_TARGET_PX)
            combo.setAccessibleName(f"Action for {gesture.replace('_', ' ')}")
            # On Linux a combo box's accessible *name* is its current choice and the question it
            # answers comes from a "labelled by" relation, which Qt derives from a buddy. Without
            # one a screen reader says "Hold to dictate, combo box" and never which gesture.
            name.setBuddy(combo)
            setb = small_button("Set", f"map_{gesture}")
            setb.setAccessibleName(f"Save mapping for {gesture.replace('_', ' ')}")
            setb.clicked.connect(lambda _=False, g=gesture: self._press_map(g))
            mgrid.addWidget(name, index, 0)
            mgrid.addWidget(combo, index, 1)
            mgrid.addWidget(setb, index, 2)
            self._map_widgets[gesture] = (name, combo, setb)
        mgrid.setColumnStretch(0, 1)
        self._map_note = wrapped("")
        mgrid.addWidget(self._map_note, len(GESTURES), 0, 1, 3)
        col.addWidget(mbox)

        self._notes = wrapped("")
        col.addWidget(self._notes)
        col.addStretch(1)

        bottom = QHBoxLayout()
        refresh = small_button("Refresh", "refresh")
        refresh.clicked.connect(self.refresh)
        # The default button is what Enter does when focus is on something that does not use
        # Enter (the health text, the dialog itself). Qt would otherwise pick the first
        # button in the window -- Pause. Refresh is harmless to press by accident.
        refresh.setDefault(True)
        close = small_button("Close", "close")
        close.clicked.connect(self._dialog.close)
        bottom.addWidget(refresh)
        bottom.addStretch(1)
        bottom.addWidget(close)
        outer.addLayout(bottom)

        self._set_tab_order()
        self._placeholders()
        self._dialog.finished.connect(lambda _=0: self.stop())
        self._timer: Any = None
        if poll_ms > 0:
            self._timer = QTimer(self._dialog)
            self._timer.timeout.connect(self.refresh)
            self._poll_ms = poll_ms

    # ---------------------------------------------------------------- before the first read

    #: Which controls stay usable until the daemon has answered once.
    _AWAITING = frozenset({"pause", "refresh", "close"})

    def _placeholders(self) -> None:
        """Words (not identifiers) on every control, and only the safe ones enabled, until the
        first state has been read. A screen reader landing on a button must never be told
        ``dwell_off``; a button that cannot know what it would do must not be pressable."""
        names = {"dwell_off": "Turn dwell-click off", "dwell_on": "Turn dwell-click on",
                 "safety_toggle": "Global stop", "apply": "Apply staged changes"}
        for ident, btn in self._buttons.items():
            if ident in names:
                btn.setText(names[ident])
            elif ident.startswith("feature_"):
                btn.setText("Checking…")
            if ident not in self._AWAITING:
                btn.setEnabled(False)
        for _name, _combo, setb in self._map_widgets.values():
            setb.setEnabled(False)
        self._first_read = False

    # ---------------------------------------------------------------- focus order

    def _set_tab_order(self) -> None:
        """Pause, Resume, Recenter first; then controls, in reading order. Explicit, so a
        layout change cannot silently reorder what a keyboard user reaches first."""
        order = ["pause", "resume", "recenter"]
        order += [f"feature_{s}" for s in ("headpointer", "facegesture", "gaze")] + ["apply"]
        order += ["dwell_off", "dwell_on", "safety_toggle"]
        widgets: list[Any] = [self._buttons[i] for i in order]
        widgets.append(self._health)
        for gesture, (_name, combo, setb) in self._map_widgets.items():
            widgets += [combo, setb]
        widgets += [self._buttons["refresh"], self._buttons["close"]]
        self._tab_order = widgets
        for first, second in zip(widgets, widgets[1:], strict=False):
            self._dialog.setTabOrder(first, second)

    @property
    def tab_order(self) -> list[Any]:
        return list(self._tab_order)

    # ---------------------------------------------------------------- refreshing

    def refresh(self) -> None:
        """Re-read the facts, off the UI thread. Overlapping refreshes collapse into one."""
        if self._busy:
            return
        self._busy = True
        if not self._threaded:
            self._finish(self._safe_gather())
            return
        threading.Thread(target=self._worker, name="handsfree-panel", daemon=True).start()

    def _safe_gather(self) -> PanelInputs | None:
        try:
            return self._gather()
        except Exception:
            log.debug("hands-free panel gather failed", exc_info=True)
            return None

    def _worker(self) -> None:
        self._bridge.ready.emit(self._safe_gather())

    def _on_inputs(self, inputs: object) -> None:
        self._finish(inputs if isinstance(inputs, PanelInputs) else None)

    def _finish(self, inputs: PanelInputs | None) -> None:
        self._busy = False
        if inputs is None:
            self._set_text(self._headline, "Could not read the hands-free state.")
            self._set_text(
                self._detail,
                "Nothing was changed. Try Refresh; `yazses handsfree status` shows the same "
                "information in a terminal.",
            )
            return
        self._inputs = inputs
        self.render(build_panel(inputs))

    # ---------------------------------------------------------------- rendering

    @staticmethod
    def _set_text(widget: Any, text: str) -> None:
        # Only touch a widget whose text changed: a screen reader re-announces on every set.
        if widget.text() != text:
            widget.setText(text)

    @staticmethod
    def _set_enabled(widget: Any, enabled: bool) -> None:
        if widget.isEnabled() != enabled:
            widget.setEnabled(enabled)

    def render(self, model: PanelModel) -> None:
        """Draw ``model`` into the existing widgets. Never creates or destroys one."""
        from PySide6.QtWidgets import QApplication

        focused = QApplication.focusWidget()
        self._model = model
        self._set_text(self._headline, model.banner.headline)
        self._set_text(self._detail, model.banner.detail)

        why_lines = []
        for ident in ("pause", "resume", "recenter"):
            spec = model.action(ident)
            assert spec is not None
            btn = self._buttons[ident]
            self._set_text(btn, mnemonic(spec.label, _MNEMONICS[ident]))
            self._set_enabled(btn, spec.enabled)
            btn.setAccessibleName(spec.label)
            btn.setAccessibleDescription(spec.help if spec.enabled else spec.why_disabled)
            btn.setToolTip(spec.help if spec.enabled else spec.why_disabled)
            if not spec.enabled:
                why_lines.append(f"{spec.label}: unavailable — {spec.why_disabled}")
        self._set_text(self._why_box, "\n".join(why_lines))

        dwell_why = []
        for spec in model.dwell:
            btn = self._buttons[spec.id]
            self._set_text(btn, spec.label)
            self._set_enabled(btn, spec.enabled)
            btn.setAccessibleName(spec.label)
            btn.setAccessibleDescription(spec.help if spec.enabled else spec.why_disabled)
            if not spec.enabled and spec.why_disabled:
                dwell_why.append(f"{spec.label}: unavailable — {spec.why_disabled}")
        self._set_text(self._dwell_why, "\n".join(dwell_why))

        sp = model.safety_toggle
        self._set_text(self._safety_btn, sp.label)
        self._set_enabled(self._safety_btn, sp.enabled)
        self._safety_btn.setAccessibleDescription(sp.help)
        self._set_enabled(self._buttons["apply"], self._apply_staged is not None)
        self._set_text(self._safety_help, sp.help)

        for feat in model.features:
            self._render_feature(feat)

        self._set_text(self._health, health_text(model))

        self._render_mapping(model)
        self._set_text(self._notes, "\n".join(model.notes))

        self._restore_focus(focused, model)
        if not self._first_read:
            self._first_read = True
            self._focus_first_action(focused, model)

    def _focus_first_action(self, focused: Any, model: PanelModel) -> None:
        """On the first read, put focus on the action the state calls for (Recover when
        faulted, Pause when running) unless the user has already moved somewhere else."""
        if focused is not None and focused is not self._buttons["pause"]:
            return
        primary = model.primary
        target = self._buttons.get(primary.id) if primary is not None else None
        if target is None or not target.isEnabled():
            target = self._buttons["pause"]
        if target.isEnabled():
            target.setFocus()

    def _render_feature(self, feat: FeatureRow) -> None:
        pair = self._feature_widgets.get(feat.slug)
        if pair is None:
            return
        label, btn = pair
        self._set_text(label, f"[{feat.word}] {feat.label} — {feat.summary}. {feat.text}")
        can = feat.desired is not None and self._toggle_feature is not None
        self._set_text(btn, feat.button or "Unavailable")
        self._set_enabled(btn, can)
        btn.setAccessibleName(feat.button or f"{feat.label} cannot be changed here")
        btn.setProperty("desired", feat.desired)

    def _render_mapping(self, model: PanelModel) -> None:
        mapping = model.mapping
        for row in mapping.rows:
            _name, combo, setb = self._map_widgets[row.gesture]
            # Rebuild the combo's items only when the *choices* changed; the current index
            # is the saved action unless the user is mid-edit on this very combo.
            want = [(key, label) for key, label, _ok, _why in mapping.choices]
            have = [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())]
            if have != want:
                combo.blockSignals(True)
                combo.clear()
                for key, label, ok, why in mapping.choices:
                    combo.addItem(label if ok else f"{label} (unavailable)", key)
                    item = combo.model().item(combo.count() - 1)
                    if item is not None and not ok:
                        item.setEnabled(False)
                        item.setToolTip(why)
                combo.blockSignals(False)
                have = [(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())]
            if not combo.hasFocus():
                saved = row.action or "none"
                idx = combo.findData(saved)
                if idx >= 0 and combo.currentIndex() != idx:
                    combo.blockSignals(True)
                    combo.setCurrentIndex(idx)
                    combo.blockSignals(False)
            self._set_enabled(setb, True)
        notes = [f"{r.gesture_label}: {r.note}" for r in mapping.rows if r.note]
        notes += [f"Ignored: {p}" for p in mapping.problems]
        notes.append("Mapping changes apply after `yazses restart`.")
        self._set_text(self._map_note, "\n".join(notes))

    def _restore_focus(self, focused: Any, model: PanelModel) -> None:
        """If the button you were on just became unavailable, move to the one the state wants."""
        if focused is None:
            return
        ours = [b for b in self._buttons.values() if b is focused]
        if ours and not focused.isEnabled():
            primary = model.primary
            target = self._buttons.get(primary.id) if primary is not None else None
            if target is not None and target.isEnabled():
                target.setFocus()

    # ---------------------------------------------------------------- presses

    def _show(self, message: str) -> None:
        self._set_text(self._result, message)

    def _press(self, ident: str) -> None:
        if self._model is None:
            if ident != "pause":
                self._show("The state has not been read yet — press Refresh.")
                return
            # A stop is never made to wait for the state to be read.
            result = self._perform(stop_without_state())
            self._show(("Done: " if result.ok else "Did not work: ") + result.message)
            self.refresh()
            return
        spec = self._model.action(ident)
        if spec is None:
            return
        result = self._perform(spec)
        self._show(("Done: " if result.ok else "Did not work: ") + result.message)
        self.refresh()

    def _press_safety(self) -> None:
        if self._model is None:
            return
        result = self._perform(self._model.safety_toggle)
        self._show(("Done: " if result.ok else "Did not work: ") + result.message)
        self.refresh()

    def _press_feature(self, slug: str) -> None:
        if self._toggle_feature is None or self._model is None:
            return
        feat = next((f for f in self._model.features if f.slug == slug), None)
        if feat is None or feat.desired is None:
            return
        self._toggle_feature(slug, feat.desired)
        self._show(
            f"{feat.label}: change staged. Press “Apply staged changes” to write it."
        )
        self.refresh()

    def _press_apply(self) -> None:
        if self._apply_staged is None:
            return
        self._apply_staged()
        self._show("Applied. Restart YazSes for camera-control changes to take effect.")
        self.refresh()

    def _press_map(self, gesture: str) -> None:
        if self._inputs is None:
            return
        combo = self._map_widgets[gesture][1]
        action = combo.currentData()
        plan = plan_mapping(self._inputs, gesture, str(action))
        if not plan.ok or plan.action is None:
            self._show(f"Not saved: {plan.reason}")
            return
        result = self._perform(plan.action)
        self._show(("Saved: " if result.ok else "Not saved: ") + result.message)
        self.refresh()

    # ---------------------------------------------------------------- showing

    @property
    def dialog(self) -> Any:
        return self._dialog

    def show(self) -> None:
        """Show the window and start polling. Reading the facts opens no camera."""
        self._dialog.show()
        if not self._first_read and self._buttons["pause"].isEnabled():
            self._buttons["pause"].setFocus()  # until the state is read, Pause is the one stop
        self.refresh()
        if self._timer is not None:
            self._timer.start(self._poll_ms)

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
