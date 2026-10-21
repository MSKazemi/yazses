"""Voice Mouse Grid wired into the daemon and the overlay (ADR-v2-030, WIRE-MOUSEGRID-001).

The pure subdivision math is covered in ``test_autostop_mousegrid.py``. What is tested here
is the promise to a user who turns ``[mousegrid]`` on — "mouse grid", "three", "seven",
"click" moves the pointer and clicks there — and the promise to every user who does not:
nothing about their daemon changes, and the package is never even imported.

Failure modes named, because each makes the feature worse than not having it:

* a sentence containing "click" or "three" moving the pointer (anchoring);
* an open grid swallowing dictation it did not understand (modal trap);
* a click before any cell was chosen (an unasked click in the middle of the screen);
* a relative-only backend driven by guesswork instead of refused with a reason.
"""
from __future__ import annotations

import builtins
import dataclasses
import logging
import threading
import types
from dataclasses import replace

import numpy as np
import pytest

from tests.pointer_fake import FakePointerSink, PointerAction
from yazses.config import Config, MousegridConfig
from yazses.mousegrid.grammar import GridCommand, is_open_phrase, parse_open_command
from yazses.mousegrid.grid import resolve_point
from yazses.mousegrid.runtime import MousegridRuntime, build_mousegrid
from yazses.mousegrid.session import GridSession
from yazses.pointer.base import PointerButton, PointerCapabilities

SCREEN = (0.0, 0.0, 900.0, 900.0)


# ---- grammar: anchored, whole-utterance -------------------------------------


@pytest.mark.parametrize("heard", ["mouse grid", "Mouse grid.", "  MOUSE   GRID!  ", "show mouse grid"])
def test_the_open_phrase_survives_case_and_punctuation(heard):
    assert is_open_phrase(heard)


@pytest.mark.parametrize("prose", [
    "open the mouse grid settings",
    "the mouse grid is nice",
    "mouse",
    "grid",
    "click",
    "",
])
def test_prose_that_contains_the_words_never_opens_a_grid(prose):
    assert not is_open_phrase(prose)


@pytest.mark.parametrize(("heard", "cells"), [
    ("three", (3,)),
    ("Three.", (3,)),
    ("3", (3,)),
    ("three seven", (3, 7)),
    ("Three. Seven.", (3, 7)),
    ("3, 7", (3, 7)),
    ("37", (3, 7)),
    ("nine-one", (9, 1)),
])
def test_cell_numbers_as_words_or_digits(heard, cells):
    assert parse_open_command(heard, 9) == GridCommand("cells", cells=cells)


@pytest.mark.parametrize("heard", [
    "to", "for", "tree",            # homophones are refused on purpose (rule 9)
    "ten",                          # out of range on a 3x3 grid
    "0", "30",                      # zero is never a cell
    "three apples",                 # one non-number token rejects the lot
    "click the button",
    "please cancel",
])
def test_anything_else_is_not_a_grid_command(heard):
    assert parse_open_command(heard, 9) is None


def test_more_than_nine_cells_reads_a_digit_run_as_one_number():
    assert parse_open_command("12", 16) == GridCommand("cells", cells=(12,))
    assert parse_open_command("sixteen", 16) == GridCommand("cells", cells=(16,))
    assert parse_open_command("17", 16) is None


@pytest.mark.parametrize(("heard", "button", "count"), [
    ("click", "left", 1), ("Left click.", "left", 1),
    ("right click", "right", 1), ("double click", "left", 2),
])
def test_click_words(heard, button, count):
    assert parse_open_command(heard, 9) == GridCommand("click", button=button, count=count)


@pytest.mark.parametrize(("heard", "button", "count"), [
    ("Right-click.", "right", 1), ("Double-click.", "left", 2), ("Left-click", "left", 1),
    ("right\u2010click", "right", 1),
])
def test_whisper_hyphenated_click_words(heard, button, count):
    """Whisper writes "Right-click." — it must not fall through to being typed."""
    assert parse_open_command(heard, 9) == GridCommand("click", button=button, count=count)


@pytest.mark.parametrize("heard", ["Mouse-grid.", "show mouse-grid", "mouse\u2013grid"])
def test_a_hyphenated_open_phrase_opens(heard):
    assert is_open_phrase(heard)


