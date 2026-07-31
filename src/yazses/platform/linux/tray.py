"""Linux system-tray indicator, built on PySide6 ``QSystemTrayIcon``.

A ``TrayBackend`` implementation (``run``/``set_state``/``stop``) driven by the generic
``yazses.tray.app`` runner: the app polls the daemon ``status`` on a worker thread and
calls ``set_state``; ``run`` owns the Qt event loop. PySide6 is already a base dependency
(the overlay uses it) so this adds nothing new.

The icon shows daemon state (and flags a live silent-streak in orange); the click-menu —
rebuilt fresh each time it opens — lets you pick/pin the input microphone, re-calibrate,
and restart/stop the daemon. On GNOME/AppIndicator the menu is the *primary* interaction
(shown on click via ``setContextMenu``); left-click activation isn't delivered there.

Unlike the macOS/Windows trays where quitting the tray stops the daemon, "Quit tray" here
only closes the icon — dictation keeps running; a separate "Stop daemon" item stops it.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from yazses.platform.base import TrayModel, TrayState

log = logging.getLogger(__name__)

_ICON_PX = 64


class LinuxTray:
    """TrayBackend for Linux, backed by a PySide6 QSystemTrayIcon."""

    def __init__(self) -> None:
        self._app = None
        self._tray = None
        self._bridge = None  # QObject carrying a thread-safe state Signal
        self._latest: dict = {}
        self._lock = threading.Lock()
        self._controller = None

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

        # Marshal set_state (called from the poller thread) onto the GUI thread.
        class _Bridge(QObject):
            changed = Signal(object)

        self._bridge = _Bridge()
        self._bridge.changed.connect(self._apply_model)

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
        }
        with self._lock:
            self._latest.update(status)
            snap = dict(self._latest)
        if self._bridge is not None:
            self._bridge.changed.emit(snap)

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
            self._tray.setIcon(self._make_icon(color))
            self._tray.setToolTip(tooltip)
        except Exception:
            log.exception("Tray icon update failed")

    def _make_icon(self, color_hex: str):
        """Draw the YazSes mark — a rounded badge in ``color_hex`` with a bold "Y"."""
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QBrush, QColor, QFont, QIcon, QPainter, QPixmap

        pm = QPixmap(_ICON_PX, _ICON_PX)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        try:
            p.setRenderHint(QPainter.Antialiasing)
            p.setRenderHint(QPainter.TextAntialiasing)
            # Rounded-square badge in the state colour (blue = working, red = idle/problem).
            p.setBrush(QBrush(QColor(color_hex)))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(5, 5, _ICON_PX - 10, _ICON_PX - 10), 15.0, 15.0)
            # Bold white "Y" — the YazSes mark.
            font = QFont()
            font.setBold(True)
            font.setPixelSize(int(_ICON_PX * 0.62))
            p.setFont(font)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(0, 0, _ICON_PX, _ICON_PX), Qt.AlignCenter, "Y")
        finally:
            p.end()
        return QIcon(pm)

    def _build_menu(self) -> None:
        """Attach a context menu that rebuilds itself each time it opens."""
        from PySide6.QtWidgets import QMenu

        menu = QMenu()
        menu.aboutToShow.connect(lambda: self._populate_menu(menu))
        self._populate_menu(menu)
        self._tray.setContextMenu(menu)

    def _populate_menu(self, menu) -> None:
        from PySide6.QtGui import QActionGroup

        from yazses.tray.menu import build_menu_model

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
            self._controller.restart()
            self._notify("YazSes", "Restarting the daemon…")

    def _on_stop_daemon(self) -> None:
        if self._controller is not None:
            self._controller.stop_daemon()
            self._notify("YazSes", "Stopping the daemon…")

    def _on_quit_tray(self) -> None:
        # Close the tray only; leave the daemon running.
        if self._tray is not None:
            self._tray.hide()
        if self._app is not None:
            self._app.quit()
