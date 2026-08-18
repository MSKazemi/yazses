"""Meeting Mode from the tray icon — the entries, and what a click actually does.

Meeting Mode is the only capability with no key to hold: it runs hands-free for up to
an hour, and until now the only way to begin or end one was ``yazses meeting start`` in
a terminal — which is exactly what nobody has open during a meeting.

Two things are worth guarding and they are different in kind. `meeting_entries` is a
*prediction* — it greys out a click that cannot work and says why — and the daemon
remains the authority. So these tests check that the prediction never contradicts the
daemon's own guard, and separately that a refusal is passed through verbatim rather than
paraphrased into something less actionable.
"""

from __future__ import annotations

import pytest

from yazses.platform.base import TrayModel, TrayState
from yazses.tray.controller import TrayController
from yazses.tray.meeting import START, STOP, call_meeting, describe, run_meeting_action
from yazses.tray.menu import (
    MEETING_START_LABEL,
    MEETING_STOP_LABEL,
    meeting_entries,
    status_from_model,
)


def entries(**status):
    """The two entries keyed by label, for readable assertions."""
    return {e.label: e for e in meeting_entries(status)}


# ---- the entries -----------------------------------------------------------


def test_both_entries_are_always_present_in_a_fixed_order():
    """Two of the three trays build their menu once and cannot add a row later.

    So the shape must not depend on state — only the enabled flag may move. A model
    that returned one entry while idle and another while recording would be impossible
    for the rumps and pystray menus to render at all.
    """
    for status in ({}, {"state": "meeting"}, {"state": "recording"}, {"ready": False}):
        got = [e.label for e in meeting_entries(status)]
        assert got == [MEETING_START_LABEL, MEETING_STOP_LABEL], status


def test_idle_offers_start_and_refuses_stop():
    got = entries(state="idle", meeting_enabled=True, ready=True)
    assert got[MEETING_START_LABEL].enabled
    assert not got[MEETING_STOP_LABEL].enabled
    assert "No meeting is running" in got[MEETING_STOP_LABEL].reason


def test_a_running_meeting_offers_stop_and_refuses_start():
    got = entries(state="meeting", meeting_enabled=True, ready=True)
    assert got[MEETING_STOP_LABEL].enabled
    assert not got[MEETING_START_LABEL].enabled
    assert "already running" in got[MEETING_START_LABEL].reason


def test_meeting_active_alone_is_enough_to_offer_stop():
    """`state` is not the only witness: it is briefly something else around a stop."""
    got = entries(state="idle", meeting_active=True, meeting_enabled=True, ready=True)
    assert got[MEETING_STOP_LABEL].enabled


def test_the_feature_being_off_greys_out_both_and_says_where_to_turn_it_on():
    """The whole point of showing a disabled entry rather than hiding it.

    A hidden entry teaches nothing; this one names the surface that fixes it. Meeting
    Mode is off by default, so this is the state most users meet first.
    """
    got = entries(state="idle", meeting_enabled=False, ready=True)
    assert not got[MEETING_START_LABEL].enabled
    assert not got[MEETING_STOP_LABEL].enabled
    assert "Settings" in got[MEETING_START_LABEL].reason


def test_finalizing_greys_out_start_even_though_capture_has_ended():
    """The state that is invisible without the daemon publishing it.

    After a stop the daemon is back to IDLE while diarization and the notes run on a
    thread. Reading only `state`, the menu would cheerfully offer a new meeting on top
    of a post-pass that has not finished writing the last one.
    """
    got = entries(state="idle", meeting_enabled=True, ready=True, meeting_finalizing=True)
    assert not got[MEETING_START_LABEL].enabled
    assert "finishing" in got[MEETING_START_LABEL].reason.lower()


def test_a_busy_daemon_refuses_start_naming_the_state():
    got = entries(state="recording", meeting_enabled=True, ready=True)
    assert not got[MEETING_START_LABEL].enabled
    assert "recording" in got[MEETING_START_LABEL].reason


def test_still_loading_refuses_both():
    got = entries(state="loading", meeting_enabled=True, ready=False)
    assert not got[MEETING_START_LABEL].enabled
    assert not got[MEETING_STOP_LABEL].enabled
    assert "starting up" in got[MEETING_START_LABEL].reason


def test_a_disabled_entry_always_carries_a_reason():
    """A greyed-out row with no explanation is worse than no row.

    The user is left choosing between "broken" and "not allowed", and it is neither.
    """
    for status in (
        {},
        {"state": "idle", "meeting_enabled": False},
        {"state": "idle", "meeting_enabled": True, "ready": False},
        {"state": "meeting", "meeting_enabled": True},
        {"state": "recording", "meeting_enabled": True},
        {"state": "idle", "meeting_enabled": True, "meeting_finalizing": True},
    ):
        for entry in meeting_entries(status):
            if not entry.enabled:
                assert entry.reason, f"{entry.label} greyed out with no reason: {status}"


