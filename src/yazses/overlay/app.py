"""``yazses-overlay`` entry point — the sonar overlay process.

Wires the pure logic to Qt: a render :class:`~PySide6.QtCore.QTimer` pulls the
latest daemon status from :class:`~yazses.overlay.poller.StatusPoller`, runs the
mic level through the :class:`~yazses.overlay.envelope.EnvelopeFollower` and
:class:`~yazses.overlay.animation.SonarModel`, and hands the resulting rings to
the :class:`~yazses.overlay.widget.SonarWidget`, repositioning it near the cursor
each frame. Runs as its own process because the daemon's main thread is owned by
the hotkey loop.

The per-frame decision (:func:`compute_frame`) is pure and unit-tested; ``run``
is the thin Qt shell around it.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass

from yazses.config import OverlayConfig, load_config
from yazses.overlay.animation import Ripple, SonarModel
from yazses.overlay.envelope import EnvelopeFollower
from yazses.overlay.poller import StatusPoller, StatusSnapshot
from yazses.overlay.position import place_fixed, place_near_cursor

log = logging.getLogger(__name__)

_MISSING_PYSIDE_MSG = (
    "The overlay needs PySide6. Install the extra:\n"
    "    uv sync --extra overlay      # or: pip install 'yazses[overlay]'"
)

# State-only mode shows a steady, strong pulse while recording.
_STATE_ONLY_INTENSITY = 0.8


@dataclass(frozen=True)
class Frame:
    """The render decision for one tick — what the Qt layer should do."""

    ripples: list[Ripple]
    intensity: float
    visible: bool
    top_left: tuple[int, int] | None


def compute_frame(
    snap: StatusSnapshot,
    cfg: OverlayConfig,
    envelope: EnvelopeFollower,
    model: SonarModel,
    now: float,
    cursor: tuple[int, int],
    screen: tuple[int, int, int, int],
) -> Frame:
    """Advance the animation one tick and decide where/whether to draw.

    Pure: it mutates the supplied ``envelope``/``model`` (which carry the
    animation's state) but touches no Qt and reads no globals, so it is fully
    unit-testable.
    """
    recording = snap.state == "recording"
    envelope.threshold = snap.vad_threshold

    if recording and cfg.react_to_voice:
        intensity = envelope.update(snap.audio_level)
    elif recording:
        intensity = _STATE_ONLY_INTENSITY
    else:
        intensity = envelope.update(0.0)  # decay toward silence after release

    ripples = model.tick(now, intensity)

    # Nothing to show: not recording and the last rings have faded.
    if not recording and not ripples:
        return Frame(ripples=[], intensity=intensity, visible=False, top_left=None)

    if cfg.position == "cursor":
        top_left = place_near_cursor(cursor, cfg.size_px, screen, cfg.cursor_offset_px)
    else:
        top_left = place_fixed(cfg.position, cfg.size_px, screen)
    return Frame(ripples=ripples, intensity=intensity, visible=True, top_left=top_left)


def run() -> None:  # pragma: no cover - thin Qt shell around compute_frame
    """GUI-script entry point for ``yazses-overlay``."""
    # No console on Windows for a GUI script, so sys.stderr is None and
    # basicConfig would raise on its first log line.
    from yazses.system.wincon import ensure_streams

    ensure_streams()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    try:
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QCursor, QGuiApplication
        from PySide6.QtWidgets import QApplication

        from yazses.overlay.widget import SonarWidget
    except ImportError:
        log.error(_MISSING_PYSIDE_MSG)
        sys.exit(1)

    from yazses.platform import get_platform

    cfg = load_config().overlay
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)

    poller = StatusPoller(client)
    poller.start()

    app = QApplication.instance() or QApplication(sys.argv)
    widget = SonarWidget(cfg.size_px, cfg.accent)
    envelope = EnvelopeFollower()
    model = SonarModel()

    def _screen_rect() -> tuple[int, int, int, int]:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.geometry()
        return geo.x(), geo.y(), geo.width(), geo.height()

    def _tick() -> None:
        cursor = QCursor.pos()
        frame = compute_frame(
            poller.latest(),
            cfg,
            envelope,
            model,
            time.monotonic(),
            (cursor.x(), cursor.y()),
            _screen_rect(),
        )
        if not frame.visible:
            if widget.isVisible():
                widget.hide()
            return
        widget.set_ripples(frame.ripples, frame.intensity)
        if frame.top_left is not None:
            widget.move_to(frame.top_left)
        if not widget.isVisible():
            widget.show()

    timer = QTimer()
    timer.timeout.connect(_tick)
    timer.start(max(1, int(1000 / max(1, cfg.fps))))

    log.info("YazSes overlay running (style=%s, position=%s).", cfg.style, cfg.position)
    try:
        app.exec()
    finally:
        poller.stop()


if __name__ == "__main__":
    run()
