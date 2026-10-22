"""The Linux AT-SPI accessibility backend and its registration (#164), over a fake pyatspi.

No accessibility bus, no desktop: ``AtspiAccessibility`` takes the ``pyatspi`` module as
an injected value, and the fake below implements exactly the slice it calls (Registry,
state sets, Action, Text, Component). What is pinned:

* **Only the active window is read**, and only what is showing in it.
* **Secrets are never read**: a password field's or a terminal's text, and any editable
  field's text, never reach a candidate -- the fake counts every ``queryText`` call.
* **``perform`` acts on exactly the node that was matched**, by its own action name, and
  refuses an id it does not know -- including one from an earlier snapshot.
* **Registration**: the Linux bundle offers the factory only with a desktop session and
  a locatable binding, and says why otherwise; building it opens nothing.
"""

from __future__ import annotations

import ast
import dataclasses
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from yazses.grounding.treewalk import TreeLimits
from yazses.platform.linux import accessibility
from yazses.platform.linux.accessibility import (
    ATSPI_MISSING_REASON,
    HEADLESS_ACCESSIBILITY_REASON,
    accessibility_route,
    build_atspi_accessibility,
)
from yazses.platform.linux.atspi_tree import FOCUS_ACTION, AtspiAccessibility

SHOWING, FOCUSABLE, EDITABLE, ACTIVE = "showing", "focusable", "editable", "active"


class States:
    def __init__(self, flags) -> None:
        self._flags = set(flags)

    def contains(self, flag) -> bool:
        return flag in self._flags


class Node:
    """One fake accessible. ``log`` collects every action, focus grab and text read."""

    def __init__(self, name="", role="push button", states=(SHOWING,), actions=(),
                 text=None, kids=(), log=None) -> None:
        self.name = name
        self._role = role
        self._states = states
        self._actions = list(actions)
        self._text = text
        self._kids = list(kids)
        self.log = log if log is not None else []
        if log is not None:
            self._share(log)

    def _share(self, log) -> None:
        """Give the whole subtree one log, so a test sees every read and action in it."""
        for kid in self._kids:
            kid.log = log
            kid._share(log)

    # tree
    def getRoleName(self):
        return self._role

    def getState(self):
        return States(self._states)

    @property
    def childCount(self):
        return len(self._kids)

    def getChildAtIndex(self, i):
        return self._kids[i]

    # interfaces
    def queryAction(self):
        if not self._actions:
            raise NotImplementedError("no Action interface")
        node = self

        class Action:
            nActions = len(node._actions)

            def getName(self, i):
                return node._actions[i]

            def doAction(self, i):
                node.log.append(("action", node.name, node._actions[i]))
                return True

        return Action()

    def queryText(self):
        self.log.append(("text-read", self.name, self._role))
        if self._text is None:
            raise NotImplementedError("no Text interface")
        text = self._text

        class Text:
            characterCount = len(text)

            def getText(self, start, end):
                return text[start:end]

        return Text()

    def queryComponent(self):
        node = self

        class Component:
            def grabFocus(self):
                node.log.append(("focus", node.name))
                return True

        return Component()


def _desktop(*apps):
    return Node("desktop", role="desktop frame", kids=list(apps))


def _module(desktop):
    return SimpleNamespace(
        STATE_SHOWING=SHOWING, STATE_FOCUSABLE=FOCUSABLE, STATE_EDITABLE=EDITABLE,
        STATE_ACTIVE=ACTIVE,
        Registry=SimpleNamespace(getDesktop=lambda _i: desktop),
    )


