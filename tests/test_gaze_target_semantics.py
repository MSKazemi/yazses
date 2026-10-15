"""What a gaze target IS on Wayland -- EYE-WAYLAND-001 (#418).

Glance-Type needs an absolute desktop pixel, the geometry of other applications' windows
and the right to focus one. X11 gives all three. A Wayland client gets none, and the
RemoteDesktop portal that gives YazSes *pointer injection* reveals none of them either.
`yazses.gaze.target_semantics` is the one place that says so; these tests pin the
consequences: on a session with no absolute position the answer is **abstention with a
reason**, at every layer that could otherwise guess.

The shapes a fake would hide, and are modelled here rather than assumed away:

* **`xdotool` is installed and works on a Wayland desktop.** It talks to XWayland, so it
  does not fail -- it returns a perfectly plausible window list that simply omits every
  native Wayland window. The backend's subprocess is therefore rigged to *succeed* with
  such a list, and the test is that nothing ever asks it.
* **`XDG_SESSION_TYPE` is absent.** logind sets it for the login session; a service or
  launcher that did not import it has `WAYLAND_DISPLAY` and `DISPLAY` and nothing else.
  The old check (`session and session != "x11"`) treated "absent" as "not Wayland".
* **A hand-edited or padded value** (`" Wayland\\n"`), and a nested compositor inside an
  Xorg session that exports `WAYLAND_DISPLAY` to its children.
"""
from __future__ import annotations

import dataclasses
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config, GazeConfig
from yazses.gaze.calibrate import calibration_blocker
from yazses.gaze.target_semantics import (
    WAYLAND_REASON,
    TargetBasis,
    classify_session,
    describe_gaze_target,
    plan_gaze_target,
)
from yazses.handsfree.observability import (
    HandsFreeFacts,
    as_payload,
    doctor_rows,
    facts_from_payload,
    health_rows,
    render_status_lines,
)
from yazses.handsfree.probe import gaze_target_facts
from yazses.platform.base import HostInfo

GNOME_WAYLAND = {
    "XDG_SESSION_TYPE": "wayland",
    "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
    "WAYLAND_DISPLAY": "wayland-0",
    "DISPLAY": ":0",
}
#: Exactly what a service sees on the same desktop when the session variable was not imported.
GNOME_WAYLAND_NO_SESSION_VAR = {
    "WAYLAND_DISPLAY": "wayland-0",
    "DISPLAY": ":0",
    "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
}


@pytest.fixture
def linux_host(monkeypatch):
    """`describe_host()` as a Linux box answers it: nothing fixed by the OS."""
    host = HostInfo(platform_name="linux", os_name="Ubuntu", os_version="24.04")
    monkeypatch.setattr("yazses.platform.factory.describe_host", lambda: host)
    return host


def _session(monkeypatch, env: dict[str, str]) -> None:
    for key in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


@pytest.fixture
def xdotool_that_would_answer(monkeypatch):
    """`xdotool`/`xrandr` installed and *succeeding*, as they do through XWayland.

    Any subprocess is recorded and answered with a plausible one-window X11 reply. A test
    passes by showing the planner never got as far as asking.
    """
    spawned: list[list[str]] = []

    def run(argv, **kwargs):
        spawned.append(list(argv))
        out = "1234\n" if argv[:2] == ["xdotool", "search"] else "1920 1080\n"
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    return spawned


# ---- the classifier (pure) -------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        (GNOME_WAYLAND, "wayland_gnome"),
        ({**GNOME_WAYLAND, "XDG_CURRENT_DESKTOP": "KDE"}, "wayland_kde"),
        ({**GNOME_WAYLAND, "XDG_CURRENT_DESKTOP": "sway"}, "wayland_other"),
        # The variable absent: WAYLAND_DISPLAY is the evidence, and DISPLAY (XWayland) is not.
        (GNOME_WAYLAND_NO_SESSION_VAR, "wayland_gnome"),
        ({"XDG_SESSION_TYPE": "tty", "WAYLAND_DISPLAY": "wayland-0"}, "wayland_other"),
        ({"XDG_SESSION_TYPE": "unspecified", "WAYLAND_DISPLAY": "wayland-1"}, "wayland_other"),
        ({"XDG_SESSION_TYPE": " Wayland\n"}, "wayland_other"),
        # An explicit x11 wins over a nested compositor's WAYLAND_DISPLAY.
        ({"XDG_SESSION_TYPE": "x11", "WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}, "x11"),
        ({"XDG_SESSION_TYPE": "X11"}, "x11"),
        ({"DISPLAY": ":0"}, "x11"),
        ({}, "headless"),
        ({"XDG_SESSION_TYPE": "tty"}, "headless"),
        ({"XDG_SESSION_TYPE": "tty", "DISPLAY": ":10"}, "headless"),  # ssh -X is not a desktop
    ],
)
def test_the_session_is_classified_from_evidence_not_from_one_variable(env, expected) -> None:
    assert classify_session(env) == expected


