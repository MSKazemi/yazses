"""AT-SPI accessibility backend: read the focused window, act on one node (#164).

The Linux implementation of ``platform.base.AccessibilityBackend``, and the producer
Screen-Grounded Dictation (ADR-v2-051) and the Voice Pilot (ADR-v2-007) both use.

``pyatspi`` comes from the OS package manager (``apt install python3-pyatspi
gir1.2-atspi-2.0``), never PyPI -- the same binding the no-text-target guard
(``inject/target.py``) and Session Bookmarks (``bookmarks/atspi.py``) already use. It is
imported lazily, inside the methods, and every failure answers "nothing" rather than
raising. Works on X11 and on Wayland desktops that run the accessibility bus (GNOME,
KDE): AT-SPI is a D-Bus service, not an X extension, and only its *coordinates* are
unreliable on Wayland -- this backend reads none.

What it reads, and what it refuses to:

* The **active window** only (the top-level whose state includes ``ACTIVE``), never
  every window on the desktop.
* Each node's accessible **name**, **role**, the names of its **actions**, and whether
  it is **showing**. Text *content* is read only for a node with no name, and never from
  a password field or an editable field -- a secret typed into one must not be able to
  reach a prompt, a match or a notification.
* Bounded by ``grounding/treewalk.py`` (nodes, depth, time) and, around that, by the
  caller's wall-clock deadline (``grounding/onscreen.py``).

Nothing is logged except counts: a label is what the user can see on screen, which is
user content, and it never goes into a log line, an event or a file.

Imported only by ``build_atspi_accessibility`` in ``platform/linux/accessibility.py``, on
a consumer's first use -- never by ``build_platform`` -- because it pulls in the
``grounding`` package, which a default start must not load.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable, Iterable
from itertools import islice
from typing import Any

from yazses.grounding.contracts import SemanticCandidate
from yazses.grounding.treewalk import NodeFacts, TreeLimits, walk

log = logging.getLogger(__name__)

#: Roles whose text content is never read, whatever else is true of the node. A password
#: field for the obvious reason; a terminal because its Text interface is the whole
#: scrollback, not what is on screen, and a token printed an hour ago is still in it.
_SECRET_ROLES = frozenset({"password text", "terminal"})

#: How many of a node's actions are listed. Real widgets expose one to three.
_MAX_ACTIONS = 8

#: How many applications, and windows per application, are looked at to find the
#: active window. A desktop with more than this is not one this feature serves well.
_MAX_APPS = 128
_MAX_WINDOWS = 32

#: The pseudo-action that means "give this node keyboard focus" (Component.grabFocus).
FOCUS_ACTION = "focus"


def _state_has(state: Any, mod: Any, name: str) -> bool:
    flag = getattr(mod, name, None)
    if flag is None:
        return False
    try:
        return bool(state.contains(flag))
    except Exception:
        return False


class PyatspiOps:
    """``grounding.treewalk.NodeOps`` over ``pyatspi`` nodes. *mod* is the module (or a fake)."""

    def __init__(self, mod: Any) -> None:
        self._mod = mod

    def facts(self, node: Any, limits: TreeLimits) -> NodeFacts | None:
        mod = self._mod
        try:
            state = node.getState()
        except Exception:
            return None  # a node that vanished mid-walk
        showing = _state_has(state, mod, "STATE_SHOWING")
        if not showing:
            # Nothing else is read: the walk skips this node and its subtree.
            return NodeFacts(showing=False)
        try:
            role = str(node.getRoleName() or "")
        except Exception:
            role = ""
        try:
            name = str(node.name or "")
        except Exception:
            name = ""
        actions = self._actions(node)
        if _state_has(state, mod, "STATE_FOCUSABLE") and FOCUS_ACTION not in actions:
            actions = (*actions, FOCUS_ACTION)
        text = ""
        if (
            not name.strip()
            and role.strip().lower() not in _SECRET_ROLES
            and not _state_has(state, mod, "STATE_EDITABLE")
        ):
            text = self._text(node, limits.max_text_chars)
        return NodeFacts(name=name, role=role, showing=True, actions=actions, text=text)

    def children(self, node: Any) -> Iterable[Any]:
        try:
            count = int(node.childCount)
        except Exception:
            return
        for index in range(max(count, 0)):
            try:
                yield node.getChildAtIndex(index)
            except Exception:
                continue

    @staticmethod
    def _actions(node: Any) -> tuple[str, ...]:
        try:
            action = node.queryAction()
        except Exception:
            return ()  # the node implements no Action interface
        names: list[str] = []
        try:
            count = min(int(action.nActions), _MAX_ACTIONS)
        except Exception:
            return ()
        for index in range(max(count, 0)):
            try:
                label = str(action.getName(index) or "").strip().lower()
            except Exception:
                continue
            if label and label not in names:
                names.append(label)
        return tuple(names)

    @staticmethod
    def _text(node: Any, max_chars: int) -> str:
        try:
            text = node.queryText()
        except Exception:
            return ""
        try:
            count = min(int(text.characterCount), max_chars)
            return str(text.getText(0, count) or "") if count > 0 else ""
        except Exception:
            return ""


def _active_window(mod: Any) -> Any | None:
    """The desktop's active top-level window, or ``None``. Bounded; never raises."""
    try:
        desktop = mod.Registry.getDesktop(0)
    except Exception:
        return None
    ops = PyatspiOps(mod)
    for app in islice(ops.children(desktop), _MAX_APPS):
        if app is None:
            continue
        for window in islice(ops.children(app), _MAX_WINDOWS):
            if window is None:
                continue
            try:
                if _state_has(window.getState(), mod, "STATE_ACTIVE"):
                    return window
            except Exception:
                continue
    return None


