"""BrainFlow activation source — OpenBCI, Muse, and friends (#103).

The serial YESP path stays the DIY reference (MyoWare 2.0, BioAmp EXG Pill, any
microcontroller). This adds hardware people can actually buy, through BrainFlow —
MIT, offline, Linux-native, and one API across a long list of boards.

The API used here was read from the published wheel, not assumed:
`BoardShim(board_id, BrainFlowInputParams())`, `prepare_session`, `start_stream`,
`get_current_board_data`, `stop_stream`, `release_session`, plus the static
`get_emg_channels` / `get_sampling_rate`. Every one of them is mocked in the
tests by a fake board, so the state machine is exercised without hardware.

**A missing device or dependency is a logged no-op, never a crash** — the same
guarantee the serial backend already gives. A dictation daemon that dies because
an optional armband is unplugged is worse than one that simply does not have the
armband.

Graded squeeze semantics live in `pressure.py`; this module only turns board
samples into envelope readings and feeds them there, so the interesting logic
stays testable without BrainFlow installed at all.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import numpy as np

from yazses.platform.emg.pressure import (
    GradedSqueeze,
    PressureThresholds,
    SqueezeLevel,
    envelope,
)

log = logging.getLogger(__name__)

# BrainFlow's own synthetic board, so `yazses doctor` and a curious user can
# exercise the path with no hardware at all.
SYNTHETIC_BOARD_ID = -1

_POLL_SECONDS = 0.02       # 50 Hz decision rate: well inside the 35–125 ms onset window


class BrainFlowSource:
    """Activation source over a BrainFlow board.

    `on_mode_start(mode)` fires when a squeeze crosses into a level that owns a
    mode; `on_mode_end()` fires when it relaxes. That shape matches the command
    key's callbacks, so `core/daemon.py` needs no new concept to wire it.
    """

    def __init__(
        self,
        board_id: int,
        thresholds: PressureThresholds,
        on_mode_start: Callable[[str], None],
        on_mode_end: Callable[[], None],
        *,
        serial_port: str = "",
        board_factory: Callable | None = None,
    ) -> None:
        self._board_id = int(board_id)
        self._serial_port = serial_port
        self._squeeze = GradedSqueeze(thresholds)
        self._on_start, self._on_end = on_mode_start, on_mode_end
        # Injected so tests drive a fake board; production passes None.
        self._board_factory = board_factory
        self._stop = threading.Event()
        self._board = None

    # ---- lifecycle -------------------------------------------------------

    def run(self) -> None:
        """Stream until `stop()`. Any failure is logged and ends the source."""
        board = self._open()
        if board is None:
            return
        self._board = board
        try:
            channels = self._emg_channels()
            while not self._stop.is_set():
                data = board.get_current_board_data(64)
                self._consume(data, channels)
                self._stop.wait(_POLL_SECONDS)
        except Exception:
            log.warning("BrainFlow source stopped after an error; "
                        "dictation continues without it.", exc_info=True)
        finally:
            self._close(board)

    def stop(self) -> None:
        self._stop.set()

    # ---- internals -------------------------------------------------------

    def _open(self):
        """Prepare and start a board, or None with the reason logged."""
        try:
            if self._board_factory is not None:
                board = self._board_factory()
            else:
                from brainflow.board_shim import BoardShim, BrainFlowInputParams

                params = BrainFlowInputParams()
                if self._serial_port:
                    params.serial_port = self._serial_port
                board = BoardShim(self._board_id, params)
            board.prepare_session()
            board.start_stream()
            log.info("BrainFlow activation source streaming (board %s).", self._board_id)
            return board
        except ModuleNotFoundError:
            log.info("BrainFlow not installed — EMG band source disabled. "
                     "Fix: yazses features enable emg-band")
        except Exception as exc:
            # An unplugged or busy device is the common case, not an error worth
            # taking the daemon down for.
            log.warning("BrainFlow board %s unavailable (%s); continuing without it.",
                        self._board_id, exc)
        return None

    @staticmethod
    def _close(board) -> None:
        for step in ("stop_stream", "release_session"):
            try:
                getattr(board, step)()
            except Exception:  # pragma: no cover - teardown is best effort
                log.debug("BrainFlow %s failed", step, exc_info=True)

    def _emg_channels(self) -> list[int]:
        """EMG channel indices for this board, falling back to all rows."""
        try:
            from brainflow.board_shim import BoardShim

            channels = list(BoardShim.get_emg_channels(self._board_id))
            if channels:
                return channels
        except Exception:
            log.debug("no EMG channel map for board %s", self._board_id, exc_info=True)
        return []

    def _consume(self, data, channels: list[int]) -> None:
        """Turn one chunk of board data into at most one mode transition."""
        array = np.asarray(data)
        if array.size == 0:
            return
        if array.ndim == 2:
            rows = channels or list(range(array.shape[0]))
            usable = [r for r in rows if r < array.shape[0]]
            if not usable:
                return
            signal = np.mean(array[usable, :], axis=0)
        else:
            signal = array
        changed = self._squeeze.update(envelope(signal))
        if changed is None:
            return
        if changed is SqueezeLevel.RELAXED:
            self._on_end()
        else:
            mode = self._squeeze.mode
            if mode:
                self._on_start(mode)
