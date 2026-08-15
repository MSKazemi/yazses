"""Linux system-tray indicator, built on PySide6 ``QSystemTrayIcon``.

A ``TrayBackend`` implementation (``run``/``set_state``/``stop``) driven by the generic
``yazses.tray.app`` runner: the app polls the daemon ``status`` on a worker thread and
calls ``set_state``; ``run`` owns the Qt event loop. PySide6 is already a base dependency
(the overlay uses it) so this adds nothing new.

The icon shows daemon state (and flags a live silent-streak in orange); the click-menu —
rebuilt fresh each time it opens — lets you pick/pin the input microphone, re-calibrate,
restart/stop the daemon, open the graphical settings window, reach the docs and the issue
tracker, see which version is running, and check for a newer one. On GNOME/AppIndicator the
menu is the *primary* interaction (shown on click via ``setContextMenu``); left-click
activation isn't delivered there.

Unlike the macOS/Windows trays where quitting the tray stops the daemon, "Quit tray" here
only closes the icon — dictation keeps running; a separate "Stop daemon" item stops it.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from yazses.platform.base import TrayModel, TrayState

if TYPE_CHECKING:
    from yazses.tray.controller import TrayController

log = logging.getLogger(__name__)

_ICON_PX = 64


class LinuxTray:
    """TrayBackend for Linux, backed by a PySide6 QSystemTrayIcon."""

    def __init__(self) -> None:
        # The Qt objects are typed ``Any`` on purpose: PySide6 is imported lazily
        # inside run(), so naming QApplication/QSystemTrayIcon here would drag the
        # import back to module scope and break importing this module without it.
        self._app: Any = None
        self._tray: Any = None
        self._bridge: Any = None  # QObject carrying a thread-safe state Signal
        self._latest: dict = {}
        self._lock = threading.Lock()
        self._controller: TrayController | None = None

    # ---- TrayBackend protocol ---------------------------------------------

    def run(self, on_quit: Callable[[], None]) -> None:
        try:
            from PySide6.QtCore import QObject, Signal
            from PySide6.QtWidgets import QApplication, QSystemTrayIcon
        except ImportError as exc:  # pragma: no cover - PySide6 is a base dep
            raise RuntimeError(
                "The tray needs PySide6. Install it with `uv sync --extra overlay` "
                "(or pip install 'yazses[overlay]'), or run the daemon without the tray."
            ) from exc

        from yazses.platform import get_platform
        from yazses.tray.controller import TrayController

        platform = get_platform()
        client = platform.ipc_client_factory(platform.paths.ipc_socket)
        self._controller = TrayController(client)

        self._app = QApplication.instance() or QApplication([])
        self._app.setQuitOnLastWindowClosed(False)  # menu closing must not exit

        if not QSystemTrayIcon.isSystemTrayAvailable():
            # No SNI/AppIndicator host (e.g. plain GNOME without the extension).
            log.warning(
                "No system tray is available on this desktop; the tray icon can't show. "
                "On GNOME install/enable the AppIndicator extension."
            )
            return

        # Marshal work done off the GUI thread back onto it: state from the poller, and
        # the update check / install, which block on the network and must not run here.
        class _Bridge(QObject):
            changed = Signal(object)
            update_ready = Signal(object)
            notified = Signal(object)

        self._bridge = _Bridge()
        self._bridge.changed.connect(self._apply_model)
        self._bridge.update_ready.connect(self._show_update_result)
        self._bridge.notified.connect(lambda pair: self._notify(*pair))

        self._tray = QSystemTrayIcon()
        self._tray.setToolTip("YazSes")
        self._build_menu()
        with self._lock:
            self._apply_status(self._latest)  # reflect any state seen before run()
        self._tray.show()

        log.info("System-tray icon shown (QSystemTrayIcon).")
        self._app.exec()
        # "Quit tray" only exits the loop; the daemon is left running on purpose.

    def set_state(self, model: TrayModel) -> None:
        # Called from the poller thread. Stash a status-shaped dict and, once the Qt
        # bridge exists, hand it to the GUI thread via a queued signal.
        status = {
            "state": model.state.value if isinstance(model.state, TrayState) else model.state,
            "hotkey": model.hotkey,
            "model": model.model,
            "silent_streak": model.silent_streak,
            "target_ok": model.target_ok,
            "command_mode": model.command_mode,
            "audio_level": model.audio_level,
            "vad_threshold": model.vad_threshold,
        }
        with self._lock:
            self._latest.update(status)
            snap = dict(self._latest)
        if self._bridge is not None:
            self._bridge.changed.emit(snap)

    def notify(self, title: str, body: str) -> None:
        """Deliberately a no-op — on Linux the daemon already toasted directly.

        `system/notify.py` uses `notify-send`, which exists here, so the relay
        that feeds the Windows and macOS trays never fires on Linux. Showing
        anything would be a duplicate of a toast the user has already seen.
        Present rather than absent because `TrayBackend` is `runtime_checkable`,
        so a missing method makes `isinstance(tray, TrayBackend)` fail.
        """
        log.debug("Ignoring relayed notification on Linux (notify-send handled it).")

    def stop(self) -> None:
        if self._app is not None:
            try:
                self._app.quit()
            except Exception:
                log.exception("Tray stop raised")

    # ---- internals ---------------------------------------------------------

    def _apply_model(self, status: dict) -> None:
        """GUI-thread slot: refresh the icon/tooltip from a status snapshot."""
        self._apply_status(status)

    def _apply_status(self, status: dict) -> None:
        if self._tray is None:
            return
        from yazses.tray.menu import icon_spec

        color, tooltip = icon_spec(status)
        try:
            self._tray.setIcon(self._make_icon(color, status))
            self._tray.setToolTip(tooltip)
        except Exception:
            log.exception("Tray icon update failed")

    def _make_icon(self, color_hex: str, status: dict | None = None):
        """Draw the YazSes mark — a rounded badge in ``color_hex`` with a bold "Y".

        *status* is the live poll result, passed in rather than read from
        ``self._latest``: that cache is only refreshed when the context menu opens,
        so a level ring drawn from it would freeze at whatever was true the last time
        someone right-clicked.
        """
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap

        pm = QPixmap(_ICON_PX, _ICON_PX)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            # Rounded-square badge in the state colour (blue = working, red = idle/problem).
            p.setBrush(QBrush(QColor(color_hex)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawRoundedRect(QRectF(5, 5, _ICON_PX - 10, _ICON_PX - 10), 15.0, 15.0)
            # Bold white "Y" — the YazSes mark.
            font = QFont()
            font.setBold(True)
            font.setPixelSize(int(_ICON_PX * 0.62))
            p.setFont(font)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(0, 0, _ICON_PX, _ICON_PX), Qt.AlignmentFlag.AlignCenter, "Y")
            self._draw_level_ring(p, status or {}, QRectF, Qt, QColor)
        finally:
            p.end()
        return QIcon(pm)

    def _draw_level_ring(self, p, status: dict, QRectF, Qt, QColor) -> None:
        """Draw the live input-level ring, if there is one to draw.

        The badge colour says what YazSes is *doing*; this says whether the
        microphone is actually hearing you. They come apart precisely when it
        matters — a muted mic or a VAD threshold above your voice looks identical to
        working, right up until nothing is typed.

        The notch is the silence gate. Ring short of the notch means what you are
        saying will be discarded; past it, it will be transcribed.
        """
        from PySide6.QtGui import QPen

        from yazses.tray.menu import level_ring

        ring = level_ring(status)
        if not ring.show:
            return

        inset = 1.5
        box = QRectF(inset, inset, _ICON_PX - 2 * inset, _ICON_PX - 2 * inset)
        # Qt angles are sixteenths of a degree, anticlockwise from 3 o'clock. Start at
        # the top and sweep clockwise, which is how a level meter is read.
        start = 90 * 16
        span = -int(360 * 16 * ring.fraction)

        p.setBrush(Qt.BrushStyle.NoBrush)
        # Track: a faint full circle, so a short arc reads as "low" rather than as a
        # rendering glitch.
        p.setPen(QPen(QColor(255, 255, 255, 60), 3.0))
        p.drawArc(box, 0, 360 * 16)
        # The level itself. White above the gate, muted below it: below-gate is not an
        # error state (you may simply not be speaking yet), it is "this will not count".
        p.setPen(QPen(QColor("#ffffff") if ring.above_gate else QColor(255, 255, 255, 130), 3.0))
        p.drawArc(box, start, span)
        # The gate notch.
        p.setPen(QPen(QColor(0, 0, 0, 160), 2.0))
        p.drawArc(box, start - int(360 * 16 * ring.gate_fraction), -int(2.5 * 16))

    def _build_menu(self) -> None:
        """Attach a context menu that rebuilds itself each time it opens."""
        from PySide6.QtWidgets import QMenu

        menu = QMenu()
        menu.aboutToShow.connect(lambda: self._populate_menu(menu))
        self._populate_menu(menu)
        self._tray.setContextMenu(menu)

    def _populate_menu(self, menu) -> None:
        from PySide6.QtGui import QActionGroup

        from yazses.tray.about import help_links
        from yazses.tray.menu import (
            ABOUT_LABEL,
            HELP_LABEL,
            REPORT_BUG_LABEL,
            UPDATE_LABEL,
            build_menu_model,
        )

        menu.clear()
        ctrl = self._controller
        status = ctrl.status() if ctrl is not None else {}
        with self._lock:
            self._latest.update(status)
        devices = ctrl.list_devices() if ctrl is not None else []
        pinned = str(status.get("input_device") or "") if status.get("input_device") else ""
        # Prefer the configured pin over the live device name for the checkmark.
        from yazses.config import load_config
        from yazses.platform import get_platform

        try:
            pinned = (load_config(get_platform().paths.config_file).audio.device or "").strip()
        except Exception:
            pass
        model = build_menu_model(status, devices, pinned)

        header = menu.addAction(model.header)
        header.setEnabled(False)
        mic = menu.addAction(model.mic_line)
        mic.setEnabled(False)
        if model.warning:
            warn = menu.addAction(model.warning)
            warn.setEnabled(False)
        menu.addSeparator()

        # Microphone submenu: an exclusive radio group of devices + actions.
        mic_menu = menu.addMenu("Microphone")
        group = QActionGroup(mic_menu)
        group.setExclusive(True)
        for item in model.devices:
            act = mic_menu.addAction(item.label)
            act.setCheckable(True)
            act.setChecked(item.checked)
            group.addAction(act)
            act.triggered.connect(lambda _checked, d=item.device: self._on_pick_device(d))
        mic_menu.addSeparator()
        mic_menu.addAction("Re-calibrate mic level").triggered.connect(self._on_recalibrate)

        menu.addSeparator()
        menu.addAction("Restart daemon").triggered.connect(self._on_restart)
        menu.addAction("Stop daemon").triggered.connect(self._on_stop_daemon)
        menu.addSeparator()
        menu.addAction(model.settings_label).triggered.connect(self._on_settings)

        # Help / About / updates — the questions you have *at the icon*, where a terminal
        # (`yazses about`, `yazses update`) is exactly what you don't have to hand.
        help_menu = menu.addMenu(HELP_LABEL)
        for label, url in help_links():
            if label == REPORT_BUG_LABEL:
                help_menu.addSeparator()
            help_menu.addAction(label).triggered.connect(
                lambda _checked=False, u=url: self._on_open_url(u)
            )
        menu.addAction(ABOUT_LABEL).triggered.connect(self._on_about)
        menu.addAction(UPDATE_LABEL).triggered.connect(self._on_check_updates)

        menu.addSeparator()
        menu.addAction("Quit tray").triggered.connect(self._on_quit_tray)

    # ---- menu action handlers ---------------------------------------------

    def _notify(self, title: str, body: str) -> None:
        if self._tray is not None:
            try:
                self._tray.showMessage(title, body)
            except Exception:
                pass

    def _on_pick_device(self, device: str) -> None:
        if self._controller is None:
            return
        self._controller.pin(device)
        self._notify(
            "YazSes microphone",
            f"Pinned to '{device}'." if device else "Following the OS default input.",
        )

    def _on_recalibrate(self) -> None:
        if self._controller is None:
            return
        res = self._controller.recalibrate()
        if res.get("started"):
            self._notify("YazSes", "Re-calibrating — speak normally for a few seconds…")
        else:
            self._notify("YazSes", res.get("reason", "Could not re-calibrate right now."))

    def _on_restart(self) -> None:
        if self._controller is not None:
            ok = self._controller.restart()
            self._notify(
                "YazSes",
                "Restarting the daemon…" if ok
                else "Could not run `yazses restart` — is yazses on PATH?",
            )

    def _on_stop_daemon(self) -> None:
        if self._controller is not None:
            self._controller.stop_daemon()
            self._notify("YazSes", "Stopping the daemon…")

    def _on_settings(self) -> None:
        # Opening a window is the one menu action with no visible effect of its own if
        # the launch fails, so say so rather than leaving the click looking ignored.
        if self._controller is not None and not self._controller.launch_settings():
            self._notify(
                "YazSes", "Could not open Settings — is `yazses` on PATH?"
            )

    def _brand_icon(self):
        """The YazSes mark in the brand colour, for dialog windows."""
        from yazses import branding

        return self._make_icon("#%02x%02x%02x" % branding.BRAND_TOP)

    def _dialog(self, title: str, text: str, *, rich: bool = False,
                accept_label: str | None = None) -> bool:
        """Show a modal dialog. Returns True only when ``accept_label`` was clicked.

        Falls back to a tray notification if Qt's dialogs are unavailable, so a click
        still says something rather than doing nothing visible.
        """
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QMessageBox
        except ImportError:  # pragma: no cover - PySide6 is a base dep
            self._notify(title, text)
            return False
        try:
            box = QMessageBox()
            box.setWindowTitle(title)
            box.setWindowIcon(self._brand_icon())
            box.setIconPixmap(self._brand_icon().pixmap(_ICON_PX, _ICON_PX))
            box.setText(text)
            if rich:
                # Rich text so the Website/Source/Issues URLs are clickable; the browser
                # interaction flag is what actually lets a click open them.
                box.setTextFormat(Qt.TextFormat.RichText)
                box.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            if accept_label:
                accept = box.addButton(accept_label, QMessageBox.ButtonRole.AcceptRole)
                box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
                box.exec()
                return box.clickedButton() is accept
            box.addButton(QMessageBox.StandardButton.Ok)
            box.exec()
            return False
        except Exception:
            log.exception("Tray dialog failed")
            self._notify(title, text)
            return False

    def _on_open_url(self, url: str) -> None:
        if self._controller is not None and not self._controller.open_url(url):
            self._notify("YazSes", f"Could not open your browser. The link is:\n{url}")

    def _on_about(self) -> None:
        from yazses.tray.about import about_html, about_title

        self._dialog(about_title(), about_html(), rich=True)

    def _on_check_updates(self) -> None:
        """Check for a newer release — on a worker thread, never on the Qt loop.

        The check reaches PyPI (5 s timeout) or shells ``snap info`` (10 s). Running that
        inline would freeze the menu and the icon for as long as it takes, which on a slow
        or captive network looks exactly like a crashed tray.
        """
        ctrl = self._controller
        if ctrl is None:
            return
        self._notify("YazSes", "Checking for updates…")

        def _work() -> None:
            status = ctrl.check_updates()
            bridge = self._bridge
            if bridge is not None:
                bridge.update_ready.emit(status)

        threading.Thread(target=_work, name="tray-update-check", daemon=True).start()

    def _show_update_result(self, status) -> None:
        """GUI-thread slot: report the check, and offer the install when we can run it."""
        from yazses.tray.about import needs_terminal, update_message, upgrade_result_message

        title, body = update_message(status)
        offerable = bool(status.available and status.command) and not needs_terminal(status)
        accepted = self._dialog(
            title, body, accept_label="Install now" if offerable else None
        )
        # Both conditions, not just the dialog's answer: nothing may install unless there
        # was an install to offer *and* the user clicked it.
        ctrl = self._controller
        if not (offerable and accepted) or ctrl is None:
            return
        self._notify("YazSes", "Installing the update…")

        def _work() -> None:
            outcome = ctrl.install_update(status)
            bridge = self._bridge
            if bridge is not None:
                bridge.notified.emit(upgrade_result_message(outcome))

        threading.Thread(target=_work, name="tray-update-install", daemon=True).start()

    def _on_quit_tray(self) -> None:
        # Close the tray only; leave the daemon running.
        if self._tray is not None:
            self._tray.hide()
        if self._app is not None:
            self._app.quit()
