"""The macOS menu bar menu carries status lines, like the Linux menu and Windows tooltip.

The rumps tray showed a state glyph and nothing else: which engine decodes, whether the
speech model is in memory (`[stt] idle_unload_s`, ADR-029) and any warning were
invisible on a Mac. Now the top of its menu carries up to three disabled lines from the
shared `tray/menu.py::status_lines`, retitled on the same poll tick as the glyph, with
the AppKit mutation queued onto the main thread.

Two halves, as elsewhere in the macOS tests ("rumps is tested manually on a Mac"):

* **which lines appear** -- pure, from a status dict or a `TrayModel`, on any runner;
* **the menu build and refresh** -- against a fake rumps and a fake
  `PyObjCTools.AppHelper`. What a real Mac does with the calls is UNVERIFIED: there is
  no Mac on this project.
"""

from __future__ import annotations

import ast
import sys
import types
from pathlib import Path

import pytest

from yazses.platform.base import TrayModel, TrayState
from yazses.platform.macos import tray as mac_tray
from yazses.platform.macos.tray import MacosTray
from yazses.stt.factory import fallback_phrase, render_engine_status_lines
from yazses.tray import menu as tray_menu
from yazses.tray.menu import (
    MEETING_START_LABEL,
    SETTINGS_LABEL,
    STATUS_LINE_SLOTS,
    UPDATE_LABEL,
    build_menu_model,
    engine_line,
    residency_line,
    status_from_model,
    status_lines,
    top_warning,
)