def test_hyphens_do_not_widen_prose_into_commands():
    assert parse_open_command("right-click the link", 9) is None
    assert not is_open_phrase("mouse-grid settings")


def test_back_and_cancel():
    assert parse_open_command("back", 9) == GridCommand("back")
    assert parse_open_command("Cancel.", 9) == GridCommand("cancel")
    assert parse_open_command("close grid", 9) == GridCommand("cancel")


# ---- session: the state machine ---------------------------------------------


class _Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


def test_cells_zoom_and_back_zooms_out():
    s = GridSession(3, 3, clock=_Clock())
    s.open(SCREEN)
    step = s.apply(GridCommand("cells", cells=(3,)))
    assert step.kind == "move" and step.point == (750.0, 150.0)
    step = s.apply(GridCommand("cells", cells=(7,)))
    assert step.point == resolve_point(SCREEN, [3, 7])
    assert s.region() == (600.0, 200.0, 100.0, 100.0)
    step = s.apply(GridCommand("back"))
    assert step.point == (750.0, 150.0) and s.path == (3,)


def test_click_before_any_cell_is_refused_and_the_grid_stays_open():
    s = GridSession(clock=_Clock())
    s.open(SCREEN)
    step = s.apply(GridCommand("click"))
    assert step.kind == "refused" and s.active


def test_an_idle_grid_closes_itself():
    clock = _Clock()
    s = GridSession(clock=clock, idle_timeout_s=30.0)
    s.open(SCREEN)
    clock.t += 29.0
    assert s.active
    s.apply(GridCommand("cells", cells=(5,)))  # activity resets the timer
    clock.t += 29.0
    assert s.active
    clock.t += 2.0
    assert not s.active and s.status()["active"] is False


def test_a_zoom_below_a_pixel_is_refused_whole():
    s = GridSession(clock=_Clock())
    s.open((0.0, 0.0, 9.0, 9.0))
    step = s.apply(GridCommand("cells", cells=(5, 5, 5)))
    assert step.kind == "refused"
    assert s.path == (), "half a path is a different place: nothing may be applied"


# ---- runtime: grammar -> session -> pointer sink ------------------------------


def _runtime(sink=None, *, region=SCREEN, paused=False, factory_calls=None):
    sink = sink if sink is not None else FakePointerSink()

    def factory():
        if factory_calls is not None:
            factory_calls.append(1)
        return sink

    rt = MousegridRuntime(
        3, 3, sink_factory=factory, region_provider=lambda: region,
        paused=lambda: paused, clock=_Clock(),
    )
    return rt, sink


def test_three_seven_click_moves_then_clicks_once_at_the_cell_centre():
    calls: list[int] = []
    rt, sink = _runtime(factory_calls=calls)
    assert rt.handle_transcript("Mouse grid.") == "opened"
    assert calls == [1], "opening a grid probes the sink once, so a bad backend refuses now"
    assert rt.handle_transcript("three") == "moved"
    assert rt.handle_transcript("seven") == "moved"
    assert rt.handle_transcript("click") == "clicked"
    x, y = resolve_point(SCREEN, [3, 7])
    assert sink.actions == [
        PointerAction.move_absolute(750.0, 150.0),
        PointerAction.move_absolute(x, y),
        PointerAction.move_absolute(x, y),
        PointerAction.press(PointerButton.LEFT),
        PointerAction.release(PointerButton.LEFT),
    ]
    assert not rt.active, "a click ends the grid"
    assert rt.handle_transcript("three") is None, "with the grid closed, numbers are dictation"


def test_right_and_double_click():
    rt, sink = _runtime()
    rt.handle_transcript("mouse grid")
    rt.handle_transcript("5")
    rt.handle_transcript("double click")
    presses = [a for a in sink.actions if a.kind.value == "button_press"]
    assert len(presses) == 2
    rt.handle_transcript("mouse grid")
    rt.handle_transcript("5")
    rt.handle_transcript("right click")
    assert sink.actions[-1] == PointerAction.release(PointerButton.RIGHT)


def test_with_no_grid_open_only_the_exact_phrase_is_claimed():
    rt, sink = _runtime()
    for prose in ("click", "three", "cancel", "open the mouse grid", "hello world"):
        assert rt.handle_transcript(prose) is None, prose
    assert sink.actions == []


