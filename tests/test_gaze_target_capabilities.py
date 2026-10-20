"""The Wayland gaze-target capability model -- EYE-WAYLAND-001 (#418).

`gaze/target_capabilities.py` holds the platform matrix: per session, what an ordinary
client gets for screen position, other windows' geometry, focus, and (separately) pointer
injection. `gaze/target_semantics.py` derives what gaze may honestly do from it. These tests
pin the four things that would otherwise drift silently:

* **the rule** -- a target needs all three target capabilities as plain ``YES``; a
  compositor-specific or consent-only path never counts, and pointer injection is never
  read, so a granted Remote Desktop permission can never manufacture a target;
* **the citations** -- every source id the matrix uses exists, every source is cited in the
  design spec, and none is a file download (AGENTS.md rule 10);
* **the fallback** -- where no target can exist, "close this" is refused with feedback and
  never sent to the focused window, whatever ``refuse_destructive_fallback`` says;
* **the surfaces** -- `gaze status`, the doctor/status row and the daemon wire carry the
  capability line.

No compositor, D-Bus or subprocess is touched: every session is a literal environment.
"""
from __future__ import annotations

import dataclasses
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

import yazses.cli as cli
from yazses.config import Config, GazeConfig
from yazses.eyeeval.schema import SESSION_TYPES
from yazses.gaze import target_semantics as sem
from yazses.gaze.target_capabilities import (
    SESSION_CAPABILITIES,
    SOURCES,
    TARGET_CAPABILITIES,
    Capability,
    CapabilityFact,
    Support,
    capabilities_for,
    gaze_target_supported,
    summarize,
)
from yazses.gaze.target_semantics import (
    DestructiveDeixis,
    DictationRoute,
    TargetBasis,
    plan_gaze_target,
)
from yazses.handsfree.observability import (
    HandsFreeFacts,
    as_payload,
    facts_from_payload,
    health_rows,
)
from yazses.handsfree.probe import gaze_target_facts
from yazses.platform.base import HostInfo

ROOT = Path(__file__).resolve().parent.parent
SPEC = ROOT / "design" / "specs" / "eye-wayland-gaze-target.md"

WAYLAND = ("wayland_gnome", "wayland_kde", "wayland_other")
GNOME_WAYLAND = {
    "XDG_SESSION_TYPE": "wayland",
    "XDG_CURRENT_DESKTOP": "ubuntu:GNOME",
    "WAYLAND_DISPLAY": "wayland-0",
    "DISPLAY": ":0",
}


def _with(facts: tuple[CapabilityFact, ...], cap: Capability, support: Support):
    return tuple(dataclasses.replace(f, support=support) if f.capability is cap else f
                 for f in facts)


# ---- the matrix is complete and well-formed ----------------------------------------


@pytest.mark.parametrize("session", sorted(SESSION_CAPABILITIES))
def test_every_assessed_session_answers_each_capability_exactly_once(session) -> None:
    caps = [f.capability for f in SESSION_CAPABILITIES[session]]
    assert sorted(caps) == sorted(Capability)


def test_the_matrix_covers_every_linux_session_bucket_the_evaluation_schema_knows() -> None:
    # windows/macos are outside #418 and say so (empty row), everything else is assessed.
    assert set(SESSION_CAPABILITIES) == set(SESSION_TYPES) - {"windows", "macos"}
    assert capabilities_for("windows") == () and capabilities_for("macos") == ()


def test_pointer_injection_is_not_one_of_the_target_capabilities() -> None:
    assert Capability.POINTER_INJECTION not in TARGET_CAPABILITIES
    assert len(TARGET_CAPABILITIES) == 3


# ---- the derivation rule ------------------------------------------------------------


def test_only_x11_supports_a_gaze_target() -> None:
    supported = {s for s, facts in SESSION_CAPABILITIES.items() if gaze_target_supported(facts)}
    assert supported == {"x11"}


@pytest.mark.parametrize("session", sorted(SESSION_CAPABILITIES))
@pytest.mark.parametrize("support", list(Support))
def test_pointer_injection_never_changes_the_answer(session, support) -> None:
    facts = SESSION_CAPABILITIES[session]
    before = gaze_target_supported(facts)
    assert gaze_target_supported(_with(facts, Capability.POINTER_INJECTION, support)) is before


@pytest.mark.parametrize("cap", TARGET_CAPABILITIES)
@pytest.mark.parametrize("support", [Support.COMPOSITOR_SPECIFIC, Support.CONSENT, Support.NO])
def test_a_compositor_specific_or_consent_path_never_makes_a_target(cap, support) -> None:
    """#418 AC3: no compositor-private path is a default requirement -- by construction."""
    assert not gaze_target_supported(_with(SESSION_CAPABILITIES["x11"], cap, support))