def test_an_os_fixed_session_beats_the_environment() -> None:
    assert classify_session(GNOME_WAYLAND, fixed_session="windows") == "windows"


# ---- the definition -------------------------------------------------------------


@pytest.mark.parametrize("session", ["wayland_gnome", "wayland_kde", "wayland_other"])
def test_on_wayland_a_gaze_target_is_nothing_and_the_plan_says_why(session) -> None:
    plan = plan_gaze_target(session, xdotool_available=True)  # a present xdotool changes nothing

    assert plan.basis is TargetBasis.NONE
    assert not plan.available
    assert (plan.absolute_position, plan.window_geometry, plan.window_focus) == (False,) * 3
    assert plan.reason == WAYLAND_REASON
    # The three missing capabilities are named, so the sentence is checkable, not a shrug.
    for word in ("global pointer position", "geometry", "focus"):
        assert word in plan.reason
    # Pointer injection and gaze targeting are separate capabilities (the issue's first
    # criterion): the remedy says the pointer permission does not change the answer.
    assert "pointer" in plan.remedy and "separate" in plan.remedy
    assert "X11" in plan.remedy


def test_x11_has_all_three_capabilities_when_xdotool_is_there() -> None:
    plan = plan_gaze_target("x11", xdotool_available=True)
    assert plan.basis is TargetBasis.SCREEN_WINDOWS
    assert (plan.absolute_position, plan.window_geometry, plan.window_focus) == (True,) * 3


def test_x11_without_xdotool_is_refused_but_an_unchecked_tool_is_not() -> None:
    assert not plan_gaze_target("x11", xdotool_available=False).available
    assert plan_gaze_target("x11", xdotool_available=None).available


@pytest.mark.parametrize("session", ["windows", "macos", "headless", "", "something-new"])
def test_every_other_session_abstains_with_a_reason_too(session) -> None:
    plan = plan_gaze_target(session)
    assert plan.basis is TargetBasis.NONE
    assert plan.reason, "an abstention with no reason is the silent no-op this exists to end"


# ---- the platform seam (no sys.platform branch) ------------------------------------


def test_the_os_fixed_bucket_comes_from_describe_host_not_from_sys_platform(monkeypatch) -> None:
    host = HostInfo(platform_name="darwin", os_name="macOS", os_version="15",
                    fixed_session_type="macos")
    monkeypatch.setattr("yazses.platform.factory.describe_host", lambda: host)
    plan = describe_gaze_target(GNOME_WAYLAND, xdotool_available=lambda: True)
    assert plan.session == "macos"


def test_an_unreadable_host_degrades_to_the_environment_instead_of_raising(monkeypatch) -> None:
    def broken():
        raise OSError("/etc/os-release unreadable")

    monkeypatch.setattr("yazses.platform.factory.describe_host", broken)
    assert describe_gaze_target(GNOME_WAYLAND).session == "wayland_gnome"


def test_xdotool_is_only_looked_for_on_x11() -> None:
    probes: list[str] = []

    def which() -> bool:
        probes.append("asked")
        return True

    describe_gaze_target(GNOME_WAYLAND, fixed_session=lambda: None, xdotool_available=which)
    assert probes == []
    describe_gaze_target({"XDG_SESSION_TYPE": "x11"}, fixed_session=lambda: None,
                         xdotool_available=which)
    assert probes == ["asked"]


# ---- the builders: no absolute position, no backend, no subprocess ----------------


