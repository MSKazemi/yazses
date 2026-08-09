"""Tests for the pure provisioning planner in yazses.system.setup."""

import os

import pytest

from yazses.system import setup

# `preflight_hints` short-circuits to [] on non-POSIX platforms (`os.name != "posix"`,
# i.e. Windows), since `yazses setup` provisions POSIX runtime prerequisites. Tests that
# assert a hint is produced therefore can't run on Windows; they still run on Linux and
# macOS (both POSIX).
posix_only = pytest.mark.skipif(
    os.name != "posix",
    reason="preflight_hints returns [] on non-POSIX platforms (Windows)",
)


def _which(available):
    return lambda cmd: f"/usr/bin/{cmd}" if cmd in available else None


ALL_TOOLS = ["xdotool", "ydotool", "wtype", "xclip", "wl-copy"]


def test_detect_session():
    assert setup.detect_session({"WAYLAND_DISPLAY": "wayland-0"}) == "wayland"
    assert setup.detect_session({"DISPLAY": ":0"}) == "x11"
    assert setup.detect_session({}) == "headless"


def test_fully_provisioned_machine_is_noop_on_x11():
    plan = setup.build_plan(
        {"DISPLAY": ":0"},
        which=_which(ALL_TOOLS),
        portaudio_present=lambda: True,
        user="u",
        user_in_input_group=lambda u: True,
    )
    assert plan.session == "x11"
    assert plan.apt_packages == []
    assert plan.add_to_input_group is False
    assert plan.setup_ydotoold is False
    assert plan.is_noop


def test_bare_machine_needs_everything():
    plan = setup.build_plan(
        {"WAYLAND_DISPLAY": "wayland-0"},
        which=_which([]),  # no tools installed
        portaudio_present=lambda: False,
        user="u",
        user_in_input_group=lambda u: False,
    )
    assert "libportaudio2" in plan.apt_packages
    assert "ydotool" in plan.apt_packages and "wtype" in plan.apt_packages
    assert "wl-clipboard" in plan.apt_packages  # mapped from missing wl-copy
    assert plan.add_to_input_group is True
    assert plan.setup_ydotoold is True  # Wayland
    assert not plan.is_noop


def test_portaudio_detected_via_loader_not_binary():
    # libportaudio2 has no binary; presence is decided by portaudio_present()
    plan = setup.build_plan(
        {"DISPLAY": ":0"},
        which=_which(ALL_TOOLS),
        portaudio_present=lambda: False,
        user="u",
        user_in_input_group=lambda u: True,
    )
    assert plan.apt_packages == ["libportaudio2"]


def test_wl_clipboard_package_maps_from_wl_copy_binary():
    plan = setup.build_plan(
        {"WAYLAND_DISPLAY": "wayland-0"},
        which=_which(["xdotool", "ydotool", "wtype", "xclip"]),  # wl-copy missing
        portaudio_present=lambda: True,
        user="u",
        user_in_input_group=lambda u: True,
    )
    assert plan.apt_packages == ["wl-clipboard"]


def test_x11_session_skips_ydotoold():
    plan = setup.build_plan(
        {"DISPLAY": ":0"},
        which=_which([]),
        portaudio_present=lambda: True,
        user="u",
        user_in_input_group=lambda u: True,
    )
    assert plan.setup_ydotoold is False


def test_apply_noop_plan_does_nothing():
    calls = []
    plan = setup.SetupPlan(session="x11")
    assert plan.is_noop
    ok = setup.apply_plan(plan, runner=lambda *a, **k: calls.append(a), echo=lambda *_: None)
    assert ok is True
    assert calls == []


# ── preflight_hints / input_group_pending_relogin ──────────────────────────────

def _fully_provisioned_plan():
    """A plan on a machine where nothing is missing."""
    return setup.build_plan(
        {"DISPLAY": ":0"},
        which=_which(ALL_TOOLS),
        portaudio_present=lambda: True,
        user="u",
        user_in_input_group=lambda u: True,
    )


@posix_only
def test_preflight_hint_when_packages_missing():
    plan = setup.build_plan(
        {"DISPLAY": ":0"},
        which=_which([]),  # every injector binary missing
        portaudio_present=lambda: False,
        user="u",
        user_in_input_group=lambda u: True,
    )
    hints = setup.preflight_hints(plan=plan, pending_relogin=False)
    assert len(hints) == 1
    assert "yazses setup" in hints[0]
    assert "Missing prerequisites" in hints[0]


@posix_only
def test_preflight_hint_when_relogin_pending():
    # Fully provisioned, but the group change hasn't taken effect in this session.
    plan = _fully_provisioned_plan()
    hints = setup.preflight_hints(plan=plan, pending_relogin=True)
    assert len(hints) == 1
    assert "log out" in hints[0].lower()
    assert "sg input" in hints[0]


def test_preflight_no_hints_when_fully_provisioned():
    plan = _fully_provisioned_plan()
    assert setup.preflight_hints(plan=plan, pending_relogin=False) == []


class _Rc:
    def __init__(self, returncode):
        self.returncode = returncode