class AtspiAccessibility:
    """``AccessibilityBackend`` over AT-SPI. One instance per consumer; see `snapshot`."""

    def __init__(
        self,
        limits: TreeLimits | None = None,
        *,
        atspi: Any = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limits = limits or TreeLimits()
        self._injected = atspi
        self._clock = clock
        self._handles: dict[str, Any] = {}
        self._generation = 0
        self._lock = threading.Lock()

    def _module(self) -> Any | None:
        if self._injected is not None:
            return self._injected
        try:
            import pyatspi
        except Exception:
            return None
        return pyatspi

    def snapshot(
        self,
        *,
        window_id: str | None = None,
        region: Any = None,
    ) -> tuple[SemanticCandidate, ...]:
        """The active window's labelled, showing nodes, in reading order.

        Only the focused window is answered. A request for a specific *window_id* or a
        *region* returns nothing rather than the focused window's nodes, because a
        caller that asked about somewhere else must not be handed a plausible answer
        about here (ADR-v2-151's abstention rule).

        Replaces the handle map, and every snapshot numbers its ids under a fresh
        prefix, so an id from an earlier snapshot of this instance is unknown to
        `perform` -- never silently the id of some other node in the new one.
        """
        with self._lock:
            self._handles = {}
            self._generation += 1
            prefix = f"s{self._generation}n"
        if window_id is not None or region is not None:
            return ()
        mod = self._module()
        if mod is None:
            return ()
        root = _active_window(mod)
        if root is None:
            return ()
        result = walk(root, PyatspiOps(mod), self._limits,
                      clock=self._clock, captured_at_s=self._clock(), id_prefix=prefix)
        with self._lock:
            self._handles = dict(result.handles)
        # Counts and the stop reason only -- never a label.
        log.debug("AT-SPI snapshot: %d node(s) read, %d labelled%s.",
                  result.visited, len(result.candidates),
                  f", stopped at {result.stopped}" if result.stopped else "")
        return result.candidates

    def perform(self, entity_id: str, action: str) -> bool:
        """Run *action* on the node *entity_id* of the latest snapshot. False on any doubt."""
        with self._lock:
            node = self._handles.get(entity_id)
        if node is None or not action:
            return False
        wanted = action.strip().lower()
        try:
            if wanted == FOCUS_ACTION:
                return bool(node.queryComponent().grabFocus())
            iface = node.queryAction()
            count = min(int(iface.nActions), _MAX_ACTIONS)
            for index in range(max(count, 0)):
                if str(iface.getName(index) or "").strip().lower() == wanted:
                    return bool(iface.doAction(index))
        except Exception:
            log.debug("AT-SPI action failed", exc_info=True)
            return False
        return False


__all__ = ["FOCUS_ACTION", "AtspiAccessibility", "PyatspiOps"]