def _scene():
    log: list = []
    active = Node("Report.odt - Writer", role="frame", states=(SHOWING, ACTIVE), kids=[
        Node("Save", actions=("Click",), states=(SHOWING, FOCUSABLE)),
        Node("Delete", actions=("press",)),
        Node("Hidden menu", states=(), kids=[Node("Never seen", actions=("click",))]),
        Node("", role="paragraph", text="Dear Aoife Nguyen"),
        Node("Password", role="password text", states=(SHOWING, EDITABLE), text="hunter2"),
        Node("", role="password text", text="s3cret"),
        Node("", role="entry", states=(SHOWING, EDITABLE), text="draft I am typing"),
        Node("", role="terminal", text="export TOKEN=abc"),
    ], log=log)
    other = Node("Other window", role="frame", states=(SHOWING,), kids=[Node("Other button")])
    app = Node("writer", role="application", kids=[other, active])
    return _module(_desktop(app)), log


def _backend(mod, **kw):
    return AtspiAccessibility(atspi=mod, clock=lambda: 1.0, **kw)


# ---- what is read -----------------------------------------------------------------------


def test_only_the_active_windows_showing_nodes_are_returned():
    mod, _log = _scene()
    labels = [c.label for c in _backend(mod).snapshot()]
    assert labels[:3] == ["Report.odt - Writer", "Save", "Delete"]
    assert "Other button" not in labels and "Other window" not in labels
    assert "Never seen" not in labels and "Hidden menu" not in labels
    assert "Dear Aoife Nguyen" in labels


def test_action_names_are_lowercased_and_a_focusable_node_can_be_focused():
    mod, _log = _scene()
    by_label = {c.label: c for c in _backend(mod).snapshot()}
    assert by_label["Save"].actions == ("click", FOCUS_ACTION)
    assert by_label["Delete"].actions == ("press",)


def test_no_secret_or_editable_text_is_ever_read():
    mod, log = _scene()
    labels = [c.label for c in _backend(mod).snapshot()]
    read_roles = [role for kind, _name, role in (e for e in log if e[0] == "text-read")]
    assert "password text" not in read_roles
    assert "terminal" not in read_roles
    assert "entry" not in read_roles
    joined = " ".join(labels)
    for secret in ("hunter2", "s3cret", "draft I am typing", "TOKEN"):
        assert secret not in joined
    assert "Password" in labels, "a password field's *name* is its visible label, and is fine"


def test_no_active_window_means_nothing():
    app = Node("app", role="application", kids=[Node("w", role="frame", states=(SHOWING,))])
    assert _backend(_module(_desktop(app))).snapshot() == ()


def test_a_registry_that_raises_means_nothing_not_an_exception():
    def boom(_i):
        raise RuntimeError("no accessibility bus")

    mod = SimpleNamespace(STATE_ACTIVE=ACTIVE, Registry=SimpleNamespace(getDesktop=boom))
    assert _backend(mod).snapshot() == ()


@pytest.mark.parametrize("kwargs", [{"window_id": "0x42"}, {"region": object()}])
def test_a_question_about_somewhere_else_is_not_answered_with_here(kwargs):
    mod, _log = _scene()
    assert _backend(mod).snapshot(**kwargs) == ()


def test_the_walk_bounds_apply():
    mod, _log = _scene()
    got = _backend(mod, limits=TreeLimits(max_nodes=3)).snapshot()
    assert len(got) <= 3


# ---- what is done -----------------------------------------------------------------------


def test_perform_runs_the_named_action_on_exactly_the_matched_node():
    mod, log = _scene()
    backend = _backend(mod)
    save = next(c for c in backend.snapshot() if c.label == "Save")
    assert backend.perform(save.entity_id, "click") is True
    assert ("action", "Save", "Click") in log
    assert not any(e[0] == "action" and e[1] != "Save" for e in log)


def test_focus_grabs_focus_instead_of_running_an_action():
    mod, log = _scene()
    backend = _backend(mod)
    save = next(c for c in backend.snapshot() if c.label == "Save")
    assert backend.perform(save.entity_id, FOCUS_ACTION) is True
    assert ("focus", "Save") in log
    assert not any(e[0] == "action" for e in log)