def test_an_open_grid_hands_back_speech_it_does_not_understand():
    """No modal trap: the utterance is dictated as usual and the grid closes."""
    rt, sink = _runtime()
    rt.handle_transcript("mouse grid")
    assert rt.handle_transcript("send the report on friday") is None
    assert not rt.active
    assert sink.actions == []


def test_cancel_closes_without_moving_or_clicking():
    rt, sink = _runtime()
    rt.handle_transcript("mouse grid")
    assert rt.handle_transcript("cancel") == "cancelled"
    assert not rt.active and sink.actions == []


def test_a_relative_only_backend_is_refused_with_a_reason_and_closed():
    caps = PointerCapabilities(
        backend="portal", relative_motion=True, absolute_motion=False,
        buttons=frozenset({PointerButton.LEFT, PointerButton.RIGHT}),
    )
    sink = FakePointerSink(caps)
    rt, _ = _runtime(sink)
    assert rt.handle_transcript("mouse grid") == "refused", "refused at open, before a grid draws"
    assert not rt.active and rt.status()["region"] is None
    assert rt.handle_transcript("three") is None, "no grid open: the number is dictation"
    assert sink.closed
    assert [a for a in sink.actions if a.kind.value != "close"] == [], "nothing moved"
    assert "absolute motion" in str(rt.status()["reason"])
    assert rt.status()["available"] is False
    assert rt.handle_transcript("mouse grid") == "refused", "unsupported is permanent"


def test_a_paused_hands_free_gate_moves_nothing():
    rt, sink = _runtime(paused=True)
    assert rt.handle_transcript("mouse grid") == "refused"
    assert not rt.active and sink.actions == []


def test_an_unknown_screen_refuses_to_open_and_the_overlay_screen_fixes_it():
    rt, _ = _runtime(region=None)
    assert rt.handle_transcript("mouse grid") == "refused"
    assert rt.status()["screen_reported"] is False
    assert rt.command("screen", {"region": [0, 0, 300, 300]}) == {"ok": True}
    assert rt.handle_transcript("mouse grid") == "opened"
    assert rt.status()["region"] == [0.0, 0.0, 300.0, 300.0]


@pytest.mark.parametrize("bad", [None, [0, 0, 0, 10], [0, 0, 10], ["a", 0, 1, 1],
                                 [0, 0, float("nan"), 1], "0,0,1,1"])
def test_a_malformed_screen_is_rejected(bad):
    rt, _ = _runtime(region=None)
    assert rt.command("screen", {"region": bad})["ok"] is False


def test_ipc_say_drives_the_same_grammar_and_status_is_value_free():
    rt, sink = _runtime()
    reply = rt.command("say", {"text": "mouse grid"})
    assert reply["ok"] is True and reply["active"] is True and reply["region"] == list(SCREEN)
    reply = rt.command("say", {"text": "one"})
    assert reply["result"] == "moved" and reply["depth"] == 1
    assert set(rt.status()) == {"active", "cols", "rows", "region", "depth", "enabled",
                                "available", "reason", "screen_reported"}
    assert rt.command("bogus")["ok"] is False
    rt.close()
    assert sink.closed


def test_build_mousegrid_reads_the_section_and_the_safety_gate():
    gate = types.SimpleNamespace(
        status=lambda: types.SimpleNamespace(user_paused=True, terminal=False))
    rt = build_mousegrid(MousegridConfig(enabled=True, cols=4, rows=2),
                         pointer_factory=FakePointerSink, safety=gate)
    assert rt.status()["cols"] == 4 and rt.status()["rows"] == 2
    rt._region_provider = lambda: SCREEN
    assert rt.handle_transcript("mouse grid") == "refused", "a paused gate blocks the grid"


def test_a_runtime_that_is_never_opened_never_builds_the_sink():
    calls: list[int] = []
    rt, _ = _runtime(factory_calls=calls)
    for prose in ("hello", "three", "click"):
        rt.handle_transcript(prose)
    rt.command("status")
    assert calls == [], "no pointer permission is asked before the user opens a grid"