_LOADED = {"idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 45.0}
_FALLBACK = {"from": "parakeet", "reason": "it failed to load (RuntimeError)"}
_ENGINE = {"engine": "faster-whisper", "engine_model": "base.en", "model": "base.en"}


# ---- which lines appear (pure, shared) -------------------------------------------------


def test_the_engine_line_names_the_engine_actually_decoding():
    assert engine_line({"state": "idle", **_ENGINE}) == "YazSes — idle · base.en (faster-whisper)"


def test_an_older_or_loading_daemon_gets_the_configured_model_like_yazses_status():
    # `yazses status` prints `model: base.en` for a daemon that names no engine.
    assert engine_line({"state": "loading", "model": "base.en"}) == "YazSes — loading · base.en"


def test_with_no_model_at_all_the_engine_line_is_just_the_state():
    assert engine_line({"state": "error", "model": ""}) == "YazSes — error"
    assert status_lines({"state": "loading"}) == ["YazSes — loading"]


def test_at_the_default_there_is_exactly_one_line():
    """`idle_unload_s = 0`, no warning: the memory and warning lines do not appear."""
    assert status_lines({"state": "idle", **_ENGINE, "stt_residency": None}) == [
        "YazSes — idle · base.en (faster-whisper)"
    ]


def test_the_memory_line_appears_only_under_idle_unload_and_is_the_shared_phrase():
    lines = status_lines({"state": "idle", **_ENGINE, "stt_residency": _LOADED})
    assert lines[1] == residency_line({"stt_residency": _LOADED})
    assert lines[1] == "Speech model: loaded, idle 45 s of 300 s"
    assert len(lines) == 2


def test_all_three_lines_in_order():
    lines = status_lines(
        {"state": "idle", **_ENGINE, "stt_residency": _LOADED, "silent_streak": 2}
    )
    assert lines == [
        "YazSes — idle · base.en (faster-whisper)",
        "Speech model: loaded, idle 45 s of 300 s",
        "⚠ 2 silent clips in a row",
    ]
    assert len(lines) <= STATUS_LINE_SLOTS


def test_the_silent_streak_warning_is_the_linux_menus_wording():
    status = {"state": "idle", "silent_streak": 1}
    assert top_warning(status) == build_menu_model(status, [], "").warning


def test_the_fallback_warning_is_yazses_statuss_fallback_line():
    status = {"state": "idle", **_ENGINE, "engine_fallback": _FALLBACK}
    warning = top_warning(status)
    phrase = fallback_phrase(status)
    assert phrase is not None and warning is not None
    full = f"⚠ {phrase}"
    # Whole, or cut to fit one menu line -- never reworded.
    assert warning == full or (warning.endswith("…") and full.startswith(warning[:-1]))
    assert warning.startswith("⚠ [stt] engine = parakeet is not running, because it failed")
    # One wording: the CLI's FALLBACK line is built from the same phrase.
    assert render_engine_status_lines(status)[1] == f"  FALLBACK: {phrase}"


def test_an_error_outranks_a_fallback_which_outranks_a_silent_streak():
    both = {"state": "idle", **_ENGINE, "engine_fallback": _FALLBACK, "silent_streak": 3}
    assert (top_warning(both) or "").startswith("⚠ [stt] engine = parakeet is not running")

    failed = {**both, "state": "error", "last_error": "daemon not responding"}
    assert top_warning(failed) == "⚠ daemon not responding"


def test_last_error_is_only_a_warning_while_the_daemon_is_in_error():
    """A stale `last_error` on a recovered daemon must not keep alarming the menu."""
    assert top_warning({"state": "idle", "last_error": "old trouble"}) is None
    # In error but with no reason given: fall through to the next warning.
    assert top_warning({"state": "error", "silent_streak": 2}) == "⚠ 2 silent clips in a row"


def test_a_long_or_multiline_warning_stays_one_short_line():
    reason = "Traceback line one\nline two " + "x" * 300
    warning = top_warning({"state": "error", "last_error": reason})
    assert warning is not None
    assert "\n" not in warning
    assert len(warning) <= tray_menu._WARNING_MAX
    assert warning.endswith("…")


def test_the_lines_come_through_the_shared_traymodel_bridge():
    model = TrayModel(
        state=TrayState.IDLE,
        model="nemo-parakeet-tdt-0.6b-v2",
        engine="faster-whisper",
        engine_model="base.en",
        engine_fallback=dict(_FALLBACK),
        stt_residency=dict(_LOADED),
    )
    hash(model)  # a frozen dataclass holding two dicts must still hash
    lines = status_lines(status_from_model(model))
    assert lines[0] == "YazSes — idle · base.en (faster-whisper)"
    assert lines[1] == "Speech model: loaded, idle 45 s of 300 s"
    assert lines[2].startswith("⚠ [stt] engine = parakeet is not running")


def test_an_unreachable_daemon_shows_no_invented_model():
    """The poller passes `model=""` when no daemon answered: the dataclass default
    ("tiny.en") must not appear as if it were the running model."""
    model = TrayModel(state=TrayState.ERROR, last_error="daemon not responding", model="")
    assert status_lines(status_from_model(model)) == [
        "YazSes — error",
        "⚠ daemon not responding",
    ]


def test_the_poller_carries_the_engine_fields_and_no_model_when_unreachable():
    """`tray/app.py` builds the TrayModel in a loop no test drives (see
    test_tray_model_contract.py), so the wiring is checked on its source."""
    app = Path(__file__).resolve().parents[1] / "src" / "yazses" / "tray" / "app.py"
    calls = [
        node
        for node in ast.walk(ast.parse(app.read_text(encoding="utf-8")))
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("TrayModel")
    ]
    keywords = [{kw.arg: kw.value for kw in call.keywords} for call in calls]
    connected = [kw for kw in keywords if "stt_residency" in kw]
    assert len(connected) == 1
    assert {"engine", "engine_model", "engine_fallback"} <= set(connected[0])
    unreachable = [kw for kw in keywords if "stt_residency" not in kw]
    assert unreachable, "the unreachable / failed-call TrayModels are gone"
    for kw in unreachable:
        assert "model" in kw and ast.literal_eval(kw["model"]) == ""


# ---- the macOS menu: build and refresh against a fake rumps ------------------------------


class _Item:
    def __init__(self, title: str, callback=None, key=None) -> None:
        self.key_title = title  # what rumps keys the item by: its title when added
        self.title = title
        self.callback = callback
        self.hidden = False


def test_apply_status_lines_fills_in_order_and_hides_the_rest():
    items = [_Item("a"), _Item("b"), _Item("c")]
    mac_tray._apply_status_lines(items, ["one", "two", "three"])
    assert [(i.title, i.hidden) for i in items] == [
        ("one", False), ("two", False), ("three", False)
    ]

    mac_tray._apply_status_lines(items, ["only"])
    assert items[0].title == "only" and items[0].hidden is False
    assert items[1].hidden is True and items[2].hidden is True


def test_one_failing_item_does_not_leave_the_others_stale():
    class _Broken:
        def __setattr__(self, name, value):
            raise RuntimeError("AppKit said no")

    items = [_Broken(), _Item("b")]
    mac_tray._apply_status_lines(items, ["one", "two"])
    assert items[1].title == "two"


def _install_fake_rumps(monkeypatch):
    events = types.ModuleType("rumps.events")

    class _Emitter:
        def register(self, func):
            return func

    events.before_quit = _Emitter()

    class App:
        def __init__(self, *a, **k):
            self.menu = None
            self.title = k.get("title", "")

        def run(self):
            return None  # a loop that returns, so the test can carry on

    rumps = types.ModuleType("rumps")
    rumps.App = App
    rumps.MenuItem = _Item
    rumps.events = events
    rumps.clicked = lambda *a, **k: (lambda f: f)
    monkeypatch.setitem(sys.modules, "rumps", rumps)
    monkeypatch.setitem(sys.modules, "rumps.events", events)


def _install_fake_apphelper(monkeypatch) -> list:
    """A `PyObjCTools.AppHelper` whose `callAfter` only queues, like the real one."""
    queued: list = []
    helper = types.ModuleType("PyObjCTools.AppHelper")
    helper.callAfter = lambda func, *args: queued.append((func, args))
    package = types.ModuleType("PyObjCTools")
    package.AppHelper = helper
    monkeypatch.setitem(sys.modules, "PyObjCTools", package)
    monkeypatch.setitem(sys.modules, "PyObjCTools.AppHelper", helper)
    return queued


def _drain(queued: list) -> None:
    """What the main run loop does with the queue."""
    while queued:
        func, args = queued.pop(0)
        func(*args)


@pytest.fixture
def running_tray(monkeypatch):
    _install_fake_rumps(monkeypatch)
    tray = MacosTray()
    tray.run(lambda: None)
    return tray


def test_the_menu_starts_with_the_status_slots_then_the_existing_items(running_tray):
    menu = running_tray._app.menu
    slots = menu[:STATUS_LINE_SLOTS]
    assert all(isinstance(item, _Item) for item in slots)
    assert menu[STATUS_LINE_SLOTS] is None  # a separator below them
    # The existing entries follow, in their existing order.
    rest = menu[STATUS_LINE_SLOTS + 1:]
    assert rest[0] == SETTINGS_LABEL
    assert rest.index(MEETING_START_LABEL) < rest.index("Pause hotkey") < rest.index(UPDATE_LABEL)
    assert rest[-1] == UPDATE_LABEL


def test_the_status_slots_are_disabled_and_keyed_apart(running_tray):
    slots = running_tray._app.menu[:STATUS_LINE_SLOTS]
    # No callback: rumps greys the item out, so it cannot be clicked.
    assert all(item.callback is None for item in slots)
    # rumps keys a MenuItem by its title when added; equal keys would collapse slots.
    assert len({item.key_title for item in slots}) == STATUS_LINE_SLOTS


def test_before_the_first_poll_the_menu_says_loading(running_tray):
    slots = running_tray._app.menu[:STATUS_LINE_SLOTS]
    assert slots[0].title == "YazSes — loading" and slots[0].hidden is False
    assert all(item.hidden for item in slots[1:])


def test_a_tick_queues_the_lines_on_the_main_thread_and_moves_the_glyph(
    running_tray, monkeypatch
):
    queued = _install_fake_apphelper(monkeypatch)
    slots = running_tray._app.menu[:STATUS_LINE_SLOTS]
    model = TrayModel(
        state=TrayState.IDLE,
        model="base.en",
        engine="faster-whisper",
        engine_model="base.en",
        stt_residency=dict(_LOADED),
        silent_streak=2,
    )

    running_tray.set_state(model)

    assert running_tray._app.title == mac_tray._GLYPH[TrayState.IDLE]
    # Nothing touched from the poller's thread: the mutation waits for the main loop.
    assert slots[0].title == "YazSes — loading"
    assert len(queued) == 1

    _drain(queued)
    assert [s.title for s in slots] == status_lines(status_from_model(model))
    assert not any(s.hidden for s in slots)


def test_an_unchanged_tick_queues_nothing(running_tray, monkeypatch):
    queued = _install_fake_apphelper(monkeypatch)
    model = TrayModel(state=TrayState.IDLE, model="base.en", engine="faster-whisper")
    running_tray.set_state(model)
    _drain(queued)

    running_tray.set_state(model)
    assert queued == []

    running_tray.set_state(TrayModel(state=TrayState.IDLE, model="base.en", silent_streak=1))
    assert len(queued) == 1


def test_lines_that_drop_out_are_hidden_on_the_next_tick(running_tray, monkeypatch):
    queued = _install_fake_apphelper(monkeypatch)
    slots = running_tray._app.menu[:STATUS_LINE_SLOTS]
    running_tray.set_state(
        TrayModel(model="base.en", stt_residency=dict(_LOADED), silent_streak=2)
    )
    _drain(queued)
    running_tray.set_state(TrayModel(model="base.en"))
    _drain(queued)
    assert slots[0].hidden is False
    assert slots[1].hidden is True and slots[2].hidden is True


def test_without_a_main_thread_dispatcher_nothing_is_mutated_off_thread(
    running_tray, monkeypatch
):
    """No `PyObjCTools`: skip the update rather than touch AppKit from the poller."""
    monkeypatch.setitem(sys.modules, "PyObjCTools", None)
    slots = running_tray._app.menu[:STATUS_LINE_SLOTS]

    running_tray.set_state(TrayModel(state=TrayState.ERROR, last_error="boom", model=""))

    assert running_tray._app.title == mac_tray._GLYPH[TrayState.ERROR]  # glyph still moves
    assert slots[0].title == "YazSes — loading"

    # The skipped lines were not recorded as shown, so the next tick tries again.
    queued = _install_fake_apphelper(monkeypatch)
    running_tray.set_state(TrayModel(state=TrayState.ERROR, last_error="boom", model=""))
    _drain(queued)
    assert [s.title for s in slots[:2]] == ["YazSes — error", "⚠ boom"]


def test_the_tray_module_imports_no_toolkit_at_top_level():
    """rumps and PyObjCTools are imported lazily, so CI on Linux can import the tray."""
    source = Path(mac_tray.__file__).read_text(encoding="utf-8")
    top = ast.parse(source).body
    names = set()
    for node in top:
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    assert not names & {"rumps", "PyObjCTools", "AppKit", "Foundation"}