def test_kde_offers_all_three_but_only_compositor_specifically_so_there_is_no_target() -> None:
    row = {f.capability: f.support for f in SESSION_CAPABILITIES["wayland_kde"]}
    assert all(row[c] is Support.COMPOSITOR_SPECIFIC for c in TARGET_CAPABILITIES)
    assert not gaze_target_supported(SESSION_CAPABILITIES["wayland_kde"])


@pytest.mark.parametrize("session", WAYLAND)
def test_on_wayland_the_pointer_comes_through_a_portal_and_no_target_capability_is_plain(
    session,
) -> None:
    row = {f.capability: f.support for f in SESSION_CAPABILITIES[session]}
    assert row[Capability.POINTER_INJECTION] is Support.CONSENT
    assert all(row[c] is not Support.YES for c in TARGET_CAPABILITIES)


def test_an_unassessed_session_supports_nothing() -> None:
    assert not gaze_target_supported(())
    assert capabilities_for("") == () and capabilities_for("no-such-session") == ()


# ---- citations ----------------------------------------------------------------------


def test_every_source_a_row_cites_exists_and_every_source_is_cited_by_a_row() -> None:
    used = {s for facts in SESSION_CAPABILITIES.values() for f in facts for s in f.sources}
    assert used <= set(SOURCES), used - set(SOURCES)
    assert set(SOURCES) <= used, set(SOURCES) - used


@pytest.mark.parametrize("session", sorted(set(SESSION_CAPABILITIES) - {"headless"}))
def test_every_desktop_claim_carries_a_source(session) -> None:
    assert all(f.sources for f in SESSION_CAPABILITIES[session])


def test_every_source_is_a_landing_page_cited_by_id_and_url_in_the_design_spec() -> None:
    text = SPEC.read_text(encoding="utf-8")
    assert SOURCES, "an empty source table would pass every loop below"
    for sid, (title, url) in SOURCES.items():
        assert title
        assert url.startswith("https://"), url
        assert not re.search(r"\.pdf($|[?#])", url, re.I), url
        assert f"[{sid}]" in text, sid
        assert url in text, url


# ---- what gaze may do: the plan -----------------------------------------------------


@pytest.mark.parametrize("session", [*WAYLAND, "headless", "windows", "macos"])
def test_without_a_target_dictation_stays_focused_and_destructive_deixis_is_refused(
    session,
) -> None:
    plan = plan_gaze_target(session, xdotool_available=True)
    assert plan.basis is TargetBasis.NONE
    assert plan.dictation_route is DictationRoute.FOCUSED_WINDOW
    assert plan.destructive_deixis is DestructiveDeixis.REFUSE
    assert plan.capabilities == capabilities_for(session)


def test_x11_routes_to_the_gazed_window_and_leaves_destructive_actions_to_config() -> None:
    plan = plan_gaze_target("x11", xdotool_available=True)
    assert plan.dictation_route is DictationRoute.GAZED_WINDOW
    assert plan.destructive_deixis is DestructiveDeixis.BY_CONFIG
    assert plan.capabilities == SESSION_CAPABILITIES["x11"]


def test_x11_without_xdotool_refuses_like_wayland_but_keeps_its_capability_row() -> None:
    plan = plan_gaze_target("x11", xdotool_available=False)
    assert plan.destructive_deixis is DestructiveDeixis.REFUSE
    assert plan.capabilities == SESSION_CAPABILITIES["x11"]


def test_the_summary_prints_pointer_injection_last_and_labelled_separate() -> None:
    line = plan_gaze_target("wayland_gnome").capability_summary
    parts = line.split("; ")
    assert parts[0] == "screen position: no"
    assert parts[-1] == "pointer injection (separate, not a target): with permission"
    assert "other windows' geometry: compositor-specific only" in parts
    assert summarize(()) == ""
    assert plan_gaze_target("windows").capability_summary == ""


# ---- surfaces -----------------------------------------------------------------------


def _facts() -> HandsFreeFacts:
    return HandsFreeFacts(features_requested=("gaze",))


def test_the_doctor_row_carries_the_capability_line_and_it_survives_the_wire() -> None:
    facts = gaze_target_facts(_facts(), environ=GNOME_WAYLAND, fixed_session=lambda: None,
                              xdotool_available=lambda: True)
    assert facts.gaze_target_capabilities.startswith("screen position: no")
    row = {r.label: r for r in health_rows(facts)}["Gaze target"]
    assert row.reason.startswith("none — ")
    assert "pointer injection (separate, not a target)" in row.reason

    rebuilt = facts_from_payload(as_payload(facts))
    assert rebuilt is not None
    assert rebuilt.gaze_target_capabilities == facts.gaze_target_capabilities