def test_a_grid_bigger_than_the_number_words_warns_at_build(caplog):
    with caplog.at_level(logging.WARNING, logger="yazses.mousegrid.runtime"):
        build_mousegrid(MousegridConfig(enabled=True, cols=4, rows=5),
                        pointer_factory=FakePointerSink)
    assert any("20 cells" in r.getMessage() for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="yazses.mousegrid.runtime"):
        build_mousegrid(MousegridConfig(enabled=True, cols=4, rows=4),
                        pointer_factory=FakePointerSink)
    assert caplog.records == []


def test_an_ipc_status_poll_cannot_interleave_with_a_transcript():
    """The overlay polls `status` from an IPC thread while the pipeline applies a command.

    The poll must wait for the command to finish: without the lock it can run the idle
    close between `apply()`'s open-check and its region read (a TypeError, a lost burst).
    """
    polled = threading.Event()
    started = threading.Event()
    seen_inside: list[bool] = []
    rt, _ = _runtime()
    rt.handle_transcript("mouse grid")

    def poll():
        started.set()
        rt.command("status")
        polled.set()

    real_apply = rt._session.apply

    def apply_with_a_poll_racing(command):
        t = threading.Thread(target=poll, daemon=True)
        t.start()
        started.wait(1.0)
        seen_inside.append(polled.wait(0.2))
        return real_apply(command)

    rt._session.apply = apply_with_a_poll_racing  # type: ignore[method-assign]
    assert rt.handle_transcript("three") == "moved"
    assert seen_inside == [False], "a status poll ran in the middle of a grid command"
    assert polled.wait(2.0), "the poll must complete once the command is done"


def test_no_pointer_backend_on_this_platform_is_a_reason():
    rt = MousegridRuntime(sink_factory=None, region_provider=lambda: SCREEN)
    assert rt.handle_transcript("mouse grid") == "refused"
    assert "no pointer backend" in str(rt.status()["reason"])


# ---- the daemon: off means untouched, on means reachable ---------------------


class _FakeRecorder:
    def __init__(self, audio):
        self._audio = audio

    def stop(self):
        return self._audio


class _FakeEngine:
    text = ""

    def transcribe(self, *args, **kwargs):
        return self.text


class _Injector:
    def __init__(self):
        self.injected: list[str] = []

    def inject(self, text):
        self.injected.append(text)

    def inject_backspaces(self, count):
        pass

    def inject_key_sequence(self, keys):
        pass


def _daemon(*, enabled: bool, sink: FakePointerSink | None = None):
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    cfg.filters.disfluency.enabled = False
    cfg.streaming.enabled = False
    cfg.injection.continuation_window_ms = 0
    cfg.mousegrid.enabled = enabled
    sink = sink or FakePointerSink()
    platform = dataclasses.replace(get_platform(), pointer_factory=lambda: sink)
    d = Daemon(config=cfg, platform=platform)
    d._recorder = _FakeRecorder(np.full(16000, 0.5, dtype="float32"))
    d._engine = _FakeEngine()
    d._padding_buffer = None
    inj = _Injector()
    d._injector = inj
    d._state.target_ok = True
    d._mousegrid = d._build_mousegrid(cfg)
    if d._mousegrid is not None:
        d._mousegrid._region_provider = lambda: SCREEN
    return d, inj, sink


def _say(d, text):
    d._engine.text = text
    d._on_hold_end()


def test_an_enabled_daemon_drives_the_pointer_from_speech_and_types_nothing():
    d, inj, sink = _daemon(enabled=True)
    for word in ("mouse grid", "three", "click"):
        _say(d, word)
    assert inj.injected == [], "grid words must never be typed"
    assert sink.actions[-2:] == [PointerAction.press(PointerButton.LEFT),
                                 PointerAction.release(PointerButton.LEFT)]
    assert sink.actions[0] == PointerAction.move_absolute(750.0, 150.0)
    # The grid closed after the click: the next words are dictation again.
    _say(d, "three")
    assert inj.injected and inj.injected[-1].strip().lower().startswith("three")
    # Counted as instructions, never as dictation failures.
    outcomes = d._outcomes.as_dict()
    assert outcomes["dictation_total"] == 1