def test_an_older_daemon_that_never_sends_the_flag_is_not_greyed_out():
    """`meeting_enabled` absent means "this daemon did not say", not "off".

    Reading a missing key as False would disable the entry on a daemon where Meeting
    Mode works perfectly — a downgrade delivered by an upgrade. The daemon refuses if
    the optimism is wrong, and its refusal names the fix.
    """
    got = entries(state="idle")
    assert got[MEETING_START_LABEL].enabled


def test_the_prediction_matches_the_daemons_own_start_guard():
    """`_handle_meeting_start` allows a start only from IDLE or PAUSED.

    Read off the daemon's TrayState enum rather than a hand-written list, so a new
    state added there fails here instead of silently becoming clickable.
    """
    allowed = {TrayState.IDLE, TrayState.PAUSED}
    for state in TrayState:
        got = entries(state=state.value, meeting_enabled=True, ready=True)
        start_ok = got[MEETING_START_LABEL].enabled
        if state is TrayState.MEETING:
            assert not start_ok, "a meeting cannot start on top of a meeting"
        else:
            assert start_ok is (state in allowed), state


# ---- the first link: the daemon has to publish any of this at all ----------


def _daemon(**meeting):
    from yazses.config import Config
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = Config()
    for key, value in meeting.items():
        setattr(cfg.meeting, key, value)
    return Daemon(config=cfg, platform=get_platform())


def _status(daemon):
    from yazses.ipc.protocol import Request

    return daemon._handle_status(Request(method="status"))


def test_the_daemon_publishes_whether_meeting_mode_is_on():
    """Without this the tray cannot tell "off" from "on and idle".

    Everything downstream was written and tested before this line existed, and all of
    it would still have passed: the entry would simply never grey out, and clicking it
    would fail with a message on a feature the user was never told was off.
    """
    assert _status(_daemon(enabled=True))["meeting_enabled"] is True
    assert _status(_daemon(enabled=False))["meeting_enabled"] is False


def test_the_daemon_publishes_active_and_finalizing():
    daemon = _daemon(enabled=True)
    status = _status(daemon)
    assert status["meeting_active"] is False
    assert status["meeting_finalizing"] is False

    daemon._meeting_controller = object()
    daemon._meeting_finalizing = True
    status = _status(daemon)
    assert status["meeting_active"] is True
    assert status["meeting_finalizing"] is True


def test_the_published_status_drives_the_entries_end_to_end():
    """The whole chain in one assertion: daemon → status → entries.

    Each link is tested on its own above; this is the one that fails if a link is
    correct in isolation and connected to nothing.
    """
    got = entries(**_status(_daemon(enabled=False)))
    assert not got[MEETING_START_LABEL].enabled
    assert "Settings" in got[MEETING_START_LABEL].reason


# ---- the bridge every tray goes through ------------------------------------


def test_the_shared_bridge_carries_the_meeting_fields():
    """Windows once kept a private status dict and lost fields that way (#63).

    A tray whose hand-built dict omitted these would show an entry that is greyed out
    forever, on that OS only.
    """
    status = status_from_model(
        TrayModel(meeting_enabled=True, meeting_active=True, meeting_finalizing=False)
    )
    assert status["meeting_enabled"] is True
    assert status["meeting_active"] is True
    assert entries(**status)[MEETING_STOP_LABEL].enabled


# ---- what a click does -----------------------------------------------------


class _FakeClient:
    def __init__(self, reply=None, raises=None):
        self.reply = reply if reply is not None else {"ok": True}
        self.raises = raises
        self.calls: list[str] = []

    def call(self, method, **params):
        self.calls.append(method)
        if self.raises is not None:
            raise self.raises
        return self.reply


def test_the_controller_calls_the_right_ipc_methods():
    client = _FakeClient()
    ctrl = TrayController(client)
    ctrl.start_meeting()
    ctrl.stop_meeting()
    assert client.calls == [START, STOP]


def test_an_unreachable_daemon_is_an_answer_not_an_exception():
    """A menu click has no exception handler above it; on pystray it stops the icon."""
    result = call_meeting(START, client=_FakeClient(raises=OSError("no socket")))
    assert result["ok"] is False
    assert "no socket" in result["reason"]


def test_an_unknown_action_is_refused_rather_than_sent():
    client = _FakeClient()
    assert call_meeting("meeting_delete_everything", client=client)["ok"] is False
    assert client.calls == []


def test_a_refusal_is_passed_through_verbatim():
    """The daemon's wording names the command that fixes it; a paraphrase would not."""
    reason = "meeting mode is off; run `yazses features enable meeting`"
    title, body = run_meeting_action(START, client=_FakeClient({"ok": False, "reason": reason}))
    assert title == "YazSes"
    assert body == reason