def _runner(returncode):
    return lambda *a, **k: _Rc(returncode)


def test_snap_mic_pending_false_outside_snap():
    # Not the snap build (apt/pipx grant mic access directly) — never prompt.
    assert setup.snap_mic_pending({}, runner=_runner(1)) is False
    assert setup.snap_mic_pending({"SNAP_NAME": "somethingelse"}, runner=_runner(1)) is False


def test_snap_mic_pending_true_when_interface_unconnected():
    env = {"SNAP_NAME": "yazses"}
    assert setup.snap_mic_pending(env, runner=_runner(1)) is True


def test_snap_mic_pending_false_when_interface_connected():
    env = {"SNAP_NAME": "yazses"}
    assert setup.snap_mic_pending(env, runner=_runner(0)) is False


def test_snap_mic_pending_false_when_snapctl_missing():
    def _raise(*a, **k):
        raise FileNotFoundError("snapctl")

    assert setup.snap_mic_pending({"SNAP_NAME": "yazses"}, runner=_raise) is False


@posix_only
def test_preflight_hint_when_snap_mic_unconnected(monkeypatch):
    # In the snap with audio-record not connected, surface the connect step.
    monkeypatch.setattr(setup, "snap_mic_pending", lambda env=None: True)
    monkeypatch.setattr(setup, "snap_rawinput_pending", lambda env=None: False)
    plan = _fully_provisioned_plan()
    hints = setup.preflight_hints(plan=plan, pending_relogin=False)
    assert any("snap connect yazses:audio-record" in h for h in hints)


# --- raw-input: the other interface a fresh snap install has to be told about --


def test_snap_rawinput_pending_false_outside_snap():
    assert setup.snap_rawinput_pending({}, runner=_runner(1)) is False
    assert setup.snap_rawinput_pending({"SNAP_NAME": "other"}, runner=_runner(1)) is False


def test_snap_rawinput_pending_true_when_interface_unconnected():
    assert setup.snap_rawinput_pending({"SNAP_NAME": "yazses"}, runner=_runner(1)) is True


def test_snap_rawinput_pending_false_when_interface_connected():
    assert setup.snap_rawinput_pending({"SNAP_NAME": "yazses"}, runner=_runner(0)) is False


def test_snap_rawinput_pending_false_when_snapctl_missing():
    def _raise(*a, **k):
        raise FileNotFoundError("snapctl")

    assert setup.snap_rawinput_pending({"SNAP_NAME": "yazses"}, runner=_raise) is False


def test_each_interface_check_asks_about_its_own_interface():
    """Regression guard for the shared helper: both checks must not collapse
    onto one interface, or a connected mic would silence the hotkey warning."""
    asked: list[str] = []

    def spy(argv, **_k):
        asked.append(argv[-1])
        return _Rc(1)

    env = {"SNAP_NAME": "yazses"}
    setup.snap_mic_pending(env, runner=spy)
    setup.snap_rawinput_pending(env, runner=spy)
    assert asked == ["audio-record", "raw-input"]


@posix_only
def test_preflight_hint_when_snap_rawinput_unconnected(monkeypatch):
    """Without raw-input the daemon starts, looks healthy, and never sees the
    hotkey — the most confusing way a fresh snap install can fail."""
    monkeypatch.setattr(setup, "snap_mic_pending", lambda env=None: False)
    monkeypatch.setattr(setup, "snap_rawinput_pending", lambda env=None: True)
    plan = _fully_provisioned_plan()
    hints = setup.preflight_hints(plan=plan, pending_relogin=False)
    assert any("snap connect yazses:raw-input" in h for h in hints)


@posix_only
def test_a_fresh_snap_install_is_told_about_both(monkeypatch):
    monkeypatch.setattr(setup, "snap_mic_pending", lambda env=None: True)
    monkeypatch.setattr(setup, "snap_rawinput_pending", lambda env=None: True)
    plan = _fully_provisioned_plan()
    hints = setup.preflight_hints(plan=plan, pending_relogin=False)
    assert any("yazses:audio-record" in h for h in hints)
    assert any("yazses:raw-input" in h for h in hints)


@posix_only
def test_a_fully_connected_snap_is_told_nothing(monkeypatch):
    monkeypatch.setattr(setup, "snap_mic_pending", lambda env=None: False)
    monkeypatch.setattr(setup, "snap_rawinput_pending", lambda env=None: False)
    plan = _fully_provisioned_plan()
    hints = setup.preflight_hints(plan=plan, pending_relogin=False)
    assert not any("snap connect" in h for h in hints)


@posix_only
def test_missing_packages_take_priority_over_relogin_hint():
    # If packages are also missing, surface the actionable `yazses setup` hint,
    # not the (secondary) re-login one.
    plan = setup.build_plan(
        {"DISPLAY": ":0"},
        which=_which([]),
        portaudio_present=lambda: False,
        user="u",
        user_in_input_group=lambda u: True,
    )
    hints = setup.preflight_hints(plan=plan, pending_relogin=True)
    assert len(hints) == 1
    assert "yazses setup" in hints[0]
