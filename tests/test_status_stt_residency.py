"""`yazses status` and the tray say whether the speech model is loaded (ADR-029).

With `[stt] idle_unload_s` set, the daemon releases the speech model after that many idle
seconds and the next press reloads it, so the first words after a pause are late. Before
this, nothing told the user which of the two they were in: `status` named the engine and
the tray showed "idle" either way.

The daemon's status reply now carries one block, `stt_residency`:

    {"idle_unload_s": int, "loaded": bool, "loading": bool, "idle_s": float | None}

or `None` at the default of `0`, which leaves the reply, `yazses status` and the tray
unchanged for every install that has not opted in. These tests pin:

* the payload in each state -- off, loaded and idle, in use, unloaded, reloading -- read
  from a real `IdleUnloadEngine` over a counting fake model and a hand-driven clock;
* that reading it never waits on the engine lock, so a tray polling four times a second
  cannot queue behind a decode or a reload;
* the one phrase `yazses status` and the tray print, from one shared builder;
* that the block holds no string, so the report bundle's redactor has nothing to miss.

No model loads, no thread sleeps, and no microphone opens.
"""

from __future__ import annotations

import math
import threading

import numpy as np
import pytest
from typer.testing import CliRunner

from yazses.config import Config
from yazses.core.daemon import Daemon
from yazses.platform import get_platform
from yazses.platform.base import TrayModel
from yazses.stt.factory import render_engine_status_lines
from yazses.stt.resident import IdleUnloadEngine
from yazses.system.report import redact_status
from yazses.system.residency import (
    STT_UNIT,
    IdleTracker,
    describe_stt_residency,
    with_stt_idle_unload,
)
from yazses.tray.menu import build_menu_model, icon_spec, residency_line, status_from_model

AUDIO = np.zeros(1600, dtype=np.float32)
_KEYS = {"idle_unload_s", "loaded", "loading", "idle_s"}