@pytest.mark.parametrize(
    "env", [GNOME_WAYLAND, GNOME_WAYLAND_NO_SESSION_VAR], ids=["session-var", "no-session-var"]
)
def test_no_desktop_backend_is_built_on_wayland_even_though_xdotool_would_answer(
    monkeypatch, linux_host, xdotool_that_would_answer, env
) -> None:
    from yazses.gaze.desktop import build_desktop

    _session(monkeypatch, env)

    assert build_desktop() is None
    assert xdotool_that_would_answer == [], "the planner asked xdotool about a Wayland session"


@pytest.mark.parametrize(
    "env", [GNOME_WAYLAND, GNOME_WAYLAND_NO_SESSION_VAR], ids=["session-var", "no-session-var"]
)
def test_no_topology_is_read_from_xwayland(
    monkeypatch, linux_host, xdotool_that_would_answer, env
) -> None:
    """xrandr under XWayland reports one synthetic screen at scale 1 -- not the layout."""
    from yazses.gaze.display import build_topology_provider, current_context

    _session(monkeypatch, env)

    assert build_topology_provider() is None
    context = current_context(camera_id="0")
    assert context.topology.displays == ()  # unknown, never a guessed one-screen layout
    assert xdotool_that_would_answer == []


def test_x11_still_builds_both_backends(monkeypatch, linux_host, xdotool_that_would_answer) -> None:
    from yazses.gaze.desktop import XdotoolDesktop, build_desktop
    from yazses.gaze.display import XrandrTopology, build_topology_provider

    _session(monkeypatch, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"})

    assert isinstance(build_desktop(), XdotoolDesktop)
    assert isinstance(build_topology_provider(), XrandrTopology)


def test_the_reason_a_caller_prints_is_the_planners_sentence(monkeypatch, linux_host) -> None:
    from yazses.gaze.desktop import unavailable_reason

    _session(monkeypatch, GNOME_WAYLAND)
    text = unavailable_reason()
    assert WAYLAND_REASON in text and "X11" in text

    _session(monkeypatch, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"})
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    assert unavailable_reason() == ""


# ---- every consumer says it cannot ----------------------------------------------


def test_the_calibration_refusal_names_the_session_it_refused(monkeypatch, linux_host) -> None:
    from yazses.gaze.desktop import unavailable_reason

    _session(monkeypatch, GNOME_WAYLAND)
    blocked = calibration_blocker(
        enabled=True, desktop_ok=False, desktop_reason=unavailable_reason()
    )
    assert blocked is not None
    assert WAYLAND_REASON in blocked
    assert "cannot make this work" in blocked  # still tells them not to fetch 219 MB


def test_the_daemon_stays_dormant_on_wayland_and_logs_why(
    monkeypatch, linux_host, xdotool_that_would_answer, caplog
) -> None:
    """Hold-to-talk on a Wayland desktop with gaze switched on: no targeter, a stated reason."""
    from yazses.core.daemon import Daemon
    from yazses.platform import get_platform

    _session(monkeypatch, GNOME_WAYLAND_NO_SESSION_VAR)
    cfg = Config()
    cfg.gaze.enabled = True
    cfg.gaze.route_dictation = True
    daemon = Daemon(config=cfg, platform=get_platform())

    with caplog.at_level(logging.WARNING, logger="yazses.core.daemon"):
        targeter = daemon._build_gaze_targeter(cfg)

    assert targeter is None
    assert any(
        "global pointer position" in r.getMessage() and r.levelno == logging.WARNING
        for r in caplog.records
    ), [r.getMessage() for r in caplog.records]
    assert xdotool_that_would_answer == []


def _platform(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        paths=SimpleNamespace(config_file=tmp_path / "config.toml", data_dir=tmp_path)
    )


def test_gaze_status_prints_the_target_and_the_remedy_on_wayland(
    monkeypatch, tmp_path, linux_host, xdotool_that_would_answer
) -> None:
    _session(monkeypatch, GNOME_WAYLAND)
    cfg = dataclasses.replace(Config(), gaze=dataclasses.replace(GazeConfig(), enabled=True))
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path))
    monkeypatch.setattr("yazses.config.load_config", lambda _p: cfg)
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)  # no camera, no model

    result = CliRunner().invoke(cli.app, ["gaze", "status"])

    assert result.exit_code == 0, result.output
    assert "✗ gaze target: none" in result.output
    assert "global pointer position" in result.output
    assert "Look-to-pane is dormant on this session" in result.output
    assert "Next: log in to an X11 session" in result.output
    # The old advice sent a Wayland user to enable the feature and calibrate: both refuse.
    assert "yazses gaze calibrate" not in result.output
    assert xdotool_that_would_answer == []