def test_an_older_daemon_without_the_capability_key_prints_the_row_without_it() -> None:
    rebuilt = facts_from_payload({
        "features_requested": ["gaze"], "gaze_target_available": False,
        "gaze_target_reason": "some reason",
    })
    assert rebuilt is not None and rebuilt.gaze_target_capabilities == ""
    row = {r.label: r for r in health_rows(rebuilt)}["Gaze target"]
    assert row.reason == "none — some reason"


@pytest.fixture
def linux_host(monkeypatch):
    host = HostInfo(platform_name="linux", os_name="Ubuntu", os_version="24.04")
    monkeypatch.setattr("yazses.platform.factory.describe_host", lambda: host)
    return host


def _session(monkeypatch, env: dict[str, str]) -> None:
    for key in ("XDG_SESSION_TYPE", "XDG_CURRENT_DESKTOP", "WAYLAND_DISPLAY", "DISPLAY"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def test_gaze_status_prints_the_capabilities_and_the_refusal_on_wayland(
    monkeypatch, tmp_path, linux_host
) -> None:
    _session(monkeypatch, GNOME_WAYLAND)
    monkeypatch.setattr("shutil.which", lambda name: None)
    cfg = dataclasses.replace(Config(), gaze=dataclasses.replace(GazeConfig(), enabled=True))
    platform = SimpleNamespace(
        paths=SimpleNamespace(config_file=tmp_path / "config.toml", data_dir=tmp_path)
    )
    monkeypatch.setattr(cli, "get_platform", lambda: platform)
    monkeypatch.setattr("yazses.config.load_config", lambda _p: cfg)
    monkeypatch.setattr("yazses.gaze.factory.build_gaze", lambda _cfg: None)

    result = CliRunner().invoke(cli.app, ["gaze", "status"])

    assert result.exit_code == 0, result.output
    assert "capabilities: screen position: no;" in result.output
    assert "pointer injection (separate, not a target): with permission" in result.output
    assert "is refused here, never sent to the focused window" in result.output


# ---- the daemon: a deixis phrase where no target can exist --------------------------


def _daemon(monkeypatch, *, session: str, enabled: bool = True, **gaze):
    from yazses.core.daemon import Daemon
    from yazses.platform.factory import get_platform

    monkeypatch.setattr(sem, "describe_gaze_target",
                        lambda *a, **k: plan_gaze_target(session, xdotool_available=True))
    cfg = dataclasses.replace(
        Config(), gaze=dataclasses.replace(GazeConfig(), enabled=enabled, deixis=True, **gaze)
    )
    d = Daemon(config=cfg, platform=get_platform())
    d._gaze_targeter = None  # never built off X11
    return d


@pytest.mark.parametrize("session", WAYLAND)
@pytest.mark.parametrize("refuse_fallback", [False, True])
def test_close_this_on_wayland_is_consumed_refused_and_explained(
    monkeypatch, mocker, session, refuse_fallback
) -> None:
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(monkeypatch, session=session, refuse_destructive_fallback=refuse_fallback)
    event: dict = {}

    assert d._try_deixis("close this", event) is True

    assert event["discard_reason"] == "deixis_no_gaze_target"
    assert event["intent_action"] == "close"
    title, body = notify.call_args.args
    assert title == "Did not close anything"
    assert "Wayland" in body


def test_focus_that_on_wayland_is_refused_too(monkeypatch, mocker) -> None:
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(monkeypatch, session="wayland_kde")
    event: dict = {}
    assert d._try_deixis("focus that window", event) is True
    assert event["discard_reason"] == "deixis_no_gaze_target"
    assert notify.call_args.args[0] == "Did not focus anything"


def test_with_gaze_off_a_deixis_phrase_is_left_to_the_other_handlers(monkeypatch, mocker) -> None:
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(monkeypatch, session="wayland_gnome", enabled=False)
    assert d._try_deixis("close this", {}) is False
    notify.assert_not_called()


def test_an_ordinary_phrase_is_never_consumed_on_wayland(monkeypatch, mocker) -> None:
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(monkeypatch, session="wayland_gnome")
    assert d._try_deixis("close the door behind you", {}) is False
    notify.assert_not_called()


def test_on_x11_a_missing_targeter_is_not_an_impossibility(monkeypatch, mocker) -> None:
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(monkeypatch, session="x11")
    assert d._try_deixis("close this", {}) is False
    notify.assert_not_called()


def test_a_planner_that_raises_falls_back_to_not_consumed(monkeypatch, mocker) -> None:
    notify = mocker.patch("yazses.system.notify.notify")
    d = _daemon(monkeypatch, session="wayland_gnome")

    def boom(*_a, **_k):
        raise RuntimeError("host unreadable")

    monkeypatch.setattr(sem, "describe_gaze_target", boom)
    assert d._try_deixis("close this", {}) is False
    notify.assert_not_called()