def test_the_start_warning_survives_to_the_notification():
    """The one place a user is told the transcript will have no speaker names.

    The daemon emits it when `[meeting] diarize` is on and the models are missing.
    Losing it here means an unattributed transcript that nothing ever explained.
    """
    _, body = run_meeting_action(
        START,
        client=_FakeClient(
            {"ok": True, "meeting_id": "20260818-120000", "warning": "Speaker labels are on but…"}
        ),
    )
    assert "20260818-120000" in body
    assert "Speaker labels are on but…" in body


def test_stopping_says_the_work_continues_after_the_click():
    """Capture ends immediately; the transcript does not. Silence here reads as "lost"."""
    _, body = run_meeting_action(STOP, client=_FakeClient({"ok": True, "meeting_id": "x"}))
    assert "transcrib" in body.lower()


def test_describe_is_pure_and_never_raises_on_a_junk_reply():
    """It sits on a click path, and an IPC reply is not something to trust blindly."""
    for reply in ({}, {"ok": True}, {"ok": True, "meeting_id": None}, {"ok": False}):
        for action in (START, STOP):
            title, body = describe(action, reply)
            assert title and body


@pytest.mark.parametrize("action", [START, STOP])
def test_a_non_dict_reply_still_counts_as_ok(action):
    """IPC returns whatever the daemon sent; only a dict can carry a refusal."""
    assert call_meeting(action, client=_FakeClient(reply="done"))["ok"] is True


# ---- the static menus, checked structurally rather than by substring -------
#
# The parity guard in test_tray_settings_parity.py greps for a handler name, and that
# is not enough here. Wiring Stop to `MenuItem(MEETING_STOP_LABEL, None, enabled=False)`
# leaves both the label constant and the word `_meeting_clicked` in the file — the exact
# shape of the Windows "Help" entry that shipped clickable-by-nobody — so the substring
# check passes on a tray where a meeting cannot be ended. Verified by breaking it: the
# grep stayed green, the AST checks below went red.

_ROOT = __import__("pathlib").Path(__file__).resolve().parent.parent


def _tray_ast(os_name: str):
    import ast

    path = _ROOT / f"src/yazses/platform/{os_name}/tray.py"
    return ast.parse(path.read_text(encoding="utf-8"))


def test_the_windows_menu_gives_each_meeting_entry_its_own_live_handler():
    import ast

    handlers: dict[str, str] = {}
    for node in ast.walk(_tray_ast("windows")):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        func = ast.unparse(node.func)
        if not func.endswith("MenuItem"):
            continue
        label = ast.unparse(node.args[0])
        if label not in ("MEETING_START_LABEL", "MEETING_STOP_LABEL"):
            continue
        callback = ast.unparse(node.args[1]) if len(node.args) > 1 else "None"
        assert callback != "None", f"{label} is rendered with no callback"
        handlers[label] = callback

    assert set(handlers) == {"MEETING_START_LABEL", "MEETING_STOP_LABEL"}
    # Distinct calls, so Stop cannot be quietly pointed at start.
    assert handlers["MEETING_START_LABEL"] != handlers["MEETING_STOP_LABEL"]
    assert "stop" in handlers["MEETING_STOP_LABEL"]


def test_the_macos_menu_binds_each_meeting_label_to_its_own_action():
    """Comparing handler *names* is not enough, and this is not hypothetical.

    Pointing `_on_meeting_stop` at `_run_meeting("meeting_start")` leaves two distinct
    functions, two distinct `@rumps.clicked` labels and every substring intact — and a
    Stop entry that starts a second meeting. So the actions themselves are read out of
    each handler's body.
    """
    import ast

    bound: dict[str, set[str]] = {}
    for node in ast.walk(_tray_ast("macos")):
        if not isinstance(node, ast.FunctionDef):
            continue
        for deco in node.decorator_list:
            if not (isinstance(deco, ast.Call) and deco.args):
                continue
            if not ast.unparse(deco.func).endswith("clicked"):
                continue
            label = ast.unparse(deco.args[0])
            if label not in ("MEETING_START_LABEL", "MEETING_STOP_LABEL"):
                continue
            bound[label] = {
                arg.value
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                for arg in call.args
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
            }

    assert set(bound) == {"MEETING_START_LABEL", "MEETING_STOP_LABEL"}
    assert bound["MEETING_START_LABEL"] == {START}
    assert bound["MEETING_STOP_LABEL"] == {STOP}


@pytest.mark.parametrize("os_name", ["macos", "windows"])
def test_the_static_trays_do_not_block_their_ui_thread_on_a_meeting(os_name):
    """Starting a meeting builds a recorder and may construct a diarizer.

    Done inline, a rumps or pystray menu is frozen for the duration — and this is the
    click a user makes as a meeting is starting, when a beachball is least affordable.
    """
    source = (_ROOT / f"src/yazses/platform/{os_name}/tray.py").read_text(encoding="utf-8")
    assert 'name="tray-meeting"' in source
