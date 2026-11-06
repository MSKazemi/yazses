"""What Glance-Type can and cannot do on this session, as a list -- EYE-WAYLAND-001 (#418).

`gaze/target_semantics.py` already decides what a gaze target *is* per session. This file
pins the user-facing consequence, ``glance_type_abilities``: one row per thing a user would
try (dictate to the looked-at window, "focus/minimize this", "close this", calibrate) plus
the pointer, which is reported as a separate feature and never as a gaze target.

Three properties matter, and each would drift silently without a test:

* **Wayland is fully decided.** Every Wayland session says the same thing whatever the
  ``[gaze]`` flags are, and "close this" is refused, never sent to the focused window.
* **A granted pointer permission changes nothing.** The pointer row is the only row that
  reads the pointer capability.
* **The report matches the code.** On X11 the "close this" rows depend on
  ``confirm_destructive`` and ``refuse_destructive_fallback``; the daemon's own
  ``_try_deixis`` is run with a fake targeter for every combination and the report must
  agree with what it actually did.

No compositor, D-Bus, camera or subprocess is touched.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config, GazeConfig
from yazses.gaze.route import RouteDecision
from yazses.gaze.target_capabilities import Capability, CapabilityFact, Support
from yazses.gaze.target_semantics import (
    GazeTargetPlan,
    TargetBasis,
    abilities_summary,
    glance_type_abilities,
    plan_gaze_target,
)
from yazses.handsfree.observability import (
    HandsFreeFacts,
    as_payload,
    facts_from_payload,
    health_rows,
)
from yazses.handsfree.panel import merge_facts
from yazses.handsfree.probe import gaze_target_facts
from yazses.platform.base import HostInfo

ROOT = Path(__file__).resolve().parent.parent
WAYLAND = ("wayland_gnome", "wayland_kde", "wayland_other")
FLAGS = (True, False, None)
GNOME_WAYLAND = {
    "XDG_SESSION_TYPE": "wayland",
    "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
    "WAYLAND_DISPLAY": "wayland-0",
}


def _by_key(abilities) -> dict:
    return {a.key: a for a in abilities}


# ---- Wayland: decided, whatever the flags --------------------------------------------


@pytest.mark.parametrize("session", WAYLAND)
@pytest.mark.parametrize("confirm", FLAGS)
@pytest.mark.parametrize("refuse", FLAGS)
def test_wayland_glance_type_does_nothing_and_says_so(session, confirm, refuse) -> None:
    plan = plan_gaze_target(session, xdotool_available=True)
    rows = _by_key(glance_type_abilities(
        plan, confirm_destructive=confirm, refuse_destructive_fallback=refuse))

    assert set(rows) == {"route_dictation", "gaze_commands", "close", "calibrate", "pointer"}
    assert not rows["route_dictation"].can
    assert "focus" in rows["route_dictation"].outcome  # it goes to the focused window
    assert not rows["gaze_commands"].can
    assert rows["gaze_commands"].outcome.startswith("refused")
    assert not rows["close"].can
    assert "never sent to the focused window" in rows["close"].outcome
    assert not rows["calibrate"].can


@pytest.mark.parametrize("session", WAYLAND)
def test_the_wayland_answer_does_not_depend_on_the_gaze_flags(session) -> None:
    plan = plan_gaze_target(session)
    answers = {
        glance_type_abilities(plan, confirm_destructive=c, refuse_destructive_fallback=r)
        for c in FLAGS for r in FLAGS
    }
    assert len(answers) == 1


@pytest.mark.parametrize("session", WAYLAND)
def test_the_pointer_is_reported_as_a_separate_feature_not_a_target(session) -> None:
    rows = _by_key(glance_type_abilities(plan_gaze_target(session)))
    pointer = rows["pointer"]
    assert pointer.can  # consent via the RemoteDesktop portal
    assert "separate" in pointer.label.lower() or "separate" in pointer.outcome
    assert "not" in pointer.outcome and "gaze target" in pointer.outcome


def test_a_granted_pointer_permission_does_not_make_close_this_act() -> None:
    """Pointer injection as plain ``yes`` on a Wayland row: every gaze row is unchanged."""
    real = plan_gaze_target("wayland_gnome")
    granted = tuple(
        CapabilityFact(f.capability, Support.YES, f.via, f.sources)
        if f.capability is Capability.POINTER_INJECTION else f
        for f in real.capabilities
    )
    plan = dataclasses.replace(real, capabilities=granted)
    before = _by_key(glance_type_abilities(real))
    after = _by_key(glance_type_abilities(plan))
    for key in ("route_dictation", "gaze_commands", "close", "calibrate"):
        assert before[key] == after[key]


# ---- the other buckets ---------------------------------------------------------------


@pytest.mark.parametrize("session", ["windows", "macos"])
def test_an_unassessed_os_has_no_pointer_row_and_no_target(session) -> None:
    rows = _by_key(glance_type_abilities(plan_gaze_target(session)))
    assert "pointer" not in rows
    assert not any(a.can for a in rows.values())


def test_headless_cannot_move_a_pointer_either() -> None:
    rows = _by_key(glance_type_abilities(plan_gaze_target("headless")))
    assert not rows["pointer"].can


def test_x11_without_xdotool_is_the_same_refusal() -> None:
    rows = _by_key(glance_type_abilities(plan_gaze_target("x11", xdotool_available=False)))
    assert not rows["close"].can
    assert "never sent to the focused window" in rows["close"].outcome


def test_x11_lists_both_close_this_cases_separately() -> None:
    rows = _by_key(glance_type_abilities(plan_gaze_target("x11", xdotool_available=True)))
    assert {"close_gazed", "close_fallback"} <= set(rows)
    assert "close" not in rows
    assert rows["route_dictation"].can and rows["calibrate"].can and rows["gaze_commands"].can


def test_x11_gaze_commands_name_the_deixis_key_they_depend_on() -> None:
    """With ``[gaze] deixis = false`` the daemon never tries a gaze command; say so."""
    rows = _by_key(glance_type_abilities(plan_gaze_target("x11", xdotool_available=True)))
    assert "[gaze] deixis" in rows["gaze_commands"].outcome
    assert "[gaze] deixis" in rows["close_gazed"].outcome
    assert "[gaze] deixis" in rows["close_fallback"].outcome


def test_an_unknown_flag_names_the_key_instead_of_guessing() -> None:
    """A caller that does not know a flag (an older daemon's wire) is told what decides."""
    rows = _by_key(glance_type_abilities(plan_gaze_target("x11", xdotool_available=True)))
    assert "refuse_destructive_fallback" in rows["close_fallback"].outcome
    assert "confirm_destructive" in rows["close_gazed"].outcome


# ---- the report matches what the daemon does -----------------------------------------


class _FakeTargeter:
    def __init__(self, decision):
        self.last_decision = decision
        self.actions: list = []

    def window_action(self, action, target):
        self.actions.append((action, target))
        return True


def _daemon(**gaze):
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    cfg = dataclasses.replace(
        Config(), gaze=dataclasses.replace(GazeConfig(), enabled=True, deixis=True, **gaze)
    )
    return Daemon(config=cfg, platform=get_platform())


@pytest.mark.parametrize("confirm", [True, False])
@pytest.mark.parametrize("refuse", [True, False])
@pytest.mark.parametrize("used_gaze", [True, False])
def test_the_x11_close_this_rows_agree_with_try_deixis(mocker, confirm, refuse, used_gaze) -> None:
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(confirm_destructive=confirm, refuse_destructive_fallback=refuse)
    d._gaze_targeter = _FakeTargeter(RouteDecision("w1", used_gaze, used_gaze))
    assert d._try_deixis("close this", {})

    closed = d._gaze_targeter.actions == [("close", "w1")]
    # A confirm toast carries actions (`_confirm_deixis`); a refusal (`_deixis_cannot_act`)
    # does not, so the two cannot be mistaken for each other.
    asked = notify.called and not closed and bool(notify.call_args.kwargs.get("actions"))
    refused = notify.called and not closed and not notify.call_args.kwargs.get("actions")

    rows = _by_key(glance_type_abilities(
        plan_gaze_target("x11", xdotool_available=True),
        confirm_destructive=confirm, refuse_destructive_fallback=refuse,
    ))
    row = rows["close_gazed" if used_gaze else "close_fallback"]
    if closed:
        assert row.can and "asks" not in row.outcome
        assert (row.outcome.startswith("runs"))
    elif used_gaze:
        assert asked and row.can and row.outcome.startswith("asks first")
    else:
        assert refused and not row.can and row.outcome.startswith("refused")


# ---- the surfaces: doctor/status row, the wire, the merge, `gaze status` -------------


def test_the_summary_is_one_line_with_every_row() -> None:
    abilities = glance_type_abilities(plan_gaze_target("wayland_kde"))
    line = abilities_summary(abilities)
    assert "\n" not in line
    assert line.count("; ") == len(abilities) - 1
    assert abilities_summary(()) == ""


def test_the_doctor_row_says_what_glance_type_does_and_it_survives_the_wire() -> None:
    facts = gaze_target_facts(
        HandsFreeFacts(features_requested=("gaze",)),
        environ=GNOME_WAYLAND, fixed_session=lambda: None, xdotool_available=lambda: True,
    )
    assert "never sent to the focused window" in facts.gaze_target_abilities
    row = {r.label: r for r in health_rows(facts)}["Gaze target"]
    assert facts.gaze_target_abilities in row.reason

    rebuilt = facts_from_payload(as_payload(facts))
    assert rebuilt is not None
    assert rebuilt.gaze_target_abilities == facts.gaze_target_abilities


def test_the_probe_passes_the_users_flags_through() -> None:
    facts = gaze_target_facts(
        HandsFreeFacts(features_requested=("gaze",)),
        environ={"XDG_SESSION_TYPE": "x11"}, fixed_session=lambda: None,
        xdotool_available=lambda: True,
        confirm_destructive=True, refuse_destructive_fallback=True,
    )
    assert "refuse_destructive_fallback" not in facts.gaze_target_abilities
    assert "no gaze pick" in facts.gaze_target_abilities


def test_an_older_daemon_without_the_key_reads_as_empty() -> None:
    rebuilt = facts_from_payload({
        "features_requested": ["gaze"], "gaze_target_available": False,
        "gaze_target_reason": "some reason",
    })
    assert rebuilt is not None and rebuilt.gaze_target_abilities == ""


# Where each process is: `doctor` over SSH (no DISPLAY, no XDG_SESSION_TYPE), a desktop
# daemon, a GNOME Wayland panel, and a service daemon whose environment lacks DISPLAY.
SESSIONS = {
    "x11": {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
    "wayland_gnome": GNOME_WAYLAND,
    "headless": {},
}


def _facts(env, **flags) -> HandsFreeFacts:
    return gaze_target_facts(
        HandsFreeFacts(features_requested=("gaze",)),
        environ=env, fixed_session=lambda: None, xdotool_available=lambda: True, **flags,
    )


def _gaze_row(facts: HandsFreeFacts):
    return {r.label: r for r in health_rows(facts)}["Gaze target"]


@pytest.mark.parametrize("static_session", SESSIONS)
@pytest.mark.parametrize("live_session", SESSIONS)
@pytest.mark.parametrize("refuse", [True, False])
def test_the_merged_row_never_pairs_one_sessions_reason_with_anothers_abilities(
    static_session, live_session, refuse
) -> None:
    """`doctor`/the panel and the daemon can classify different sessions; the row must not mix them.

    The static and live sides come from different processes and so from different
    environments. Whatever the merge picks, the abilities it prints must be the ones of
    the plan whose reason it prints -- the live daemon's, which is the process that acts.
    """
    static = _facts(SESSIONS[static_session], confirm_destructive=True,
                    refuse_destructive_fallback=refuse)
    # The daemon passes its own [gaze] flags (`Daemon._handsfree_payload`).
    live = _facts(SESSIONS[live_session], confirm_destructive=True,
                  refuse_destructive_fallback=refuse)
    merged = merge_facts(static, live)
    assert merged.gaze_target_reason == live.gaze_target_reason
    assert merged.gaze_target_abilities == live.gaze_target_abilities


def test_doctor_over_ssh_does_not_claim_a_refusal_the_x11_daemon_does_not_make() -> None:
    """The reproduced case: headless `doctor`, X11 daemon with the default fallback."""
    static = _facts({}, confirm_destructive=True, refuse_destructive_fallback=False)
    live = _facts(SESSIONS["x11"], confirm_destructive=True, refuse_destructive_fallback=False)
    row = _gaze_row(merge_facts(static, live))
    assert row.reason.startswith("X11:")
    assert "never sent to the focused window" not in row.reason
    assert "no gaze pick: closes the focused window" in row.reason


def test_an_x11_panel_does_not_promise_what_a_headless_service_daemon_refuses() -> None:
    static = _facts(SESSIONS["x11"], confirm_destructive=True, refuse_destructive_fallback=False)
    live = _facts({}, confirm_destructive=True, refuse_destructive_fallback=False)
    row = _gaze_row(merge_facts(static, live))
    assert "headless" in row.reason
    assert "never sent to the focused window" in row.reason
    assert "closes the focused window" not in row.reason


def test_an_older_daemon_without_abilities_borrows_the_static_line_only_for_the_same_plan() -> None:
    static = _facts(SESSIONS["x11"], confirm_destructive=True, refuse_destructive_fallback=True)
    same = dataclasses.replace(
        _facts(SESSIONS["x11"]), gaze_target_abilities="")  # an older daemon's reply
    assert merge_facts(static, same).gaze_target_abilities == static.gaze_target_abilities
    other = dataclasses.replace(_facts({}), gaze_target_abilities="")
    assert merge_facts(static, other).gaze_target_abilities == ""
    # No live answer about the target at all: the static line stands.
    assert merge_facts(static, None).gaze_target_abilities == static.gaze_target_abilities
    unknown = HandsFreeFacts(features_requested=("gaze",))
    assert merge_facts(static, unknown).gaze_target_abilities == static.gaze_target_abilities


def test_the_daemon_status_reports_its_own_gaze_flags(monkeypatch) -> None:
    """The live line is config-aware: the daemon passes the flags it actually acts on."""
    from yazses.handsfree import probe as probe_mod

    seen: dict = {}
    real = probe_mod.gaze_target_facts

    def spy(facts, **kw):
        seen.update(kw)
        return real(facts, environ=SESSIONS["x11"], fixed_session=lambda: None,
                    xdotool_available=lambda: True, **kw)

    monkeypatch.setattr(probe_mod, "gaze_target_facts", spy)
    d = _daemon(confirm_destructive=False, refuse_destructive_fallback=True)
    payload = d._handsfree_payload()
    assert seen == {"confirm_destructive": False, "refuse_destructive_fallback": True}
    assert payload is not None
    line = str(payload["gaze_target_abilities"])
    assert "no gaze pick: refused" in line
    assert "runs without asking" in line
    assert "refuse_destructive_fallback" not in line


def test_doctor_hands_its_gaze_flags_to_the_probe(monkeypatch) -> None:
    from yazses.handsfree import probe as probe_mod
    from yazses.system.doctor import _handsfree_checks

    seen: dict = {}
    real = probe_mod.gaze_target_facts

    def spy(facts, **kw):
        seen.update(kw)
        return real(facts, environ=GNOME_WAYLAND, fixed_session=lambda: None,
                    xdotool_available=lambda: True)

    monkeypatch.setattr(probe_mod, "gaze_target_facts", spy)
    cfg = Config()
    cfg.gaze.enabled = True
    cfg.gaze.refuse_destructive_fallback = True
    cfg.gaze.confirm_destructive = False
    platform = SimpleNamespace(paths=SimpleNamespace(data_dir=Path("/nonexistent-yazses")))
    rows = _handsfree_checks(cfg, platform, None, unwired=frozenset(),
                             read_context=lambda: None, live_facts=False)
    assert seen.get("refuse_destructive_fallback") is True
    assert seen.get("confirm_destructive") is False
    detail = {label: detail for label, _s, detail in rows}["Gaze target"]
    assert "never sent to the focused window" in detail


@pytest.fixture
def linux_host(monkeypatch):
    host = HostInfo(platform_name="linux", os_name="Ubuntu", os_version="24.04")
    monkeypatch.setattr("yazses.platform.factory.describe_host", lambda: host)
    return host


def _gaze_status(monkeypatch, tmp_path, env: dict[str, str], **gaze) -> str:
    for key in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    cfg = dataclasses.replace(
        Config(), gaze=dataclasses.replace(GazeConfig(), enabled=True, **gaze))
    platform = SimpleNamespace(
        paths=SimpleNamespace(config_file=tmp_path / "config.toml", data_dir=tmp_path)
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    monkeypatch.setattr("yazses.config.load_config", lambda _p: cfg)
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)
    result = CliRunner().invoke(cli.app, ["gaze", "status"])
    assert result.exit_code == 0, result.output
    return result.output


def test_gaze_status_lists_what_glance_type_does_on_wayland(
    monkeypatch, tmp_path, linux_host
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: None)
    out = _gaze_status(monkeypatch, tmp_path, GNOME_WAYLAND)
    assert "what Glance-Type does on this session (wayland_gnome):" in out
    for ability in glance_type_abilities(plan_gaze_target("wayland_gnome")):
        assert f"{ability.label}: {ability.outcome}" in out


def test_gaze_status_on_x11_reports_the_users_fallback_setting(
    monkeypatch, tmp_path, linux_host
) -> None:
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr("yazses.gaze.desktop.build_desktop", lambda: None, raising=False)
    out = _gaze_status(monkeypatch, tmp_path, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"},
                       refuse_destructive_fallback=True)
    rows = _by_key(glance_type_abilities(
        plan_gaze_target("x11", xdotool_available=True),
        confirm_destructive=True, refuse_destructive_fallback=True,
    ))
    assert f"{rows['close_fallback'].label}: {rows['close_fallback'].outcome}" in out
    assert "refused" in rows["close_fallback"].outcome


def test_the_plan_type_is_unchanged() -> None:
    """The new list is derived, not stored: ``GazeTargetPlan`` gains no field."""
    names = {f.name for f in dataclasses.fields(GazeTargetPlan)}
    assert names == {"session", "basis", "reason", "remedy", "capabilities"}
    assert TargetBasis.NONE.value == "none"
