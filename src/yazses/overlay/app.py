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
from yazses.overlay.motion import (
    band,
    detect_os_preference,
    resolve_reduced_motion,
    steady_ripples,
)
from yazses.overlay.poller import StatusPoller, StatusSnapshot
from yazses.overlay.position import place_centered, place_fixed, place_near_cursor

log = logging.getLogger(__name__)

_MISSING_PYSIDE_MSG = "The overlay needs PySide6, which is not installed."


def _missing_pyside_message() -> str:
    """:data:`_MISSING_PYSIDE_MSG` plus the install command for *this* install.

    It was a hard-coded ``uv sync`` of the overlay extra, which does nothing outside
    a source checkout; ``system/remedy.py`` derives the command instead.
    """
    try:
        from yazses.system.remedy import install_hint

        hint = install_hint("desktop", feature="overlay")
    except Exception:  # noqa: BLE001 - the refusal must reach the log regardless
        hint = ""
    return f"{_MISSING_PYSIDE_MSG} {hint}" if hint else _MISSING_PYSIDE_MSG

# State-only mode shows a steady, strong pulse while recording.
_STATE_ONLY_INTENSITY = 0.8


@dataclass(frozen=True)
class Frame:
    """The render decision for one tick — what the Qt layer should do."""

    ripples: list[Ripple]
    intensity: float
    visible: bool
    top_left: tuple[int, int] | None
    #: 0..1 fraction of a Head-Pointer dwell-click that has elapsed; 0 draws no ring.
    dwell_progress: float = 0.0


def compute_frame(
    snap: StatusSnapshot,
    cfg: OverlayConfig,
    envelope: EnvelopeFollower,
    model: SonarModel,
    now: float,
    cursor: tuple[int, int],
    screen: tuple[int, int, int, int],
    reduced_motion: bool = False,
) -> Frame:
    """Advance the animation one tick and decide where/whether to draw.

    Pure: it mutates the supplied ``envelope``/``model`` (which carry the
    animation's state) but touches no Qt and reads no globals, so it is fully
    unit-testable.

    ``reduced_motion`` is resolved once at startup rather than read here, because
    answering it means asking the desktop's settings daemon and this runs sixty
    times a second.
    """
    # Vocal Morse mode listens with the daemon IDLE; its rings follow the hums as they
    # follow speech while recording, which is how the user sees the mode is on.
    recording = snap.state == "recording" or snap.morse_active
    envelope.threshold = snap.vad_threshold

    if recording and cfg.react_to_voice:
        intensity = envelope.update(snap.audio_level)
    elif recording:
        intensity = _STATE_ONLY_INTENSITY
    else:
        intensity = envelope.update(0.0)  # decay toward silence after release

    if reduced_motion:
        # No travelling rings at all, so the model is never advanced and never
        # accumulates births. While recording there is always exactly one ring,
        # including in silence -- the animated form shows nothing then, which is
        # tolerable when rings are about to appear and not when none ever will.
        ripples = steady_ripples(intensity) if recording else []
        # The widget sizes its centre glow from this, so it has to be banded too
        # or the rings stop moving while the core keeps breathing at 60 fps.
        intensity = band(intensity)
    else:
        ripples = model.tick(now, intensity)

    dwell = snap.dwell_progress if snap.dwell_progress > 0.0 else 0.0

    # Nothing to show: not recording, the last rings have faded, no click is coming.
    if not recording and not ripples and dwell == 0.0:
        return Frame(ripples=[], intensity=intensity, visible=False, top_left=None)

    if dwell > 0.0:
        # The warning belongs around the pointer it is about to click with, wherever the
        # voice rings are configured to sit.
        top_left = place_centered(cursor, cfg.size_px, screen)
    elif cfg.position == "cursor":
        top_left = place_near_cursor(cursor, cfg.size_px, screen, cfg.cursor_offset_px)
    else:
        top_left = place_fixed(cfg.position, cfg.size_px, screen)
    return Frame(
        ripples=ripples, intensity=intensity, visible=True, top_left=top_left,
        dwell_progress=dwell,
    )


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
        log.error(_missing_pyside_message())
        sys.exit(1)

    from yazses.platform import get_platform

    full_cfg = load_config()
    cfg = full_cfg.overlay
    platform = get_platform()
    client = platform.ipc_client_factory(platform.paths.ipc_socket)

    poller = StatusPoller(client)
    poller.start()

    app = QApplication.instance() or QApplication(sys.argv)
    widget = SonarWidget(cfg.size_px, cfg.accent)
    envelope = EnvelopeFollower()
    model = SonarModel()
    reduced_motion = resolve_reduced_motion(cfg.reduced_motion, detect_os_preference())

    def _screen_rect() -> tuple[int, int, int, int]:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        geo = screen.geometry()
        return geo.x(), geo.y(), geo.width(), geo.height()

    # Voice Mouse Grid (ADR-v2-030): a second click-through window for the numbered cells,
    # and its own poller. Built only when `[mousegrid] enabled`, so an overlay without the
    # feature imports nothing more and sends the same IPC it always did.
    grid_poller = None
    grid_widget = None
    if full_cfg.mousegrid.enabled:
        from yazses.overlay.grid import GridPoller
        from yazses.overlay.grid_widget import GridWidget

        primary = QGuiApplication.primaryScreen().geometry()
        grid_poller = GridPoller(
            client, (primary.x(), primary.y(), primary.width(), primary.height())
        )
        grid_poller.start()
        grid_widget = GridWidget(cfg.accent)

    # Mouth-Sound Switch (ADR-v2-097): the scan strip, drawn from the `mouthswitch` block of
    # the `status` reply the poller above already fetches -- no IPC of its own. Built only
    # when `[mouthswitch] enabled`, so an overlay without the feature imports nothing more.
    scan_widget = None
    if full_cfg.mouthswitch.enabled:
        from yazses.overlay.scan_widget import ScanWidget

        scan_widget = ScanWidget(cfg.accent)

    def _tick() -> None:
        if grid_widget is not None and grid_poller is not None:
            grid_widget.show_grid(grid_poller.latest())
        snap = poller.latest()
        if scan_widget is not None:
            primary = QGuiApplication.primaryScreen().geometry()
            scan_widget.show_scan(
                snap.scan_items, snap.scan_index,
                (primary.x(), primary.y(), primary.width(), primary.height()),
            )
        cursor = QCursor.pos()
        frame = compute_frame(
            snap,
            cfg,
            envelope,
            model,
            time.monotonic(),
            (cursor.x(), cursor.y()),
            _screen_rect(),
            reduced_motion,
        )
        if not frame.visible:
            if widget.isVisible():
                widget.hide()
            return
        widget.set_ripples(frame.ripples, frame.intensity)
        widget.set_dwell(frame.dwell_progress)
        if frame.top_left is not None:
            widget.move_to(frame.top_left)
        if not widget.isVisible():
            widget.show()

    timer = QTimer()
    timer.timeout.connect(_tick)
    timer.start(max(1, int(1000 / max(1, cfg.fps))))

    log.info(
        "YazSes overlay running (style=%s, position=%s, reduced_motion=%s).",
        cfg.style, cfg.position, reduced_motion,
    )
    try:
        app.exec()
    finally:
        poller.stop()
        if grid_poller is not None:
            grid_poller.stop()


if __name__ == "__main__":
    run()