def test_an_enabled_daemon_still_dictates_everything_else():
    d, inj, sink = _daemon(enabled=True)
    _say(d, "click the link and three more")
    assert inj.injected and "click the link" in inj.injected[-1].lower()
    assert sink.actions == []


def test_a_failing_grid_never_breaks_dictation():
    d, inj, _sink = _daemon(enabled=True)

    def boom(text):
        raise TypeError("grid fault")

    d._mousegrid.handle_transcript = boom
    _say(d, "send the report")
    assert inj.injected and "send the report" in inj.injected[-1].lower()


def test_a_default_daemon_types_the_grid_words_and_touches_no_pointer():
    """Off is byte-for-byte the old behaviour: "mouse grid" is just dictation."""
    d, inj, sink = _daemon(enabled=False)
    assert d._mousegrid is None
    _say(d, "mouse grid")
    assert inj.injected and "mouse grid" in inj.injected[-1].lower()
    assert sink.actions == []


def test_the_ipc_handler_reports_off_and_drives_when_on():
    from yazses.ipc.protocol import Request

    d, _inj, _sink = _daemon(enabled=False)
    assert d._handle_mousegrid(Request(method="mousegrid", params={}, id=1))["ok"] is False
    d, _inj, sink = _daemon(enabled=True)
    reply = d._handle_mousegrid(
        Request(method="mousegrid", params={"action": "say", "text": "mouse grid"}, id=2))
    assert reply["ok"] is True and reply["active"] is True


class _DaemonImports:
    """Records ``yazses.mousegrid`` imports made by ``core/daemon.py`` itself."""

    def __init__(self) -> None:
        self.names: list[str] = []
        self._real = builtins.__import__

    def __call__(self, name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if level == 0 and (globals or {}).get("__name__") == "yazses.core.daemon":
            if name == "yazses.mousegrid" or name.startswith("yazses.mousegrid."):
                self.names.append(name)
        return self._real(name, globals, locals, fromlist, level)


@pytest.fixture
def started(monkeypatch: pytest.MonkeyPatch):
    """A daemon after `__init__` and the real `_build_pipeline()` (no model, no hotkey)."""
    import yazses.core.daemon as daemon_mod
    import yazses.inject.auto as inject_auto
    from yazses.platform import get_platform

    monkeypatch.setattr(daemon_mod, "build_engine", lambda stt: types.SimpleNamespace(name="stub"))
    monkeypatch.setattr(inject_auto, "apply_injection_config", lambda injection: None)
    platform = dataclasses.replace(
        get_platform(),
        injector_factory=lambda: types.SimpleNamespace(name="stub"),
        hotkey_factory=lambda *args: types.SimpleNamespace(run=lambda: None, stop=lambda: None),
        pointer_factory=FakePointerSink,
    )
    monkeypatch.setattr(platform.lifecycle, "clear_pid", lambda: None)
    made = []

    def build(cfg: Config):
        daemon = daemon_mod.Daemon(config=cfg, platform=platform)
        made.append(daemon)
        monkeypatch.setattr(daemon, "_announce_model_download", lambda cfg: None)
        daemon._build_pipeline()
        return daemon

    yield build
    for daemon in made:
        daemon._shutdown()


def test_a_default_started_daemon_never_imports_the_mouse_grid(started, monkeypatch):
    recorder = _DaemonImports()
    monkeypatch.setattr(builtins, "__import__", recorder)
    daemon = started(Config())
    assert recorder.names == []
    assert daemon._mousegrid is None


def test_an_enabled_started_daemon_imports_and_builds_it(started, monkeypatch):
    """The positive control: without it the test above could pass on a blind recorder."""
    recorder = _DaemonImports()
    monkeypatch.setattr(builtins, "__import__", recorder)
    daemon = started(replace(Config(), mousegrid=MousegridConfig(enabled=True)))
    assert recorder.names == ["yazses.mousegrid.runtime"]
    assert isinstance(daemon._mousegrid, MousegridRuntime)


def test_the_registry_lists_it_as_wired_and_experimental():
    from yazses.system.features import EXPERIMENTAL, _registry, unwired_slugs

    assert "mousegrid" not in unwired_slugs()
    (entry,) = [d for d in _registry() if d.slug == "mousegrid"]
    assert entry.tier == EXPERIMENTAL
    assert MousegridConfig().enabled is False