def test_an_action_the_node_does_not_offer_is_refused():
    mod, log = _scene()
    backend = _backend(mod)
    delete = next(c for c in backend.snapshot() if c.label == "Delete")
    assert backend.perform(delete.entity_id, "click") is False
    assert not any(e[0] == "action" for e in log)


def test_an_unknown_id_is_refused():
    mod, _log = _scene()
    backend = _backend(mod)
    backend.snapshot()
    assert backend.perform("nope", "click") is False
    assert backend.perform("", "click") is False


def test_an_id_from_an_earlier_snapshot_never_names_a_node_of_the_next():
    mod, log = _scene()
    backend = _backend(mod)
    old = next(c for c in backend.snapshot() if c.label == "Delete")
    fresh = backend.snapshot()
    assert old.entity_id not in {c.entity_id for c in fresh}
    assert backend.perform(old.entity_id, "press") is False
    assert not any(e[0] == "action" for e in log)


def test_perform_before_any_snapshot_is_refused():
    mod, _log = _scene()
    assert _backend(mod).perform("s1n0", "click") is False


# ---- registration -----------------------------------------------------------------------


def _found(_name):
    return object()


def test_the_route_offers_the_factory_with_a_desktop_and_a_binding():
    factory, reason = accessibility_route({"DISPLAY": ":0"}, find_spec=_found)
    assert factory is build_atspi_accessibility and reason is None
    factory, reason = accessibility_route({"WAYLAND_DISPLAY": "wayland-0"}, find_spec=_found)
    assert factory is not None and reason is None, "AT-SPI is D-Bus, so Wayland works too"


def test_the_route_says_why_with_no_desktop():
    assert accessibility_route({}, find_spec=_found) == (None, HEADLESS_ACCESSIBILITY_REASON)


def test_the_route_says_why_with_no_binding_and_names_the_package():
    assert accessibility_route({"DISPLAY": ":0"}, find_spec=lambda _n: None) == (
        None, ATSPI_MISSING_REASON)
    assert "python3-pyatspi" in ATSPI_MISSING_REASON


def test_a_find_spec_that_raises_reads_as_missing():
    def boom(_name):
        raise ValueError("broken path entry")

    assert accessibility_route({"DISPLAY": ":0"}, find_spec=boom)[1] == ATSPI_MISSING_REASON


def test_the_factory_builds_a_backend_and_opens_nothing():
    backend = build_atspi_accessibility()
    assert isinstance(backend, AtspiAccessibility)
    assert backend._handles == {}


def test_the_route_module_stays_light():
    """`build_platform` imports it on every start: no pyatspi, no `grounding`."""
    tree = ast.parse(Path(accessibility.__file__).read_text(encoding="utf-8"))
    top_level = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            top_level |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            top_level.add(node.module)
    assert not any(m.startswith(("pyatspi", "gi", "yazses.grounding")) for m in top_level)


def test_the_platform_fields_default_to_none():
    from yazses.platform.base import NO_ACCESSIBILITY_BACKEND_REASON, Platform

    by_name = {f.name: f for f in dataclasses.fields(Platform)}
    assert by_name["accessibility_factory"].default is None
    assert by_name["accessibility_unavailable_reason"].default is None
    assert "Linux" in NO_ACCESSIBILITY_BACKEND_REASON


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific bundle")
def test_the_linux_bundle_carries_the_route_and_its_reason(monkeypatch):
    from yazses.platform.linux import build_platform

    monkeypatch.setattr(accessibility, "accessibility_route", lambda: (None, "why not"))
    platform = build_platform()
    assert platform.accessibility_factory is None
    assert platform.accessibility_unavailable_reason == "why not"


@pytest.mark.skipif(sys.platform != "linux", reason="Linux-specific bundle")
def test_the_linux_bundle_offers_none_headless(monkeypatch):
    from yazses.platform.linux import build_platform

    for name in ("WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(name, raising=False)
    platform = build_platform()
    assert platform.accessibility_factory is None
    assert platform.accessibility_unavailable_reason == HEADLESS_ACCESSIBILITY_REASON