class _Model:
    """A stand-in engine; `during` runs inside a decode so a test can look mid-flight."""

    def __init__(self) -> None:
        self.during = None

    def transcribe(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        if self.during is not None:
            self.during()
        return "words"

    def transcribe_words(self, audio, sample_rate=16000, initial_prompt=None, task=None):
        return "words", []

    def decode_window(self, audio):
        return ""


class _Rig:
    """An `IdleUnloadEngine` on a hand-driven clock, with an inspectable reload."""

    def __init__(self, idle_unload_s: int = 300) -> None:
        self.now = [0.0]
        self.first = _Model()
        self.seen_during_load: list[dict] = []
        self.engine = IdleUnloadEngine(
            self._load,
            idle_unload_s,
            engine=self.first,
            clock=lambda: self.now[0],
            spawn=lambda fn: None,
        )

    def _load(self) -> _Model:
        # The loader runs with no engine lock held, exactly while a reload is in flight.
        self.seen_during_load.append(self.engine.residency_snapshot())
        return _Model()

    def at(self, t: float) -> IdleUnloadEngine:
        self.now[0] = t
        return self.engine


def _daemon(rig: _Rig | None = None) -> Daemon:
    d = Daemon(config=Config(), platform=get_platform())
    if rig is not None:
        d._config.stt.idle_unload_s = int(rig.engine.idle_unload_s)
        d._engine = rig.engine
        d._idle_unload_engine = rig.engine
    return d


# ---- the payload, from the engine wrapper ---------------------------------------------


def test_a_loaded_model_reports_how_long_it_has_been_idle() -> None:
    rig = _Rig(300)
    snap = rig.at(45.0).residency_snapshot()
    assert snap == {"idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 45.0}


def test_idle_counts_from_the_end_of_the_last_decode() -> None:
    rig = _Rig(300)
    rig.at(100.0).transcribe(AUDIO)
    assert rig.at(130.0).residency_snapshot()["idle_s"] == 30.0


def test_a_decode_in_flight_is_in_use_not_idle() -> None:
    rig = _Rig(300)
    seen: list[dict] = []

    def _look() -> None:
        rig.now[0] = 250.0          # the decode has been running a long time
        seen.append(rig.engine.residency_snapshot())

    rig.first.during = _look
    rig.at(10.0).transcribe(AUDIO)
    assert seen == [{"idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 0.0}]


def test_an_unloaded_model_reports_no_idle_countdown() -> None:
    rig = _Rig(300)
    assert rig.at(300.0).detach_if_idle() is rig.first
    snap = rig.at(900.0).residency_snapshot()
    assert snap == {"idle_unload_s": 300, "loaded": False, "loading": False, "idle_s": None}


def test_a_reload_in_flight_reports_loading_and_not_loaded() -> None:
    rig = _Rig(300)
    rig.at(300.0).detach_if_idle()
    rig.at(400.0).transcribe(AUDIO)             # the press after the unload reloads
    assert rig.seen_during_load == [
        {"idle_unload_s": 300, "loaded": False, "loading": True, "idle_s": None}
    ]
    assert rig.at(401.0).residency_snapshot() == {
        "idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 1.0,
    }


def test_the_snapshot_never_waits_on_the_engine_lock() -> None:
    """A status poll runs under the daemon lock; it must not queue behind the engine's."""
    rig = _Rig(300)
    held, release = threading.Event(), threading.Event()

    def _hold() -> None:
        with rig.engine._cond:
            held.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=_hold, daemon=True)
    holder.start()
    try:
        assert held.wait(timeout=10)
        snap = rig.at(60.0).residency_snapshot()   # would block here if it waited
        assert not release.is_set(), "the lock was still held while the snapshot was read"
    finally:
        release.set()
        holder.join(timeout=10)
    assert snap == {"idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 60.0}


def test_the_snapshot_does_not_disturb_the_trackers_clock_check() -> None:
    """`idle_s()` advances the monotonic check; the status read must not, or a racing
    decode stamped a moment earlier would raise "time ran backwards"."""
    rig = _Rig(300)
    rig.at(500.0).residency_snapshot()
    rig.now[0] = 200.0
    rig.engine.touch()          # earlier than the snapshot's reading: must not raise


def test_last_use_reads_no_clock_and_records_nothing() -> None:
    tracker = IdleTracker(with_stt_idle_unload(60))
    assert tracker.last_use(STT_UNIT) is None
    tracker.mark_loaded(STT_UNIT, now=5.0)
    tracker.touch(STT_UNIT, now=9.0)
    assert tracker.last_use(STT_UNIT) == 9.0
    tracker.touch(STT_UNIT, now=9.5)    # still monotonic after the read
    tracker.mark_unloaded(STT_UNIT)
    assert tracker.last_use(STT_UNIT) is None
    with pytest.raises(KeyError):
        tracker.last_use("no-such-unit")


# ---- the payload, in the daemon's status reply ----------------------------------------


def test_at_the_default_the_status_block_is_null() -> None:
    d = _daemon()
    assert d._config.stt.idle_unload_s == 0
    status = d._handle_status(None)
    assert "stt_residency" in status, "a literal key, so the report guard can classify it"
    assert status["stt_residency"] is None


def test_the_status_reply_carries_each_state() -> None:
    rig = _Rig(300)
    d = _daemon(rig)
    rig.at(45.0)
    assert d._handle_status(None)["stt_residency"] == {
        "idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 45.0,
    }
    rig.at(300.0).detach_if_idle()
    assert d._handle_status(None)["stt_residency"] == {
        "idle_unload_s": 300, "loaded": False, "loading": False, "idle_s": None,
    }


def test_the_status_reply_is_never_held_up_by_the_engine_lock() -> None:
    rig = _Rig(300)
    d = _daemon(rig)
    held, release = threading.Event(), threading.Event()

    def _hold() -> None:
        with rig.engine._cond:
            held.set()
            release.wait(timeout=10)

    holder = threading.Thread(target=_hold, daemon=True)
    holder.start()
    try:
        assert held.wait(timeout=10)
        block = d._handle_status(None)["stt_residency"]
        assert not release.is_set()
    finally:
        release.set()
        holder.join(timeout=10)
    assert block is not None and block["loaded"] is True


def test_a_snapshot_that_raises_costs_the_block_not_the_reply() -> None:
    class _Broken:
        def residency_snapshot(self):
            raise RuntimeError("boom")

    d = _daemon()
    d._idle_unload_engine = _Broken()  # type: ignore[assignment]
    status = d._handle_status(None)
    assert status["stt_residency"] is None and status["state"]


def test_the_block_holds_no_string_and_survives_the_report_redactor() -> None:
    """Numbers and booleans only, so `redact_status` passes it through untouched."""
    rig = _Rig(300)
    for t, act in ((45.0, None), (300.0, "unload")):
        if act == "unload":
            rig.at(t).detach_if_idle()
        block = rig.at(t).residency_snapshot()
        assert set(block) == _KEYS
        assert not any(isinstance(v, str) for v in block.values()), block
        assert redact_status({"stt_residency": block}) == {"stt_residency": block}


# ---- what the user reads: one phrase for `status` and the tray -------------------------


@pytest.mark.parametrize("block", [
    None,
    {},
    "loaded",
    {"idle_unload_s": 0, "loaded": True, "loading": False, "idle_s": None},
    {"idle_unload_s": True, "loaded": True, "loading": False, "idle_s": 1.0},
    {"idle_unload_s": math.nan, "loaded": True, "loading": False, "idle_s": 1.0},
    {"idle_unload_s": "300", "loaded": True, "loading": False, "idle_s": 1.0},
])
def test_nothing_is_said_when_idle_unload_is_off_or_the_shape_is_unknown(block) -> None:
    assert describe_stt_residency(block) is None


def test_the_phrase_for_each_state() -> None:
    base = {"idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 45.4}
    assert describe_stt_residency(base) == "loaded, idle 45 s of 300 s"
    assert describe_stt_residency({**base, "loaded": False, "idle_s": None}) == (
        "unloaded after 300 s idle — reloads on the next press"
    )
    assert describe_stt_residency({**base, "loaded": False, "loading": True, "idle_s": None}) == (
        "reloading — the next words wait for it"
    )
    # Loaded but no idle figure (e.g. a NaN): the keep-alive, never a made-up number.
    assert describe_stt_residency({**base, "idle_s": math.nan}) == (
        "loaded, released after 300 s idle"
    )


def test_the_status_lines_add_one_memory_line_only_under_idle_unload() -> None:
    reply = {"model": "base.en", "engine": "faster-whisper", "engine_model": "base.en"}
    assert render_engine_status_lines({**reply, "stt_residency": None}) == [
        "  model:    base.en (faster-whisper)"
    ]
    lines = render_engine_status_lines({**reply, "stt_residency": {
        "idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 45.0,
    }})
    assert lines == [
        "  model:    base.en (faster-whisper)",
        "  memory:   speech model loaded, idle 45 s of 300 s",
    ]
    lines = render_engine_status_lines({**reply, "stt_residency": {
        "idle_unload_s": 300, "loaded": False, "loading": False, "idle_s": None,
    }})
    assert lines[-1] == (
        "  memory:   speech model unloaded after 300 s idle — reloads on the next press"
    )


def test_yazses_status_prints_the_memory_line(monkeypatch) -> None:
    from yazses import cli

    reply = {
        "state": "idle", "hotkey": "right_ctrl", "model": "base.en",
        "injection_backend": "WtypeInjector", "uptime_s": 5.0, "ready": True,
        "engine": "faster-whisper", "engine_model": "base.en", "engine_fallback": None,
        "stt_residency": {"idle_unload_s": 300, "loaded": False, "loading": False,
                          "idle_s": None},
    }

    class _Client:
        def call(self, _method, **_kw):
            return reply

    class _Platform:
        name = "linux"

        class lifecycle:  # noqa: N801 - a stand-in namespace
            @staticmethod
            def read_pid():
                return 1234

            @staticmethod
            def is_running():
                return True

        class paths:  # noqa: N801
            ipc_socket = "/tmp/nope.sock"
            data_dir = "/tmp"
            config_file = "/tmp/config.toml"

        @staticmethod
        def ipc_client_factory(_s):
            return _Client()

    monkeypatch.setattr(cli, "get_platform", lambda: _Platform())
    out = CliRunner().invoke(cli.app, ["status"]).output
    assert "memory:   speech model unloaded after 300 s idle — reloads on the next press" in out

    reply["stt_residency"] = None
    out = CliRunner().invoke(cli.app, ["status"]).output
    assert "memory:" not in out, "the default install sees no new line"


# ---- the tray ---------------------------------------------------------------------------


_LOADED = {"idle_unload_s": 300, "loaded": True, "loading": False, "idle_s": 45.0}


def test_the_tooltip_carries_the_same_phrase() -> None:
    _, tooltip = icon_spec({"state": "idle", "hotkey": "right_ctrl", "stt_residency": _LOADED})
    assert tooltip.splitlines()[-1] == "Speech model: loaded, idle 45 s of 300 s"


def test_the_tooltip_is_unchanged_at_the_default() -> None:
    plain = icon_spec({"state": "idle", "hotkey": "right_ctrl"})
    assert icon_spec({"state": "idle", "hotkey": "right_ctrl", "stt_residency": None}) == plain
    assert "Speech model" not in plain[1]


def test_the_menu_model_carries_the_line() -> None:
    assert build_menu_model({"state": "idle", "stt_residency": _LOADED}, [], "").residency == (
        "Speech model: loaded, idle 45 s of 300 s"
    )
    assert build_menu_model({"state": "idle"}, [], "").residency is None
    assert residency_line({"stt_residency": None}) is None


def test_the_shared_tray_bridge_carries_the_block_and_the_model_stays_hashable() -> None:
    model = TrayModel(stt_residency=dict(_LOADED))
    status = status_from_model(model)
    assert status["stt_residency"] == _LOADED
    assert icon_spec(status)[1].endswith("Speech model: loaded, idle 45 s of 300 s")
    hash(model)  # a frozen dataclass holding a dict must still hash
    assert status_from_model(TrayModel())["stt_residency"] is None