def test_gaze_status_on_x11_names_the_target_and_still_says_ready(
    monkeypatch, tmp_path, linux_host
) -> None:
    _session(monkeypatch, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"})
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    cfg = dataclasses.replace(Config(), gaze=dataclasses.replace(GazeConfig(), enabled=True))
    monkeypatch.setattr(cli, "get_platform", lambda: _platform(tmp_path))
    monkeypatch.setattr("yazses.config.load_config", lambda _p: cfg)
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)

    result = CliRunner().invoke(cli.app, ["gaze", "status"])

    assert result.exit_code == 0, result.output
    assert "✓ gaze target: X11" in result.output


# ---- doctor / status / settings rows ----------------------------------------------


def _facts() -> HandsFreeFacts:
    return HandsFreeFacts(
        features_requested=("gaze",),
        calibration_validity="missing",
        calibration_reason="nothing has been calibrated on this machine yet",
    )


def test_the_row_says_none_with_the_reason_and_withdraws_the_calibrate_advice() -> None:
    facts = gaze_target_facts(
        _facts(), environ=GNOME_WAYLAND, fixed_session=lambda: None,
        xdotool_available=lambda: True,
    )
    rows = {row.label: row for row in health_rows(facts)}

    row = rows["Gaze target"]
    assert row.health.value != "ok"
    assert row.reason.startswith("none — ")
    assert "global pointer position" in row.reason
    assert "X11" in row.remedy
    # "run `yazses gaze calibrate`" would send the user to a command that refuses here.
    assert "Gaze calibration" not in rows
    assert ("Gaze target", "WARN") == next(
        (label, status) for label, status, _ in doctor_rows(facts) if label == "Gaze target"
    )


def test_on_x11_the_row_is_ok_and_the_calibration_row_stays() -> None:
    facts = gaze_target_facts(
        _facts(), environ={"XDG_SESSION_TYPE": "x11"}, fixed_session=lambda: None,
        xdotool_available=lambda: True,
    )
    rows = {row.label: row for row in health_rows(facts)}
    assert rows["Gaze target"].health.value == "ok"
    assert "Gaze calibration" in rows


def test_no_row_unless_gaze_was_asked_for() -> None:
    facts = gaze_target_facts(
        HandsFreeFacts(features_requested=("headpointer",)), environ=GNOME_WAYLAND,
        fixed_session=lambda: None,
    )
    assert facts.gaze_target_available is None
    assert "Gaze target" not in {row.label for row in health_rows(facts)}


def test_an_unasked_question_is_not_a_clean_bill_of_health() -> None:
    """`None` (never classified) must print nothing -- not an OK row, not a calibrate nudge."""
    rows = {row.label for row in health_rows(_facts())}
    assert "Gaze target" not in rows
    assert "Gaze calibration" in rows


def test_the_answer_survives_the_daemon_status_wire_and_prints_in_status() -> None:
    facts = gaze_target_facts(
        _facts(), environ=GNOME_WAYLAND, fixed_session=lambda: None,
        xdotool_available=lambda: True,
    )
    payload = as_payload(facts)
    assert payload is not None
    assert payload["gaze_target_available"] is False

    rebuilt = facts_from_payload(payload)
    assert rebuilt is not None and rebuilt.gaze_target_available is False
    text = "\n".join(render_status_lines(payload))
    assert "gaze target: none" in text and "global pointer position" in text


def test_an_older_daemon_that_sends_no_target_keys_reads_as_not_asked() -> None:
    rebuilt = facts_from_payload({"features_requested": ["gaze"]})
    assert rebuilt is not None
    assert rebuilt.gaze_target_available is None
    assert "Gaze target" not in {row.label for row in health_rows(rebuilt)}


def test_a_probe_that_raises_leaves_the_facts_untouched(monkeypatch) -> None:
    import yazses.gaze.target_semantics as sem

    def boom(*a, **k):
        raise RuntimeError("no")

    monkeypatch.setattr(sem, "describe_gaze_target", boom)
    facts = _facts()
    assert gaze_target_facts(facts) is facts
