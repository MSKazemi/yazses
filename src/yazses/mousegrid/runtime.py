"""The voice mouse grid's consumer: grammar → session → pointer sink — ADR-v2-030.

The daemon builds one :class:`MousegridRuntime` only when ``[mousegrid] enabled`` is true
and hands it every finished transcript through :meth:`MousegridRuntime.handle_transcript`.
The runtime answers one question — *is this utterance the grid's?* — and, when it is, does
what it says:

* closed grid: only the whole utterance "mouse grid" is claimed; it opens a grid over the
  primary display (or the screen the overlay reported, see :meth:`MousegridRuntime.command`);
* open grid: a cell number moves the pointer to that cell's centre (the pointer itself is
  the feedback, so the grid is usable even with the overlay off), ``click`` clicks there and
  closes, ``back`` zooms out, ``cancel`` closes. Any *other* utterance closes the grid and is
  **not** claimed, so it is dictated as usual — the grid never swallows speech it did not
  understand.

Pointer output goes through :class:`yazses.pointer.base.PointerSink`. The sink is built when
the user first opens a grid, not at start-up, so enabling the feature asks for no pointer
permission until then. Absolute motion is required: a backend that offers only relative
motion (the Wayland portal, Windows SendInput) is refused with a reason *at open*, before a
grid is drawn, rather than driven by guesswork.

Thread safety: the daemon's pipeline thread (transcripts) and the IPC server's per-connection
threads (the overlay polls ``status`` about 12 times a second) share one runtime, so every
public entry point holds one re-entrant lock and the session is never seen half-changed.

Safety: the hands-free global pause (``[handsfree_safety]``) is honoured before every
pointer action, the same way the Head-Pointer honours it. A click never happens before at
least one cell was chosen.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from yazses.mousegrid.grammar import MAX_NUMBER_WORD, is_open_phrase, parse_open_command
from yazses.mousegrid.session import GridSession, Step
from yazses.pointer.base import PointerButton, PointerError

log = logging.getLogger(__name__)

__all__ = ["MousegridRuntime", "build_mousegrid", "primary_display_region"]

Region = tuple[float, float, float, float]


def primary_display_region() -> Region | None:
    """The primary display's rectangle from the live X11 topology, or None.

    None off X11, without ``xrandr``, or when the layout cannot be read; the grid then
    falls back to the screen the overlay reported, and refuses to open if there is none.
    Imported lazily: :mod:`yazses.gaze.display` is only needed once a grid is opened.
    """
    try:
        from yazses.gaze.display import build_topology_provider

        provider = build_topology_provider()
        if provider is None:
            return None
        primary = provider.current_topology().primary
    except Exception:  # noqa: BLE001 - an unreadable layout means "unknown", never a crash
        log.debug("mouse grid: reading the display topology failed", exc_info=True)
        return None
    if primary is None:
        return None
    return (float(primary.x), float(primary.y), float(primary.width), float(primary.height))


class MousegridRuntime:
    """One grid session bound to a pointer sink and a screen-region source."""

    def __init__(
        self,
        cols: int = 3,
        rows: int = 3,
        *,
        sink_factory: Callable[[], Any] | None,
        region_provider: Callable[[], Region | None] | None = None,
        paused: Callable[[], bool] = lambda: False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._session = GridSession(cols, rows, clock=clock)
        self._sink_factory = sink_factory
        # Looked up at call time when not injected, so a test can patch the module function.
        self._region_provider = region_provider or (lambda: primary_display_region())
        self._paused = paused
        self._sink: Any = None
        #: Set once the pointer backend is known not to work for the grid; permanent.
        self._unavailable = "" if sink_factory is not None else (
            "this platform has no pointer backend"
        )
        self._reported_region: Region | None = None
        self.last_reason = ""
        # Re-entrant: command("say") and command("open") call back into the public methods.
        self._lock = threading.RLock()

    # ---- transcript path ----------------------------------------------------

    @property
    def active(self) -> bool:
        with self._lock:
            return self._session.active

    def handle_transcript(self, text: str) -> str | None:
        """Claim *text* for the grid, act on it, and return what happened — or None.

        None means "not the grid's": the daemon carries on and dictates or classifies the
        utterance exactly as it would without this feature.
        """
        with self._lock:
            return self._handle_transcript(text)

    def _handle_transcript(self, text: str) -> str | None:
        if not self._session.active:
            if not is_open_phrase(text):
                return None
            return self._open()
        if is_open_phrase(text):
            return self._open()  # "mouse grid" again restarts from the whole screen
        command = parse_open_command(text, self._session.cell_count)
        if command is None:
            self._session.close()
            log.info("Mouse grid: closed by an utterance that is not a grid command; "
                     "it is handled as ordinary speech.")
            return None
        step = self._session.apply(command)
        return self._perform(step)

    # ---- actions ------------------------------------------------------------

    def _refuse(self, reason: str) -> str:
        self.last_reason = reason
        log.info("Mouse grid: %s.", reason)
        return "refused"

    def _open(self) -> str:
        if self._paused():
            self._session.close()
            return self._refuse("hands-free input is paused, so the grid did not open")
        if self._unavailable:
            return self._refuse(f"cannot drive the pointer: {self._unavailable}")
        region = self._region_provider() or self._reported_region
        if region is None:
            return self._refuse("the screen size is unknown on this session, so the grid "
                                "did not open (it reads the X11 layout or the overlay's screen)")
        # Probe the pointer backend now, so a relative-only one (Wayland, Windows) is refused
        # before any grid is drawn — not at the first cell number.
        if self._ensure_sink() is None:
            self._session.close()
            return self._refuse(f"cannot drive the pointer: {self._unavailable}")
        try:
            self._session.open(region)
        except ValueError as exc:
            return self._refuse(f"bad screen region ({exc})")
        self.last_reason = ""
        log.info("Mouse grid: opened (%dx%d).", self._session.cols, self._session.rows)
        return "opened"

    def _ensure_sink(self) -> Any:
        if self._sink is not None:
            return self._sink
        if self._sink_factory is None:
            return None
        try:
            sink = self._sink_factory()
            caps = sink.capabilities()
        except Exception as exc:  # noqa: BLE001 - a backend that will not start is a reason
            self._unavailable = f"the pointer backend failed to start ({type(exc).__name__})"
            return None
        if not caps.absolute_motion:
            try:
                sink.close()
            except Exception:  # noqa: BLE001
                log.debug("mouse grid: closing a refused sink failed", exc_info=True)
            self._unavailable = (
                f"the {caps.backend!r} pointer backend cannot move to a position "
                "(the grid needs absolute motion: X11 or macOS)"
            )
            return None
        self._sink = sink
        return sink

    def _perform(self, step: Step) -> str:
        if step.kind == "refused":
            return self._refuse(step.reason)
        if step.kind == "close":
            self.last_reason = ""
            log.info("Mouse grid: cancelled.")
            return "cancelled"
        if self._paused():
            self._session.close()
            return self._refuse("hands-free input is paused, so the pointer was not moved")
        sink = self._ensure_sink()
        if sink is None:
            self._session.close()
            return self._refuse(f"cannot drive the pointer: {self._unavailable}")
        if step.point is None:  # pragma: no cover - a move/click always carries a point
            return self._refuse("the grid produced no point")
        x, y = step.point
        try:
            sink.move_absolute(x, y)
            if step.kind == "click":
                button = PointerButton(step.button)
                for _ in range(max(1, step.count)):
                    sink.click(button)
        except (PointerError, ValueError) as exc:
            self._session.close()
            return self._refuse(f"the pointer refused the action ({type(exc).__name__})")
        self.last_reason = ""
        if step.kind == "click":
            log.info("Mouse grid: %s click x%d; grid closed.", step.button, step.count)
            return "clicked"
        return "moved"

    # ---- IPC ----------------------------------------------------------------

    def status(self) -> dict[str, object]:
        with self._lock:
            return self._status()

    def _status(self) -> dict[str, object]:
        out = self._session.status()
        out["enabled"] = True
        out["available"] = not self._unavailable
        out["reason"] = self._unavailable or self.last_reason
        out["screen_reported"] = self._reported_region is not None
        return out

    def command(self, action: str, params: dict[str, Any] | None = None) -> dict[str, object]:
        """IPC: ``status`` | ``open`` | ``say`` | ``cancel`` | ``screen``.

        ``screen`` records the overlay's screen rectangle (``region: [x, y, w, h]``) as the
        fallback where the X11 layout cannot be read. ``say`` runs ``text`` through the same
        grammar as a spoken utterance, so a script or test can drive the grid exactly as a
        voice would.
        """
        with self._lock:
            return self._command(action, params or {})

    def _command(self, action: str, params: dict[str, Any]) -> dict[str, object]:
        if action == "status":
            return {"ok": True, **self.status()}
        if action == "screen":
            region = _parse_region(params.get("region"))
            if region is None:
                return {"ok": False, "reason": "region must be four numbers with a positive size"}
            self._reported_region = region
            return {"ok": True}
        if action == "open":
            result = self._open()
            return {"ok": result == "opened", "result": result, **self.status()}
        if action == "cancel":
            self._session.close()
            return {"ok": True, **self.status()}
        if action == "say":
            said = self.handle_transcript(str(params.get("text", "")))
            return {"ok": said not in (None, "refused"), "result": said, **self.status()}
        return {"ok": False, "reason": f"unknown mousegrid action {action!r}"}

    def close(self) -> None:
        with self._lock:
            self._session.close()
            sink, self._sink = self._sink, None
        if sink is not None:
            try:
                sink.close()
            except Exception:  # noqa: BLE001
                log.debug("mouse grid: closing the pointer sink failed", exc_info=True)


def _parse_region(value: object) -> Region | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x, y, w, h = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not all(v == v and abs(v) != float("inf") for v in (x, y, w, h)) or w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


def build_mousegrid(cfg: Any, *, pointer_factory: Callable[[], Any] | None,
                    safety: Any = None) -> MousegridRuntime:
    """The daemon's runtime for an enabled ``[mousegrid]`` section. Never opens a sink."""

    def paused() -> bool:
        if safety is None:
            return False
        try:
            status = safety.status()
        except Exception:  # noqa: BLE001 - an unreadable gate must not unlock the pointer
            return True
        return bool(status.user_paused or status.terminal)

    cols = int(cfg.cols) if int(cfg.cols) > 0 else 3
    rows = int(cfg.rows) if int(cfg.rows) > 0 else 3
    if cols * rows > MAX_NUMBER_WORD:
        log.warning("Mouse grid: a %dx%d grid has %d cells, but number words stop at %s; "
                    "say cells above %d as digits (\"17\"), or a spoken word closes the grid "
                    "and is typed.", cols, rows, cols * rows, MAX_NUMBER_WORD,
                    MAX_NUMBER_WORD)
    return MousegridRuntime(cols, rows, sink_factory=pointer_factory, paused=paused)
